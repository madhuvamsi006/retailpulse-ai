"""
gs-inventory-a2a — A2A Inventory Agent service.
Separate Cloud Run service (internal-only). Discovered via /.well-known/agent.json.
Called over the wire by the orchestrator — this is the real A2A hop.
"""
import sys
sys.path.insert(0, "/home/appadmin/groundswell")

import time
from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel

import config
from gs_mcp.tools.inventory import check_inventory
from gs_mcp.tools.forecasting import forecast_stockout

app = FastAPI(title="Groundswell Inventory A2A Agent", docs_url=None)

AGENT_CARD = {
    "name": "gs-inventory-agent",
    "version": "1.0.0",
    "description": "Checks real-time inventory levels and stockout risk across all stores",
    "capabilities": ["check_inventory", "forecast_stockout", "multi_store_summary"],
    "endpoint": config.INVENTORY_A2A_URL,
    "protocol": "A2A/1.0",
}


@app.get("/.well-known/agent.json")
async def agent_card() -> dict:
    return AGENT_CARD


class InventoryRequest(BaseModel):
    skus: list[str]
    store_id: str | None = None
    include_stockout_forecast: bool = True
    session_id: str = "unknown"


@app.post("/a2a/inventory")
async def inventory_check(body: InventoryRequest) -> dict[str, Any]:
    """Main A2A endpoint. Called by orchestrator over the wire."""
    t0 = time.time()
    results = {}
    for sku in body.skus:
        inv = check_inventory(sku, body.store_id)
        entry: dict[str, Any] = {"inventory": inv}
        if body.include_stockout_forecast:
            entry["stockout"] = forecast_stockout(sku, body.store_id)
        results[sku] = entry

    return {
        "results": results,
        "latency_ms": round((time.time() - t0) * 1000, 1),
        "service": "gs-inventory-a2a",
        "boundary": "a2a",
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "gs-inventory-a2a"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
