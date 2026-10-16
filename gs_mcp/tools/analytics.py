"""MCP analytics tools — sales intelligence queries for the manager analyst agent."""
from typing import Any

from google.cloud import bigquery
import config


def _bq() -> bigquery.Client:
    return bigquery.Client(project=config.GCP_PROJECT_ID)


def get_sales_summary(
    sku: str | None = None,
    category: str | None = None,
    store_id: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """Total units sold, revenue, daily average for a SKU/category/store over N days."""
    client = _bq()
    filters = ["sale_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)"]
    params: list = [bigquery.ScalarQueryParameter("days", "INT64", days)]

    if sku:
        filters.append("s.sku = @sku")
        params.append(bigquery.ScalarQueryParameter("sku", "STRING", sku))
    if store_id:
        filters.append("s.store_id = @store_id")
        params.append(bigquery.ScalarQueryParameter("store_id", "STRING", store_id))
    if category:
        filters.append("LOWER(p.category) LIKE @category")
        params.append(bigquery.ScalarQueryParameter("category", "STRING", f"%{category.lower()}%"))

    where = " AND ".join(filters)
    sql = f"""
        SELECT
            s.sku,
            p.name,
            p.category,
            SUM(s.daily_units_sold) AS total_units,
            SUM(s.revenue) AS total_revenue,
            AVG(s.daily_units_sold) AS avg_daily_units,
            COUNT(DISTINCT s.sale_date) AS days_with_sales
        FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.sales` s
        JOIN `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.products` p ON s.sku = p.sku
        WHERE {where}
        GROUP BY s.sku, p.name, p.category
        ORDER BY total_revenue DESC
        LIMIT 20
    """
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    rows = [dict(r) for r in client.query(sql, job_config=job_config).result()]
    return {"period_days": days, "rows": rows, "filter": {"sku": sku, "category": category, "store_id": store_id}}


def get_sales_trend(sku: str, days: int = 30) -> dict[str, Any]:
    """
    Day-by-day sales for a SKU. Returns trend direction, peak day, and weekly comparison.
    Used by the analyst to detect whether sales are growing or declining.
    """
    client = _bq()
    sql = f"""
        SELECT
            sale_date,
            SUM(daily_units_sold) AS units,
            SUM(revenue) AS revenue
        FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.sales`
        WHERE sku = @sku
          AND sale_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        GROUP BY sale_date
        ORDER BY sale_date ASC
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("sku", "STRING", sku),
        bigquery.ScalarQueryParameter("days", "INT64", days),
    ])
    rows = [dict(r) for r in client.query(sql, job_config=job_config).result()]
    if not rows:
        return {"sku": sku, "rows": [], "trend": "no_data"}

    units = [float(r["units"]) for r in rows]
    half = len(units) // 2
    first_half_avg = sum(units[:half]) / max(half, 1)
    second_half_avg = sum(units[half:]) / max(len(units) - half, 1)
    pct_change = ((second_half_avg - first_half_avg) / max(first_half_avg, 0.01)) * 100
    trend = "rising" if pct_change > 10 else "falling" if pct_change < -10 else "stable"
    peak_row = max(rows, key=lambda r: r["units"])

    return {
        "sku": sku,
        "days": days,
        "rows": rows,
        "trend": trend,
        "pct_change_first_vs_second_half": round(pct_change, 1),
        "peak_date": str(peak_row["sale_date"]),
        "peak_units": float(peak_row["units"]),
        "avg_daily": round(sum(units) / len(units), 2),
    }


def get_category_performance(days: int = 30) -> dict[str, Any]:
    """Rank all categories by revenue and units. Shows which are up/down vs prior period."""
    client = _bq()
    sql = f"""
        WITH current_period AS (
            SELECT p.category,
                   SUM(s.daily_units_sold) AS units,
                   SUM(s.revenue) AS revenue
            FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.sales` s
            JOIN `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.products` p ON s.sku = p.sku
            WHERE s.sale_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
            GROUP BY p.category
        ),
        prior_period AS (
            SELECT p.category,
                   SUM(s.daily_units_sold) AS units,
                   SUM(s.revenue) AS revenue
            FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.sales` s
            JOIN `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.products` p ON s.sku = p.sku
            WHERE s.sale_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @prior_days DAY)
              AND s.sale_date < DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
            GROUP BY p.category
        )
        SELECT
            c.category,
            c.units AS current_units,
            c.revenue AS current_revenue,
            COALESCE(pr.units, 0) AS prior_units,
            COALESCE(pr.revenue, 0) AS prior_revenue,
            SAFE_DIVIDE(c.units - COALESCE(pr.units, 0), COALESCE(pr.units, 1)) * 100 AS units_pct_change
        FROM current_period c
        LEFT JOIN prior_period pr ON c.category = pr.category
        ORDER BY c.revenue DESC
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("days", "INT64", days),
        bigquery.ScalarQueryParameter("prior_days", "INT64", days * 2),
    ])
    rows = [dict(r) for r in client.query(sql, job_config=job_config).result()]
    return {"period_days": days, "categories": rows}


