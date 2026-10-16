"""AP2 payment authorization router."""
import base64
import sys
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from google.cloud import firestore

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import config
from ap2.validator import (
    IntentMandate, CartMandate, validate, sign_cart, RejectReason
)

router = APIRouter()


def _fs() -> firestore.Client:
    return firestore.Client(project=config.GCP_PROJECT_ID, database=config.FIRESTORE_DB)


# ── Intent Mandate ─────────────────────────────────────────────────────────────

class IntentRequest(BaseModel):
    session_id: str
    shopper_id: str
    budget_max: float
    currency: str = "USD"
    allowed_categories: list[str] = []
    ttl_minutes: int = 15
    shopper_public_key: str  # base64 Ed25519 public key


class IntentResponse(BaseModel):
    mandate_id: str
    expires_at: float
    message: str


@router.post("/intent", response_model=IntentResponse)
async def create_intent(body: IntentRequest) -> IntentResponse:
    expires_at = time.time() + body.ttl_minutes * 60
    mandate = {
        "mandate_id": f"im_{body.session_id}_{int(time.time())}",
        "session_id": body.session_id,
        "shopper_id": body.shopper_id,
        "budget_max": body.budget_max,
        "currency": body.currency,
        "allowed_categories": body.allowed_categories,
        "expires_at": expires_at,
        "shopper_public_key": body.shopper_public_key,
        "status": "active",
        "created_at": time.time(),
    }
    _fs().collection("mandates").document(mandate["mandate_id"]).set(mandate)
    return IntentResponse(
        mandate_id=mandate["mandate_id"],
        expires_at=expires_at,
        message=f"Intent mandate created. Expires in {body.ttl_minutes} minutes.",
    )


