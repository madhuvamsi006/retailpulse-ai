"""
Enterprise Knowledge Fabric — persistent organizational knowledge graph.
Stored in BigQuery (structured facts + embeddings) and Firestore (entity cache).

Knowledge layers:
  1. Product graph      — SKU relationships, categories, use-cases, complementary items
  2. Entity resolver    — "grey runners" → SHOE-PEG41-GRY (semantic + alias matching)
  3. Supplier network   — reliability, lead times, MOQ per product
  4. Pattern store      — recurring business patterns (weekend spikes, seasonal trends)
  5. Customer profiles  — accumulated shopper preferences (opt-in, session-scoped)
"""
import json
import time
from typing import Any

from google.cloud import bigquery, firestore
import config

_ENTITY_CACHE: dict[str, str] = {}   # in-process cache for entity resolution hits


def _bq() -> bigquery.Client:
    return bigquery.Client(project=config.GCP_PROJECT_ID)


def _fs() -> firestore.Client:
    return firestore.Client(project=config.GCP_PROJECT_ID, database=config.FIRESTORE_DB)


# ── 1. Product Knowledge Graph ─────────────────────────────────────────────────

PRODUCT_GRAPH: dict[str, dict] = {
    "SHOE-PEG41-GRY": {
        "brand": "Nike",
        "category": "running-road",
        "use_cases": ["marathon", "half-marathon", "long-distance", "daily-training"],
        "features": ["max-cushion", "ReactX-foam", "road-grip", "breathable"],
        "target_customer": ["runners", "fitness-enthusiasts", "marathon-trainers"],
        "complementary_skus": ["SOCK-RUNNING-01", "INSOLE-CUSHION-01"],
        "similar_skus": ["SHOE-TRAIL-BLK"],
        "aliases": ["grey runners", "grey cushioned runners", "grey nikes", "pegasus 41", "peg 41",
                    "max cushion road shoe", "those gym shoes everyone has"],
    },
    "SHOE-TRAIL-BLK": {
        "brand": "Salomon",
        "category": "running-trail",
        "use_cases": ["trail-running", "hiking", "obstacle-courses", "technical-terrain"],
        "features": ["aggressive-lug", "waterproof", "ankle-support", "grip"],
        "target_customer": ["trail-runners", "hikers", "adventure-athletes"],
        "complementary_skus": ["SOCK-TRAIL-01"],
        "similar_skus": ["SHOE-PEG41-GRY"],
        "aliases": ["trail shoe", "trail runners", "black trail shoe", "lug shoe"],
    },
    "SHOE-DRESS-BRN": {
        "brand": "Allen Edmonds",
        "category": "dress",
        "use_cases": ["business-formal", "office", "events", "interviews"],
        "features": ["leather", "oxford", "formal", "dress"],
        "target_customer": ["professionals", "executives", "formal-occasions"],
        "complementary_skus": [],
        "similar_skus": [],
        "aliases": ["oxford shoe", "dress shoe", "leather oxford", "formal shoe", "brown oxford"],
    },
    "SHOE-XFIT-WHT": {
        "brand": "Reebok",
        "category": "training",
        "use_cases": ["crossfit", "gym", "weight-training", "HIIT", "functional-fitness"],
        "features": ["wide-toe-box", "stable-sole", "cross-training", "durable"],
        "target_customer": ["crossfitters", "gym-goers", "functional-athletes"],
        "complementary_skus": [],
        "similar_skus": [],
        "aliases": ["crossfit shoe", "gym shoe", "training shoe", "crossfit trainer", "wide gym shoe"],
    },
    "SHOE-SLIP-BLK": {
        "brand": "Skechers",
        "category": "casual",
        "use_cases": ["everyday-wear", "travel", "walking", "standing-all-day"],
        "features": ["memory-foam", "slip-on", "lightweight", "comfortable"],
        "target_customer": ["casual-wearers", "travelers", "retail-workers"],
        "complementary_skus": [],
        "similar_skus": [],
        "aliases": ["slip on", "comfortable shoe", "casual shoe", "walking shoe", "travel shoe"],
    },
}

