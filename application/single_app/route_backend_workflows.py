# route_backend_workflows.py

"""
Backend routes for personal and group workflows.
"""

import json
import logging
import time
from datetime import datetime, timezone

from flask import Response, jsonify, request, session, stream_with_context

from background_tasks import acquire_distributed_task_lock, release_distributed_task_lock
from config import CosmosResourceNotFoundError, cosmos_conversations_container
from functions_activity_logging import (
    log_workflow_creation,
    log_workflow_deletion,
    log_workflow_update,
)
from functions_appinsights import log_event
from functions_authentication import get_current_user_id, get_current_user_info, login_required, user_required
from functions_file_sync import (
    FILE_SYNC_MANAGER_ROLES,
    FILE_SYNC_SCOPE_GROUP,
    FILE_SYNC_SCOPE_PERSONAL,
    FILE_SYNC_SCOPE_PUBLIC,
    is_file_sync_enabled_for_group,
    is_file_sync_enabled_for_public_workspace,
    is_file_sync_enabled_for_user,
    list_file_sync_sources,
    sanitize_file_sync_source,
)
from functions_group import require_active_group
from functions_public_workspaces import require_active_public_workspace
from functions_document_actions import DOCUMENT_ACTION_TYPE_ANALYZE, build_analyze_config
from functions_thoughts import get_thoughts_for_message
from functions_workflow_activity import build_workflow_activity_snapshot
from functions_msgraph_pending_actions import list_msgraph_pending_actions, sanitize_msgraph_pending_action_for_client
from functions_personal_workflows import (
    compute_next_run_at,
    delete_personal_workflow,
    get_latest_personal_workflow_run_for_conversation,
    get_personal_workflow,
    get_personal_workflow_run,
    get_personal_workflows,
    list_personal_workflow_run_items,
    list_personal_workflow_runs,
    save_personal_workflow,
    update_personal_workflow_runtime_fields,
)
from functions_group import assert_group_role
from functions_group_workflows import (
    GROUP_WORKFLOW_MEMBER_ROLES,
    delete_group_workflow,
    get_group_workflow,
    get_group_workflow_agent_options,
    get_group_workflow_run,
    get_group_workflows,
    get_latest_group_workflow_run_for_conversation,
    list_group_workflow_run_items,
    list_group_workflow_runs,
    save_group_workflow,
    update_group_workflow_runtime_fields,
)
from functions_settings import (
    enabled_required,
    get_group_workflow_management_roles,
    get_settings,
    is_group_workflows_enabled_for_group,
    workflow_user_required,
)
from functions_source_review import (
    URL_ACCESS_CONTEXT_WORKFLOW,
    get_url_access_max_urls,
    has_url_access_app_role,
    is_url_access_enabled,
    is_url_access_enabled_for_user,
    validate_url_access_request,
)
from functions_workflow_runner import run_group_workflow, run_personal_workflow
from swagger_wrapper import swagger_route, get_auth_security


def _normalize_identifier(value):
    return str(value or '').strip()


def _normalize_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def _get_current_user_info_with_roles():
    user_info = get_current_user_info() or {}
    session_user = session.get('user') if isinstance(session.get('user'), dict) else {}
    if session_user.get('roles') and not user_info.get('roles'):
        user_info = dict(user_info)
        user_info['roles'] = session_user.get('roles')
    return user_info


def _assert_group_workflow_feature_enabled(group_id, settings=None):
    settings = settings or get_settings()
    if not settings.get('allow_group_workflows', False):
        raise ValueError('Group workflows are disabled.')
    if not is_group_workflows_enabled_for_group(settings, group_id):
        raise PermissionError('This group is not assigned to use workflows.')
    return settings


def _resolve_active_group_for_workflows(user_id, allowed_roles=GROUP_WORKFLOW_MEMBER_ROLES):
    group_id = require_active_group(user_id, allowed_roles=allowed_roles)
    settings = _assert_group_workflow_feature_enabled(group_id)
    return group_id, settings


def _resolve_group_workflow_request_group(user_id, allowed_roles=GROUP_WORKFLOW_MEMBER_ROLES):
    requested_group_id = _normalize_identifier(request.args.get('group_id') or request.args.get('groupId'))
    if requested_group_id:
        assert_group_role(user_id, requested_group_id, allowed_roles=allowed_roles)
        settings = _assert_group_workflow_feature_enabled(requested_group_id)
        return requested_group_id, settings
    return _resolve_active_group_for_workflows(user_id, allowed_roles=allowed_roles)


def _resolve_active_group_for_workflow_management(user_id):
    settings = get_settings()
    allowed_roles = get_group_workflow_management_roles(settings)
    group_id = require_active_group(user_id, allowed_roles=allowed_roles)
    _assert_group_workflow_feature_enabled(group_id, settings=settings)
    return group_id, settings