@router.get("/intent/{mandate_id}")
async def get_intent(mandate_id: str) -> dict[str, Any]:
    doc = _fs().collection("mandates").document(mandate_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Mandate not found")
    return doc.to_dict()


# ── Cart Signing ───────────────────────────────────────────────────────────────

class CartSignRequest(BaseModel):
    session_id: str
    line_items: list[dict]  # [{sku, name, qty, unit_price}]


class CartSignResponse(BaseModel):
    cart_hash: str
    signature: str
    merchant_public_key: str
    signed_at: float


@router.post("/cart/sign", response_model=CartSignResponse)
async def sign_cart_endpoint(body: CartSignRequest) -> CartSignResponse:
    if not config.AP2_MERCHANT_PRIVATE_KEY:
        raise HTTPException(status_code=500, detail="Merchant private key not configured")

    cart_hash, signature = sign_cart(body.line_items, config.AP2_MERCHANT_PRIVATE_KEY)
    return CartSignResponse(
        cart_hash=cart_hash,
        signature=signature,
        merchant_public_key=config.AP2_MERCHANT_PUBLIC_KEY,
        signed_at=time.time(),
    )


# ── Authorization ──────────────────────────────────────────────────────────────

class AuthorizeRequest(BaseModel):
    mandate_id: str
    session_id: str
    cart_mandate: dict  # CartMandate fields


class AuthorizeResponse(BaseModel):
    approved: bool
    reason: str | None
    detail: str
    mandate_diff: dict | None = None


@router.post("/authorize", response_model=AuthorizeResponse)
async def authorize(body: AuthorizeRequest) -> AuthorizeResponse:
    # Fetch intent mandate
    doc = _fs().collection("mandates").document(body.mandate_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Intent mandate not found")
    intent_data = doc.to_dict()

    intent = IntentMandate(
        session_id=intent_data["session_id"],
        shopper_id=intent_data["shopper_id"],
        budget_max=intent_data["budget_max"],
        currency=intent_data["currency"],
        allowed_categories=intent_data["allowed_categories"],
        expires_at=intent_data["expires_at"],
        shopper_public_key=intent_data["shopper_public_key"],
        signature=intent_data.get("signature", ""),
    )

    cm = body.cart_mandate
    cart = CartMandate(
        intent_mandate_id=body.mandate_id,
        line_items=cm["line_items"],
        total=cm["total"],
        merchant_id=cm.get("merchant_id", "groundswell"),
        merchant_public_key=cm["merchant_public_key"],
        signed_at=cm["signed_at"],
        cart_hash=cm["cart_hash"],
        signature=cm["signature"],
    )

    # Fetch current catalog prices for drift check
    from agents.mcp_client import get_product
    catalog_prices: dict[str, float] = {}
    for item in cart.line_items:
        sku = item["sku"]
        try:
            product = get_product(sku, body.session_id, "ap2_validator")
            if product:
                catalog_prices[sku] = float(product["price"])
        except Exception:
            pass

    # Deterministic validation — no LLM
    result = validate(intent, cart, catalog_prices)

    if result.approved:
        _fs().collection("mandates").document(body.mandate_id).update({"status": "authorized"})

    return AuthorizeResponse(
        approved=result.approved,
        reason=result.reason.value if result.reason else None,
        detail=result.detail,
        mandate_diff=result.mandate_diff,
    )


# ── Settlement (sandbox) ───────────────────────────────────────────────────────

class SettleRequest(BaseModel):
    mandate_id: str
    session_id: str


@router.post("/settle")
async def settle(body: SettleRequest) -> dict[str, Any]:
    db = _fs()

    # Verify mandate is authorized
    doc = db.collection("mandates").document(body.mandate_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Mandate not found")
    mandate = doc.to_dict()
    if mandate.get("status") != "authorized":
        raise HTTPException(status_code=400, detail="Mandate is not in authorized state")

    # Mark cart settled (sandbox — no real payment processor)
    cart_ref = db.collection("carts").document(body.session_id)
    cart_doc = cart_ref.get()
    if not cart_doc.exists:
        raise HTTPException(status_code=404, detail="Cart not found")

    cart_ref.update({"status": "settled", "settled_at": time.time(), "mandate_id": body.mandate_id})
    db.collection("mandates").document(body.mandate_id).update({"status": "settled"})

    # Release reservations (they become permanent on settle)
    reservations = db.collection("reservations").where("session_id", "==", body.session_id).stream()
    for res in reservations:
        res.reference.update({"status": "settled"})

    return {
        "success": True,
        "mandate_id": body.mandate_id,
        "session_id": body.session_id,
        "status": "settled",
        "note": "Sandbox settlement — no real payment processor",
    }


# ── PO Approval ────────────────────────────────────────────────────────────────

class POApproveRequest(BaseModel):
    manager_id: str
    session_id: str


@router.post("/approve_po/{po_id}")
async def approve_po(po_id: str, body: POApproveRequest) -> dict[str, Any]:
    from gs_mcp.guards import audit

    db = _fs()
    po_ref = db.collection("purchase_orders").document(po_id)
    po_doc = po_ref.get()
    if not po_doc.exists:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    po = po_doc.to_dict()
    if po.get("status") != "pending_approval":
        raise HTTPException(status_code=400, detail=f"PO status is '{po.get('status')}', not pending_approval")

    po_ref.update({
        "status": "approved",
        "approved_by": body.manager_id,
        "approved_at": time.time(),
    })

    # Emit audit row to BigQuery
    audit(
        session_id=body.session_id,
        agent="manager",
        tool="approve_po",
        input_data={"po_id": po_id, "manager_id": body.manager_id},
        output_summary=f"PO {po_id} approved for {po.get('sku')} qty={po.get('recommended_qty')}",
        decision="approved",
        confidence=1.0,
        latency_ms=0,
    )

    return {
        "success": True,
        "po_id": po_id,
        "sku": po.get("sku"),
        "recommended_qty": po.get("recommended_qty"),
        "total_cost": po.get("total_cost"),
        "status": "approved",
        "approved_by": body.manager_id,
    }
