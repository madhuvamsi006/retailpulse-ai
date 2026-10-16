"""SSE agent trace broadcaster — streams every delegation, tool call, and decision live."""
import asyncio
import json
from collections import defaultdict
from typing import AsyncGenerator

_queues: dict[str, list[asyncio.Queue]] = defaultdict(list)


async def subscribe(session_id: str) -> AsyncGenerator[str, None]:
    q: asyncio.Queue = asyncio.Queue()
    _queues[session_id].append(q)
    try:
        while True:
            event = await asyncio.wait_for(q.get(), timeout=30)
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"
    except asyncio.TimeoutError:
        yield "data: {\"type\": \"ping\"}\n\n"
    finally:
        _queues[session_id].remove(q)


def emit(session_id: str, event_type: str, payload: dict) -> None:
    event = {"type": event_type, **payload}
    for q in list(_queues.get(session_id, [])):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def emit_delegation(session_id: str, from_agent: str, to_agent: str, reason: str) -> None:
    emit(session_id, "delegation", {"from": from_agent, "to": to_agent, "reason": reason})


def emit_tool_call(session_id: str, agent: str, tool: str, args: dict, result_summary: str, latency_ms: float) -> None:
    emit(session_id, "tool_call", {
        "agent": agent, "tool": tool, "args": args,
        "result_summary": result_summary, "latency_ms": latency_ms,
    })


def emit_decision(session_id: str, agent: str, decision: str, reason: str, confidence: float) -> None:
    emit(session_id, "decision", {
        "agent": agent, "decision": decision, "reason": reason, "confidence": confidence,
    })


def emit_a2a_hop(session_id: str, target_service: str, method: str) -> None:
    emit(session_id, "a2a_hop", {"target": target_service, "method": method, "boundary": "service"})
