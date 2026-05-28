#!/usr/bin/env python3
# test_chat_file_upload_access_control.py
"""
Functional test for chat file upload access control and client enablement.
Version: 0.241.111
Implemented in: 0.241.110

This test ensures chat follow-up uploads can be globally disabled or limited to
users with the ChatFileUploadUser app role, while workspace uploads remain under
their existing controls. It also prevents regression where the chat page omitted
the effective upload setting from the frontend app settings object.
"""

import os
import re
import sys
import traceback


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
FUNCTIONS_SETTINGS_FILE = os.path.join(APP_ROOT, "functions_settings.py")
ROUTE_FRONTEND_CHATS_FILE = os.path.join(APP_ROOT, "route_frontend_chats.py")
ADMIN_SETTINGS_ROUTE_FILE = os.path.join(APP_ROOT, "route_frontend_admin_settings.py")
CHAT_TEMPLATE_FILE = os.path.join(APP_ROOT, "templates", "chats.html")
ADMIN_TEMPLATE_FILE = os.path.join(APP_ROOT, "templates", "admin_settings.html")
CHAT_INPUT_ACTIONS_FILE = os.path.join(APP_ROOT, "static", "js", "chat", "chat-input-actions.js")
APP_ROLES_FILE = os.path.join(REPO_ROOT, "deployers", "azurecli", "appRegistrationRoles.json")
TERRAFORM_FILE = os.path.join(REPO_ROOT, "deployers", "terraform", "main.tf")
CONFIG_FILE = os.path.join(APP_ROOT, "config.py")
FEATURE_DOC_FILE = os.path.join(
    REPO_ROOT,
    "docs",
    "explanation",
    "features",
    "CHAT_FILE_UPLOAD_ACCESS_CONTROL.md",
)
FIX_DOC_FILE = os.path.join(
    REPO_ROOT,
    "docs",
    "explanation",
    "fixes",
    "CHAT_FILE_UPLOAD_CLIENT_FLAG_FIX.md",
)

CURRENT_VERSION = "0.241.111"
ACCESS_CONTROL_VERSION = "0.241.098"
CLIENT_FLAG_FIX_VERSION = "0.241.110"


def read_file(path):
    """Read a UTF-8 text file from the repo."""
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def read_version():
    """Read the current SimpleChat application version from config.py."""
    config_source = read_file(CONFIG_FILE)
    version_match = re.search(r'VERSION = "([0-9.]+)"', config_source)
    if not version_match:
        raise AssertionError("VERSION assignment not found in config.py")
    return version_match.group(1)


def test_settings_defaults_and_role_helper():
    """Verify chat upload defaults and role helper are present."""
    print("Testing chat file upload settings defaults and helper...")

    settings_source = read_file(FUNCTIONS_SETTINGS_FILE)
    required_snippets = [
        'CHAT_FILE_UPLOAD_APP_ROLE = "ChatFileUploadUser"',
        "def normalize_app_role_claims(user_roles):",
        "def has_chat_file_upload_app_role(user_roles):",
        "def is_chat_file_upload_enabled_for_user(settings, user_roles=None, authorization_prechecked=False):",
        "'enable_chat_file_uploads': True,",
        "'require_member_of_chat_file_upload_user': False,",
    ]

    missing = [snippet for snippet in required_snippets if snippet not in settings_source]
    assert not missing, f"Missing settings/helper snippets: {missing}"

    print("Settings defaults and helper passed")


def test_backend_upload_route_enforces_role_gate():
    """Verify the chat upload route enforces the global and app role policies."""
    print("Testing backend chat upload enforcement...")

    route_source = read_file(ROUTE_FRONTEND_CHATS_FILE)
    required_snippets = [
        "chat_file_upload_enabled_for_user = is_chat_file_upload_enabled_for_user(settings, current_user_roles)",
        "public_settings['enable_chat_file_uploads'] = chat_file_upload_enabled_for_user",
        "if not settings.get('enable_chat_file_uploads', True):",
        "Chat file uploads are disabled.",
        "settings.get('require_member_of_chat_file_upload_user', False)",
        "not has_chat_file_upload_app_role(current_user_roles)",
        "Chat file uploads require the ChatFileUploadUser app role.",
    ]

    missing = [snippet for snippet in required_snippets if snippet not in route_source]
    assert not missing, f"Missing backend enforcement snippets: {missing}"

    print("Backend enforcement passed")