def get_sales_anomalies(days: int = 14) -> dict[str, Any]:
    """
    Detect SKUs with unusual sales velocity vs their own 90-day baseline.
    Returns over-performers (likely viral) and under-performers (potential problem).
    """
    client = _bq()
    sql = f"""
        WITH baseline AS (
            SELECT sku, AVG(daily_units_sold) AS avg_90d, STDDEV(daily_units_sold) AS stddev_90d
            FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.sales`
            WHERE sale_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
            GROUP BY sku
        ),
        recent AS (
            SELECT sku, AVG(daily_units_sold) AS avg_recent
            FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.sales`
            WHERE sale_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
            GROUP BY sku
        )
        SELECT
            r.sku,
            p.name,
            p.category,
            b.avg_90d,
            r.avg_recent,
            SAFE_DIVIDE(r.avg_recent - b.avg_90d, NULLIF(b.stddev_90d, 0)) AS z_score,
            SAFE_DIVIDE(r.avg_recent - b.avg_90d, NULLIF(b.avg_90d, 0.01)) * 100 AS pct_vs_baseline
        FROM recent r
        JOIN baseline b ON r.sku = b.sku
        JOIN `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.products` p ON r.sku = p.sku
        WHERE ABS(SAFE_DIVIDE(r.avg_recent - b.avg_90d, NULLIF(b.stddev_90d, 0))) > 1.5
        ORDER BY z_score DESC
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("days", "INT64", days),
    ])
    rows = [dict(r) for r in client.query(sql, job_config=job_config).result()]
    over = [r for r in rows if float(r.get("z_score") or 0) > 0]
    under = [r for r in rows if float(r.get("z_score") or 0) < 0]
    return {"over_performers": over, "under_performers": under, "period_days": days}


def get_store_comparison(sku: str | None = None, days: int = 30) -> dict[str, Any]:
    """Compare sales across all stores for a SKU or overall."""
    client = _bq()
    filters = ["s.sale_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)"]
    params: list = [bigquery.ScalarQueryParameter("days", "INT64", days)]
    if sku:
        filters.append("s.sku = @sku")
        params.append(bigquery.ScalarQueryParameter("sku", "STRING", sku))

    sql = f"""
        SELECT
            s.store_id,
            st.name AS store_name,
            st.location,
            SUM(s.daily_units_sold) AS total_units,
            SUM(s.revenue) AS total_revenue,
            AVG(s.daily_units_sold) AS avg_daily
        FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.sales` s
        JOIN `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.stores` st ON s.store_id = st.store_id
        WHERE {' AND '.join(filters)}
        GROUP BY s.store_id, st.name, st.location
        ORDER BY total_revenue DESC
    """
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    rows = [dict(r) for r in client.query(sql, job_config=job_config).result()]
    return {"sku": sku, "period_days": days, "stores": rows}


def get_correlation_signal_sales(sku: str, days: int = 14) -> dict[str, Any]:
    """
    Cross-reference social signal volume with sales for a SKU.
    Shows whether social buzz is translating to actual sales uplift.
    """
    client = _bq()
    sql = f"""
        WITH daily_sales AS (
            SELECT DATE(sale_date) AS d, SUM(daily_units_sold) AS units
            FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.sales`
            WHERE sku = @sku AND sale_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
            GROUP BY d
        ),
        daily_signals AS (
            SELECT DATE(posted_at) AS d, COUNT(*) AS posts, AVG(engagement_score) AS avg_eng
            FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.social_signals`
            WHERE sku = @sku AND posted_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
            GROUP BY d
        )
        SELECT
            ds.d AS date,
            COALESCE(ds.units, 0) AS units_sold,
            COALESCE(sig.posts, 0) AS social_posts,
            COALESCE(sig.avg_eng, 0) AS avg_engagement
        FROM daily_sales ds
        LEFT JOIN daily_signals sig ON ds.d = sig.d
        ORDER BY ds.d ASC
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("sku", "STRING", sku),
        bigquery.ScalarQueryParameter("days", "INT64", days),
    ])
    rows = [dict(r) for r in client.query(sql, job_config=job_config).result()]
    return {"sku": sku, "days": days, "correlation_data": rows}
