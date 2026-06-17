#!/usr/bin/env python3
# test_broken_access_control_guardrails_checker.py
"""
Functional test for Broken Access Control PR guardrail checker.
Version: 0.242.066
Implemented in: 0.241.022

This test ensures the changed-file BAC checker flags the repo's target
authorization-regression patterns, allows the approved helper-based patterns,
and stays wired into the repo instruction and PR workflow.
"""

import importlib.util
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CHECKER_FILE = ROOT_DIR / 'scripts' / 'check_broken_access_control.py'
WORKFLOW_FILE = ROOT_DIR / '.github' / 'workflows' / 'broken-access-control-check.yml'
FULL_SCAN_WORKFLOW_FILE = ROOT_DIR / '.github' / 'workflows' / 'broken-access-control-full-scan.yml'
INSTRUCTION_FILE = ROOT_DIR / '.github' / 'instructions' / 'broken-access-control-prevention.instructions.md'
PROMPT_FILE = ROOT_DIR / '.github' / 'prompts' / 'broken-access-control-audit.prompt.md'
ROUTE_AUTH_PROMPT_FILE = ROOT_DIR / '.github' / 'prompts' / 'route-authentication-audit.prompt.md'
FEATURE_DOC = ROOT_DIR / 'docs' / 'explanation' / 'features' / 'v0.241.022' / 'BROKEN_ACCESS_CONTROL_PR_GUARDRAILS.md'
FULL_SCAN_FEATURE_DOC = ROOT_DIR / 'docs' / 'explanation' / 'features' / 'BROKEN_ACCESS_CONTROL_FULL_REPO_AUDIT.md'
CONFIG_FILE = ROOT_DIR / 'application' / 'single_app' / 'config.py'


def read_text(path: Path) -> str:
    """Read a UTF-8 text file from the repository."""
    return path.read_text(encoding='utf-8')


def load_checker_module():
    """Import the checker module from disk without mutating sys.path."""
    spec = importlib.util.spec_from_file_location('check_broken_access_control', CHECKER_FILE)
    assert spec is not None and spec.loader is not None, 'Expected a module spec for check_broken_access_control.py'
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_config_version() -> str:
    """Extract the current application version from config.py."""
    for line in read_text(CONFIG_FILE).splitlines():
        if line.startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def issue_messages(module, relative_path: str, source_text: str) -> list[str]:
    """Return the issue messages emitted for one in-memory Python source string."""
    issues = module.inspect_source(ROOT_DIR / relative_path, source_text)
    return [issue.message for issue in issues]


def test_checker_flags_direct_active_scope_writes_and_raw_backend_reads() -> None:
    """Verify direct active scope writes and backend raw-setting reads are rejected."""
    module = load_checker_module()

    write_source = """
def persist_scope(user_id, group_id):
    update_user_settings(user_id, {'activeGroupOid': group_id})
""".strip()
    write_messages = issue_messages(
        module,
        'application/single_app/route_backend_example.py',
        write_source,
    )
    assert any('Do not persist activeGroupOid' in message for message in write_messages), write_messages

    read_source = """
def list_group_documents(settings):
    active_group_id = settings.get('settings', {}).get('activeGroupOid')
    return active_group_id
""".strip()
    read_messages = issue_messages(
        module,
        'application/single_app/route_backend_group_documents.py',
        read_source,
    )
    assert any('Avoid reading activeGroupOid from raw settings' in message for message in read_messages), read_messages


