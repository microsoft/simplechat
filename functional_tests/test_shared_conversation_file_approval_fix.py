#!/usr/bin/env python3
# test_shared_conversation_file_approval_fix.py
"""
Functional test for shared conversation file generation and owner approvals.
Version: 0.260.004
Implemented in: 0.260.004

This test ensures that a non-owner participant of a shared (collaborative) conversation can
invoke the AI without a "Forbidden" stream interruption, that downloadable files they generate
are staged for approval instead of failing, and that a staged file stays unreachable until an
authorized approver releases it.

The application package connects to Cosmos DB at import time, so the approval module is loaded
against lightweight dependency stubs. Wiring into the routes that own each authorization gate
is verified against the real source.
"""

import ast
import importlib.util
import os
import sys
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
TESTS_ROOT = os.path.dirname(os.path.abspath(__file__))
if TESTS_ROOT not in sys.path:
    sys.path.insert(0, TESTS_ROOT)

from test_support.versioning import assert_app_version_at_least


OWNER_USER_ID = 'owner-user-001'
PARTICIPANT_USER_ID = 'participant-user-002'
OUTSIDER_USER_ID = 'outsider-user-003'
GROUP_ADMIN_USER_ID = 'group-admin-004'
GROUP_DOC_MANAGER_USER_ID = 'group-docmgr-005'
COLLABORATION_CONVERSATION_ID = 'collaboration-conversation-001'
GROUP_ID = 'group-001'

GROUP_DOC = {
    'id': GROUP_ID,
    'owner': {'id': OWNER_USER_ID},
    'admins': [GROUP_ADMIN_USER_ID],
    'documentManagers': [GROUP_DOC_MANAGER_USER_ID],
    'users': [
        {'userId': PARTICIPANT_USER_ID},
        {'userId': GROUP_ADMIN_USER_ID},
        {'userId': GROUP_DOC_MANAGER_USER_ID},
        {'userId': OWNER_USER_ID},
    ],
}


def read_app_source(file_name):
    with open(os.path.join(APP_ROOT, file_name), 'r', encoding='utf-8') as source_file:
        return source_file.read()


def extract_function_source(source_text, function_name):
    parsed = ast.parse(source_text)
    for node in ast.walk(parsed):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source_text, node)
    raise AssertionError(f'Function {function_name} not found')


def _stub_get_user_role_in_group(group_doc, user_id):
    """Mirror functions_group.get_user_role_in_group without importing the Azure-backed module."""
    if not group_doc:
        return None
    if group_doc.get('owner', {}).get('id') == user_id:
        return 'Owner'
    if user_id in group_doc.get('admins', []):
        return 'Admin'
    if user_id in group_doc.get('documentManagers', []):
        return 'DocumentManager'
    for member in group_doc.get('users', []):
        if member.get('userId') == user_id:
            return 'User'
    return None