def _serialize_workflow_file_sync_source(scope_type, scope_id, source):
    sanitized_source = sanitize_file_sync_source(source)
    source_name = str(sanitized_source.get('name') or sanitized_source.get('id') or '').strip()
    scope_label = {
        FILE_SYNC_SCOPE_PERSONAL: 'Personal',
        FILE_SYNC_SCOPE_GROUP: 'Group',
        FILE_SYNC_SCOPE_PUBLIC: 'Public',
    }.get(scope_type, scope_type.title())
    return {
        'scope_type': scope_type,
        'scope_id': scope_id,
        'source_id': str(sanitized_source.get('id') or '').strip(),
        'name': source_name,
        'source_type': str(sanitized_source.get('source_type') or '').strip(),
        'enabled': sanitized_source.get('enabled') is not False,
        'label': f'{source_name} ({scope_label})' if source_name else scope_label,
    }


def _collect_workflow_file_sync_sources(user_id):
    settings = get_settings()
    user_info = _get_current_user_info_with_roles()
    sources = []

    if is_file_sync_enabled_for_user(settings, user_id, user_info.get('email'), user_info=user_info):
        sources.extend(
            _serialize_workflow_file_sync_source(FILE_SYNC_SCOPE_PERSONAL, user_id, source)
            for source in list_file_sync_sources(FILE_SYNC_SCOPE_PERSONAL, user_id)
        )

    try:
        group_id = require_active_group(user_id, allowed_roles=FILE_SYNC_MANAGER_ROLES)
        if is_file_sync_enabled_for_group(settings, group_id, user_info=user_info):
            sources.extend(
                _serialize_workflow_file_sync_source(FILE_SYNC_SCOPE_GROUP, group_id, source)
                for source in list_file_sync_sources(FILE_SYNC_SCOPE_GROUP, group_id)
            )
    except (LookupError, PermissionError, ValueError):
        pass

    try:
        public_workspace_id, _, _ = require_active_public_workspace(user_id, allowed_roles=FILE_SYNC_MANAGER_ROLES)
        if is_file_sync_enabled_for_public_workspace(settings, public_workspace_id, user_info=user_info):
            sources.extend(
                _serialize_workflow_file_sync_source(FILE_SYNC_SCOPE_PUBLIC, public_workspace_id, source)
                for source in list_file_sync_sources(FILE_SYNC_SCOPE_PUBLIC, public_workspace_id)
            )
    except (LookupError, PermissionError, ValueError):
        pass

    return [source for source in sources if source.get('source_id')]


def _collect_group_workflow_file_sync_sources(user_id, group_id, settings=None):
    settings = settings or get_settings()
    user_info = _get_current_user_info_with_roles()
    if not is_file_sync_enabled_for_group(settings, group_id, user_info=user_info):
        return []

    return [
        _serialize_workflow_file_sync_source(FILE_SYNC_SCOPE_GROUP, group_id, source)
        for source in list_file_sync_sources(FILE_SYNC_SCOPE_GROUP, group_id)
        if source.get('id')
    ]


def _build_resume_failed_workflow(workflow, failed_items):
    action_config = workflow.get('document_action') if isinstance(workflow.get('document_action'), dict) else {}
    if action_config.get('type') != DOCUMENT_ACTION_TYPE_ANALYZE:
        raise ValueError('Resume failed items currently supports Analyze workflows.')

    document_ids = []
    group_ids = []
    public_workspace_ids = []
    for item in failed_items:
        document_id = _normalize_identifier(item.get('document_id'))
        if document_id and document_id not in document_ids:
            document_ids.append(document_id)
        scope_type = _normalize_identifier(item.get('scope_type')).lower()
        scope_id = _normalize_identifier(item.get('scope_id'))
        if scope_type == FILE_SYNC_SCOPE_GROUP and scope_id and scope_id not in group_ids:
            group_ids.append(scope_id)
        elif scope_type == FILE_SYNC_SCOPE_PUBLIC and scope_id and scope_id not in public_workspace_ids:
            public_workspace_ids.append(scope_id)

    if not document_ids:
        raise ValueError('No failed document items are available to resume.')

    resume_workflow = dict(workflow)
    resume_action = dict(action_config)
    resume_action.update({
        'document_ids': document_ids,
        'doc_scope': 'all',
        'active_group_ids': group_ids or list(action_config.get('active_group_ids') or []),
        'active_public_workspace_id': public_workspace_ids or list(action_config.get('active_public_workspace_id') or []),
    })
    resume_workflow['document_action'] = resume_action
    resume_workflow['analyze'] = build_analyze_config(resume_action)
    resume_workflow['file_sync'] = {
        'enabled': False,
        'wait_mode': 'complete',
        'continue_mode': 'always',
        'use_changed_documents': False,
        'sources': [],
    }
    resume_workflow['task_prompt'] = (
        f"{workflow.get('task_prompt', '')}\n\n"
        f"Resume only the {len(document_ids)} document(s) that failed in the previous workflow run."
    ).strip()
    return resume_workflow


