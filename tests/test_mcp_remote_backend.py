"""Phase 1 wiring: ``_get_backend()`` selects the right backend impl.

These tests don't need Postgres — we monkeypatch ``load_config`` to control
the resolved ``LuploConfig`` and ``create_pool`` to avoid real DB dialing
in the local-fallback case.
"""

from __future__ import annotations

import pytest

import luplo.mcp as mcp_mod
from luplo.config import LuploConfig
from luplo.core.backend.local import LocalBackend
from luplo.core.backend.remote import RemoteBackend


@pytest.fixture(autouse=True)
def _reset_backend_singleton(monkeypatch):
    mcp_mod._backend = None
    yield
    mcp_mod._backend = None


@pytest.mark.asyncio
async def test_remote_backend_selected_when_config_says_remote_and_token_set(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        mcp_mod,
        "load_config",
        lambda: LuploConfig(backend_type="remote", server_url="https://api.luplo.io"),
    )
    monkeypatch.setenv("LUPLO_CLOUD_API_KEY", "lupk_deadbeef")

    backend = await mcp_mod._get_backend()
    assert isinstance(backend, RemoteBackend)


@pytest.mark.asyncio
async def test_remote_backend_friendly_error_when_no_token(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        mcp_mod,
        "load_config",
        lambda: LuploConfig(backend_type="remote", server_url="https://api.luplo.io"),
    )
    monkeypatch.delenv("LUPLO_CLOUD_API_KEY", raising=False)

    with pytest.raises(mcp_mod._RemoteAuthMissing) as ei:
        await mcp_mod._get_backend()
    msg = str(ei.value)
    assert "LUPLO_CLOUD_API_KEY" in msg
    assert "remote" in msg.lower()


@pytest.mark.asyncio
async def test_local_backend_used_by_default(monkeypatch: pytest.MonkeyPatch):
    """No remote config → falls through to LocalBackend (existing behaviour)."""
    monkeypatch.setattr(mcp_mod, "load_config", lambda: LuploConfig())

    sentinel_pool = object()

    async def _fake_create_pool(_url):
        return sentinel_pool

    monkeypatch.setattr(mcp_mod, "create_pool", _fake_create_pool)

    backend = await mcp_mod._get_backend()
    assert isinstance(backend, LocalBackend)
    assert backend.pool is sentinel_pool


@pytest.mark.asyncio
async def test_remote_token_keyring_fallback_when_env_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    """No env var, but keyring has the access token `lps login` would have written."""
    monkeypatch.setattr(
        mcp_mod,
        "load_config",
        lambda: LuploConfig(backend_type="remote", server_url="https://api.luplo.io"),
    )
    monkeypatch.delenv("LUPLO_CLOUD_API_KEY", raising=False)
    monkeypatch.setattr(mcp_mod, "_read_keyring_token", lambda: "jwt-from-lps-login")

    backend = await mcp_mod._get_backend()
    assert isinstance(backend, RemoteBackend)


@pytest.mark.asyncio
async def test_remote_token_env_wins_over_keyring(
    monkeypatch: pytest.MonkeyPatch,
):
    """Both populated → env takes priority (consistent with `lps mcp-config`)."""
    monkeypatch.setattr(
        mcp_mod,
        "load_config",
        lambda: LuploConfig(backend_type="remote", server_url="https://api.luplo.io"),
    )
    monkeypatch.setenv("LUPLO_CLOUD_API_KEY", "lupk_envwins")
    monkeypatch.setattr(mcp_mod, "_read_keyring_token", lambda: "jwt-loses")

    assert mcp_mod._remote_token() == "lupk_envwins"


@pytest.mark.asyncio
async def test_remote_token_friendly_error_when_neither_env_nor_keyring(
    monkeypatch: pytest.MonkeyPatch,
):
    """Updated friendly error mentions BOTH escape hatches."""
    monkeypatch.delenv("LUPLO_CLOUD_API_KEY", raising=False)
    monkeypatch.setattr(mcp_mod, "_read_keyring_token", lambda: None)

    with pytest.raises(mcp_mod._RemoteAuthMissing) as ei:
        mcp_mod._remote_token()
    msg = str(ei.value)
    assert "lps login" in msg
    assert "LUPLO_CLOUD_API_KEY" in msg


@pytest.mark.asyncio
async def test_remote_with_blank_server_url_falls_back_to_local(
    monkeypatch: pytest.MonkeyPatch,
):
    """Belt-and-suspenders: ``type = "remote"`` without ``server_url`` shouldn't
    pretend it's remote — fall through to local rather than throw."""
    monkeypatch.setattr(
        mcp_mod,
        "load_config",
        lambda: LuploConfig(backend_type="remote", server_url=""),
    )

    async def _fake_create_pool(_url):
        return object()

    monkeypatch.setattr(mcp_mod, "create_pool", _fake_create_pool)
    backend = await mcp_mod._get_backend()
    assert isinstance(backend, LocalBackend)