SEASONAL_PATTERNS = [
    {
        "pattern": "marathon_season",
        "months": [3, 4, 9, 10],
        "affected_categories": ["running-road"],
        "demand_multiplier": 1.4,
        "description": "Spring (April) and Fall (October) marathons drive road running shoe demand",
    },
    {
        "pattern": "weekend_spike",
        "day_of_week": [5, 6],  # Saturday, Sunday
        "affected_categories": ["all"],
        "demand_multiplier": 1.6,
        "description": "Weekend foot traffic 60% higher than weekday average",
    },
    {
        "pattern": "size_curve",
        "description": "Sizes 9-10 sell 3x faster than sizes 7 or 13. Stock accordingly.",
        "fast_sizes": ["9", "10"],
        "slow_sizes": ["7", "13"],
        "velocity_ratio": 3.0,
    },
    {
        "pattern": "new_year_fitness",
        "months": [1, 2],
        "affected_categories": ["running-road", "training"],
        "demand_multiplier": 1.8,
        "description": "New Year fitness resolutions drive training/running shoe demand in Jan-Feb",
    },
]


def get_product_knowledge(sku: str) -> dict[str, Any]:
    """Return full knowledge graph entry for a SKU."""
    return PRODUCT_GRAPH.get(sku, {})


def get_complementary_products(sku: str) -> list[str]:
    """Return SKUs that pair well with this product (for upsell suggestions)."""
    return PRODUCT_GRAPH.get(sku, {}).get("complementary_skus", [])


def get_seasonal_context() -> list[dict]:
    """Return currently active seasonal patterns."""
    import datetime
    current_month = datetime.datetime.now().month
    current_dow = datetime.datetime.now().weekday()
    active = []
    for pattern in SEASONAL_PATTERNS:
        if "months" in pattern and current_month in pattern["months"]:
            active.append(pattern)
        elif "day_of_week" in pattern and current_dow in pattern["day_of_week"]:
            active.append(pattern)
    return active


# ── 2. Entity Resolver ─────────────────────────────────────────────────────────

