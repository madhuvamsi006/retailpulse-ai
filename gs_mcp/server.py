"""
MCP Server — the only data path. Internal-only Cloud Run service.
All 9 tools are exposed here. Agents never hold a DB client directly.
"""
import time
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from gs_mcp import guards
from gs_mcp.tools import products, inventory, forecasting, signals, orders, analytics

app = FastAPI(title="Groundswell MCP Server", docs_url=None, redoc_url=None)


def _session(request: Request) -> str:
    return request.headers.get("X-Session-Id", "unknown")


def _agent(request: Request) -> str:
    return request.headers.get("X-Agent-Name", "unknown")


# ── Tool 1: search_products ────────────────────────────────────────────────────
class SearchRequest(BaseModel):
    query: str
    budget_max: float | None = None
    size: str | None = None
    width: str | None = None
    category: str | None = None
    limit: int = 10


@app.post("/tools/search_products")
async def tool_search_products(body: SearchRequest, request: Request) -> dict[str, Any]:
    session_id = _session(request)
    guards.guard(session_id, "search_products")
    t0 = time.time()
    result = products.search_products(
        body.query, body.budget_max, body.size, body.width, body.category, body.limit
    )
    guards.audit(session_id, _agent(request), "search_products", body.model_dump(),
                 f"{len(result)} products", "returned", 1.0, (time.time() - t0) * 1000)
    return {"results": result}


# ── Tool 2: get_product ────────────────────────────────────────────────────────
@app.get("/tools/get_product/{sku}")
async def tool_get_product(sku: str, request: Request) -> dict[str, Any]:
    session_id = _session(request)
    guards.guard(session_id, "get_product")
    t0 = time.time()
    result = products.get_product(sku)
    guards.audit(session_id, _agent(request), "get_product", {"sku": sku},
                 "found" if result else "not_found", "returned", 1.0, (time.time() - t0) * 1000)
    if not result:
        raise HTTPException(status_code=404, detail=f"SKU {sku} not found")
    return result


# ── Tool 3: check_inventory ────────────────────────────────────────────────────
@app.get("/tools/check_inventory/{sku}")
async def tool_check_inventory(sku: str, store_id: str | None = None, request: Request = None) -> dict[str, Any]:
    session_id = _session(request)
    guards.guard(session_id, "check_inventory")
    t0 = time.time()
    result = inventory.check_inventory(sku, store_id)
    guards.audit(session_id, _agent(request), "check_inventory", {"sku": sku, "store_id": store_id},
                 f"available={result['available']}", "returned", 1.0, (time.time() - t0) * 1000)
    return result


# ── Tool 4: reserve_stock ──────────────────────────────────────────────────────
class ReserveRequest(BaseModel):
    sku: str
    qty: int
    store_id: str | None = None


@app.post("/tools/reserve_stock")
async def tool_reserve_stock(body: ReserveRequest, request: Request) -> dict[str, Any]:
    session_id = _session(request)
    guards.guard(session_id, "reserve_stock")
    t0 = time.time()
    result = inventory.reserve_stock(body.sku, body.qty, session_id, body.store_id)
    guards.audit(session_id, _agent(request), "reserve_stock", body.model_dump(),
                 "success" if result["success"] else result.get("reason", "failed"),
                 "approved" if result["success"] else "rejected", 1.0, (time.time() - t0) * 1000)
    return result


# ── Tool 5: get_forecast ───────────────────────────────────────────────────────
@app.get("/tools/get_forecast/{sku}")
async def tool_get_forecast(sku: str, horizon_days: int = 7, request: Request = None) -> dict[str, Any]:
    session_id = _session(request)
    guards.guard(session_id, "get_forecast")
    t0 = time.time()
    result = forecasting.get_forecast(sku, horizon_days)
    guards.audit(session_id, _agent(request), "get_forecast", {"sku": sku, "horizon_days": horizon_days},
                 f"baseline={result['baseline_units']}", "returned", 1.0, (time.time() - t0) * 1000)
    return result


# ── Tool 6: forecast_stockout ──────────────────────────────────────────────────
@app.get("/tools/forecast_stockout/{sku}")
async def tool_forecast_stockout(sku: str, store_id: str | None = None, request: Request = None) -> dict[str, Any]:
    session_id = _session(request)
    guards.guard(session_id, "forecast_stockout")
    t0 = time.time()
    result = forecasting.forecast_stockout(sku, store_id)
    guards.audit(session_id, _agent(request), "forecast_stockout", {"sku": sku},
                 f"days={result['days_until_stockout']} urgency={result['urgency']}",
                 "returned", 1.0, (time.time() - t0) * 1000)
    return result


# ── Tool 7: get_social_signals ─────────────────────────────────────────────────
@app.get("/tools/get_social_signals")
async def tool_get_social_signals(sku: str | None = None, hours: int = 24, limit: int = 50, request: Request = None) -> dict[str, Any]:
    session_id = _session(request)
    guards.guard(session_id, "get_social_signals")
    t0 = time.time()
    result = signals.get_social_signals(sku, hours, limit)
    guards.audit(session_id, _agent(request), "get_social_signals", {"sku": sku, "hours": hours},
                 f"{len(result)} signals", "returned", 1.0, (time.time() - t0) * 1000)
    return {"signals": result}


