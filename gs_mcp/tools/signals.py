"""MCP tools: social signal retrieval from BigQuery."""
from typing import Any

from google.cloud import bigquery
import config


def get_social_signals(sku: str | None = None, hours: int = 24, limit: int = 50) -> list[dict[str, Any]]:
    """
    Fetch recent social posts from BigQuery. Optionally filtered by SKU.
    Returns raw posts for the Signal Agent to extract structured signals from.
    """
    client = bigquery.Client(project=config.GCP_PROJECT_ID)

    filters = ["posted_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)"]
    params: list = [bigquery.ScalarQueryParameter("hours", "INT64", hours)]

    if sku:
        filters.append("sku = @sku")
        params.append(bigquery.ScalarQueryParameter("sku", "STRING", sku))

    where = " AND ".join(filters)
    sql = f"""
        SELECT
            post_id,
            platform,
            post_text,
            sku,
            engagement_score,
            posted_at
        FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.social_signals`
        WHERE {where}
        ORDER BY engagement_score DESC
        LIMIT @limit
    """
    params.append(bigquery.ScalarQueryParameter("limit", "INT64", limit))
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    return [dict(r) for r in client.query(sql, job_config=job_config).result()]


def get_fused_forecast(sku: str) -> dict[str, Any] | None:
    """Fetch the latest fused forecast (ARIMA + signal) for a SKU."""
    client = bigquery.Client(project=config.GCP_PROJECT_ID)
    sql = f"""
        SELECT sku, baseline_units, fused_units, surge_multiplier, confidence,
               horizon_days, computed_at
        FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.fused_forecast`
        WHERE sku = @sku
        ORDER BY computed_at DESC
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("sku", "STRING", sku)]
    )
    rows = list(client.query(sql, job_config=job_config).result())
    return dict(rows[0]) if rows else None
