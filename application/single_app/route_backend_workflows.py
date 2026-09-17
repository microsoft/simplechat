# route_backend_workflows.py

"""
Backend routes for personal and group workflows.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone

from flask import Response, jsonify, request, session, stream_with_context
from azure.core.exceptions import AzureError

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
from functions_group import find_group_by_id, require_active_group
from functions_public_workspaces import require_active_public_workspace
from functions_document_actions import DOCUMENT_ACTION_TYPE_ANALYZE, DOCUMENT_ACTION_TYPE_NONE, build_analyze_config
from functions_thoughts import get_thoughts_for_message
from functions_workflow_activity import build_workflow_activity_snapshot
from functions_msgraph_pending_actions import list_msgraph_pending_actions, sanitize_msgraph_pending_action_for_client
from functions_m365_workflow_binding import (
    M365_ACTIVE_STATES,
    workflow_result_is_waiting,
    workflow_result_runtime_status,
)
from functions_m365_runtime import cancel_m365_workflow_requests
from functions_personal_workflows import (
    compute_next_run_at,
    delete_personal_workflow,
    get_latest_personal_workflow_run_for_conversation,
    get_personal_workflow,
    get_personal_workflow_run,
    get_personal_workflow_run_item,
    get_personal_workflows,
    list_personal_workflow_run_items,
    list_personal_workflow_runs,
    save_personal_workflow,
    save_personal_workflow_run,
    update_personal_workflow_runtime_fields,
)
from functions_group import assert_group_role
from functions_group_workflows import (
    GROUP_WORKFLOW_MEMBER_ROLES,
    delete_group_workflow,
    get_group_workflow,
    get_group_workflow_agent_options,
    get_group_workflow_run,
    get_group_workflow_run_item,
    get_group_workflows,
    get_latest_group_workflow_run_for_conversation,
    list_group_workflow_run_items,
    list_group_workflow_runs,
    save_group_workflow,
    save_group_workflow_run,
    update_group_workflow_runtime_fields,
)
from functions_settings import (
    enabled_required,
    get_group_workflow_management_roles,
    get_settings,
    is_user_workflows_enabled_for_user,
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
from functions_workflow_runner import _workflow_task_run_item_id, create_workflow_run_id, run_group_workflow, run_personal_workflow
from functions_workflow_result_store import WorkflowResultStorageUnavailableError, read_workflow_task_result_page
from functions_workflow_definitions import WorkflowDefinitionConflict, WorkflowDefinitionError
from functions_workflow_editor import get_workflow_editor_options
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_results import authorize_workflow_run_read, authorize_workflow_task_result_read
from functions_saved_analysis import sanitize_workflow_analysis_history
from functions_workflow_runtime import (
    cancel_durable_workflow_run,
    decide_workflow_runtime,
    queue_durable_workflow_run,
    workflow_runtime_status,
)
from functions_workflow_runtime_store import RuntimeUnavailable, WorkflowRuntimeConflict
from functions_workflow_execution_history import workflow_execution_history, workflow_execution_result_page
from route_backend_agents import (
    _build_agent_instruction_api_params,
    _create_agent_instruction_client,
    _resolve_agent_instruction_model,
)
from swagger_wrapper import swagger_route, get_auth_security


WORKFLOW_INSTRUCTION_FIELD_LIMIT = 6000


class WorkflowCancellationConflictError(RuntimeError):
    """Raised when a workflow run cannot transition into cancellation."""


def _normalize_identifier(value):
    return str(value or '').strip()


def _normalize_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def _workflow_definition_response(workflow, reader_user_id):
    """Keep definitions editable without exposing an inaccessible run's cached text."""
    if not workflow.get('last_run_response_preview') and not workflow.get('last_run_error'):
        return workflow
    access = 'available'
    run_id = workflow.get('last_run_id')
    if not run_id:
        access = 'legacy_preview_unbound'
    else:
        try:
            authorize_workflow_run_read(workflow, run_id, reader_user_id=reader_user_id)
        except AnalysisResultUnavailable:
            access = 'source_unavailable'
    if access == 'available':
        return workflow
    return {
        **workflow,
        'last_run_response_preview': '',
        'last_run_error': '',
        'result_access': access,
    }


def _workflow_task_result_page_response(workflow, run_record, task_id, get_item):
    if (run_record or {}).get('definition_version') == 3 or ((run_record or {}).get('runtime') or {}).get('schema_version') == 2:
        return jsonify({'error': 'Select an exact execution and attempt for this structured run.'}), 409
    run_id = _normalize_identifier((run_record or {}).get('id'))
    workflow_id = _normalize_identifier((workflow or {}).get('id'))
    if not workflow_id or not run_id or _normalize_identifier(run_record.get('workflow_id')) != workflow_id:
        return jsonify({'error': 'Workflow run not found.'}), 404
    item = get_item(run_id, _workflow_task_run_item_id(run_id, task_id))
    if not item or any((
        _normalize_identifier(item.get('workflow_id')) != workflow_id,
        _normalize_identifier(item.get('run_id')) != run_id,
        _normalize_identifier(item.get('task_id')) != _normalize_identifier(task_id),
    )):
        return jsonify({'error': 'Workflow task result not found.'}), 404
    summary = item.get('workflow_result') or {}
    if summary.get('contract_version') == 'workflow-result-v2':
        return jsonify({'error': 'Select an exact execution and attempt for this structured run.'}), 409
    result_ref = summary.get('result_ref')
    if not isinstance(result_ref, dict):
        return jsonify({'error': 'This task has no durable result. Older runs contain previews only.'}), 409
    output_name = _normalize_identifier(request.args.get('output') or 'manifest')
    try:
        offset = int(request.args.get('offset', '0'))
        limit = int(request.args.get('limit', '65536'))
    except ValueError:
        return jsonify({'error': 'Result page offset and limit must be integers.'}), 400
    if offset < 0 or not 1 <= limit <= 65536:
        return jsonify({'error': 'Invalid result page range.'}), 400
    try:
        manifest, _ = authorize_workflow_task_result_read(
            workflow, run_id, task_id, result_ref, reader_user_id=get_current_user_id(),
        )
        if output_name == 'authoritative':
            output_name = manifest.get('authoritative_output')
        if output_name != 'manifest':
            output = (manifest.get('outputs') or {}).get(output_name)
            if not isinstance(output, dict) or not isinstance(output.get('result_ref'), dict):
                return jsonify({'error': 'The requested task output is not available.'}), 404
            result_ref = output['result_ref']
        page = read_workflow_task_result_page(
            workflow, run_id, task_id, result_ref, offset=offset, limit=limit,
        )
        return jsonify({**page, 'output_name': output_name})
    except PermissionError:
        return jsonify({'error': 'Access to this task result is not allowed.'}), 403
    except LookupError:
        return jsonify({'error': 'The saved task result is unavailable.'}), 404
    except ValueError:
        return jsonify({'error': 'The saved result or requested page is unavailable.'}), 409
    except WorkflowResultStorageUnavailableError:
        return jsonify({'error': 'The storage for this task result is not available.'}), 503
    except AzureError as exc:
        log_event(
            '[WORKFLOW_STORE] Task result read failed',
            extra={'workflow_id': workflow_id, 'run_id': run_id, 'error_type': type(exc).__name__},
            level=logging.ERROR,
        )
        return jsonify({'error': 'Unable to read the saved task result.'}), 503


