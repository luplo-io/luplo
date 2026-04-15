"""Email-domain allow-list.

Paired with ``auto_create_users``: domain filter enforces "only users from
approved domains may enter", auto_create_users controls whether first-time
visitors are created automatically.
"""

from __future__ import annotations


def is_allowed_domain(email: str, allowed: list[str]) -> bool:
    """Check whether *email* belongs to one of the *allowed* domains.

    An empty *allowed* list means "no restriction" (default for OSS).
    Comparison is case-insensitive.
    """
    if not allowed:
        return True
    email_lower = email.lower()
    return any(email_lower.endswith("@" + d.lower()) for d in allowed)
