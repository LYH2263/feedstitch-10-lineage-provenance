"""Row-level lineage provenance for canonical writes.

Only rows that were actually written to ``canonical_items`` are recorded in
``lineage_events``.  Quarantined feed rows stay in ``conflicts`` and are
exposed by :func:`build_chain` as ``quarantined`` chain nodes, never as
successful write events.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable

APPLIED = "applied"
QUARANTINED = "quarantined"


def record_write(
    conn: sqlite3.Connection,
    *,
    item: dict[str, Any],
    source_id: int,
    run_id: int,
    action: str,
) -> int:
    """Append one successful write/update to the lineage chain and return its id."""
    key = item["business_key"]
    previous = conn.execute(
        "SELECT id FROM lineage_events WHERE business_key = ? ORDER BY id DESC LIMIT 1",
        (key,),
    ).fetchone()
    previous_id = int(previous["id"]) if previous else None
    cur = conn.execute(
        """
        INSERT INTO lineage_events(
            business_key, source_id, run_id, source_revision, event_ts,
            written_at, action, payload_json, previous_lineage_id
        ) VALUES (?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'),?,?,?)
        """,
        (
            key,
            source_id,
            run_id,
            int(item["source_revision"]),
            item["event_ts"],
            action,
            json.dumps(item["payload"], ensure_ascii=False),
            previous_id,
        ),
    )
    return int(cur.lastrowid)


def count_run(conn: sqlite3.Connection, run_id: int) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) c FROM lineage_events WHERE run_id = ?", (run_id,)
        ).fetchone()["c"]
    )


def distinct_keys_run(conn: sqlite3.Connection, run_id: int) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(DISTINCT business_key) c FROM lineage_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()["c"]
    )


def reconciliation(conn: sqlite3.Connection, run_id: int, upserted: int) -> dict[str, Any]:
    """Explain a run's write count with its own successful lineage rows."""
    written = count_run(conn, run_id)
    keys = distinct_keys_run(conn, run_id)
    pointer_ok = int(
        conn.execute(
            """
            SELECT COUNT(*) c
            FROM canonical_items c
            JOIN (
                SELECT business_key, MAX(id) AS latest_id
                FROM lineage_events
                WHERE run_id = ?
                GROUP BY business_key
            ) l ON l.business_key = c.business_key
            WHERE c.run_id = ? AND c.lineage_id = l.latest_id
            """,
            (run_id, run_id),
        ).fetchone()["c"]
    )
    return {
        "lineage_written_count": written,
        "lineage_distinct_keys": keys,
        "lineage_reconciles": written == upserted,
        "canonical_lineage_pointers_ok": pointer_ok == keys,
    }


def _canonical_view(conn: sqlite3.Connection, business_key: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT c.id, c.business_key, c.title, c.price, c.category, c.source_id,
               s.name AS source_name, c.event_ts, c.source_revision,
               c.run_id, c.lineage_id, c.payload_json, c.updated_at
        FROM canonical_items c
        LEFT JOIN sources s ON s.id = c.source_id
        WHERE c.business_key = ?
        """,
        (business_key,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["payload"] = json.loads(d.pop("payload_json"))
    return d


def _applied_events(conn: sqlite3.Connection, business_key: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT l.id, l.business_key, l.source_id, s.name AS source_name,
               l.run_id, l.source_revision, l.event_ts, l.written_at,
               l.action, l.payload_json, l.previous_lineage_id
        FROM lineage_events l
        LEFT JOIN sources s ON s.id = l.source_id
        WHERE l.business_key = ?
        ORDER BY l.written_at, l.id
        """,
        (business_key,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        d["payload"] = json.loads(d.pop("payload_json"))
        d["kind"] = APPLIED
        d["applied"] = True
        out.append(d)
    return out


def _quarantined_attempts(conn: sqlite3.Connection, business_key: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT c.id, c.run_id, c.source_id, s.name AS source_name,
               c.reason, c.created_at,
               c.incoming_revision, c.incoming_event_ts,
               c.existing_source_id, es.name AS existing_source_name,
               c.existing_revision, c.existing_event_ts,
               c.existing_run_id, c.existing_lineage_id,
               c.existing_payload, c.incoming_payload
        FROM conflicts c
        LEFT JOIN sources s ON s.id = c.source_id
        LEFT JOIN sources es ON es.id = c.existing_source_id
        WHERE c.business_key = ?
        ORDER BY c.created_at, c.id
        """,
        (business_key,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        payload = json.loads(d.pop("incoming_payload"))
        d["existing_payload"] = json.loads(d.pop("existing_payload"))
        # Older rows may only carry the values inside the payload snapshot.
        if d["incoming_revision"] is None:
            d["incoming_revision"] = payload.get("source_revision")
        if d["incoming_event_ts"] is None:
            d["incoming_event_ts"] = payload.get("event_ts")
        d["payload"] = payload
        d["event_ts"] = d["incoming_event_ts"]
        d["source_revision"] = d["incoming_revision"]
        d["written_at"] = d["created_at"]
        d["kind"] = QUARANTINED
        d["applied"] = False
        out.append(d)
    return out


def _sort_chain(nodes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(node: dict[str, Any]) -> tuple[str, int, int]:
        kind_rank = 0 if node["kind"] == APPLIED else 1
        node_id = int(node.get("id") or 0)
        return (str(node.get("written_at") or ""), kind_rank, node_id)

    return sorted(nodes, key=key)


def build_chain(conn: sqlite3.Connection, business_key: str) -> dict[str, Any]:
    """Return applied write events plus quarantined attempts for one business key."""
    canonical = _canonical_view(conn, business_key)
    applied = _applied_events(conn, business_key)
    attempts = _quarantined_attempts(conn, business_key)
    latest_id = applied[-1]["id"] if applied else None
    for event in applied:
        event["is_latest"] = event["id"] == latest_id
        event["is_canonical_current"] = bool(
            canonical and canonical["lineage_id"] == event["id"]
        )

    return {
        "business_key": business_key,
        "exists": bool(canonical or applied or attempts),
        "canonical": canonical,
        "events": applied,
        "attempts": attempts,
        "chain": _sort_chain([*applied, *attempts]),
        "applied_count": len(applied),
        "quarantined_count": len(attempts),
        "latest_applied_lineage_id": latest_id,
        "canonical_points_to_latest": bool(
            canonical and latest_id is not None and canonical["lineage_id"] == latest_id
        ),
    }


def summary(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "lineage_event_count": int(
            conn.execute("SELECT COUNT(*) c FROM lineage_events").fetchone()["c"]
        ),
        "canonical_count": int(
            conn.execute("SELECT COUNT(*) c FROM canonical_items").fetchone()["c"]
        ),
        "canonical_with_lineage": int(
            conn.execute(
                "SELECT COUNT(*) c FROM canonical_items WHERE lineage_id IS NOT NULL"
            ).fetchone()["c"]
        ),
        "quarantined_count": int(
            conn.execute("SELECT COUNT(*) c FROM conflicts").fetchone()["c"]
        ),
    }