def _request_workflow_run_cancellation(
    workflow,
    run_id,
    requested_by,
    get_run,
    save_run,
    update_runtime_fields,
):
    workflow = workflow if isinstance(workflow, dict) else {}
    workflow_id = _normalize_identifier(workflow.get('id'))
    active_run_id = _normalize_identifier(workflow.get('active_run_id'))
    target_run_id = _normalize_identifier(run_id) or active_run_id
    if not target_run_id:
        raise WorkflowCancellationConflictError('No active workflow run is available to cancel.')
    if active_run_id and active_run_id != target_run_id:
        raise WorkflowCancellationConflictError('A different workflow run is currently active.')

    run_record = get_run(target_run_id)
    if run_record and _normalize_identifier(run_record.get('workflow_id')) != workflow_id:
        raise LookupError('Workflow run not found.')
    if not run_record and target_run_id != active_run_id:
        raise LookupError('Workflow run not found.')
    if run_record and run_record.get('durable_execution') is True:
        cancelled = cancel_durable_workflow_run(workflow, target_run_id, actor_user_id=requested_by)
        safe_run = {key: cancelled['run'].get(key) for key in ('id', 'workflow_id', 'status', 'durable_execution', 'runtime')}
        return _workflow_definition_response(cancelled['workflow'], requested_by), safe_run

    run_status = _normalize_identifier((run_record or {}).get('status')).lower()
    if run_status in {'completed', 'completed_partial', 'failed', 'invalid', 'incomplete', 'skipped', 'cancelled', 'canceled'}:
        raise WorkflowCancellationConflictError('This workflow run has already finished.')

    requested_at = datetime.now(timezone.utc).isoformat()
    if run_status in M365_ACTIVE_STATES:
        run_record = {
            **run_record,
            'status': 'cancelled',
            'completed_at': requested_at,
            'cancellation_requested_at': requested_at,
            'cancellation_requested_by': requested_by,
        }
        run_record = save_run(run_record)
        updated_workflow = update_runtime_fields({
            'status': 'idle', 'last_run_status': 'cancelled',
            'active_run_id': '', 'cancellation_requested_at': requested_at,
            'cancellation_requested_by': requested_by,
        })
        cancel_m365_workflow_requests(workflow_id, target_run_id)
        return updated_workflow, run_record
    if run_record:
        run_record = dict(run_record)
        run_record.update({
            'status': 'cancelling',
            'cancellation_requested_at': run_record.get('cancellation_requested_at') or requested_at,
            'cancellation_requested_by': run_record.get('cancellation_requested_by') or requested_by,
        })
        run_record = save_run(run_record)
    else:
        run_record = {
            'id': target_run_id,
            'workflow_id': workflow_id,
            'status': 'cancelling',
            'cancellation_requested_at': requested_at,
            'cancellation_requested_by': requested_by,
        }
        run_record = save_run(run_record)

    updated_workflow = update_runtime_fields({
        'status': 'cancelling',
        'last_run_status': 'cancelling',
        'active_run_id': target_run_id,
        'cancellation_requested_at': run_record.get('cancellation_requested_at') or requested_at,
        'cancellation_requested_by': run_record.get('cancellation_requested_by') or requested_by,
    })
    return updated_workflow, run_record


def _workflow_runtime_response(workflow_id, run_id, *, group=False, action=None):
    user_id = get_current_user_id()
    try:
        if group:
            group_id, settings = _resolve_group_workflow_request_group(user_id)
            workflow = get_group_workflow(group_id, workflow_id)
            try:
                assert_group_role(user_id, group_id, allowed_roles=get_group_workflow_management_roles(settings))
                can_decide = True
            except PermissionError:
                can_decide = False
        else:
            workflow = get_personal_workflow(user_id, workflow_id)
            can_decide = True
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404
        if action:
            if not can_decide:
                return jsonify({'error': 'You cannot make decisions for this workflow.'}), 403
            data = request.get_json(silent=True)
            allowed = {'expected_version', 'request_id'} | ({'gate_id', 'choice'} if action == 'decision' else set())
            if not isinstance(data, dict) or data.keys() - allowed:
                return jsonify({'error': 'Invalid workflow decision.'}), 400
            runtime = decide_workflow_runtime(workflow, run_id, data, actor_user_id=user_id, resume=action == 'resume')
        else:
            runtime = workflow_runtime_status(workflow, run_id, reader_user_id=user_id)
        return jsonify({'runtime': runtime, 'can_decide': can_decide})
    except WorkflowRuntimeConflict as exc:
        return jsonify({'error': exc.public_message, 'code': exc.code}), 409
    except PermissionError:
        return jsonify({'error': 'Workflow progress is unavailable because current access could not be confirmed.'}), 403
    except (LookupError, CosmosResourceNotFoundError):
        return jsonify({'error': 'Durable workflow run not found.'}), 404
    except ValueError:
        return jsonify({'error': 'Invalid workflow decision or request identifier.'}), 400
    except (AzureError, RuntimeUnavailable) as exc:
        log_event(
            '[WORKFLOW_ROUTES] Durable workflow operation failed',
            extra={'workflow_id': workflow_id, 'run_id': run_id, 'error_type': type(exc).__name__},
            level=logging.ERROR,
        )
        return jsonify({'error': 'Workflow progress is temporarily unavailable.'}), 503


def _workflow_execution_history_response(workflow_id, run_id, *, group=False, kind='execution',
                                         execution_id=None, attempt=None):
    user_id = get_current_user_id()
    try:
        if group:
            group_id, _ = _resolve_group_workflow_request_group(user_id)
            workflow = get_group_workflow(group_id, workflow_id)
            run = get_group_workflow_run(group_id, run_id)
        else:
            workflow = get_personal_workflow(user_id, workflow_id)
            run = get_personal_workflow_run(user_id, run_id)
        if not workflow or not run or run.get('workflow_id') != workflow_id:
            return jsonify({'error': 'Workflow run not found.'}), 404
        if attempt is not None:
            offset, limit = int(request.args.get('offset', '0')), int(request.args.get('limit', '2000'))
            if offset < 0 or not 1 <= limit <= 65536 or attempt < 1:
                raise ValueError('Invalid result page.')
            response = workflow_execution_result_page(
                workflow, run_id, execution_id, attempt, reader_user_id=user_id,
                output=request.args.get('output', 'authoritative'), offset=offset, limit=limit,
            )
        else:
            response = workflow_execution_history(
                workflow, run_id, reader_user_id=user_id, kind=kind, execution_id=execution_id,
                cursor=request.args.get('cursor'), limit=int(request.args.get('limit', '50')),
            )
        return jsonify(response)
    except WorkflowRuntimeConflict as exc:
        return jsonify({'error': exc.public_message, 'code': exc.code}), 409
    except (PermissionError, AnalysisResultUnavailable):
        return jsonify({'error': 'Current access to this execution or its contributing sources could not be confirmed.'}), 403
    except (LookupError, CosmosResourceNotFoundError):
        return jsonify({'error': 'Workflow execution or attempt not found.'}), 404
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid execution, attempt or page request.'}), 400
    except (AzureError, RuntimeUnavailable, WorkflowResultStorageUnavailableError) as exc:
        log_event('[WORKFLOW_ROUTES] Execution history read failed',
                  extra={'workflow_id': workflow_id, 'run_id': run_id, 'error_type': type(exc).__name__},
                  level=logging.ERROR)
        return jsonify({'error': 'Workflow execution history is temporarily unavailable.'}), 503


