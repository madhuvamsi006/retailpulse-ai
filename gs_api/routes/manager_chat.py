"""Manager chat route — conversational analyst for the dashboard."""
import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from gs_api import sse as sse_broadcaster
from gs_api.model_armor import screen_prompt, screen_response

router = APIRouter(prefix="/manager")


class ManagerChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    manager_id: str = "manager"


@router.post("/chat")
async def manager_chat(body: ManagerChatRequest) -> dict[str, Any]:
    session_id = body.session_id or str(uuid.uuid4())

    # Screen the manager's question through Model Armor
    try:
        screen_prompt(body.message)
    except PermissionError as e:
        return {"session_id": session_id, "blocked": True, "detail": str(e)}

    # Enrich with ECF + EKF before the analyst runs
    ctx_block = ""
    kb_block = ""
    try:
        from context_fabric.assembler import assemble, append_turn
        from knowledge_fabric.graph import build_knowledge_block, resolve_entities_in_text
        ctx = assemble(session_id=session_id, user_type="manager", query=body.message)
        ctx_block = ctx.to_prompt_block()
        entity_skus = list(resolve_entities_in_text(body.message).values())
        kb_block = build_knowledge_block(entity_skus, body.message)
        append_turn(session_id, "manager", body.message)
    except Exception:
        pass

    from agents.analyst import run
    enriched_question = f"{ctx_block}\n{kb_block}\n\nManager question: {body.message}" if (ctx_block or kb_block) else body.message
    answer = run(enriched_question, session_id)

    try:
        from context_fabric.assembler import append_turn
        append_turn(session_id, "analyst", answer)
    except Exception:
        pass

    # Screen the answer before returning
    try:
        screen_response(answer)
    except PermissionError as e:
        return {"session_id": session_id, "blocked": True, "detail": str(e)}

    return {"session_id": session_id, "answer": answer, "blocked": False}


@router.get("/chat/stream/{session_id}")
async def manager_chat_stream(session_id: str):
    return EventSourceResponse(sse_broadcaster.subscribe(session_id))
