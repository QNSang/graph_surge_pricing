"""FastAPI app factory. DEMO/REPLAY only: no route reaches a production pricing gateway."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1 import read, write
from app.core.config import get_policy, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, install_request_middleware, metrics
from app.db.session import get_engine

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title="Graph Surge Recommendation API",
        version="1.0.0",
        description="DEMO/REPLAY backend: serves provider recommendations and records operator decisions. "
        "Decisions are never executed in production (execution_mode=DEMO).",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
        expose_headers=["X-Correlation-ID", "Idempotent-Replayed"],
    )
    install_request_middleware(app)
    install_error_handlers(app)
    app.include_router(read.router, prefix=API_PREFIX)
    app.include_router(write.router, prefix=API_PREFIX)

    @app.get("/health", tags=["ops"])
    def health() -> dict:
        db_ok = True
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            db_ok = False
        policy = get_policy()
        return {
            "status": "ok" if db_ok else "degraded",
            "database": "ok" if db_ok else "unreachable",
            "execution_mode": policy.execution_mode,
            "replay_mode": policy.replay_mode,
            "policy_version": policy.policy_version,
        }

    @app.get("/metrics", tags=["ops"])
    def get_metrics() -> dict:
        return metrics.snapshot()

    return app


app = create_app()
