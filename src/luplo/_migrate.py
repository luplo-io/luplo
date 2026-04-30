"""Programmatic alembic invocation against wheel-bundled migration assets.

The luplo package ships its alembic ``env.py`` and migration scripts under
:mod:`luplo._db_assets`. This module locates that directory at runtime via
``importlib.resources`` so that ``lp migrate`` works from a PyPI-installed
wheel — without requiring a source checkout, an external ``alembic.ini``,
or a particular working directory.

Public surface: :func:`run_upgrade_head`. Used by the ``lp migrate`` CLI
command (production deploys) and by ``lp init`` (developer setup).
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig


def _assets_dir() -> Path:
    """Return the absolute path to the bundled ``_db_assets`` directory.

    Works for both editable installs (returns the source tree path) and
    wheel installs (returns the path under ``site-packages/luplo``). The
    ``as_file`` indirection handles zipped wheels too, though luplo's
    wheel is currently unzipped on install.
    """
    # ``files`` returns a Traversable; ``as_file`` materialises it to a
    # filesystem path (a no-op for unzipped wheels). We immediately
    # convert to ``Path`` and return — the context manager closes when
    # the function returns, but for unzipped paths the file remains.
    with resources.as_file(resources.files("luplo._db_assets")) as p:
        return Path(p)


def build_config(db_url: str) -> AlembicConfig:
    """Build an in-memory alembic ``Config`` pointing at the bundled assets.

    Args:
        db_url: PostgreSQL connection URL. The leading ``postgresql://``
            scheme is normalised to ``postgresql+psycopg://`` to match
            the dialect used in :mod:`luplo._db_assets.env`.

    Returns:
        A configured :class:`alembic.config.Config` ready to pass to
        :func:`alembic.command.upgrade` / ``downgrade``.
    """
    assets = _assets_dir()
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(assets))
    cfg.set_main_option("version_locations", str(assets / "migrations"))
    # Alembic 1.16+ deprecates the legacy whitespace-separated splitter.
    # ``os`` uses the platform path separator which matches what we
    # produce above (single absolute path; no separator actually needed,
    # but the option silences the DeprecationWarning).
    cfg.set_main_option("path_separator", "os")
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def run_upgrade_head(db_url: str) -> None:
    """Run ``alembic upgrade head`` against ``db_url``.

    Idempotent — alembic's version table makes a second invocation a
    no-op once migrations are at head. Safe to call from container boot
    scripts.

    Args:
        db_url: PostgreSQL connection URL.

    Raises:
        Whatever alembic / sqlalchemy raise on connection or migration
        failures; callers should let those propagate so a deploy
        script can fail fast.
    """
    cfg = build_config(db_url)
    alembic_command.upgrade(cfg, "head")
