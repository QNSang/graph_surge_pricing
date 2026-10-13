"""Stable error codes and the spec §10.1 error envelope."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("surge.errors")

# code -> default HTTP status (spec §10.2 / §10.3)
ERROR_STATUS: dict[str, int] = {
    "INVALID_REQUEST": 400,
    "UNAUTHENTICATED": 401,
    "SCHEMA_VERSION_UNSUPPORTED": 422,
    "SNAPSHOT_NOT_FOUND": 404,
    "PROPOSAL_NOT_FOUND": 404,
    "NOT_FOUND": 404,
    "PROPOSAL_BLOCKED": 422,
    "PROPOSAL_EXPIRED": 422,
    "PROPOSAL_SUPERSEDED": 409,
    "PROPOSAL_VERSION_CONFLICT": 409,
    "POLICY_VERSION_CONFLICT": 409,
    "SNAPSHOT_MISMATCH": 422,
    "RECOMMENDATION_SET_MISMATCH": 422,
    "SURGE_LIMIT_EXCEEDED": 422,
    "INVALID_SURGE_STEP": 422,
    "INVALID_SURGE_PRECISION": 422,
    "REVIEW_REQUIRED": 422,
    "ACTION_NOT_ALLOWED": 422,
    "REASON_REQUIRED": 422,
    "SERIES_UNAVAILABLE": 422,
    "DECISION_ALREADY_EXISTS": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "BATCH_PLAN_EXPIRED": 409,
    "PERMISSION_DENIED": 403,
    "SESSION_NOT_FOUND": 404,
    "PROVIDER_OUTPUT_INVALID": 422,
    "INTERNAL_ERROR": 500,
}


class AppError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status = status or ERROR_STATUS.get(code, 400)


def error_body(code: str, message: str, details: dict | None, correlation_id: str | None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}, "correlation_id": correlation_id}}


def _cid(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        request.state.error_code = exc.code
        return JSONResponse(error_body(exc.code, exc.message, exc.details, _cid(request)), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        request.state.error_code = "INVALID_REQUEST"
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(
            error_body("INVALID_REQUEST", "Request validation failed.", {"errors": errors}, _cid(request)),
            status_code=400,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = "NOT_FOUND" if exc.status_code == 404 else "INVALID_REQUEST"
        request.state.error_code = code
        return JSONResponse(error_body(code, str(exc.detail), None, _cid(request)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error", extra={"correlation_id": _cid(request)})
        request.state.error_code = "INTERNAL_ERROR"
        return JSONResponse(error_body("INTERNAL_ERROR", "Internal error.", None, _cid(request)), status_code=500)
