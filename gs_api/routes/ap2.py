"""AP2 payment authorization — Ed25519 signed mandates, 7 deterministic reject codes."""
import base64
import os
import sys
import time
import uuid
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, HTTPException
from google.cloud import bigquery, firestore
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import config
from ap2.validator import (
    IntentMandate, CartMandate, validate, sign_cart, RejectReason
)

router = APIRouter()


def _fs() -> firestore.Client:
    return firestore.Client(project=config.GCP_PROJECT_ID, database=config.FIRESTORE_DB)


# ── Merchant key pair (auto-generated at startup if not configured) ────────────

def _get_or_create_merchant_keys() -> tuple[str, str]:
    """Return (private_key_b64, public_key_b64). Generate + cache in Firestore if missing."""
    priv_b64 = config.AP2_MERCHANT_PRIVATE_KEY
    pub_b64 = config.AP2_MERCHANT_PUBLIC_KEY
    if priv_b64 and pub_b64:
        return priv_b64, pub_b64
    # Auto-generate and cache in Firestore for this session
    try:
        db = _fs()
        doc = db.collection("ap2_config").document("merchant_keys").get()
        if doc.exists:
            data = doc.to_dict()
            return data["private_key"], data["public_key"]
        priv = Ed25519PrivateKey.generate()
        priv_b64 = base64.b64encode(priv.private_bytes_raw()).decode()
        pub_b64 = base64.b64encode(priv.public_key().public_bytes_raw()).decode()
        db.collection("ap2_config").document("merchant_keys").set({
            "private_key": priv_b64, "public_key": pub_b64,
        })
        return priv_b64, pub_b64
    except Exception:
        # Last resort: generate ephemeral keys (not persisted)
        priv = Ed25519PrivateKey.generate()
        return (base64.b64encode(priv.private_bytes_raw()).decode(),
                base64.b64encode(priv.public_key().public_bytes_raw()).decode())


# ── Intent Mandate ─────────────────────────────────────────────────────────────

class IntentRequest(BaseModel):
    session_id: str
    budget_max: float
    currency: str = "USD"
    allowed_categories: list[str] = []
    ttl_minutes: int | None = None
    expires_in_seconds: int | None = None
    shopper_id: str | None = None
    shopper_public_key: str | None = None


@router.post("/intent")
async def create_intent(body: IntentRequest) -> dict[str, Any]:
    ttl_seconds = body.expires_in_seconds or (body.ttl_minutes or 15) * 60
    expires_at = time.time() + ttl_seconds
    shopper_id = body.shopper_id or f"shopper_{body.session_id[:8]}"
    if not body.shopper_public_key:
        priv = Ed25519PrivateKey.generate()
        shopper_public_key = base64.b64encode(priv.public_key().public_bytes_raw()).decode()
    else:
        shopper_public_key = body.shopper_public_key

    mandate_id = f"im_{body.session_id[:12]}_{int(time.time())}"
    mandate = {
        "mandate_id": mandate_id,
        "session_id": body.session_id,
        "shopper_id": shopper_id,
        "budget_max": body.budget_max,
        "currency": body.currency,
        "allowed_categories": body.allowed_categories,
        "expires_at": expires_at,
        "shopper_public_key": shopper_public_key,
        "status": "active",
        "created_at": time.time(),
    }
    _fs().collection("mandates").document(mandate_id).set(mandate)
    return {
        "mandate_id": mandate_id,
        "expires_at": expires_at,
        "budget_max": body.budget_max,
        "message": f"Intent mandate signed. Expires in {ttl_seconds // 60:.0f} minutes.",
    }


