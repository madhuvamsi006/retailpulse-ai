"""
MCP policy chokepoint — rate limiting and async fire-and-forget audit.
Audit rows are queued and written by a background daemon thread.
The tool call path is never blocked by audit I/O.
"""
import hashlib
import json
import queue
import threading
import time
from collections import defaultdict
from typing import Any

import config

# ── Rate limiting ──────────────────────────────────────────────────────────────
_rate_buckets: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_PER_MINUTE = 60


def _check_rate_limit(session_id: str) -> None:
    now = time.time()
    window = [t for t in _rate_buckets[session_id] if now - t < 60]
    if len(window) >= RATE_LIMIT_PER_MINUTE:
        raise PermissionError(f"Rate limit exceeded for session {session_id}")
    window.append(now)
    _rate_buckets[session_id] = window


# ── Audit — fire-and-forget via background queue ───────────────────────────────
_audit_queue: queue.Queue = queue.Queue(maxsize=500)
_BQ_CLIENT = None


def _get_bq():
    global _BQ_CLIENT
    if _BQ_CLIENT is None:
        from google.cloud import bigquery
        _BQ_CLIENT = bigquery.Client(project=config.GCP_PROJECT_ID)
    return _BQ_CLIENT


def _audit_worker() -> None:
    """Daemon thread: drains audit queue and writes to BigQuery in batches."""
    batch: list[dict] = []
    while True:
        try:
            row = _audit_queue.get(timeout=5)
            batch.append(row)
            # Flush batch when it has 10 rows or queue empties
            if len(batch) >= 10 or _audit_queue.empty():
                try:
                    table = f"{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.agent_audit"
                    _get_bq().insert_rows_json(table, batch)
                except Exception:
                    pass
                batch = []
        except queue.Empty:
            if batch:
                try:
                    table = f"{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.agent_audit"
                    _get_bq().insert_rows_json(table, batch)
                except Exception:
                    pass
                batch = []


_worker_thread = threading.Thread(target=_audit_worker, daemon=True, name="audit-worker")
_worker_thread.start()


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
    """Enqueue an audit row. Never blocks the caller."""
    row = {
        "event_id": hashlib.sha256(f"{session_id}{tool}{time.time()}".encode()).hexdigest()[:16],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": session_id,
        "agent": agent,
        "tool": tool,
        "input_hash": hashlib.sha256(json.dumps(input_data, default=str).encode()).hexdigest()[:16],
        "output_summary": str(output_summary)[:500],
        "decision": decision,
        "confidence": confidence,
        "latency_ms": latency_ms,
    }
    try:
        _audit_queue.put_nowait(row)
    except queue.Full:
        pass  # drop rather than block


def guard(session_id: str, tool_name: str) -> None:
    _check_rate_limit(session_id)
