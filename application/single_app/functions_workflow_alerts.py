# functions_workflow_alerts.py

"""
Workflow alert rule evaluation.

Version: 0.250.213
Implemented in: 0.250.213

Workflow alerts used to fire on every run because a workflow carried a single
``alert_priority`` value. This module adds a rule engine so a workflow only
notifies when a declared condition is actually met, and so the severity of the
resulting notification reflects which condition matched.

The module deliberately avoids importing the workflow runner or the workflow
CRUD helpers so it can be shared by the personal save path, the group save path
and the runner without creating an import cycle. Model-evaluated conditions are
resolved through a caller-supplied callable rather than a direct model client
for the same reason.
"""

import json
import logging
import re
import uuid

from functions_appinsights import log_event


# Severity ladder, ordered from quietest to loudest.
WORKFLOW_ALERT_SEVERITY_ORDER = ('info', 'low', 'medium', 'high', 'critical')
WORKFLOW_ALERT_SEVERITIES = set(WORKFLOW_ALERT_SEVERITY_ORDER)
WORKFLOW_ALERT_DEFAULT_SEVERITY = 'medium'

WORKFLOW_ALERT_MODES = {'off', 'every_run', 'rules'}
WORKFLOW_ALERT_CATEGORIES = {'alert', 'failure'}
WORKFLOW_ALERT_DELIVERIES = {'default', 'notify_only', 'popup'}
WORKFLOW_ALERT_RESOLVED_DELIVERIES = {'notify_only', 'popup'}
WORKFLOW_ALERT_LEGACY_PRIORITIES = {'none', 'low', 'medium', 'high'}

# Quiet severities land in the notification bell; louder ones interrupt with the modal.
WORKFLOW_ALERT_SEVERITY_DELIVERY = {
    'info': 'notify_only',
    'low': 'notify_only',
    'medium': 'popup',
    'high': 'popup',
    'critical': 'popup',
}

WORKFLOW_ALERT_CONDITION_TYPES = {
    'run_status',
    'task_status',
    'text_match',
    'file_sync',
    'no_output',
    'model_evaluation',
    'agent_signal',
}
WORKFLOW_ALERT_RUN_STATUSES = {'completed', 'failed', 'cancelled', 'completed_with_task_errors'}
WORKFLOW_ALERT_TASK_STATUSES = {'succeeded', 'failed'}
WORKFLOW_ALERT_TEXT_MATCH_MODES = {'contains_any', 'contains_all', 'not_contains', 'regex'}
WORKFLOW_ALERT_FILE_SYNC_OUTCOMES = {'changes_found', 'no_changes', 'sync_failed'}
WORKFLOW_ALERT_SCOPE_TYPES = {'final', 'task', 'any_task'}
WORKFLOW_ALERT_EVALUATION_ERROR_MODES = {'skip', 'alert'}

# Conditions whose match means the run itself went wrong rather than the run
# finding something noteworthy.
WORKFLOW_ALERT_FAILURE_RUN_STATUSES = {'failed', 'completed_with_task_errors'}

WORKFLOW_ALERT_MAX_RULES = 20
WORKFLOW_ALERT_RULE_NAME_MAX_LENGTH = 120
WORKFLOW_ALERT_MAX_TEXT_VALUES = 25
WORKFLOW_ALERT_TEXT_VALUE_MAX_LENGTH = 400
WORKFLOW_ALERT_REGEX_MAX_LENGTH = 200
WORKFLOW_ALERT_EVALUATION_PROMPT_MAX_LENGTH = 2000
WORKFLOW_ALERT_EVALUATION_TEXT_LIMIT = 12000
WORKFLOW_ALERT_MATCH_TEXT_LIMIT = 20000
WORKFLOW_ALERT_REASON_MAX_LENGTH = 240

# Rejects the classic catastrophic-backtracking shape, a quantified group that
# itself contains a quantifier, such as ``(a+)+`` or ``(\d*)*``.
_NESTED_QUANTIFIER_PATTERN = re.compile(r'\([^)]*[*+][^)]*\)\s*[*+]')

WORKFLOW_ALERT_CONDITION_LABELS = {
    'run_status': 'Run status',
    'task_status': 'Task status',
    'text_match': 'Output text',
    'file_sync': 'File Sync result',
    'no_output': 'No output produced',
    'model_evaluation': 'Model evaluated condition',
    'agent_signal': 'Agent raised alert',
}


def normalize_alert_severity(value, default=WORKFLOW_ALERT_DEFAULT_SEVERITY):
    """Return a supported severity, falling back to the supplied default."""
    normalized = str(value or '').strip().lower()
    if normalized in WORKFLOW_ALERT_SEVERITIES:
        return normalized
    return default


def get_alert_severity_rank(severity):
    """Return the ordinal position of a severity so severities can be compared."""
    normalized = normalize_alert_severity(severity)
    return WORKFLOW_ALERT_SEVERITY_ORDER.index(normalized)


def get_default_alert_delivery(severity):
    """Return the delivery style a severity uses when the rule does not override it."""
    return WORKFLOW_ALERT_SEVERITY_DELIVERY.get(
        normalize_alert_severity(severity),
        'popup',
    )


