#!/usr/bin/env python3
# test_chat_openai_timeout_and_stream_resilience.py
"""
Functional test for chat OpenAI client timeouts, stream disconnect grace-period
cancellation, document-action total deadlines, and dedicated chat-stream workers.
Version: 0.261.387
Implemented in: 0.261.387

This test ensures that:
1. Model endpoint and legacy AzureOpenAI clients are constructed with bounded
   httpx.Timeout and max_retries options from Scale settings.
2. Auxiliary pre-stream calls (history answerability and older-message summary)
   bind a short 30s fail-open timeout with 0 retries.
3. Sync OpenAI streams in /api/chat/stream are closed in a finally block on exit
   or cancellation.
4. Disconnected stream sessions auto-cancel once stream_disconnect_grace_seconds
   expires without reattachment, while preserving brief reconnects within the
   grace window.
5. Document-action model invocations enforce the overall wall-clock deadline and
   abort promptly on cancellation or timeout.
6. Chat streams use a dedicated chat_stream_executor pool and Gunicorn defaults
   to 16 threads per worker.
"""

from datetime import datetime, timedelta
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
sys.path.insert(0, str(REPO_ROOT / "functional_tests"))
sys.path.insert(0, str(APP_ROOT))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least

import model_endpoint_clients as endpoint_clients
from functions_mixed_source_orchestration import MixedSourceCancellationError


def test_openai_timeout_and_retry_helpers():
    """Verify timeout and retry helpers honor Scale settings and clamp bounds."""
    print("Testing OpenAI client timeout and retry helpers...")
    assert_app_version_at_least("0.261.387")

    default_options = endpoint_clients.build_openai_client_timeout_options({})
    timeout_obj = default_options["timeout"]
    assert isinstance(timeout_obj, httpx.Timeout)
    assert timeout_obj.read == 120.0
    assert timeout_obj.connect == 10.0
    assert default_options["max_retries"] == 1

    custom_options = endpoint_clients.build_openai_client_timeout_options({
        "model_stream_read_timeout_seconds": 180,
        "model_call_max_retries": 2,
    })
    assert custom_options["timeout"].read == 180.0
    assert custom_options["max_retries"] == 2

    clamped_options = endpoint_clients.build_openai_client_timeout_options({
        "model_stream_read_timeout_seconds": 9999,
        "model_call_max_retries": 99,
    })
    assert clamped_options["timeout"].read == 600.0
    assert clamped_options["max_retries"] == 3

    assert endpoint_clients.resolve_document_action_timeout_seconds({}) == 300
    assert endpoint_clients.resolve_document_action_timeout_seconds({"document_action_timeout_seconds": 450}) == 450
    assert endpoint_clients.resolve_stream_disconnect_grace_seconds({}) == 60
    assert endpoint_clients.resolve_stream_disconnect_grace_seconds({"stream_disconnect_grace_seconds": 0}) == 0

    # Verify bind_callable_with_timeout scopes client options when supported
    scoped_calls = []

    class FakeClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            return ("unscoped", kwargs)

        def with_options(self, **options):
            scoped_calls.append(options)
            return SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(create=lambda **kwargs: ("scoped", kwargs))
                )
            )

    client = FakeClient()
    bound = endpoint_clients.bind_callable_with_timeout(
        client,
        client.chat.completions.create,
        timeout_seconds=30.0,
        max_retries=0,
    )
    mode, payload = bound(model="gpt-4o", messages=[])
    assert mode == "scoped"
    assert payload["model"] == "gpt-4o"
    assert len(scoped_calls) == 1
    assert scoped_calls[0]["timeout"].read == 30.0
    assert scoped_calls[0]["max_retries"] == 0
    print("  OpenAI timeout and retry helpers passed.")
    return True


