"""Server-side settings (pydantic-settings).

Loaded from environment variables (prefix ``LUPLO_``) and optionally
``luplo-server.toml`` in the working directory. Sensitive values
(``LUPLO_JWT_SECRET``, ``LUPLO_ADMIN_PASSWORD_INITIAL``) are env-only —
never read from TOML.

Distinct from the client ``LuploConfig`` in ``luplo.config``; the server
never imports that module.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, cast

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_TOML_FILENAME = "luplo-server.toml"

# Fields that may only be set via environment variables (never from TOML).
_ENV_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "jwt_secret",
        "admin_password_initial",
        "github_client_secret",
        "google_client_secret",
    }
)


class LuploServerSettings(BaseSettings):
    """Server configuration.

    Priority: env > luplo-server.toml > defaults.

    Sensitive fields are env-only by design (see ``_ENV_ONLY_FIELDS``).
    """

    model_config = SettingsConfigDict(
        env_prefix="LUPLO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ────────────────────────────────────────────────────
    db_url: str = "postgresql://localhost/luplo"

    # ── JWT ─────────────────────────────────────────────────────────
    jwt_secret: str = Field(default="", description="HS256 signing secret (env-only).")
    jwt_alg: str = "HS256"
    jwt_ttl_minutes: int = 60

    # ── Admin seed ──────────────────────────────────────────────────
    admin_email: str = ""
    admin_password_initial: str = Field(default="", description="Env-only.")

    # ── OAuth (optional, auto-enabled when both id + secret present) ─
    github_client_id: str = ""
    github_client_secret: str = Field(default="", description="Env-only.")
    google_client_id: str = ""
    google_client_secret: str = Field(default="", description="Env-only.")

    # ── Policy ──────────────────────────────────────────────────────
    allowed_email_domains: list[str] = Field(default_factory=list)
    auto_create_users: bool = True

    # ── Runtime toggles ─────────────────────────────────────────────
    worker_enabled: bool = False
    base_url: str = "http://localhost:8000"
    session_secret: str = Field(default="", description="For OAuth session state.")

    # ── Derived ─────────────────────────────────────────────────────
    @property
    def github_enabled(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret)

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


def _read_toml(path: Path) -> dict[str, Any]:
    """Read a flat TOML file. Top-level keys only; nested tables are flattened
    by concatenating the keys (e.g. ``[oauth.github] client_id = "..."`` becomes
    ``github_client_id``). Returns an empty dict if the file is missing."""
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

    TOML values fill in defaults; env vars take priority (via pydantic-settings).
    Sensitive fields from ``_ENV_ONLY_FIELDS`` are never taken from TOML.
    """
    toml_path = toml_path or Path.cwd() / SERVER_TOML_FILENAME
    toml_values = _read_toml(toml_path)
    for field in _ENV_ONLY_FIELDS:
        toml_values.pop(field, None)
    return LuploServerSettings(**toml_values)


def fail_fast_check(settings: LuploServerSettings) -> list[str]:
    """Return a list of missing/invalid settings. Empty list = OK."""
    problems: list[str] = []
    if not settings.jwt_secret:
        problems.append("LUPLO_JWT_SECRET is required (generate with 'lp server init-secrets').")
    if settings.jwt_ttl_minutes <= 0:
        problems.append("jwt_ttl_minutes must be positive.")
    if (
        settings.admin_email
        and not settings.admin_password_initial
        and not _admin_exists_hint(settings)
    ):
        problems.append(
            "LUPLO_ADMIN_EMAIL is set but LUPLO_ADMIN_PASSWORD_INITIAL is not — "
            "admin seed will be skipped unless the admin already exists."
        )
    return problems


def _admin_exists_hint(_settings: LuploServerSettings) -> bool:
    """Best-effort hint: we can't query the DB in this sync check. Caller
    treats the warning as informational."""
    return False
