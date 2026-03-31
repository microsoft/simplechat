#!/usr/bin/env python3
"""
Functional test for agent streaming tool fallback.
Version: 0.239.201
Implemented in: 0.239.201

This test ensures Semantic Kernel agent streaming retries once with tool
calling disabled for retryable tool-choice and header-size failures.
"""

from pathlib import Path
import traceback


ROOT = Path(__file__).resolve().parents[1]


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def test_agent_stream_retry_helpers() -> None:
    print("🧪 Running test_agent_stream_retry_helpers...")
    chats_path = ROOT / "application" / "single_app" / "route_backend_chats.py"

    assert_contains(chats_path, "def classify_agent_stream_retry_mode(stream_error):")
    assert_contains(chats_path, "def apply_agent_stream_retry_mode(agent, retry_mode):")
    assert_contains(chats_path, "def restore_agent_stream_retry_state(agent, retry_state):")
    assert_contains(chats_path, "'auto tool choice requires'")
    assert_contains(chats_path, "'tool-call-parser'")
    assert_contains(chats_path, "'header fields too large'")
    assert_contains(chats_path, "agent.function_choice_behavior = None")
    print("✅ Agent stream retry helpers verified.")


def test_agent_stream_retry_wiring() -> None:
    print("🧪 Running test_agent_stream_retry_wiring...")
    chats_path = ROOT / "application" / "single_app" / "route_backend_chats.py"

    assert_contains(chats_path, "candidate_retry_plan = classify_agent_stream_retry_mode(stream_error)")
    assert_contains(chats_path, "if candidate_retry_plan and not accumulated_content and attempt_number == 0:")
    assert_contains(chats_path, "retry_state = apply_agent_stream_retry_mode(")
    assert_contains(chats_path, "restore_agent_stream_retry_state(selected_agent, retry_state)")
    assert_contains(chats_path, "Retrying agent stream without tool calling")
    print("✅ Agent stream retry wiring verified.")


if __name__ == "__main__":
    tests = [
        test_agent_stream_retry_helpers,
        test_agent_stream_retry_wiring,
    ]
    results = []

    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"❌ {test.__name__} failed: {exc}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    raise SystemExit(0 if success else 1)