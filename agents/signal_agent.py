"""Signal Agent — extracts structured demand signals from raw social post text."""
import json
import sys
import os
import time
from typing import Any

import google.generativeai as genai
from google.cloud import firestore

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from agents import mcp_client
from fusion.surge_multiplier import SocialSignal, fuse

genai.configure()

SYSTEM_PROMPT = """You are the Signal Agent for Groundswell. Your job is to read raw social media posts and extract structured demand signals.

Rules:
- Only fire a signal if you are confident a specific named product is generating genuine purchase intent or strong enthusiasm.
- Ambiguous queries (e.g., "anyone know a good trail shoe?") must produce momentum=none, confidence<0.3.
- An extractor that fires on everything is worse than no extractor — it inflates purchase orders.
- Never hallucinate product names. If you cannot identify a specific product, set entity=null.
"""

EXTRACTION_PROMPT = """Analyze this social media post and extract a demand signal. Return only valid JSON.

Post: {post_text}

Return:
{{
  "entity": null or "product name as mentioned",
  "momentum": "high" | "medium" | "low" | "none",
  "confidence": 0.0 to 1.0,
  "reasoning": "one sentence explanation"
}}

Rules:
- momentum=none if post is a question, complaint, or general inquiry
- confidence < 0.3 for any signal without a clearly named product
- momentum=high only for strong enthusiasm with social proof ("everyone has them", viral context)
"""


def _extract_signal_from_post(post_text: str) -> dict[str, Any]:
    model = genai.GenerativeModel(config.GEMINI_MODEL)
    resp = model.generate_content(EXTRACTION_PROMPT.format(post_text=post_text))
    text = resp.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    signal = json.loads(text.strip())

    # Enforce schema: clamp low-confidence non-none momentum
    if signal.get("confidence", 0) < 0.3 and signal.get("momentum") != "none":
        signal["momentum"] = "none"
        signal["confidence"] = min(signal.get("confidence", 0), 0.29)

    return signal


def _resolve_sku(entity: str, session_id: str) -> str | None:
    """Map a product entity mention to a SKU via semantic search."""
    results = mcp_client.search_products(
        query=entity,
        session_id=session_id,
        agent_name="signal_agent",
        limit=1,
    )
    if results and results[0].get("cosine_distance", 1.0) < 0.35:
        return results[0]["sku"]
    return None


def _save_fused_forecast(
    sku: str,
    baseline_units: int,
    fused_units: int,
    surge_multiplier: float,
    confidence: float,
    horizon_days: int,
) -> None:
    db = firestore.Client(project=config.GCP_PROJECT_ID, database=config.FIRESTORE_DB)
    db.collection("fused_forecasts").document(f"{sku}_latest").set({
        "sku": sku,
        "baseline_units": baseline_units,
        "fused_units": fused_units,
        "surge_multiplier": surge_multiplier,
        "confidence": confidence,
        "horizon_days": horizon_days,
        "computed_at": firestore.SERVER_TIMESTAMP,
    })


def run(session_id: str, sku: str | None = None, hours: int = 24) -> dict[str, Any]:
    """
    Run the signal extraction flow:
    1. Fetch raw posts from MCP
    2. Extract signals with Gemini
    3. Map entity to SKU
    4. Fuse with ARIMA baseline (deterministic)
    5. Save fused forecast
    """
    from gs_api.sse import emit_tool_call, emit_decision

    t0 = time.time()
    posts = mcp_client.get_social_signals(session_id, "signal_agent", sku=sku, hours=hours)
    emit_tool_call(
        session_id, "signal_agent", "get_social_signals",
        {"sku": sku, "hours": hours}, f"{len(posts)} posts", (time.time() - t0) * 1000
    )

    results = []
    for post in posts:
        post_text = post.get("post_text", "")
        if not post_text:
            continue

        t1 = time.time()
        try:
            raw_signal = _extract_signal_from_post(post_text)
        except (json.JSONDecodeError, Exception):
            continue

        emit_tool_call(
            session_id, "signal_agent", "extract_signal",
            {"post_id": post.get("post_id")},
            f"entity={raw_signal.get('entity')} momentum={raw_signal.get('momentum')} conf={raw_signal.get('confidence', 0):.2f}",
            (time.time() - t1) * 1000
        )

        if raw_signal.get("momentum") == "none" or not raw_signal.get("entity"):
            continue

        # Resolve SKU
        resolved_sku = sku or _resolve_sku(raw_signal["entity"], session_id)
        if not resolved_sku:
            continue

        # Fetch ARIMA baseline
        forecast_data = mcp_client.get_forecast(resolved_sku, session_id, "signal_agent")
        baseline_units = forecast_data.get("baseline_units", 0)

        # Deterministic fusion — no LLM
        signal_obj = SocialSignal(
            sku=resolved_sku,
            momentum=raw_signal["momentum"],
            confidence=raw_signal["confidence"],
            corroborating_sources=1,
            signal_age_hours=0.0,
        )
        fusion_result = fuse(baseline_units, signal_obj)

        # Persist fused forecast
        _save_fused_forecast(
            sku=resolved_sku,
            baseline_units=fusion_result.baseline_units,
            fused_units=fusion_result.fused_units,
            surge_multiplier=fusion_result.surge_multiplier,
            confidence=fusion_result.confidence,
            horizon_days=fusion_result.horizon_days,
        )

        emit_decision(
            session_id, "signal_agent",
            f"fused_forecast_computed for {resolved_sku}",
            f"baseline={baseline_units} fused={fusion_result.fused_units} multiplier={fusion_result.surge_multiplier:.2f}x",
            fusion_result.confidence,
        )

        results.append({
            "post_id": post.get("post_id"),
            "sku": resolved_sku,
            "entity": raw_signal["entity"],
            "momentum": raw_signal["momentum"],
            "confidence": raw_signal["confidence"],
            "baseline_units": fusion_result.baseline_units,
            "fused_units": fusion_result.fused_units,
            "surge_multiplier": fusion_result.surge_multiplier,
            "capped": fusion_result.capped,
            "detail": fusion_result.detail,
        })

    return {"processed_posts": len(posts), "signals_fired": len(results), "results": results}
