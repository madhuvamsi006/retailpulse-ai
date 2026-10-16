"""HTTP client used by all agents to call MCP tools. Agents never hold a DB client."""
from typing import Any

import httpx
import config

TIMEOUT = 30.0


def _headers(session_id: str, agent_name: str) -> dict[str, str]:
    return {"X-Session-Id": session_id, "X-Agent-Name": agent_name}


def _base() -> str:
    return config.MCP_SERVICE_URL.rstrip("/")


def search_products(
    query: str,
    session_id: str,
    agent_name: str,
    budget_max: float | None = None,
    size: str | None = None,
    width: str | None = None,
    category: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {"query": query, "limit": limit}
    if budget_max is not None:
        payload["budget_max"] = budget_max
    if size is not None:
        payload["size"] = size
    if width is not None:
        payload["width"] = width
    if category is not None:
        payload["category"] = category

    resp = httpx.post(
        f"{_base()}/tools/search_products",
        json=payload,
        headers=_headers(session_id, agent_name),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def get_product(sku: str, session_id: str, agent_name: str) -> dict[str, Any]:
    resp = httpx.get(
        f"{_base()}/tools/get_product/{sku}",
        headers=_headers(session_id, agent_name),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def check_inventory(
    sku: str,
    session_id: str,
    agent_name: str,
    store_id: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if store_id:
        params["store_id"] = store_id
    resp = httpx.get(
        f"{_base()}/tools/check_inventory/{sku}",
        params=params,
        headers=_headers(session_id, agent_name),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def reserve_stock(
    sku: str,
    qty: int,
    session_id: str,
    agent_name: str,
    store_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"sku": sku, "qty": qty}
    if store_id:
        payload["store_id"] = store_id
    resp = httpx.post(
        f"{_base()}/tools/reserve_stock",
        json=payload,
        headers=_headers(session_id, agent_name),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_forecast(
    sku: str,
    session_id: str,
    agent_name: str,
    horizon_days: int = 7,
) -> dict[str, Any]:
    resp = httpx.get(
        f"{_base()}/tools/get_forecast/{sku}",
        params={"horizon_days": horizon_days},
        headers=_headers(session_id, agent_name),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def forecast_stockout(
    sku: str,
    session_id: str,
    agent_name: str,
    store_id: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if store_id:
        params["store_id"] = store_id
    resp = httpx.get(
        f"{_base()}/tools/forecast_stockout/{sku}",
        params=params,
        headers=_headers(session_id, agent_name),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_social_signals(
    session_id: str,
    agent_name: str,
    sku: str | None = None,
    hours: int = 24,
    limit: int = 50,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"hours": hours, "limit": limit}
    if sku:
        params["sku"] = sku
    resp = httpx.get(
        f"{_base()}/tools/get_social_signals",
        params=params,
        headers=_headers(session_id, agent_name),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("signals", [])


def create_cart(
    line_items: list[dict[str, Any]],
    session_id: str,
    agent_name: str,
) -> dict[str, Any]:
    resp = httpx.post(
        f"{_base()}/tools/create_cart",
        json={"line_items": line_items},
        headers=_headers(session_id, agent_name),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def request_replenishment(
    sku: str,
    recommended_qty: int,
    reasoning: str,
    manager_id: str,
    session_id: str,
    agent_name: str,
) -> dict[str, Any]:
    resp = httpx.post(
        f"{_base()}/tools/request_replenishment",
        json={
            "sku": sku,
            "recommended_qty": recommended_qty,
            "reasoning": reasoning,
            "manager_id": manager_id,
        },
        headers=_headers(session_id, agent_name),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


# ── Analytics tools ────────────────────────────────────────────────────────────

def get_sales_summary(
    session_id: str,
    agent_name: str,
    sku: str | None = None,
    category: str | None = None,
    store_id: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"days": days}
    if sku:
        payload["sku"] = sku
    if category:
        payload["category"] = category
    if store_id:
        payload["store_id"] = store_id
    resp = httpx.post(
        f"{_base()}/tools/get_sales_summary",
        json=payload,
        headers=_headers(session_id, agent_name),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_sales_trend(sku: str, session_id: str, agent_name: str, days: int = 30) -> dict[str, Any]:
    resp = httpx.get(
        f"{_base()}/tools/get_sales_trend/{sku}",
        params={"days": days},
        headers=_headers(session_id, agent_name),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_category_performance(session_id: str, agent_name: str, days: int = 30) -> dict[str, Any]:
    resp = httpx.get(
        f"{_base()}/tools/get_category_performance",
        params={"days": days},
        headers=_headers(session_id, agent_name),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_sales_anomalies(session_id: str, agent_name: str, days: int = 14) -> dict[str, Any]:
    resp = httpx.get(
        f"{_base()}/tools/get_sales_anomalies",
        params={"days": days},
        headers=_headers(session_id, agent_name),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_store_comparison(
    session_id: str,
    agent_name: str,
    sku: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    params: dict[str, Any] = {"days": days}
    if sku:
        params["sku"] = sku
    resp = httpx.get(
        f"{_base()}/tools/get_store_comparison",
        params=params,
        headers=_headers(session_id, agent_name),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_correlation_signal_sales(
    sku: str,
    session_id: str,
    agent_name: str,
    days: int = 14,
) -> dict[str, Any]:
    resp = httpx.get(
        f"{_base()}/tools/get_correlation_signal_sales/{sku}",
        params={"days": days},
        headers=_headers(session_id, agent_name),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()
