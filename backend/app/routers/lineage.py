from fastapi import APIRouter, HTTPException

from app.db import connect
from app.modules import lineage_provenance as lineage
from app.repositories import runs as runs_repo

router = APIRouter(tags=["lineage"])


@router.get("/lineage/summary")
def lineage_summary():
    conn = connect()
    try:
        return lineage.summary(conn)
    finally:
        conn.close()


@router.get("/lineage/{business_key}")
def get_lineage(business_key: str):
    conn = connect()
    try:
        chain = lineage.build_chain(conn, business_key)
        if not chain["exists"]:
            raise HTTPException(404, "no lineage for business key")
        return chain
    finally:
        conn.close()


@router.get("/runs/{run_id}/lineage")
def run_lineage(run_id: int):
    conn = connect()
    try:
        run = runs_repo.get_run(conn, run_id)
        if not run:
            raise HTTPException(404, "run not found")
        report = run.get("report") or {}
        return {
            "run_id": run_id,
            "upserted_count": run["upserted_count"],
            "lineage_written_count": lineage.count_run(conn, run_id),
            "lineage_distinct_keys": lineage.distinct_keys_run(conn, run_id),
            "reported_lineage_event_count": report.get("lineage_event_count"),
            "reconciles": lineage.count_run(conn, run_id) == run["upserted_count"],
        }
    finally:
        conn.close()