def resolve_entity(natural_language_mention: str) -> str | None:
    """
    Resolve a natural language product mention to a canonical SKU.
    Uses alias lookup first (fast), then semantic vector search (slower).

    Examples:
      "grey runners" → "SHOE-PEG41-GRY"
      "those gym shoes everyone has" → "SHOE-PEG41-GRY"
      "crossfit trainer" → "SHOE-XFIT-WHT"
    """
    mention_lower = natural_language_mention.lower().strip()

    # Check in-process cache
    if mention_lower in _ENTITY_CACHE:
        return _ENTITY_CACHE[mention_lower]

    # Alias lookup (exact and substring)
    for sku, data in PRODUCT_GRAPH.items():
        for alias in data.get("aliases", []):
            if alias.lower() in mention_lower or mention_lower in alias.lower():
                _ENTITY_CACHE[mention_lower] = sku
                return sku

    # Semantic fallback via vector search
    try:
        from data.embeddings import generate_embedding
        embedding = generate_embedding(natural_language_mention)
        client = _bq()
        sql = f"""
            SELECT base.sku, distance
            FROM VECTOR_SEARCH(
                TABLE `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.products`,
                'embedding',
                (SELECT @embedding AS embedding),
                distance_type => 'COSINE',
                top_k => 1
            ) vs
            JOIN `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.products` base ON vs.base.sku = base.sku
            WHERE vs.distance < 0.35
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ArrayQueryParameter("embedding", "FLOAT64", embedding)]
        )
        rows = list(client.query(sql, job_config=job_config).result())
        if rows:
            sku = rows[0]["sku"]
            _ENTITY_CACHE[mention_lower] = sku
            return sku
    except Exception:
        pass

    return None


def resolve_entities_in_text(text: str) -> dict[str, str]:
    """
    Scan text for product mentions and return all resolved SKUs.
    Returns {mention: sku} for each recognized entity.
    """
    resolved = {}
    # Check all known aliases against the text
    text_lower = text.lower()
    for sku, data in PRODUCT_GRAPH.items():
        for alias in data.get("aliases", []):
            if alias.lower() in text_lower:
                resolved[alias] = sku
    return resolved


# ── 3. Supplier Network ────────────────────────────────────────────────────────

def get_supplier_intelligence(sku: str) -> dict[str, Any]:
    """Return enriched supplier knowledge for a SKU including risk assessment."""
    try:
        client = _bq()
        sql = f"""
            SELECT s.supplier_id, s.name, s.lead_time_days, s.moq, s.reliability_score,
                   p.unit_cost
            FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.suppliers` s
            JOIN `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.products` p
              ON p.supplier_id = s.supplier_id
            WHERE p.sku = @sku
            LIMIT 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("sku", "STRING", sku)]
        )
        rows = list(client.query(sql, job_config=job_config).result())
        if not rows:
            return {}
        data = dict(rows[0])
        reliability = float(data.get("reliability_score", 0.9))
        data["risk_level"] = "low" if reliability > 0.95 else "medium" if reliability > 0.85 else "high"
        data["reorder_advice"] = (
            f"Order {data['moq']} minimum units, allow {data['lead_time_days']} days lead time. "
            f"Supplier reliability: {reliability:.0%}."
        )
        return data
    except Exception:
        return {}


# ── 4. Pattern Store ───────────────────────────────────────────────────────────

def get_demand_patterns(sku: str | None = None, category: str | None = None) -> list[dict]:
    """Return known demand patterns relevant to a SKU or category."""
    results = []
    target_category = None
    if sku and sku in PRODUCT_GRAPH:
        target_category = PRODUCT_GRAPH[sku]["category"]
    elif category:
        target_category = category

    for pattern in SEASONAL_PATTERNS:
        affected = pattern.get("affected_categories", [])
        if "all" in affected or not target_category:
            results.append(pattern)
        elif any(target_category.startswith(c) for c in affected):
            results.append(pattern)
    return results


# ── 5. Knowledge Fabric summary (for agent injection) ─────────────────────────

def build_knowledge_block(skus: list[str], query: str) -> str:
    """
    Build a structured knowledge block to inject into agent prompts.
    Runs entity resolution on the query and enriches with graph knowledge.
    """
    parts = ["<enterprise_knowledge>"]

    # Resolve any product entities mentioned in the query
    entity_map = resolve_entities_in_text(query)
    if entity_map:
        parts.append("<entity_resolution>")
        for mention, sku in entity_map.items():
            parts.append(f'  "{mention}" → {sku}')
        parts.append("</entity_resolution>")
        skus = list(set(skus + list(entity_map.values())))

    # Product knowledge for relevant SKUs
    for sku in skus:
        kg = get_product_knowledge(sku)
        if kg:
            parts.append(f"<product sku='{sku}'>")
            parts.append(f"  use_cases: {', '.join(kg.get('use_cases', []))}")
            parts.append(f"  features: {', '.join(kg.get('features', []))}")
            parts.append(f"  target_customer: {', '.join(kg.get('target_customer', []))}")
            comps = kg.get("complementary_skus", [])
            if comps:
                parts.append(f"  complementary: {', '.join(comps)}")
            parts.append("</product>")

    # Active seasonal patterns
    active_patterns = get_seasonal_context()
    if active_patterns:
        parts.append("<active_patterns>")
        for p in active_patterns:
            mult = p.get("demand_multiplier", 1.0)
            parts.append(f"  {p['pattern']}: {p['description']} (demand ×{mult})")
        parts.append("</active_patterns>")

    # Size curve knowledge (always relevant for footwear)
    parts.append("<size_knowledge>Sizes 9-10 sell 3× faster than 7 or 13. Prioritize these sizes in reorder quantities.</size_knowledge>")

    parts.append("</enterprise_knowledge>")
    return "\n".join(parts)
