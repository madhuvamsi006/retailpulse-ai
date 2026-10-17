"""Discovery Agent — semantic product search with hard constraint enforcement."""
import json
import sys
import os
import time
from typing import Any

from agents.gemini_client import get_model, generate, init as _init_gemini

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from agents import mcp_client
from ranking.constraint_filter import ShopperConstraints, apply as hard_filter


_init_gemini()

SYSTEM_PROMPT = """You are the Discovery Agent for Groundswell, a retail platform.

Your only job is to understand a shopper's natural language request and extract structured search parameters, then interpret search results into clear recommendations.

Rules you MUST follow:
- Extract budget, size, width, and category constraints precisely from the user's words.
- Never suggest a product that violates a stated constraint.
- When flagging stockout risk, use urgency levels: critical (<3 days), high (<7 days), medium (<14 days).
- Explain each recommendation in one sentence referencing why it fits the shopper's needs.
- You do not set prices. You do not approve payments. You only discover and explain.

Output format for recommendations:
{
  "recommendations": [
    {
      "sku": "...",
      "name": "...",
      "price": 0.00,
      "reason": "...",
      "stockout_risk": "low|medium|high|critical",
      "days_until_stockout": 0
    }
  ],
  "summary": "..."
}
"""


def _extract_constraints(user_query: str, session_id: str) -> dict[str, Any]:
    """Use Gemini to extract structured constraints from a natural language query."""
    model = get_model()
    extraction_prompt = f"""Extract search constraints from this shopper query. Return only valid JSON.

Query: {user_query}

Return JSON with these optional fields:
{{
  "search_query": "semantic search query (required)",
  "budget_max": null or number,
  "size": null or string,
  "width": null or string (e.g. "2E", "D", "B"),
  "category": null or string
}}"""
    resp = model.generate_content(extraction_prompt)
    text = resp.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def run(user_query: str, session_id: str) -> dict[str, Any]:
    """
    Run the discovery flow:
    1. Extract constraints from natural language
    2. Search products via MCP
    3. Hard-filter results (deterministic constraint node)
    4. Check stockout risk for each result
    5. Return structured recommendations
    """
    from gs_api.sse import emit_tool_call, emit_decision

    t0 = time.time()
    constraints_raw = _extract_constraints(user_query, session_id)
    emit_tool_call(
        session_id, "discovery_agent", "extract_constraints",
        {"query": user_query}, f"extracted: {constraints_raw}", (time.time() - t0) * 1000
    )

    t1 = time.time()
    products = mcp_client.search_products(
        query=constraints_raw.get("search_query", user_query),
        session_id=session_id,
        agent_name="discovery_agent",
        budget_max=constraints_raw.get("budget_max"),
        size=constraints_raw.get("size"),
        width=constraints_raw.get("width"),
        category=constraints_raw.get("category"),
        limit=20,
    )
    emit_tool_call(
        session_id, "discovery_agent", "search_products",
        constraints_raw, f"{len(products)} results", (time.time() - t1) * 1000
    )

    # Hard filter — deterministic, no LLM.
    # IMPORTANT: do NOT apply category here — product search already handles relevance.
    # Category strings from Gemini (e.g. "running shoes") don't match our taxonomy ("running-road").
    shopper_constraints = ShopperConstraints(
        budget_max=constraints_raw.get("budget_max"),
        size=str(constraints_raw.get("size")) if constraints_raw.get("size") else None,
        width=str(constraints_raw.get("width")).upper() if constraints_raw.get("width") else None,
        categories=None,  # relevance handled by search; category mismatch would filter everything
        in_stock_only=True,
    )
    filtered = hard_filter(products, shopper_constraints)

    recommendations = []
    for product in filtered[:5]:
        sku = product["sku"]
        t2 = time.time()
        stockout = mcp_client.forecast_stockout(sku, session_id, "discovery_agent")
        emit_tool_call(
            session_id, "discovery_agent", "forecast_stockout",
            {"sku": sku}, f"days={stockout['days_until_stockout']} urgency={stockout['urgency']}",
            (time.time() - t2) * 1000
        )
        recommendations.append({
            "sku": sku,
            "name": product["name"],
            "price": product["price"],
            "category": product.get("category"),
            "available_sizes": product.get("available_sizes", []),
            "stockout_risk": stockout["urgency"],
            "days_until_stockout": stockout["days_until_stockout"],
            "cosine_distance": product.get("cosine_distance"),
        })

    if not recommendations:
        return {
            "recommendations": [],
            "summary": "No products found matching your criteria. Try adjusting your budget, size, or category.",
        }

    # Add reason for each product — Gemini narrates ONLY the products we found
    valid_skus = {r["sku"] for r in recommendations}
    model = get_model()
    reason_prompt = f"""A shopper asked: "{user_query}"

We found these EXACT products in our catalog (do NOT add or invent any other products):
{json.dumps(recommendations, default=str)}

Write a brief one-sentence reason for each product explaining why it fits the shopper's request.
Return ONLY valid JSON with this exact schema — use only the SKUs listed above:
{{
  "recommendations": [
    {{"sku": "EXACT_SKU_FROM_LIST", "name": "exact name", "price": 0.0, "reason": "one sentence", "stockout_risk": "urgency", "days_until_stockout": 0}}
  ],
  "summary": "one sentence overview"
}}"""
    try:
        resp = model.generate_content(reason_prompt)
        text = resp.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text.strip())
        # Strip any hallucinated SKUs Gemini might have added
        result["recommendations"] = [
            r for r in result.get("recommendations", [])
            if r.get("sku") in valid_skus
        ]
        if not result["recommendations"]:
            raise ValueError("All recommendations were hallucinated")
    except Exception:
        result = {
            "recommendations": recommendations,
            "summary": f"Found {len(recommendations)} products matching your criteria.",
        }

    emit_decision(session_id, "discovery_agent", "recommendations_ready",
                  f"{len(result.get('recommendations', []))} products", 0.9)
    return result
