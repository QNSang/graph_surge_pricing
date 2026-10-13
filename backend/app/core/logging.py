"""Structured JSON request logging, correlation ids and in-process metrics (spec §14)."""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
import uuid
from collections import Counter

from fastapi import FastAPI, Request

log = logging.getLogger("surge.request")


class Metrics:
    """Thread-safe counters; latency kept as sum + count per endpoint."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()
        self._latency_ms: Counter[str] = Counter()

    def inc(self, name: str, n: int = 1) -> None:
        with self._lock:
            self._counts[name] += n

    def observe_latency(self, endpoint: str, ms: float) -> None:
        with self._lock:
            self._latency_ms[endpoint] += ms

    def snapshot(self) -> dict:
        with self._lock:
            return {"counters": dict(self._counts), "latency_ms_sum": dict(self._latency_ms)}


metrics = Metrics()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("surge")
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(logging.INFO)
    root.propagate = False


_LOG_FIELDS = ("actor_id", "demo_session_id", "snapshot_id", "proposal_id", "batch_id", "error_code")


def install_request_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def _request_context(request: Request, call_next):
        cid = request.headers.get("X-Correlation-ID") or f"req_{uuid.uuid4().hex[:16]}"
        request.state.correlation_id = cid
        start = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000
        route = request.scope.get("route")
        endpoint = f"{request.method} {getattr(route, 'path', request.url.path)}"
        response.headers["X-Correlation-ID"] = cid
        metrics.inc("api_request_count")
        if response.status_code >= 400:
            metrics.inc("api_error_count")
        metrics.observe_latency(endpoint, ms)
        fields = {
            "correlation_id": cid,
            "endpoint": endpoint,
            "status": response.status_code,
            "duration_ms": round(ms, 2),
        }
        for key in _LOG_FIELDS:
            value = getattr(request.state, key, None)
            if value is not None:
                fields[key] = value
        log.info("request", extra={"fields": fields})
        return response
