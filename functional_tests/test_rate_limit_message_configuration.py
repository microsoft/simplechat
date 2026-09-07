#!/usr/bin/env python3
# test_rate_limit_message_configuration.py
"""
Functional test for the admin-configurable rate limiting (429) response message.
Version: 0.261.001
Implemented in: 0.261.001

This test ensures that a rate limited user always receives a usable message,
that an administrator can replace it with Markdown of their own, and that every
429 surface resolves the message from one shared place instead of carrying its
own hard-coded string.

Refs: https://github.com/microsoft/simplechat/issues/1354
"""

import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(APP_ROOT))

from functions_rate_limit import (  # noqa: E402
    RATE_LIMIT_MESSAGE_DEFAULT,
    RATE_LIMIT_MESSAGE_MAX_LENGTH,
    build_rate_limit_error_payload,
    build_rate_limit_message,
    normalize_rate_limit_message,
)


def read_app_file(relative_path):
    """Return the text of a file under the application directory."""
    return (APP_ROOT / relative_path).read_text(encoding="utf-8")


def test_default_message_is_used_when_not_customized():
    """A throttled user must never receive an empty or missing message."""
    print("Testing rate limit message fallbacks...")

    try:
        assert build_rate_limit_message({}) == RATE_LIMIT_MESSAGE_DEFAULT, \
            "Empty settings should fall back to the built-in message."

        assert build_rate_limit_message(None) == RATE_LIMIT_MESSAGE_DEFAULT, \
            "Non-dict settings should fall back to the built-in message."

        toggle_off = {
            "enable_custom_rate_limit_message": False,
            "rate_limit_message": "Custom wording that must stay hidden.",
        }
        assert build_rate_limit_message(toggle_off) == RATE_LIMIT_MESSAGE_DEFAULT, \
            "A stored message must not be shown while the toggle is off."

        for blank_value in ("", "   ", "\n\n", None):
            blank_settings = {
                "enable_custom_rate_limit_message": True,
                "rate_limit_message": blank_value,
            }
            assert build_rate_limit_message(blank_settings) == RATE_LIMIT_MESSAGE_DEFAULT, \
                f"Blank message {blank_value!r} should fall back to the built-in message."

        assert RATE_LIMIT_MESSAGE_DEFAULT.strip(), "The built-in message must not be empty."

        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_custom_message_is_normalized_and_returned():
    """An enabled custom message is returned, normalized, and bounded."""
    print("Testing custom rate limit message handling...")

    try:
        custom_settings = {
            "enable_custom_rate_limit_message": True,
            "rate_limit_message": "  **Slow down**\r\n\r\nTry again in 60 seconds.  ",
        }
        resolved = build_rate_limit_message(custom_settings)

        assert resolved == "**Slow down**\n\nTry again in 60 seconds.", \
            f"Expected normalized Markdown, got {resolved!r}"
        assert "\r" not in resolved, "Carriage returns must be normalized away."

        over_long = normalize_rate_limit_message("x" * (RATE_LIMIT_MESSAGE_MAX_LENGTH + 500))
        assert len(over_long) == RATE_LIMIT_MESSAGE_MAX_LENGTH, \
            f"Message should be bounded to {RATE_LIMIT_MESSAGE_MAX_LENGTH}, got {len(over_long)}"

        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_error_payload_shape():
    """The shared payload carries the message and the rate_limited flag."""
    print("Testing rate limit error payload...")

    try:
        payload = build_rate_limit_error_payload({}, retry_after=60)

        assert payload["error"] == RATE_LIMIT_MESSAGE_DEFAULT, \
            "Payload must carry the resolved message under 'error'."
        assert payload["rate_limited"] is True, \
            "Payload must flag itself so the client can render Markdown."
        assert payload["retry_after"] == 60, "Extra values should pass through."

        assert "retry_after" not in build_rate_limit_error_payload({}, retry_after=None), \
            "None extras should be omitted rather than serialized as null."

        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_settings_defaults_and_sanitization():
    """Both keys ship as defaults and survive frontend sanitization."""
    print("Testing settings defaults and sanitization passthrough...")

    try:
        settings_source = read_app_file("functions_settings.py")

        assert "'enable_custom_rate_limit_message': False," in settings_source, \
            "enable_custom_rate_limit_message must ship as a default settings key."
        assert "'rate_limit_message': RATE_LIMIT_MESSAGE_DEFAULT," in settings_source, \
            "rate_limit_message must ship seeded with the built-in default."
        assert "def get_rate_limit_message(" in settings_source, \
            "functions_settings must expose the shared resolver."

        # sanitize_settings_for_user drops any key containing a sensitive term,
        # so confirm neither new key would be stripped before it reaches a page.
        sensitive_terms = ("key", "secret", "password", "connection", "base64", "storage_account_url")
        for settings_key in ("enable_custom_rate_limit_message", "rate_limit_message"):
            matched = [term for term in sensitive_terms if term in settings_key.lower()]
            assert not matched, \
                f"{settings_key} would be stripped by sanitization because of {matched}."

        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_admin_settings_persist_and_expose_the_controls():
    """The admin form saves both keys and the tab is registered and rendered."""
    print("Testing admin settings wiring...")

    try:
        admin_route_source = read_app_file("route_frontend_admin_settings.py")
        assert "'enable_custom_rate_limit_message': enable_custom_rate_limit_message," in admin_route_source, \
            "The toggle must be persisted on save."
        assert "'rate_limit_message': rate_limit_message," in admin_route_source, \
            "The message must be persisted on save."
        assert "normalize_rate_limit_message(" in admin_route_source, \
            "The saved message must be normalized before persistence."

        nav_source = read_app_file("admin_settings_nav.py")
        assert '"id": "rate-limiting"' in nav_source, \
            "The Rate Limiting tab must be registered in the admin navigation."
        assert '"id": "rate-limit-message-section"' in nav_source, \
            "The Rate Limit Message section must be registered."

        pane_source = read_app_file("templates/admin/_panes/rate-limiting.html")
        assert 'id="rate-limiting"' in pane_source, "The pane must define the tab id."
        assert 'id="rate-limit-message-section"' in pane_source, \
            "The pane must define the section card id used by cross-references."
        assert 'name="enable_custom_rate_limit_message"' in pane_source, \
            "The toggle must post its form field."
        assert 'name="rate_limit_message"' in pane_source, \
            "The message must post its form field."

        admin_template_source = read_app_file("templates/admin_settings.html")
        assert 'admin/_panes/rate-limiting.html' in admin_template_source, \
            "The pane must be included in the admin settings tab content."

        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_every_429_surface_uses_the_shared_message():
    """No 429 surface may keep its own hard-coded explanation."""
    print("Testing that all 429 surfaces resolve the shared message...")

    try:
        app_source = read_app_file("app.py")
        assert "@app.errorhandler(429)" in app_source, \
            "A global 429 error handler must exist."
        assert "build_rate_limit_error_payload(" in app_source, \
            "The global handler must return the shared JSON payload."
        assert "errors/429.html" in app_source, \
            "The global handler must render a page for browser navigations."

        tts_source = read_app_file("route_backend_tts.py")
        assert "build_rate_limit_error_payload(settings)" in tts_source, \
            "Text to speech must use the shared payload."
        assert "Service temporarily unavailable due to high load" not in tts_source, \
            "The old hard-coded text to speech message must be gone."

        swagger_source = read_app_file("swagger_wrapper.py")
        assert "Too many requests for swagger.json" not in swagger_source, \
            "The old hard-coded swagger.json message must be gone."
        assert "Too many requests for swagger.yaml" not in swagger_source, \
            "The old hard-coded swagger.yaml message must be gone."
        assert swagger_source.count("build_rate_limit_error_payload(") >= 2, \
            "Both swagger spec endpoints must use the shared payload."

        mcp_source = read_app_file("route_inbound_mcp.py")
        assert "get_rate_limit_message()" in mcp_source, \
            "Inbound MCP must use the shared message."
        assert "Inbound MCP tool rate limit exceeded." not in mcp_source, \
            "The old hard-coded inbound MCP message must be gone."
        assert "rate_limit.to_public_dict()" in mcp_source, \
            "Inbound MCP must keep its structured backoff data."

        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_chat_streaming_reports_exhausted_throttling():
    """An exhausted throttle in chat is reported as rate limiting, not a fault."""
    print("Testing chat streaming rate limit classification...")

    try:
        chat_source = read_app_file("route_backend_chats.py")

        assert "def is_rate_limit_error(" in chat_source, \
            "Chat must classify throttling separately from other failures."
        assert "stream_rate_limited = is_rate_limit_error(error_msg, e)" in chat_source, \
            "The streaming failure path must classify the error."
        assert "rate_limited=stream_rate_limited or None," in chat_source, \
            "The stream error event must flag rate limiting for the client."
        assert "status_code=429 if stream_rate_limited else None," in chat_source, \
            "The stream error event must carry the 429 status for rate limiting."
        assert "'rate_limited' if stream_rate_limited else 'stream_interrupted'" in chat_source, \
            "Persisted metadata must record that the interruption was throttling."

        # get_safe_stream_error_message only masks statuses >= 500, so a 429
        # message reaches the client intact. Guard that assumption.
        assert "if status_code >= 500 and not (" in chat_source, \
            "Stream error masking must remain limited to server errors."

        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_frontend_renders_markdown_only_for_rate_limits():
    """The banner renders Markdown for throttling without loosening other errors."""
    print("Testing chat streaming frontend rendering...")

    try:
        streaming_source = read_app_file("static/js/chat/chat-streaming.js")

        assert "const rateLimited = errorPayload.rate_limited === true;" in streaming_source, \
            "The banner must detect the rate_limited flag."
        assert "DOMPurify.sanitize(marked.parse(markdownText))" in streaming_source, \
            "Markdown must be sanitized before it is inserted."
        assert "function toPlainTextSummary(" in streaming_source, \
            "The toast must show a plain-text summary rather than raw Markdown."

        # Other stream errors must keep their text-node rendering.
        assert "errorBanner.appendChild(document.createTextNode(` ${displayMessage}`));" in streaming_source, \
            "Non-rate-limit errors must still render as plain text."

        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_documentation_claims_the_capability():
    """Docs coverage requires the tab anchor and a features.yml claim."""
    print("Testing documentation coverage...")

    try:
        security_doc = (REPO_ROOT / "docs" / "admin" / "security.md").read_text(encoding="utf-8")
        assert "{#rate-limiting}" in security_doc, \
            "The Rate Limiting tab needs a heading anchor on its group page."
        assert "{#rate-limit-message-section}" in security_doc, \
            "The Rate Limit Message section needs a heading anchor."
        assert "enable_custom_rate_limit_message" in security_doc, \
            "The settings table must name the capability key."

        features_doc = (REPO_ROOT / "docs" / "_data" / "features.yml").read_text(encoding="utf-8")
        assert "enable_custom_rate_limit_message" in features_doc, \
            "features.yml must claim the capability key."

        inventory = (REPO_ROOT / "docs" / "_data" / "app_surface.yml").read_text(encoding="utf-8")
        assert "id: rate-limiting" in inventory, \
            "The regenerated inventory must include the new tab."

        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_version_is_at_least_implementation_version():
    """The application version must include this feature."""
    print("Testing application version...")

    try:
        assert_app_version_at_least("0.261.001")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_default_message_is_used_when_not_customized,
        test_custom_message_is_normalized_and_returned,
        test_error_payload_shape,
        test_settings_defaults_and_sanitization,
        test_admin_settings_persist_and_expose_the_controls,
        test_every_429_surface_uses_the_shared_message,
        test_chat_streaming_reports_exhausted_throttling,
        test_frontend_renders_markdown_only_for_rate_limits,
        test_documentation_claims_the_capability,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