def test_disconnect_grace_period_auto_cancellation():
    """Verify detached streams stay reattachable during grace window and auto-cancel after."""
    print("Testing stream disconnect grace-period auto-cancellation...")
    from test_chat_content_streaming import Cache, stream_classes

    cache = Cache()
    module = stream_classes(cache, Mock(return_value=None))

    clock = {"now": datetime(2026, 10, 27, 12, 0, 0)}
    module.ActiveConversationStreamSession.__init__.__globals__["_utcnow_iso"] = (
        lambda: clock["now"].isoformat()
    )

    # 1. Non-zero grace period allows brief disconnect and reattach, then cancels if abandoned
    session = module.ActiveConversationStreamSession(
        "user-1",
        "conv-1",
        disconnect_grace_seconds=60,
    )
    session.initialize()
    assert not session.is_cancel_requested()

    session.mark_consumer_detached(reason="client_disconnect")
    clock["now"] = clock["now"] + timedelta(seconds=20)
    assert not session.is_cancel_requested(), "Stream should remain active within 60s grace period"

    # Reattach resets the detach timer
    session.mark_reattached()
    clock["now"] = clock["now"] + timedelta(seconds=120)
    assert not session.is_cancel_requested(), "Reattached stream must not auto-cancel"

    # Detach again and let grace window expire
    session.mark_consumer_detached(reason="client_disconnect")
    clock["now"] = clock["now"] + timedelta(seconds=61)
    assert session.is_cancel_requested(), "Detached stream should auto-cancel after grace period"
    assert session.get_cancel_reason() == "client_disconnect_timeout"

    # 2. Grace period of 0 cancels immediately on client disconnect
    immediate_session = module.ActiveConversationStreamSession(
        "user-1",
        "conv-immediate",
        disconnect_grace_seconds=0,
    )
    immediate_session.initialize()
    immediate_session.mark_consumer_detached(reason="client_disconnect")
    assert immediate_session.is_cancel_requested()
    assert immediate_session.get_cancel_reason() == "client_disconnect"
    print("  Stream disconnect grace-period auto-cancellation passed.")
    return True


def _load_workflow_runner_helpers():
    import ast
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
    from contextvars import copy_context

    source = APP_ROOT / "functions_workflow_runner.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    wanted_functions = {
        "_invoke_document_action_model_completion",
        "_execute_document_action_workflow",
        "_build_legacy_default_client",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted_functions
    ]
    namespace = {
        "ThreadPoolExecutor": ThreadPoolExecutor,
        "FutureTimeoutError": FutureTimeoutError,
        "copy_context": copy_context,
        "time": time,
        "_DOCUMENT_ACTION_MODEL_EXECUTOR": ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="test-doc-action-model",
        ),
        "MixedSourceCancellationError": MixedSourceCancellationError,
        "raise_if_mixed_source_cancelled": (
            lambda cancel_requested, phase, request_correlation_id=None: (
                (_ for _ in ()).throw(MixedSourceCancellationError(phase))
                if callable(cancel_requested) and cancel_requested()
                else None
            )
        ),
        "normalize_mixed_source_correlation_id": lambda cid=None: cid or "corr-default",
        "bind_callable_with_timeout": endpoint_clients.bind_callable_with_timeout,
        "build_openai_client_timeout_options": endpoint_clients.build_openai_client_timeout_options,
        "resolve_document_action_timeout_seconds": endpoint_clients.resolve_document_action_timeout_seconds,
        "resolve_model_call_max_retries": endpoint_clients.resolve_model_call_max_retries,
        "resolve_model_stream_read_timeout_seconds": endpoint_clients.resolve_model_stream_read_timeout_seconds,
        "build_model_endpoint_identity_headers": lambda *_a, **_k: {},
        "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
        "DOCUMENT_ACTION_TYPE_COMPARISON": "comparison",
        "_get_document_action_config": lambda wf: dict(wf.get("document_action") or {}),
        "_resolve_recent_document_action_targets": lambda wf, cfg, _s: cfg,
        "_no_document_selection_result": lambda cfg: {"reply": "", "document_action": cfg},
        "_apply_runtime_document_action_config": lambda wf, cfg: {**wf, "document_action": cfg},
        "debug_print": lambda *_a, **_k: None,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    return SimpleNamespace(**namespace)


