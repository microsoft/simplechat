# errors.py
"""Errors the map server returns to callers, each with a stable code and a message that's safe to show."""

from typing import Any, Optional


class MapServerError(Exception):
    """A request failed in a way the caller can act on."""

    def __init__(self, status_code: int, code: str, message: str, details: Optional[Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def invalid(message: str, code: str = "invalid_request") -> MapServerError:
    return MapServerError(400, code, message)


def unauthorized(message: str = "A valid access token is required.") -> MapServerError:
    return MapServerError(401, "unauthorized", message)


def forbidden(code: str, message: str) -> MapServerError:
    return MapServerError(403, code, message)


def not_found(code: str = "map_not_found", message: str = "Map not found.") -> MapServerError:
    return MapServerError(404, code, message)


def conflict(code: str, message: str) -> MapServerError:
    return MapServerError(409, code, message)


def precondition_failed(code: str, message: str) -> MapServerError:
    return MapServerError(412, code, message)


def store_unavailable() -> MapServerError:
    return MapServerError(503, "store_unavailable", "The map store is unavailable. Try again shortly.")
