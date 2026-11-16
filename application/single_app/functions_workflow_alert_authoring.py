# functions_workflow_alert_authoring.py
"""Closed, ID-free alert schemas shared by workflow AI authoring surfaces."""

from functions_workflow_alerts import (
    WORKFLOW_ALERT_DELIVERIES,
    WORKFLOW_ALERT_EVALUATION_PROMPT_MAX_LENGTH,
    WORKFLOW_ALERT_FILE_SYNC_OUTCOMES,
    WORKFLOW_ALERT_MAX_TEXT_VALUES,
    WORKFLOW_ALERT_REGEX_MAX_LENGTH,
    WORKFLOW_ALERT_RULE_NAME_MAX_LENGTH,
    WORKFLOW_ALERT_RUN_STATUSES,
    WORKFLOW_ALERT_SEVERITY_ORDER,
    WORKFLOW_ALERT_SIZE_ORDER,
    WORKFLOW_ALERT_SOUND_ORDER,
    WORKFLOW_ALERT_TASK_STATUSES,
    WORKFLOW_ALERT_TEXT_MATCH_MODES,
    WORKFLOW_ALERT_TEXT_VALUE_MAX_LENGTH,
)


def _text(limit, minimum=1):
    return {'type': 'string', 'minLength': minimum, 'maxLength': limit, **({'pattern': r'\S'} if minimum else {})}


def _values(options):
    return {'type': 'array', 'minItems': 1, 'maxItems': len(options), 'uniqueItems': True,
            'items': {'enum': sorted(options)}}


def alert_condition_schema(*, file_sync=True):
    """Native conditions without storage IDs or free-form fields."""
    variants = []
    fields = {
        'run_status': ({'statuses': _values(WORKFLOW_ALERT_RUN_STATUSES)}, ['statuses']),
        'task_status': ({'statuses': _values(WORKFLOW_ALERT_TASK_STATUSES)}, ['statuses']),
        'model_evaluation': ({'prompt': _text(WORKFLOW_ALERT_EVALUATION_PROMPT_MAX_LENGTH)}, ['prompt']),
        'agent_signal': ({
            'signal_name': _text(WORKFLOW_ALERT_RULE_NAME_MAX_LENGTH, 0),
            'min_severity': {'enum': list(WORKFLOW_ALERT_SEVERITY_ORDER)},
        }, []),
        'no_output': ({}, []),
    }
    if file_sync:
        fields['file_sync'] = ({'outcome': {'enum': sorted(WORKFLOW_ALERT_FILE_SYNC_OUTCOMES)}}, ['outcome'])
    for kind, (properties, required) in fields.items():
        variants.append({
            'type': 'object', 'additionalProperties': False, 'required': ['type', *required],
            'properties': {'type': {'const': kind}, **properties},
        })
    for mode in sorted(WORKFLOW_ALERT_TEXT_MATCH_MODES):
        properties = (
            {'pattern': _text(WORKFLOW_ALERT_REGEX_MAX_LENGTH)} if mode == 'regex' else {
                'values': {'type': 'array', 'minItems': 1, 'maxItems': WORKFLOW_ALERT_MAX_TEXT_VALUES,
                           'items': _text(WORKFLOW_ALERT_TEXT_VALUE_MAX_LENGTH)},
                'case_sensitive': {'type': 'boolean'},
            }
        )
        variants.append({
            'type': 'object', 'additionalProperties': False,
            'required': ['type', 'mode', 'pattern' if mode == 'regex' else 'values'],
            'properties': {'type': {'const': 'text_match'}, 'mode': {'const': mode}, **properties},
        })
    return {'oneOf': variants}


def alert_rule_properties(task_reference, *, file_sync=True):
    """Editable personal rule fields; the caller supplies its local task-reference schema."""
    return {
        'name': _text(WORKFLOW_ALERT_RULE_NAME_MAX_LENGTH, 0),
        'enabled': {'type': 'boolean'},
        'severity': {'enum': list(WORKFLOW_ALERT_SEVERITY_ORDER)},
        'delivery': {'enum': sorted(WORKFLOW_ALERT_DELIVERIES)},
        'require_acknowledgment': {'type': 'boolean'},
        'sound': {'enum': list(WORKFLOW_ALERT_SOUND_ORDER)},
        'size': {'enum': list(WORKFLOW_ALERT_SIZE_ORDER)},
        'scope': {
            'oneOf': [
                {'type': 'object', 'additionalProperties': False, 'required': ['type', 'task'],
                 'properties': {'type': {'const': 'task'}, 'task': task_reference}},
                {'type': 'object', 'additionalProperties': False, 'required': ['type'],
                 'properties': {'type': {'enum': ['final', 'any_task']}}},
            ],
        },
        'condition': alert_condition_schema(file_sync=file_sync),
    }
