# blob_container_readiness.py
"""Write-triggered recovery for application-owned private Blob containers.

No configuration, logging bootstrap, or network activity occurs on import.
Owners supply initialized clients, replayable writes, and their logging callback.
"""

from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
import logging
import threading
import time
from typing import Callable, TypeVar

from azure.core.exceptions import AzureError


APPLICATION_BLOB_CONTAINERS = (
    "user-documents", "group-documents", "public-documents", "personal-chat", "group-chat",
)
STORAGE_FAILURE_CODE = "result_storage_unavailable"
STORAGE_FAILURE_MESSAGE = (
    "The storage needed to save analysis progress or results is unavailable. "
    "Ask an administrator to create the missing storage containers or check the app's "
    "storage access, then retry."
)
REPAIR_FAILURE_COOLDOWN_SECONDS = 60
MAX_CACHED_CONTAINERS = 128
_T = TypeVar("_T")


class BlobContainerUnavailableError(RuntimeError):
    """A safe, structured storage-initialization failure, never an SDK message."""

    orchestration_failure_code = STORAGE_FAILURE_CODE

    def __init__(self, reason="container_missing", status_code=None):
        self.reason = reason
        self.status_code = status_code
        super().__init__(STORAGE_FAILURE_MESSAGE)


@dataclass
class _ContainerState:
    client: object
    lock: object = field(default_factory=threading.Lock)
    users: int = 0
    generation: int = 0
    retry_after: float = 0
    failure: tuple | None = None


_states = OrderedDict()
_states_lock = threading.Lock()


def _trim_states():
    # In-flight entries stay pinned; the idle cache is bounded after they finish.
    for key in list(_states):
        if len(_states) <= MAX_CACHED_CONTAINERS:
            break
        if not _states[key].users:
            del _states[key]


@contextmanager
def _container_state(client, container_name):
    if not isinstance(container_name, str) or not container_name:
        raise ValueError("A storage container name is required.")
    key = (id(client), container_name)
    with _states_lock:
        state = _states.get(key)
        if state is None:
            state = _states[key] = _ContainerState(client)
        _states.move_to_end(key)
        state.users += 1
        _trim_states()
    try:
        yield state
    finally:
        with _states_lock:
            state.users -= 1
            _trim_states()


def _storage_reason(error):
    status = getattr(error, "status_code", None)
    if status in (401, 403):
        return "storage_access_denied", status
    if getattr(error, "error_code", None) == "ContainerNotFound":
        return "container_missing", status
    return "storage_service_unavailable", status


def _check_cooldown(state):
    if state.failure is not None and time.monotonic() < state.retry_after:
        raise BlobContainerUnavailableError(*state.failure)


def _record_failure(state, error):
    state.failure = _storage_reason(error)
    state.retry_after = time.monotonic() + REPAIR_FAILURE_COOLDOWN_SECONDS
    state.generation += 1
    return BlobContainerUnavailableError(*state.failure)


def _create_container(client, container_name, state, log):
    created = True
    try:
        client.get_container_client(container_name).create_container(
            public_access=None, connection_timeout=5, read_timeout=10, retry_total=0,
        )
    except (AzureError, TimeoutError, ConnectionError) as error:
        if getattr(error, "error_code", None) != "ContainerAlreadyExists":
            failure = _record_failure(state, error)
            if log is not None:
                log(
                    "[ENHANCED_CITATIONS] Storage container creation failed.",
                    extra={
                        "container_name": container_name, "reason": failure.reason,
                        "status_code": failure.status_code, "error_type": type(error).__name__,
                    },
                    level=logging.ERROR,
                )
            raise failure from error
        created = False
    state.failure = None
    state.retry_after = 0
    state.generation += 1
    if log is not None:
        log(
            "[ENHANCED_CITATIONS] Storage container readiness restored.",
            extra={"container_name": container_name, "created": created},
            level=logging.INFO,
        )
    return created


def create_missing_blob_container(client, container_name, *, log=None):
    """Explicit admin/intake operation; never change an existing container's ACL."""
    with _container_state(client, container_name) as state:
        with state.lock:
            return _create_container(client, container_name, state, log)


def write_blob_with_container_recovery(
    client, container_name, write: Callable[[], _T], *, before_retry=None, log=None,
) -> _T:
    """Retry one replayable write only after a structured ContainerNotFound.

    Capture the repair generation before writing so concurrent missing-container
    responses share one creation attempt, including an explicit admin repair.
    """
    with _container_state(client, container_name) as state:
        with state.lock:
            generation = state.generation
        try:
            result = write()
        except AzureError as error:
            if getattr(error, "error_code", None) != "ContainerNotFound":
                raise
        else:
            with state.lock:
                state.failure = None
                state.retry_after = 0
            return result
        if before_retry is not None:
            before_retry()
        with state.lock:
            _check_cooldown(state)
            if generation == state.generation:
                _create_container(client, container_name, state, log)
        if before_retry is not None:
            before_retry()
        try:
            return write()
        except AzureError as error:
            if getattr(error, "error_code", None) != "ContainerNotFound":
                raise
            with state.lock:
                failure = _record_failure(state, error)
            raise failure from error
