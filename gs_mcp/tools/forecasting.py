"""MCP tools: ARIMA forecast and stockout prediction."""
from typing import Any

from google.cloud import bigquery
import config


def _bq() -> bigquery.Client:
    return bigquery.Client(project=config.GCP_PROJECT_ID)


def get_forecast(sku: str, horizon_days: int = 7) -> dict[str, Any]:
    """Fetch ARIMA_PLUS baseline forecast for a SKU from BigQuery."""
    client = _bq()
    sql = """
        SELECT
            forecast_timestamp,
            forecast_value,
            prediction_interval_lower_bound,
            prediction_interval_upper_bound
        FROM `@project.@dataset.stockout_forecast`
        WHERE sku = @sku
          AND horizon_days = @horizon_days
        ORDER BY forecast_timestamp ASC
    """.replace("@project", config.GCP_PROJECT_ID).replace("@dataset", config.BQ_DATASET)

    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("sku", "STRING", sku),
        bigquery.ScalarQueryParameter("horizon_days", "INT64", horizon_days),
    ])
    rows = list(client.query(sql, job_config=job_config).result())
    if not rows:
        return {"sku": sku, "horizon_days": horizon_days, "baseline_units": 0, "rows": []}

    total = sum(float(r["forecast_value"]) for r in rows)
    return {
        "sku": sku,
        "horizon_days": horizon_days,
        "baseline_units": round(total),
        "rows": [dict(r) for r in rows],
    }


def forecast_stockout(sku: str, store_id: str | None = None) -> dict[str, Any]:
    """
    Predict days until stockout given current inventory and daily demand rate.
    Returns days_until_stockout and urgency level.
    """
    from gs_mcp.tools.inventory import check_inventory

    inv = check_inventory(sku, store_id)
    available = inv["available"]

    client = _bq()
    sql = """
        SELECT AVG(daily_units_sold) AS avg_daily
        FROM `@project.@dataset.sales`
        WHERE sku = @sku
          AND sale_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
    """.replace("@project", config.GCP_PROJECT_ID).replace("@dataset", config.BQ_DATASET)

    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("sku", "STRING", sku),
    ])
    rows = list(client.query(sql, job_config=job_config).result())
    avg_daily = float(rows[0]["avg_daily"] or 1) if rows else 1.0

    days = available / avg_daily if avg_daily > 0 else float("inf")
    urgency = "critical" if days < 3 else "high" if days < 7 else "medium" if days < 14 else "low"

    return {
        "sku": sku,
        "store_id": store_id,
        "available_units": available,
        "avg_daily_sales": round(avg_daily, 2),
        "days_until_stockout": round(days, 1),
        "urgency": urgency,
    }
