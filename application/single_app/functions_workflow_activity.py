# functions_workflow_activity.py

"""Helpers for building workflow activity timeline snapshots."""

from datetime import datetime, timezone


def _normalize_text(value):
    return str(value or '').strip()


def _coerce_datetime(value):
    normalized_value = _normalize_text(value)
    if not normalized_value:
        return None

    try:
        return datetime.fromisoformat(normalized_value.replace('Z', '+00:00'))
    except ValueError:
        return None


def _normalize_duration_ms(value):
    if value in (None, ''):
        return None

    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _normalize_status(value):
    normalized_value = _normalize_text(value).lower()
    if normalized_value in {'running', 'pending', 'in_progress', 'in-progress'}:
        return 'running'
    if normalized_value in {'failed', 'error', 'cancelled', 'canceled'}:
        return 'failed'
    if normalized_value in {'completed', 'complete', 'succeeded', 'success', 'done'}:
        return 'completed'
    if normalized_value:
        return normalized_value
    return 'completed'


def _serialize_workflow(workflow):
    if not isinstance(workflow, dict):
        return None

    return {
        'id': workflow.get('id'),
        'name': workflow.get('name'),
        'description': workflow.get('description'),
        'runner_type': workflow.get('runner_type'),
        'trigger_type': workflow.get('trigger_type'),
        'alert_priority': workflow.get('alert_priority'),
        'conversation_id': workflow.get('conversation_id'),
    }


def _serialize_conversation(conversation):
    if not isinstance(conversation, dict):
        return None

    return {
        'id': conversation.get('id'),
        'title': conversation.get('title'),
        'chat_type': conversation.get('chat_type'),
        'workflow_id': conversation.get('workflow_id'),
        'last_updated': conversation.get('last_updated'),
    }


def _serialize_run(run_record):
    if not isinstance(run_record, dict):
        return None

    return {
        'id': run_record.get('id'),
        'workflow_id': run_record.get('workflow_id'),
        'workflow_name': run_record.get('workflow_name'),
        'runner_type': run_record.get('runner_type'),
        'trigger_source': run_record.get('trigger_source'),
        'status': run_record.get('status'),
        'success': bool(run_record.get('success')),
        'started_at': run_record.get('started_at'),
        'completed_at': run_record.get('completed_at'),
        'conversation_id': run_record.get('conversation_id'),
        'user_message_id': run_record.get('user_message_id'),
        'assistant_message_id': run_record.get('assistant_message_id'),
        'model_deployment_name': run_record.get('model_deployment_name'),
        'agent_name': run_record.get('agent_name'),
        'agent_display_name': run_record.get('agent_display_name'),
        'response_preview': run_record.get('response_preview'),
        'error': run_record.get('error'),
    }


def _build_activity_event(thought, activity_payload):
    return {
        'thought_id': thought.get('id'),
        'step_index': thought.get('step_index'),
        'step_type': thought.get('step_type'),
        'state': _normalize_status(activity_payload.get('status') or activity_payload.get('state')),
        'content': thought.get('content'),
        'detail': thought.get('detail'),
        'timestamp': thought.get('timestamp'),
        'duration_ms': _normalize_duration_ms(thought.get('duration_ms')),
    }


def _initialize_activity_record(activity_key, thought, activity_payload, order_index):
    lane_key = _normalize_text(activity_payload.get('lane_key')) or 'main'
    lane_label = _normalize_text(activity_payload.get('lane_label')) or lane_key.replace('_', ' ').title()
    title = _normalize_text(activity_payload.get('title')) or _normalize_text(thought.get('content')) or 'Workflow activity'
    summary = _normalize_text(activity_payload.get('summary')) or _normalize_text(thought.get('content')) or title
    detail = _normalize_text(thought.get('detail')) or _normalize_text(activity_payload.get('detail'))
    status = _normalize_status(activity_payload.get('status') or activity_payload.get('state'))

    record = {
        'id': activity_key,
        'title': title,
        'summary': summary,
        'detail': detail,
        'kind': _normalize_text(activity_payload.get('kind')) or 'thought',
        'status': status,
        'lane_key': lane_key,
        'lane_label': lane_label,
        'plugin_name': _normalize_text(activity_payload.get('plugin_name')) or None,
        'function_name': _normalize_text(activity_payload.get('function_name')) or None,
        'run_id': _normalize_text(activity_payload.get('run_id')) or None,
        'workflow_id': _normalize_text(activity_payload.get('workflow_id')) or None,
        'started_at': thought.get('timestamp'),
        'completed_at': thought.get('timestamp') if status in {'completed', 'failed'} else None,
        'duration_ms': _normalize_duration_ms(thought.get('duration_ms')),
        'timestamp': thought.get('timestamp'),
        'step_index': thought.get('step_index'),
        'events': [],
        'order_index': order_index,
    }
    record['events'].append(_build_activity_event(thought, activity_payload))
    return record


