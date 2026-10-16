"""Commerce Agent — assembles carts and narrates them to shoppers. Never sets prices."""
import json
import sys
import os
import time
from typing import Any

import google.generativeai as genai

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from agents import mcp_client

genai.configure()

SYSTEM_PROMPT = """You are the Commerce Agent for Groundswell.

Your job is to assemble a shopping cart from products the Discovery Agent has found, and narrate it clearly to the shopper.

Rules you MUST follow:
- You do NOT set prices. Prices are always read from the catalog by the system.
- You do NOT approve payments. Payments go through AP2 authorization.
- You do NOT modify quantities beyond what the shopper requested.
- Your job is to confirm what is in the cart and present it clearly.
- Flag any items with low stock prominently.
"""


def run(
    session_id: str,
    line_items: list[dict[str, Any]],
    shopper_query: str = "",
) -> dict[str, Any]:
    """
    Assemble a cart for the shopper.
    line_items: [{"sku": str, "qty": int}]
    Prices are re-read from the catalog by create_cart — never trusted from caller.
    """
    from gs_api.sse import emit_tool_call, emit_decision

    t0 = time.time()
    cart_result = mcp_client.create_cart(line_items, session_id, "commerce_agent")
    emit_tool_call(
        session_id, "commerce_agent", "create_cart",
        {"line_items": line_items},
        f"total=${cart_result.get('cart', {}).get('total', 0):.2f}" if cart_result.get("success") else "failed",
        (time.time() - t0) * 1000,
    )

    if not cart_result.get("success"):
        return {"success": False, "error": cart_result.get("error", "Cart creation failed")}

    cart = cart_result["cart"]

    # Generate shopper-facing narration
    model = genai.GenerativeModel(config.GEMINI_MODEL)
    narration_prompt = f"""You are a helpful shopping assistant. Narrate this cart to the shopper in a friendly, clear way.

Shopper asked: "{shopper_query}"
Cart contents: {json.dumps(cart['line_items'], default=str)}
Total: ${cart['total']:.2f}

Write 2-3 sentences summarizing what's in the cart, the total, and next steps (they'll need to authorize payment).
Do not make up prices — the prices shown are from the catalog."""

    narration_resp = model.generate_content(narration_prompt)
    narration = narration_resp.text.strip()

    emit_decision(session_id, "commerce_agent", "cart_assembled",
                  f"{len(cart['line_items'])} items, total=${cart['total']:.2f}", 1.0)

    return {
        "success": True,
        "cart": cart,
        "narration": narration,
        "next_step": "Authorize payment via AP2 mandate",
    }
