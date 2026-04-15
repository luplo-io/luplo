"""Configuration loading from ``.luplo`` file, env vars, and CLI flags.

Priority (highest wins): CLI flag → env var → ``.luplo`` file → defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

CONFIG_FILENAME = ".luplo"
DEFAULT_DB_URL = "postgresql://localhost/luplo"


@dataclass(slots=True)
class LuploConfig:
    """Resolved configuration from all sources."""

    db_url: str = DEFAULT_DB_URL
    backend_type: str = "local"
    server_url: str = ""
    project_id: str = ""
    project_name: str = ""
    actor_id: str = ""
    actor_name: str = ""
    actor_email: str = ""


def find_config_file() -> Path | None:
    """Walk up from cwd looking for a ``.luplo`` file."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        candidate = parent / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_config() -> LuploConfig:
    """Load configuration with priority: env var → ``.luplo`` file → defaults.

    CLI flags override at call time (not handled here).
    """
    cfg = LuploConfig()

    # Layer 1: .luplo file
    config_path = find_config_file()
    if config_path:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)

        backend = data.get("backend", {})
        cfg.db_url = backend.get("db_url", cfg.db_url)
        cfg.backend_type = backend.get("type", cfg.backend_type)
        cfg.server_url = backend.get("server_url", cfg.server_url)

        project = data.get("project", {})
        cfg.project_id = project.get("id", cfg.project_id)
        cfg.project_name = project.get("name", cfg.project_name)

        actor = data.get("actor", {})
        cfg.actor_id = actor.get("id", cfg.actor_id)
        cfg.actor_name = actor.get("name", cfg.actor_name)
        cfg.actor_email = actor.get("email", cfg.actor_email)

    # Layer 2: env vars override
    cfg.db_url = os.environ.get("LUPLO_DB_URL", cfg.db_url)
    cfg.project_id = os.environ.get("LUPLO_PROJECT", cfg.project_id)
    cfg.actor_id = os.environ.get("LUPLO_ACTOR_ID", cfg.actor_id)
    cfg.server_url = os.environ.get("LUPLO_SERVER_URL", cfg.server_url)

    return cfg


def write_config(
    path: Path,
    *,
    db_url: str,
    project_id: str,
    project_name: str,
    actor_id: str,
    actor_name: str,
    actor_email: str = "",
    server_url: str = "",
    backend_type: str = "local",
) -> None:
    """Write a ``.luplo`` config file."""
    server_line = f'server_url = "{server_url}"\n' if server_url else ""
    email_line = f'email = "{actor_email}"\n' if actor_email else ""
    content = f"""\
[backend]
type = "{backend_type}"
db_url = "{db_url}"
{server_line}
[project]
id = "{project_id}"
name = "{project_name}"

[actor]
id = "{actor_id}"
name = "{actor_name}"
{email_line}"""
    path.write_text(content)
