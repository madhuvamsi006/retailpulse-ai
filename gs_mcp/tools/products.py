"""MCP tools: product search and catalog lookup."""
import time
from typing import Any

from google.cloud import bigquery
import config


def _bq_client() -> bigquery.Client:
    return bigquery.Client(project=config.GCP_PROJECT_ID)


DEMO_CATALOG = [
    {"sku": "SHOE-PEG41-GRY", "name": "Pegasus 41 Max-Cushion Road Runner",
     "category": "running-road", "price": 139.99, "unit_cost": 62.0,
     "available_sizes": ["7","8","9","10","11","12","13"],
     "available_widths": ["D","2E"], "total_stock": 48,
     "description": "Max-cushioned road marathon training shoe with ReactX foam. Grey/white colorway.",
     "cosine_distance": 0.27},
    {"sku": "SHOE-TRAIL-BLK", "name": "TrailBlazer Pro Aggressive Lug Trail Shoe",
     "category": "running-trail", "price": 124.99, "unit_cost": 54.0,
     "available_sizes": ["7","8","9","10","11","12"],
     "available_widths": ["D"], "total_stock": 22,
     "description": "Aggressive lug trail shoe for technical terrain. Black/orange.",
     "cosine_distance": 0.39},
    {"sku": "SHOE-XFIT-WHT", "name": "CrossFit Trainer 5.0 Wide",
     "category": "training", "price": 109.99, "unit_cost": 48.0,
     "available_sizes": ["8","9","10","11","12","13"],
     "available_widths": ["D","2E","4E"], "total_stock": 34,
     "description": "Stable wide-fit cross-training shoe for gym and WODs.",
     "cosine_distance": 0.45},
    {"sku": "SHOE-SLIP-BLK", "name": "ComfortWalk Slip-On Casual",
     "category": "casual", "price": 79.99, "unit_cost": 32.0,
     "available_sizes": ["7","8","9","10","11","12"],
     "available_widths": ["D","2E"], "total_stock": 60,
     "description": "Lightweight memory foam slip-on for all-day wear.",
     "cosine_distance": 0.47},
    {"sku": "SHOE-DRESS-BRN", "name": "Oxford Executive Leather Dress Shoe",
     "category": "dress", "price": 189.99, "unit_cost": 88.0,
     "available_sizes": ["8","9","10","11","12"],
     "available_widths": ["D","EE"], "total_stock": 15,
     "description": "Premium leather oxford for business formal. Brown.",
     "cosine_distance": 0.51},
]


def search_products(
    query: str,
    budget_max: float | None = None,
    size: str | None = None,
    width: str | None = None,
    category: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Semantic vector search with keyword and demo fallbacks.
    Tries VECTOR_SEARCH → keyword search → demo catalog.
    """
    try:
        results = _vector_search(query, budget_max, size, width, category, limit)
        if results:
            return results
    except Exception:
        pass
    try:
        results = _keyword_search(query, budget_max, size, width, category, limit)
        if results:
            return results
    except Exception:
        pass
    # Demo fallback: filter the in-memory catalog
    return _demo_search(query, budget_max, size, width, category, limit)


def _build_filters(
    budget_max: float | None, size: str | None, width: str | None, category: str | None
) -> tuple[list[str], list]:
    filters = ["total_stock > 0"]
    params: list = []
    if budget_max is not None:
        filters.append("price <= @budget_max")
        params.append(bigquery.ScalarQueryParameter("budget_max", "FLOAT64", budget_max))
    if size is not None:
        filters.append("@size IN UNNEST(available_sizes)")
        params.append(bigquery.ScalarQueryParameter("size", "STRING", str(size)))
    if width is not None:
        filters.append("@width IN UNNEST(available_widths)")
        params.append(bigquery.ScalarQueryParameter("width", "STRING", width.upper()))
    if category is not None:
        filters.append("LOWER(category) LIKE @category")
        params.append(bigquery.ScalarQueryParameter("category", "STRING", f"%{category.lower()}%"))
    return filters, params


def _vector_search(query, budget_max, size, width, category, limit) -> list[dict[str, Any]]:
    from data.embeddings import generate_embedding
    query_embedding = generate_embedding(query)
    client = _bq_client()
    dataset = config.BQ_DATASET
    filters, params = _build_filters(budget_max, size, width, category)
    # Vector search returns vs.base which already has all product columns
    where = " AND ".join(f"vs.base.{f}" for f in filters)
    params.insert(0, bigquery.ArrayQueryParameter("qemb", "FLOAT64", query_embedding))
    params.append(bigquery.ScalarQueryParameter("limit", "INT64", limit))
    sql = f"""
        SELECT
            vs.base.sku, vs.base.name, vs.base.category, vs.base.price,
            vs.base.available_sizes, vs.base.available_widths,
            vs.base.total_stock, vs.base.description, vs.distance AS cosine_distance
        FROM VECTOR_SEARCH(
            TABLE `{config.GCP_PROJECT_ID}.{dataset}.products`,
            'embedding',
            (SELECT @qemb AS embedding),
            distance_type => 'COSINE',
            top_k => 50
        ) vs
        WHERE {where}
        ORDER BY vs.distance ASC
        LIMIT @limit
    """
    results = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
    return [dict(row) for row in results]


def _demo_search(query, budget_max, size, width, category, limit) -> list[dict[str, Any]]:
    """In-memory fallback. Applies budget/size/width hard filters, uses keyword scoring for category."""
    from ranking.constraint_filter import ShopperConstraints, apply as hard_filter
    # Don't pass category to hard_filter — use keyword scoring instead (avoids Gemini/catalog mismatch)
    constraints = ShopperConstraints(
        budget_max=float(budget_max) if budget_max is not None else None,
        size=str(size) if size else None,
        width=str(width).upper() if width else None,
        categories=None,
        in_stock_only=True,
    )
    filtered = hard_filter(DEMO_CATALOG, constraints)
    # Keyword relevance sort — uses query + category hint
    q_lower = (query + " " + (category or "")).lower()
    keywords = [w for w in q_lower.split() if len(w) > 3]
    def score(p):
        desc = (p["description"] + " " + p["name"] + " " + p["category"]).lower()
        return sum(1 for kw in keywords if kw in desc)
    filtered.sort(key=score, reverse=True)
    return filtered[:limit]


def _keyword_search(query, budget_max, size, width, category, limit) -> list[dict[str, Any]]:
    """Fallback: keyword LIKE search when vector search is unavailable."""
    client = _bq_client()
    dataset = config.BQ_DATASET
    filters, params = _build_filters(budget_max, size, width, category)
    # Add keyword filter from query words
    words = [w.lower() for w in query.split() if len(w) > 3]
    if words:
        kw_conditions = " OR ".join(f"LOWER(description) LIKE '%{w}%' OR LOWER(name) LIKE '%{w}%'" for w in words[:3])
        filters.append(f"({kw_conditions})")
    where = " AND ".join(filters)
    params.append(bigquery.ScalarQueryParameter("limit", "INT64", limit))
    sql = f"""
        SELECT sku, name, category, price, available_sizes, available_widths,
               total_stock, description, 0.5 AS cosine_distance
        FROM `{config.GCP_PROJECT_ID}.{dataset}.products`
        WHERE {where}
        ORDER BY price ASC
        LIMIT @limit
    """
    results = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
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