def _queue_workflow_response(workflow, user_id):
    data = request.get_json(silent=True)
    if data is None and not request.data:
        data = {}
    if not isinstance(data, dict) or data.keys() - {'request_id'}:
        return jsonify({'error': 'Invalid workflow run request.'}), 400
    try:
        queued = queue_durable_workflow_run(
            workflow, actor_user_id=user_id, request_id=data.get('request_id'),
        )
        queued['workflow'] = _workflow_definition_response(queued['workflow'], user_id)
        queued['run'] = {key: queued['run'].get(key) for key in (
            'id', 'workflow_id', 'status', 'success', 'durable_execution', 'started_at', 'completed_at',
        )}
        return jsonify(queued), 202
    except WorkflowRuntimeConflict as exc:
        return jsonify({'error': exc.public_message, 'code': exc.code}), 409
    except (ValueError, LookupError):
        return jsonify({'error': 'The workflow could not be queued. Reload its saved definition.'}), 400
    except PermissionError:
        return jsonify({'error': 'You cannot run this workflow.'}), 403
    except (AzureError, RuntimeUnavailable) as exc:
        log_event(
            '[WORKFLOW_ROUTES] Durable workflow submission failed',
            extra={'workflow_id': workflow['id'], 'error_type': type(exc).__name__}, level=logging.ERROR,
        )
        return jsonify({'error': 'The workflow could not be queued right now.'}), 503


def _normalize_workflow_instruction_draft_input(value, max_length=WORKFLOW_INSTRUCTION_FIELD_LIMIT):
    normalized_value = re.sub(r'\s+', ' ', str(value or '')).strip()
    return normalized_value[:max_length]


def _build_workflow_instruction_messages(name, description, brief, existing_instructions):
    name = _normalize_workflow_instruction_draft_input(name, 500)
    description = _normalize_workflow_instruction_draft_input(description)
    brief = _normalize_workflow_instruction_draft_input(brief)
    existing_instructions = _normalize_workflow_instruction_draft_input(existing_instructions)

    user_sections = [
        f'Workflow name: {name or "Not provided"}',
        f'Workflow description: {description or "Not provided"}',
        f'Task brief: {brief or "Not provided"}',
    ]
    if existing_instructions:
        user_sections.append(
            f'Existing workflow instructions to improve or preserve where useful:\n{existing_instructions}'
        )

    return [
        {
            'role': 'system',
            'content': (
                'You write production-ready SimpleChat workflow instructions. '
                'Return only the finished instructions in Markdown. '
                'Be specific about the recurring task goal, inputs to inspect, output format, constraints, '
                'failure handling, and any document or URL review expectations. '
                'Do not include code fences, preambles, or commentary about how the instructions were created.'
            ),
        },
        {
            'role': 'user',
            'content': (
                '\n\n'.join(user_sections)
                + '\n\nDraft concise but complete workflow instructions that the user can edit before saving the workflow.'
            ),
        },
    ]


def _assert_personal_workflow_draft_access(settings):
    user_roles = (session.get('user') or {}).get('roles', [])
    if is_user_workflows_enabled_for_user(settings, user_roles=user_roles):
        return
    if not settings.get('allow_user_workflows', False):
        raise ValueError('Personal workflows are disabled.')
    raise PermissionError('Personal workflows require the WorkflowUser app role.')


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
    group_id = _normalize_identifier(request.args.get('group_id') or request.args.get('groupId'))
    if group_id:
        assert_group_role(user_id, group_id, allowed_roles=allowed_roles)
    else:
        group_id = require_active_group(user_id, allowed_roles=allowed_roles)
    settings = _assert_group_workflow_feature_enabled(group_id)
    return group_id, settings


def _resolve_group_workflow_request_group(user_id, allowed_roles=GROUP_WORKFLOW_MEMBER_ROLES):
    return _resolve_active_group_for_workflows(user_id, allowed_roles=allowed_roles)


def _resolve_active_group_for_workflow_management(user_id):
    settings = get_settings()
    allowed_roles = get_group_workflow_management_roles(settings)
    group_id, _ = _resolve_group_workflow_request_group(user_id, allowed_roles=allowed_roles)
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


def _force_group_document_action_scope(action_config, group_id):
    """Keep a resumed group workflow document action inside the owning group workspace."""
    action_config = dict(action_config) if isinstance(action_config, dict) else {'type': DOCUMENT_ACTION_TYPE_NONE}
    if action_config.get('type') == DOCUMENT_ACTION_TYPE_NONE:
        return action_config

    action_config['doc_scope'] = 'group'
    action_config['active_group_ids'] = [group_id]
    action_config['active_public_workspace_id'] = []
    return action_config


def _narrow_analyze_action_to_documents(action_config, document_ids, group_ids, public_workspace_ids):
    """Point an analyze action at a specific document set, or disable it when empty."""
    action_config = action_config if isinstance(action_config, dict) else {}
    if action_config.get('type') != DOCUMENT_ACTION_TYPE_ANALYZE:
        return None
    if not document_ids:
        return {'type': DOCUMENT_ACTION_TYPE_NONE}

    narrowed_action = dict(action_config)
    narrowed_action.update({
        'document_ids': list(document_ids),
        'doc_scope': 'all',
        'active_group_ids': group_ids or list(action_config.get('active_group_ids') or []),
        'active_public_workspace_id': public_workspace_ids or list(action_config.get('active_public_workspace_id') or []),
    })
    return narrowed_action


