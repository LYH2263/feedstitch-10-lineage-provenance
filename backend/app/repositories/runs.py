from __future__ import annotations

import json
import sqlite3
from typing import Any


def create_run(
    conn: sqlite3.Connection,
    source_id: int,
    mode: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO runs(source_id, mode, status, parsed_count, upserted_count,
                         conflict_count, skipped_count, report_json, created_at)
        VALUES (?,?, 'running', 0, 0, 0, 0, '{}', datetime('now'))
        """,
        (source_id, mode),
    )
    return int(cur.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    status: str,
    parsed: int,
    upserted: int,
    conflicts: int,
    skipped: int,
    report: dict[str, Any],
) -> None:
    conn.execute(
        """
        UPDATE runs SET status=?, parsed_count=?, upserted_count=?, conflict_count=?,
            skipped_count=?, report_json=? WHERE id=?
        """,
        (
            status,
            parsed,
            upserted,
            conflicts,
            skipped,
            json.dumps(report, ensure_ascii=False),
            run_id,
        ),
    )


def list_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT r.id, r.source_id, s.name AS source_name, r.mode, r.status,
               r.parsed_count, r.upserted_count, r.conflict_count, r.skipped_count,
               r.report_json, r.created_at
        FROM runs r JOIN sources s ON s.id = r.source_id
        ORDER BY r.id DESC
        """
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["report"] = json.loads(d.pop("report_json") or "{}")
        out.append(d)
    return out


def get_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT r.id, r.source_id, s.name AS source_name, r.mode, r.status,
               r.parsed_count, r.upserted_count, r.conflict_count, r.skipped_count,
               r.report_json, r.created_at
        FROM runs r JOIN sources s ON s.id = r.source_id
        WHERE r.id = ?
        """,
        (run_id,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["report"] = json.loads(d.pop("report_json") or "{}")
    return d


def insert_staging(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    source_id: int,
    item: dict[str, Any],
    disposition: str,
) -> None:
    conn.execute(
        """
        INSERT INTO staging_rows(
            run_id, source_id, business_key, event_ts, source_revision,
            payload_json, disposition
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (
            run_id,
            source_id,
            item["business_key"],
            item["event_ts"],
            item["source_revision"],
            json.dumps(item["payload"], ensure_ascii=False),
            disposition,
        ),
    )


def list_staging(conn: sqlite3.Connection, run_id: int | None = None) -> list[dict[str, Any]]:
    if run_id is None:
        rows = conn.execute(
            """
            SELECT id, run_id, source_id, business_key, event_ts, source_revision,
                   payload_json, disposition
            FROM staging_rows ORDER BY id DESC LIMIT 200
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, run_id, source_id, business_key, event_ts, source_revision,
                   payload_json, disposition
            FROM staging_rows WHERE run_id = ? ORDER BY id
            """,
            (run_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d.pop("payload_json"))
        out.append(d)
    return out


def insert_conflict(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    source_id: int,
    item: dict[str, Any],
    existing_payload: dict[str, Any],
    reason: str,
    existing_source_id: int | None = None,
    existing_run_id: int | None = None,
    existing_lineage_id: int | None = None,
    existing_event_ts: str | None = None,
    existing_revision: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO conflicts(
            run_id, source_id, business_key, existing_payload, incoming_payload,
            reason, created_at, incoming_revision, incoming_event_ts,
            existing_source_id, existing_revision, existing_event_ts,
            existing_run_id, existing_lineage_id
        ) VALUES (?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'),?,?,?,?,?,?,?)
        """,
        (
            run_id,
            source_id,
            item["business_key"],
            json.dumps(existing_payload, ensure_ascii=False),
            json.dumps(item["payload"], ensure_ascii=False),
            reason,
            int(item["source_revision"]),
            item["event_ts"],
            existing_source_id,
            existing_revision,
            existing_event_ts,
            existing_run_id,
            existing_lineage_id,
        ),
    )


def list_conflicts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT c.id, c.run_id, c.source_id, s.name AS source_name,
               c.business_key, c.existing_payload, c.incoming_payload,
               c.reason, c.created_at,
               c.incoming_revision, c.incoming_event_ts,
               c.existing_source_id, es.name AS existing_source_name,
               c.existing_revision, c.existing_event_ts,
               c.existing_run_id, c.existing_lineage_id
        FROM conflicts c
        LEFT JOIN sources s ON s.id = c.source_id
        LEFT JOIN sources es ON es.id = c.existing_source_id
        ORDER BY c.id DESC
        """
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["existing"] = json.loads(d.pop("existing_payload"))
        d["incoming"] = json.loads(d.pop("incoming_payload"))
        out.append(d)
    return out
