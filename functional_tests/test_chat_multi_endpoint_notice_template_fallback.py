# test_chat_multi_endpoint_notice_template_fallback.py
#!/usr/bin/env python3
"""
Functional test for chat multi-endpoint notice template fallback.
Version: 0.240.004
Implemented in: 0.240.004

This test ensures the chats template safely defaults the multi-endpoint notice
context, renders the notice markup only when enabled, and avoids Jinja
undefined errors when the route does not pass the notice object.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "chats.html"
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"


def test_chat_multi_endpoint_notice_template_fallback():
    """Verify the chats template safely handles a missing notice context."""
    template_content = CHAT_TEMPLATE.read_text(encoding="utf-8")
    config_content = CONFIG_FILE.read_text(encoding="utf-8")

    assert 'VERSION = "0.240.004"' in config_content, "Expected config.py version 0.240.004"
    assert '{% set multi_endpoint_notice_data = multi_endpoint_notice|default({}) %}' in template_content, (
        "Expected chats.html to define a safe default for multi_endpoint_notice."
    )
    assert '{% if multi_endpoint_notice_data.enabled %}' in template_content, (
        "Expected the chat multi-endpoint notice markup to be conditionally rendered."
    )
    assert 'id="multi-endpoint-notice"' in template_content, (
        "Expected chats.html to keep the multi-endpoint notice container for chat-onload.js."
    )
    assert 'window.multiEndpointNotice = JSON.parse(\'{{ multi_endpoint_notice_data|tojson()|safe }}\');' in template_content, (
        "Expected chats.html to serialize the safe default notice object for chat-onload.js."
    )
    assert '<!--\n            {% if multi_endpoint_notice.enabled %}' not in template_content, (
        "Expected chats.html to remove the HTML comment wrapper around active Jinja markup."
    )


if __name__ == "__main__":
    test_chat_multi_endpoint_notice_template_fallback()
    print("✅ Chat multi-endpoint notice template fallback verified.")
