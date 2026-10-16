"""MCP tools: cart management and purchase order drafting."""
import time
import hashlib
from typing import Any

from google.cloud import firestore
import config


def _fs() -> firestore.Client:
    return firestore.Client(project=config.GCP_PROJECT_ID, database=config.FIRESTORE_DB)


def create_cart(session_id: str, line_items: list[dict]) -> dict[str, Any]:
    """
    Create or update a cart. Re-reads prices from catalog — never trusts caller prices.
    line_items: [{sku, qty}]
    """
    from gs_mcp.tools.products import get_product
    db = _fs()

    resolved_items = []
    total = 0.0
    for item in line_items:
        product = get_product(item["sku"])
        if not product:
            return {"success": False, "error": f"SKU {item['sku']} not found"}
        unit_price = float(product["price"])
        qty = int(item["qty"])
        resolved_items.append({
            "sku": item["sku"],
            "name": product["name"],
            "qty": qty,
            "unit_price": unit_price,
            "line_total": round(unit_price * qty, 2),
        })
        total += unit_price * qty

    cart = {
        "session_id": session_id,
        "line_items": resolved_items,
        "total": round(total, 2),
        "created_at": time.time(),
        "status": "draft",
    }
    db.collection("carts").document(session_id).set(cart)
    return {"success": True, "cart": cart}


def get_cart(session_id: str) -> dict[str, Any] | None:
    db = _fs()
    doc = db.collection("carts").document(session_id).get()
    return doc.to_dict() if doc.exists else None


def request_replenishment(
    sku: str,
    recommended_qty: int,
    reasoning: str,
    manager_id: str,
    session_id: str,
) -> dict[str, Any]:
    """
    Draft a PO for manager approval. Does NOT submit to supplier — requires Approve action.
    """
    from gs_mcp.tools.products import get_product
    db = _fs()

    product = get_product(sku)
    if not product:
        return {"success": False, "error": f"SKU {sku} not found"}

    supplier_id = product.get("supplier_id", "unknown")

    po = {
        "po_id": hashlib.sha256(f"{sku}{session_id}{time.time()}".encode()).hexdigest()[:12],
        "sku": sku,
        "product_name": product["name"],
        "recommended_qty": recommended_qty,
        "unit_cost": float(product.get("unit_cost", 0)),
        "total_cost": round(float(product.get("unit_cost", 0)) * recommended_qty, 2),
        "supplier_id": supplier_id,
        "reasoning": reasoning,
        "drafted_by_agent": True,
        "manager_id": manager_id,
        "status": "pending_approval",
        "created_at": time.time(),
        "session_id": session_id,
    }
    db.collection("purchase_orders").document(po["po_id"]).set(po)
    return {"success": True, "po": po}
