# test_orchestration_invocation_capture.py
"""Private invocation capture and execution-frame propagation.

Version: 0.261.127
Implemented in: 0.261.127

Verifies isolated callback inputs, released exception chains, sticky refusal,
and task/thread/reused-frame propagation without Azure, a request context,
or a process-global policy.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import gc
import importlib
import weakref

import pytest

from test_support.app_stubs import APP_ROOT
from test_orchestration_result_imports import EARLY_PROBE, run_probe


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_ROOT))
    return (
        importlib.import_module("functions_orchestration_invocation_capture"),
        importlib.import_module("agent_execution_context"),
    )


def test_capture_inputs_and_return_value_never_escape(modules):
    capture_types, _ = modules
    settings = {"nested": {"endpoint": "private"}}
    source = {"record": {"id": "original"}}
    calls = []

    def callback(source_type, **kwargs):
        calls.append((source_type, kwargs["selector"]))
        kwargs["settings"]["nested"]["endpoint"] = "replacement"
        kwargs["source"]["record"]["id"] = "replacement"
        return {"private": "not a result"}

    capture = capture_types.OrchestrationInvocationCapture(callback)
    returned = capture("action", settings=settings, source=source, selector="personal:owner:action")
    capture.require_valid(captured=True)
    assert returned is None
    assert settings == {"nested": {"endpoint": "private"}}
    assert source == {"record": {"id": "original"}}
    assert calls == [("action", "personal:owner:action")]


@pytest.mark.parametrize("failure", ["false", "exception", "missing_capture", "awaitable"])
def test_refusal_cannot_be_caught_and_replaced_with_success(modules, failure):
    capture_types, _ = modules
    calls = []

    async def asynchronous_result():
        return True

    def callback(*args, **kwargs):
        calls.append(True)
        if failure == "exception":
            raise RuntimeError("PRIVATE_FAILURE")
        if failure == "awaitable":
            return asynchronous_result()
        return False

    capture = capture_types.OrchestrationInvocationCapture(callback)
    with pytest.raises(capture_types.OrchestrationInvocationCaptureError) as caught:
        if failure == "missing_capture":
            capture.require_valid(captured=True)
        else:
            capture("agent", settings={})
    assert "PRIVATE_" not in str(caught.value)
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    previous_calls = len(calls)
    with pytest.raises(capture_types.OrchestrationInvocationCaptureError):
        capture("agent", settings={})
    assert len(calls) == previous_calls


@pytest.mark.parametrize("source_type", ["agent", "action", "web", "deep_research"])
@pytest.mark.parametrize("previous_capture", [False, True])
def test_preparation_is_not_completed_execution_proof(modules, source_type, previous_capture):
    capture_types, _ = modules
    capture = capture_types.OrchestrationInvocationCapture(lambda *args, **kwargs: None)
    if previous_capture:
        capture(source_type, settings={}, source={"actual": "earlier invocation"})
        capture.require_valid(captured=True)
    capture(source_type, settings={})
    capture.require_valid()
    with pytest.raises(capture_types.OrchestrationInvocationCaptureError):
        capture.require_valid(captured=True)


def test_url_fetch_policy_capture_does_not_require_model_evidence(modules):
    capture_types, _ = modules
    capture = capture_types.OrchestrationInvocationCapture(lambda *args, **kwargs: None)
    capture("url", settings={"source_review_allow_js_rendering": False})
    capture.require_valid(captured=True)


@pytest.mark.parametrize("kind", ["service", "cancelled", "control"])
def test_safe_authority_failures_keep_their_type_without_retaining_private_exception(modules, kind):
    capture_types, _ = modules

    class ServiceError(capture_types.OrchestrationInvocationServiceError):
        def __init__(self, code):
            self.code = code
            self.retryable = True
            super().__init__("The authority is unavailable.")

    class CancelledError(capture_types.OrchestrationInvocationCancelledError):
        def __init__(self):
            super().__init__("The authority check was cancelled.")

    class ControlError(capture_types.OrchestrationInvocationControlError):
        def __init__(self, code):
            self.code = code
            super().__init__("The owning execution is no longer active.")

    original = {
        "service": ServiceError("authority_timeout"),
        "cancelled": CancelledError(),
        "control": ControlError("ownership_lost"),
    }[kind]
    original.private_detail = {"credential": "PRIVATE_AUTHORITY_VALUE"}
    calls = []

    def fail(*args, **kwargs):
        calls.append(True)
        raise original

    capture = capture_types.OrchestrationInvocationCapture(fail)
    operations = (
        lambda: capture("action", settings={"key": "PRIVATE_CONFIGURATION_VALUE"}),
        lambda: capture("action", settings={}),
        capture.require_valid,
        capture.refuse,
        lambda: capture.fail(RuntimeError("PRIVATE_REPLACEMENT_FAILURE")),
    )
    for operation in operations:
        with pytest.raises(type(original)) as caught:
            operation()
        assert caught.value is not original
        assert not hasattr(caught.value, "private_detail")
        assert "PRIVATE_" not in str(caught.value)
        assert caught.value.__context__ is None
        assert caught.value.__cause__ is None
        if kind == "service":
            assert caught.value.code == "authority_timeout" and caught.value.retryable
        if kind == "control":
            assert caught.value.code == "ownership_lost"
    assert calls == [True]


@pytest.mark.parametrize("module_name,error_name", [
    ("functions_orchestration_external_identity", "ExternalIdentityServiceError"),
    ("functions_orchestration_external_identity", "ExternalIdentityCancelledError"),
    ("functions_orchestration_external_configuration", "ExternalConfigurationServiceError"),
    ("functions_orchestration_external_configuration", "ExternalConfigurationCancelledError"),
])
@pytest.mark.parametrize("initial", ["callback", "engine"])
@pytest.mark.parametrize("recheck", ["invoke", "fail", "require_valid", "refuse"])
def test_initial_and_sticky_sdk_handlers_release_private_exception_chains(
    modules, module_name, error_name, initial, recheck,
):
    capture_types, _ = modules
    error_type = getattr(importlib.import_module(module_name), error_name)
    expected = error_type()
    originals = []

    class PrivateSdkError(RuntimeError):
        pass

    def raise_private(kind):
        error = kind()
        error.args = ("PRIVATE_EXCEPTION_PAYLOAD",)
        error.private_detail = {"key": "PRIVATE_EXCEPTION_PAYLOAD"}
        cause = PrivateSdkError("PRIVATE_CAUSE")
        originals.extend((weakref.ref(error), weakref.ref(cause)))
        raise error from cause

    def callback(*args, **kwargs):
        raise_private(error_type)

    capture = capture_types.OrchestrationInvocationCapture(callback)

    def engine_failure():
        try:
            raise_private(error_type)
        except error_type as error:
            capture.fail(error)

    with pytest.raises(error_type) as first:
        if initial == "callback":
            capture("web", settings={}, source={"phase": "run"})
        else:
            engine_failure()

    def sdk_handler():
        try:
            raise_private(PrivateSdkError)
        except PrivateSdkError as error:
            if recheck == "invoke":
                capture("web", settings={})
            elif recheck == "fail":
                capture.fail(error)
            elif recheck == "require_valid":
                capture.require_valid(captured=True)
            else:
                capture.refuse()

    with pytest.raises(error_type) as repeated:
        sdk_handler()
    for safe in (first.value, repeated.value):
        assert type(safe) is error_type
        assert safe.code == expected.code
        assert safe.args == expected.args
        assert getattr(safe, "retryable", None) == getattr(expected, "retryable", None)
        assert safe.__context__ is None and safe.__cause__ is None
        assert not hasattr(safe, "private_detail")
    gc.collect()
    assert all(reference() is None for reference in originals)


def test_callback_cannot_swallow_its_sticky_failure_and_return_success(modules):
    capture_types, _ = modules
    errors = importlib.import_module("functions_orchestration_external_configuration")

    def callback(*args, **kwargs):
        try:
            capture.fail(errors.ExternalConfigurationServiceError("external_configuration_timeout"))
        except errors.ExternalConfigurationServiceError:
            pass
        return True

    capture = capture_types.OrchestrationInvocationCapture(callback)
    with pytest.raises(errors.ExternalConfigurationServiceError) as caught:
        capture("web", settings={}, source={"phase": "run"})
    assert caught.value.code == "external_configuration_timeout"
    assert caught.value.retryable is True
    assert caught.value.__context__ is None and caught.value.__cause__ is None


@pytest.mark.parametrize("invalid", ["callback", "coroutine", "state"])
def test_invalid_capture_entrypoints_do_not_retain_an_active_sdk_exception(modules, invalid):
    capture_types, _ = modules
    originals = []

    class PrivateSdkError(RuntimeError):
        pass

    def raise_private():
        error = PrivateSdkError("PRIVATE_SDK_DETAILS")
        originals.append(weakref.ref(error))
        raise error

    async def callback():
        return None

    def sdk_handler():
        try:
            raise_private()
        except PrivateSdkError:
            if invalid == "state":
                capture_types.require_invocation_capture(object())
            else:
                capture_types.OrchestrationInvocationCapture(callback if invalid == "coroutine" else None)

    with pytest.raises(capture_types.OrchestrationInvocationCaptureError) as caught:
        sdk_handler()
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    gc.collect()
    assert all(reference() is None for reference in originals)


def test_capture_propagates_to_tasks_threads_and_preexisting_frames(modules):
    capture_types, contexts = modules
    capture = capture_types.OrchestrationInvocationCapture(lambda *args, **kwargs: None)
    identity = contexts.ExecutionIdentity("owner")
    budget = contexts.DelegationBudget()
    existing = contexts.AgentExecutionFrame(identity, {"id": "original"}, budget)
    root = contexts.AgentExecutionFrame(
        identity, {"id": "original"}, budget,
        invocation_capture=capture, invocation_settings={"model": "original"},
    )

    def observe():
        current = contexts.current_agent_execution()
        return current.invocation_capture, current.invocation_settings

    def transport(captured_frame):
        with contexts.agent_execution(captured_frame):
            return observe()

    async def run():
        with contexts.agent_execution(root):
            task_value = await asyncio.create_task(asyncio.to_thread(observe))
            with contexts.agent_execution(existing) as effective:
                assert effective.invocation_capture is capture
                with ThreadPoolExecutor(max_workers=1) as executor:
                    transported = executor.submit(transport, effective).result()
            assert contexts.current_agent_execution() is root
        return task_value, transported

    values = asyncio.run(run())
    assert all(value == (capture, {"model": "original"}) for value in values)
    assert existing.invocation_capture is None
    assert contexts.current_agent_execution() is None


def test_nested_scope_cannot_replace_owning_capture(modules):
    capture_types, contexts = modules
    original = capture_types.OrchestrationInvocationCapture(lambda *args, **kwargs: None)
    replacement = capture_types.OrchestrationInvocationCapture(lambda *args, **kwargs: None)
    identity = contexts.ExecutionIdentity("owner")
    budget = contexts.DelegationBudget()
    root = contexts.AgentExecutionFrame(identity, {}, budget, invocation_capture=original)
    nested = contexts.AgentExecutionFrame(identity, {}, budget, invocation_capture=replacement)
    with contexts.agent_execution(root):
        with pytest.raises(capture_types.OrchestrationInvocationCaptureError):
            with contexts.agent_execution(nested):
                pytest.fail("The owning capture must not be replaced.")
        with pytest.raises(capture_types.OrchestrationInvocationCaptureError):
            original.require_valid()
    assert contexts.current_agent_execution() is None


@pytest.mark.parametrize("identity", [("another-owner", "conversation"), ("owner", "another-conversation")])
def test_nested_scope_cannot_rebind_capture_to_another_actor_or_conversation(modules, identity):
    capture_types, contexts = modules
    capture = capture_types.OrchestrationInvocationCapture(lambda *args, **kwargs: None)
    budget = contexts.DelegationBudget()
    root = contexts.AgentExecutionFrame(
        contexts.ExecutionIdentity("owner", "conversation"), {}, budget, invocation_capture=capture,
    )
    child = contexts.AgentExecutionFrame(contexts.ExecutionIdentity(*identity), {}, budget)
    with contexts.agent_execution(root):
        with pytest.raises(capture_types.OrchestrationInvocationCaptureError):
            with contexts.agent_execution(child):
                pytest.fail("The captured actor and conversation must remain unchanged.")
    assert contexts.current_agent_execution() is None


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("functions_orchestration_invocation_capture", "agent_execution_context"),
    ("agent_execution_context", "functions_orchestration_invocation_capture"),
    ("functions_orchestration_model_capture", "agent_execution_context"),
    ("agent_execution_context", "functions_orchestration_model_capture"),
])
def test_capture_and_frame_cold_imports_do_not_initialize_owners(order, optimized):
    run_probe(EARLY_PROBE, order, optimized)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
