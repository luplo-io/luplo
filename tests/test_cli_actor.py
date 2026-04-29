"""Tests for ``_cfg_actor`` resolution.

Local backend: missing actor is fatal (Exit(1)).
Remote backend: missing actor is fine (empty string) — the SaaS server
resolves the caller from the bearer token.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
import typer

from luplo.cli import _cfg_actor


def _stub_config(*, actor_id: str = "", backend_type: str = "local") -> Any:
    class _Cfg:
        pass

    cfg = _Cfg()
    cfg.actor_id = actor_id
    cfg.backend_type = backend_type
    return cfg


def test_flag_wins_regardless_of_mode() -> None:
    """An explicit flag always wins, even with no .luplo / no env."""
    with patch("luplo.cli.load_config") as lc:
        lc.return_value = _stub_config(actor_id="", backend_type="local")
        assert _cfg_actor("flag-actor") == "flag-actor"


def test_local_with_actor_returns_actor() -> None:
    with patch("luplo.cli.load_config") as lc:
        lc.return_value = _stub_config(actor_id="local-actor", backend_type="local")
        assert _cfg_actor() == "local-actor"


def test_local_without_actor_exits_one() -> None:
    """Local backend with no actor → Exit(1)."""
    with patch("luplo.cli.load_config") as lc:
        lc.return_value = _stub_config(actor_id="", backend_type="local")
        with pytest.raises(typer.Exit) as exc_info:
            _cfg_actor()
        assert exc_info.value.exit_code == 1


def test_remote_without_actor_returns_empty_string() -> None:
    """Remote backend with no actor → empty string (server resolves from token)."""
    with patch("luplo.cli.load_config") as lc:
        lc.return_value = _stub_config(actor_id="", backend_type="remote")
        assert _cfg_actor() == ""


def test_remote_with_actor_returns_configured_actor() -> None:
    """Even in remote mode, an explicitly configured actor is honored.

    The bearer token is still authoritative server-side, but a configured
    actor in ``.luplo`` is preserved in case the user wants to debug or
    override locally before any payload is sent.
    """
    with patch("luplo.cli.load_config") as lc:
        lc.return_value = _stub_config(actor_id="cfg-actor", backend_type="remote")
        assert _cfg_actor() == "cfg-actor"