def _prepare_workflow_url_access_payload(payload, user_id):
    payload = payload if isinstance(payload, dict) else {}
    settings = get_settings()
    current_user_roles = (session.get('user') or {}).get('roles', [])
    url_access_requested = _normalize_bool(payload.get('url_access_enabled'))
    if not url_access_requested:
        payload['url_access_authorized'] = False
        payload['url_access_authorized_by'] = ''
        payload['url_access_authorized_at'] = ''
        return payload

    if not is_url_access_enabled_for_user(settings, user_roles=current_user_roles):
        if is_url_access_enabled(settings):
            raise PermissionError('URL Access requires the UrlAccessUser app role.')
        raise PermissionError('URL Access is disabled by an administrator.')

    validation_result = validate_url_access_request(
        payload.get('task_prompt', ''),
        settings,
        URL_ACCESS_CONTEXT_WORKFLOW,
        user_roles=current_user_roles,
    )
    if not validation_result.get('allowed'):
        limit = validation_result.get('limit') or get_url_access_max_urls(URL_ACCESS_CONTEXT_WORKFLOW, settings)
        if validation_result.get('reason') == 'url_count_exceeded':
            raise ValueError(f'URL Access workflows support up to {limit} URL(s) per run.')
        if validation_result.get('reason') == 'url_access_role_required':
            raise PermissionError('URL Access requires the UrlAccessUser app role.')
        raise PermissionError('URL Access is disabled by an administrator.')

    payload['url_access_authorized'] = has_url_access_app_role(current_user_roles)
    payload['url_access_authorized_by'] = user_id if payload['url_access_authorized'] else ''
    payload['url_access_authorized_at'] = datetime.now(timezone.utc).isoformat() if payload['url_access_authorized'] else ''
    return payload


def _load_workflow_conversation(user_id, conversation_id):
    if not conversation_id:
        return None

    try:
        conversation = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
    except CosmosResourceNotFoundError as exc:
        raise ValueError('Workflow conversation not found.') from exc

    if conversation.get('user_id') != user_id:
        raise PermissionError('Forbidden')
    if conversation.get('chat_type') != 'workflow':
        raise ValueError('Workflow activity is only available for workflow conversations.')
    return {key: value for key, value in conversation.items() if not str(key).startswith('_')}


def _load_group_workflow_conversation(group_id, conversation_id):
    if not conversation_id:
        return None

    try:
        conversation = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
    except CosmosResourceNotFoundError as exc:
        raise ValueError('Workflow conversation not found.') from exc

    if conversation.get('chat_type') != 'workflow':
        raise ValueError('Workflow activity is only available for workflow conversations.')
    if _normalize_identifier(conversation.get('group_id')) != _normalize_identifier(group_id):
        raise PermissionError('Forbidden')
    return {key: value for key, value in conversation.items() if not str(key).startswith('_')}


def _resolve_workflow_activity_context(user_id, conversation_id='', workflow_id='', run_id=''):
    workflow_id = _normalize_identifier(workflow_id)
    conversation_id = _normalize_identifier(conversation_id)
    run_id = _normalize_identifier(run_id)

    if not any([conversation_id, workflow_id, run_id]):
        raise ValueError('A workflow activity request needs a conversation, workflow, or run identifier.')

    workflow = get_personal_workflow(user_id, workflow_id) if workflow_id else None
    run_record = get_personal_workflow_run(user_id, run_id) if run_id else None

    if run_id and not run_record:
        raise ValueError('Workflow run not found.')

    if run_record and workflow_id and _normalize_identifier(run_record.get('workflow_id')) != workflow_id:
        raise ValueError('The requested run does not belong to this workflow.')

    if run_record and not workflow:
        workflow = get_personal_workflow(user_id, run_record.get('workflow_id'))

    if not conversation_id:
        conversation_id = _normalize_identifier((run_record or {}).get('conversation_id') or (workflow or {}).get('conversation_id'))

    conversation = _load_workflow_conversation(user_id, conversation_id) if conversation_id else None

    if conversation and workflow_id and _normalize_identifier(conversation.get('workflow_id')) not in {'', workflow_id}:
        raise ValueError('The requested conversation does not belong to this workflow.')

    if not workflow and conversation:
        workflow = get_personal_workflow(user_id, conversation.get('workflow_id'))

    if not run_record and conversation_id:
        run_record = get_latest_personal_workflow_run_for_conversation(
            user_id,
            conversation_id,
            workflow_id=_normalize_identifier((workflow or {}).get('id')) or workflow_id,
        )

    if run_record and conversation_id and _normalize_identifier(run_record.get('conversation_id')) not in {'', conversation_id}:
        raise ValueError('The requested run does not belong to this workflow conversation.')

    thoughts = []
    if run_record and conversation_id and _normalize_identifier(run_record.get('assistant_message_id')):
        thoughts = get_thoughts_for_message(
            conversation_id,
            run_record.get('assistant_message_id'),
            user_id,
        )

    pending_actions = []
    if run_record or conversation_id or workflow_id:
        raw_pending_actions = list_msgraph_pending_actions(
            user_id,
            conversation_id=conversation_id or _normalize_identifier((run_record or {}).get('conversation_id')),
            workflow_id=workflow_id or _normalize_identifier((workflow or {}).get('id')),
            run_id=_normalize_identifier((run_record or {}).get('id')),
            limit=100,
        )
        pending_actions = [sanitize_msgraph_pending_action_for_client(action) for action in raw_pending_actions]

    return build_workflow_activity_snapshot(
        run_record=run_record,
        workflow=workflow,
        conversation=conversation,
        thoughts=thoughts,
        pending_actions=pending_actions,
    )


