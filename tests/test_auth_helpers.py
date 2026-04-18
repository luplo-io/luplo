"""Unit tests for server auth helpers and server config loading.

Covers:
- ``luplo.server.auth.pkce`` (verifier/challenge derivation)
- ``luplo.server.auth.email`` (LoggingEmailSender + SMTPEmailSender wiring)
- ``luplo.server.auth.oauth`` (provider registration)
- ``luplo.server.auth.admin`` (idempotent admin seed against a real pool)
- ``luplo.server.config`` (env + TOML layering, fail_fast_check)
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool

from luplo.core.actors import get_actor_by_email
from luplo.server.auth import pkce
from luplo.server.auth.admin import ensure_admin
from luplo.server.auth.email import (
    LoggingEmailSender,
    SMTPEmailSender,
    email_sender_from_env,
)
from luplo.server.auth.oauth import setup_oauth
from luplo.server.config import (
    LuploServerSettings,
    fail_fast_check,
    load_settings,
)

# ── PKCE ────────────────────────────────────────────────────────


def test_pkce_verifier_length_and_alphabet() -> None:
    v = pkce.generate_verifier()
    # base64url without padding — must be [A-Za-z0-9_-]
    assert set(v) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert "=" not in v


def test_pkce_challenge_matches_spec() -> None:
    verifier = "abc123"
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    assert pkce.generate_challenge(verifier) == expected


def test_pkce_pair_roundtrips() -> None:
    v, c = pkce.generate_pair()
    assert c == pkce.generate_challenge(v)


# ── Email senders ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_logging_email_sender_writes_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sender = LoggingEmailSender()
    await sender.send(to="x@y.com", subject="Hi", body="hello")
    captured = capsys.readouterr()
    assert "x@y.com" in captured.err
    assert "Hi" in captured.err
    assert "hello" in captured.err


def test_smtp_from_env_requires_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LUPLO_SMTP_HOST", raising=False)
    with pytest.raises(RuntimeError, match="LUPLO_SMTP_HOST"):
        SMTPEmailSender.from_env()


def test_smtp_from_env_requires_from(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUPLO_SMTP_HOST", "smtp.example")
    monkeypatch.delenv("LUPLO_SMTP_FROM", raising=False)
    with pytest.raises(RuntimeError, match="LUPLO_SMTP_FROM"):
        SMTPEmailSender.from_env()


def test_smtp_from_env_happy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUPLO_SMTP_HOST", "smtp.example")
    monkeypatch.setenv("LUPLO_SMTP_FROM", "noreply@example")
    monkeypatch.setenv("LUPLO_SMTP_PORT", "2525")
    monkeypatch.setenv("LUPLO_SMTP_USER", "u")
    monkeypatch.setenv("LUPLO_SMTP_PASSWORD", "p")
    monkeypatch.setenv("LUPLO_SMTP_STARTTLS", "0")
    sender = SMTPEmailSender.from_env()
    assert sender.host == "smtp.example"
    assert sender.port == 2525
    assert sender.user == "u"
    assert sender.use_starttls is False


def test_email_sender_from_env_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LUPLO_EMAIL_BACKEND", raising=False)
    assert isinstance(email_sender_from_env(), LoggingEmailSender)


def test_email_sender_from_env_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUPLO_EMAIL_BACKEND", "smtp")
    monkeypatch.setenv("LUPLO_SMTP_HOST", "smtp.example")
    monkeypatch.setenv("LUPLO_SMTP_FROM", "noreply@example")
    assert isinstance(email_sender_from_env(), SMTPEmailSender)


@pytest.mark.asyncio
async def test_smtp_send_calls_smtplib(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            calls["init"] = (host, port, timeout)

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def starttls(self) -> None:
            calls["starttls"] = True

        def login(self, user: str, password: str) -> None:
            calls["login"] = (user, password)

        def send_message(self, msg: Any) -> None:
            calls["sent"] = msg["To"]

    import luplo.server.auth.email as email_mod

    monkeypatch.setattr(email_mod.smtplib, "SMTP", FakeSMTP)
    sender = SMTPEmailSender(
        host="smtp.example",
        port=587,
        from_addr="noreply@x.com",
        user="u",
        password="p",
        use_starttls=True,
    )
    await sender.send(to="to@x.com", subject="s", body="b")
    assert calls["init"] == ("smtp.example", 587, 30)
    assert calls["starttls"] is True
    assert calls["login"] == ("u", "p")
    assert calls["sent"] == "to@x.com"


# ── OAuth ───────────────────────────────────────────────────────


def test_setup_oauth_empty() -> None:
    settings = LuploServerSettings(jwt_secret="s" * 32)
    oauth = setup_oauth(settings)
    # No providers registered — no attributes github/google.
    assert getattr(oauth, "github", None) is None
    assert getattr(oauth, "google", None) is None


def test_setup_oauth_github_only() -> None:
    settings = LuploServerSettings(
        jwt_secret="s" * 32,
        github_client_id="cid",
        github_client_secret="cs",
    )
    oauth = setup_oauth(settings)
    assert getattr(oauth, "github", None) is not None
    assert getattr(oauth, "google", None) is None


def test_setup_oauth_both() -> None:
    settings = LuploServerSettings(
        jwt_secret="s" * 32,
        github_client_id="cid",
        github_client_secret="cs",
        google_client_id="gid",
        google_client_secret="gs",
    )
    oauth = setup_oauth(settings)
    assert getattr(oauth, "github", None) is not None
    assert getattr(oauth, "google", None) is not None


@pytest.mark.asyncio
async def test_fetch_github_email_picks_primary_verified() -> None:
    from luplo.server.auth.oauth import fetch_github_email

    class FakeResponse:
        def json(self) -> list[dict[str, Any]]:
            return [
                {"email": "other@x.com", "primary": False, "verified": True},
                {"email": "me@x.com", "primary": True, "verified": True},
            ]

    class FakeClient:
        async def get(self, path: str, token: Any) -> FakeResponse:
            return FakeResponse()

    email = await fetch_github_email(FakeClient(), {"tok": "t"})
    assert email == "me@x.com"


@pytest.mark.asyncio
async def test_fetch_github_email_none_when_unverified() -> None:
    from luplo.server.auth.oauth import fetch_github_email

    class FakeResponse:
        def json(self) -> list[dict[str, Any]]:
            return [{"email": "x@y.com", "primary": True, "verified": False}]

    class FakeClient:
        async def get(self, path: str, token: Any) -> FakeResponse:
            return FakeResponse()

    assert await fetch_github_email(FakeClient(), {}) is None


# ── Server config ───────────────────────────────────────────────


def test_load_settings_from_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Sensitive fields must NOT be read from TOML.
    toml = tmp_path / "luplo-server.toml"
    toml.write_text(
        """
