"""
Orchestrator Agent — decomposes intent and delegates. Never touches the database.
For shopper queries: discovery + inventory in parallel, then commerce.
For manager queries: signal extraction, then merchandising.
"""
import json
import sys
import os
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import google.generativeai as genai

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

genai.configure()

SYSTEM_PROMPT = """You are the Orchestrator Agent for Groundswell, an agentic retail platform.

Your role: decompose user intent and delegate to specialized agents.

HARD RULES — you must never break these:
- You do NOT query the database. You have no database client.
- You do NOT set prices or modify prices.
- You do NOT approve payments. That goes through AP2 authorization.
- You do NOT multiply or change forecasts. The fusion math is deterministic.
- You decompose. You delegate. You verify the output and present it to the user.

You receive two enrichment blocks before each user message:
- <enterprise_context>: real-time state — session history, live inventory, social signals, alerts
- <enterprise_knowledge>: organizational knowledge — product graph, entity resolutions, seasonal patterns

Use these blocks to make smarter decisions without extra tool calls. If the context already
contains the inventory level for a SKU, do not call check_inventory again. If the knowledge
block has already resolved "grey runners" to SHOE-PEG41-GRY, use that resolution directly.
If a system alert says stockout is critical, surface that urgency to the user proactively.

For SHOPPER queries (product discovery, buying intent):
1. Check context block for relevant inventory alerts — surface them immediately
2. Check knowledge block for entity resolutions and product relationships
3. Delegate to discovery_agent with pre-resolved constraints
4. Use complementary_skus from knowledge graph for upsell opportunities

For MANAGER queries (inventory, forecasting, replenishment):
1. Check context block for active viral signals before calling signal_agent
2. Check knowledge block for seasonal patterns that may explain trends
3. Delegate to signal_agent, then merchandising_agent

Always be transparent about what each agent is doing. Narrate delegations to the user.
"""

_executor = ThreadPoolExecutor(max_workers=4)


