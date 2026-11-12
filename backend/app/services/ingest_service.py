from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import FIXTURES_DIR
from app.db import connect
from app.engines.merge_rules import decide_merge, eligible_for_incremental
from app.engines.parse_feed import parse_fixture
from app.modules import lineage_provenance as lineage
from app.repositories import canonical as canon_repo
from app.repositories import runs as runs_repo
from app.repositories import sources as sources_repo


def preview_source(source_id: int) -> dict[str, Any]:
    conn = connect()
    try:
        source = sources_repo.get_source(conn, source_id)
        if not source:
            raise ValueError("source not found")
        path = FIXTURES_DIR / source["fixture_path"]
        items = parse_fixture(path, source["format"])
        return {
            "source": source,
            "count": len(items),
            "items": items[:50],
        }
    finally:
        conn.close()


def run_ingest(source_id: int, mode: str = "incremental") -> dict[str, Any]:
    if mode not in ("incremental", "full"):
        raise ValueError("mode must be incremental or full")

    conn = connect()
    try:
        source = sources_repo.get_source(conn, source_id)
        if not source:
            raise ValueError("source not found")
        if not source["enabled"]:
            raise ValueError("source disabled")

        if mode == "full":
            sources_repo.set_watermark(conn, source_id, None)
            source["watermark_ts"] = None

        run_id = runs_repo.create_run(conn, source_id, mode)
        path = FIXTURES_DIR / source["fixture_path"]

        try:
            items = parse_fixture(path, source["format"])
        except Exception as exc:  # noqa: BLE001
            runs_repo.finish_run(
                conn,
                run_id,
                status="failed",
                parsed=0,
                upserted=0,
                conflicts=0,
                skipped=0,
                report={"error": str(exc)},
            )
            conn.commit()
            raise

        parsed = 0
        upserted = 0
        conflicts = 0
        skipped = 0
        max_event_ts: str | None = source.get("watermark_ts")
        dispositions: list[str] = []
        written_keys: list[str] = []

        for item in items:
            parsed += 1
            if mode == "incremental" and not eligible_for_incremental(
                item["event_ts"],
                source.get("watermark_ts"),
                int(source.get("lookback_seconds") or 0),
            ):
                runs_repo.insert_staging(
                    conn,
                    run_id=run_id,
                    source_id=source_id,
                    item=item,
                    disposition="skipped_watermark",
                )
                skipped += 1
                dispositions.append("skipped_watermark")
                continue

            existing = canon_repo.get_by_key(conn, item["business_key"])
            existing_view = None
            if existing:
                existing_view = {
                    "business_key": existing["business_key"],
                    "title": existing["title"],
                    "price": existing["price"],
                    "category": existing["category"],
                    "event_ts": existing["event_ts"],
                    "source_revision": existing["source_revision"],
                    "payload": existing["payload"],
                }

            decision = decide_merge(existing_view, item)
            if decision in ("insert", "upsert"):
                lineage_id = lineage.record_write(
                    conn,
                    item=item,
                    source_id=source_id,
                    run_id=run_id,
                    action=decision,
                )
                canon_repo.upsert_item(
                    conn,
                    item,
                    source_id,
                    run_id=run_id,
                    lineage_id=lineage_id,
                )
                runs_repo.insert_staging(
                    conn,
                    run_id=run_id,
                    source_id=source_id,
                    item=item,
                    disposition=decision,
                )
                upserted += 1
                dispositions.append(decision)
                written_keys.append(item["business_key"])
                if max_event_ts is None or item["event_ts"] > max_event_ts:
                    max_event_ts = item["event_ts"]
            elif decision == "conflict":
                runs_repo.insert_conflict(
                    conn,
                    run_id=run_id,
                    source_id=source_id,
                    item=item,
                    existing_payload=existing_view["payload"] if existing_view else {},
                    reason="non_key_field_mismatch",
                    existing_source_id=existing["source_id"] if existing else None,
                    existing_run_id=existing["run_id"] if existing else None,
                    existing_lineage_id=existing["lineage_id"] if existing else None,
                    existing_event_ts=existing["event_ts"] if existing else None,
                    existing_revision=existing["source_revision"] if existing else None,
                )
                runs_repo.insert_staging(
                    conn,
                    run_id=run_id,
                    source_id=source_id,
                    item=item,
                    disposition="quarantine",
                )
                conflicts += 1
                dispositions.append("quarantine")
                if max_event_ts is None or item["event_ts"] > max_event_ts:
                    max_event_ts = item["event_ts"]
            else:
                runs_repo.insert_staging(
                    conn,
                    run_id=run_id,
                    source_id=source_id,
                    item=item,
                    disposition="skip_stale",
                )
                skipped += 1
                dispositions.append("skip_stale")
                if max_event_ts is None or item["event_ts"] > max_event_ts:
                    max_event_ts = item["event_ts"]

        if max_event_ts:
            sources_repo.set_watermark(conn, source_id, max_event_ts)

        written_keys = list(dict.fromkeys(written_keys))
        canonical_count = canon_repo.count_items(conn)
        lineage_check = lineage.reconciliation(conn, run_id, upserted)
        report = {
            "source_id": source_id,
            "mode": mode,
            "parsed_count": parsed,
            "upserted_count": upserted,
            "conflict_count": conflicts,
            "skipped_count": skipped,
            "canonical_count": canonical_count,
            "lineage_event_count": lineage_check["lineage_written_count"],
            "lineage_distinct_keys": lineage_check["lineage_distinct_keys"],
            "lineage_reconciles": lineage_check["lineage_reconciles"],
            "canonical_lineage_pointers_ok": lineage_check[
                "canonical_lineage_pointers_ok"
            ],
            "watermark_ts": max_event_ts,
            "dispositions": dispositions,
            "written_keys": written_keys,
        }
        runs_repo.finish_run(
            conn,
            run_id,
            status="ok",
            parsed=parsed,
            upserted=upserted,
            conflicts=conflicts,
            skipped=skipped,
            report=report,
        )
        conn.commit()
        run = runs_repo.get_run(conn, run_id)
        return run or report
    finally:
        conn.close()


def dashboard_stats() -> dict[str, Any]:
    conn = connect()
    try:
        sources = sources_repo.list_sources(conn)
        lineage_stats = lineage.summary(conn)
        return {
            "source_count": len(sources),
            "enabled_sources": sum(1 for s in sources if s["enabled"]),
            "canonical_count": canon_repo.count_items(conn),
            "conflict_count": conn.execute("SELECT COUNT(*) c FROM conflicts").fetchone()["c"],
            "run_count": conn.execute("SELECT COUNT(*) c FROM runs").fetchone()["c"],
            "staging_count": conn.execute("SELECT COUNT(*) c FROM staging_rows").fetchone()["c"],
            "lineage_event_count": lineage_stats["lineage_event_count"],
            "canonical_with_lineage": lineage_stats["canonical_with_lineage"],
        }
    finally:
        conn.close()