db_url = "postgresql://toml-host/luplo"
jwt_secret = "should-be-ignored"
jwt_ttl_minutes = 30
allowed_email_domains = ["example.com"]
"""
    )
    # Ensure no stray env vars leak through.
    for k in list(__import__("os").environ):
        if k.startswith("LUPLO_"):
            monkeypatch.delenv(k, raising=False)
    settings = load_settings(toml_path=toml)
    assert settings.db_url == "postgresql://toml-host/luplo"
    assert settings.jwt_ttl_minutes == 30
    assert settings.allowed_email_domains == ["example.com"]
    # Sensitive field stripped.
    assert settings.jwt_secret == ""


def test_load_settings_nested_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toml = tmp_path / "luplo-server.toml"
    toml.write_text(
        """
[github]
client_id = "cid-from-toml"
"""
    )
    for k in list(__import__("os").environ):
        if k.startswith("LUPLO_"):
            monkeypatch.delenv(k, raising=False)
    settings = load_settings(toml_path=toml)
    assert settings.github_client_id == "cid-from-toml"


def test_load_settings_missing_toml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    # No TOML, no env — defaults apply.
    for k in list(__import__("os").environ):
        if k.startswith("LUPLO_"):
            monkeypatch.delenv(k, raising=False)
    settings = load_settings()
    assert settings.jwt_secret == ""
    assert settings.jwt_ttl_minutes == 60


def test_fail_fast_missing_jwt_secret() -> None:
    s = LuploServerSettings()
    problems = fail_fast_check(s)
    assert any("JWT_SECRET" in p for p in problems)


def test_fail_fast_bad_ttl() -> None:
    s = LuploServerSettings(jwt_secret="x" * 32, jwt_ttl_minutes=0)
    problems = fail_fast_check(s)
    assert any("ttl" in p.lower() for p in problems)


def test_fail_fast_admin_without_password_warns() -> None:
    s = LuploServerSettings(
        jwt_secret="x" * 32,
        admin_email="admin@x.com",
        admin_password_initial="",
    )
    problems = fail_fast_check(s)
    assert any("ADMIN" in p for p in problems)


def test_fail_fast_happy() -> None:
    s = LuploServerSettings(
        jwt_secret="x" * 32,
        jwt_ttl_minutes=60,
    )
    assert fail_fast_check(s) == []


def test_oauth_enabled_properties() -> None:
    s = LuploServerSettings(
        jwt_secret="x" * 32,
        github_client_id="a",
        github_client_secret="b",
    )
    assert s.github_enabled is True
    assert s.google_enabled is False


# ── Admin seed ──────────────────────────────────────────────────


@pytest_asyncio.fixture
async def pool_fixture(db_url: str):  # type: ignore[no-untyped-def]
    pool = AsyncConnectionPool(db_url, open=False)
    await pool.open()
    try:
        yield pool
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_ensure_admin_no_email_is_noop(pool_fixture: AsyncConnectionPool) -> None:
    # Should return without touching the DB.
    await ensure_admin(pool_fixture, email="", password="x" * 20)


@pytest.mark.asyncio
async def test_ensure_admin_creates_when_missing(
    pool_fixture: AsyncConnectionPool,
) -> None:
    email = "admin-seed@test.com"
    async with pool_fixture.connection() as conn:
        await conn.execute("DELETE FROM actors WHERE email = %s", (email,))
    await ensure_admin(pool_fixture, email=email, password="correcthorse12345")
    async with pool_fixture.connection() as conn:
        actor = await get_actor_by_email(conn, email)
        assert actor is not None
        assert actor.is_admin
        await conn.execute("DELETE FROM actors WHERE email = %s", (email,))


@pytest.mark.asyncio
async def test_ensure_admin_promotes_existing(
    pool_fixture: AsyncConnectionPool,
) -> None:
    from luplo.core.actors import create_actor as core_create_actor

    email = "admin-promote@test.com"
    async with pool_fixture.connection() as conn:
        await conn.execute("DELETE FROM actors WHERE email = %s", (email,))
        await core_create_actor(conn, name="Promote Me", email=email)
    await ensure_admin(pool_fixture, email=email, password=None)
    async with pool_fixture.connection() as conn:
        actor = await get_actor_by_email(conn, email)
        assert actor is not None
        assert actor.is_admin
        await conn.execute("DELETE FROM actors WHERE email = %s", (email,))


@pytest.mark.asyncio
async def test_ensure_admin_missing_password_and_missing_actor_noop(
    pool_fixture: AsyncConnectionPool,
) -> None:
    email = f"missing-{pkce.generate_verifier(6)}@test.com"
    # No actor, no password — early return, nothing created.
    await ensure_admin(pool_fixture, email=email, password=None)
    async with pool_fixture.connection() as conn:
        assert await get_actor_by_email(conn, email) is None
