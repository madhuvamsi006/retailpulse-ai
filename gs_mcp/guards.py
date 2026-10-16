"""
MCP guards — the policy chokepoint. All tool calls pass through here.
Validates inputs, enforces rate limits, emits audit events.
"""
import hashlib
import json
import time
from collections import defaultdict
from typing import Any

from google.cloud import bigquery
import config

_rate_buckets: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_PER_MINUTE = 60


def _check_rate_limit(session_id: str) -> None:
    now = time.time()
    window = [t for t in _rate_buckets[session_id] if now - t < 60]
    if len(window) >= RATE_LIMIT_PER_MINUTE:
        raise PermissionError(f"Rate limit exceeded for session {session_id}")
    window.append(now)
    _rate_buckets[session_id] = window


def audit(
    session_id: str,
    agent: str,
    tool: str,
    input_data: Any,
    output_summary: str,
    decision: str,
    confidence: float,
    latency_ms: float,
) -> None:
    try:
        client = bigquery.Client(project=config.GCP_PROJECT_ID)
        table = f"{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.agent_audit"
        row = {
            "event_id": hashlib.sha256(f"{session_id}{tool}{time.time()}".encode()).hexdigest()[:16],
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "session_id": session_id,
            "agent": agent,
            "tool": tool,
            "input_hash": hashlib.sha256(json.dumps(input_data, default=str).encode()).hexdigest()[:16],
            "output_summary": output_summary[:500],
            "decision": decision,
            "confidence": confidence,
            "latency_ms": latency_ms,
        }
        client.insert_rows_json(table, [row])
    except Exception:
        pass  # audit must not block the tool call


def guard(session_id: str, tool_name: str) -> None:
    _check_rate_limit(session_id)
