"""Discovery Agent — semantic product search with hard constraint enforcement."""
import json
import sys
import os
import time
from typing import Any

import google.generativeai as genai

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from agents import mcp_client
from ranking.constraint_filter import ShopperConstraints, apply as hard_filter

genai.configure()

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
    model = genai.GenerativeModel(config.GEMINI_MODEL)
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

    # Hard filter — deterministic, no LLM
    shopper_constraints = ShopperConstraints(
        budget_max=constraints_raw.get("budget_max"),
        size=constraints_raw.get("size"),
        width=constraints_raw.get("width"),
        categories=[constraints_raw["category"]] if constraints_raw.get("category") else None,
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

    # Generate natural language reasons
    model = genai.GenerativeModel(config.GEMINI_MODEL)
    reason_prompt = f"""Given shopper query: "{user_query}"
And these product results: {json.dumps(recommendations, default=str)}

Write a JSON response with recommendations. For each product write a one-sentence reason why it fits.
Follow this schema exactly:
{{
  "recommendations": [
    {{"sku": "...", "name": "...", "price": 0.0, "reason": "...", "stockout_risk": "...", "days_until_stockout": 0}}
  ],
  "summary": "one sentence overview"
}}"""
    resp = model.generate_content(reason_prompt)
    text = resp.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]

    try:
        result = json.loads(text.strip())
    except json.JSONDecodeError:
        result = {
            "recommendations": recommendations,
            "summary": f"Found {len(recommendations)} products matching your criteria.",
        }

    emit_decision(session_id, "discovery_agent", "recommendations_ready",
                  f"{len(result.get('recommendations', []))} products", 0.9)
    return result
