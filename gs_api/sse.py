"""
SSE agent trace broadcaster.
emit() is called from worker threads — uses loop.call_soon_threadsafe() for safety.
subscribe() keep-alive ping sits inside the while loop so it never terminates the stream.
"""
import asyncio
import json
import weakref
from collections import defaultdict
from typing import AsyncGenerator

_queues: dict[str, list[asyncio.Queue]] = defaultdict(list)
_loop: asyncio.AbstractEventLoop | None = None


def _get_loop() -> asyncio.AbstractEventLoop | None:
    global _loop
    try:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.get_event_loop()
        return _loop
    except RuntimeError:
        return None


async def subscribe(session_id: str) -> AsyncGenerator[str, None]:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _queues[session_id].append(q)
    # Capture the running loop for thread-safe emit
    global _loop
    _loop = asyncio.get_running_loop()
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=25)
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                # Keep-alive ping — continues loop, never terminates stream
                yield 'data: {"type":"ping"}\n\n'
    finally:
        try:
            _queues[session_id].remove(q)
        except ValueError:
            pass
        if session_id in _queues and not _queues[session_id]:
            del _queues[session_id]


def _enqueue(q: asyncio.Queue, event: dict) -> None:
    try:
        q.put_nowait(event)
    except asyncio.QueueFull:
        pass


def emit(session_id: str, event_type: str, payload: dict) -> None:
    """Thread-safe emit — safe to call from any worker thread."""
    event = {"type": event_type, **payload}
    loop = _get_loop()
    for q in list(_queues.get(session_id, [])):
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(_enqueue, q, event)
        else:
            try:
                q.put_nowait(event)
            except Exception:
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