def resolve_alert_delivery(severity, delivery):
    """Resolve a stored delivery value into ``notify_only`` or ``popup``."""
    normalized = str(delivery or 'default').strip().lower()
    if normalized in WORKFLOW_ALERT_RESOLVED_DELIVERIES:
        return normalized
    return get_default_alert_delivery(severity)


def _truncate(text, limit):
    normalized = str(text or '')
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + '…'


def _normalize_reason(text):
    return _truncate(' '.join(str(text or '').split()), WORKFLOW_ALERT_REASON_MAX_LENGTH)


def _normalize_legacy_alert_priority(value):
    normalized = str(value or 'none').strip().lower() or 'none'
    if normalized not in WORKFLOW_ALERT_LEGACY_PRIORITIES:
        raise ValueError('Alert priority must be none, low, medium, or high.')
    return normalized


def validate_alert_regex(pattern):
    """Compile a user supplied regex, rejecting oversized or backtracking-prone patterns."""
    normalized = str(pattern or '').strip()
    if not normalized:
        raise ValueError('Alert rule regex pattern is required.')
    if len(normalized) > WORKFLOW_ALERT_REGEX_MAX_LENGTH:
        raise ValueError(
            f'Alert rule regex pattern must be {WORKFLOW_ALERT_REGEX_MAX_LENGTH} characters or fewer.'
        )
    if _NESTED_QUANTIFIER_PATTERN.search(normalized):
        raise ValueError('Alert rule regex pattern uses nested quantifiers that are not allowed.')

    try:
        return re.compile(normalized, re.IGNORECASE | re.MULTILINE)
    except re.error as exc:
        raise ValueError(f'Alert rule regex pattern is invalid: {exc}') from exc


def _normalize_string_list(values, field_name, max_items, max_length):
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        raise ValueError(f'{field_name} must be a list of text values.')

    normalized_values = []
    for raw_value in values:
        normalized_value = str(raw_value or '').strip()
        if not normalized_value:
            continue
        if len(normalized_value) > max_length:
            raise ValueError(f'{field_name} entries must be {max_length} characters or fewer.')
        if normalized_value not in normalized_values:
            normalized_values.append(normalized_value)

    if not normalized_values:
        raise ValueError(f'{field_name} requires at least one value.')
    if len(normalized_values) > max_items:
        raise ValueError(f'{field_name} supports up to {max_items} values.')
    return normalized_values


def _normalize_status_list(values, field_name, allowed_statuses):
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        raise ValueError(f'{field_name} must be a list.')

    normalized_values = []
    for raw_value in values:
        normalized_value = str(raw_value or '').strip().lower()
        if not normalized_value:
            continue
        if normalized_value not in allowed_statuses:
            allowed_text = ', '.join(sorted(allowed_statuses))
            raise ValueError(f'{field_name} must be one of: {allowed_text}.')
        if normalized_value not in normalized_values:
            normalized_values.append(normalized_value)

    if not normalized_values:
        raise ValueError(f'{field_name} requires at least one value.')
    return normalized_values


def _normalize_alert_rule_scope(raw_scope, task_ids=None):
    raw_scope = raw_scope if isinstance(raw_scope, dict) else {}
    scope_type = str(raw_scope.get('type') or 'final').strip().lower() or 'final'
    if scope_type not in WORKFLOW_ALERT_SCOPE_TYPES:
        raise ValueError('Alert rule scope must be final, task, or any_task.')

    task_id = str(raw_scope.get('task_id') or '').strip()
    if scope_type != 'task':
        return {'type': scope_type, 'task_id': ''}

    if not task_id:
        raise ValueError('Alert rules scoped to a task must select a task.')
    if task_ids is not None and task_id not in set(task_ids):
        raise ValueError('Alert rule references a task that is not part of this workflow.')
    return {'type': scope_type, 'task_id': task_id}


