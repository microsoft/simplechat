# test_orchestration_external_error_markers.py
"""
Functional tests for safe external authority errors across invocation capture.
Version: 0.261.127
Implemented in: 0.261.127

Real identity/configuration exceptions preserve public codes, retryability and
cancellation through initial and sticky capture failures without retaining the
original exception or private payload. Cold imports use real modules with
network access blocked, including explicit checks under optimized Python.
Refs microsoft/simplechat#1509.
"""

import gc
from pathlib import Path
import sys
import weakref

import pytest

# Standalone tests resolve the real application modules only after path setup.
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))

from functions_orchestration_external_configuration import (
    ExternalConfigurationCancelledError, ExternalConfigurationServiceError,
)
from functions_orchestration_external_identity import (
    ExternalIdentityCancelledError, ExternalIdentityServiceError,
)
from functions_orchestration_invocation_capture import (
    OrchestrationInvocationCancelledError, OrchestrationInvocationCapture,
    OrchestrationInvocationServiceError,
)
from functions_orchestration_results import ResultUnavailableError
from test_orchestration_result_imports import APP_PROBE, EARLY_PROBE, run_probe


SERVICE_CONTRACTS = (
    (
        ExternalIdentityServiceError,
        {
            "external_identity_service_unavailable": True,
            "external_identity_timeout": True,
            "external_identity_throttled": True,
            "external_identity_incomplete": True,
            "external_identity_response_invalid": False,
            "external_identity_pagination_invalid": False,
            "external_identity_limit_exceeded": False,
            "external_identity_callback_invalid": False,
        },
        "Current directory authorization could not be verified.",
    ),
    (
        ExternalConfigurationServiceError,
        {
            "external_configuration_service_unavailable": True,
            "external_configuration_timeout": True,
            "external_configuration_throttled": True,
            "external_configuration_metadata_invalid": False,
            "external_configuration_limit_exceeded": False,
        },
        "Current source configuration could not be verified.",
    ),
)
SERVICE_CASES = [
    (error_type, code, retryable, message)
    for error_type, codes, message in SERVICE_CONTRACTS
    for code, retryable in codes.items()
]
CANCEL_CASES = (
    (
        ExternalIdentityCancelledError, "external_identity_cancelled",
        "Current directory authorization was cancelled.",
    ),
    (
        ExternalConfigurationCancelledError, "external_configuration_cancelled",
        "Current source configuration verification was cancelled.",
    ),
)
CAPTURE_CASES = SERVICE_CASES + [
    (error_type, code, None, message) for error_type, code, message in CANCEL_CASES
]
PRIVATE_DETAIL = "PRIVATE_AUTHORITY_EXCEPTION_PAYLOAD"


@pytest.mark.parametrize("error_type,code,retryable,message", SERVICE_CASES)
def test_service_marker_preserves_every_existing_public_error_contract(error_type, code, retryable, message):
    error = error_type(code)
    assert isinstance(error, OrchestrationInvocationServiceError)
    assert isinstance(error, RuntimeError)
    assert not isinstance(error, (OrchestrationInvocationCancelledError, ResultUnavailableError))
    assert error.code == code
    assert error.retryable is retryable
    assert error.args == (message,)


@pytest.mark.parametrize("error_type,code", [
    (ExternalIdentityServiceError, "external_identity_service_unavailable"),
    (ExternalConfigurationServiceError, "external_configuration_service_unavailable"),
])
def test_service_default_constructor_is_unchanged(error_type, code):
    error = error_type()
    assert error.code == code
    assert error.retryable is True


@pytest.mark.parametrize("error_type", [ExternalIdentityServiceError, ExternalConfigurationServiceError])
@pytest.mark.parametrize("code", [None, True, 1, {}, [], "", PRIVATE_DETAIL, " external_identity_timeout "])
def test_service_constructor_still_refuses_unvalidated_codes(error_type, code):
    with pytest.raises(ValueError) as raised:
        error_type(code)
    assert PRIVATE_DETAIL not in str(raised.value)


@pytest.mark.parametrize("error_type,code,message", CANCEL_CASES)
def test_cancel_marker_preserves_no_argument_constructor_and_public_code(error_type, code, message):
    error = error_type()
    assert isinstance(error, OrchestrationInvocationCancelledError)
    assert isinstance(error, InterruptedError)
    assert not isinstance(error, (OrchestrationInvocationServiceError, ResultUnavailableError))
    assert error.code == code
    assert error.args == (message,)


