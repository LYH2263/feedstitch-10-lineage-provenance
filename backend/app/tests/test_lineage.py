import pytest

from app import db, seed
from app.db import connect
from app.modules import lineage_provenance as lineage
from app.repositories import canonical as canon_repo
from app.services.ingest_service import run_ingest


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "lineage.db")
    seed.init_db()
    yield


def test_clean_source_writes_lineage_and_reconciles(temp_db):
    run = run_ingest(1)
    assert run["upserted_count"] == 3
    assert run["report"]["lineage_event_count"] == 3
    assert run["report"]["lineage_reconciles"] is True
    assert run["report"]["canonical_lineage_pointers_ok"] is True

    conn = connect()
    try:
        chain = lineage.build_chain(conn, "SKU-1001")
    finally:
        conn.close()
    assert chain["applied_count"] == 1
    assert chain["quarantined_count"] == 0
    event = chain["events"][0]
    assert event["source_id"] == 1
    assert event["run_id"] == run["id"]
    assert event["source_revision"] == 3
    assert event["event_ts"] == "2026-11-01T10:00:00Z"
    assert event["written_at"]
    assert chain["canonical_points_to_latest"] is True
    assert chain["canonical"]["lineage_id"] == event["id"]


def test_conflict_attempt_is_visible_but_not_applied(temp_db):
    run_ingest(1)
    run = run_ingest(2)
    assert run["conflict_count"] == 1
    # SKU-2001 / SKU-2002 are written; SKU-1001's dirty row is quarantined only.
    assert run["upserted_count"] == 2
    assert run["report"]["lineage_event_count"] == 2

    conn = connect()
    try:
        chain = lineage.build_chain(conn, "SKU-1001")
    finally:
        conn.close()
    assert chain["applied_count"] == 1  # from the Alpha run only
    assert chain["quarantined_count"] == 1
    attempt = chain["attempts"][0]
    assert attempt["run_id"] == run["id"]
    assert attempt["source_id"] == 2
    assert attempt["applied"] is False
    assert attempt["source_revision"] == 4
    assert attempt["existing_source_id"] == 1
    assert attempt["existing_run_id"] == 1
    # The quarantine node must not be counted as an applied write for this run.
    applied_for_run = [n for n in chain["chain"] if n["kind"] == lineage.APPLIED and n["run_id"] == run["id"]]
    assert applied_for_run == []


def test_chain_is_ordered_and_survives_reload(temp_db):
    run_ingest(1)
    conn = connect()
    try:
        item = {
            "business_key": "SKU-1001",
            "title": "Oak Desk Lamp",
            "price": 129.0,
            "category": "lighting",
            "event_ts": "2026-11-03T09:00:00Z",
            "source_revision": 5,
            "payload": {
                "business_key": "SKU-1001",
                "title": "Oak Desk Lamp",
                "price": 129.0,
                "category": "lighting",
                "event_ts": "2026-11-03T09:00:00Z",
                "source_revision": 5,
            },
        }
        lineage_id = lineage.record_write(conn, item=item, source_id=1, run_id=2, action="upsert")
        canon_repo.upsert_item(conn, item, 1, run_id=2, lineage_id=lineage_id)
        conn.commit()

        chain = lineage.build_chain(conn, "SKU-1001")
    finally:
        conn.close()

    assert chain["applied_count"] == 2
    ids = [e["id"] for e in chain["events"]]
    assert ids == sorted(ids)
    assert chain["events"][-1]["is_latest"] is True
    assert chain["events"][-1]["source_revision"] == 5
    assert chain["canonical"]["lineage_id"] == ids[-1]
    assert chain["canonical_points_to_latest"] is True

    # Re-opening the same SQLite file keeps the lineage.
    conn = connect()
    try:
        assert lineage.count_run(conn, 1) == 3
        assert lineage.summary(conn)["lineage_event_count"] == 4
        chain_again = lineage.build_chain(conn, "SKU-1001")
        assert chain_again["applied_count"] == 2
    finally:
        conn.close()