def _normalize_alert_condition(raw_condition, task_ids=None):
    raw_condition = raw_condition if isinstance(raw_condition, dict) else {}
    condition_type = str(raw_condition.get('type') or '').strip().lower()
    if condition_type not in WORKFLOW_ALERT_CONDITION_TYPES:
        allowed_text = ', '.join(sorted(WORKFLOW_ALERT_CONDITION_TYPES))
        raise ValueError(f'Alert rule condition type must be one of: {allowed_text}.')

    if condition_type == 'run_status':
        return {
            'type': condition_type,
            'statuses': _normalize_status_list(
                raw_condition.get('statuses'),
                'Alert rule run statuses',
                WORKFLOW_ALERT_RUN_STATUSES,
            ),
        }

    if condition_type == 'task_status':
        return {
            'type': condition_type,
            'statuses': _normalize_status_list(
                raw_condition.get('statuses'),
                'Alert rule task statuses',
                WORKFLOW_ALERT_TASK_STATUSES,
            ),
        }

    if condition_type == 'text_match':
        match_mode = str(raw_condition.get('mode') or 'contains_any').strip().lower() or 'contains_any'
        if match_mode not in WORKFLOW_ALERT_TEXT_MATCH_MODES:
            raise ValueError('Alert rule text match mode must be contains_any, contains_all, not_contains, or regex.')

        if match_mode == 'regex':
            pattern = str(raw_condition.get('pattern') or '').strip()
            validate_alert_regex(pattern)
            return {
                'type': condition_type,
                'mode': match_mode,
                'pattern': pattern,
                'values': [],
                'case_sensitive': False,
            }

        return {
            'type': condition_type,
            'mode': match_mode,
            'pattern': '',
            'values': _normalize_string_list(
                raw_condition.get('values'),
                'Alert rule match values',
                WORKFLOW_ALERT_MAX_TEXT_VALUES,
                WORKFLOW_ALERT_TEXT_VALUE_MAX_LENGTH,
            ),
            'case_sensitive': bool(raw_condition.get('case_sensitive')),
        }

    if condition_type == 'file_sync':
        outcome = str(raw_condition.get('outcome') or '').strip().lower()
        if outcome not in WORKFLOW_ALERT_FILE_SYNC_OUTCOMES:
            raise ValueError('Alert rule File Sync outcome must be changes_found, no_changes, or sync_failed.')
        return {'type': condition_type, 'outcome': outcome}

    if condition_type == 'no_output':
        return {'type': condition_type}

    if condition_type == 'model_evaluation':
        prompt = str(raw_condition.get('prompt') or '').strip()
        if not prompt:
            raise ValueError('Alert rule model evaluation requires a condition to evaluate.')
        if len(prompt) > WORKFLOW_ALERT_EVALUATION_PROMPT_MAX_LENGTH:
            raise ValueError(
                f'Alert rule model evaluation condition must be '
                f'{WORKFLOW_ALERT_EVALUATION_PROMPT_MAX_LENGTH} characters or fewer.'
            )
        return {'type': condition_type, 'prompt': prompt}

    signal_name = str(raw_condition.get('signal_name') or '').strip()
    if len(signal_name) > WORKFLOW_ALERT_RULE_NAME_MAX_LENGTH:
        raise ValueError(
            f'Alert rule signal name must be {WORKFLOW_ALERT_RULE_NAME_MAX_LENGTH} characters or fewer.'
        )
    return {
        'type': condition_type,
        'signal_name': signal_name,
        'min_severity': normalize_alert_severity(raw_condition.get('min_severity'), default='info'),
    }


def describe_alert_condition(condition):
    """Return a short human readable description of a normalized condition."""
    condition = condition if isinstance(condition, dict) else {}
    condition_type = str(condition.get('type') or '').strip().lower()
    label = WORKFLOW_ALERT_CONDITION_LABELS.get(condition_type, 'Condition')

    if condition_type == 'run_status':
        return f"{label} is {', '.join(condition.get('statuses') or [])}"
    if condition_type == 'task_status':
        return f"{label} is {', '.join(condition.get('statuses') or [])}"
    if condition_type == 'text_match':
        if condition.get('mode') == 'regex':
            return f"{label} matches /{condition.get('pattern')}/"
        mode_labels = {
            'contains_any': 'contains any of',
            'contains_all': 'contains all of',
            'not_contains': 'does not contain',
        }
        mode_label = mode_labels.get(condition.get('mode'), 'contains')
        return f"{label} {mode_label} {', '.join(condition.get('values') or [])}"
    if condition_type == 'file_sync':
        return f"{label} is {condition.get('outcome')}"
    if condition_type == 'model_evaluation':
        return f"{label}: {condition.get('prompt')}"
    if condition_type == 'agent_signal':
        signal_name = condition.get('signal_name')
        if signal_name:
            return f"{label} named {signal_name}"
        return label
    return label


def normalize_alert_rule(raw_rule, task_ids=None, index=0):
    """Normalize and validate a single alert rule."""
    if not isinstance(raw_rule, dict):
        raise ValueError(f'Alert rule {index + 1} is invalid.')

    condition = _normalize_alert_condition(raw_rule.get('condition'), task_ids=task_ids)
    scope = _normalize_alert_rule_scope(raw_rule.get('scope'), task_ids=task_ids)

    name = str(raw_rule.get('name') or '').strip()
    if not name:
        name = describe_alert_condition(condition)
    if len(name) > WORKFLOW_ALERT_RULE_NAME_MAX_LENGTH:
        raise ValueError(
            f'Alert rule name must be {WORKFLOW_ALERT_RULE_NAME_MAX_LENGTH} characters or fewer.'
        )

    delivery = str(raw_rule.get('delivery') or 'default').strip().lower() or 'default'
    if delivery not in WORKFLOW_ALERT_DELIVERIES:
        raise ValueError('Alert rule delivery must be default, notify_only, or popup.')

    severity = str(raw_rule.get('severity') or WORKFLOW_ALERT_DEFAULT_SEVERITY).strip().lower()
    if severity not in WORKFLOW_ALERT_SEVERITIES:
        allowed_text = ', '.join(WORKFLOW_ALERT_SEVERITY_ORDER)
        raise ValueError(f'Alert rule severity must be one of: {allowed_text}.')

    enabled = raw_rule.get('enabled', True)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in {'1', 'true', 'yes', 'on'}

    return {
        'id': str(raw_rule.get('id') or '').strip() or str(uuid.uuid4()),
        'name': name,
        'enabled': bool(enabled),
        'severity': severity,
        'delivery': delivery,
        'scope': scope,
        'condition': condition,
        'order': index + 1,
    }


