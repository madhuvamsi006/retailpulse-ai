"""MCP tools: product search and catalog lookup."""
import time
from typing import Any

from google.cloud import bigquery
import config


def _bq_client() -> bigquery.Client:
    return bigquery.Client(project=config.GCP_PROJECT_ID)


def search_products(
    query: str,
    budget_max: float | None = None,
    size: str | None = None,
    width: str | None = None,
    category: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Semantic vector search over products, with hard filters applied in SQL.
    Uses VECTOR_SEARCH with pre-generated embeddings stored in BigQuery.
    """
    from data.embeddings import generate_embedding
    query_embedding = generate_embedding(query)

    client = _bq_client()
    dataset = config.BQ_DATASET

    filters = ["p.total_stock > 0"]
    params = [bigquery.ArrayQueryParameter("query_embedding", "FLOAT64", query_embedding)]

    if budget_max is not None:
        filters.append("p.price <= @budget_max")
        params.append(bigquery.ScalarQueryParameter("budget_max", "FLOAT64", budget_max))

    if size is not None:
        filters.append("@size IN UNNEST(p.available_sizes)")
        params.append(bigquery.ScalarQueryParameter("size", "STRING", str(size)))

    if width is not None:
        filters.append("@width IN UNNEST(p.available_widths)")
        params.append(bigquery.ScalarQueryParameter("width", "STRING", width.upper()))

    if category is not None:
        filters.append("LOWER(p.category) LIKE @category")
        params.append(bigquery.ScalarQueryParameter("category", "STRING", f"%{category.lower()}%"))

    where_clause = " AND ".join(filters)

    sql = f"""
        SELECT
            p.sku,
            p.name,
            p.category,
            p.price,
            p.available_sizes,
            p.available_widths,
            p.total_stock,
            p.description,
            vs.distance AS cosine_distance
        FROM
            VECTOR_SEARCH(
                TABLE `{config.GCP_PROJECT_ID}.{dataset}.products`,
                'embedding',
                (SELECT @query_embedding AS embedding),
                distance_type => 'COSINE',
                top_k => 50
            ) vs
        JOIN `{config.GCP_PROJECT_ID}.{dataset}.products` p ON vs.base.sku = p.sku
        WHERE {where_clause}
        ORDER BY vs.distance ASC
        LIMIT @limit
    """
    params.append(bigquery.ScalarQueryParameter("limit", "INT64", limit))

    job_config = bigquery.QueryJobConfig(query_parameters=params)
    results = client.query(sql, job_config=job_config).result()
    return [dict(row) for row in results]


def get_product(sku: str) -> dict[str, Any] | None:
    """Fetch a single product with full detail including current price."""
    client = _bq_client()
    sql = """
        SELECT sku, name, category, price, available_sizes, available_widths,
               total_stock, description, supplier_id
        FROM `@project.@dataset.products`
        WHERE sku = @sku
        LIMIT 1
    """.replace("@project", config.GCP_PROJECT_ID).replace("@dataset", config.BQ_DATASET)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("sku", "STRING", sku)]
    )
    results = list(client.query(sql, job_config=job_config).result())
    return dict(results[0]) if results else None