def _build_resume_failed_workflow(workflow, failed_items):
    action_config = workflow.get('document_action') if isinstance(workflow.get('document_action'), dict) else {}
    tasks = workflow.get('tasks') if isinstance(workflow.get('tasks'), list) else []
    task_analyze_ids = {
        _normalize_identifier(task.get('id'))
        for task in tasks
        if isinstance(task, dict)
        and isinstance(task.get('document_action'), dict)
        and task['document_action'].get('type') == DOCUMENT_ACTION_TYPE_ANALYZE
    }
    if action_config.get('type') != DOCUMENT_ACTION_TYPE_ANALYZE and not task_analyze_ids:
        raise ValueError('Resume failed items currently supports Analyze workflows.')

    document_ids = []
    document_ids_by_task = {}
    group_ids = []
    public_workspace_ids = []
    for item in failed_items:
        document_id = _normalize_identifier(item.get('document_id'))
        if document_id and document_id not in document_ids:
            document_ids.append(document_id)
        task_id = _normalize_identifier(item.get('task_id'))
        if document_id and task_id:
            task_documents = document_ids_by_task.setdefault(task_id, [])
            if document_id not in task_documents:
                task_documents.append(document_id)
        scope_type = _normalize_identifier(item.get('scope_type')).lower()
        scope_id = _normalize_identifier(item.get('scope_id'))
        if scope_type == FILE_SYNC_SCOPE_GROUP and scope_id and scope_id not in group_ids:
            group_ids.append(scope_id)
        elif scope_type == FILE_SYNC_SCOPE_PUBLIC and scope_id and scope_id not in public_workspace_ids:
            public_workspace_ids.append(scope_id)

    if not document_ids:
        raise ValueError('No failed document items are available to resume.')

    resume_workflow = dict(workflow)
    resume_action = _narrow_analyze_action_to_documents(
        action_config,
        document_ids,
        group_ids,
        public_workspace_ids,
    ) or dict(action_config)
    resume_workflow['document_action'] = resume_action
    resume_workflow['analyze'] = build_analyze_config(resume_action)

    if tasks:
        # Task document actions take precedence at run time, so narrow them too or the
        # resume would re-run every document the task originally targeted.
        resume_tasks = []
        for task in tasks:
            resume_task = dict(task) if isinstance(task, dict) else {}
            task_id = _normalize_identifier(resume_task.get('id'))
            narrowed_task_action = _narrow_analyze_action_to_documents(
                resume_task.get('document_action'),
                document_ids_by_task.get(task_id, [] if document_ids_by_task else document_ids),
                group_ids,
                public_workspace_ids,
            )
            if narrowed_task_action is not None:
                resume_task['document_action'] = narrowed_task_action
            resume_tasks.append(resume_task)
        resume_workflow['tasks'] = resume_tasks

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
    if run_record and workflow:
        authorize_workflow_run_read(workflow, run_record['id'], reader_user_id=user_id)
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
        pending_actions = [
            sanitize_msgraph_pending_action_for_client(action, viewer_user_id=user_id)
            for action in raw_pending_actions
        ]

    run_record, _, analysis_access_available = sanitize_workflow_analysis_history(workflow, run_record, user_id)
    if not analysis_access_available:
        thoughts = []
        pending_actions = []
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
    if run_record and workflow:
        authorize_workflow_run_read(workflow, run_record['id'], reader_user_id=user_id)
    if run_record and conversation_id and _normalize_identifier(run_record.get('assistant_message_id')):
        thoughts = get_thoughts_for_message(
            conversation_id,
            run_record.get('assistant_message_id'),
            run_owner_user_id,
        )

    pending_actions = []
    if run_record or conversation_id or workflow_id:
        raw_pending_actions = list_msgraph_pending_actions(
            _normalize_identifier(
                (run_record or {}).get('m365_run_as_user_id')
                or (workflow or {}).get('m365_run_as_user_id')
                or run_owner_user_id
            ),
            conversation_id=conversation_id or _normalize_identifier((run_record or {}).get('conversation_id')),
            workflow_id=workflow_id or _normalize_identifier((workflow or {}).get('id')),
            run_id=_normalize_identifier((run_record or {}).get('id')),
            limit=100,
        )
        pending_actions = [
            sanitize_msgraph_pending_action_for_client(action, viewer_user_id=user_id)
            for action in raw_pending_actions
        ]

    run_record, _, analysis_access_available = sanitize_workflow_analysis_history(workflow, run_record, user_id)
    if not analysis_access_available:
        thoughts = []
        pending_actions = []
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
        try:
            snapshot = _resolve_workflow_activity_context(
                user_id, conversation_id=conversation_id, workflow_id=workflow_id, run_id=run_id,
            )
        except AnalysisResultUnavailable:
            yield 'event: error\ndata: {"error":"Workflow source access is no longer available.","code":"source_access_denied"}\n\n'
            return
        payload = json.dumps(snapshot, default=str, sort_keys=True)

        if payload != last_payload:
            last_payload = payload
            yield f'data: {payload}\n\n'
        else:
            yield ': keep-alive\n\n'

        run_status = str(((snapshot.get('run') or {}).get('status') or '')).strip().lower()
        if run_status and run_status not in ({'running', 'cancelling'} | M365_ACTIVE_STATES) and not snapshot.get('live'):
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
        try:
            snapshot = _resolve_group_workflow_activity_context(
                user_id, group_id, conversation_id=conversation_id, workflow_id=workflow_id, run_id=run_id,
            )
        except AnalysisResultUnavailable:
            yield 'event: error\ndata: {"error":"Workflow source access is no longer available.","code":"source_access_denied"}\n\n'
            return
        payload = json.dumps(snapshot, default=str, sort_keys=True)

        if payload != last_payload:
            last_payload = payload
            yield f'data: {payload}\n\n'
        else:
            yield ': keep-alive\n\n'

        run_status = str(((snapshot.get('run') or {}).get('status') or '')).strip().lower()
        if run_status and run_status not in ({'running', 'cancelling'} | M365_ACTIVE_STATES) and not snapshot.get('live'):
            terminal_snapshots_seen += 1
            if terminal_snapshots_seen >= 2:
                break
        else:
            terminal_snapshots_seen = 0

        time.sleep(0.5)


