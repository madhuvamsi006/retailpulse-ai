"""
AP2 validator — deterministic, zero LLM calls.
Validates Cart Mandates against Intent Mandates.
"""
import hashlib
import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.exceptions import InvalidSignature
import base64


class RejectReason(str, Enum):
    CART_HASH_MISMATCH = "CART_HASH_MISMATCH"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    MANDATE_EXPIRED = "MANDATE_EXPIRED"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    PRICE_DRIFT = "PRICE_DRIFT"
    UNKNOWN_SKU = "UNKNOWN_SKU"
    QUANTITY_OVERFLOW = "QUANTITY_OVERFLOW"


@dataclass
class IntentMandate:
    session_id: str
    shopper_id: str
    budget_max: float
    currency: str
    allowed_categories: list[str]
    expires_at: float  # unix timestamp
    shopper_public_key: str  # base64 Ed25519
    signature: str  # base64 signature over canonical JSON


@dataclass
class CartMandate:
    intent_mandate_id: str
    line_items: list[dict]  # [{sku, name, qty, unit_price}]
    total: float
    merchant_id: str
    merchant_public_key: str  # base64 Ed25519
    signed_at: float
    cart_hash: str  # SHA-256 of canonical line_items JSON
    signature: str  # base64 merchant signature over cart_hash


@dataclass
class ValidationResult:
    approved: bool
    reason: RejectReason | None
    detail: str
    mandate_diff: dict | None = None


def _canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def _compute_cart_hash(line_items: list[dict]) -> str:
    canonical = _canonical_json(line_items)
    return hashlib.sha256(canonical).hexdigest()


def _verify_ed25519(public_key_b64: str, message: bytes, signature_b64: str) -> bool:
    try:
        pub_bytes = base64.b64decode(public_key_b64)
        sig_bytes = base64.b64decode(signature_b64)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        pub_key.verify(sig_bytes, message)
        return True
    except (InvalidSignature, Exception):
        return False


def validate(intent: IntentMandate, cart: CartMandate, current_catalog_prices: dict[str, float]) -> ValidationResult:
    """Validate a cart mandate against an intent mandate. No LLM calls."""

    # 1 — mandate not expired
    if time.time() > intent.expires_at:
        return ValidationResult(
            approved=False,
            reason=RejectReason.MANDATE_EXPIRED,
            detail=f"Intent mandate expired at {intent.expires_at}",
        )

    # 2 — verify merchant signature over cart_hash
    if not _verify_ed25519(cart.merchant_public_key, cart.cart_hash.encode(), cart.signature):
        return ValidationResult(
            approved=False,
            reason=RejectReason.INVALID_SIGNATURE,
            detail="Merchant signature verification failed",
        )

    # 3 — recompute cart hash and compare (tamper detection)
    expected_hash = _compute_cart_hash(cart.line_items)
    if expected_hash != cart.cart_hash:
        return ValidationResult(
            approved=False,
            reason=RejectReason.CART_HASH_MISMATCH,
            detail="Cart contents were modified after signing",
            mandate_diff={
                "expected_hash": expected_hash,
                "received_hash": cart.cart_hash,
                "line_items": cart.line_items,
            },
        )

    # 4 — verify all SKUs are known and prices haven't drifted > 1%
    for item in cart.line_items:
        sku = item["sku"]
        if sku not in current_catalog_prices:
            return ValidationResult(
                approved=False,
                reason=RejectReason.UNKNOWN_SKU,
                detail=f"SKU {sku} not found in catalog",
            )
        catalog_price = current_catalog_prices[sku]
        cart_price = item["unit_price"]
        drift = abs(catalog_price - cart_price) / catalog_price
        if drift > 0.01:
            return ValidationResult(
                approved=False,
                reason=RejectReason.PRICE_DRIFT,
                detail=f"SKU {sku}: cart price ${cart_price} vs catalog ${catalog_price} ({drift:.1%} drift)",
            )

    # 5 — quantity sanity (per-item max 100, total max 500)
    total_qty = sum(item["qty"] for item in cart.line_items)
    if total_qty > 500 or any(item["qty"] > 100 for item in cart.line_items):
        return ValidationResult(
            approved=False,
            reason=RejectReason.QUANTITY_OVERFLOW,
            detail=f"Total quantity {total_qty} exceeds maximum",
        )

    # 6 — total within intent budget
    if cart.total > intent.budget_max:
        return ValidationResult(
            approved=False,
            reason=RejectReason.BUDGET_EXCEEDED,
            detail=f"Cart total ${cart.total:.2f} exceeds mandate budget ${intent.budget_max:.2f}",
        )

    return ValidationResult(approved=True, reason=None, detail="APPROVED")


def sign_cart(line_items: list[dict], merchant_private_key_b64: str) -> tuple[str, str]:
    """Sign line_items; returns (cart_hash, signature_b64)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    cart_hash = _compute_cart_hash(line_items)
    priv_bytes = base64.b64decode(merchant_private_key_b64)
    priv_key = Ed25519PrivateKey.from_private_bytes(priv_bytes)
    sig = priv_key.sign(cart_hash.encode())
    return cart_hash, base64.b64encode(sig).decode()
