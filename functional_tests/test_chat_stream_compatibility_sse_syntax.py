#!/usr/bin/env python3
# test_chat_stream_compatibility_sse_syntax.py
"""
Functional test for chat stream compatibility SSE syntax.
Version: 0.239.136
Implemented in: 0.239.134

This test ensures that the streaming chat route compiles successfully and that
the compatibility SSE bridge builds image-generation thought payloads outside
the f-string expression so parser regressions are caught early.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
FIX_DOC_FILE = ROOT / "docs" / "explanation" / "fixes" / "CHAT_STREAM_COMPATIBILITY_SSE_SYNTAX_FIX.md"


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def test_chat_stream_compatibility_sse_syntax() -> bool:
    print("Testing chat stream compatibility SSE syntax...")

    source = ROUTE_FILE.read_text(encoding="utf-8")
    compile(source, str(ROUTE_FILE), "exec")

    assert_contains(ROUTE_FILE, "image_prompt_event = {")
    assert_contains(ROUTE_FILE, "image_request_event = {")
    assert_contains(ROUTE_FILE, "image_ready_event = {")
    assert_contains(ROUTE_FILE, 'yield f"data: {json.dumps(image_prompt_event)}\\n\\n"')
    assert_contains(CONFIG_FILE, 'VERSION = "0.239.136"')
    assert_contains(FIX_DOC_FILE, "Fixed/Implemented in version: **0.239.134**")

    print("Chat stream compatibility SSE syntax checks passed!")
    return True


if __name__ == "__main__":
    try:
        success = test_chat_stream_compatibility_sse_syntax()
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)