def normalize_alert_rules(raw_rules, task_ids=None):
    """Normalize a list of alert rules, enforcing the rule limit and unique ids."""
    if raw_rules is None:
        return []
    if not isinstance(raw_rules, list):
        raise ValueError('Alert rules must be a list.')
    if len(raw_rules) > WORKFLOW_ALERT_MAX_RULES:
        raise ValueError(f'Workflows support up to {WORKFLOW_ALERT_MAX_RULES} alert rules.')

    normalized_rules = []
    seen_rule_ids = set()
    for index, raw_rule in enumerate(raw_rules):
        normalized_rule = normalize_alert_rule(raw_rule, task_ids=task_ids, index=index)
        if normalized_rule['id'] in seen_rule_ids:
            normalized_rule['id'] = str(uuid.uuid4())
        seen_rule_ids.add(normalized_rule['id'])
        normalized_rules.append(normalized_rule)
    return normalized_rules


def _normalize_alert_evaluation(raw_evaluation):
    raw_evaluation = raw_evaluation if isinstance(raw_evaluation, dict) else {}
    on_error = str(raw_evaluation.get('on_error') or 'skip').strip().lower() or 'skip'
    if on_error not in WORKFLOW_ALERT_EVALUATION_ERROR_MODES:
        raise ValueError('Alert evaluation error handling must be skip or alert.')
    return {'on_error': on_error}


def build_legacy_alert_rules(alert_priority):
    """Build the editable rules that reproduce the legacy alert-on-every-run behavior.

    Legacy alerts always opened the modal regardless of priority, so the migrated
    rules pin ``delivery`` to ``popup`` instead of inheriting the severity default.
    """
    normalized_priority = _normalize_legacy_alert_priority(alert_priority)
    if normalized_priority == 'none':
        return []

    return [
        {
            'id': 'legacy-run-failed',
            'name': 'Run failed',
            'enabled': True,
            'severity': 'high',
            'delivery': 'popup',
            'scope': {'type': 'final', 'task_id': ''},
            'condition': {'type': 'run_status', 'statuses': ['failed']},
            'order': 1,
        },
        {
            'id': 'legacy-run-completed',
            'name': 'Run completed',
            'enabled': True,
            'severity': normalized_priority,
            'delivery': 'popup',
            'scope': {'type': 'final', 'task_id': ''},
            'condition': {'type': 'run_status', 'statuses': ['completed']},
            'order': 2,
        },
    ]


def resolve_workflow_alert_config(workflow):
    """Return the effective alert configuration for a workflow document.

    Workflows saved before alert rules existed only carry ``alert_priority``. They
    are migrated on read so they keep alerting exactly as before without needing a
    stored data migration.
    """
    workflow = workflow if isinstance(workflow, dict) else {}
    stored_rules = workflow.get('alert_rules') if isinstance(workflow.get('alert_rules'), list) else None
    stored_mode = str(workflow.get('alert_mode') or '').strip().lower()
    alert_priority = str(workflow.get('alert_priority') or 'none').strip().lower()
    if alert_priority not in WORKFLOW_ALERT_LEGACY_PRIORITIES:
        alert_priority = 'none'

    if stored_mode in WORKFLOW_ALERT_MODES:
        mode = stored_mode
        rules = stored_rules or []
    elif stored_rules:
        mode = 'rules'
        rules = stored_rules
    elif alert_priority != 'none':
        mode = 'rules'
        rules = build_legacy_alert_rules(alert_priority)
    else:
        mode = 'off'
        rules = []

    evaluation = workflow.get('alert_evaluation') if isinstance(workflow.get('alert_evaluation'), dict) else {}
    return {
        'alert_mode': mode,
        'alert_priority': alert_priority,
        'alert_rules': rules,
        'alert_evaluation': {
            'on_error': str(evaluation.get('on_error') or 'skip').strip().lower() or 'skip',
        },
    }


def normalize_workflow_alert_settings(workflow_data, existing_workflow=None, task_ids=None):
    """Normalize the alert fields for a workflow save request.

    Returns a dict with ``alert_mode``, ``alert_priority``, ``alert_rules`` and
    ``alert_evaluation`` ready to persist on the workflow document.
    """
    workflow_data = workflow_data if isinstance(workflow_data, dict) else {}
    existing_workflow = existing_workflow if isinstance(existing_workflow, dict) else {}
    existing_config = resolve_workflow_alert_config(existing_workflow)

    alert_priority = _normalize_legacy_alert_priority(
        workflow_data.get('alert_priority', existing_config.get('alert_priority', 'none'))
    )

    if 'alert_rules' in workflow_data:
        alert_rules = normalize_alert_rules(workflow_data.get('alert_rules'), task_ids=task_ids)
    else:
        alert_rules = normalize_alert_rules(existing_config.get('alert_rules'), task_ids=None)

    if 'alert_mode' in workflow_data:
        alert_mode = str(workflow_data.get('alert_mode') or '').strip().lower()
        if alert_mode not in WORKFLOW_ALERT_MODES:
            raise ValueError('Alert mode must be off, every_run, or rules.')
    elif 'alert_rules' in workflow_data:
        alert_mode = 'rules' if alert_rules else 'off'
    else:
        alert_mode = existing_config.get('alert_mode') or 'off'
        if alert_mode == 'off' and alert_priority != 'none' and not alert_rules:
            # Clients that predate alert rules only send alert_priority, so keep
            # them alerting by materializing the equivalent editable rules.
            alert_rules = normalize_alert_rules(build_legacy_alert_rules(alert_priority))
            alert_mode = 'rules'

    if alert_mode == 'rules' and not alert_rules:
        raise ValueError('Add at least one alert rule or choose a different alert mode.')
    if alert_mode == 'every_run' and alert_priority == 'none':
        raise ValueError('Select an alert priority or choose a different alert mode.')

    if 'alert_evaluation' in workflow_data:
        alert_evaluation = _normalize_alert_evaluation(workflow_data.get('alert_evaluation'))
    else:
        alert_evaluation = _normalize_alert_evaluation(existing_config.get('alert_evaluation'))

    return {
        'alert_mode': alert_mode,
        'alert_priority': alert_priority,
        'alert_rules': alert_rules,
        'alert_evaluation': alert_evaluation,
    }


