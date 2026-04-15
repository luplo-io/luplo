"""PKCE (Proof Key for Code Exchange) helpers for CLI OAuth loopback flow.

The CLI generates a ``code_verifier`` locally, sends the derived
``code_challenge`` (S256) to the OAuth provider, and exchanges the
authorization code plus the original verifier for a token. This prevents
authorization code interception on the loopback redirect.
"""

from __future__ import annotations

import base64
import hashlib
import secrets


def generate_verifier(num_bytes: int = 32) -> str:
    """Generate a random code verifier (base64url-encoded, no padding)."""
    raw = secrets.token_bytes(num_bytes)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_challenge(verifier: str) -> str:
    """Derive the S256 code challenge from the verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_pair() -> tuple[str, str]:
    """Return a ``(verifier, challenge)`` pair for a single OAuth flow."""
    verifier = generate_verifier()
    return verifier, generate_challenge(verifier)
