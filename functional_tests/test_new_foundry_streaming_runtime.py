# test_new_foundry_streaming_runtime.py
#!/usr/bin/env python3
"""
Functional test for new Foundry REST streaming runtime.
Version: 0.239.177
Implemented in: 0.239.177

This test ensures that new Foundry application discovery stays REST-based,
that the runtime exposes a streaming executor, and that the chat stream route
emits agent deltas as they arrive instead of buffering them first.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def assert_not_contains(file_path: Path, forbidden: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if forbidden in content:
        raise AssertionError(f"Did not expect to find {forbidden!r} in {file_path}")


def test_new_foundry_streaming_runtime() -> None:
    print("Testing new Foundry REST streaming runtime...")

    runtime_path = ROOT / "application" / "single_app" / "foundry_agent_runtime.py"
    chats_path = ROOT / "application" / "single_app" / "route_backend_chats.py"
    models_path = ROOT / "application" / "single_app" / "route_backend_models.py"
    config_path = ROOT / "application" / "single_app" / "config.py"

    assert_contains(runtime_path, "async def execute_new_foundry_agent_stream(")
    assert_contains(runtime_path, '"stream": stream')
    assert_contains(runtime_path, "stream=True,")
    assert_contains(runtime_path, "def _iter_sse_events(response: requests.Response):")
    assert_contains(runtime_path, "yield FoundryAgentStreamMessage(content=delta_text)")
    assert_not_contains(runtime_path, "from azure.ai.projects import AIProjectClient")

    assert_contains(models_path, 'agents = list_new_foundry_agents_from_endpoint(foundry_settings, get_settings())')

    assert_contains(chats_path, "agent_stream = selected_agent.invoke_stream(messages=agent_message_history)")
    assert_contains(chats_path, "response = loop.run_until_complete(agent_stream.__anext__())")
    assert_not_contains(chats_path, "chunks, stream_usage = loop.run_until_complete(stream_agent_async())")

    assert_contains(config_path, 'VERSION = "0.239.177"')

    print("✅ New Foundry REST streaming runtime verified.")


if __name__ == "__main__":
    try:
        test_new_foundry_streaming_runtime()
        success = True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        success = False

    raise SystemExit(0 if success else 1)