def normalize_agent_alert_signal(raw_signal):
    """Normalize an alert signal raised by an agent during a workflow run."""
    raw_signal = raw_signal if isinstance(raw_signal, dict) else {}
    title = _truncate(' '.join(str(raw_signal.get('title') or '').split()), WORKFLOW_ALERT_RULE_NAME_MAX_LENGTH)
    return {
        'severity': normalize_alert_severity(raw_signal.get('severity'), default='medium'),
        'signal_name': str(raw_signal.get('signal_name') or '').strip(),
        'title': title,
        'reason': _normalize_reason(raw_signal.get('reason')),
    }


def build_workflow_alert_facts(workflow, run_record, execution_result=None):
    """Collect everything the rule engine needs from a finished run."""
    workflow = workflow if isinstance(workflow, dict) else {}
    run_record = run_record if isinstance(run_record, dict) else {}
    execution_result = execution_result if isinstance(execution_result, dict) else {}

    run_status = str(run_record.get('status') or '').strip().lower() or 'completed'
    task_results = execution_result.get('task_results')
    if not isinstance(task_results, list):
        task_results = run_record.get('task_results') if isinstance(run_record.get('task_results'), list) else []

    task_outputs = []
    for index, task_result in enumerate(task_results):
        if not isinstance(task_result, dict):
            continue
        task = task_result.get('task') if isinstance(task_result.get('task'), dict) else {}
        nested_result = task_result.get('result') if isinstance(task_result.get('result'), dict) else {}
        task_outputs.append({
            'task_id': str(task.get('id') or '').strip(),
            'task_name': str(task.get('name') or f'Task {index + 1}').strip(),
            'status': str(task_result.get('status') or '').strip().lower(),
            'output': str(nested_result.get('reply') or '').strip(),
            'error': str(task_result.get('error') or '').strip(),
        })

    try:
        task_error_count = int(execution_result.get('task_error_count') or run_record.get('task_error_count') or 0)
    except (TypeError, ValueError):
        task_error_count = 0
    if not task_error_count:
        task_error_count = sum(1 for item in task_outputs if item.get('status') == 'failed')

    effective_statuses = {run_status}
    if run_status == 'completed' and task_error_count:
        effective_statuses.add('completed_with_task_errors')

    file_sync = run_record.get('file_sync') if isinstance(run_record.get('file_sync'), dict) else {}
    if not file_sync and isinstance(execution_result.get('file_sync'), dict):
        file_sync = execution_result.get('file_sync')

    raw_signals = execution_result.get('agent_alert_signals')
    if not isinstance(raw_signals, list):
        raw_signals = []

    final_output = str(execution_result.get('reply') or run_record.get('response_preview') or '').strip()

    return {
        'workflow_id': str(workflow.get('id') or '').strip(),
        'workflow_name': str(workflow.get('name') or 'Workflow').strip() or 'Workflow',
        'run_status': run_status,
        'effective_run_statuses': effective_statuses,
        'success': bool(run_record.get('success')),
        'error': str(run_record.get('error') or '').strip(),
        'final_output': final_output,
        'task_outputs': task_outputs,
        'task_error_count': task_error_count,
        'file_sync': file_sync,
        'file_sync_outcome': _resolve_file_sync_outcome(file_sync),
        'agent_signals': [normalize_agent_alert_signal(signal) for signal in raw_signals],
        'trigger_source': str(run_record.get('trigger_source') or 'manual').strip() or 'manual',
    }


def _resolve_file_sync_outcome(file_sync):
    file_sync = file_sync if isinstance(file_sync, dict) else {}
    if not file_sync:
        return ''
    if file_sync.get('error') or str(file_sync.get('status') or '').strip().lower() == 'failed':
        return 'sync_failed'

    changed_documents = file_sync.get('changed_documents')
    changed_count = len(changed_documents) if isinstance(changed_documents, list) else 0
    if not changed_count:
        try:
            changed_count = int(file_sync.get('changed_document_count') or 0)
        except (TypeError, ValueError):
            changed_count = 0
    return 'changes_found' if changed_count else 'no_changes'


def _collect_scoped_texts(facts, scope):
    scope = scope if isinstance(scope, dict) else {}
    scope_type = str(scope.get('type') or 'final').strip().lower()
    task_outputs = facts.get('task_outputs') or []

    if scope_type == 'task':
        task_id = str(scope.get('task_id') or '').strip()
        return [
            (item.get('task_name') or 'Task', item.get('output') or '')
            for item in task_outputs
            if item.get('task_id') == task_id
        ]

    if scope_type == 'any_task':
        return [(item.get('task_name') or 'Task', item.get('output') or '') for item in task_outputs]

    return [('Final output', facts.get('final_output') or '')]