def _merge_activity_record(record, thought, activity_payload):
    thought_timestamp = thought.get('timestamp')
    thought_datetime = _coerce_datetime(thought_timestamp)
    record_started_at = _coerce_datetime(record.get('started_at'))
    record_completed_at = _coerce_datetime(record.get('completed_at'))

    summary = _normalize_text(activity_payload.get('summary')) or _normalize_text(thought.get('content'))
    detail = _normalize_text(thought.get('detail')) or _normalize_text(activity_payload.get('detail'))
    status = _normalize_status(activity_payload.get('status') or activity_payload.get('state'))
    duration_ms = _normalize_duration_ms(thought.get('duration_ms'))

    if summary:
        record['summary'] = summary
    if detail:
        record['detail'] = detail
    if status:
        record['status'] = status
    if duration_ms is not None:
        record['duration_ms'] = duration_ms

    if thought_datetime and (record_started_at is None or thought_datetime < record_started_at):
        record['started_at'] = thought_timestamp
    if thought_datetime and status in {'completed', 'failed'}:
        if record_completed_at is None or thought_datetime >= record_completed_at:
            record['completed_at'] = thought_timestamp

    if thought.get('step_index') is not None:
        existing_index = record.get('step_index')
        if existing_index is None or thought.get('step_index') < existing_index:
            record['step_index'] = thought.get('step_index')

    record['timestamp'] = thought_timestamp or record.get('timestamp')
    record['events'].append(_build_activity_event(thought, activity_payload))


def _build_fallback_activity(run_record, workflow):
    workflow_name = _normalize_text((workflow or {}).get('name') or (run_record or {}).get('workflow_name')) or 'Workflow'
    run_status = _normalize_status((run_record or {}).get('status'))
    error_text = _normalize_text((run_record or {}).get('error'))
    response_preview = _normalize_text((run_record or {}).get('response_preview'))
    detail = error_text or response_preview or 'No structured activity was captured for this run.'

    return {
        'id': f"run:{_normalize_text((run_record or {}).get('id')) or 'unknown'}:fallback",
        'title': workflow_name,
        'summary': 'Workflow run summary',
        'detail': detail,
        'kind': 'workflow_run',
        'status': run_status or 'completed',
        'lane_key': 'main',
        'lane_label': 'Main',
        'plugin_name': None,
        'function_name': None,
        'run_id': _normalize_text((run_record or {}).get('id')) or None,
        'workflow_id': _normalize_text((run_record or {}).get('workflow_id')) or _normalize_text((workflow or {}).get('id')) or None,
        'started_at': (run_record or {}).get('started_at'),
        'completed_at': (run_record or {}).get('completed_at'),
        'duration_ms': None,
        'timestamp': (run_record or {}).get('completed_at') or (run_record or {}).get('started_at'),
        'step_index': 0,
        'lane_index': 0,
        'events': [],
    }


def build_workflow_activity_snapshot(run_record=None, workflow=None, conversation=None, thoughts=None):
    """Build a frontend-friendly workflow activity snapshot."""
    thoughts = thoughts if isinstance(thoughts, list) else []

    sorted_thoughts = sorted(
        thoughts,
        key=lambda thought: (
            _coerce_datetime(thought.get('timestamp')) or datetime.min.replace(tzinfo=timezone.utc),
            thought.get('step_index') if thought.get('step_index') is not None else 0,
        ),
    )

    activity_records = {}
    lane_order = []

    for order_index, thought in enumerate(sorted_thoughts):
        activity_payload = thought.get('activity') if isinstance(thought.get('activity'), dict) else {}
        activity_key = _normalize_text(activity_payload.get('activity_key')) or _normalize_text(thought.get('id')) or f'thought:{order_index}'
        lane_key = _normalize_text(activity_payload.get('lane_key')) or 'main'

        if lane_key not in lane_order:
            lane_order.append(lane_key)

        if activity_key not in activity_records:
            activity_records[activity_key] = _initialize_activity_record(activity_key, thought, activity_payload, order_index)
            continue

        _merge_activity_record(activity_records[activity_key], thought, activity_payload)

    activities = sorted(
        activity_records.values(),
        key=lambda activity: (
            activity.get('order_index', 0),
            _coerce_datetime(activity.get('started_at')) or datetime.max.replace(tzinfo=timezone.utc),
        ),
    )

    if not activities and isinstance(run_record, dict):
        activities = [_build_fallback_activity(run_record, workflow)]
        lane_order = ['main']

    for activity in activities:
        activity['lane_index'] = lane_order.index(activity.get('lane_key')) if activity.get('lane_key') in lane_order else 0
        activity.pop('order_index', None)

    return {
        'workflow': _serialize_workflow(workflow),
        'conversation': _serialize_conversation(conversation),
        'run': _serialize_run(run_record),
        'activities': activities,
        'lane_count': max(1, len(lane_order) or 1),
        'live': _normalize_status((run_record or {}).get('status')) == 'running',
    }