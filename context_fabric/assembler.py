"""
Enterprise Context Fabric — assembles real-time context before every agent call.
Runs in <200ms. Enriches the agent prompt with live operational state so the
agent starts each turn already knowing the world, not discovering it mid-flight.

Context layers assembled:
  1. Session history     — last N turns of this conversation
  2. Shopper profile     — known preferences (size, width, budget, past purchases)
  3. Inventory snapshot  — live stock for SKUs relevant to the query
  4. Social signals      — trending products and their momentum right now
  5. Store context       — regional/store-specific state if known
  6. System alerts       — any active stockout warnings or surge forecasts
"""
import json
import time
from dataclasses import dataclass, field
from typing import Any

from google.cloud import firestore
import config

HISTORY_TURNS = 5          # how many prior turns to inject
SIGNAL_WINDOW_HOURS = 24   # how fresh signals must be
MAX_INVENTORY_SKUS = 5     # max SKUs to pre-fetch inventory for


@dataclass
class AssembledContext:
    session_id: str
    user_type: str               # "shopper" | "manager"
    session_history: list[dict]  # [{role, content, ts}]
    shopper_profile: dict        # size, width, budget_max, past_skus
    inventory_snapshot: dict     # {sku: {available, urgency}}
    active_signals: list[dict]   # [{sku, momentum, confidence, post_count}]
    store_context: dict          # {store_id, name, region}
    system_alerts: list[str]     # plain-text alerts
    assembled_at: float

    def to_prompt_block(self) -> str:
        """Render context as a structured block injected before the user message."""
        parts = ["<enterprise_context>"]

        if self.session_history:
            parts.append("<session_history>")
            for turn in self.session_history[-HISTORY_TURNS:]:
                parts.append(f"  [{turn['role']}]: {turn['content'][:200]}")
            parts.append("</session_history>")

        if self.shopper_profile and self.user_type == "shopper":
            p = self.shopper_profile
            prefs = []
            if p.get("preferred_size"):
                prefs.append(f"size={p['preferred_size']}")
            if p.get("preferred_width"):
                prefs.append(f"width={p['preferred_width']}")
            if p.get("typical_budget_max"):
                prefs.append(f"typical_budget<=${p['typical_budget_max']}")
            if p.get("past_skus"):
                prefs.append(f"past_purchases={','.join(p['past_skus'][-3:])}")
            if prefs:
                parts.append(f"<shopper_profile>{' | '.join(prefs)}</shopper_profile>")

        if self.inventory_snapshot:
            parts.append("<live_inventory>")
            for sku, inv in self.inventory_snapshot.items():
                urgency = inv.get("urgency", "")
                flag = " ⚠ LOW STOCK" if urgency in ("critical", "high") else ""
                parts.append(f"  {sku}: {inv.get('available', 0)} units available{flag}")
            parts.append("</live_inventory>")

        if self.active_signals:
            parts.append("<trending_now>")
            for sig in self.active_signals[:3]:
                parts.append(
                    f"  {sig['sku']}: momentum={sig['momentum']} "
                    f"confidence={sig.get('confidence', 0):.2f} "
                    f"posts={sig.get('post_count', 0)} in last 24h"
                )
            parts.append("</trending_now>")

        if self.store_context.get("store_id"):
            sc = self.store_context
            parts.append(f"<store_context>store={sc['store_id']} name={sc.get('name','')} region={sc.get('region','')}</store_context>")

        if self.system_alerts:
            parts.append("<system_alerts>")
            for alert in self.system_alerts:
                parts.append(f"  ! {alert}")
            parts.append("</system_alerts>")

        parts.append("</enterprise_context>")
        return "\n".join(parts)


def _fs() -> firestore.Client:
    return firestore.Client(project=config.GCP_PROJECT_ID, database=config.FIRESTORE_DB)


def _load_session_history(db: firestore.Client, session_id: str) -> list[dict]:
    doc = db.collection("sessions").document(session_id).get()
    if not doc.exists:
        return []
    return doc.to_dict().get("history", [])


def _load_shopper_profile(db: firestore.Client, session_id: str) -> dict:
    doc = db.collection("sessions").document(session_id).get()
    if not doc.exists:
        return {}
    data = doc.to_dict()
    return {
        "preferred_size": data.get("preferred_size"),
        "preferred_width": data.get("preferred_width"),
        "typical_budget_max": data.get("typical_budget_max"),
        "past_skus": data.get("past_skus", []),
    }


