# functions_orchestration_invocation_capture.py
"""Private invocation-capture state, independent of application initialization.

Version: 0.261.127

The server supplies an already producer-bound callback. SDKs and tool loops may
catch exceptions, so a refused capture remains sticky until the owning
invocation fails. No settings, source records or callback return values are
retained here.
"""

from copy import deepcopy
import inspect
from threading import RLock
from typing import NoReturn

from content_screening.contracts import DocumentHeldError
from functions_orchestration_result_contracts import ResultContractError


class OrchestrationInvocationCaptureError(ResultContractError):
    """The actual invocation configuration could not be attested."""

    def __init__(self):
        super().__init__("result_external_configuration_unavailable")


class OrchestrationInvocationServiceError(RuntimeError):
    """Safe owner-defined authority failure; subclasses reconstruct from code."""


class OrchestrationInvocationCancelledError(InterruptedError):
    """Safe owner-defined cancellation; subclasses have a no-argument constructor."""


class OrchestrationInvocationControlError(RuntimeError):
    """Safe owning lifecycle failure; subclasses reconstruct from their stable code."""


class OrchestrationInvocationDeniedError(PermissionError):
    """An acquired source is denied, without retaining private authority details."""

    code = "result_unavailable"
    retryable = False

    def __init__(self):
        super().__init__("The acquired source is unavailable under the current access policy.")


class OrchestrationInvocationHeldError(DocumentHeldError):
    """A captured source remains on hold under the existing screening policy."""


def _raise_without_context(failure) -> NoReturn:
    try:
        raise failure from None
    except Exception:
        # SDK callers may still be in an except block; "from None" only hides this reference.
        failure.__context__ = None
        raise


class OrchestrationInvocationCapture:
    """Runtime-only callback state shared by an invocation and its descendants."""

    def __init__(self, callback):
        if not callable(callback) or inspect.iscoroutinefunction(callback):
            _raise_without_context(OrchestrationInvocationCaptureError())
        self._callback = callback
        self._failed = False
        self._failure_type = None
        self._failure_code = None
        self._captures = 0
        self._lock = RLock()

    def __call__(self, source_type, *, settings, source=None, selector=None):
        with self._lock:
            self.require_valid()
            try:
                captured = self._callback(
                    source_type, settings=deepcopy(settings),
                    source=deepcopy(source), selector=selector,
                )
                if inspect.isawaitable(captured):
                    if inspect.iscoroutine(captured):
                        captured.close()
                    raise OrchestrationInvocationCaptureError()
                if captured is False:
                    raise OrchestrationInvocationCaptureError()
            except Exception as exc:
                self._record_failure(exc)
            self.require_valid()
            if source is None and source_type != "url":
                self._captures = 0
            else:
                self._captures += 1

    def _raise_failure(self) -> NoReturn:
        if self._failure_type is not None:
            if self._failure_code is None:
                failure = self._failure_type()
            else:
                failure = self._failure_type(self._failure_code)
        else:
            failure = OrchestrationInvocationCaptureError()
        _raise_without_context(failure)

    def _record_failure(self, error):
        if not self._failed:
            self._failed = True
            if isinstance(error, OrchestrationInvocationCancelledError):
                self._failure_type = type(error)
            elif isinstance(error, InterruptedError):
                # Metadata/lifecycle owners also expose plain cancellation.
                self._failure_type = OrchestrationInvocationCancelledError
            elif isinstance(error, (OrchestrationInvocationServiceError, OrchestrationInvocationControlError)):
                code = getattr(error, "code", None)
                if type(code) is str and code and len(code) <= 128:
                    self._failure_type = type(error)
                    self._failure_code = code
            elif isinstance(error, DocumentHeldError):
                self._failure_type = OrchestrationInvocationHeldError
            elif isinstance(error, PermissionError):
                self._failure_type = OrchestrationInvocationDeniedError

    def fail(self, error) -> NoReturn:
        """Record an owned engine failure without retaining its private exception."""
        with self._lock:
            self._record_failure(error)
            del error
            self._raise_failure()

    def require_valid(self, *, captured=False):
        with self._lock:
            if self._failed or (captured and not self._captures):
                self._failed = True
                self._raise_failure()

    def refuse(self) -> NoReturn:
        with self._lock:
            self._failed = True
        self._raise_failure()


def require_invocation_capture(value):
    if value is not None and type(value) is not OrchestrationInvocationCapture:
        _raise_without_context(OrchestrationInvocationCaptureError())
    if value is not None:
        value.require_valid()
    return value