def test_admin_settings_persist_chat_upload_controls():
    """Verify Admin Settings exposes and persists the chat upload controls."""
    print("Testing admin settings chat upload controls...")

    admin_route_source = read_file(ADMIN_SETTINGS_ROUTE_FILE)
    admin_template_source = read_file(ADMIN_TEMPLATE_FILE)

    required_route_snippets = [
        "settings['enable_chat_file_uploads'] = True",
        "settings['require_member_of_chat_file_upload_user'] = False",
        "require_member_of_chat_file_upload_user = form_data.get('require_member_of_chat_file_upload_user') == 'on'",
        "'enable_chat_file_uploads': form_data.get('enable_chat_file_uploads') == 'on',",
        "'require_member_of_chat_file_upload_user': require_member_of_chat_file_upload_user,",
    ]
    required_template_snippets = [
        'id="chat-file-uploads-section"',
        'name="enable_chat_file_uploads"',
        'name="require_member_of_chat_file_upload_user"',
        "ChatFileUploadUser",
        "Existing chat attachments remain visible; this only controls new uploads.",
    ]

    missing_route = [snippet for snippet in required_route_snippets if snippet not in admin_route_source]
    missing_template = [snippet for snippet in required_template_snippets if snippet not in admin_template_source]
    assert not missing_route, f"Missing admin route snippets: {missing_route}"
    assert not missing_template, f"Missing admin template snippets: {missing_template}"

    print("Admin settings controls passed")


def test_chat_ui_hides_and_guards_upload_controls():
    """Verify chat upload UI rendering and client-side guards use the effective setting."""
    print("Testing chat UI upload gates...")

    chat_template_source = read_file(CHAT_TEMPLATE_FILE)
    chat_js_source = read_file(CHAT_INPUT_ACTIONS_FILE)

    required_template_snippets = [
        "{% if settings.enable_chat_file_uploads %}",
        'id="file-input"',
        'id="choose-file-btn"',
        "enable_chat_file_uploads: {{ settings.enable_chat_file_uploads|tojson }},",
    ]
    required_js_snippets = [
        "function isChatFileUploadEnabled() {",
        "function showChatFileUploadDisabledToast() {",
        "Chat file uploads are not enabled for your account.",
        "if (!isChatFileUploadEnabled()) {",
        'event.dataTransfer.dropEffect = "none";',
        'beginChatFileUpload(droppedFiles, { fallbackPrefix: "dropped_file" });',
    ]

    missing_template = [snippet for snippet in required_template_snippets if snippet not in chat_template_source]
    missing_js = [snippet for snippet in required_js_snippets if snippet not in chat_js_source]
    assert not missing_template, f"Missing chat template snippets: {missing_template}"
    assert not missing_js, f"Missing chat JS snippets: {missing_js}"

    print("Chat UI gates passed")


def test_chat_ui_exposes_effective_upload_flag_to_client():
    """Verify the server-rendered effective setting reaches chat upload JavaScript."""
    print("Testing chat UI app settings upload flag exposure...")

    chat_template_source = read_file(CHAT_TEMPLATE_FILE)
    chat_js_source = read_file(CHAT_INPUT_ACTIONS_FILE)

    expected_template_snippet = "enable_chat_file_uploads: {{ settings.enable_chat_file_uploads|tojson }},"
    assert expected_template_snippet in chat_template_source
    assert "Boolean(window.appSettings?.enable_chat_file_uploads)" in chat_js_source

    app_settings_index = chat_template_source.index("window.appSettings = {")
    upload_flag_index = chat_template_source.index(expected_template_snippet)
    assert upload_flag_index > app_settings_index, "Upload flag must be serialized inside window.appSettings."

    print("Chat UI app settings upload flag exposure passed")


def test_app_role_definitions_and_versions_are_updated():
    """Verify app role definitions, feature documentation, and version tracking were updated."""
    print("Testing app role definitions and version tracking...")

    app_roles_source = read_file(APP_ROLES_FILE)
    terraform_source = read_file(TERRAFORM_FILE)
    feature_doc_source = read_file(FEATURE_DOC_FILE)
    fix_doc_source = read_file(FIX_DOC_FILE)
    version = read_version()

    assert version == CURRENT_VERSION, f"Expected config VERSION to be {CURRENT_VERSION}, found {version}"
    assert '"value": "ChatFileUploadUser"' in app_roles_source
    assert '"id": "3f6ec07d-db95-4c0e-ab03-0645b95736e3"' in app_roles_source
    assert 'value                = "ChatFileUploadUser"' in terraform_source
    assert 'role_id              = "3f6ec07d-db95-4c0e-ab03-0645b95736e3"' in terraform_source
    assert f"Implemented in version: **{ACCESS_CONTROL_VERSION}**" in feature_doc_source
    assert "Related config.py version update" in feature_doc_source
    assert f"Fixed in version: **{CLIENT_FLAG_FIX_VERSION}**" in fix_doc_source

    print("App role definitions and version tracking passed")


if __name__ == "__main__":
    tests = [
        test_settings_defaults_and_role_helper,
        test_backend_upload_route_enforces_role_gate,
        test_admin_settings_persist_chat_upload_controls,
        test_chat_ui_hides_and_guards_upload_controls,
        test_chat_ui_exposes_effective_upload_flag_to_client,
        test_app_role_definitions_and_versions_are_updated,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            traceback.print_exc()
            results.append(False)

    passed = sum(results)
    total = len(results)
    print(f"\nResults: {passed}/{total} tests passed")
    sys.exit(0 if all(results) else 1)