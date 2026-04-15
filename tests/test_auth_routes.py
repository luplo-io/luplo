"""End-to-end tests for the auth HTTP routes.

Uses FastAPI TestClient against a fresh FastAPI app wired to the test DB.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from luplo.core.actors import create_actor
from luplo.core.backend.local import LocalBackend
from luplo.core.db import create_pool
from luplo.server.auth.oauth import setup_oauth
from luplo.server.auth.password import hash_password
from luplo.server.config import LuploServerSettings
from luplo.server.routes.auth import router as auth_router

JWT_SECRET = "test-jwt-secret-32-bytes-minimum-xxx"


def _make_app(pool: object, settings: LuploServerSettings) -> FastAPI:
    """Minimal FastAPI wiring for auth route tests."""
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-session-secret-" + "x" * 20)
    app.state.pool = pool
    app.state.backend = LocalBackend(pool)  # type: ignore[arg-type]
    app.state.settings = settings
    app.state.oauth = setup_oauth(settings)
    app.include_router(auth_router, prefix="/auth")
    return app


@pytest_asyncio.fixture
async def auth_client(db_url: str) -> AsyncIterator[TestClient]:
    """FastAPI client with a real DB pool + a seeded login user."""
    # Disable auth-disabled mode for these tests so the real JWT flow runs.
    prev_disabled = os.environ.pop("LUPLO_AUTH_DISABLED", None)
    pool = await create_pool(db_url)
    try:
        # Seed: project (dependency for items), login actor.
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO projects (id, name) VALUES (%s, %s)"
                " ON CONFLICT (id) DO NOTHING",
                ("auth-test", "auth-test"),
            )
            await create_actor(
                conn,
                id="00000000-0000-0000-0000-0000000000aa",
                name="Login User",
                email="login@test.com",
                password_hash=hash_password("correcthorsebatterystaple"),
            )
        settings = LuploServerSettings(
            db_url=db_url,
            jwt_secret=JWT_SECRET,
            jwt_ttl_minutes=5,
        )
        app = _make_app(pool, settings)
        with TestClient(app) as client:
            yield client
    finally:
        # Clean up the login actor so the fixture is idempotent across runs.
        async with pool.connection() as conn:
            await conn.execute(
                "DELETE FROM actors WHERE email = %s", ("login@test.com",)
            )
            await conn.execute(
                "DELETE FROM projects WHERE id = %s", ("auth-test",)
            )
        await pool.close()  # type: ignore[attr-defined]
        if prev_disabled is not None:
            os.environ["LUPLO_AUTH_DISABLED"] = prev_disabled


def test_login_page_renders(auth_client: TestClient) -> None:
    resp = auth_client.get("/auth/login")
    assert resp.status_code == 200
    assert "luplo" in resp.text.lower()
    assert "email" in resp.text.lower()


def test_login_success(auth_client: TestClient) -> None:
    resp = auth_client.post(
        "/auth/login",
        data={"email": "login@test.com", "password": "correcthorsebatterystaple"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body
    assert body["email"] == "login@test.com"


def test_login_wrong_password(auth_client: TestClient) -> None:
    resp = auth_client.post(
        "/auth/login",
        data={"email": "login@test.com", "password": "definitelywrong"},
    )
    assert resp.status_code == 401


def test_login_unknown_email(auth_client: TestClient) -> None:
    resp = auth_client.post(
        "/auth/login",
        data={"email": "nobody@test.com", "password": "whatever1234"},
    )
    assert resp.status_code == 401


def test_whoami_requires_auth(auth_client: TestClient) -> None:
    resp = auth_client.get("/auth/whoami")
    assert resp.status_code == 401


def test_whoami_with_token(auth_client: TestClient) -> None:
    login = auth_client.post(
        "/auth/login",
        data={"email": "login@test.com", "password": "correcthorsebatterystaple"},
    )
    token = login.json()["token"]
    resp = auth_client.get(
        "/auth/whoami", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "login@test.com"


def test_token_refresh(auth_client: TestClient) -> None:
    login = auth_client.post(
        "/auth/login",
        data={"email": "login@test.com", "password": "correcthorsebatterystaple"},
    )
    token = login.json()["token"]
    resp = auth_client.post(
        "/auth/token/refresh", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert "token" in resp.json()


def test_logout_clears_cookie(auth_client: TestClient) -> None:
    resp = auth_client.post("/auth/logout")
    assert resp.status_code == 200
    # cookie should be cleared
    assert auth_client.cookies.get("luplo_token") in (None, "")


def test_oauth_disabled_provider_404(auth_client: TestClient) -> None:
    # No GitHub/Google credentials configured in fixture settings.
    resp = auth_client.get("/auth/oauth/github/start", follow_redirects=False)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_domain_filter_matches() -> None:
    from luplo.server.auth.domain_filter import is_allowed_domain

    assert is_allowed_domain("me@example.com", ["example.com"]) is True
    assert is_allowed_domain("me@other.com", ["example.com"]) is False
    assert is_allowed_domain("me@example.com", []) is True  # unrestricted
    assert is_allowed_domain("Me@Example.COM", ["example.com"]) is True