def register_route_backend_workflows(bp):
    @bp.route('/api/workflows/m365-run-as-users', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def m365_workflow_run_as_users():
        actor_id = get_current_user_id()
        scope = request.args.get('scope', 'personal')
        if scope not in {'personal', 'group'}:
            return jsonify({'error': 'Unsupported workflow scope.'}), 400
        user_info = get_current_user_info() or {}
        users = {
            actor_id: {
                'id': actor_id,
                'display_name': user_info.get('displayName')
                or user_info.get('name') or user_info.get('email') or actor_id,
            }
        }
        if scope == 'group':
            group_id = str(request.args.get('group_id') or '').strip()
            if not group_id:
                return jsonify({'error': 'Select a group for this workflow.'}), 400
            try:
                assert_group_role(
                    actor_id, group_id,
                    allowed_roles=get_group_workflow_management_roles(get_settings()),
                )
                group = find_group_by_id(group_id)
                if not group:
                    return jsonify({'error': 'Group not found.'}), 404
                members = [
                    group.get('owner') or {},
                    *(group.get('admins') or []),
                    *(group.get('documentManagers') or []),
                    *(group.get('users') or []),
                ]
                for member in members:
                    member_id = str(member.get('userId') or member.get('id') or '').strip()
                    if member_id:
                        users[member_id] = {
                            'id': member_id,
                            'display_name': member.get('displayName')
                            or member.get('email') or member_id,
                        }
            except PermissionError:
                return jsonify({'error': 'You cannot configure this group workflow.'}), 403
            except LookupError:
                return jsonify({'error': 'Group not found.'}), 404
        return jsonify({'users': list(users.values())})

    @bp.route('/api/user/workflows/<workflow_id>/runs/<run_id>/executions', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def get_user_workflow_executions(workflow_id, run_id):
        return _workflow_execution_history_response(workflow_id, run_id)

    @bp.route('/api/group/workflows/<workflow_id>/runs/<run_id>/executions', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def get_group_workflow_executions(workflow_id, run_id):
        return _workflow_execution_history_response(workflow_id, run_id, group=True)

    @bp.route('/api/user/workflows/<workflow_id>/runs/<run_id>/executions/<execution_id>/attempts', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def get_user_workflow_execution_attempts(workflow_id, run_id, execution_id):
        return _workflow_execution_history_response(workflow_id, run_id, execution_id=execution_id, kind='attempt')

    @bp.route('/api/group/workflows/<workflow_id>/runs/<run_id>/executions/<execution_id>/attempts', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def get_group_workflow_execution_attempts(workflow_id, run_id, execution_id):
        return _workflow_execution_history_response(workflow_id, run_id, group=True, execution_id=execution_id, kind='attempt')

    @bp.route('/api/user/workflows/<workflow_id>/runs/<run_id>/executions/<execution_id>/attempts/<int:attempt>/result', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def get_user_workflow_execution_result(workflow_id, run_id, execution_id, attempt):
        return _workflow_execution_history_response(workflow_id, run_id, execution_id=execution_id, attempt=attempt)

    @bp.route('/api/group/workflows/<workflow_id>/runs/<run_id>/executions/<execution_id>/attempts/<int:attempt>/result', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def get_group_workflow_execution_result(workflow_id, run_id, execution_id, attempt):
        return _workflow_execution_history_response(workflow_id, run_id, group=True, execution_id=execution_id, attempt=attempt)

    @bp.route('/api/user/workflows/<workflow_id>/runs/<run_id>/runtime/decisions', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def get_user_workflow_decisions(workflow_id, run_id):
        return _workflow_execution_history_response(workflow_id, run_id, kind='decision')

    @bp.route('/api/group/workflows/<workflow_id>/runs/<run_id>/runtime/decisions', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def get_group_workflow_decisions(workflow_id, run_id):
        return _workflow_execution_history_response(workflow_id, run_id, group=True, kind='decision')

    @bp.route('/api/user/workflows/<workflow_id>/runs/<run_id>/runtime', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def get_user_workflow_runtime(workflow_id, run_id):
        return _workflow_runtime_response(workflow_id, run_id)

    @bp.route('/api/user/workflows/<workflow_id>/runs/<run_id>/runtime/decision', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def decide_user_workflow_runtime(workflow_id, run_id):
        return _workflow_runtime_response(workflow_id, run_id, action='decision')

    @bp.route('/api/user/workflows/<workflow_id>/runs/<run_id>/runtime/resume', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def resume_user_workflow_runtime(workflow_id, run_id):
        return _workflow_runtime_response(workflow_id, run_id, action='resume')

    @bp.route('/api/group/workflows/<workflow_id>/runs/<run_id>/runtime', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def get_group_workflow_runtime(workflow_id, run_id):
        return _workflow_runtime_response(workflow_id, run_id, group=True)

    @bp.route('/api/group/workflows/<workflow_id>/runs/<run_id>/runtime/decision', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def decide_group_workflow_runtime(workflow_id, run_id):
        return _workflow_runtime_response(workflow_id, run_id, group=True, action='decision')

    @bp.route('/api/group/workflows/<workflow_id>/runs/<run_id>/runtime/resume', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def resume_group_workflow_runtime(workflow_id, run_id):
        return _workflow_runtime_response(workflow_id, run_id, group=True, action='resume')

    @bp.route('/api/workflows/draft-instructions', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def draft_workflow_instructions():
        settings = get_settings()
        request_data = request.get_json(silent=True) or {}
        user_id = get_current_user_id()
        workflow_scope = str(request_data.get('workflow_scope') or 'personal').strip().lower()

        try:
            if workflow_scope == 'group':
                _resolve_active_group_for_workflow_management(user_id)
            elif workflow_scope == 'personal':
                _assert_personal_workflow_draft_access(settings)
            else:
                return jsonify({'error': 'Invalid workflow scope.'}), 400
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except (LookupError, PermissionError) as exc:
            return jsonify({'error': str(exc)}), 403

        name = request_data.get('name')
        description = request_data.get('description')
        brief = request_data.get('brief')
        existing_instructions = request_data.get('existing_instructions')
        if not any(str(value or '').strip() for value in (name, description, brief, existing_instructions)):
            return jsonify({'error': 'Provide a task brief, workflow name, description, or existing instructions.'}), 400

        try:
            model_name = _resolve_agent_instruction_model(settings)
            client = _create_agent_instruction_client(settings)
            messages = _build_workflow_instruction_messages(
                name,
                description,
                brief,
                existing_instructions,
            )
            response = client.chat.completions.create(
                **_build_agent_instruction_api_params(model_name, messages)
            )
            instructions = ''
            if getattr(response, 'choices', None):
                instructions = str(response.choices[0].message.content or '').strip()
            if not instructions:
                return jsonify({'error': 'The model did not return workflow instructions.'}), 502

            log_event(
                '[WORKFLOW_INSTRUCTIONS] Workflow instructions drafted.',
                extra={
                    'user_id': str(user_id),
                    'workflow_scope': workflow_scope,
                    'model_name': model_name,
                },
                debug_only=True,
            )
            return jsonify({'success': True, 'instructions': instructions})
        except Exception as exc:
            log_event(
                f'[WORKFLOW_INSTRUCTIONS] Error drafting workflow instructions: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to draft workflow instructions.'}), 500

    @bp.route('/api/user/workflows', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def get_user_workflows():
        user_id = get_current_user_id()
        return jsonify({'workflows': [
            _workflow_definition_response(workflow, user_id)
            for workflow in get_personal_workflows(user_id)
        ]})


    @bp.route('/api/user/workflows/editor-options', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def get_user_workflow_editor_options():
        user_id = get_current_user_id()
        try:
            return jsonify(get_workflow_editor_options(user_id, get_settings()))
        except AzureError as exc:
            log_event(
                '[WORKFLOW_ROUTES] Workflow editor choices unavailable',
                extra={'user_id': user_id, 'error_type': type(exc).__name__}, level=logging.ERROR,
            )
            return jsonify({'error': 'Workflow editor choices are temporarily unavailable.'}), 503


    @bp.route('/api/user/workflows/file-sync-sources', methods=['GET'])
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
                f'[WORKFLOW_ROUTES] Failed to load workflow File Sync sources: {exc}',
                extra={'user_id': user_id},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Unable to load File Sync sources right now.'}), 500


    @bp.route('/api/user/workflows', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def save_user_workflow():
        user_id = get_current_user_id()
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({'error': 'Workflow settings must be a JSON object.'}), 400
        is_create = not str(payload.get('id') or '').strip()

        try:
            payload = _prepare_workflow_url_access_payload(payload, user_id)
            workflow = save_personal_workflow(user_id, payload, actor_user_id=user_id)
        except WorkflowDefinitionConflict as exc:
            return jsonify({'error': exc.public_message, 'code': 'workflow_definition_conflict'}), 409
        except WorkflowDefinitionError as exc:
            return jsonify({'error': exc.public_message, 'code': 'invalid_workflow_definition'}), 400
        except PermissionError as exc:
            return jsonify({'error': 'Workflow settings or sources are not allowed for this account.'}), 403
        except ValueError as exc:
            return jsonify({'error': 'Invalid workflow settings. Review the task, runner, trigger, and document inputs.'}), 400
        except Exception as exc:
            log_event(
                f'[WORKFLOW_ROUTES] Failed to save workflow: {exc}',
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

        return jsonify({'success': True, 'workflow': _workflow_definition_response(workflow, user_id)}), 201 if is_create else 200


    @bp.route('/api/user/workflows/<workflow_id>', methods=['DELETE'])
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


    @bp.route('/api/user/workflows/<workflow_id>/runs', methods=['GET'])
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

        runs = list_personal_workflow_runs(user_id, workflow_id, limit=50)
        try:
            for run in runs:
                authorize_workflow_run_read(workflow, run['id'], reader_user_id=user_id)
        except AnalysisResultUnavailable:
            return jsonify({'error': 'Run history is unavailable because source access could not be confirmed.'}), 403
        return jsonify({
            'workflow_id': workflow_id,
            'runs': [
                sanitize_workflow_analysis_history(workflow, run, user_id)[0]
                for run in runs
            ],
        })


    @bp.route('/api/user/workflows/<workflow_id>/cancel', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def cancel_active_user_workflow_run(workflow_id):
        user_id = get_current_user_id()
        workflow = get_personal_workflow(user_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        try:
            updated_workflow, run_record = _request_workflow_run_cancellation(
                workflow,
                run_id='',
                requested_by=user_id,
                get_run=lambda requested_run_id: get_personal_workflow_run(user_id, requested_run_id),
                save_run=lambda requested_run: save_personal_workflow_run(user_id, requested_run),
                update_runtime_fields=lambda updates: update_personal_workflow_runtime_fields(user_id, workflow_id, updates),
            )
        except LookupError as exc:
            logging.exception("LookupError while cancelling active user workflow run.")
            return jsonify({'error': 'Workflow run not found.'}), 404
        except WorkflowCancellationConflictError as exc:
            logging.exception("Workflow cancellation conflict while cancelling active user workflow run.")
            return jsonify({'error': 'Workflow run cannot be cancelled in its current state.'}), 409

        return jsonify({'success': True, 'workflow': updated_workflow, 'run': run_record}), 202


    @bp.route('/api/user/workflows/<workflow_id>/runs/<run_id>/cancel', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def cancel_user_workflow_run(workflow_id, run_id):
        user_id = get_current_user_id()
        workflow = get_personal_workflow(user_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        try:
            updated_workflow, run_record = _request_workflow_run_cancellation(
                workflow,
                run_id=run_id,
                requested_by=user_id,
                get_run=lambda requested_run_id: get_personal_workflow_run(user_id, requested_run_id),
                save_run=lambda requested_run: save_personal_workflow_run(user_id, requested_run),
                update_runtime_fields=lambda updates: update_personal_workflow_runtime_fields(user_id, workflow_id, updates),
            )
        except LookupError:
            logging.exception(
                "LookupError while cancelling personal workflow run. workflow_id=%s run_id=%s user_id=%s",
                workflow_id,
                run_id,
                user_id,
            )
            return jsonify({'error': 'Workflow run not found.'}), 404
        except WorkflowCancellationConflictError:
            logging.exception(
                "WorkflowCancellationConflictError while cancelling personal workflow run. workflow_id=%s run_id=%s user_id=%s",
                workflow_id,
                run_id,
                user_id,
            )
            return jsonify({'error': 'Workflow run cancellation conflict.'}), 409

        return jsonify({'success': True, 'workflow': updated_workflow, 'run': run_record}), 202


    @bp.route('/api/user/workflows/<workflow_id>/runs/<run_id>/items', methods=['GET'])
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

        try:
            authorize_workflow_run_read(workflow, run_id, reader_user_id=user_id)
        except AnalysisResultUnavailable:
            return jsonify({'error': 'Task results are unavailable because source access could not be confirmed.'}), 403
        return jsonify({
            'workflow_id': workflow_id,
            'run_id': run_id,
            'items': sanitize_workflow_analysis_history(
                workflow, run_record, user_id, items=list_personal_workflow_run_items(run_id, limit=1000),
            )[1],
        })


    @bp.route('/api/user/workflows/<workflow_id>/runs/<run_id>/tasks/<task_id>/result', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    @workflow_user_required
    def get_user_workflow_task_result(workflow_id, run_id, task_id):
        user_id = get_current_user_id()
        workflow = get_personal_workflow(user_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404
        run_record = get_personal_workflow_run(user_id, run_id)
        return _workflow_task_result_page_response(
            workflow, run_record, task_id, get_personal_workflow_run_item,
        )


    @bp.route('/api/user/workflows/<workflow_id>/runs/<run_id>/resume-failed', methods=['POST'])
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
        if workflow.get('durable_execution') is True:
            return jsonify({'error': 'Use the durable run resume controls to reuse checkpoints without restarting completed tasks.'}), 409

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
            active_run_id = create_workflow_run_id()
            update_personal_workflow_runtime_fields(
                user_id,
                workflow_id,
                {
                    'status': 'running',
                    'active_run_id': active_run_id,
                    'cancellation_requested_at': None,
                    'cancellation_requested_by': '',
                    'last_run_started_at': started_at,
                    'last_run_trigger_source': 'resume_failed',
                    'last_run_error': '',
                },
            )

            result = run_personal_workflow(
                resume_workflow,
                trigger_source='resume_failed',
                user_roles=(session.get('user') or {}).get('roles', []),
                run_id=active_run_id,
            )
            update_fields = dict(result.get('workflow_updates') or {})
            update_fields['status'] = workflow_result_runtime_status(result)
            run_status = _normalize_identifier((result.get('run') or {}).get('status')).lower()
            if workflow.get('trigger_type') in {'interval', 'file_sync'} and workflow.get('is_enabled', False) and (
                not workflow.get('next_run_at') or run_status in {'cancelled', 'canceled'}
            ):
                update_fields['next_run_at'] = compute_next_run_at(workflow, from_time=datetime.now(timezone.utc))

            updated_workflow = update_personal_workflow_runtime_fields(user_id, workflow_id, update_fields)
            response_body = {
                'success': bool(result.get('success')),
                'workflow': updated_workflow,
                'run': result.get('run'),
                'resumed_item_count': len(failed_items),
            }
            if workflow_result_is_waiting(result):
                return jsonify(response_body), 202
            if result.get('success'):
                return jsonify(response_body)
            return jsonify(response_body), 500
        finally:
            release_distributed_task_lock(lock_document)


    @bp.route('/api/group/workflows', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def get_group_workflows_route():
        user_id = get_current_user_id()
        try:
            group_id, _ = _resolve_group_workflow_request_group(user_id)
            return jsonify({'workflows': [
                _workflow_definition_response(workflow, user_id)
                for workflow in get_group_workflows(group_id)
            ]})
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403


    @bp.route('/api/group/workflows/editor-options', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def get_group_workflow_editor_options_route():
        user_id = get_current_user_id()
        try:
            group_id, settings = _resolve_group_workflow_request_group(user_id)
            return jsonify(get_workflow_editor_options(user_id, settings, group_id=group_id))
        except (ValueError, LookupError, PermissionError):
            return jsonify({'error': 'The selected group is not available for workflow editing.'}), 403
        except AzureError as exc:
            log_event(
                '[WORKFLOW_ROUTES] Group workflow editor choices unavailable',
                extra={'user_id': user_id, 'error_type': type(exc).__name__}, level=logging.ERROR,
            )
            return jsonify({'error': 'Workflow editor choices are temporarily unavailable.'}), 503


    @bp.route('/api/group/workflows/file-sync-sources', methods=['GET'])
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
                f'[WORKFLOW_ROUTES] Failed to load group workflow File Sync sources: {exc}',
                extra={'user_id': user_id},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Unable to load File Sync sources right now.'}), 500


    @bp.route('/api/group/workflows/agents', methods=['GET'])
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
                f'[WORKFLOW_ROUTES] Failed to load group workflow agents: {exc}',
                extra={'user_id': user_id},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Unable to load group workflow agents right now.'}), 500


    @bp.route('/api/group/workflows', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def save_group_workflow_route():
        user_id = get_current_user_id()
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({'error': 'Workflow settings must be a JSON object.'}), 400
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
        except WorkflowDefinitionConflict as exc:
            return jsonify({'error': exc.public_message, 'code': 'workflow_definition_conflict'}), 409
        except WorkflowDefinitionError as exc:
            return jsonify({'error': exc.public_message, 'code': 'invalid_workflow_definition'}), 400
        except ValueError as exc:
            return jsonify({'error': 'Invalid workflow settings. Review the task, runner, trigger, and document inputs.'}), 400
        except LookupError as exc:
            return jsonify({'error': 'The workflow or one of its sources is not available.'}), 404
        except PermissionError as exc:
            return jsonify({'error': 'The selected group or workflow sources are not allowed.'}), 403
        except Exception as exc:
            log_event(
                f'[WORKFLOW_ROUTES] Failed to save group workflow: {exc}',
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

        return jsonify({'success': True, 'workflow': _workflow_definition_response(workflow, user_id)}), 201 if is_create else 200


    @bp.route('/api/group/workflows/<workflow_id>', methods=['DELETE'])
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


    @bp.route('/api/group/workflows/<workflow_id>/runs', methods=['GET'])
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

        runs = list_group_workflow_runs(group_id, workflow_id, limit=50)
        try:
            for run in runs:
                authorize_workflow_run_read(workflow, run['id'], reader_user_id=user_id)
        except AnalysisResultUnavailable:
            return jsonify({'error': 'Run history is unavailable because source access could not be confirmed.'}), 403
        return jsonify({
            'workflow_id': workflow_id,
            'runs': [
                sanitize_workflow_analysis_history(workflow, run, user_id)[0]
                for run in runs
            ],
        })


    @bp.route('/api/group/workflows/<workflow_id>/cancel', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def cancel_active_group_workflow_run(workflow_id):
        user_id = get_current_user_id()
        try:
            group_id, _ = _resolve_group_workflow_request_group(user_id)
        except ValueError as exc:
            logging.exception(
                "Invalid group workflow request during cancellation. user_id=%s workflow_id=%s",
                user_id,
                workflow_id,
            )
            return jsonify({'error': 'Invalid group workflow request.'}), 400
        except LookupError as exc:
            logging.exception(
                "Group workspace lookup failed during workflow cancellation. user_id=%s workflow_id=%s",
                user_id,
                workflow_id,
            )
            return jsonify({'error': 'Group workspace not found.'}), 404
        except PermissionError as exc:
            logging.exception(
                "Unauthorized group workflow cancellation attempt. user_id=%s workflow_id=%s",
                user_id,
                workflow_id,
            )
            return jsonify({'error': 'Not authorized to access this group workspace.'}), 403

        workflow = get_group_workflow(group_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        try:
            updated_workflow, run_record = _request_workflow_run_cancellation(
                workflow,
                run_id='',
                requested_by=user_id,
                get_run=lambda requested_run_id: get_group_workflow_run(group_id, requested_run_id),
                save_run=lambda requested_run: save_group_workflow_run(group_id, requested_run),
                update_runtime_fields=lambda updates: update_group_workflow_runtime_fields(group_id, workflow_id, updates),
            )
        except LookupError as exc:
            logging.exception('Group workflow run cancellation failed: run not found.', exc_info=exc)
            return jsonify({'error': 'Workflow run not found.'}), 404
        except WorkflowCancellationConflictError as exc:
            return jsonify({'error': str(exc)}), 409

        return jsonify({'success': True, 'workflow': updated_workflow, 'run': run_record}), 202


    @bp.route('/api/group/workflows/<workflow_id>/runs/<run_id>/cancel', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def cancel_group_workflow_run(workflow_id, run_id):
        user_id = get_current_user_id()
        try:
            group_id, _ = _resolve_group_workflow_request_group(user_id)
        except ValueError:
            logging.exception('Invalid group workflow cancellation request.')
            return jsonify({'error': 'Invalid request.'}), 400
        except LookupError:
            logging.exception('Group not found while cancelling workflow run.')
            return jsonify({'error': 'Group not found.'}), 404
        except PermissionError:
            logging.exception('Permission denied while cancelling workflow run.')
            return jsonify({'error': 'Forbidden.'}), 403

        workflow = get_group_workflow(group_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        try:
            updated_workflow, run_record = _request_workflow_run_cancellation(
                workflow,
                run_id=run_id,
                requested_by=user_id,
                get_run=lambda requested_run_id: get_group_workflow_run(group_id, requested_run_id),
                save_run=lambda requested_run: save_group_workflow_run(group_id, requested_run),
                update_runtime_fields=lambda updates: update_group_workflow_runtime_fields(group_id, workflow_id, updates),
            )
        except LookupError as exc:
            logging.exception('Group workflow run cancellation failed due to missing resource.')
            return jsonify({'error': 'Run not found.'}), 404
        except WorkflowCancellationConflictError as exc:
            logging.exception('Group workflow run cancellation conflict.')
            return jsonify({'error': 'Unable to cancel run in its current state.'}), 409

        return jsonify({'success': True, 'workflow': updated_workflow, 'run': run_record}), 202


    @bp.route('/api/group/workflows/<workflow_id>/runs/<run_id>/items', methods=['GET'])
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

        try:
            authorize_workflow_run_read(workflow, run_id, reader_user_id=user_id)
        except AnalysisResultUnavailable:
            return jsonify({'error': 'Task results are unavailable because source access could not be confirmed.'}), 403
        return jsonify({
            'workflow_id': workflow_id,
            'run_id': run_id,
            'items': sanitize_workflow_analysis_history(
                workflow, run_record, user_id, items=list_group_workflow_run_items(run_id, limit=1000),
            )[1],
        })


    @bp.route('/api/group/workflows/<workflow_id>/runs/<run_id>/tasks/<task_id>/result', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_workflows')
    def get_group_workflow_task_result(workflow_id, run_id, task_id):
        user_id = get_current_user_id()
        try:
            group_id, _ = _resolve_group_workflow_request_group(user_id)
        except (ValueError, LookupError, PermissionError):
            return jsonify({'error': 'Group workflow access is not allowed.'}), 403
        workflow = get_group_workflow(group_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404
        run_record = get_group_workflow_run(group_id, run_id)
        return _workflow_task_result_page_response(
            workflow, run_record, task_id, get_group_workflow_run_item,
        )


    @bp.route('/api/group/workflows/<workflow_id>/runs/<run_id>/resume-failed', methods=['POST'])
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
        if workflow.get('durable_execution') is True:
            return jsonify({'error': 'Use the durable run resume controls to reuse checkpoints without restarting completed tasks.'}), 409

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
                resume_workflow['document_action'] = _force_group_document_action_scope(resume_action, group_id)
                resume_workflow['analyze'] = build_analyze_config(resume_workflow['document_action'])
            if isinstance(resume_workflow.get('tasks'), list):
                resume_workflow['tasks'] = [
                    {
                        **task,
                        'document_action': _force_group_document_action_scope(task.get('document_action'), group_id),
                    }
                    if isinstance(task, dict) and isinstance(task.get('document_action'), dict)
                    else task
                    for task in resume_workflow['tasks']
                ]
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

        lock_document = acquire_distributed_task_lock(f'group_workflow_run_{group_id}_{workflow_id}', lease_seconds=900)
        if not lock_document:
            return jsonify({'error': 'This workflow is already running.'}), 409

        try:
            started_at = datetime.now(timezone.utc).isoformat()
            active_run_id = create_workflow_run_id()
            update_group_workflow_runtime_fields(
                group_id,
                workflow_id,
                {
                    'status': 'running',
                    'active_run_id': active_run_id,
                    'cancellation_requested_at': None,
                    'cancellation_requested_by': '',
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
                run_id=active_run_id,
            )
            update_fields = dict(result.get('workflow_updates') or {})
            update_fields['status'] = workflow_result_runtime_status(result)
            run_status = _normalize_identifier((result.get('run') or {}).get('status')).lower()
            if workflow.get('trigger_type') in {'interval', 'file_sync'} and workflow.get('is_enabled', False) and (
                not workflow.get('next_run_at') or run_status in {'cancelled', 'canceled'}
            ):
                update_fields['next_run_at'] = compute_next_run_at(workflow, from_time=datetime.now(timezone.utc))

            updated_workflow = update_group_workflow_runtime_fields(group_id, workflow_id, update_fields)
            response_body = {
                'success': bool(result.get('success')),
                'workflow': updated_workflow,
                'run': result.get('run'),
                'resumed_item_count': len(failed_items),
            }
            if workflow_result_is_waiting(result):
                return jsonify(response_body), 202
            if result.get('success'):
                return jsonify(response_body)
            return jsonify(response_body), 500
        finally:
            release_distributed_task_lock(lock_document)


    @bp.route('/api/group/workflows/activity', methods=['GET'])
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
                f'[WORKFLOW_ROUTES] Failed to load group workflow activity snapshot: {exc}',
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


    @bp.route('/api/group/workflows/activity/stream', methods=['GET'])
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
                f'[WORKFLOW_ROUTES] Failed to initialize group workflow activity stream: {exc}',
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


    @bp.route('/api/group/workflows/<workflow_id>/run', methods=['POST'])
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
        if workflow.get('status') in M365_ACTIVE_STATES:
            return jsonify({
                'error': 'This workflow is waiting for Microsoft 365 approval or sign-in.',
                'active_run_id': workflow.get('active_run_id'),
                'status': workflow.get('status'),
            }), 409
        if workflow.get('durable_execution') is True:
            return _queue_workflow_response(workflow, user_id)

        lock_document = acquire_distributed_task_lock(f'group_workflow_run_{group_id}_{workflow_id}', lease_seconds=900)
        if not lock_document:
            return jsonify({'error': 'This workflow is already running.'}), 409

        try:
            started_at = datetime.now(timezone.utc).isoformat()
            active_run_id = create_workflow_run_id()
            update_group_workflow_runtime_fields(
                group_id,
                workflow_id,
                {
                    'status': 'running',
                    'active_run_id': active_run_id,
                    'cancellation_requested_at': None,
                    'cancellation_requested_by': '',
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
                run_id=active_run_id,
            )
            update_fields = dict(result.get('workflow_updates') or {})
            update_fields['status'] = workflow_result_runtime_status(result)
            run_status = _normalize_identifier((result.get('run') or {}).get('status')).lower()
            if workflow.get('trigger_type') in {'interval', 'file_sync'} and workflow.get('is_enabled', False) and (
                not workflow.get('next_run_at') or run_status in {'cancelled', 'canceled'}
            ):
                update_fields['next_run_at'] = compute_next_run_at(workflow, from_time=datetime.now(timezone.utc))

            updated_workflow = update_group_workflow_runtime_fields(group_id, workflow_id, update_fields)
            response_body = {
                'success': bool(result.get('success')),
                'workflow': updated_workflow,
                'run': result.get('run'),
            }
            if workflow_result_is_waiting(result):
                return jsonify(response_body), 202
            if result.get('success'):
                return jsonify(response_body)
            return jsonify(response_body), 500
        finally:
            release_distributed_task_lock(lock_document)


    @bp.route('/api/user/workflows/activity', methods=['GET'])
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
                f'[WORKFLOW_ROUTES] Failed to load workflow activity snapshot: {exc}',
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


    @bp.route('/api/user/workflows/activity/stream', methods=['GET'])
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
                f'[WORKFLOW_ROUTES] Failed to initialize workflow activity stream: {exc}',
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


    @bp.route('/api/user/workflows/<workflow_id>/run', methods=['POST'])
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
        if workflow.get('status') in M365_ACTIVE_STATES:
            return jsonify({
                'error': 'This workflow is waiting for Microsoft 365 approval or sign-in.',
                'active_run_id': workflow.get('active_run_id'),
                'status': workflow.get('status'),
            }), 409
        if workflow.get('durable_execution') is True:
            return _queue_workflow_response(workflow, user_id)

        lock_document = acquire_distributed_task_lock(f'workflow_run_{workflow_id}', lease_seconds=900)
        if not lock_document:
            return jsonify({'error': 'This workflow is already running.'}), 409

        try:
            started_at = datetime.now(timezone.utc).isoformat()
            active_run_id = create_workflow_run_id()
            update_personal_workflow_runtime_fields(
                user_id,
                workflow_id,
                {
                    'status': 'running',
                    'active_run_id': active_run_id,
                    'cancellation_requested_at': None,
                    'cancellation_requested_by': '',
                    'last_run_started_at': started_at,
                    'last_run_trigger_source': 'manual',
                    'last_run_error': '',
                },
            )

            result = run_personal_workflow(
                workflow,
                trigger_source='manual',
                user_roles=(session.get('user') or {}).get('roles', []),
                run_id=active_run_id,
            )
            update_fields = dict(result.get('workflow_updates') or {})
            update_fields['status'] = workflow_result_runtime_status(result)
            run_status = _normalize_identifier((result.get('run') or {}).get('status')).lower()
            if workflow.get('trigger_type') in {'interval', 'file_sync'} and workflow.get('is_enabled', False) and (
                not workflow.get('next_run_at') or run_status in {'cancelled', 'canceled'}
            ):
                update_fields['next_run_at'] = compute_next_run_at(workflow, from_time=datetime.now(timezone.utc))

            updated_workflow = update_personal_workflow_runtime_fields(user_id, workflow_id, update_fields)
            response_body = {
                'success': bool(result.get('success')),
                'workflow': updated_workflow,
                'run': result.get('run'),
            }
            if workflow_result_is_waiting(result):
                return jsonify(response_body), 202
            if result.get('success'):
                return jsonify(response_body)
            return jsonify(response_body), 500
        finally:
            release_distributed_task_lock(lock_document)