def _collect_scoped_tasks(facts, scope):
    scope = scope if isinstance(scope, dict) else {}
    scope_type = str(scope.get('type') or 'final').strip().lower()
    task_outputs = facts.get('task_outputs') or []
    if scope_type == 'task':
        task_id = str(scope.get('task_id') or '').strip()
        return [item for item in task_outputs if item.get('task_id') == task_id]
    return list(task_outputs)


def _evaluate_run_status_condition(condition, facts):
    statuses = set(condition.get('statuses') or [])
    matched_statuses = sorted(statuses & set(facts.get('effective_run_statuses') or set()))
    if not matched_statuses:
        return None

    category = 'failure' if set(matched_statuses) & WORKFLOW_ALERT_FAILURE_RUN_STATUSES else 'alert'
    return {
        'reason': f"Run status is {', '.join(matched_statuses)}",
        'category': category,
    }


def _evaluate_task_status_condition(condition, facts, scope):
    statuses = set(condition.get('statuses') or [])
    matched_tasks = [
        item for item in _collect_scoped_tasks(facts, scope)
        if item.get('status') in statuses
    ]
    if not matched_tasks:
        return None

    task_names = ', '.join(item.get('task_name') or 'Task' for item in matched_tasks[:3])
    matched_statuses = {item.get('status') for item in matched_tasks}
    return {
        'reason': f"Task status {', '.join(sorted(matched_statuses))} for {task_names}",
        'category': 'failure' if 'failed' in matched_statuses else 'alert',
    }


def _evaluate_text_match_condition(condition, facts, scope):
    candidates = [
        (label, _truncate(text, WORKFLOW_ALERT_MATCH_TEXT_LIMIT))
        for label, text in _collect_scoped_texts(facts, scope)
    ]
    candidates = [(label, text) for label, text in candidates if text]
    match_mode = str(condition.get('mode') or 'contains_any').strip().lower()

    if match_mode == 'regex':
        compiled_pattern = validate_alert_regex(condition.get('pattern'))
        for label, text in candidates:
            match = compiled_pattern.search(text)
            if match:
                return {
                    'reason': f"{label} matched pattern /{condition.get('pattern')}/",
                    'category': 'alert',
                }
        return None

    case_sensitive = bool(condition.get('case_sensitive'))
    values = list(condition.get('values') or [])
    comparison_values = values if case_sensitive else [value.lower() for value in values]

    if match_mode == 'not_contains':
        if not candidates:
            return {
                'reason': 'No output contained the configured text',
                'category': 'alert',
            }
        for _label, text in candidates:
            haystack = text if case_sensitive else text.lower()
            if any(value in haystack for value in comparison_values):
                return None
        return {
            'reason': f"No output contained {', '.join(values[:3])}",
            'category': 'alert',
        }

    for label, text in candidates:
        haystack = text if case_sensitive else text.lower()
        matched_values = [
            values[index] for index, value in enumerate(comparison_values) if value in haystack
        ]
        if match_mode == 'contains_all' and len(matched_values) != len(comparison_values):
            continue
        if not matched_values:
            continue
        return {
            'reason': f"{label} contains {', '.join(matched_values[:3])}",
            'category': 'alert',
        }
    return None


def _evaluate_file_sync_condition(condition, facts):
    outcome = str(condition.get('outcome') or '').strip().lower()
    if not outcome or outcome != facts.get('file_sync_outcome'):
        return None

    outcome_labels = {
        'changes_found': 'File Sync found changed documents',
        'no_changes': 'File Sync found no changed documents',
        'sync_failed': 'File Sync failed',
    }
    return {
        'reason': outcome_labels.get(outcome, 'File Sync condition met'),
        'category': 'failure' if outcome == 'sync_failed' else 'alert',
    }


def _evaluate_no_output_condition(facts, scope):
    candidates = _collect_scoped_texts(facts, scope)
    if any(str(text or '').strip() for _label, text in candidates):
        return None
    return {
        'reason': 'The run produced no output',
        'category': 'failure',
    }


def _evaluate_agent_signal_condition(condition, facts):
    signal_name = str(condition.get('signal_name') or '').strip().lower()
    min_rank = get_alert_severity_rank(condition.get('min_severity') or 'info')

    for signal in facts.get('agent_signals') or []:
        if signal_name and str(signal.get('signal_name') or '').strip().lower() != signal_name:
            continue
        if get_alert_severity_rank(signal.get('severity')) < min_rank:
            continue
        reason = signal.get('reason') or signal.get('title') or 'The agent raised an alert'
        return {
            'reason': reason,
            'category': 'alert',
            'severity_floor': signal.get('severity'),
        }
    return None


def _evaluate_deterministic_rule(rule, facts):
    condition = rule.get('condition') if isinstance(rule.get('condition'), dict) else {}
    condition_type = str(condition.get('type') or '').strip().lower()
    scope = rule.get('scope') if isinstance(rule.get('scope'), dict) else {}

    if condition_type == 'run_status':
        return _evaluate_run_status_condition(condition, facts)
    if condition_type == 'task_status':
        return _evaluate_task_status_condition(condition, facts, scope)
    if condition_type == 'text_match':
        return _evaluate_text_match_condition(condition, facts, scope)
    if condition_type == 'file_sync':
        return _evaluate_file_sync_condition(condition, facts)
    if condition_type == 'no_output':
        return _evaluate_no_output_condition(facts, scope)
    if condition_type == 'agent_signal':
        return _evaluate_agent_signal_condition(condition, facts)
    return None


