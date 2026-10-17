"""
Orchestrator — decomposes intent and delegates. No database access. No price setting.
Parallel execution: discovery + inventory fan-out for shopper queries.
Intent is inferred from user_type + keywords — no extra LLM round-trip for classification.
"""
import json
import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from agents.gemini_client import get_model, generate, init as _init_gemini
_init_gemini()

SYSTEM_PROMPT = """You are the Orchestrator Agent for Groundswell, an agentic retail platform.

Your role: decompose user intent and delegate to specialized agents.

HARD RULES — you must never break these:
- You do NOT query the database. You have no database client.
- You do NOT set prices or modify prices.
- You do NOT approve payments. That goes through AP2 authorization.
- You decompose. You delegate. You verify output and present it to the user.

You receive enrichment blocks before each user message:
- <enterprise_context>: real-time state — session history, live inventory, social signals
- <enterprise_knowledge>: product graph, entity resolutions, seasonal patterns

Use these to skip redundant tool calls. If context already has inventory levels, don't call again.
"""

_executor = ThreadPoolExecutor(max_workers=8)


def _infer_intent(message: str, user_type: str) -> dict[str, Any]:
    """
    Classify intent from user_type + keywords — no LLM round-trip needed.
    Falls back to LLM only for ambiguous manager queries.
    """
    msg_lower = message.lower()
    buy_words = {"buy", "purchase", "order", "cart", "checkout", "get", "want"}
    if user_type == "shopper":
        wants_to_buy = any(w in msg_lower for w in buy_words)
        return {
            "intent": "build_cart" if wants_to_buy else "discover_products",
            "sku": None,
            "product_query": message,
            "wants_to_buy": wants_to_buy,
        }
    # Manager — use lightweight classification
    restock_words = {"reorder", "replenish", "stock", "po", "purchase order", "supplier"}
    if any(w in msg_lower for w in restock_words):
        return {"intent": "replenish_stock", "sku": None, "product_query": message, "wants_to_buy": False}
    return {"intent": "check_signals", "sku": None, "product_query": message, "wants_to_buy": False}


def run(
    message: str,
    session_id: str,
    user_type: str = "shopper",
    manager_id: str = "manager-001",
    context_block: str = "",
    knowledge_block: str = "",
) -> dict[str, Any]:
    from gs_api.sse import emit_delegation, emit_decision
    import agents.discovery as discovery_agent
    import agents.signal_agent as signal_agent_mod
    import agents.commerce as commerce_agent
    import agents.merchandising as merchandising_agent

    enriched_message = message
    if context_block or knowledge_block:
        enriched_message = f"{context_block}\n{knowledge_block}\n\nUser message: {message}"

    intent = _infer_intent(enriched_message, user_type)
    emit_decision(session_id, "orchestrator", f"intent={intent['intent']}", message[:80], 0.9)

    # ── SHOPPER FLOW ─────────────────────────────────────────────────────────────
    if user_type == "shopper" or intent["intent"] in ("discover_products", "build_cart"):
        emit_delegation(session_id, "orchestrator", "discovery_agent",
                        "semantic product search with constraint extraction")
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

    # ── MANAGER FLOW ──────────────────────────────────────────────────────────────
    emit_delegation(session_id, "orchestrator", "signal_agent", "processing latest social signals")
    signal_result = signal_agent_mod.run(session_id=session_id, sku=intent.get("sku"), hours=24)

    results_with_po = []
    for signal in signal_result.get("results", []):
        sku = signal["sku"]
        emit_delegation(session_id, "orchestrator", "merchandising_agent", f"drafting PO for {sku}")
        po_result = merchandising_agent.run(
            session_id=session_id, sku=sku, manager_id=manager_id,
            fused_units=signal.get("fused_units"),
            baseline_units=signal.get("baseline_units"),
            surge_multiplier=signal.get("surge_multiplier"),
            confidence=signal.get("confidence"),
        )
        results_with_po.append({"sku": sku, "signal": signal, "po": po_result})

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
            days = r.get("days_until_stockout", "?")
            risk_note = f" ⚠ Only ~{days:.0f}d of stock left." if isinstance(days, float) else f" ⚠ Low stock."
        lines.append(f"{i}. **{r['name']}** — ${r.get('price', '?'):.2f}{risk_note}")
        if r.get("reason"):
            lines.append(f"   {r['reason']}")
    return "\n".join(lines)


def _format_manager_answer(signal_result: dict, po_results: list) -> str:
    n = signal_result.get("signals_fired", 0)
    if n == 0:
        return "No significant demand signals in the last 24 hours. No purchase orders drafted."
    lines = [f"Detected {n} demand signal(s). Drafted {len(po_results)} PO(s) for review.\n"]
    for item in po_results:
        po = item.get("po", {})
        if po.get("success"):
            d = po.get("po", {})
            lines.append(f"**{d.get('product_name')}** — {d.get('recommended_qty')} units "
                         f"(${d.get('total_cost', 0):.2f}) — awaiting approval.")
    return "\n".join(lines)
