# cosmos_network_guard.py
"""Pytest plugin blocking network before collection for the Cosmos contract CI job.

Version: 0.261.324
Implemented in: 0.261.324
"""

import socket
from contextlib import ExitStack
from contextvars import ContextVar
from unittest.mock import patch


_PATCHES = None
_IN_SOCKETPAIR = ContextVar("cosmos_contract_socketpair", default=False)
_CONNECT = socket.socket.connect
_SOCKETPAIR = socket.socketpair


def _blocked(*args, **kwargs):
    raise AssertionError("Cosmos response contract tests cannot access the network.")


def _connect(sock, address):
    # Windows' asyncio wakeup pair uses the standard library's loopback fallback.
    if _IN_SOCKETPAIR.get() and isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
        return _CONNECT(sock, address)
    return _blocked()


def _socketpair(*args, **kwargs):
    token = _IN_SOCKETPAIR.set(True)
    try:
        return _SOCKETPAIR(*args, **kwargs)
    finally:
        _IN_SOCKETPAIR.reset(token)


def pytest_sessionstart(session):
    global _PATCHES
    _PATCHES = ExitStack()
    _PATCHES.enter_context(patch.object(socket.socket, "connect", _connect))
    _PATCHES.enter_context(patch.object(socket, "socketpair", _socketpair))
    for name in ("connect_ex", "sendto"):
        _PATCHES.enter_context(patch.object(socket.socket, name, _blocked))
    _PATCHES.enter_context(patch.object(socket, "getaddrinfo", _blocked))


def pytest_sessionfinish(session, exitstatus):
    global _PATCHES
    if _PATCHES is not None:
        _PATCHES.close()
        _PATCHES = None