def build_model_evaluation_prompt(rules, facts):
    """Build the single batched prompt used to judge all model-evaluated rules."""
    condition_lines = []
    for rule in rules:
        condition = rule.get('condition') if isinstance(rule.get('condition'), dict) else {}
        condition_lines.append(f"- rule_id: {rule.get('id')}\n  condition: {condition.get('prompt')}")

    scoped_sections = []
    for rule in rules:
        for label, text in _collect_scoped_texts(facts, rule.get('scope')):
            section = f'{label}:\n{text}'
            if text and section not in scoped_sections:
                scoped_sections.append(section)
    if not scoped_sections:
        scoped_sections.append('Final output:\n(no output was produced)')

    output_text = _truncate('\n\n'.join(scoped_sections), WORKFLOW_ALERT_EVALUATION_TEXT_LIMIT)

    return (
        'You are evaluating the output of an automated workflow run against alert conditions.\n'
        'Decide, for each condition, whether it is met by the workflow output below.\n'
        'Respond with ONLY a JSON object and no markdown, using exactly this shape:\n'
        '{"results": [{"rule_id": "<id>", "matched": true, "reason": "<one short sentence>"}]}\n\n'
        f"Workflow: {facts.get('workflow_name')}\n"
        f"Run status: {facts.get('run_status')}\n\n"
        '--- WORKFLOW OUTPUT ---\n'
        f'{output_text}\n'
        '--- END WORKFLOW OUTPUT ---\n\n'
        'Conditions:\n'
        f"{chr(10).join(condition_lines)}\n"
    )


def parse_model_evaluation_response(response_text):
    """Parse the JSON verdict payload returned for model-evaluated conditions."""
    normalized_text = str(response_text or '').strip()
    if not normalized_text:
        raise ValueError('Model evaluation returned an empty response.')

    try:
        payload = json.loads(normalized_text)
    except (TypeError, ValueError):
        start_index = normalized_text.find('{')
        end_index = normalized_text.rfind('}')
        if start_index == -1 or end_index <= start_index:
            raise ValueError('Model evaluation response was not valid JSON.')
        try:
            payload = json.loads(normalized_text[start_index:end_index + 1])
        except (TypeError, ValueError) as exc:
            raise ValueError('Model evaluation response was not valid JSON.') from exc

    if not isinstance(payload, dict):
        raise ValueError('Model evaluation response was not a JSON object.')

    raw_results = payload.get('results')
    if not isinstance(raw_results, list):
        raise ValueError('Model evaluation response did not include a results list.')

    verdicts = {}
    for raw_result in raw_results:
        if not isinstance(raw_result, dict):
            continue
        rule_id = str(raw_result.get('rule_id') or '').strip()
        if not rule_id:
            continue
        matched = raw_result.get('matched')
        if isinstance(matched, str):
            matched = matched.strip().lower() in {'1', 'true', 'yes'}
        verdicts[rule_id] = {
            'matched': bool(matched),
            'reason': _normalize_reason(raw_result.get('reason')),
        }
    return verdicts


def _build_match(rule, evaluation, source='rule'):
    severity = normalize_alert_severity(rule.get('severity'))
    severity_floor = evaluation.get('severity_floor')
    if severity_floor and get_alert_severity_rank(severity_floor) > get_alert_severity_rank(severity):
        severity = normalize_alert_severity(severity_floor)

    condition = rule.get('condition') if isinstance(rule.get('condition'), dict) else {}
    return {
        'rule_id': rule.get('id'),
        'rule_name': rule.get('name'),
        'severity': severity,
        'delivery': rule.get('delivery') or 'default',
        'condition_type': str(condition.get('type') or '').strip().lower(),
        'reason': _normalize_reason(evaluation.get('reason')),
        'category': evaluation.get('category') or 'alert',
        'order': rule.get('order') or 0,
        'source': source,
    }


def _build_decision(should_alert, mode, matches=None, model_evaluation=None, evaluated_rule_count=0):
    matches = list(matches or [])
    model_evaluation = model_evaluation or {'used': False, 'error': '', 'rule_ids': []}

    if not should_alert or not matches:
        return {
            'should_alert': False,
            'severity': '',
            'category': 'alert',
            'delivery': '',
            'mode': mode,
            'matched_rules': matches,
            'reasons': [match.get('reason') for match in matches if match.get('reason')],
            'evaluated_rule_count': evaluated_rule_count,
            'model_evaluation': model_evaluation,
        }

    matches.sort(key=lambda match: (-get_alert_severity_rank(match.get('severity')), match.get('order') or 0))
    winning_match = matches[0]
    severity = normalize_alert_severity(winning_match.get('severity'))

    return {
        'should_alert': True,
        'severity': severity,
        'category': winning_match.get('category') or 'alert',
        'delivery': resolve_alert_delivery(severity, winning_match.get('delivery')),
        'mode': mode,
        'winning_rule_id': winning_match.get('rule_id'),
        'winning_rule_name': winning_match.get('rule_name'),
        'matched_rules': matches,
        'reasons': [match.get('reason') for match in matches if match.get('reason')],
        'evaluated_rule_count': evaluated_rule_count,
        'model_evaluation': model_evaluation,
    }


