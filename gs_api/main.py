"""
gs-api — Main FastAPI application. Public-facing Cloud Run service.
All data access goes through gs-mcp (internal). All LLM boundaries go through Model Armor.
"""
import sys
import os

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from gs_api.routes.chat import router as chat_router
from gs_api.routes.ap2 import router as ap2_router
from gs_api.routes.dashboard import router as dashboard_router
from gs_api.routes.manager_chat import router as manager_chat_router
import config

app = FastAPI(
    title="Groundswell API",
    description="Two-sided agentic commerce platform. Agents propose. Deterministic code disposes.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if config.APP_ENV == "development" else [os.getenv("FRONTEND_ORIGIN", "")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/chat", tags=["chat"])
app.include_router(ap2_router, prefix="/ap2", tags=["ap2"])
app.include_router(dashboard_router, tags=["dashboard"])
app.include_router(manager_chat_router, tags=["manager-chat"])

# Serve frontend static files if present
_static_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "shopper")
if os.path.isdir(_static_path):
    app.mount("/", StaticFiles(directory=_static_path, html=True), name="shopper_ui")


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok", "service": "gs-api", "env": config.APP_ENV}


@app.get("/api/info", tags=["ops"])
async def info() -> dict:
    return {
        "project": config.GCP_PROJECT_ID,
        "region": config.GCP_REGION,
        "model": config.GEMINI_MODEL,
        "mcp_url": config.MCP_SERVICE_URL,
        "inventory_a2a_url": config.INVENTORY_A2A_URL,
    }


if __name__ == "__main__":
    uvicorn.run(
        "gs_api.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=config.APP_ENV == "development",
    )
