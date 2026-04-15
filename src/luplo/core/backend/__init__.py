"""Backend abstraction — Local (direct PG) or Remote (HTTP)."""

from luplo.core.backend.local import LocalBackend
from luplo.core.backend.protocol import Backend

__all__ = ["Backend", "LocalBackend"]