def evaluate_workflow_alert_rules(workflow, facts, model_evaluator=None):
    """Decide whether a finished workflow run should raise an alert, and how loudly.

    ``model_evaluator`` is an optional callable taking the batched prompt text and
    returning the raw model response. It is injected so this module stays free of
    model client imports.
    """
    facts = facts if isinstance(facts, dict) else {}
    config = resolve_workflow_alert_config(workflow)
    mode = config.get('alert_mode')

    if mode == 'off':
        return _build_decision(False, mode)

    if mode == 'every_run':
        alert_priority = config.get('alert_priority')
        if alert_priority == 'none' or facts.get('run_status') == 'cancelled':
            return _build_decision(False, mode)

        severity = normalize_alert_severity(alert_priority)
        legacy_match = {
            'rule_id': 'every-run',
            'rule_name': 'Every run',
            'severity': severity,
            'delivery': 'popup',
            'condition_type': 'run_status',
            'reason': f"Workflow run {facts.get('run_status') or 'completed'}",
            'category': 'alert' if facts.get('success') else 'failure',
            'order': 1,
            'source': 'legacy',
        }
        return _build_decision(True, mode, matches=[legacy_match], evaluated_rule_count=1)

    enabled_rules = [
        rule for rule in (config.get('alert_rules') or [])
        if isinstance(rule, dict) and rule.get('enabled', True)
    ]
    if not enabled_rules:
        return _build_decision(False, mode)

    matches = []
    model_rules = []
    for rule in enabled_rules:
        condition = rule.get('condition') if isinstance(rule.get('condition'), dict) else {}
        if str(condition.get('type') or '').strip().lower() == 'model_evaluation':
            model_rules.append(rule)
            continue
        try:
            evaluation = _evaluate_deterministic_rule(rule, facts)
        except Exception as exc:
            log_event(
                f'[WORKFLOW_ALERTS] Alert rule evaluation failed: {exc}',
                extra={
                    'workflow_id': facts.get('workflow_id'),
                    'rule_id': rule.get('id'),
                },
                level=logging.WARNING,
                exceptionTraceback=True,
            )
            continue
        if evaluation:
            matches.append(_build_match(rule, evaluation))

    best_rank = max(
        (get_alert_severity_rank(match.get('severity')) for match in matches),
        default=-1,
    )
    # A model call cannot change the outcome when a deterministic rule already
    # matched at or above the severity of every remaining model-evaluated rule.
    pending_model_rules = [
        rule for rule in model_rules
        if get_alert_severity_rank(rule.get('severity')) > best_rank
    ]

    model_evaluation_state = {
        'used': False,
        'error': '',
        'rule_ids': [rule.get('id') for rule in pending_model_rules],
        'skipped_rule_ids': [
            rule.get('id') for rule in model_rules if rule not in pending_model_rules
        ],
    }

    if pending_model_rules and callable(model_evaluator):
        model_evaluation_state['used'] = True
        try:
            prompt = build_model_evaluation_prompt(pending_model_rules, facts)
            verdicts = parse_model_evaluation_response(model_evaluator(prompt))
            for rule in pending_model_rules:
                verdict = verdicts.get(rule.get('id')) or {}
                if verdict.get('matched'):
                    matches.append(_build_match(
                        rule,
                        {
                            'reason': verdict.get('reason') or rule.get('name'),
                            'category': 'alert',
                        },
                        source='model_evaluation',
                    ))
        except Exception as exc:
            model_evaluation_state['error'] = str(exc)
            log_event(
                f'[WORKFLOW_ALERTS] Model evaluated alert conditions could not be judged: {exc}',
                extra={'workflow_id': facts.get('workflow_id')},
                level=logging.WARNING,
                exceptionTraceback=True,
            )
            if config.get('alert_evaluation', {}).get('on_error') == 'alert':
                for rule in pending_model_rules:
                    matches.append(_build_match(
                        rule,
                        {
                            'reason': f'Alert condition could not be evaluated: {exc}',
                            'category': 'failure',
                        },
                        source='model_evaluation_error',
                    ))
    elif pending_model_rules:
        model_evaluation_state['error'] = 'No model evaluator was available for this run.'

    return _build_decision(
        bool(matches),
        mode,
        matches=matches,
        model_evaluation=model_evaluation_state,
        evaluated_rule_count=len(enabled_rules),
    )


def summarize_alert_decision(decision):
    """Return a short one line summary of an alert decision for logs and activity views."""
    decision = decision if isinstance(decision, dict) else {}
    if not decision.get('should_alert'):
        if decision.get('mode') == 'off':
            return 'Alerts are turned off for this workflow.'
        return 'No alert rule matched this run.'

    matched_names = [
        match.get('rule_name') for match in decision.get('matched_rules') or []
        if match.get('rule_name')
    ]
    severity = str(decision.get('severity') or '').upper()
    if matched_names:
        return f"{severity} alert triggered by: {', '.join(matched_names)}"
    return f'{severity} alert triggered.'