def _resolve_group_workflow_activity_context(user_id, group_id, conversation_id='', workflow_id='', run_id=''):
    assert_group_role(user_id, group_id, allowed_roles=GROUP_WORKFLOW_MEMBER_ROLES)
    _assert_group_workflow_feature_enabled(group_id)

    workflow_id = _normalize_identifier(workflow_id)
    conversation_id = _normalize_identifier(conversation_id)
    run_id = _normalize_identifier(run_id)

    if not any([conversation_id, workflow_id, run_id]):
        raise ValueError('A workflow activity request needs a conversation, workflow, or run identifier.')

    workflow = get_group_workflow(group_id, workflow_id) if workflow_id else None
    run_record = get_group_workflow_run(group_id, run_id) if run_id else None

    if run_id and not run_record:
        raise ValueError('Workflow run not found.')

    if run_record and workflow_id and _normalize_identifier(run_record.get('workflow_id')) != workflow_id:
        raise ValueError('The requested run does not belong to this workflow.')

    if run_record and not workflow:
        workflow = get_group_workflow(group_id, run_record.get('workflow_id'))

    if not conversation_id:
        conversation_id = _normalize_identifier((run_record or {}).get('conversation_id') or (workflow or {}).get('conversation_id'))

    conversation = _load_group_workflow_conversation(group_id, conversation_id) if conversation_id else None

    if conversation and workflow_id and _normalize_identifier(conversation.get('workflow_id')) not in {'', workflow_id}:
        raise ValueError('The requested conversation does not belong to this workflow.')

    if not workflow and conversation:
        workflow = get_group_workflow(group_id, conversation.get('workflow_id'))

    if not run_record and conversation_id:
        run_record = get_latest_group_workflow_run_for_conversation(
            group_id,
            conversation_id,
            workflow_id=_normalize_identifier((workflow or {}).get('id')) or workflow_id,
        )

    if run_record and conversation_id and _normalize_identifier(run_record.get('conversation_id')) not in {'', conversation_id}:
        raise ValueError('The requested run does not belong to this workflow conversation.')

    run_owner_user_id = _normalize_identifier(
        (run_record or {}).get('user_id')
        or (workflow or {}).get('user_id')
        or user_id
    )

    thoughts = []
    if run_record and conversation_id and _normalize_identifier(run_record.get('assistant_message_id')):
        thoughts = get_thoughts_for_message(
            conversation_id,
            run_record.get('assistant_message_id'),
            run_owner_user_id,
        )

    pending_actions = []
    if run_record or conversation_id or workflow_id:
        raw_pending_actions = list_msgraph_pending_actions(
            run_owner_user_id,
            conversation_id=conversation_id or _normalize_identifier((run_record or {}).get('conversation_id')),
            workflow_id=workflow_id or _normalize_identifier((workflow or {}).get('id')),
            run_id=_normalize_identifier((run_record or {}).get('id')),
            limit=100,
        )
        pending_actions = [sanitize_msgraph_pending_action_for_client(action) for action in raw_pending_actions]

    return build_workflow_activity_snapshot(
        run_record=run_record,
        workflow=workflow,
        conversation=conversation,
        thoughts=thoughts,
        pending_actions=pending_actions,
    )


def _stream_workflow_activity(user_id, conversation_id='', workflow_id='', run_id=''):
    last_payload = None
    terminal_snapshots_seen = 0

    yield 'retry: 750\n\n'

    for _ in range(300):
        snapshot = _resolve_workflow_activity_context(
            user_id,
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            run_id=run_id,
        )
        payload = json.dumps(snapshot, default=str, sort_keys=True)

        if payload != last_payload:
            last_payload = payload
            yield f'data: {payload}\n\n'
        else:
            yield ': keep-alive\n\n'

        run_status = str(((snapshot.get('run') or {}).get('status') or '')).strip().lower()
        if run_status and run_status != 'running':
            terminal_snapshots_seen += 1
            if terminal_snapshots_seen >= 2:
                break
        else:
            terminal_snapshots_seen = 0

        time.sleep(0.5)


def _stream_group_workflow_activity(user_id, group_id, conversation_id='', workflow_id='', run_id=''):
    last_payload = None
    terminal_snapshots_seen = 0

    yield 'retry: 750\n\n'

    for _ in range(300):
        snapshot = _resolve_group_workflow_activity_context(
            user_id,
            group_id,
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            run_id=run_id,
        )
        payload = json.dumps(snapshot, default=str, sort_keys=True)

        if payload != last_payload:
            last_payload = payload
            yield f'data: {payload}\n\n'
        else:
            yield ': keep-alive\n\n'

        run_status = str(((snapshot.get('run') or {}).get('status') or '')).strip().lower()
        if run_status and run_status != 'running':
            terminal_snapshots_seen += 1
            if terminal_snapshots_seen >= 2:
                break
        else:
            terminal_snapshots_seen = 0

        time.sleep(0.5)