def _load_active_signals() -> list[dict]:
    """Load high-confidence active signals from the last 24h."""
    try:
        from gs_mcp.tools.signals import get_social_signals
        posts = get_social_signals(hours=SIGNAL_WINDOW_HOURS, limit=50)
        # Aggregate by SKU
        sku_counts: dict[str, dict] = {}
        for p in posts:
            sku = p.get("sku")
            if not sku:
                continue
            if sku not in sku_counts:
                sku_counts[sku] = {"post_count": 0, "total_eng": 0.0}
            sku_counts[sku]["post_count"] += 1
            sku_counts[sku]["total_eng"] += p.get("engagement_score", 0)

        signals = []
        for sku, data in sku_counts.items():
            avg_eng = data["total_eng"] / max(data["post_count"], 1)
            momentum = "high" if avg_eng > 6 and data["post_count"] >= 3 else \
                       "medium" if avg_eng > 3 and data["post_count"] >= 2 else "low"
            signals.append({
                "sku": sku,
                "momentum": momentum,
                "confidence": min(0.95, avg_eng / 10.0),
                "post_count": data["post_count"],
            })
        return sorted(signals, key=lambda s: s["confidence"], reverse=True)
    except Exception:
        return []


def _load_inventory_snapshot(relevant_skus: list[str]) -> dict:
    """Pre-fetch inventory for SKUs likely relevant to this query."""
    if not relevant_skus:
        return {}
    try:
        from gs_mcp.tools.forecasting import forecast_stockout
        snapshot = {}
        for sku in relevant_skus[:MAX_INVENTORY_SKUS]:
            result = forecast_stockout(sku)
            snapshot[sku] = {
                "available": result.get("available_units", 0),
                "days_until_stockout": result.get("days_until_stockout"),
                "urgency": result.get("urgency", "low"),
            }
        return snapshot
    except Exception:
        return {}


def _extract_relevant_skus(query: str, session_history: list[dict]) -> list[str]:
    """Heuristic: find SKU codes mentioned in recent context."""
    import re
    text = query + " ".join(h.get("content", "") for h in session_history[-3:])
    return list(set(re.findall(r"SHOE-[A-Z0-9]+-[A-Z]+", text)))


def _build_system_alerts(inventory_snapshot: dict, active_signals: list[dict]) -> list[str]:
    alerts = []
    for sku, inv in inventory_snapshot.items():
        urgency = inv.get("urgency", "low")
        days = inv.get("days_until_stockout", 99)
        if urgency == "critical":
            alerts.append(f"CRITICAL STOCKOUT: {sku} — {inv['available']} units, ~{days:.0f} days remaining")
        elif urgency == "high":
            alerts.append(f"Low stock alert: {sku} — {days:.0f} days at current velocity")
    for sig in active_signals:
        if sig["momentum"] == "high" and sig["confidence"] > 0.7:
            alerts.append(f"Viral signal detected: {sig['sku']} trending ({sig['post_count']} posts, {sig['confidence']:.0%} confidence)")
    return alerts


def assemble(
    session_id: str,
    user_type: str,
    query: str,
    store_id: str | None = None,
) -> AssembledContext:
    """
    Assemble all context layers. Call this before running any agent.
    Total latency target: <200ms (all reads are point-lookups or small queries).
    """
    db = _fs()

    history = _load_session_history(db, session_id)
    profile = _load_shopper_profile(db, session_id) if user_type == "shopper" else {}
    relevant_skus = _extract_relevant_skus(query, history)
    inventory_snapshot = _load_inventory_snapshot(relevant_skus)
    active_signals = _load_active_signals()

    store_context: dict[str, Any] = {}
    if store_id:
        store_doc = db.collection("stores").document(store_id).get()
        store_context = store_doc.to_dict() if store_doc.exists else {"store_id": store_id}

    alerts = _build_system_alerts(inventory_snapshot, active_signals)

    return AssembledContext(
        session_id=session_id,
        user_type=user_type,
        session_history=history,
        shopper_profile=profile,
        inventory_snapshot=inventory_snapshot,
        active_signals=active_signals,
        store_context=store_context,
        system_alerts=alerts,
        assembled_at=time.time(),
    )


def append_turn(session_id: str, role: str, content: str) -> None:
    """Persist a conversation turn to session history."""
    try:
        db = _fs()
        ref = db.collection("sessions").document(session_id)
        ref.set({
            "history": firestore.ArrayUnion([{
                "role": role,
                "content": content[:500],
                "ts": time.time(),
            }]),
            "last_active": time.time(),
        }, merge=True)
    except Exception:
        pass


def update_shopper_profile(session_id: str, updates: dict) -> None:
    """Update inferred shopper preferences (size, width, budget) from conversation."""
    try:
        db = _fs()
        db.collection("sessions").document(session_id).set(updates, merge=True)
    except Exception:
        pass
