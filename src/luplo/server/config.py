"""Server-side settings (pydantic-settings).

Loaded from environment variables (prefix ``LUPLO_``) and optionally
``luplo-server.toml`` in the working directory.

Distinct from the client ``LuploConfig`` in ``luplo.config``; the server
never imports that module.

luplo's HTTP server does not authenticate callers. It is intended to
run on a trusted network (localhost, VPN, or behind a reverse proxy
that handles authentication). ``X-Actor`` on write requests, or
``default_actor_id`` as a fallback, tells luplo whose name to stamp on
the audit trail — that is the only identity concept core knows.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, cast

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_TOML_FILENAME = "luplo-server.toml"


class LuploServerSettings(BaseSettings):
    """Server configuration.

    Priority: env > luplo-server.toml > defaults.
    """

    model_config = SettingsConfigDict(
        env_prefix="LUPLO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ────────────────────────────────────────────────────
    db_url: str = "postgresql://localhost/luplo"

    # ── Attribution ─────────────────────────────────────────────────
    # Fallback actor UUID when a request has no X-Actor header. Leaving
    # this empty forces callers to supply X-Actor on every write.
    default_actor_id: str = ""

    # ── Runtime toggles ─────────────────────────────────────────────
    worker_enabled: bool = False
    base_url: str = "http://127.0.0.1:8000"


def _read_toml(path: Path) -> dict[str, Any]:
    """Read a flat TOML file. Top-level keys only; nested tables are flattened
    by concatenating the keys. Returns an empty dict if the file is missing."""
    if not path.is_file():
        return {}
    with open(path, "rb") as f:
        data = tomllib.load(f)
    flat: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, dict):
            sub = cast("dict[str, Any]", v)
            for sub_k, sub_v in sub.items():
                flat[f"{k}_{sub_k}"] = sub_v
        else:
            flat[k] = v
    return flat


def load_settings(toml_path: Path | None = None) -> LuploServerSettings:
    """Load settings from env + optional TOML file.

    TOML values fill in defaults; env vars take priority.
    """
    toml_path = toml_path or Path.cwd() / SERVER_TOML_FILENAME
    toml_values = _read_toml(toml_path)
    return LuploServerSettings(**toml_values)


def fail_fast_check(settings: LuploServerSettings) -> list[str]:
    """Return a list of missing/invalid settings. Empty list = OK."""
    _ = settings  # no hard requirements after auth removal
    return []
