#!/usr/bin/env python3
# test_document_action_stream_reconnect.py
"""
Functional test for document action stream reconnect support.
Version: 0.250.070
Implemented in: 0.241.090

This test ensures analysis and document comparison streaming
requests register replayable chat stream sessions so reconnecting to an
active conversation resumes progress updates after navigation.
"""

from pathlib import Path
import traceback
from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def slice_between(content: str, start_marker: str, end_marker: str) -> str:
    start_index = content.find(start_marker)
    if start_index == -1:
        raise AssertionError(f"Expected to find start marker {start_marker!r}")

    end_index = content.find(end_marker, start_index)
    if end_index == -1:
        raise AssertionError(f"Expected to find end marker {end_marker!r} after {start_marker!r}")

    return content[start_index:end_index]


def test_document_action_stream_reconnect_wiring() -> None:
    print("🔍 Testing document action stream reconnect wiring...")

    config_content = read_text("application/single_app/config.py")
    route_content = read_text("application/single_app/route_backend_chats.py")

    document_action_stream_block = slice_between(
        route_content,
        "@bp.route('/api/chat/document-action/stream', methods=['POST'])",
        "@bp.route('/api/chat/analyze', methods=['POST'])",
    )
    analyze_stream_block = slice_between(
        route_content,
        "@bp.route('/api/chat/analyze/stream', methods=['POST'])",
        "@bp.route('/api/chat/image-proposals/generate', methods=['POST'])",
    )

    assert_app_version_at_least("0.250.070")
    assert "@bp.route('/api/chat/stream/status/<conversation_id>', methods=['GET'])" in route_content, (
        "Expected the shared chat stream status endpoint to exist for reconnect support."
    )
    assert "@bp.route('/api/chat/stream/reattach/<conversation_id>', methods=['GET'])" in route_content, (
        "Expected the shared chat stream reattach endpoint to exist for reconnect support."
    )

    assert "user_id = get_current_user_id()" in document_action_stream_block, (
        "Expected the document action streaming route to resolve the current user before creating a reconnectable stream session."
    )
    assert "stream_session = CHAT_STREAM_REGISTRY.start_session(user_id, conversation_id)" in document_action_stream_block, (
        "Expected the document action streaming route to register a replayable stream session."
    )
    assert "return build_background_stream_response(generate_document_action_response, stream_session=stream_session)" in document_action_stream_block, (
        "Expected the document action streaming route to publish events through the reconnectable stream session."
    )

    assert "user_id = get_current_user_id()" in analyze_stream_block, (
        "Expected the analysis streaming route to resolve the current user before creating a reconnectable stream session."
    )
    assert "stream_session = CHAT_STREAM_REGISTRY.start_session(user_id, conversation_id)" in analyze_stream_block, (
        "Expected the analysis streaming route to register a replayable stream session."
    )
    assert "return build_background_stream_response(generate_analyze_response, stream_session=stream_session)" in analyze_stream_block, (
        "Expected the analysis streaming route to publish events through the reconnectable stream session."
    )

    print("✅ Document action stream reconnect wiring verified")


def run_tests() -> bool:
    tests = [test_document_action_stream_reconnect_wiring]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            print("✅ Test passed")
            results.append(True)
        except Exception as exc:
            print(f"❌ Test failed: {exc}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)