def test_document_action_cancellable_invocation_and_deadline():
    """Verify document-action model calls abort promptly on cancel or deadline expiry."""
    print("Testing document-action cancellable model invocation and deadline enforcement...")
    workflow_runner = _load_workflow_runner_helpers()

    release_event = threading.Event()
    started_event = threading.Event()

    class SlowClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            started_event.set()
            release_event.wait(timeout=5.0)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="done"))])

    slow_client = SlowClient()

    # 1. Cancellation aborts waiting within ~100ms even while SlowClient blocks
    cancel_state = {"cancelled": False}

    def trigger_cancel():
        started_event.wait(timeout=2.0)
        time.sleep(0.08)
        cancel_state["cancelled"] = True

    canceller = threading.Thread(target=trigger_cancel, daemon=True)
    canceller.start()
    start_t = time.perf_counter()
    try:
        workflow_runner._invoke_document_action_model_completion(
            slow_client,
            "gpt-4o",
            [{"role": "user", "content": "Analyze"}],
            workflow={"_document_action_deadline": time.monotonic() + 60.0},
            settings={"model_stream_read_timeout_seconds": 120},
            cancel_requested=lambda: cancel_state["cancelled"],
            request_correlation_id="corr-1",
        )
        raise AssertionError("Expected MixedSourceCancellationError on cancellation")
    except MixedSourceCancellationError as exc:
        elapsed = time.perf_counter() - start_t
        assert elapsed < 1.0, f"Cancellation took too long ({elapsed:.2f}s)"
        assert exc.phase == "model_invocation"
    finally:
        release_event.set()

    # 2. Expired deadline raises MixedSourceCancellationError and marks timeout_state
    timeout_state = {"timed_out": False}
    try:
        workflow_runner._invoke_document_action_model_completion(
            slow_client,
            "gpt-4o",
            [{"role": "user", "content": "Analyze"}],
            workflow={
                "_document_action_deadline": time.monotonic() - 1.0,
                "_document_action_timeout_state": timeout_state,
            },
            settings={"model_stream_read_timeout_seconds": 120},
            cancel_requested=lambda: False,
            request_correlation_id="corr-2",
        )
        raise AssertionError("Expected MixedSourceCancellationError on expired deadline")
    except MixedSourceCancellationError as exc:
        assert timeout_state["timed_out"] is True
        assert exc.phase == "model_invocation_timeout"

    print("  Document-action cancellable invocation and deadline enforcement passed.")
    return True


def test_stream_close_and_worker_isolation_wiring():
    """Verify route_backend_chats.py, app.py, and gunicorn.conf.py wiring."""
    print("Testing stream close cleanup and worker pool isolation wiring...")
    route_chats_source = (APP_ROOT / "route_backend_chats.py").read_text(encoding="utf-8")
    app_source = (APP_ROOT / "app.py").read_text(encoding="utf-8")
    config_source = (APP_ROOT / "config.py").read_text(encoding="utf-8")
    gunicorn_source = (APP_ROOT / "gunicorn.conf.py").read_text(encoding="utf-8")

    assert "**build_openai_client_timeout_options(settings)" in route_chats_source
    assert "stream_close = getattr(stream, 'close', None)" in route_chats_source
    assert "current_app.extensions.get('chat_stream_executor')" in route_chats_source
    assert "CHAT_STREAM_EXECUTOR_MAX_WORKERS" in config_source
    assert "app.extensions['chat_stream_executor'] = chat_stream_executor" in app_source
    assert "threads = _env_int('GUNICORN_THREADS', 16)" in gunicorn_source
    print("  Stream close cleanup and worker pool isolation wiring passed.")
    return True


if __name__ == "__main__":
    tests = [
        test_openai_timeout_and_retry_helpers,
        test_disconnect_grace_period_auto_cancellation,
        test_document_action_cancellable_invocation_and_deadline,
        test_stream_close_and_worker_isolation_wiring,
    ]
    results = [test() for test in tests]
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
