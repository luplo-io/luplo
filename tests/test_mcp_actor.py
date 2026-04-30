"""Tests for ``_resolve_actor`` (MCP-side actor resolution).

Mirrors the pattern in :mod:`tests.test_cli_actor`, but for the MCP
``_resolve_actor`` helper. The same remote-backend rule applies: missing
actor in remote mode is *not* an error — the SaaS server resolves the
caller from the bearer token.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from luplo.mcp import _resolve_actor


def _stub_config(*, actor_id: str = "", backend_type: str = "local") -> Any:
    class _Cfg:
        pass

    cfg = _Cfg()
    cfg.actor_id = actor_id
    cfg.backend_type = backend_type
    return cfg


def test_explicit_uuid_wins() -> None:
    """A real UUID is used as-is, no .luplo lookup."""
    aid = "11111111-2222-3333-4444-555555555555"
    with patch("luplo.mcp.load_config") as lc:
        assert _resolve_actor(aid) == aid
        lc.assert_not_called()


def test_claude_sentinel_falls_back_to_config() -> None:
    """The literal ``"claude"`` triggers .luplo resolution."""
    with patch("luplo.mcp.load_config") as lc:
        lc.return_value = _stub_config(actor_id="cfg-actor", backend_type="local")
        assert _resolve_actor("claude") == "cfg-actor"


def test_local_without_actor_raises() -> None:
    """Local backend with no actor → ValueError (preserves prior behaviour)."""
    with patch("luplo.mcp.load_config") as lc:
        lc.return_value = _stub_config(actor_id="", backend_type="local")
        with pytest.raises(ValueError, match="No actor_id configured"):
            _resolve_actor("claude")


def test_remote_without_actor_returns_empty_string() -> None:
    """Remote backend with no actor → empty string."""
    with patch("luplo.mcp.load_config") as lc:
        lc.return_value = _stub_config(actor_id="", backend_type="remote")
        assert _resolve_actor("claude") == ""


def test_remote_with_actor_returns_configured() -> None:
    """Configured actor in remote mode is still honored."""
    with patch("luplo.mcp.load_config") as lc:
        lc.return_value = _stub_config(actor_id="cfg-actor", backend_type="remote")
        assert _resolve_actor("claude") == "cfg-actor"
