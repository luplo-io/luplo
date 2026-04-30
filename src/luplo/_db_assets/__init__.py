"""Bundled alembic migration assets shipped inside the wheel.

This package contains the alembic ``env.py`` and the migration scripts
that were previously located at ``db/`` at the repository root. Moving
them under ``src/luplo`` ensures they ride in the PyPI wheel so that
``lp migrate`` can run migrations from an installed package without
requiring a source checkout.

Runtime callers should not import this module directly — use
:func:`luplo._migrate.run_upgrade_head` which builds an alembic
:class:`alembic.config.Config` programmatically against this directory
via ``importlib.resources``.
"""