# ── Tool 8: create_cart ────────────────────────────────────────────────────────
class CartRequest(BaseModel):
    line_items: list[dict]


@app.post("/tools/create_cart")
async def tool_create_cart(body: CartRequest, request: Request) -> dict[str, Any]:
    session_id = _session(request)
    guards.guard(session_id, "create_cart")
    t0 = time.time()
    result = orders.create_cart(session_id, body.line_items)
    guards.audit(session_id, _agent(request), "create_cart", body.model_dump(),
                 f"total={result.get('cart', {}).get('total', 0)}" if result["success"] else "failed",
                 "created" if result["success"] else "rejected", 1.0, (time.time() - t0) * 1000)
    return result


# ── Tool 9: request_replenishment ──────────────────────────────────────────────
class ReplenishRequest(BaseModel):
    sku: str
    recommended_qty: int
    reasoning: str
    manager_id: str


@app.post("/tools/request_replenishment")
async def tool_request_replenishment(body: ReplenishRequest, request: Request) -> dict[str, Any]:
    session_id = _session(request)
    guards.guard(session_id, "request_replenishment")
    t0 = time.time()
    result = orders.request_replenishment(
        body.sku, body.recommended_qty, body.reasoning, body.manager_id, session_id
    )
    guards.audit(session_id, _agent(request), "request_replenishment", body.model_dump(),
                 f"po_id={result.get('po', {}).get('po_id', '')}" if result["success"] else "failed",
                 "drafted" if result["success"] else "rejected", 0.9, (time.time() - t0) * 1000)
    return result


# ── Analytics tools (6 additional tools for the analyst agent) ────────────────

class SalesSummaryRequest(BaseModel):
    sku: str | None = None
    category: str | None = None
    store_id: str | None = None
    days: int = 30


@app.post("/tools/get_sales_summary")
async def tool_get_sales_summary(body: SalesSummaryRequest, request: Request) -> dict[str, Any]:
    session_id = _session(request)
    guards.guard(session_id, "get_sales_summary")
    t0 = time.time()
    result = analytics.get_sales_summary(body.sku, body.category, body.store_id, body.days)
    guards.audit(session_id, _agent(request), "get_sales_summary", body.model_dump(),
                 f"{len(result['rows'])} rows", "returned", 1.0, (time.time() - t0) * 1000)
    return result


@app.get("/tools/get_sales_trend/{sku}")
async def tool_get_sales_trend(sku: str, days: int = 30, request: Request = None) -> dict[str, Any]:
    session_id = _session(request)
    guards.guard(session_id, "get_sales_trend")
    t0 = time.time()
    result = analytics.get_sales_trend(sku, days)
    guards.audit(session_id, _agent(request), "get_sales_trend", {"sku": sku, "days": days},
                 f"trend={result['trend']}", "returned", 1.0, (time.time() - t0) * 1000)
    return result


@app.get("/tools/get_category_performance")
async def tool_get_category_performance(days: int = 30, request: Request = None) -> dict[str, Any]:
    session_id = _session(request)
    guards.guard(session_id, "get_category_performance")
    t0 = time.time()
    result = analytics.get_category_performance(days)
    guards.audit(session_id, _agent(request), "get_category_performance", {"days": days},
                 f"{len(result['categories'])} categories", "returned", 1.0, (time.time() - t0) * 1000)
    return result


@app.get("/tools/get_sales_anomalies")
async def tool_get_sales_anomalies(days: int = 14, request: Request = None) -> dict[str, Any]:
    session_id = _session(request)
    guards.guard(session_id, "get_sales_anomalies")
    t0 = time.time()
    result = analytics.get_sales_anomalies(days)
    guards.audit(session_id, _agent(request), "get_sales_anomalies", {"days": days},
                 f"over={len(result['over_performers'])} under={len(result['under_performers'])}",
                 "returned", 1.0, (time.time() - t0) * 1000)
    return result


@app.get("/tools/get_store_comparison")
async def tool_get_store_comparison(sku: str | None = None, days: int = 30, request: Request = None) -> dict[str, Any]:
    session_id = _session(request)
    guards.guard(session_id, "get_store_comparison")
    t0 = time.time()
    result = analytics.get_store_comparison(sku, days)
    guards.audit(session_id, _agent(request), "get_store_comparison", {"sku": sku, "days": days},
                 f"{len(result['stores'])} stores", "returned", 1.0, (time.time() - t0) * 1000)
    return result


@app.get("/tools/get_correlation_signal_sales/{sku}")
async def tool_get_correlation(sku: str, days: int = 14, request: Request = None) -> dict[str, Any]:
    session_id = _session(request)
    guards.guard(session_id, "get_correlation_signal_sales")
    t0 = time.time()
    result = analytics.get_correlation_signal_sales(sku, days)
    guards.audit(session_id, _agent(request), "get_correlation_signal_sales", {"sku": sku, "days": days},
                 f"{len(result['correlation_data'])} days", "returned", 1.0, (time.time() - t0) * 1000)
    return result


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "gs-mcp"}