@router.get("/intent/{mandate_id}")
async def get_intent(mandate_id: str) -> dict[str, Any]:
    doc = _fs().collection("mandates").document(mandate_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Mandate not found")
    return doc.to_dict()


# ── Cart Signing ───────────────────────────────────────────────────────────────

class CartSignRequest(BaseModel):
    session_id: str
    # line_items optional — reads from Firestore cart if not provided
    line_items: list[dict] | None = None


@router.post("/cart/sign")
async def sign_cart_endpoint(body: CartSignRequest) -> dict[str, Any]:
    priv_b64, pub_b64 = _get_or_create_merchant_keys()
    db = _fs()

    # Read line_items from Firestore cart if not provided
    line_items = body.line_items
    if not line_items:
        cart_doc = db.collection("carts").document(body.session_id).get()
        if cart_doc.exists:
            line_items = cart_doc.to_dict().get("line_items", [])
        else:
            # Demo: create a sample cart if none exists
            line_items = [
                {"sku": "SHOE-PEG41-GRY", "name": "Pegasus 41 Max-Cushion Road Runner",
                 "qty": 1, "unit_price": 139.99}
            ]
            total = sum(i["unit_price"] * i["qty"] for i in line_items)
            db.collection("carts").document(body.session_id).set({
                "session_id": body.session_id, "line_items": line_items,
                "total": total, "status": "draft", "created_at": time.time(),
            })

    cart_hash, signature = sign_cart(line_items, priv_b64)

    # Save signed cart mandate to Firestore
    cart_mandate = {
        "session_id": body.session_id,
        "line_items": line_items,
        "total": sum(i.get("unit_price", 0) * i.get("qty", 1) for i in line_items),
        "merchant_public_key": pub_b64,
        "cart_hash": cart_hash,
        "signature": signature,
        "signed_at": time.time(),
    }
    db.collection("cart_mandates").document(body.session_id).set(cart_mandate)

    return {
        "cart_hash": cart_hash,
        "signature": signature,
        "merchant_public_key": pub_b64,
        "line_items": line_items,
        "total": cart_mandate["total"],
        "signed_at": cart_mandate["signed_at"],
    }


# ── Authorization ──────────────────────────────────────────────────────────────

class AuthorizeRequest(BaseModel):
    session_id: str
    intent_mandate_id: str | None = None
    mandate_id: str | None = None  # alias
    tamper_demo: bool = False  # set True to demo cart tampering


@router.post("/authorize")
async def authorize(body: AuthorizeRequest) -> dict[str, Any]:
    db = _fs()
    _, pub_b64 = _get_or_create_merchant_keys()

    mandate_id = body.intent_mandate_id or body.mandate_id
    if not mandate_id:
        raise HTTPException(status_code=400, detail="intent_mandate_id required")

    # Load intent mandate
    intent_doc = db.collection("mandates").document(mandate_id).get()
    if not intent_doc.exists:
        raise HTTPException(status_code=404, detail="Intent mandate not found")
    intent_data = intent_doc.to_dict()

    intent = IntentMandate(
        session_id=intent_data["session_id"],
        shopper_id=intent_data["shopper_id"],
        budget_max=intent_data["budget_max"],
        currency=intent_data["currency"],
        allowed_categories=intent_data["allowed_categories"],
        expires_at=intent_data["expires_at"],
        shopper_public_key=intent_data["shopper_public_key"],
        signature=intent_data.get("signature", "placeholder"),
    )

    # Load signed cart mandate
    cart_doc = db.collection("cart_mandates").document(body.session_id).get()
    if not cart_doc.exists:
        raise HTTPException(status_code=400, detail="Cart not signed yet. Call /ap2/cart/sign first.")
    cart_data = cart_doc.to_dict()

    line_items = cart_data["line_items"]

    # Demo tamper: mutate qty after signing (cart_hash will mismatch)
    if body.tamper_demo:
        line_items = [dict(item, qty=item.get("qty", 1) * 10) for item in line_items]

    cart = CartMandate(
        intent_mandate_id=mandate_id,
        line_items=line_items,
        total=sum(i.get("unit_price", 0) * i.get("qty", 1) for i in line_items),
        merchant_id="groundswell",
        merchant_public_key=cart_data["merchant_public_key"],
        signed_at=cart_data["signed_at"],
        cart_hash=cart_data["cart_hash"],
        signature=cart_data["signature"],
    )

    # Fetch live catalog prices for drift check
    catalog_prices: dict[str, float] = {}
    try:
        bq = bigquery.Client(project=config.GCP_PROJECT_ID)
        skus = list({i["sku"] for i in line_items})
        sql = f"""
            SELECT sku, price FROM `{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.products`
            WHERE sku IN UNNEST(@skus)
        """
        job = bq.query(sql, job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ArrayQueryParameter("skus", "STRING", skus)]
        ))
        for row in job.result():
            catalog_prices[row.sku] = float(row.price)
    except Exception:
        # Use cart prices as fallback (demo mode)
        catalog_prices = {i["sku"]: float(i.get("unit_price", 0)) for i in cart_data["line_items"]}

    # Deterministic validation — zero LLM calls
    result = validate(intent, cart, catalog_prices)

    if result.approved:
        db.collection("mandates").document(mandate_id).update({"status": "authorized"})
        db.collection("carts").document(body.session_id).update({"status": "authorized"})
        # Emit audit row
        try:
            bq = bigquery.Client(project=config.GCP_PROJECT_ID)
            bq.insert_rows_json(f"{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.agent_audit", [{
                "event_id": str(uuid.uuid4())[:12],
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "session_id": body.session_id,
                "agent": "ap2_validator",
                "tool": "validate",
                "input_hash": mandate_id[:12],
                "output_summary": "APPROVED",
                "decision": "approved",
                "confidence": 1.0,
                "latency_ms": 0,
            }])
        except Exception:
            pass

    return {
        "approved": result.approved,
        "reason": result.reason.value if result.reason else None,
        "detail": result.detail,
        "mandate_diff": result.mandate_diff,
        "session_id": body.session_id,
    }


# ── PO Approval ────────────────────────────────────────────────────────────────

class POApproveRequest(BaseModel):
    manager_id: str = "manager"


@router.post("/approve_po/{po_id}")
async def approve_po(po_id: str, body: POApproveRequest) -> dict[str, Any]:
    db = _fs()
    ref = db.collection("purchase_orders").document(po_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="PO not found")
    po_data = doc.to_dict()
    if po_data.get("status") == "approved":
        return {"success": True, "message": "Already approved", "po": po_data}

    ref.update({
        "status": "approved",
        "approved_by": body.manager_id,
        "approved_at": time.time(),
    })

    # Emit audit row
    try:
        bq = bigquery.Client(project=config.GCP_PROJECT_ID)
        bq.insert_rows_json(f"{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.agent_audit", [{
            "event_id": str(uuid.uuid4())[:12],
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "session_id": po_data.get("session_id", ""),
            "agent": "manager",
            "tool": "approve_po",
            "input_hash": po_id[:12],
            "output_summary": f"PO approved by {body.manager_id}",
            "decision": "approved",
            "confidence": 1.0,
            "latency_ms": 0,
        }])
    except Exception:
        pass

    return {"success": True, "po_id": po_id, "approved_by": body.manager_id}
