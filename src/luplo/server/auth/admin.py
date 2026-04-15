"""Admin seed — idempotent creation of the admin actor at boot.

Called from the FastAPI lifespan. If ``admin_email`` is set but no matching
actor exists, and ``admin_password_initial`` is provided, creates the actor
with ``is_admin=True``. If the actor already exists but lacks admin rights,
promotes them.
"""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from luplo.core.actors import create_actor, get_actor_by_email, set_admin
from luplo.server.auth.password import hash_password


async def ensure_admin(
    pool: AsyncConnectionPool,
    *,
    email: str,
    password: str | None,
) -> None:
    """Ensure a bootstrap admin actor exists.

    Args:
        pool: Async connection pool.
        email: Admin email (from settings). If empty, this function is a no-op.
        password: Initial password (from env). If empty *and* no actor exists,
            seed is skipped with no error. If the actor already exists, the
            password is never overwritten — use ``lp admin set-password``.
    """
    if not email:
        return

    async with pool.connection() as conn:
        existing = await get_actor_by_email(conn, email)
        if existing:
            if not existing.is_admin:
                await set_admin(conn, existing.id, True)
            return
        if not password:
            return  # no credentials to seed
        await create_actor(
            conn,
            name="Admin",
            email=email,
            role="admin",
            password_hash=hash_password(password),
            is_admin=True,
        )
