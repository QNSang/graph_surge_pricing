"""Shared fixtures.

Integration/E2E tests run against TEST_DATABASE_URL (never the dev database). The schema is rebuilt from the
Alembic migrations once per test session and seeded with a small synthetic snapshot set, so tests are fast and
independent of the active dataset release.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _env_file_value(name: str) -> str | None:
    env = BACKEND_ROOT / ".env"
    if not env.exists():
        return None
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return None


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or _env_file_value("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    # Must happen before app modules cache their settings / engine.
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

OPERATOR = {"Authorization": "Bearer demo-operator-token"}
VIEWER = {"Authorization": "Bearer demo-viewer-token"}


def _reset_schema(url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, make_url, text

    if not make_url(url).database.endswith("_test"):
        raise RuntimeError(f"Refusing to reset non-test database: {make_url(url).database}")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "app" / "db" / "migrations"))
    cfg.attributes["url"] = url
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def seeded():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not configured")
    try:
        _reset_schema(TEST_DATABASE_URL)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL test database unavailable: {exc}")
    from app.db.session import get_sessionmaker
    from tests.fixtures.seed import seed

    with get_sessionmaker()() as session:
        return seed(session)


@pytest.fixture
def db(seeded):
    from app.db.session import get_sessionmaker

    with get_sessionmaker()() as session:
        yield session


@pytest.fixture(scope="session")
def client(seeded):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def demo_session(client) -> str:
    r = client.post("/api/v1/demo-sessions", headers=OPERATOR, json={"name": f"t-{uuid.uuid4().hex[:6]}"})
    assert r.status_code == 201, r.text
    return r.json()["demo_session_id"]
