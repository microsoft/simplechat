# public_source_access.py
"""Bootstrap-free public discovery boundary configured by its storage owner."""

from collections.abc import Callable


_resolver: Callable[..., list[str]] | None = None


def configure_public_source_resolver(resolver):
    if not callable(resolver):
        raise TypeError("A public source resolver is required.")
    global _resolver
    _resolver = resolver


def get_public_source_workspace_ids(user_id, *, settings=None, user_settings=None):
    if _resolver is None:
        raise RuntimeError("Public source resolution has not been initialized.")
    return _resolver(user_id, settings=settings, user_settings=user_settings)
