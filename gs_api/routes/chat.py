"""Chat router — /chat endpoints with Model Armor screening on every request."""
import asyncio
import sys
import os
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str
    message: str
    user_type: str = "shopper"
    manager_id: str = "manager-001"


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    trace_url: str
    data: dict | None = None


@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    from gs_api.model_armor import screen_prompt, screen_response
    import agents.orchestrator as orchestrator

    # Ingress screen — blocks before model sees it
    try:
        screen_prompt(body.message)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    # ── Enterprise Context Fabric ──────────────────────────────────────────────
    # Assemble real-time context before the agent runs: session history,
    # shopper profile, live inventory, active social signals, system alerts.
    ctx_block = ""
    kb_block = ""
    try:
        from context_fabric.assembler import assemble, append_turn
        from knowledge_fabric.graph import build_knowledge_block, resolve_entities_in_text
        ctx = assemble(
            session_id=body.session_id,
            user_type=body.user_type,
            query=body.message,
            store_id=getattr(body, "store_id", None),
        )
        ctx_block = ctx.to_prompt_block()
        # ── Enterprise Knowledge Fabric ────────────────────────────────────────
        # Resolve product entities in the query and inject knowledge graph context:
        # product relationships, seasonal patterns, supplier intelligence.
        entity_skus = list(resolve_entities_in_text(body.message).values())
        kb_block = build_knowledge_block(entity_skus, body.message)
        # Persist this turn to session history
        append_turn(body.session_id, "user", body.message)
    except Exception:
        pass  # fabric errors never block the agent

    # Run orchestrator in thread (synchronous agent code)
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: orchestrator.run(
                message=body.message,
                session_id=body.session_id,
                user_type=body.user_type,
                manager_id=body.manager_id,
                context_block=ctx_block,
                knowledge_block=kb_block,
            )
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")

    answer = result.get("answer", "")

    # Persist the agent's answer to session history
    try:
        from context_fabric.assembler import append_turn
        append_turn(body.session_id, "assistant", answer)
    except Exception:
        pass

    # Egress screen — blocks before browser sees it
    try:
        screen_response(answer)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    return ChatResponse(
        session_id=body.session_id,
        answer=answer,
        trace_url=f"/chat/stream/{body.session_id}",
        data={k: v for k, v in result.items() if k != "answer"},
    )


@router.get("/stream/{session_id}")
async def stream(session_id: str) -> StreamingResponse:
    from gs_api.sse import subscribe

    async def event_generator() -> AsyncGenerator[str, None]:
        async for chunk in subscribe(session_id):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
