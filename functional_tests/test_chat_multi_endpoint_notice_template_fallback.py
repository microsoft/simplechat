# test_chat_multi_endpoint_notice_template_fallback.py
# test_chat_multi_endpoint_notice_template_fallback.py
"""
Functional test for chat multi-endpoint notice template fallback.
Version: 0.240.008
Implemented in: 0.240.008

This test ensures the chats template safely defaults the multi-endpoint notice
context, renders the notice markup only when enabled, avoids Jinja
undefined errors when the route does not pass the notice object, and emits
the notice bootstrap data without JSON.parse string wrapping.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "chats.html"
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"


def test_chat_multi_endpoint_notice_template_fallback():
    """Verify the chats template safely handles a missing notice context."""
    template_content = CHAT_TEMPLATE.read_text(encoding="utf-8")
    config_content = CONFIG_FILE.read_text(encoding="utf-8")

    assert 'VERSION = "0.240.008"' in config_content, "Expected config.py version 0.240.008"
    assert '{% set multi_endpoint_notice_data = multi_endpoint_notice|default({}) %}' in template_content, (
        "Expected chats.html to define a safe default for multi_endpoint_notice."
    )
    assert '{% if multi_endpoint_notice_data.enabled %}' in template_content, (
        "Expected the chat multi-endpoint notice markup to be conditionally rendered."
    )
    assert 'id="multi-endpoint-notice"' in template_content, (
        "Expected chats.html to keep the multi-endpoint notice container for chat-onload.js."
    )
    assert 'window.multiEndpointNotice = {{ multi_endpoint_notice_data|tojson|safe }};' in template_content, (
        "Expected chats.html to serialize the safe default notice object for chat-onload.js."
    )
    assert 'window.multiEndpointNotice = JSON.parse(' not in template_content, (
        "Expected chats.html to avoid JSON.parse bootstrapping for notice data."
    )
    assert '<!--\n            {% if multi_endpoint_notice.enabled %}' not in template_content, (
        "Expected chats.html to remove the HTML comment wrapper around active Jinja markup."
    )


if __name__ == "__main__":
    test_chat_multi_endpoint_notice_template_fallback()
    print("✅ Chat multi-endpoint notice template fallback verified.")