@pytest.mark.parametrize("error_type,code,retryable,message", CAPTURE_CASES)
def test_initial_and_sticky_capture_reconstruct_safe_owner_types_without_exception_retention(
    error_type, code, retryable, message,
):
    originals = []
    callback_calls = []

    def fail_callback(_source_type, *, settings, source, selector):
        callback_calls.append(True)
        error = error_type() if retryable is None else error_type(code)
        error.private_detail = {"settings": settings, "source": source, "selector": selector}
        error.args = (PRIVATE_DETAIL,)
        if retryable is not None:
            error.retryable = not retryable
        originals.append(weakref.ref(error))
        raise error from RuntimeError(PRIVATE_DETAIL)

    capture = OrchestrationInvocationCapture(fail_callback)
    with pytest.raises(error_type) as first:
        capture("web", settings={"secret": PRIVATE_DETAIL}, source={"private": PRIVATE_DETAIL})
    fresh = first.value
    assert type(fresh) is error_type
    assert fresh.code == code
    assert fresh.args == (message,)
    assert fresh.__cause__ is None
    assert fresh.__context__ is None
    assert not hasattr(fresh, "private_detail")
    if retryable is not None:
        assert fresh.retryable is retryable

    previous = fresh
    for check in (
        lambda: capture("web", settings={}, source=None),
        lambda: capture.require_valid(captured=True),
        capture.refuse,
    ):
        with pytest.raises(error_type) as repeated:
            check()
        fresh = repeated.value
        assert type(fresh) is error_type
        assert fresh is not previous
        assert fresh.code == code
        assert fresh.args == (message,)
        assert fresh.__cause__ is None
        assert fresh.__context__ is None
        assert not hasattr(fresh, "private_detail")
        if retryable is not None:
            assert fresh.retryable is retryable
        previous = fresh

    state = vars(capture).copy()
    assert state["_failure_type"] is error_type
    assert state["_failure_code"] == (None if retryable is None else code)
    assert not any(isinstance(value, BaseException) for value in state.values())
    assert PRIVATE_DETAIL not in repr(state)
    assert callback_calls == [True]
    gc.collect()
    retained_originals = [reference() for reference in originals]
    assert retained_originals == [None]


MARKER_PROBE = r'''
import socket
from unittest.mock import patch

from functions_orchestration_external_identity import (
    ExternalIdentityServiceError, ExternalIdentityCancelledError,
)
from functions_orchestration_external_configuration import (
    ExternalConfigurationServiceError, ExternalConfigurationCancelledError,
)
from functions_orchestration_invocation_capture import (
    OrchestrationInvocationCapture, OrchestrationInvocationServiceError,
    OrchestrationInvocationCancelledError,
)

def verify(condition, message):
    if not condition:
        raise AssertionError(message)

with patch.object(socket.socket, "connect", side_effect=AssertionError("Unexpected marker I/O")) as network:
    for error_type, code, retryable in (
        (ExternalIdentityServiceError, "external_identity_timeout", True),
        (ExternalIdentityServiceError, "external_identity_response_invalid", False),
        (ExternalConfigurationServiceError, "external_configuration_timeout", True),
        (ExternalConfigurationServiceError, "external_configuration_metadata_invalid", False),
        (ExternalIdentityCancelledError, "external_identity_cancelled", None),
        (ExternalConfigurationCancelledError, "external_configuration_cancelled", None),
    ):
        calls = []
        def fail(*_args, **_kwargs):
            calls.append(True)
            error = error_type() if retryable is None else error_type(code)
            error.private_detail = "PRIVATE_EXCEPTION"
            raise error
        capture = OrchestrationInvocationCapture(fail)
        for invoke in (
            lambda: capture("web", settings={}, source=None),
            capture.require_valid,
            capture.refuse,
        ):
            try:
                invoke()
            except error_type as error:
                marker = OrchestrationInvocationCancelledError if retryable is None else OrchestrationInvocationServiceError
                verify(isinstance(error, marker), "Owner failure lost its pure runtime marker")
                verify(error.code == code, "Owner failure lost its stable code")
                verify(error.__context__ is None and error.__cause__ is None, "Original exception chain retained")
                verify(not hasattr(error, "private_detail"), "Private exception data retained")
                if retryable is not None:
                    verify(error.retryable is retryable, "Retry classification changed")
            else:
                raise AssertionError("Required owner/capture failure disappeared")
        verify(calls == [True], "Sticky capture repeated callback work")
    verify(network.call_count == 0, "Marker operation attempted external I/O")
print("PASS: required real-owner failure operations and safe reconstruction")
'''


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("probe,order", [
    (EARLY_PROBE, (
        "functions_orchestration_external_identity", "functions_orchestration_external_configuration",
        "functions_orchestration_invocation_capture",
    )),
    (EARLY_PROBE, (
        "functions_orchestration_invocation_capture", "functions_orchestration_external_configuration",
        "functions_orchestration_external_identity",
    )),
    (APP_PROBE, (
        "functions_orchestration_invocation_capture", "app", "functions_orchestration_external_identity",
        "functions_orchestration_external_configuration", "background_tasks",
    )),
    (APP_PROBE, (
        "app", "functions_orchestration_external_identity",
        "functions_orchestration_external_configuration", "functions_orchestration_invocation_capture",
    )),
    (APP_PROBE, (
        "background_tasks", "functions_orchestration_invocation_capture",
        "functions_orchestration_external_configuration", "functions_orchestration_external_identity",
    )),
], ids=["owners-first", "marker-first", "marker-web-scheduler", "web-first", "scheduler-first"])
def test_marker_imports_and_failure_operations_in_real_fresh_processes(probe, order, optimized):
    run_probe(probe + MARKER_PROBE, order, optimized)
