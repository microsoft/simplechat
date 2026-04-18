# functions_personal_workflows.py

"""
Personal workflow CRUD helpers and schedule validation.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from azure.cosmos import exceptions

from config import (
    cosmos_personal_workflow_runs_container,
    cosmos_personal_workflows_container,
)
from functions_appinsights import log_event
from functions_debug import debug_print
from functions_global_agents import get_global_agents
from functions_personal_agents import get_personal_agents
from functions_settings import get_settings, get_user_settings, normalize_model_endpoints


WORKFLOW_TRIGGER_TYPES = {'manual', 'interval'}
WORKFLOW_RUNNER_TYPES = {'agent', 'model'}
WORKFLOW_SCHEDULE_UNITS = {'seconds', 'minutes', 'hours'}
WORKFLOW_ALERT_PRIORITIES = {'none', 'low', 'medium', 'high'}


def _utc_now():
    return datetime.now(timezone.utc)


def _utc_now_iso():
    return _utc_now().isoformat()


def _strip_cosmos_metadata(document):
    if not isinstance(document, dict):
        return {}
    return {key: value for key, value in document.items() if not str(key).startswith('_')}


def _normalize_text(value, field_name, required=False):
    normalized = str(value or '').strip()
    if required and not normalized:
        raise ValueError(f'{field_name} is required.')
    return normalized


def _normalize_schedule(schedule_payload):
    schedule_payload = schedule_payload if isinstance(schedule_payload, dict) else {}
    unit = str(schedule_payload.get('unit') or '').strip().lower()
    if unit not in WORKFLOW_SCHEDULE_UNITS:
        raise ValueError('Schedule unit must be seconds, minutes, or hours.')

    try:
        value = int(schedule_payload.get('value'))
    except (TypeError, ValueError):
        raise ValueError('Schedule value must be an integer.')

    max_value = 59 if unit in ('seconds', 'minutes') else 24
    if value < 1 or value > max_value:
        raise ValueError(f'Schedule value for {unit} must be between 1 and {max_value}.')

    return {
        'unit': unit,
        'value': value,
    }


def _normalize_alert_priority(value):
    normalized = str(value or 'none').strip().lower() or 'none'
    if normalized not in WORKFLOW_ALERT_PRIORITIES:
        raise ValueError('Alert priority must be none, low, medium, or high.')
    return normalized


def _build_schedule_delta(schedule_payload):
    unit = schedule_payload.get('unit')
    value = schedule_payload.get('value')
    if unit == 'seconds':
        return timedelta(seconds=value)
    if unit == 'minutes':
        return timedelta(minutes=value)
    return timedelta(hours=value)


def _build_selectable_agents(user_id, settings, requested_agent=None):
    requested_agent = requested_agent if isinstance(requested_agent, dict) else {}
    candidates = []

    for agent in get_personal_agents(user_id):
        candidate = dict(agent)
        candidate['is_global'] = False
        candidate['is_group'] = False
        candidates.append(candidate)

    merge_global = (
        settings.get('per_user_semantic_kernel', False)
        and settings.get('merge_global_semantic_kernel_with_workspace', False)
    )
    if merge_global or requested_agent.get('is_global'):
        for agent in get_global_agents():
            candidate = dict(agent)
            candidate['is_global'] = True
            candidate['is_group'] = False
            candidates.append(candidate)

    return candidates


def _find_matching_agent(candidates, requested_agent):
    if not isinstance(requested_agent, dict):
        return None

    requested_id = str(requested_agent.get('id') or '').strip()
    requested_name = str(requested_agent.get('name') or '').strip()
    requested_is_global = bool(requested_agent.get('is_global', False))

    def scope_matches(candidate):
        return bool(candidate.get('is_global', False)) == requested_is_global

    if requested_id:
        for candidate in candidates:
            if str(candidate.get('id') or '').strip() == requested_id and scope_matches(candidate):
                return candidate

    if requested_name:
        for candidate in candidates:
            if str(candidate.get('name') or '').strip() == requested_name and scope_matches(candidate):
                return candidate

    return None


def _normalize_selected_agent(user_id, settings, requested_agent):
    candidates = _build_selectable_agents(user_id, settings, requested_agent=requested_agent)
    matched_agent = _find_matching_agent(candidates, requested_agent)
    if not matched_agent:
        raise ValueError('Select a valid personal or merged global agent.')

    return {
        'id': str(matched_agent.get('id') or '').strip(),
        'name': str(matched_agent.get('name') or '').strip(),
        'display_name': str(matched_agent.get('display_name') or matched_agent.get('name') or '').strip(),
        'description': str(matched_agent.get('description') or '').strip(),
        'is_global': bool(matched_agent.get('is_global', False)),
        'is_group': False,
    }


def _build_default_model_summary(settings):
    default_selection = settings.get('default_model_selection', {}) if isinstance(settings, dict) else {}
    endpoint_id = str(default_selection.get('endpoint_id') or '').strip()
    model_id = str(default_selection.get('model_id') or '').strip()
    provider = str(default_selection.get('provider') or '').strip().lower()

    if endpoint_id and model_id:
        return {
            'mode': 'default_selection',
            'valid': True,
            'endpoint_id': endpoint_id,
            'model_id': model_id,
            'provider': provider,
            'label': 'Default app model selection',
        }

    selected_models = (settings.get('gpt_model') or {}).get('selected') or []
    default_model = selected_models[0] if selected_models else {}
    default_label = (
        default_model.get('displayName')
        or default_model.get('deploymentName')
        or default_model.get('modelName')
        or 'Default app model'
    )

    return {
        'mode': 'legacy_default',
        'valid': bool(
            settings.get('enable_gpt_apim', False)
            or settings.get('azure_openai_gpt_endpoint')
            or first_if_comma(settings.get('azure_openai_gpt_deployment'))
        ),
        'endpoint_id': '',
        'model_id': '',
        'provider': 'aoai',
        'label': default_label,
    }


def _build_model_endpoint_candidates(user_id, settings):
    candidates = []
    user_settings = get_user_settings(user_id)

    if settings.get('allow_user_custom_endpoints', False):
        personal_endpoints, _ = normalize_model_endpoints(
            user_settings.get('settings', {}).get('personal_model_endpoints', []) or []
        )
        for endpoint in personal_endpoints:
            candidate = dict(endpoint)
            candidate['scope'] = 'user'
            candidates.append(candidate)

    global_endpoints, _ = normalize_model_endpoints(settings.get('model_endpoints', []) or [])
    for endpoint in global_endpoints:
        candidate = dict(endpoint)
        candidate['scope'] = 'global'
        candidates.append(candidate)

    return candidates


def _summarize_model_binding(candidates, endpoint_id, model_id):
    endpoint_id = str(endpoint_id or '').strip()
    model_id = str(model_id or '').strip()
    if not endpoint_id and not model_id:
        return None
    if not endpoint_id or not model_id:
        raise ValueError('Select both an endpoint and model, or choose the default app model.')

    endpoint_cfg = next((candidate for candidate in candidates if candidate.get('id') == endpoint_id), None)
    if not endpoint_cfg:
        raise ValueError('The selected model endpoint is no longer available.')
    if not endpoint_cfg.get('enabled', True):
        raise ValueError('The selected model endpoint is disabled.')

    model_cfg = next(
        (model for model in endpoint_cfg.get('models', []) if model.get('id') == model_id),
        None,
    )
    if not model_cfg:
        raise ValueError('The selected model is no longer available on that endpoint.')
    if not model_cfg.get('enabled', True):
        raise ValueError('The selected model is disabled.')

    endpoint_name = endpoint_cfg.get('name') or endpoint_id
    model_name = (
        model_cfg.get('displayName')
        or model_cfg.get('deploymentName')
        or model_cfg.get('modelName')
        or model_id
    )
    provider = str(endpoint_cfg.get('provider') or '').strip().lower()
    scope = str(endpoint_cfg.get('scope') or 'global').strip().lower()
    scope_prefix = 'Workspace' if scope == 'user' else 'Global'

    return {
        'mode': 'custom',
        'valid': True,
        'endpoint_id': endpoint_id,
        'model_id': model_id,
        'provider': provider,
        'scope': scope,
        'label': f'{scope_prefix}: {endpoint_name} / {model_name}',
    }


def compute_next_run_at(workflow, from_time=None):
    """Return the next scheduled run timestamp for an interval workflow."""
    workflow = workflow if isinstance(workflow, dict) else {}
    if workflow.get('trigger_type') != 'interval' or not workflow.get('is_enabled', False):
        return None

    schedule = workflow.get('schedule') if isinstance(workflow.get('schedule'), dict) else {}
    if not schedule:
        return None

    reference_time = from_time or _utc_now()
    if isinstance(reference_time, str):
        reference_time = datetime.fromisoformat(reference_time)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    return (reference_time + _build_schedule_delta(schedule)).isoformat()


def get_personal_workflows(user_id):
    """Fetch all workflows for a user."""
    try:
        items = list(cosmos_personal_workflows_container.query_items(
            query='SELECT * FROM c WHERE c.user_id = @user_id',
            parameters=[{'name': '@user_id', 'value': user_id}],
            partition_key=user_id,
        ))
        cleaned = [_strip_cosmos_metadata(item) for item in items]
        cleaned.sort(key=lambda item: item.get('updated_at') or item.get('created_at') or '', reverse=True)
        return cleaned
    except exceptions.CosmosResourceNotFoundError:
        return []
    except Exception as exc:
        log_event(
            f'[WorkflowStore] Error fetching workflows for user {user_id}: {exc}',
            extra={'user_id': user_id},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return []


def get_personal_workflow(user_id, workflow_id):
    """Fetch a specific personal workflow."""
    try:
        workflow = cosmos_personal_workflows_container.read_item(item=workflow_id, partition_key=user_id)
        return _strip_cosmos_metadata(workflow)
    except exceptions.CosmosResourceNotFoundError:
        return None
    except Exception as exc:
        log_event(
            f'[WorkflowStore] Error fetching workflow {workflow_id}: {exc}',
            extra={'user_id': user_id, 'workflow_id': workflow_id},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return None


def get_due_personal_workflows(limit=20):
    """Return interval workflows whose next run timestamp is due."""
    now_iso = _utc_now_iso()
    try:
        items = list(cosmos_personal_workflows_container.query_items(
            query=(
                'SELECT * FROM c '
                'WHERE c.trigger_type = @trigger_type '
                'AND c.is_enabled = true '
                'AND IS_DEFINED(c.next_run_at) '
                'AND c.next_run_at != null '
                'AND c.next_run_at <= @now_iso'
            ),
            parameters=[
                {'name': '@trigger_type', 'value': 'interval'},
                {'name': '@now_iso', 'value': now_iso},
            ],
            enable_cross_partition_query=True,
        ))
        cleaned = [_strip_cosmos_metadata(item) for item in items]
        cleaned.sort(key=lambda item: item.get('next_run_at') or '')
        return cleaned[:limit]
    except Exception as exc:
        log_event(
            f'[WorkflowStore] Error fetching due workflows: {exc}',
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return []


def save_personal_workflow(user_id, workflow_data, actor_user_id=None):
    """Create or update a personal workflow."""
    workflow_data = workflow_data if isinstance(workflow_data, dict) else {}
    settings = get_settings()
    now_iso = _utc_now_iso()
    modifying_user_id = actor_user_id or user_id

    workflow_id = str(workflow_data.get('id') or '').strip()
    existing_workflow = get_personal_workflow(user_id, workflow_id) if workflow_id else None

    workflow_name = _normalize_text(workflow_data.get('name'), 'Workflow name', required=True)
    description = _normalize_text(workflow_data.get('description'), 'Description')
    task_prompt = _normalize_text(workflow_data.get('task_prompt'), 'Task prompt', required=True)
    runner_type = _normalize_text(workflow_data.get('runner_type'), 'Runner type', required=True).lower()
    if runner_type not in WORKFLOW_RUNNER_TYPES:
        raise ValueError('Runner type must be agent or model.')

    trigger_type = _normalize_text(workflow_data.get('trigger_type'), 'Trigger type', required=True).lower()
    if trigger_type not in WORKFLOW_TRIGGER_TYPES:
        raise ValueError('Trigger type must be manual or interval.')

    is_enabled = bool(workflow_data.get('is_enabled', existing_workflow.get('is_enabled', True) if existing_workflow else True))
    alert_priority = _normalize_alert_priority(
        workflow_data.get('alert_priority', (existing_workflow or {}).get('alert_priority', 'none'))
    )
    selected_agent = {}
    model_binding_summary = None
    model_endpoint_id = ''
    model_id = ''
    model_provider = ''

    if runner_type == 'agent':
        if not settings.get('enable_semantic_kernel', False):
            raise ValueError('Agents must be enabled before creating agent-based workflows.')
        if not settings.get('allow_user_agents', False):
            raise ValueError('User agents must be enabled before creating agent-based workflows.')
        selected_agent = _normalize_selected_agent(user_id, settings, workflow_data.get('selected_agent'))
    else:
        model_candidates = _build_model_endpoint_candidates(user_id, settings)
        model_endpoint_id = _normalize_text(workflow_data.get('model_endpoint_id'), 'Model endpoint')
        model_id = _normalize_text(workflow_data.get('model_id'), 'Model')
        if model_endpoint_id or model_id:
            model_binding_summary = _summarize_model_binding(model_candidates, model_endpoint_id, model_id)
            model_provider = str(model_binding_summary.get('provider') or '').strip().lower()
        else:
            model_binding_summary = _build_default_model_summary(settings)
            model_provider = str(model_binding_summary.get('provider') or '').strip().lower()

    schedule = {}
    if trigger_type == 'interval':
        schedule = _normalize_schedule(workflow_data.get('schedule'))

    workflow = {
        'id': workflow_id or str(uuid.uuid4()),
        'user_id': user_id,
        'name': workflow_name,
        'description': description,
        'task_prompt': task_prompt,
        'runner_type': runner_type,
        'trigger_type': trigger_type,
        'is_enabled': is_enabled,
        'alert_priority': alert_priority,
        'schedule': schedule,
        'selected_agent': selected_agent,
        'model_endpoint_id': model_endpoint_id,
        'model_id': model_id,
        'model_provider': model_provider,
        'model_binding_summary': model_binding_summary,
        'conversation_id': _normalize_text(
            workflow_data.get('conversation_id') or (existing_workflow or {}).get('conversation_id'),
            'Conversation id',
        ),
        'created_at': (existing_workflow or {}).get('created_at') or now_iso,
        'created_by': (existing_workflow or {}).get('created_by') or user_id,
        'modified_at': now_iso,
        'modified_by': modifying_user_id,
        'updated_at': now_iso,
        'status': (existing_workflow or {}).get('status') or 'idle',
        'last_run_started_at': (existing_workflow or {}).get('last_run_started_at'),
        'last_run_at': (existing_workflow or {}).get('last_run_at'),
        'last_run_status': (existing_workflow or {}).get('last_run_status'),
        'last_run_error': (existing_workflow or {}).get('last_run_error', ''),
        'last_run_response_preview': (existing_workflow or {}).get('last_run_response_preview', ''),
        'last_run_trigger_source': (existing_workflow or {}).get('last_run_trigger_source', ''),
        'run_count': int((existing_workflow or {}).get('run_count') or 0),
    }

    if trigger_type == 'interval' and is_enabled:
        schedule_changed = (
            not existing_workflow
            or existing_workflow.get('trigger_type') != 'interval'
            or not existing_workflow.get('is_enabled', False)
            or existing_workflow.get('schedule') != schedule
        )
        workflow['next_run_at'] = (existing_workflow or {}).get('next_run_at')
        if schedule_changed or not workflow.get('next_run_at'):
            workflow['next_run_at'] = compute_next_run_at(workflow)
    else:
        workflow['next_run_at'] = None

    result = cosmos_personal_workflows_container.upsert_item(body=workflow)
    cleaned_result = _strip_cosmos_metadata(result)
    debug_print(f"[WorkflowStore] Saved workflow {cleaned_result.get('id')} for user {user_id}")
    return cleaned_result


def update_personal_workflow_runtime_fields(user_id, workflow_id, updates):
    """Apply runtime fields such as status and last-run metadata."""
    updates = updates if isinstance(updates, dict) else {}
    workflow = get_personal_workflow(user_id, workflow_id)
    if not workflow:
        raise ValueError('Workflow not found.')

    workflow.update(updates)
    workflow['updated_at'] = _utc_now_iso()
    result = cosmos_personal_workflows_container.upsert_item(body=workflow)
    return _strip_cosmos_metadata(result)


def list_personal_workflow_runs(user_id, workflow_id, limit=25):
    """List recent workflow runs for a workflow."""
    try:
        items = list(cosmos_personal_workflow_runs_container.query_items(
            query=(
                'SELECT * FROM c '
                'WHERE c.user_id = @user_id AND c.workflow_id = @workflow_id '
                'ORDER BY c.started_at DESC'
            ),
            parameters=[
                {'name': '@user_id', 'value': user_id},
                {'name': '@workflow_id', 'value': workflow_id},
            ],
            partition_key=user_id,
        ))
        return [_strip_cosmos_metadata(item) for item in items[:limit]]
    except Exception as exc:
        log_event(
            f'[WorkflowStore] Error fetching workflow runs for {workflow_id}: {exc}',
            extra={'user_id': user_id, 'workflow_id': workflow_id},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return []


def get_personal_workflow_run(user_id, run_id):
    """Fetch a workflow run record by id."""
    try:
        item = cosmos_personal_workflow_runs_container.read_item(item=run_id, partition_key=user_id)
        return _strip_cosmos_metadata(item)
    except exceptions.CosmosResourceNotFoundError:
        return None
    except Exception as exc:
        log_event(
            f'[WorkflowStore] Error fetching workflow run {run_id}: {exc}',
            extra={'user_id': user_id, 'run_id': run_id},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return None


def get_latest_personal_workflow_run_for_conversation(user_id, conversation_id, workflow_id=None):
    """Return the latest run for a workflow conversation."""
    try:
        query = (
            'SELECT TOP 1 * FROM c '
            'WHERE c.user_id = @user_id AND c.conversation_id = @conversation_id '
        )
        parameters = [
            {'name': '@user_id', 'value': user_id},
            {'name': '@conversation_id', 'value': conversation_id},
        ]

        if str(workflow_id or '').strip():
            query += 'AND c.workflow_id = @workflow_id '
            parameters.append({'name': '@workflow_id', 'value': workflow_id})

        query += 'ORDER BY c.started_at DESC'

        items = list(cosmos_personal_workflow_runs_container.query_items(
            query=query,
            parameters=parameters,
            partition_key=user_id,
        ))
        if not items:
            return None
        return _strip_cosmos_metadata(items[0])
    except Exception as exc:
        log_event(
            f'[WorkflowStore] Error fetching latest run for conversation {conversation_id}: {exc}',
            extra={'user_id': user_id, 'conversation_id': conversation_id, 'workflow_id': workflow_id},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return None


def save_personal_workflow_run(user_id, run_record):
    """Create or update a workflow run record."""
    run_record = run_record if isinstance(run_record, dict) else {}
    run_record['user_id'] = user_id
    run_record.setdefault('id', str(uuid.uuid4()))
    result = cosmos_personal_workflow_runs_container.upsert_item(body=run_record)
    return _strip_cosmos_metadata(result)


def delete_personal_workflow(user_id, workflow_id):
    """Delete a workflow and its run history."""
    workflow = get_personal_workflow(user_id, workflow_id)
    if not workflow:
        return False

    cosmos_personal_workflows_container.delete_item(item=workflow_id, partition_key=user_id)

    runs = list_personal_workflow_runs(user_id, workflow_id, limit=500)
    for run in runs:
        try:
            cosmos_personal_workflow_runs_container.delete_item(item=run.get('id'), partition_key=user_id)
        except exceptions.CosmosResourceNotFoundError:
            continue
        except Exception as exc:
            log_event(
                f"[WorkflowStore] Error deleting workflow run {run.get('id')}: {exc}",
                extra={'user_id': user_id, 'workflow_id': workflow_id},
                level=logging.WARNING,
            )

    return True


def first_if_comma(val):
    """Return the first item from a comma-separated string."""
    if isinstance(val, str) and ',' in val:
        return val.split(',')[0].strip()
    return val