def _classify_intent(message: str, user_type: str) -> dict[str, Any]:
    model = genai.GenerativeModel(config.GEMINI_MODEL)
    prompt = f"""Classify the user's intent. Return only valid JSON.

User type: {user_type}
Message: {message}

Return:
{{
  "intent": "discover_products" | "build_cart" | "check_signals" | "replenish_stock" | "general_query",
  "sku": null or "specific SKU if mentioned",
  "product_query": "natural language product query",
  "wants_to_buy": true or false,
  "manager_id": null or "manager ID if mentioned"
}}"""
    resp = model.generate_content(prompt)
    text = resp.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def run(
    message: str,
    session_id: str,
    user_type: str = "shopper",
    manager_id: str = "manager-001",
    context_block: str = "",
    knowledge_block: str = "",
) -> dict[str, Any]:
    """
    Main orchestration entry point.
    Runs in the same thread but uses parallel execution for independent sub-agent calls.
    """
    from gs_api.sse import emit_delegation, emit_decision
    import agents.discovery as discovery_agent
    import agents.signal_agent as signal_agent_mod
    import agents.commerce as commerce_agent
    import agents.merchandising as merchandising_agent

    t0 = time.time()

    # Prepend context and knowledge blocks to the message for intent classification
    enriched_message = message
    if context_block or knowledge_block:
        enriched_message = f"{context_block}\n{knowledge_block}\n\nUser message: {message}"

    # Classify intent
    try:
        intent = _classify_intent(enriched_message, user_type)
    except (json.JSONDecodeError, Exception):
        intent = {
            "intent": "discover_products" if user_type == "shopper" else "check_signals",
            "sku": None,
            "product_query": message,
            "wants_to_buy": False,
            "manager_id": manager_id,
        }

    emit_decision(session_id, "orchestrator", f"intent={intent['intent']}",
                  message[:80], 0.9)

    # ── SHOPPER FLOW ────────────────────────────────────────────────────────────
    if user_type == "shopper" or intent["intent"] in ("discover_products", "build_cart"):

        emit_delegation(session_id, "orchestrator", "discovery_agent",
                        "semantic product search with constraint extraction")

        # Run discovery (A2A inventory check is embedded inside discovery.run via forecast_stockout)
        discovery_result = discovery_agent.run(
            user_query=intent.get("product_query", message),
            session_id=session_id,
        )

        if not intent.get("wants_to_buy") or not discovery_result.get("recommendations"):
            return {
                "answer": _format_discovery_answer(discovery_result, message),
                "discovery": discovery_result,
                "session_id": session_id,
            }

        # Build cart if shopper wants to buy
        emit_delegation(session_id, "orchestrator", "commerce_agent", "assembling cart")
        recs = discovery_result.get("recommendations", [])
        line_items = [{"sku": r["sku"], "qty": 1} for r in recs[:3]]
        cart_result = commerce_agent.run(
            session_id=session_id,
            line_items=line_items,
            shopper_query=message,
        )

        return {
            "answer": cart_result.get("narration", "Cart assembled."),
            "discovery": discovery_result,
            "cart": cart_result.get("cart"),
            "next_step": "authorize_payment",
            "session_id": session_id,
        }

    # ── MANAGER FLOW ────────────────────────────────────────────────────────────
    emit_delegation(session_id, "orchestrator", "signal_agent",
                    "processing latest social signals")

    signal_result = signal_agent_mod.run(
        session_id=session_id,
        sku=intent.get("sku"),
        hours=24,
    )

    results_with_po = []
    for signal in signal_result.get("results", []):
        sku = signal["sku"]
        emit_delegation(session_id, "orchestrator", "merchandising_agent",
                        f"drafting PO for {sku}")

        po_result = merchandising_agent.run(
            session_id=session_id,
            sku=sku,
            manager_id=intent.get("manager_id") or manager_id,
            fused_units=signal.get("fused_units"),
            baseline_units=signal.get("baseline_units"),
            surge_multiplier=signal.get("surge_multiplier"),
            confidence=signal.get("confidence"),
        )
        results_with_po.append({
            "sku": sku,
            "signal": signal,
            "po": po_result,
        })

    emit_decision(session_id, "orchestrator", "manager_flow_complete",
                  f"{len(results_with_po)} POs drafted", 0.9)

    return {
        "answer": _format_manager_answer(signal_result, results_with_po),
        "signals": signal_result,
        "purchase_orders": results_with_po,
        "session_id": session_id,
    }


def _format_discovery_answer(discovery_result: dict, original_query: str) -> str:
    recs = discovery_result.get("recommendations", [])
    if not recs:
        return "I couldn't find products matching your criteria. Try adjusting your budget or size constraints."
    summary = discovery_result.get("summary", "")
    lines = [summary, ""]
    for i, r in enumerate(recs, 1):
        risk_note = ""
        if r.get("stockout_risk") in ("critical", "high"):
            risk_note = f" ⚠️ Only ~{r.get('days_until_stockout', '?')} days of stock left."
        lines.append(f"{i}. **{r['name']}** — ${r.get('price', '?'):.2f}{risk_note}")
        lines.append(f"   {r.get('reason', '')}")
    return "\n".join(lines)


def _format_manager_answer(signal_result: dict, po_results: list) -> str:
    n_signals = signal_result.get("signals_fired", 0)
    if n_signals == 0:
        return "No significant demand signals detected in the last 24 hours. No purchase orders drafted."
    lines = [f"Detected {n_signals} demand signal(s). Drafted {len(po_results)} purchase order(s) for review.\n"]
    for item in po_results:
        po = item.get("po", {})
        if po.get("success"):
            po_data = po.get("po", {})
            lines.append(
                f"**{po_data.get('product_name')}** — {po_data.get('recommended_qty')} units "
                f"(${po_data.get('total_cost', 0):.2f}) — awaiting your approval."
            )
    return "\n".join(lines)
