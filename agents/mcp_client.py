"""
MCP Client — calls MCP tool functions directly (in-process).
The gs-mcp Cloud Run service represents the production design (separate internal service).
For the demo, we call the tool functions directly since they share the same image.
All DB access still goes through the tool functions — agents never hold clients directly.
"""
import time
from typing import Any

import config

# ── Commerce tools ──────────────────────────────────────────────────────────────

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
    from gs_mcp.tools.products import search_products as _fn
    from gs_mcp.guards import audit
    t0 = time.time()
    result = _fn(query, budget_max, size, width, category, limit)
    audit(session_id, agent_name, "search_products", {"query": query},
          f"{len(result)} products", "returned", 1.0, (time.time() - t0) * 1000)
    return result


def get_product(sku: str, session_id: str, agent_name: str) -> dict[str, Any]:
    from gs_mcp.tools.products import get_product as _fn
    return _fn(sku) or {}


def check_inventory(
    sku: str, session_id: str, agent_name: str, store_id: str | None = None
) -> dict[str, Any]:
    from gs_mcp.tools.inventory import check_inventory as _fn
    return _fn(sku, store_id)


def reserve_stock(
    sku: str, qty: int, session_id: str, agent_name: str, store_id: str | None = None
) -> dict[str, Any]:
    from gs_mcp.tools.inventory import reserve_stock as _fn
    return _fn(sku, qty, session_id, store_id)


def get_forecast(
    sku: str, session_id: str, agent_name: str, horizon_days: int = 7
) -> dict[str, Any]:
    from gs_mcp.tools.forecasting import get_forecast as _fn
    return _fn(sku, horizon_days)


def forecast_stockout(
    sku: str, session_id: str, agent_name: str, store_id: str | None = None
) -> dict[str, Any]:
    from gs_mcp.tools.forecasting import forecast_stockout as _fn
    return _fn(sku, store_id)


def get_social_signals(
    session_id: str, agent_name: str,
    sku: str | None = None, hours: int = 24, limit: int = 50
) -> list[dict[str, Any]]:
    from gs_mcp.tools.signals import get_social_signals as _fn
    return _fn(sku, hours, limit)


def create_cart(
    line_items: list[dict[str, Any]], session_id: str, agent_name: str
) -> dict[str, Any]:
    from gs_mcp.tools.orders import create_cart as _fn
    return _fn(session_id, line_items)


def request_replenishment(
    sku: str, recommended_qty: int, reasoning: str,
    manager_id: str, session_id: str, agent_name: str
) -> dict[str, Any]:
    from gs_mcp.tools.orders import request_replenishment as _fn
    return _fn(sku, recommended_qty, reasoning, manager_id, session_id)


# ── Analytics tools ─────────────────────────────────────────────────────────────

def get_sales_summary(
    session_id: str, agent_name: str,
    sku: str | None = None, category: str | None = None,
    store_id: str | None = None, days: int = 30
) -> dict[str, Any]:
    from gs_mcp.tools.analytics import get_sales_summary as _fn
    return _fn(sku, category, store_id, days)


def get_sales_trend(sku: str, session_id: str, agent_name: str, days: int = 30) -> dict[str, Any]:
    from gs_mcp.tools.analytics import get_sales_trend as _fn
    return _fn(sku, days)


def get_category_performance(session_id: str, agent_name: str, days: int = 30) -> dict[str, Any]:
    from gs_mcp.tools.analytics import get_category_performance as _fn
    return _fn(days)


def get_sales_anomalies(session_id: str, agent_name: str, days: int = 14) -> dict[str, Any]:
    from gs_mcp.tools.analytics import get_sales_anomalies as _fn
    return _fn(days)


def get_store_comparison(
    session_id: str, agent_name: str,
    sku: str | None = None, days: int = 30
) -> dict[str, Any]:
    from gs_mcp.tools.analytics import get_store_comparison as _fn
    return _fn(sku, days)


def get_correlation_signal_sales(
    sku: str, session_id: str, agent_name: str, days: int = 14
) -> dict[str, Any]:
    from gs_mcp.tools.analytics import get_correlation_signal_sales as _fn
    return _fn(sku, days)
