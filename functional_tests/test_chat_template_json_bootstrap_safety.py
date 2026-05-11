# test_chat_template_json_bootstrap_safety.py
"""
Functional test for chat template JSON bootstrap safety.
Version: 0.240.008
Implemented in: 0.240.008

This test ensures the chats template emits bootstrapped chat data as direct
JavaScript literals rather than wrapping Jinja JSON output in JSON.parse
string literals that can break when payload values contain control characters.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "chats.html"
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"

SAFE_ASSIGNMENTS = [
    "window.enableUserFeedback = {{ enable_user_feedback|tojson }};",
    "window.activeGroupId = {{ active_group_id|tojson }};",
    "window.activeGroupName = {{ active_group_name|tojson }};",
    "window.activePublicWorkspaceId = {{ active_public_workspace_id|tojson }};",
    "window.userGroups = {{ user_groups|default([], true)|tojson|safe }};",
    "window.userVisiblePublicWorkspaces = {{ user_visible_public_workspaces|default([], true)|tojson|safe }};",
    "window.chatPromptOptions = {{ chat_prompt_options|default([], true)|tojson|safe }};",
    "window.chatAgentOptions = {{ chat_agent_options|default([], true)|tojson|safe }};",
    "window.chatModelOptions = {{ chat_model_options|default([], true)|tojson|safe }};",
    "window.enableEnhancedCitations = {{ enable_enhanced_citations|tojson }};",
    "window.enable_document_classification = {{ enable_document_classification|tojson }};",
    "window.classification_categories = {{ settings.document_classification_categories|default([], true)|tojson(indent=None)|safe }};",
    "id: {{ user_id|tojson }},",
    "display_name: {{ user_display_name|tojson }}",
    "enable_text_to_speech: {{ app_settings.enable_text_to_speech|tojson }},",
    "enable_speech_to_text_input: {{ app_settings.enable_speech_to_text_input|tojson }},",
    "enable_web_search_user_notice: {{ settings.enable_web_search_user_notice|tojson }},",
    "enforce_workspace_scope_lock: {{ settings.enforce_workspace_scope_lock|tojson }},",
    "enable_multi_model_endpoints: {{ enable_multi_model_endpoints|tojson }},",
    "enable_thoughts: {{ settings.enable_thoughts|tojson }}",
    "window.multiEndpointNotice = {{ multi_endpoint_notice_data|tojson|safe }};",
]

UNSAFE_PARSE_SNIPPETS = [
    "window.userGroups = JSON.parse('{{ user_groups|tojson|safe }}');",
    "window.userVisiblePublicWorkspaces = JSON.parse('{{ user_visible_public_workspaces|tojson|safe }}');",
    "window.chatPromptOptions = JSON.parse('{{ chat_prompt_options|tojson|safe }}');",
    "window.chatAgentOptions = JSON.parse('{{ chat_agent_options|tojson|safe }}');",
    "window.chatModelOptions = JSON.parse('{{ chat_model_options|tojson|safe }}');",
    "window.classification_categories = JSON.parse('{{ settings.document_classification_categories|tojson(indent=None)|safe }}' || '[]');",
    "window.multiEndpointNotice = JSON.parse('{{ multi_endpoint_notice_data|tojson()|safe }}');",
]


def test_chat_template_bootstraps_json_with_direct_literals():
    """Verify chats.html emits safe direct literals for bootstrapped JSON data."""
    template_content = CHAT_TEMPLATE.read_text(encoding="utf-8")
    config_content = CONFIG_FILE.read_text(encoding="utf-8")

    assert 'VERSION = "0.240.008"' in config_content, "Expected config.py version 0.240.008"

    missing_safe_assignments = [
        snippet for snippet in SAFE_ASSIGNMENTS if snippet not in template_content
    ]
    assert not missing_safe_assignments, (
        "Expected chats.html to bootstrap data with direct tojson literals. "
        f"Missing: {missing_safe_assignments}"
    )

    present_unsafe_snippets = [
        snippet for snippet in UNSAFE_PARSE_SNIPPETS if snippet in template_content
    ]
    assert not present_unsafe_snippets, (
        "Expected chats.html to avoid JSON.parse-wrapped template payloads. "
        f"Found: {present_unsafe_snippets}"
    )


if __name__ == "__main__":
    test_chat_template_bootstraps_json_with_direct_literals()
    print("✅ Chat template JSON bootstrap safety verified.")