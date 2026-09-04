#!/usr/bin/env python3
# test_chat_stream_empty_model_fallback.py
"""
Functional test for empty model stream fallback.
Version: 0.250.006
Implemented in: 0.250.003; updated in 0.250.006

This test ensures non-agent model streams that complete without assistant text
retry once without streaming, and that app thought events do not count as
assistant content in stream lifecycle counters.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
RUNTIME_FILE = ROOT / "application" / "single_app" / "functions_model_endpoint_runtime.py"
WORKFLOW_FILE = ROOT / "application" / "single_app" / "functions_workflow_runner.py"
DOCUMENTS_FILE = ROOT / "application" / "single_app" / "functions_documents.py"


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def test_chat_stream_empty_model_fallback() -> None:
    """Validate empty provider streams do not silently persist blank messages."""
    print("Testing empty model stream fallback markers...")

    assert_contains(
        ROUTE_FILE,
        "Model stream returned no assistant content; retrying without streaming",
    )
    assert_contains(ROUTE_FILE, "fallback_params = {")
    assert_contains(ROUTE_FILE, "fallback_params.pop('reasoning_effort', None)")
    assert_contains(ROUTE_FILE, "def _resolve_reasoning_effort_for_model")
    assert_contains(ROUTE_FILE, "ModelEndpointBehavior(provider, model_name).resolve_reasoning_effort")
    assert_contains(ROUTE_FILE, "ModelEndpointBehavior(provider, model_name).context_mode")
    assert_contains(ROUTE_FILE, "MODEL_CONTEXT_MODE_FOLD_LATEST_USER")
    assert_contains(ROUTE_FILE, "def _should_inject_fact_memory_context_for_model")
    assert_contains(ROUTE_FILE, "def _fold_fact_memory_notes_into_latest_user_message")
    assert_contains(ROUTE_FILE, "inject_context=(")
    assert_contains(ROUTE_FILE, "else 'fold_latest_user'")
    assert_contains(ROUTE_FILE, "Folded memory context into latest user message")
    assert_contains(ROUTE_FILE, "extract_chat_completion_response_text(fallback_response)")
    assert_contains(RUNTIME_FILE, "def build_model_endpoint_sync_chat_client")
    assert_contains(ROUTE_FILE, "build_model_endpoint_sync_chat_client(")
    assert_contains(WORKFLOW_FILE, "build_model_endpoint_sync_chat_client(")
    assert_contains(DOCUMENTS_FILE, "build_model_endpoint_sync_chat_client(")
    assert_contains(
        ROUTE_FILE,
        "The selected model returned an empty response. Check the model endpoint API version and provider compatibility",
    )
    assert_contains(ROUTE_FILE, "payload.get('type') != 'thought'")
    assert_contains(CONFIG_FILE, 'VERSION = "0.250.006"')

    print("✅ Empty model stream fallback markers verified.")


if __name__ == "__main__":
    success = True
    try:
        test_chat_stream_empty_model_fallback()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback

        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)