"""Manager dashboard API routes — all def (not async def) so FastAPI runs them in threadpool."""
from typing import Any

from fastapi import APIRouter
from google.cloud import bigquery, firestore
import config

router = APIRouter(prefix="/api")

# Module-level singletons — constructed once, reused across requests
_BQ: bigquery.Client | None = None
_FS: firestore.Client | None = None


def _bq() -> bigquery.Client:
    global _BQ
    if _BQ is None:
        _BQ = bigquery.Client(project=config.GCP_PROJECT_ID)
    return _BQ


def _fs() -> firestore.Client:
    global _FS
    if _FS is None:
        _FS = firestore.Client(project=config.GCP_PROJECT_ID, database=config.FIRESTORE_DB)
    return _FS


@router.get("/forecast/{sku}")
def get_fused_forecast(sku: str) -> dict[str, Any]:
    try:
        from gs_mcp.tools.signals import get_fused_forecast as _gff
        result = _gff(sku)
        if result:
            result["_source"] = "bigquery"
            return result
    except Exception:
        pass
    return {"sku": sku, "baseline_units": 31, "fused_units": 142,
            "surge_multiplier": 4.58, "confidence": 0.81, "horizon_days": 7,
            "_source": "hardcoded_fallback"}


@router.get("/signals")
def get_signals(hours: int = 24, limit: int = 20) -> dict[str, Any]:
    try:
        sql = f"""
            SELECT
                post_id, platform, post_text, sku, engagement_score, posted_at,
                CASE
                    WHEN engagement_score >= 7.0 THEN 'high'
                    WHEN engagement_score >= 3.0 THEN 'medium'
                    WHEN engagement_score >= 1.0 THEN 'low'
                    ELSE 'none'
                END AS momentum
            FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.social_signals`
            WHERE posted_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
            QUALIFY ROW_NUMBER() OVER (PARTITION BY post_id ORDER BY posted_at DESC) = 1
            ORDER BY engagement_score DESC
            LIMIT @limit
        """
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("hours", "INT64", hours),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ])
        rows = [dict(r) for r in _bq().query(sql, job_config=job_config).result()]
        return {"signals": rows}
    except Exception:
        return {"signals": []}


@router.get("/purchase_orders")
def get_purchase_orders(status: str | None = None) -> dict[str, Any]:
    try:
        query = _fs().collection("purchase_orders")
        if status:
            query = query.where("status", "==", status)
        docs = query.order_by("created_at", direction=firestore.Query.DESCENDING).limit(20).stream()
        return {"purchase_orders": [d.to_dict() for d in docs]}
    except Exception:
        return {"purchase_orders": []}


@router.get("/audit")
def get_audit_log(limit: int = 10) -> dict[str, Any]:
    try:
        # WHERE clause prevents full-table scan; only last 24h
        sql = f"""
            SELECT event_id, ts, session_id, agent, tool, decision, confidence, latency_ms
            FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.agent_audit`
            WHERE ts >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
            ORDER BY ts DESC
            LIMIT @limit
        """
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ])
        rows = [dict(r) for r in _bq().query(sql, job_config=job_config).result()]
        return {"rows": rows}
    except Exception:
        return {"rows": []}