def test_checker_enforces_kernel_scope_normalization_and_conversation_auth_helpers() -> None:
    """Verify kernel tool surfaces and direct conversation reads need approved auth helpers."""
    module = load_checker_module()

    unsafe_kernel_source = """
class UnsafePlugin:
    @kernel_function(name='unsafe')
    def unsafe(self, user_id: str, conversation_id: str, group_id: str = ''):
        return {'user_id': user_id, 'conversation_id': conversation_id, 'group_id': group_id}
""".strip()
    kernel_messages = issue_messages(
        module,
        'application/single_app/semantic_kernel_plugins/unsafe_plugin.py',
        unsafe_kernel_source,
    )
    assert any('Kernel functions that expose' in message for message in kernel_messages), kernel_messages
    assert any('user_id' in message for message in kernel_messages), kernel_messages
    assert any('conversation_id' in message for message in kernel_messages), kernel_messages
    assert any('group_id' in message for message in kernel_messages), kernel_messages

    unsafe_conversation_source = """
def get_file_content(user_id, conversation_id):
    conversation_item = cosmos_conversations_container.read_item(item=conversation_id, partition_key=conversation_id)
    return conversation_item
""".strip()
    conversation_messages = issue_messages(
        module,
        'application/single_app/route_backend_documents.py',
        unsafe_conversation_source,
    )
    assert any('Avoid direct personal conversation reads' in message for message in conversation_messages), conversation_messages

    unsafe_user_profile_source = """
def register_route_backend_users(app):
    @app.route('/api/user/info/<user_id>', methods=['GET'])
    @login_required
    @user_required
    def api_get_user_info(user_id):
        return cosmos_user_settings_container.read_item(item=user_id, partition_key=user_id)
""".strip()
    user_profile_messages = issue_messages(
        module,
        'application/single_app/route_backend_users.py',
        unsafe_user_profile_source,
    )
    assert any(
        'Avoid direct user settings reads from request-derived user_id' in message
        for message in user_profile_messages
    ), user_profile_messages


def test_checker_allows_approved_helpers_and_reviewed_suppressions() -> None:
    """Verify approved helper patterns and reviewed suppressions stay allowed."""
    module = load_checker_module()

    allowed_write_source = """
def update_active_group_for_user(group_id, user_id):
    update_user_settings(user_id, {'activeGroupOid': group_id})
""".strip()
    assert issue_messages(
        module,
        'application/single_app/functions_group.py',
        allowed_write_source,
    ) == []

    allowed_read_source = """
def require_active_group(settings):
    return settings.get('settings', {}).get('activeGroupOid')
""".strip()
    assert issue_messages(
        module,
        'application/single_app/functions_group.py',
        allowed_read_source,
    ) == []

    safe_kernel_source = """
class SafePlugin:
    @kernel_function(name='safe')
    def safe(self, user_id: str, conversation_id: str, group_id: str = ''):
        authorized_context = self._resolve_authorized_scope_arguments(
            user_id,
            conversation_id,
            group_id=group_id,
        )
        return authorized_context
""".strip()
    assert issue_messages(
        module,
        'application/single_app/semantic_kernel_plugins/safe_plugin.py',
        safe_kernel_source,
    ) == []

    safe_conversation_source = """
def api_get_messages(user_id, conversation_id):
    _authorize_personal_conversation_read(user_id, conversation_id)
    conversation_item = cosmos_conversations_container.read_item(item=conversation_id, partition_key=conversation_id)
    return conversation_item
""".strip()
    assert issue_messages(
        module,
        'application/single_app/route_backend_conversations.py',
        safe_conversation_source,
    ) == []

    safe_user_profile_source = """
def api_get_user_info(user_id):
    _, normalized_user_id, user_doc = _read_authorized_user_profile_document(user_id)
    return normalized_user_id, user_doc
""".strip()
    assert issue_messages(
        module,
        'application/single_app/route_backend_users.py',
        safe_user_profile_source,
    ) == []

    suppressed_source = """
def load_scope(settings):
    # bac-check: ignore reviewed legacy compatibility shim
    return settings.get('settings', {}).get('activePublicWorkspaceOid')
""".strip()
    assert issue_messages(
        module,
        'application/single_app/route_backend_public_documents.py',
        suppressed_source,
    ) == []


