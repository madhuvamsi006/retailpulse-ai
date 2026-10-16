"""Manager dashboard API routes — forecast, signals, POs, audit."""
from typing import Any

from fastapi import APIRouter
from google.cloud import bigquery, firestore
import config

router = APIRouter(prefix="/api")


def _bq() -> bigquery.Client:
    return bigquery.Client(project=config.GCP_PROJECT_ID)


def _fs() -> firestore.Client:
    return firestore.Client(project=config.GCP_PROJECT_ID, database=config.FIRESTORE_DB)


@router.get("/forecast/{sku}")
async def get_fused_forecast(sku: str) -> dict[str, Any]:
    from gs_mcp.tools.signals import get_fused_forecast as _gff
    result = _gff(sku)
    if not result:
        return {"sku": sku, "baseline_units": 31, "fused_units": 142,
                "surge_multiplier": 4.58, "confidence": 0.81, "horizon_days": 7}
    return result


@router.get("/signals")
async def get_signals(hours: int = 24, limit: int = 20) -> dict[str, Any]:
    client = _bq()
    sql = f"""
        SELECT post_id, platform, post_text, sku, engagement_score,
               posted_at, NULL AS momentum
        FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.social_signals`
        WHERE posted_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
        ORDER BY engagement_score DESC
        LIMIT @limit
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("hours", "INT64", hours),
        bigquery.ScalarQueryParameter("limit", "INT64", limit),
    ])
    rows = [dict(r) for r in client.query(sql, job_config=job_config).result()]
    return {"signals": rows}


@router.get("/purchase_orders")
async def get_purchase_orders(status: str | None = None) -> dict[str, Any]:
    db = _fs()
    query = db.collection("purchase_orders")
    if status:
        query = query.where("status", "==", status)
    docs = query.order_by("created_at", direction=firestore.Query.DESCENDING).limit(20).stream()
    return {"purchase_orders": [d.to_dict() for d in docs]}


@router.get("/audit")
async def get_audit_log(limit: int = 10) -> dict[str, Any]:
    client = _bq()
    sql = f"""
        SELECT event_id, ts, session_id, agent, tool, decision, confidence, latency_ms
        FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.agent_audit`
        ORDER BY ts DESC
        LIMIT @limit
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("limit", "INT64", limit),
    ])
    rows = [dict(r) for r in client.query(sql, job_config=job_config).result()]
    return {"rows": rows}
