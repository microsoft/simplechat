# test_chat_error_response_sanitization.py
#!/usr/bin/env python3
"""
Functional test for chat error response sanitization.
Version: 0.250.113
Implemented in: 0.250.113

This test ensures that unexpected chat exceptions are logged server-side and
browser-visible JSON/SSE responses do not include raw exception text,
traceback details, provider class names, local paths, or internal descriptors.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"


def read_chat_route():
    """Return the chat route source for response-boundary assertions."""
    return CHAT_ROUTE_FILE.read_text(encoding="utf-8")


def assert_not_contains(content, unexpected):
    """Fail with a readable message when an unsafe source pattern remains."""
    if unexpected in content:
        raise AssertionError(f"Unsafe browser response pattern remains: {unexpected}")


def assert_contains(content, expected):
    """Fail with a readable message when an expected safe pattern is missing."""
    if expected not in content:
        raise AssertionError(f"Expected safe response pattern is missing: {expected}")


def test_unexpected_exception_text_is_not_sent_to_browser():
    """Validate known raw exception response patterns are removed."""
    content = read_chat_route()
    unsafe_patterns = [
        "Internal server error: {str(e)}",
        "Failed to initialize AI model: {str(e)}",
        "Error reading conversation: {str(e)}",
        "Error preparing conversation history: {str(e)}",
        "Model initialization failed: {str(e)}",
        "History error: {str(e)}",
        "Agent streaming failed: {str(stream_error)}",
        "Failed to parse request: {str(e)}",
        "Error fetching message: {str(e)}",
        "Error updating message: {str(e)}",
        "Details: {str(e)}",
        "Image generation request was invalid: {error_message}",
        "Image generation failed due to a technical error: {error_message}",
        "'details': error_traceback if current_app.debug else None",
        "{'error': error_msg, 'partial_content': accumulated_content}",
    ]
    for unsafe_pattern in unsafe_patterns:
        assert_not_contains(content, unsafe_pattern)


def test_safe_json_and_sse_helpers_are_used():
    """Validate route-level JSON and SSE responses use stable public messages."""
    content = read_chat_route()
    expected_patterns = [
        "CLIENT_SAFE_INTERNAL_ERROR_MESSAGE = 'Something went wrong while processing the request. Please try again.'",
        "CLIENT_SAFE_STREAM_ERROR_MESSAGE = 'Something went wrong while streaming the response. Please try again.'",
        "def build_stream_error_event(message=CLIENT_SAFE_STREAM_ERROR_MESSAGE, **extra):",
        "def build_json_error_response(message=CLIENT_SAFE_INTERNAL_ERROR_MESSAGE, status_code=500, **extra):",
        "return jsonify({'error': 'Invalid request payload'}), 400",
        "return build_json_error_response('Failed to initialize AI model')",
        "return build_json_error_response('Failed to read conversation')",
        "return build_json_error_response('Failed to prepare conversation history')",
        "yield build_stream_error_event('Failed to initialize AI model')",
        "yield build_stream_error_event('Failed to prepare conversation history')",
        "return jsonify({'error': 'Document context request is invalid. Please review the selected sources and try again.'}), 400",
        "return jsonify({'error': 'Selected document context is unavailable. Please refresh and try again.'}), 400",
        "return jsonify({'error': 'Invalid mask request'}), 400",
        "'error': 'Document action request is invalid. Please review the selected documents and try again.'",
    ]
    for expected_pattern in expected_patterns:
        assert_contains(content, expected_pattern)


def test_stream_partial_content_keeps_sanitized_error_metadata():
    """Validate partial SSE content can flow without raw exception metadata."""
    content = read_chat_route()
    expected_patterns = [
        "'error': 'stream_interrupted',",
        "'error_message': CLIENT_SAFE_STREAM_ERROR_MESSAGE,",
        "yield build_stream_error_event(",
        "partial_content=accumulated_content,",
    ]
    for expected_pattern in expected_patterns:
        assert_contains(content, expected_pattern)

    unsafe_metadata_patterns = [
        "'error': error_msg,",
        '"error": error_msg,',
        "yield f\"data: {json.dumps({'error': error_msg, 'partial_content': accumulated_content})}",
    ]
    for unsafe_pattern in unsafe_metadata_patterns:
        assert_not_contains(content, unsafe_pattern)


def test_intentional_user_facing_contracts_are_preserved():
    """Validate allowlisted auth, validation, and content-safety responses remain."""
    content = read_chat_route()
    expected_patterns = [
        "return jsonify({'error': 'Conversation not found'}), 404",
        "return jsonify({'error': 'Forbidden'}), 403",
        "return jsonify({'error': 'User not authenticated'}), 401",
        "Image generation was blocked by content safety policies",
        "if isinstance(stream_error, FoundryAgentUserAuthenticationRequired):",
        "'auth_required': True",
        "'scopes': auth_response.get('scopes') or [],",
    ]
    for expected_pattern in expected_patterns:
        assert_contains(content, expected_pattern)


def main():
    """Run the focused sanitization checks."""
    tests = [
        test_unexpected_exception_text_is_not_sent_to_browser,
        test_safe_json_and_sse_helpers_are_used,
        test_stream_partial_content_keeps_sanitized_error_metadata,
        test_intentional_user_facing_contracts_are_preserved,
    ]
    for test in tests:
        print(f"Running {test.__name__}...")
        test()
    print("All chat error response sanitization checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())