def test_checker_assets_and_version_are_wired_into_repo() -> None:
    """Verify the new workflow, instruction, feature doc, and version bump landed together."""
    assert CHECKER_FILE.exists(), f'Expected checker script at {CHECKER_FILE}'
    assert WORKFLOW_FILE.exists(), f'Expected workflow file at {WORKFLOW_FILE}'
    assert FULL_SCAN_WORKFLOW_FILE.exists(), f'Expected full-scan workflow file at {FULL_SCAN_WORKFLOW_FILE}'
    assert INSTRUCTION_FILE.exists(), f'Expected instruction file at {INSTRUCTION_FILE}'
    assert PROMPT_FILE.exists(), f'Expected audit prompt at {PROMPT_FILE}'
    assert ROUTE_AUTH_PROMPT_FILE.exists(), f'Expected route auth audit prompt at {ROUTE_AUTH_PROMPT_FILE}'
    assert FEATURE_DOC.exists(), f'Expected feature document at {FEATURE_DOC}'
    assert FULL_SCAN_FEATURE_DOC.exists(), f'Expected full-scan feature document at {FULL_SCAN_FEATURE_DOC}'
    assert read_config_version() == '0.242.066'

    workflow_source = read_text(WORKFLOW_FILE)
    assert 'scripts/check_broken_access_control.py' in workflow_source
    assert 'functional_tests/test_broken_access_control_guardrails_checker.py' in workflow_source
    assert 'broken-access-control-full-scan.yml' in workflow_source
    assert 'route-authentication-audit.prompt.md' in workflow_source

    full_scan_workflow_source = read_text(FULL_SCAN_WORKFLOW_FILE)
    assert 'workflow_dispatch' in full_scan_workflow_source
    assert 'fail_on_findings' in full_scan_workflow_source
    assert '--full-file' in full_scan_workflow_source
    assert 'actions/upload-artifact@v4' in full_scan_workflow_source

    instruction_source = read_text(INSTRUCTION_FILE)
    assert 'bac-check: ignore' in instruction_source
    assert 'update_active_group_for_user(...)' in instruction_source
    assert '_resolve_authorized_scope_arguments(...)' in instruction_source
    assert '_read_authorized_user_profile_document(...)' in instruction_source
    assert 'broken-access-control-full-scan.yml' in instruction_source

    prompt_source = read_text(PROMPT_FILE)
    assert 'Broken Access Control Audit' in prompt_source
    assert 'IDOR' in prompt_source
    assert 'BOLA' in prompt_source
    assert 'Source' in prompt_source
    assert 'Sink' in prompt_source

    route_auth_prompt_source = read_text(ROUTE_AUTH_PROMPT_FILE)
    assert 'Route Authentication Audit' in route_auth_prompt_source
    assert '@login_required' in route_auth_prompt_source
    assert '@user_required' in route_auth_prompt_source
    assert '@admin_required' in route_auth_prompt_source

    feature_doc_source = read_text(FEATURE_DOC)
    assert 'Fixed/Implemented in version: **0.241.022**' in feature_doc_source
    assert 'scripts/check_broken_access_control.py' in feature_doc_source
    assert '.github/workflows/broken-access-control-check.yml' in feature_doc_source

    full_scan_feature_doc_source = read_text(FULL_SCAN_FEATURE_DOC)
    assert 'Fixed/Implemented in version: **0.241.203**' in full_scan_feature_doc_source
    assert '.github/workflows/broken-access-control-full-scan.yml' in full_scan_feature_doc_source
    assert '.github/prompts/broken-access-control-audit.prompt.md' in full_scan_feature_doc_source


if __name__ == '__main__':
    tests = [
        test_checker_flags_direct_active_scope_writes_and_raw_backend_reads,
        test_checker_enforces_kernel_scope_normalization_and_conversation_auth_helpers,
        test_checker_allows_approved_helpers_and_reviewed_suppressions,
        test_checker_assets_and_version_are_wired_into_repo,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            test()
            print('✅ PASS')
            results.append(True)
        except Exception as exc:  # pragma: no cover - standalone script reporting
            print(f'❌ FAIL: {exc}')
            results.append(False)

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)