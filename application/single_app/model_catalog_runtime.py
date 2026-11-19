# model_catalog_runtime.py
"""Injected catalog snapshots, independent of Flask, settings and Azure bootstrap."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps


_provider = None
_UNSET = object()
_snapshot = ContextVar("model_catalog_snapshot", default=_UNSET)
_pin = ContextVar("model_catalog_pin", default=False)


def configure_catalog_provider(provider):
    global _provider
    _provider = provider


@contextmanager
def catalog_scope(snapshot=_UNSET):
    """Pin lazily, so startup/requests with no model work need no catalog I/O."""
    snapshot_token = _snapshot.set(snapshot)
    pin_token = _pin.set(True)
    try:
        yield
    finally:
        _pin.reset(pin_token)
        _snapshot.reset(snapshot_token)


def effective_catalog():
    """Return an internal read-only-by-contract snapshot; public resolvers copy outputs."""
    snapshot = _snapshot.get()
    if snapshot is _UNSET and _provider is not None:
        snapshot = _provider()
        if _pin.get():
            _snapshot.set(snapshot)
    return snapshot if snapshot is not _UNSET else None


def pin_catalog_stream(iterable):
    """Keep request decisions stable after Flask tears down the initial request."""
    snapshot = _snapshot.get()

    def generate():
        try:
            with catalog_scope(snapshot):
                yield from iterable
        finally:
            close = getattr(iterable, "close", None)
            if close is not None:
                close()
    return generate()


def pin_catalog_task(function):
    """Carry the request's catalog into an executor or standalone worker thread."""
    snapshot = effective_catalog()

    @wraps(function)
    def run(*args, **kwargs):
        with catalog_scope(snapshot):
            return function(*args, **kwargs)
    return run
