"""Merchandising Agent — drafts POs with explicit reasoning. Never submits without human approval."""
import json
import sys
import os
import time
from typing import Any

from agents.gemini_client import get_model, generate, init as _init_gemini

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from agents import mcp_client


_init_gemini()

SYSTEM_PROMPT = """You are the Merchandising Agent for Groundswell.

Your job is to analyze demand signals and draft purchase orders with clear, auditable reasoning.

Rules you MUST follow:
- You draft POs. You do NOT submit them. A human manager must approve every PO.
- You do NOT multiply the fused forecast arbitrarily — the fusion math already accounted for surge.
- Always state: fused demand, lead time, MOQ rounding, and category budget check.
- If the total PO cost exceeds the category budget, flag it and reduce quantity to fit, then explain.
- Be honest about confidence levels. A confidence of 0.81 means you might be wrong.
"""

_CATEGORY_BUDGET = 10_000.0  # default per-category budget cap


def run(
    session_id: str,
    sku: str,
    manager_id: str,
    fused_units: int | None = None,
    baseline_units: int | None = None,
    surge_multiplier: float | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    """Draft a PO for a SKU based on fused forecast. Does NOT submit."""
    from gs_api.sse import emit_tool_call, emit_decision

    # Fetch product and supplier details
    t0 = time.time()
    product = mcp_client.get_product(sku, session_id, "merchandising_agent")
    emit_tool_call(
        session_id, "merchandising_agent", "get_product",
        {"sku": sku}, product.get("name", "not found"), (time.time() - t0) * 1000
    )

    if not product:
        return {"success": False, "error": f"SKU {sku} not found"}

    # If fused units not provided, fetch from MCP
    if fused_units is None:
        t1 = time.time()
        forecast = mcp_client.get_forecast(sku, session_id, "merchandising_agent")
        emit_tool_call(
            session_id, "merchandising_agent", "get_forecast",
            {"sku": sku}, f"baseline={forecast.get('baseline_units')}", (time.time() - t1) * 1000
        )
        baseline_units = forecast.get("baseline_units", 0)
        fused_units = baseline_units  # no signal available

    unit_cost = float(product.get("unit_cost", product.get("price", 0) * 0.5))
    lead_time_days = int(product.get("lead_time_days", 7))
    moq = int(product.get("moq", 24))

    # Round up to MOQ
    qty_before_moq = fused_units
    recommended_qty = max(moq, ((fused_units + moq - 1) // moq) * moq)
    total_cost = recommended_qty * unit_cost

    # Budget check — reduce to fit if over
    budget_flag = False
    if total_cost > _CATEGORY_BUDGET:
        max_qty = int(_CATEGORY_BUDGET / unit_cost)
        max_qty = max(moq, (max_qty // moq) * moq)
        budget_flag = True
        recommended_qty = max_qty
        total_cost = recommended_qty * unit_cost

    # Generate reasoning narrative with Gemini
    model = get_model()
    reasoning_prompt = f"""Write a purchase order justification for a retail manager. Be concise (3-4 sentences).

Product: {product.get('name')} (SKU: {sku})
Baseline ARIMA forecast (7 days): {baseline_units} units
Fused forecast after signal: {fused_units} units
Surge multiplier applied: {surge_multiplier or 'N/A'}x
Signal confidence: {confidence or 'N/A'}
Lead time: {lead_time_days} days
MOQ: {moq} units
Quantity before MOQ rounding: {qty_before_moq}
Final recommended quantity: {recommended_qty} units
Unit cost: ${unit_cost:.2f}
Total PO cost: ${total_cost:.2f}
Budget flag: {'YES — reduced to fit $10,000 category budget' if budget_flag else 'No — within budget'}

Explain why this quantity, how lead time was considered, and state the confidence caveat."""

    reasoning_resp = model.generate_content(reasoning_prompt)
    reasoning = reasoning_resp.text.strip()

    emit_tool_call(
        session_id, "merchandising_agent", "generate_reasoning",
        {"sku": sku, "qty": recommended_qty}, "reasoning generated", 0.0
    )

    # Draft PO via MCP — this does NOT submit to supplier
    t2 = time.time()
    po_result = mcp_client.request_replenishment(
        sku=sku,
        recommended_qty=recommended_qty,
        reasoning=reasoning,
        manager_id=manager_id,
        session_id=session_id,
        agent_name="merchandising_agent",
    )
    emit_tool_call(
        session_id, "merchandising_agent", "request_replenishment",
        {"sku": sku, "qty": recommended_qty},
        f"po_id={po_result.get('po', {}).get('po_id')}" if po_result.get("success") else "failed",
        (time.time() - t2) * 1000,
    )

    if not po_result.get("success"):
        return {"success": False, "error": po_result.get("error", "PO drafting failed")}

    emit_decision(
        session_id, "merchandising_agent",
        f"PO drafted for {sku}",
        f"qty={recommended_qty} cost=${total_cost:.2f} budget_flag={budget_flag}",
        confidence or 0.8,
    )

    return {
        "success": True,
        "po": po_result["po"],
        "reasoning": reasoning,
        "baseline_units": baseline_units,
        "fused_units": fused_units,
        "recommended_qty": recommended_qty,
        "total_cost": total_cost,
        "budget_flag": budget_flag,
        "status": "pending_approval — manager must approve before submission",
    }
