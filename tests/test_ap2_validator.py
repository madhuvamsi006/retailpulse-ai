"""Unit tests for AP2 validator — all 7 reason codes + happy path. Must be 100% passing."""
import base64
import time
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import sys
sys.path.insert(0, "/home/appadmin/groundswell")

from ap2.validator import (
    IntentMandate, CartMandate, validate, sign_cart,
    RejectReason, _compute_cart_hash,
)


def _make_merchant_keys():
    priv = Ed25519PrivateKey.generate()
    priv_b64 = base64.b64encode(priv.private_bytes_raw()).decode()
    pub_b64 = base64.b64encode(priv.public_key().public_bytes_raw()).decode()
    return priv_b64, pub_b64


def _make_intent(budget: float = 200.0, expires_in: float = 300.0) -> IntentMandate:
    return IntentMandate(
        session_id="test-session",
        shopper_id="shopper-1",
        budget_max=budget,
        currency="USD",
        allowed_categories=["running"],
        expires_at=time.time() + expires_in,
        shopper_public_key="placeholder",
        signature="placeholder",
    )


def _make_cart(line_items, total, merchant_priv_b64, merchant_pub_b64) -> CartMandate:
    cart_hash, signature = sign_cart(line_items, merchant_priv_b64)
    return CartMandate(
        intent_mandate_id="test-intent",
        line_items=line_items,
        total=total,
        merchant_id="merchant-1",
        merchant_public_key=merchant_pub_b64,
        signed_at=time.time(),
        cart_hash=cart_hash,
        signature=signature,
    )


# Happy path
def test_valid_cart_approved():
    priv, pub = _make_merchant_keys()
    intent = _make_intent(budget=200.0)
    items = [{"sku": "SHOE-PEG41-GRY", "name": "Pegasus 41", "qty": 1, "unit_price": 139.99}]
    cart = _make_cart(items, 139.99, priv, pub)
    catalog = {"SHOE-PEG41-GRY": 139.99}
    result = validate(intent, cart, catalog)
    assert result.approved is True
    assert result.reason is None


# Reason code 1: CART_HASH_MISMATCH (tampered qty)
def test_cart_hash_mismatch_on_tamper():
    priv, pub = _make_merchant_keys()
    intent = _make_intent(budget=1500.0)
    items = [{"sku": "SHOE-PEG41-GRY", "name": "Pegasus 41", "qty": 1, "unit_price": 139.99}]
    cart = _make_cart(items, 139.99, priv, pub)
    # Tamper: change qty after signing
    cart.line_items[0]["qty"] = 10
    cart.total = 1399.90
    catalog = {"SHOE-PEG41-GRY": 139.99}
    result = validate(intent, cart, catalog)
    assert result.approved is False
    assert result.reason == RejectReason.CART_HASH_MISMATCH
    assert result.mandate_diff is not None


# Reason code 2: BUDGET_EXCEEDED
def test_budget_exceeded():
    priv, pub = _make_merchant_keys()
    intent = _make_intent(budget=100.0)
    items = [{"sku": "SHOE-PEG41-GRY", "name": "Pegasus 41", "qty": 1, "unit_price": 139.99}]
    cart = _make_cart(items, 139.99, priv, pub)
    catalog = {"SHOE-PEG41-GRY": 139.99}
    result = validate(intent, cart, catalog)
    assert result.approved is False
    assert result.reason == RejectReason.BUDGET_EXCEEDED


# Reason code 3: MANDATE_EXPIRED
def test_mandate_expired():
    priv, pub = _make_merchant_keys()
    intent = _make_intent(expires_in=-1)  # already expired
    items = [{"sku": "SHOE-PEG41-GRY", "name": "Pegasus 41", "qty": 1, "unit_price": 139.99}]
    cart = _make_cart(items, 139.99, priv, pub)
    catalog = {"SHOE-PEG41-GRY": 139.99}
    result = validate(intent, cart, catalog)
    assert result.approved is False
    assert result.reason == RejectReason.MANDATE_EXPIRED


# Reason code 4: INVALID_SIGNATURE (corrupted sig)
def test_invalid_signature():
    priv, pub = _make_merchant_keys()
    intent = _make_intent()
    items = [{"sku": "SHOE-PEG41-GRY", "name": "Pegasus 41", "qty": 1, "unit_price": 139.99}]
    cart = _make_cart(items, 139.99, priv, pub)
    cart.signature = base64.b64encode(b"bad_signature_padding_x" * 3).decode()
    catalog = {"SHOE-PEG41-GRY": 139.99}
    result = validate(intent, cart, catalog)
    assert result.approved is False
    assert result.reason == RejectReason.INVALID_SIGNATURE


# Reason code 5: PRICE_DRIFT (>1%)
def test_price_drift():
    priv, pub = _make_merchant_keys()
    intent = _make_intent(budget=200.0)
    items = [{"sku": "SHOE-PEG41-GRY", "name": "Pegasus 41", "qty": 1, "unit_price": 50.00}]
    cart = _make_cart(items, 50.00, priv, pub)
    catalog = {"SHOE-PEG41-GRY": 139.99}  # catalog price != cart price
    result = validate(intent, cart, catalog)
    assert result.approved is False
    assert result.reason == RejectReason.PRICE_DRIFT


# Reason code 6: UNKNOWN_SKU
def test_unknown_sku():
    priv, pub = _make_merchant_keys()
    intent = _make_intent(budget=200.0)
    items = [{"sku": "FAKE-SKU-999", "name": "Ghost Shoe", "qty": 1, "unit_price": 99.99}]
    cart = _make_cart(items, 99.99, priv, pub)
    catalog = {}
    result = validate(intent, cart, catalog)
    assert result.approved is False
    assert result.reason == RejectReason.UNKNOWN_SKU


# Reason code 7: QUANTITY_OVERFLOW
def test_quantity_overflow():
    priv, pub = _make_merchant_keys()
    intent = _make_intent(budget=100_000.0)
    items = [{"sku": "SHOE-PEG41-GRY", "name": "Pegasus 41", "qty": 501, "unit_price": 139.99}]
    cart = _make_cart(items, 501 * 139.99, priv, pub)
    catalog = {"SHOE-PEG41-GRY": 139.99}
    result = validate(intent, cart, catalog)
    assert result.approved is False
    assert result.reason == RejectReason.QUANTITY_OVERFLOW