def load_approvals_module(settings=None):
    """Load functions_generated_file_approvals against dependency stubs."""
    resolved_settings = settings or {'require_shared_conversation_file_approval': True}

    config_stub = types.ModuleType('config')
    config_stub.cosmos_messages_container = None
    sys.modules['config'] = config_stub

    appinsights_stub = types.ModuleType('functions_appinsights')
    appinsights_stub.log_event = lambda *args, **kwargs: None
    sys.modules['functions_appinsights'] = appinsights_stub

    group_stub = types.ModuleType('functions_group')
    group_stub.find_group_by_id = lambda group_id: GROUP_DOC if group_id == GROUP_ID else None
    group_stub.get_user_role_in_group = _stub_get_user_role_in_group
    sys.modules['functions_group'] = group_stub

    settings_stub = types.ModuleType('functions_settings')
    settings_stub.get_settings = lambda: dict(resolved_settings)
    sys.modules['functions_settings'] = settings_stub

    module_path = os.path.join(APP_ROOT, 'functions_generated_file_approvals.py')
    spec = importlib.util.spec_from_file_location('functions_generated_file_approvals', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_participant_context(group_id=''):
    return {
        'is_owner': False,
        'user_id': PARTICIPANT_USER_ID,
        'owner_user_id': OWNER_USER_ID,
        'collaboration_conversation_id': COLLABORATION_CONVERSATION_ID,
        'group_id': group_id,
    }


def test_participation_context_allows_shared_conversation_participants():
    """Gate 1: participants resolve access through the linked shared conversation."""
    print('Testing shared conversation participation authorization...')
    source = read_app_source('functions_collaboration.py')
    function_source = extract_function_source(source, 'build_conversation_participation_context')

    assert 'assert_user_can_participate_in_collaboration_conversation' in function_source, (
        'Participants must be authorized against the linked collaboration conversation'
    )
    assert 'get_collaboration_conversation_for_source' in function_source, (
        'The helper must resolve the shared conversation from the source conversation'
    )
    assert "raise PermissionError('You can only access your own conversations')" in function_source, (
        'Unlinked personal conversations must stay owner-only'
    )
    assert "'is_owner': True" in function_source and "'is_owner': False" in function_source, (
        'The context must distinguish owners from participants for staging decisions'
    )

    print('Shared conversation participation authorization verified.')
    return True


def test_stream_authorization_no_longer_rejects_participants():
    """Gate 1 regression: chat_stream_api must not hard-compare conversation ownership."""
    print('Testing chat stream authorization source...')
    source = read_app_source('route_backend_chats.py')

    authorize_source = extract_function_source(source, '_authorize_personal_conversation_access')
    assert "conversation_item.get('user_id') != user_id" not in authorize_source, (
        'The owner-only equality check must no longer gate conversation access'
    )
    assert '_resolve_authorized_conversation_context' in authorize_source, (
        'Authorization must flow through the collaboration-aware resolver'
    )

    resolver_source = extract_function_source(source, '_resolve_authorized_conversation_context')
    assert 'build_conversation_participation_context' in resolver_source, (
        'The resolver must use the shared participation context'
    )
    assert 'from functions_collaboration import build_conversation_participation_context' in source, (
        'route_backend_chats must import the shared participation context helper'
    )

    print('Chat stream authorization verified.')
    return True


def test_only_gated_formats_require_approval():
    """Only downloadable deliverables are gated; images and charts stay ungated."""
    print('Testing approval format scope...')
    approvals = load_approvals_module()

    for gated_format in ('csv', 'xlsx', 'xls', 'xlsm', 'docx', 'pdf', 'json', 'xml'):
        assert approvals.is_approval_gated_file(f'report.{gated_format}'), (
            f'{gated_format} should require approval'
        )

    for ungated_format in ('png', 'jpg', 'gif', 'svg', 'webp', 'txt', 'md'):
        assert not approvals.is_approval_gated_file(f'chart.{ungated_format}'), (
            f'{ungated_format} should not require approval'
        )

    assert approvals.is_approval_gated_file('', output_format='csv'), (
        'An explicit output format should be honored when no file name is present'
    )

    print('Approval format scope verified.')
    return True


def test_owner_writes_are_never_gated():
    """Owners bypass the gate, participants are staged, and the admin setting disables it."""
    print('Testing owner bypass and setting toggle...')
    approvals = load_approvals_module()

    owner_context = {
        'is_owner': True,
        'owner_user_id': OWNER_USER_ID,
        'collaboration_conversation_id': COLLABORATION_CONVERSATION_ID,
        'group_id': '',
    }
    enabled_settings = {'require_shared_conversation_file_approval': True}
    disabled_settings = {'require_shared_conversation_file_approval': False}

    assert not approvals.requires_generated_file_approval(
        owner_context, file_name='report.csv', settings=enabled_settings,
    ), 'Owners must never be gated'

    assert approvals.requires_generated_file_approval(
        build_participant_context(), file_name='report.csv', settings=enabled_settings,
    ), 'Participants generating downloadable files must be gated'

    assert not approvals.requires_generated_file_approval(
        build_participant_context(), file_name='report.csv', settings=disabled_settings,
    ), 'Disabling the admin setting must restore direct behavior'

    assert not approvals.requires_generated_file_approval(
        build_participant_context(), file_name='diagram.png', settings=enabled_settings,
    ), 'Inline image artifacts must stay ungated'

    solo_context = {
        'is_owner': False,
        'owner_user_id': OWNER_USER_ID,
        'collaboration_conversation_id': '',
        'group_id': '',
    }
    assert not approvals.requires_generated_file_approval(
        solo_context, file_name='report.csv', settings=enabled_settings,
    ), 'Non-shared conversations must not create approvals'

    print('Owner bypass and setting toggle verified.')
    return True


def test_staged_artifact_is_not_downloadable_until_approved():
    """A staged artifact must be unreachable for every caller, including the requester."""
    print('Testing staged artifact download enforcement...')
    approvals = load_approvals_module()

    approval_metadata = approvals.build_generated_file_approval_metadata(
        build_participant_context(),
        requester={'user_id': PARTICIPANT_USER_ID, 'display_name': 'Participant'},
    )
    assert approval_metadata['generated_artifact_approval_state'] == approvals.APPROVAL_STATE_PENDING
    assert approval_metadata['generated_artifact_approval_expires_at'], 'Staged files must expire'
    assert approval_metadata['generated_artifact_approval_scope'] == approvals.APPROVAL_SCOPE_PERSONAL

    staged_message = {'id': 'artifact-1', 'metadata': dict(approval_metadata)}
    for caller_id in (PARTICIPANT_USER_ID, OWNER_USER_ID, OUTSIDER_USER_ID):
        try:
            approvals.assert_generated_file_approval_allows_download(caller_id, staged_message)
            raise AssertionError('Pending artifacts must never be downloadable')
        except PermissionError:
            pass

    denied_message = {'id': 'artifact-1', 'metadata': dict(approval_metadata)}
    denied_message['metadata']['generated_artifact_approval_state'] = approvals.APPROVAL_STATE_DENIED
    try:
        approvals.assert_generated_file_approval_allows_download(OWNER_USER_ID, denied_message)
        raise AssertionError('Denied artifacts must not be downloadable')
    except PermissionError:
        pass

    approved_message = {'id': 'artifact-1', 'metadata': dict(approval_metadata)}
    approved_message['metadata']['generated_artifact_approval_state'] = approvals.APPROVAL_STATE_APPROVED
    approvals.assert_generated_file_approval_allows_download(OWNER_USER_ID, approved_message)
    approvals.assert_generated_file_approval_allows_download(PARTICIPANT_USER_ID, approved_message)

    # Artifacts written by an owner carry no approval contract and stay downloadable.
    approvals.assert_generated_file_approval_allows_download(OWNER_USER_ID, {'id': 'a2', 'metadata': {}})

    print('Staged artifact download enforcement verified.')
    return True


def test_personal_and_group_approver_resolution():
    """Personal approvals route to the owner; group approvals route to document managers."""
    print('Testing approver resolution...')
    approvals = load_approvals_module()

    personal_message = {
        'id': 'artifact-1',
        'metadata': approvals.build_generated_file_approval_metadata(
            build_participant_context(),
            requester={'user_id': PARTICIPANT_USER_ID},
        ),
    }
    assert approvals.user_can_approve_generated_file(OWNER_USER_ID, personal_message)
    assert not approvals.user_can_approve_generated_file(PARTICIPANT_USER_ID, personal_message), (
        'A requester must not approve their own file'
    )
    assert not approvals.user_can_approve_generated_file(OUTSIDER_USER_ID, personal_message)

    group_metadata = approvals.build_generated_file_approval_metadata(
        build_participant_context(group_id=GROUP_ID),
        requester={'user_id': PARTICIPANT_USER_ID},
    )
    assert group_metadata['generated_artifact_approval_scope'] == approvals.APPROVAL_SCOPE_GROUP
    group_message = {'id': 'artifact-2', 'metadata': group_metadata}

    assert approvals.user_can_approve_generated_file(OWNER_USER_ID, group_message), 'Group owner approves'
    assert approvals.user_can_approve_generated_file(GROUP_ADMIN_USER_ID, group_message), 'Group admin approves'
    assert approvals.user_can_approve_generated_file(GROUP_DOC_MANAGER_USER_ID, group_message), (
        'Group document manager approves'
    )
    assert not approvals.user_can_approve_generated_file(PARTICIPANT_USER_ID, group_message), (
        'A plain group User must not approve their own file'
    )
    assert not approvals.user_can_approve_generated_file(OUTSIDER_USER_ID, group_message), (
        'Non-members must not approve'
    )

    print('Approver resolution verified.')
    return True


def test_requester_can_never_approve_their_own_file():
    """A requester is never their own approver, whatever group role they hold."""
    print('Testing requester self-approval guard...')
    approvals = load_approvals_module()

    # A group Admin or DocumentManager who is only a participant still gets staged, so the
    # requester check must win over their group role.
    for privileged_requester in (GROUP_ADMIN_USER_ID, GROUP_DOC_MANAGER_USER_ID, OWNER_USER_ID):
        metadata = approvals.build_generated_file_approval_metadata(
            {
                'is_owner': False,
                'user_id': privileged_requester,
                'owner_user_id': OWNER_USER_ID,
                'collaboration_conversation_id': COLLABORATION_CONVERSATION_ID,
                'group_id': GROUP_ID,
            },
            requester={'user_id': privileged_requester},
        )
        message_item = {'id': 'artifact-self', 'metadata': metadata}
        assert not approvals.user_can_approve_generated_file(privileged_requester, message_item), (
            f'{privileged_requester} must not approve a file they requested'
        )
        payload = approvals.build_generated_file_approval_client_payload(
            message_item, privileged_requester,
        )
        assert payload['viewer_can_approve'] is False, (
            'The requester must not be offered approve controls'
        )
        assert payload['viewer_is_requester'] is True

        # Another eligible approver must still be able to release it.
        assert approvals.user_can_approve_generated_file(
            GROUP_ADMIN_USER_ID if privileged_requester != GROUP_ADMIN_USER_ID else GROUP_DOC_MANAGER_USER_ID,
            message_item,
        ), 'A different eligible approver must still be able to release the file'

    # The same guard applies in a personal shared conversation.
    personal_metadata = approvals.build_generated_file_approval_metadata(
        {
            'is_owner': False,
            'user_id': OWNER_USER_ID,
            'owner_user_id': OWNER_USER_ID,
            'collaboration_conversation_id': COLLABORATION_CONVERSATION_ID,
            'group_id': '',
        },
        requester={'user_id': OWNER_USER_ID},
    )
    assert not approvals.user_can_approve_generated_file(
        OWNER_USER_ID, {'id': 'artifact-self-personal', 'metadata': personal_metadata},
    ), 'An owner-requester must not self-approve'

    print('Requester self-approval guard verified.')
    return True


def test_all_artifact_blob_readers_enforce_the_approval_gate():
    """Every route that streams a stored artifact blob must consult the approval gate."""
    print('Testing artifact blob reader coverage...')
    source = read_app_source('route_enhanced_citations.py')

    # The tabular citation route serves arbitrary blob-backed file messages from a conversation,
    # and the source conversation owner is not necessarily an approver in a group shared
    # conversation, so it must enforce the gate too.
    enforcement_count = source.count('assert_generated_file_approval_allows_download(user_id, ')
    assert enforcement_count >= 2, (
        'Both the generated-artifact reader and the tabular citation reader must enforce '
        f'the approval gate (found {enforcement_count})'
    )

    tabular_index = source.index('def get_enhanced_citation_tabular')
    tabular_source = source[tabular_index:source.index('@bp.route', tabular_index + 1)]
    assert 'assert_generated_file_approval_allows_download' in tabular_source, (
        'The tabular citation route must enforce the approval gate before streaming a blob'
    )
    assert 'except PermissionError' in tabular_source, (
        'The tabular citation route must return 403 rather than 500 for a withheld file'
    )
    gate_index = tabular_source.index('assert_generated_file_approval_allows_download')
    download_index = tabular_source.index('blob_client.download_blob()')
    assert gate_index < download_index, 'The gate must run before the blob is read'

    print('Artifact blob reader coverage verified.')
    return True


def test_pending_approval_listing_is_scoped_before_truncation():
    """The pending list must narrow to the caller's scopes before applying the row cap."""
    print('Testing pending approval listing scope...')
    source = read_app_source('functions_simplechat_operations.py')
    function_source = extract_function_source(source, 'list_pending_generated_file_approvals_for_user')

    assert 'generated_artifact_approval_owner_user_id = @user_id' in function_source, (
        'Personal-scope candidates must be filtered in the query'
    )
    assert 'generated_artifact_approval_group_id IN (' in function_source, (
        'Group-scope candidates must be filtered in the query'
    )
    assert 'generated_artifact_approval_requested_by_id != @user_id' in function_source, (
        'A requester must never appear in their own approval queue'
    )
    assert 'get_user_groups' in function_source, (
        'Group scope must come from the caller group membership'
    )

    scope_index = function_source.index('scope_clauses')
    query_index = function_source.index('"SELECT TOP @limit * FROM c "')
    assert scope_index < query_index, 'Scope filtering must be built before the capped query'

    # Authorization is still decided by the shared predicate, not by the query alone.
    assert 'user_can_approve_generated_file' in function_source, (
        'The shared authorization predicate must still gate every returned row'
    )

    print('Pending approval listing scope verified.')
    return True


def test_approval_decisions_are_recorded_and_single_use():
    """A decision must be recorded once and never re-applied."""
    print('Testing approval decision transitions...')
    approvals = load_approvals_module()

    message_item = {
        'id': 'artifact-1',
        'metadata': approvals.build_generated_file_approval_metadata(
            build_participant_context(),
            requester={'user_id': PARTICIPANT_USER_ID, 'display_name': 'Participant'},
        ),
    }

    pending_payload = approvals.build_generated_file_approval_client_payload(message_item, OWNER_USER_ID)
    assert pending_payload['is_pending'] is True
    assert pending_payload['viewer_can_approve'] is True, 'Owner should see approve controls'

    requester_payload = approvals.build_generated_file_approval_client_payload(
        message_item, PARTICIPANT_USER_ID,
    )
    assert requester_payload['viewer_can_approve'] is False
    assert requester_payload['viewer_is_requester'] is True

    updated = approvals.apply_generated_file_approval_decision(
        message_item,
        approvals.APPROVAL_STATE_APPROVED,
        resolver={'user_id': OWNER_USER_ID, 'display_name': 'Owner User'},
    )
    assert updated['metadata']['generated_artifact_approval_state'] == approvals.APPROVAL_STATE_APPROVED
    assert updated['metadata']['generated_artifact_approval_resolved_by_name'] == 'Owner User'
    assert updated['metadata']['generated_artifact_approval_resolved_at']

    try:
        approvals.apply_generated_file_approval_decision(
            updated,
            approvals.APPROVAL_STATE_APPROVED,
            resolver={'user_id': OWNER_USER_ID},
        )
        raise AssertionError('A resolved approval must not be re-applied')
    except ValueError:
        pass

    try:
        approvals.apply_generated_file_approval_decision(
            {'id': 'ungated', 'metadata': {}},
            approvals.APPROVAL_STATE_APPROVED,
        )
        raise AssertionError('Ungated artifacts must not accept approval decisions')
    except ValueError:
        pass

    print('Approval decision transitions verified.')
    return True


def test_download_route_enforces_approval_before_publication():
    """Gate 4: the download route checks approval independently of the export manifest."""
    print('Testing download route enforcement...')
    source = read_app_source('route_enhanced_citations.py')
    function_source = extract_function_source(source, '_get_authorized_chat_artifact_message')

    assert 'build_conversation_participation_context' in function_source, (
        'The download route must authorize shared conversation participants'
    )
    assert "raise PermissionError('Forbidden')" not in function_source, (
        'The owner-only equality check must no longer gate artifact downloads'
    )

    approval_index = function_source.index('assert_generated_file_approval_allows_download')
    publication_index = function_source.index('assert_generated_chat_artifact_is_published_for_user')
    assert approval_index < publication_index, (
        'Approval must be enforced before the export manifest short-circuit'
    )

    # The original bug was an unactionable bare "Forbidden"; the download route must surface
    # the specific reason so a pending file explains itself.
    assert 'return jsonify({"error": str(exc) or "Forbidden"}), 403' in source, (
        'The artifact download route must surface the specific permission message'
    )

    print('Download route enforcement verified.')
    return True


def test_artifact_upload_stages_participant_files():
    """Gate 2: participant artifact writes are staged rather than refused."""
    print('Testing artifact staging wiring...')
    source = read_app_source('functions_simplechat_operations.py')
    function_source = extract_function_source(source, '_upload_generated_chat_artifact_for_current_user')

    assert 'build_conversation_participation_context' in function_source, (
        'Artifact uploads must authorize through the shared participation context'
    )
    assert 'raise PermissionError("Forbidden")' not in function_source, (
        'Participant artifact writes must no longer fail with a bare Forbidden'
    )
    assert 'requires_generated_file_approval' in function_source, (
        'Artifact uploads must consult the approval decision'
    )
    assert '**approval_metadata' in function_source, (
        'Approval state must be persisted on the artifact message metadata'
    )
    assert '_notify_generated_file_approval_requested' in function_source, (
        'Approvers must be notified when a file is staged'
    )

    resolve_source = extract_function_source(source, 'resolve_generated_file_approval_for_user')
    assert 'user_can_approve_generated_file' in resolve_source, (
        'Approval resolution must re-authorize the acting user on every call'
    )
    assert 'delete_blob_backed_chat_message_files' in resolve_source, (
        'Denied files must have their stored blob removed'
    )

    print('Artifact staging wiring verified.')
    return True


def test_expired_staged_files_are_auto_denied():
    """Staged files that nobody approves expire and release their storage."""
    print('Testing auto-deny sweep wiring...')
    approvals_source = read_app_source('functions_generated_file_approvals.py')
    assert 'APPROVAL_TTL_DAYS = 3' in approvals_source, (
        'Staged files should expire on the same 3 day window as Control Center approvals'
    )

    operations_source = read_app_source('functions_simplechat_operations.py')
    sweep_source = extract_function_source(
        operations_source, 'auto_deny_expired_generated_file_approvals',
    )
    assert 'list_expired_pending_generated_file_artifacts' in sweep_source
    assert 'APPROVAL_STATE_AUTO_DENIED' in sweep_source
    assert 'delete_blob_backed_chat_message_files' in sweep_source, (
        'Expired staged files must not leak blob storage'
    )

    background_source = read_app_source('background_tasks.py')
    assert 'auto_deny_expired_generated_file_approvals' in background_source, (
        'The expiry sweep must be scheduled'
    )

    print('Auto-deny sweep wiring verified.')
    return True


def test_admin_setting_is_exposed_and_safe_to_share():
    """The admin toggle exists, defaults on, and survives settings sanitization."""
    print('Testing admin setting...')
    settings_source = read_app_source('functions_settings.py')
    assert "'require_shared_conversation_file_approval': True," in settings_source, (
        'The approval requirement must default to enabled'
    )

    admin_route_source = read_app_source('route_frontend_admin_settings.py')
    assert "'require_shared_conversation_file_approval': form_data.get(" in admin_route_source, (
        'The admin form must persist the approval toggle'
    )

    template_path = os.path.join(APP_ROOT, 'templates', 'admin_settings.html')
    with open(template_path, 'r', encoding='utf-8') as template_file:
        template_source = template_file.read()
    assert 'id="require_shared_conversation_file_approval"' in template_source, (
        'The admin settings page must expose the toggle'
    )

    # sanitize_settings_for_user drops keys containing these terms; the toggle must survive.
    sensitive_terms = ('key', 'secret', 'password', 'connection', 'base64', 'storage_account_url')
    setting_key = 'require_shared_conversation_file_approval'
    assert not any(term in setting_key for term in sensitive_terms), (
        'The toggle name must not collide with sanitization filters'
    )

    print('Admin setting verified.')
    return True


def test_frontend_approval_module_is_local_and_safe():
    """The approval UI is a local asset that renders untrusted values safely."""
    print('Testing frontend approval module...')
    module_path = os.path.join(APP_ROOT, 'static', 'js', 'chat', 'chat-file-approvals.js')
    assert os.path.exists(module_path), 'The approval UI module must be a local static asset'

    with open(module_path, 'r', encoding='utf-8') as module_file:
        module_source = module_file.read()

    assert module_source.startswith('// chat-file-approvals.js'), 'Missing filename comment'
    assert 'innerHTML' not in module_source, 'Approval UI must not use innerHTML'
    assert 'display:none' not in module_source and 'display: none' not in module_source, (
        'Use Bootstrap d-none instead of inline display styles'
    )
    assert 'alert(' not in module_source, 'Use Bootstrap alerts and toasts, not alert()'
    assert '//cdn' not in module_source and 'https://' not in module_source, (
        'Browser assets must not reference remote sources'
    )

    messages_path = os.path.join(APP_ROOT, 'static', 'js', 'chat', 'chat-messages.js')
    with open(messages_path, 'r', encoding='utf-8') as messages_file:
        messages_source = messages_file.read()
    assert 'buildGeneratedFileApprovalBlock' in messages_source, (
        'The artifact card must render the approval block'
    )
    assert 'generatedFileApprovalBlocksDownload' in messages_source, (
        'The artifact card must suppress downloads while a file is staged'
    )

    print('Frontend approval module verified.')
    return True


def test_version_supports_shared_conversation_file_approvals():
    """The fix must be present in at least its implementation version."""
    print('Testing application version...')
    assert_app_version_at_least(
        '0.260.004',
        reason='Shared conversation file approvals were implemented in 0.260.004',
    )
    print('Application version verified.')
    return True


if __name__ == '__main__':
    tests = [
        test_participation_context_allows_shared_conversation_participants,
        test_stream_authorization_no_longer_rejects_participants,
        test_only_gated_formats_require_approval,
        test_owner_writes_are_never_gated,
        test_staged_artifact_is_not_downloadable_until_approved,
        test_personal_and_group_approver_resolution,
        test_requester_can_never_approve_their_own_file,
        test_approval_decisions_are_recorded_and_single_use,
        test_download_route_enforces_approval_before_publication,
        test_all_artifact_blob_readers_enforce_the_approval_gate,
        test_pending_approval_listing_is_scoped_before_truncation,
        test_artifact_upload_stages_participant_files,
        test_expired_staged_files_are_auto_denied,
        test_admin_setting_is_exposed_and_safe_to_share,
        test_frontend_approval_module_is_local_and_safe,
        test_version_supports_shared_conversation_file_approvals,
    ]

    results = []
    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            results.append(bool(test()))
        except Exception as error:
            print(f'FAILED: {error}')
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if all(results) else 1)
