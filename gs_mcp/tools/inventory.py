"""MCP tools: inventory check and stock reservation (Firestore atomic transactions)."""
from typing import Any

from google.cloud import firestore
import config


def _fs_client() -> firestore.Client:
    return firestore.Client(project=config.GCP_PROJECT_ID, database=config.FIRESTORE_DB)


def check_inventory(sku: str, store_id: str | None = None) -> dict[str, Any]:
    """Return on-hand, reserved, and available stock for a SKU."""
    db = _fs_client()
    doc_id = f"{sku}_{store_id}" if store_id else sku
    doc = db.collection("inventory").document(doc_id).get()
    if not doc.exists:
        return {"sku": sku, "store_id": store_id, "on_hand": 0, "reserved": 0, "available": 0}
    data = doc.to_dict()
    available = data.get("on_hand", 0) - data.get("reserved", 0)
    return {
        "sku": sku,
        "store_id": store_id or "all",
        "on_hand": data.get("on_hand", 0),
        "reserved": data.get("reserved", 0),
        "available": max(0, available),
    }


def reserve_stock(sku: str, qty: int, session_id: str, store_id: str | None = None) -> dict[str, Any]:
    """
    Atomically reserve stock for a session. Uses Firestore transaction.
    Returns success/failure without side effects on failure.
    """
    db = _fs_client()
    doc_id = f"{sku}_{store_id}" if store_id else sku
    ref = db.collection("inventory").document(doc_id)

    @firestore.transactional
    def _reserve(transaction: firestore.Transaction) -> dict[str, Any]:
        snap = ref.get(transaction=transaction)
        if not snap.exists:
            return {"success": False, "reason": "SKU not found in inventory"}
        data = snap.to_dict()
        available = data.get("on_hand", 0) - data.get("reserved", 0)
        if available < qty:
            return {"success": False, "reason": f"Insufficient stock: {available} available, {qty} requested"}
        transaction.update(ref, {"reserved": firestore.Increment(qty)})
        db.collection("reservations").document(f"{session_id}_{sku}").set({
            "session_id": session_id,
            "sku": sku,
            "qty": qty,
            "store_id": store_id,
        })
        return {"success": True, "reserved": qty, "remaining_available": available - qty}

    transaction = db.transaction()
    return _reserve(transaction)