def register_route_backend_workflows(app):
    @app.route('/api/user/workflows', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def get_user_workflows():
        user_id = get_current_user_id()
        return jsonify({'workflows': get_personal_workflows(user_id)})


    @app.route('/api/user/workflows/file-sync-sources', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def get_user_workflow_file_sync_sources():
        user_id = get_current_user_id()
        try:
            return jsonify({'sources': _collect_workflow_file_sync_sources(user_id)})
        except Exception as exc:
            log_event(
                f'[WorkflowRoutes] Failed to load workflow File Sync sources: {exc}',
                extra={'user_id': user_id},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Unable to load File Sync sources right now.'}), 500


    @app.route('/api/user/workflows', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def save_user_workflow():
        user_id = get_current_user_id()
        payload = request.get_json(silent=True) or {}
        is_create = not str(payload.get('id') or '').strip()

        try:
            payload = _prepare_workflow_url_access_payload(payload, user_id)
            workflow = save_personal_workflow(user_id, payload, actor_user_id=user_id)
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            log_event(
                f'[WorkflowRoutes] Failed to save workflow: {exc}',
                extra={'user_id': user_id},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Unable to save workflow right now.'}), 500

        if is_create:
            log_workflow_creation(
                user_id=user_id,
                workflow_id=workflow.get('id', ''),
                workflow_name=workflow.get('name', ''),
                runner_type=workflow.get('runner_type'),
                trigger_type=workflow.get('trigger_type'),
            )
        else:
            log_workflow_update(
                user_id=user_id,
                workflow_id=workflow.get('id', ''),
                workflow_name=workflow.get('name', ''),
                runner_type=workflow.get('runner_type'),
                trigger_type=workflow.get('trigger_type'),
            )

        return jsonify({'success': True, 'workflow': workflow}), 201 if is_create else 200


    @app.route('/api/user/workflows/<workflow_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def delete_user_workflow(workflow_id):
        user_id = get_current_user_id()
        workflow = get_personal_workflow(user_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        deleted = delete_personal_workflow(user_id, workflow_id)
        if not deleted:
            return jsonify({'error': 'Workflow not found.'}), 404

        log_workflow_deletion(
            user_id=user_id,
            workflow_id=workflow_id,
            workflow_name=workflow.get('name', ''),
        )
        return jsonify({'success': True})


    @app.route('/api/user/workflows/<workflow_id>/runs', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def get_user_workflow_runs(workflow_id):
        user_id = get_current_user_id()
        workflow = get_personal_workflow(user_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        return jsonify({
            'workflow_id': workflow_id,
            'runs': list_personal_workflow_runs(user_id, workflow_id, limit=50),
        })


    @app.route('/api/user/workflows/<workflow_id>/runs/<run_id>/items', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def get_user_workflow_run_items(workflow_id, run_id):
        user_id = get_current_user_id()
        workflow = get_personal_workflow(user_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        run_record = get_personal_workflow_run(user_id, run_id)
        if not run_record or _normalize_identifier(run_record.get('workflow_id')) != _normalize_identifier(workflow_id):
            return jsonify({'error': 'Workflow run not found.'}), 404

        return jsonify({
            'workflow_id': workflow_id,
            'run_id': run_id,
            'items': list_personal_workflow_run_items(run_id, limit=1000),
        })


    @app.route('/api/user/workflows/<workflow_id>/runs/<run_id>/resume-failed', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def resume_failed_user_workflow_items(workflow_id, run_id):
        user_id = get_current_user_id()
        workflow = get_personal_workflow(user_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        source_run = get_personal_workflow_run(user_id, run_id)
        if not source_run or _normalize_identifier(source_run.get('workflow_id')) != _normalize_identifier(workflow_id):
            return jsonify({'error': 'Workflow run not found.'}), 404

        failed_items = [
            item for item in list_personal_workflow_run_items(run_id, limit=1000)
            if _normalize_identifier(item.get('status')).lower() == 'failed' and _normalize_identifier(item.get('document_id'))
        ]
        if not failed_items:
            return jsonify({'error': 'No failed workflow items are available to resume.'}), 400

        try:
            resume_workflow = _build_resume_failed_workflow(workflow, failed_items)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

        lock_document = acquire_distributed_task_lock(f'workflow_run_{workflow_id}', lease_seconds=900)
        if not lock_document:
            return jsonify({'error': 'This workflow is already running.'}), 409

        try:
            started_at = datetime.now(timezone.utc).isoformat()
            update_personal_workflow_runtime_fields(
                user_id,
                workflow_id,
                {
                    'status': 'running',
                    'last_run_started_at': started_at,
                    'last_run_trigger_source': 'resume_failed',
                    'last_run_error': '',
                },
            )

            result = run_personal_workflow(
                resume_workflow,
                trigger_source='resume_failed',
                user_roles=(session.get('user') or {}).get('roles', []),
            )
            update_fields = dict(result.get('workflow_updates') or {})
            update_fields['status'] = 'idle'
            if workflow.get('trigger_type') in {'interval', 'file_sync'} and workflow.get('is_enabled', False) and not workflow.get('next_run_at'):
                update_fields['next_run_at'] = compute_next_run_at(workflow, from_time=datetime.now(timezone.utc))

            updated_workflow = update_personal_workflow_runtime_fields(user_id, workflow_id, update_fields)
            response_body = {
                'success': bool(result.get('success')),
                'workflow': updated_workflow,
                'run': result.get('run'),
                'resumed_item_count': len(failed_items),
            }
            if result.get('success'):
                return jsonify(response_body)
            return jsonify(response_body), 500
        finally:
            release_distributed_task_lock(lock_document)


    @app.route('/api/group/workflows', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def get_group_workflows_route():
        user_id = get_current_user_id()
        try:
            group_id, _ = _resolve_group_workflow_request_group(user_id)
            return jsonify({'workflows': get_group_workflows(group_id)})
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403


    @app.route('/api/group/workflows/file-sync-sources', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def get_group_workflow_file_sync_sources():
        user_id = get_current_user_id()
        try:
            group_id = require_active_group(user_id, allowed_roles=FILE_SYNC_MANAGER_ROLES)
            settings = _assert_group_workflow_feature_enabled(group_id)
            return jsonify({'sources': _collect_group_workflow_file_sync_sources(user_id, group_id, settings=settings)})
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[WorkflowRoutes] Failed to load group workflow File Sync sources: {exc}',
                extra={'user_id': user_id},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Unable to load File Sync sources right now.'}), 500


    @app.route('/api/group/workflows/agents', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def get_group_workflow_agent_options_route():
        user_id = get_current_user_id()
        try:
            group_id, settings = _resolve_active_group_for_workflows(user_id)
            return jsonify({'agents': get_group_workflow_agent_options(group_id, settings=settings)})
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[WorkflowRoutes] Failed to load group workflow agents: {exc}',
                extra={'user_id': user_id},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Unable to load group workflow agents right now.'}), 500


    @app.route('/api/group/workflows', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def save_group_workflow_route():
        user_id = get_current_user_id()
        payload = request.get_json(silent=True) or {}
        is_create = not str(payload.get('id') or '').strip()

        try:
            group_id, _ = _resolve_active_group_for_workflow_management(user_id)
            payload = _prepare_workflow_url_access_payload(payload, user_id)
            workflow = save_group_workflow(
                group_id,
                payload,
                actor_user_id=user_id,
                user_info=_get_current_user_info_with_roles(),
            )
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[WorkflowRoutes] Failed to save group workflow: {exc}',
                extra={'user_id': user_id},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Unable to save workflow right now.'}), 500

        if is_create:
            log_workflow_creation(
                user_id=user_id,
                workflow_id=workflow.get('id', ''),
                workflow_name=workflow.get('name', ''),
                runner_type=workflow.get('runner_type'),
                trigger_type=workflow.get('trigger_type'),
                workspace_type='group',
                group_id=group_id,
            )
        else:
            log_workflow_update(
                user_id=user_id,
                workflow_id=workflow.get('id', ''),
                workflow_name=workflow.get('name', ''),
                runner_type=workflow.get('runner_type'),
                trigger_type=workflow.get('trigger_type'),
                workspace_type='group',
                group_id=group_id,
            )

        return jsonify({'success': True, 'workflow': workflow}), 201 if is_create else 200


    @app.route('/api/group/workflows/<workflow_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def delete_group_workflow_route(workflow_id):
        user_id = get_current_user_id()
        try:
            group_id, _ = _resolve_active_group_for_workflow_management(user_id)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403

        workflow = get_group_workflow(group_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        deleted = delete_group_workflow(group_id, workflow_id)
        if not deleted:
            return jsonify({'error': 'Workflow not found.'}), 404

        log_workflow_deletion(
            user_id=user_id,
            workflow_id=workflow_id,
            workflow_name=workflow.get('name', ''),
            workspace_type='group',
            group_id=group_id,
        )
        return jsonify({'success': True})


    @app.route('/api/group/workflows/<workflow_id>/runs', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def get_group_workflow_runs_route(workflow_id):
        user_id = get_current_user_id()
        try:
            group_id, _ = _resolve_group_workflow_request_group(user_id)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403

        workflow = get_group_workflow(group_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        return jsonify({
            'workflow_id': workflow_id,
            'runs': list_group_workflow_runs(group_id, workflow_id, limit=50),
        })


    @app.route('/api/group/workflows/<workflow_id>/runs/<run_id>/items', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def get_group_workflow_run_items_route(workflow_id, run_id):
        user_id = get_current_user_id()
        try:
            group_id, _ = _resolve_active_group_for_workflows(user_id)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403

        workflow = get_group_workflow(group_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        run_record = get_group_workflow_run(group_id, run_id)
        if not run_record or _normalize_identifier(run_record.get('workflow_id')) != _normalize_identifier(workflow_id):
            return jsonify({'error': 'Workflow run not found.'}), 404

        return jsonify({
            'workflow_id': workflow_id,
            'run_id': run_id,
            'items': list_group_workflow_run_items(run_id, limit=1000),
        })


    @app.route('/api/group/workflows/<workflow_id>/runs/<run_id>/resume-failed', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def resume_failed_group_workflow_items(workflow_id, run_id):
        user_id = get_current_user_id()
        try:
            group_id, _ = _resolve_active_group_for_workflows(user_id)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403

        workflow = get_group_workflow(group_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        source_run = get_group_workflow_run(group_id, run_id)
        if not source_run or _normalize_identifier(source_run.get('workflow_id')) != _normalize_identifier(workflow_id):
            return jsonify({'error': 'Workflow run not found.'}), 404

        failed_items = [
            item for item in list_group_workflow_run_items(run_id, limit=1000)
            if _normalize_identifier(item.get('status')).lower() == 'failed' and _normalize_identifier(item.get('document_id'))
        ]
        if not failed_items:
            return jsonify({'error': 'No failed workflow items are available to resume.'}), 400

        try:
            resume_workflow = _build_resume_failed_workflow(workflow, failed_items)
            resume_action = resume_workflow.get('document_action') if isinstance(resume_workflow.get('document_action'), dict) else {}
            if resume_action:
                resume_action['doc_scope'] = 'group'
                resume_action['active_group_ids'] = [group_id]
                resume_action['active_public_workspace_id'] = []
                resume_workflow['document_action'] = resume_action
                resume_workflow['analyze'] = build_analyze_config(resume_action)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

        lock_document = acquire_distributed_task_lock(f'group_workflow_run_{group_id}_{workflow_id}', lease_seconds=900)
        if not lock_document:
            return jsonify({'error': 'This workflow is already running.'}), 409

        try:
            started_at = datetime.now(timezone.utc).isoformat()
            update_group_workflow_runtime_fields(
                group_id,
                workflow_id,
                {
                    'status': 'running',
                    'last_run_started_at': started_at,
                    'last_run_trigger_source': 'resume_failed',
                    'last_run_error': '',
                },
            )

            result = run_group_workflow(
                resume_workflow,
                trigger_source='resume_failed',
                user_roles=(session.get('user') or {}).get('roles', []),
                actor_user_id=user_id,
            )
            update_fields = dict(result.get('workflow_updates') or {})
            update_fields['status'] = 'idle'
            if workflow.get('trigger_type') in {'interval', 'file_sync'} and workflow.get('is_enabled', False) and not workflow.get('next_run_at'):
                update_fields['next_run_at'] = compute_next_run_at(workflow, from_time=datetime.now(timezone.utc))

            updated_workflow = update_group_workflow_runtime_fields(group_id, workflow_id, update_fields)
            response_body = {
                'success': bool(result.get('success')),
                'workflow': updated_workflow,
                'run': result.get('run'),
                'resumed_item_count': len(failed_items),
            }
            if result.get('success'):
                return jsonify(response_body)
            return jsonify(response_body), 500
        finally:
            release_distributed_task_lock(lock_document)


    @app.route('/api/group/workflows/activity', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def get_group_workflow_activity_snapshot():
        user_id = get_current_user_id()
        conversation_id = request.args.get('conversation_id', '')
        workflow_id = request.args.get('workflow_id', '')
        run_id = request.args.get('run_id', '')

        try:
            group_id, _ = _resolve_group_workflow_request_group(user_id)
            snapshot = _resolve_group_workflow_activity_context(
                user_id,
                group_id,
                conversation_id=conversation_id,
                workflow_id=workflow_id,
                run_id=run_id,
            )
            return jsonify(snapshot)
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            log_event(
                f'[WorkflowRoutes] Failed to load group workflow activity snapshot: {exc}',
                extra={
                    'user_id': user_id,
                    'conversation_id': conversation_id,
                    'workflow_id': workflow_id,
                    'run_id': run_id,
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Unable to load workflow activity right now.'}), 500


    @app.route('/api/group/workflows/activity/stream', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def stream_group_workflow_activity():
        user_id = get_current_user_id()
        conversation_id = request.args.get('conversation_id', '')
        workflow_id = request.args.get('workflow_id', '')
        run_id = request.args.get('run_id', '')

        try:
            group_id, _ = _resolve_group_workflow_request_group(user_id)
            _resolve_group_workflow_activity_context(
                user_id,
                group_id,
                conversation_id=conversation_id,
                workflow_id=workflow_id,
                run_id=run_id,
            )
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            log_event(
                f'[WorkflowRoutes] Failed to initialize group workflow activity stream: {exc}',
                extra={
                    'user_id': user_id,
                    'conversation_id': conversation_id,
                    'workflow_id': workflow_id,
                    'run_id': run_id,
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Unable to open workflow activity stream right now.'}), 500

        return Response(
            stream_with_context(
                _stream_group_workflow_activity(
                    user_id,
                    group_id,
                    conversation_id=conversation_id,
                    workflow_id=workflow_id,
                    run_id=run_id,
                )
            ),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
            },
        )


    @app.route('/api/group/workflows/<workflow_id>/run', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def run_group_workflow_route(workflow_id):
        user_id = get_current_user_id()
        try:
            group_id, _ = _resolve_active_group_for_workflows(user_id)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403

        workflow = get_group_workflow(group_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        lock_document = acquire_distributed_task_lock(f'group_workflow_run_{group_id}_{workflow_id}', lease_seconds=900)
        if not lock_document:
            return jsonify({'error': 'This workflow is already running.'}), 409

        try:
            started_at = datetime.now(timezone.utc).isoformat()
            update_group_workflow_runtime_fields(
                group_id,
                workflow_id,
                {
                    'status': 'running',
                    'last_run_started_at': started_at,
                    'last_run_trigger_source': 'manual',
                    'last_run_error': '',
                },
            )

            result = run_group_workflow(
                workflow,
                trigger_source='manual',
                user_roles=(session.get('user') or {}).get('roles', []),
                actor_user_id=user_id,
            )
            update_fields = dict(result.get('workflow_updates') or {})
            update_fields['status'] = 'idle'
            if workflow.get('trigger_type') in {'interval', 'file_sync'} and workflow.get('is_enabled', False) and not workflow.get('next_run_at'):
                update_fields['next_run_at'] = compute_next_run_at(workflow, from_time=datetime.now(timezone.utc))

            updated_workflow = update_group_workflow_runtime_fields(group_id, workflow_id, update_fields)
            response_body = {
                'success': bool(result.get('success')),
                'workflow': updated_workflow,
                'run': result.get('run'),
            }
            if result.get('success'):
                return jsonify(response_body)
            return jsonify(response_body), 500
        finally:
            release_distributed_task_lock(lock_document)


    @app.route('/api/user/workflows/activity', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def get_user_workflow_activity_snapshot():
        user_id = get_current_user_id()
        conversation_id = request.args.get('conversation_id', '')
        workflow_id = request.args.get('workflow_id', '')
        run_id = request.args.get('run_id', '')

        try:
            snapshot = _resolve_workflow_activity_context(
                user_id,
                conversation_id=conversation_id,
                workflow_id=workflow_id,
                run_id=run_id,
            )
            return jsonify(snapshot)
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            log_event(
                f'[WorkflowRoutes] Failed to load workflow activity snapshot: {exc}',
                extra={
                    'user_id': user_id,
                    'conversation_id': conversation_id,
                    'workflow_id': workflow_id,
                    'run_id': run_id,
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Unable to load workflow activity right now.'}), 500


    @app.route('/api/user/workflows/activity/stream', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def stream_user_workflow_activity():
        user_id = get_current_user_id()
        conversation_id = request.args.get('conversation_id', '')
        workflow_id = request.args.get('workflow_id', '')
        run_id = request.args.get('run_id', '')

        try:
            _resolve_workflow_activity_context(
                user_id,
                conversation_id=conversation_id,
                workflow_id=workflow_id,
                run_id=run_id,
            )
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            log_event(
                f'[WorkflowRoutes] Failed to initialize workflow activity stream: {exc}',
                extra={
                    'user_id': user_id,
                    'conversation_id': conversation_id,
                    'workflow_id': workflow_id,
                    'run_id': run_id,
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Unable to open workflow activity stream right now.'}), 500

        return Response(
            stream_with_context(
                _stream_workflow_activity(
                    user_id,
                    conversation_id=conversation_id,
                    workflow_id=workflow_id,
                    run_id=run_id,
                )
            ),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
            },
        )


    @app.route('/api/user/workflows/<workflow_id>/run', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def run_user_workflow(workflow_id):
        user_id = get_current_user_id()
        workflow = get_personal_workflow(user_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        lock_document = acquire_distributed_task_lock(f'workflow_run_{workflow_id}', lease_seconds=900)
        if not lock_document:
            return jsonify({'error': 'This workflow is already running.'}), 409

        try:
            started_at = datetime.now(timezone.utc).isoformat()
            update_personal_workflow_runtime_fields(
                user_id,
                workflow_id,
                {
                    'status': 'running',
                    'last_run_started_at': started_at,
                    'last_run_trigger_source': 'manual',
                    'last_run_error': '',
                },
            )

            result = run_personal_workflow(
                workflow,
                trigger_source='manual',
                user_roles=(session.get('user') or {}).get('roles', []),
            )
            update_fields = dict(result.get('workflow_updates') or {})
            update_fields['status'] = 'idle'
            if workflow.get('trigger_type') in {'interval', 'file_sync'} and workflow.get('is_enabled', False) and not workflow.get('next_run_at'):
                update_fields['next_run_at'] = compute_next_run_at(workflow, from_time=datetime.now(timezone.utc))

            updated_workflow = update_personal_workflow_runtime_fields(user_id, workflow_id, update_fields)
            response_body = {
                'success': bool(result.get('success')),
                'workflow': updated_workflow,
                'run': result.get('run'),
            }
            if result.get('success'):
                return jsonify(response_body)
            return jsonify(response_body), 500
        finally:
            release_distributed_task_lock(lock_document)