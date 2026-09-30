# functions_workflow_assist_editor.py
"""
Python mirror of the V2 workflow editor logic the AI workflow assistant depends on.

Version: 0.261.208
Implemented in: 0.261.208

The assistant returns a candidate that the V2 editor applies with ``applyAssist``. To check that
candidate the way the editor and a save will, this module ports these pieces of ``application/v2_ui``:

* ``WORKFLOW_AUTHORED_FIELDS``, ``ASSIST_FORBIDDEN_FIELDS``, ``ASSIST_FORBIDDEN_TASK_FIELDS`` and
  ``workflowAssistViolation`` (``components/workflows/WorkflowAuthoringHistory.tsx``). The server keeps
  its own copy of the lists; test_workflow_assist_field_parity.py fails when the two drift.
* ``sameEditorValue`` (``lib/workspaceAuthoring.ts``), with ``Object.is`` semantics.
* ``normalizeWorkflowDefinition`` and ``workflowForSave`` for the personal scope (``lib/workflowEditor.ts``),
  which turn an editor draft into the payload a save posts, after a JSON round trip.
* The change keys and labels of ``diffWorkflowChanges`` (``lib/workflowChangeTracking.ts``), so each change
  the server reports names the key the editor's Jump to focuses.

Two deliberate differences. The flow of a structured workflow may not change at all, which is
stricter than the editor (it allows flow edits that keep every ID's meaning). And
``flowUnsupportedReason`` is not ported. The save's own validation refuses most of what it flags, but
not every publication format: ``pdf``, ``docx`` or ``xml``, for example, passes the save and not the
editor. No operation sets a publication, so only a draft that already has one is affected.

The editor keeps a non-string ``trigger_type``, reference ``scope_type`` or task runner ``type`` whose
``String()`` is an allowed value (``['interval']`` reads as ``'interval'``); this port treats any
non-string as unknown. The assistant refuses a draft carrying such a value before projecting it, so
the two never disagree. Numbers follow JSON's round trip (``strip_undefined``): whole numbers below
1e21 become ints, as they reach the save route.

It imports nothing from the application, so it loads cheaply in tests and in the assistant core.
"""

import copy
import decimal
import math
import re
import uuid


class _Undefined:
    """JavaScript's ``undefined``: a key that ``JSON.stringify`` drops."""

    __slots__ = ()

    def __repr__(self):
        return 'undefined'

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


UNDEFINED = _Undefined()
_ABSENT = object()


class WorkflowEditorProjectionError(ValueError):
    """The editor would refuse to save this draft; ``code`` is a stable reason."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Field lists (WorkflowAuthoringHistory.tsx)
# ---------------------------------------------------------------------------

WORKFLOW_ALERT_FIELDS = ('alert_priority', 'alert_mode', 'alert_rules', 'alert_evaluation')

WORKFLOW_AUTHORED_FIELDS = (
    'name', 'description', 'runner_type', 'selected_agent', 'model_endpoint_id', 'model_id',
    'chat_capabilities_enabled', 'trigger_type', 'schedule', 'is_enabled', 'error_handling', 'm365_run_as_user_id',
    'tasks', 'reference_inputs', 'durable_execution', 'flow', 'limits', 'file_sync', *WORKFLOW_ALERT_FIELDS,
)

ASSIST_FORBIDDEN_FIELDS = (
    'is_enabled', 'm365_run_as_user_id', 'definition_version', 'id', 'user_id', 'group_id', 'url_access_enabled',
)

ASSIST_FORBIDDEN_TASK_FIELDS = ('approval',)

_AUTHORED_FIELD_SET = frozenset(WORKFLOW_AUTHORED_FIELDS)
_FORBIDDEN_FIELD_SET = frozenset(ASSIST_FORBIDDEN_FIELDS)

# ---------------------------------------------------------------------------
# Editor constants (workflowEditor.ts, workflowSettings.ts, workflowAlerts.ts)
# ---------------------------------------------------------------------------

WORKFLOW_ALIAS_PATTERN = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}')
WORKFLOW_OUTPUT_KINDS = ('any', 'text', 'records', 'json', 'document_results')
WORKFLOW_INPUT_OUTPUTS = ('authoritative', 'text', 'records', 'json', 'documents')
WORKFLOW_TRIGGER_TYPES = ('manual', 'interval', 'file_sync')
WORKFLOW_REFERENCE_SCOPES = ('personal', 'group', 'public')
WORKFLOW_TASK_RUNNER_TYPES = ('inherit', 'agent', 'model')
WORKFLOW_SCHEDULE_UNITS = ('seconds', 'minutes', 'hours')
WORKFLOW_SCHEDULE_FREQUENCIES = ('daily', 'weekdays', 'weekly', 'monthly')
WORKFLOW_SCHEDULE_DAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
WORKFLOW_ALERT_MODES = ('off', 'every_run', 'rules')
WORKFLOW_ALERT_PRIORITIES = ('none', 'low', 'medium', 'high')
WORKFLOW_UNSUPPORTED_SCHEDULE_REASON = (
    'This workflow uses a schedule this editor does not support. Its original schedule has been retained '
    'and editing is disabled.'
)
WORKFLOW_UNSUPPORTED_TASKS_REASON = (
    'This workflow contains task configuration or bindings from an unsupported schema. Its original '
    'configuration has been retained and editing is disabled.'
)
FLOW_OUTPUT_KINDS = WORKFLOW_OUTPUT_KINDS

# JavaScript's String.prototype.trim() whitespace, which differs from Python's str.strip().
_JS_WHITESPACE = (
    '\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a'
    '\u2028\u2029\u202f\u205f\u3000\ufeff'
)
# ASCII digits only: in a str pattern ``\d`` also matches other Unicode digits, which JavaScript's
# ``Number()`` rejects.
_JS_DECIMAL = re.compile(r'[+-]?(?:[0-9]+\.?[0-9]*(?:[eE][+-]?[0-9]+)?|\.[0-9]+(?:[eE][+-]?[0-9]+)?)')
_JS_RADIX = re.compile(r'0([xXoObB])([0-9A-Fa-f]+)')
_JS_MAX_SAFE_INTEGER = 2 ** 53
# Number::toString writes whole numbers below 1e21 as plain digits, which Python's JSON reads as int.
_JS_EXPONENT_THRESHOLD = 1e21


# ---------------------------------------------------------------------------
# JavaScript value helpers
# ---------------------------------------------------------------------------

def _js_trim(value):
    return value.strip(_JS_WHITESPACE)


def js_trim(value):
    """JavaScript's ``String.prototype.trim()``."""
    return _js_trim(value)


def js_truthy(value):
    """Whether JavaScript treats a JSON value as true."""
    return _js_truthy(value)


def _text(value):
    return value if isinstance(value, str) else ''


def _nullish(value):
    return value is None or value is UNDEFINED


def _js_truthy(value):
    if _nullish(value) or value is False:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0 and not (isinstance(value, float) and math.isnan(value))
    if isinstance(value, str):
        return value != ''
    return True


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_js_integer(value):
    return _is_number(value) and (isinstance(value, int) or (math.isfinite(value) and value.is_integer()))


def _js_strict_equals(value, number):
    return _is_number(value) and value == number


def _js_double(number):
    """An integer as the double JavaScript holds: rounded past 2**53, and Infinity past the largest double."""
    if -_JS_MAX_SAFE_INTEGER <= number <= _JS_MAX_SAFE_INTEGER:
        return number
    try:
        return float(number)
    except OverflowError:
        return math.inf if number > 0 else -math.inf


def _js_number(value):
    """JavaScript's ``Number(value)`` for the JSON values a definition can hold."""
    if value is UNDEFINED:
        return math.nan
    if value is None:
        return 0
    if isinstance(value, bool):
        return 1 if value else 0
    if _is_number(value):
        return _js_double(value) if isinstance(value, int) else value
    if isinstance(value, str):
        text = _js_trim(value)
        if not text:
            return 0
        if text in ('Infinity', '+Infinity'):
            return math.inf
        if text == '-Infinity':
            return -math.inf
        if _JS_DECIMAL.fullmatch(text):
            return float(text)
        radix = _JS_RADIX.fullmatch(text)
        if radix:
            base = {'x': 16, 'o': 8, 'b': 2}[radix.group(1).lower()]
            try:
                return _js_double(int(radix.group(2), base))
            except ValueError:
                return math.nan
        return math.nan
    if isinstance(value, list):
        if not value:
            return 0
        if len(value) == 1:
            item = value[0]
            if _nullish(item):
                return 0
            if isinstance(item, (str, int, float)) or isinstance(item, list):
                return _js_number(item if isinstance(item, str) else _js_string(item))
        return math.nan
    return math.nan


def _js_string(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer() and math.isfinite(value):
            return str(int(value))
        return repr(value)
    if isinstance(value, list):
        return ','.join('' if _nullish(item) else _js_string(item) for item in value)
    if isinstance(value, str):
        return value
    return '[object Object]'


def _number_in_range(value, fallback, minimum, maximum):
    parsed = _js_number(value)
    if not math.isfinite(parsed):
        return fallback
    parsed = math.trunc(parsed)
    return int(min(maximum, max(minimum, parsed)))


def _object_is(left, right):
    if left is right:
        return True
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if _is_number(left) and _is_number(right):
        if isinstance(left, float) and math.isnan(left):
            return isinstance(right, float) and math.isnan(right)
        if left == 0 and right == 0:
            return math.copysign(1.0, left) == math.copysign(1.0, right)
        return left == right
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    return False


def same_editor_value(left, right):
    """``sameEditorValue``: deep equality of plain JSON values, with ``Object.is`` for primitives."""
    if _object_is(left, right):
        return True
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            same_editor_value(item, right[index]) for index, item in enumerate(left)
        )
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    return len(left) == len(right) and all(
        key in right and same_editor_value(value, right[key]) for key, value in left.items()
    )


def json_number(value):
    """A number as Python's JSON parser reads it after JavaScript's ``JSON.stringify``.

    JavaScript holds every number as a double and writes a whole number below 1e21 as plain
    digits (the shortest that round-trip), so it arrives as an int; ``-0`` arrives as ``0``, a
    non-finite number as null, and anything else as a float.
    """
    if isinstance(value, bool) or not _is_number(value):
        return value
    if isinstance(value, int):
        if -_JS_MAX_SAFE_INTEGER <= value <= _JS_MAX_SAFE_INTEGER:
            return value
        try:
            value = float(value)
        except OverflowError:
            return None
    if not math.isfinite(value):
        return None
    if value.is_integer() and abs(value) < _JS_EXPONENT_THRESHOLD:
        return int(decimal.Decimal(repr(value)))
    return value


def strip_undefined(value):
    """The value Python reads from ``JSON.stringify(value)``: ``JSON.parse`` of it, as the server sees it."""
    if isinstance(value, dict):
        return {key: strip_undefined(item) for key, item in value.items() if item is not UNDEFINED}
    if isinstance(value, list):
        return [None if item is UNDEFINED else strip_undefined(item) for item in value]
    return json_number(value)


# ---------------------------------------------------------------------------
# workflowAssistViolation
# ---------------------------------------------------------------------------

def _own(record, field):
    return record[field] if isinstance(record, dict) and field in record else _ABSENT


def _task_field_value(task, field):
    value = _own(task, field)
    return None if value is _ABSENT or _nullish(value) else value


def _tasks_by_id(workflow):
    result = {}
    tasks = workflow.get('tasks') if isinstance(workflow, dict) else None
    for task in tasks if isinstance(tasks, list) else []:
        if isinstance(task, dict) and isinstance(task.get('id'), str) and task['id'] not in result:
            result[task['id']] = task
    return result


def workflow_assist_violation(current, candidate):
    """Why a candidate may not be applied to ``current``, or '' when it may.

    Mirrors ``workflowAssistViolation``, returning its messages word for word. The structural
    identity rule is stricter here: the flow may not change at all.
    """
    if not isinstance(candidate, dict):
        return 'The assist candidate is not a workflow.'
    for field in dict.fromkeys([*current.keys(), *candidate.keys()]):
        if same_editor_value(_own(current, field), _own(candidate, field)):
            continue
        if field in _FORBIDDEN_FIELD_SET:
            return f'AI assist cannot change {field}. Change it yourself if it needs to change.'
        if field not in _AUTHORED_FIELD_SET:
            return f'AI assist cannot change {field}, which the workflow editor does not author.'
    before = _tasks_by_id(current)
    after = _tasks_by_id(candidate)
    for task_id in dict.fromkeys([*before.keys(), *after.keys()]):
        for field in ASSIST_FORBIDDEN_TASK_FIELDS:
            if not same_editor_value(
                _task_field_value(before.get(task_id), field), _task_field_value(after.get(task_id), field),
            ):
                return 'AI assist cannot add, change, or remove a task approval. Change approvals yourself.'
    if not same_editor_value(_own(current, 'flow'), _own(candidate, 'flow')):
        return 'AI assist cannot change the flow of a structured workflow. Change its blocks yourself.'
    return ''


# ---------------------------------------------------------------------------
# normalizeWorkflowDefinition and workflowForSave (personal scope)
# ---------------------------------------------------------------------------

def safe_workflow_alias(value, fallback='input'):
    """``safeWorkflowAlias``: a name the save accepts, derived from free text."""
    cleaned = _js_trim(_text(value))
    cleaned = re.sub(r'^[^A-Za-z]+', '', cleaned)
    cleaned = re.sub(r'[^A-Za-z0-9_-]+', '_', cleaned)[:64]
    if WORKFLOW_ALIAS_PATTERN.fullmatch(cleaned):
        return cleaned
    fallback_cleaned = re.sub(r'^[^A-Za-z]+', '', fallback)
    fallback_cleaned = re.sub(r'[^A-Za-z0-9_-]+', '_', fallback_cleaned)[:64]
    return fallback_cleaned if WORKFLOW_ALIAS_PATTERN.fullmatch(fallback_cleaned) else 'input'


def _agent_reference(value):
    if not isinstance(value, dict) or not isinstance(value.get('id'), str) or not value['id']:
        return UNDEFINED
    return {
        'id': value['id'],
        'name': _text(value.get('name')),
        'display_name': _text(value.get('display_name')) or UNDEFINED,
        'is_global': value.get('is_global') is True,
        'is_group': value.get('is_group') is True,
        'group_id': _text(value.get('group_id')) or UNDEFINED,
    }


def _output_kind(value, fallback):
    return value if isinstance(value, str) and value in WORKFLOW_OUTPUT_KINDS else fallback


def is_flow_binding(value):
    """``isFlowBinding``: an input a structured task may carry."""
    if not isinstance(value, dict) or not isinstance(value.get('source'), dict):
        return False
    source = value['source']
    if source.get('scope') != 'current' or not isinstance(value.get('name'), str):
        return False
    kind = source.get('kind')
    expected_kind = value.get('expected_kind')
    if kind == 'node_output':
        source_ok = isinstance(source.get('node_id'), str) and isinstance(source.get('output'), str)
    elif kind == 'loop_item':
        source_ok = isinstance(source.get('loop_id'), str) and expected_kind in ('json', 'any')
    elif kind == 'repeat_state':
        source_ok = isinstance(source.get('loop_id'), str) and isinstance(source.get('state_name'), str)
    else:
        source_ok = False
    return (
        source_ok
        and isinstance(value.get('required'), bool)
        and isinstance(value.get('allow_partial'), bool)
        and isinstance(expected_kind, str) and expected_kind in FLOW_OUTPUT_KINDS
    )


def _normalize_runner(value, structured=False):
    if not isinstance(value, dict):
        return {'type': 'inherit'}
    runner_type = value.get('type')
    result = dict(value) if structured else {}
    result['type'] = runner_type if isinstance(runner_type, str) and runner_type in WORKFLOW_TASK_RUNNER_TYPES else 'inherit'
    result['selected_agent'] = _agent_reference(value.get('selected_agent'))
    result['model_endpoint_id'] = _text(value.get('model_endpoint_id'))
    result['model_id'] = _text(value.get('model_id'))
    return result


def _normalize_output_contract(value):
    if not isinstance(value, dict):
        return UNDEFINED
    expected = value.get('expected_count', UNDEFINED)
    expected = UNDEFINED if _nullish(expected) or expected == '' else _js_number(expected)
    identity_field = _js_trim(_text(value.get('identity_field')))
    result = {'kind': _output_kind(value.get('kind'), 'any')}
    if isinstance(value.get('schema'), dict):
        result['schema'] = value['schema']
    if expected is not UNDEFINED:
        result['expected_count'] = expected
    if identity_field:
        result['identity_field'] = identity_field
    result['require_complete_coverage'] = value.get('require_complete_coverage') is True
    result['allow_partial'] = value.get('allow_partial') is True
    return result


def _normalize_inputs(value, structured=False):
    if structured:
        if value is UNDEFINED:
            return []
        if not isinstance(value, list) or not all(is_flow_binding(entry) for entry in value):
            raise WorkflowEditorProjectionError(
                'workflow_read_only',
                'This structured workflow contains unsupported input bindings. Its saved definition was not changed.',
            )
        return copy.deepcopy(value)
    if not isinstance(value, list):
        return UNDEFINED
    return [
        {
            'name': safe_workflow_alias(entry.get('name'), 'input'),
            'task_id': _text(entry.get('task_id')),
            'output': entry['output'] if isinstance(entry.get('output'), str) and entry['output'] in WORKFLOW_INPUT_OUTPUTS else 'text',
            'required': entry.get('required') is not False,
            'expected_kind': _output_kind(entry.get('expected_kind'), 'any'),
        }
        for entry in value
        if isinstance(entry, dict)
    ]


def _normalize_approval(value):
    if not isinstance(value, dict):
        return UNDEFINED
    message = _text(value.get('message'))
    result = {'required': value.get('required') is True}
    if message:
        result['message'] = message
    return result


def _new_id():
    return str(uuid.uuid4())


def _normalize_task(value, index, structured=False):
    record = value if isinstance(value, dict) else {}
    raw_inputs = record.get('inputs', UNDEFINED)
    unsupported_inputs = structured and raw_inputs is not UNDEFINED and (
        not isinstance(raw_inputs, list) or not all(is_flow_binding(entry) for entry in raw_inputs)
    )
    runner = record.get('runner', UNDEFINED)
    output_contract = record.get('output_contract', UNDEFINED)
    unsupported_configuration = structured and (
        (record.get('type', UNDEFINED) is not UNDEFINED and record.get('type') != 'instructions')
        or (runner is not UNDEFINED and (
            not isinstance(runner, dict)
            or not (isinstance(runner.get('type'), str) and runner['type'] in WORKFLOW_TASK_RUNNER_TYPES)
        ))
        or (not _nullish(output_contract) and (
            not isinstance(output_contract, dict)
            or not (isinstance(output_contract.get('kind'), str) and output_contract['kind'] in WORKFLOW_OUTPUT_KINDS)
        ))
    )
    if structured or ('inputs' in record and record['inputs'] is not None):
        if unsupported_inputs:
            inputs = []
        else:
            inputs = _normalize_inputs(raw_inputs, structured)
            inputs = [] if inputs is UNDEFINED else inputs
    else:
        inputs = UNDEFINED
    reference_ids = record.get('reference_ids')
    reference_ids = [item for item in reference_ids if isinstance(item, str)] if isinstance(reference_ids, list) else UNDEFINED
    normalized_contract = _normalize_output_contract(output_contract)
    approval = _normalize_approval(record['approval']) if 'approval' in record else UNDEFINED

    result = dict(record)
    result['id'] = _text(record.get('id')) or _new_id()
    result['type'] = 'instructions'
    result['name'] = _text(record.get('name')) or f'Task {index + 1}'
    result['instructions'] = _text(record.get('instructions'))
    result['order'] = index + 1
    result['runner'] = _normalize_runner(runner, structured)
    if unsupported_inputs:
        result['unrecognized_inputs'] = copy.deepcopy(raw_inputs)
    if unsupported_configuration:
        result['unrecognized_configuration'] = copy.deepcopy(record)
    result['document_action'] = record['document_action'] if isinstance(record.get('document_action'), dict) else UNDEFINED
    if inputs is not UNDEFINED:
        result['inputs'] = inputs
    if reference_ids is not UNDEFINED:
        result['reference_ids'] = reference_ids
    if normalized_contract is not UNDEFINED:
        result['output_contract'] = (
            {**output_contract, **normalized_contract}
            if structured and isinstance(output_contract, dict) else normalized_contract
        )
    if approval is not UNDEFINED:
        result['approval'] = approval
    return result


def _legacy_workflow_task(record):
    prompt = _text(record.get('task_prompt'))
    if not prompt:
        return None
    task = {
        'id': _text(record.get('task_id')) or _new_id(),
        'type': 'instructions',
        'name': _text(record.get('task_name')) or 'Task 1',
        'instructions': prompt,
        'order': 1,
        'runner': {'type': 'inherit'},
    }
    if isinstance(record.get('document_action'), dict):
        task['document_action'] = record['document_action']
    return task


def create_workflow_task(index):
    """``createWorkflowTask``."""
    return {
        'id': _new_id(), 'type': 'instructions', 'name': f'Task {index + 1}', 'instructions': '',
        'order': index + 1, 'runner': {'type': 'inherit'},
    }


def new_workflow_definition():
    """``newWorkflowDefinition`` for the personal scope."""
    return {
        'definition_version': 2,
        'durable_execution': True,
        'name': '',
        'description': '',
        'runner_type': 'model',
        'model_endpoint_id': '',
        'model_id': '',
        'm365_run_as_user_id': '',
        'chat_capabilities_enabled': False,
        'trigger_type': 'manual',
        'schedule': {'unit': 'minutes', 'value': 15},
        'is_enabled': True,
        'error_handling': {'strategy': 'halt', 'retry_count': 0},
        'tasks': [create_workflow_task(0)],
        'reference_inputs': [],
    }


def _calendar_days(sent):
    if not isinstance(sent, list):
        return None
    selected = set()
    for day in sent:
        name = day.strip().lower() if isinstance(day, str) else ''
        if name not in WORKFLOW_SCHEDULE_DAYS:
            return None
        selected.add(name)
    return [day for day in WORKFLOW_SCHEDULE_DAYS if day in selected]


def workflow_schedule_for_editor(raw):
    """``workflowScheduleForEditor``: the schedule the editor shows and saves, or None."""
    schedule = raw if isinstance(raw, dict) else {}
    kind = str(schedule.get('kind') or 'interval').strip().lower()
    if kind == 'interval':
        unit = str(schedule.get('unit') or '').strip().lower()
        value = schedule.get('value')
        if unit not in WORKFLOW_SCHEDULE_UNITS or (unit != 'hours' and schedule.get('unit') != unit):
            return None
        if not _is_js_integer(value):
            return None
        return {'unit': unit, 'value': value}
    if kind != 'calendar':
        return None
    frequency = str(schedule.get('frequency') or '').strip().lower()
    if frequency not in WORKFLOW_SCHEDULE_FREQUENCIES:
        return None
    sent_days = schedule.get('days_of_week')
    days = _calendar_days([] if sent_days is None else sent_days) if frequency == 'weekly' else []
    if days is None:
        return None
    day_of_month = schedule.get('day_of_month')
    return {
        'kind': 'calendar',
        'frequency': frequency,
        'days_of_week': days,
        'day_of_month': day_of_month if frequency == 'monthly' and _is_js_integer(day_of_month) else None,
        'time_of_day': schedule['time_of_day'].strip() if isinstance(schedule.get('time_of_day'), str) else '',
        'timezone': schedule['timezone'].strip() if isinstance(schedule.get('timezone'), str) else '',
    }


def normalize_workflow_definition(value):
    """``normalizeWorkflowDefinition`` for the personal scope; keys may hold ``UNDEFINED``."""
    record = value if isinstance(value, dict) else {}
    revision = _text(record.get('definition_revision'))
    error_handling = record['error_handling'] if isinstance(record.get('error_handling'), dict) else {}
    trigger = record.get('trigger_type')
    trigger = trigger if isinstance(trigger, str) and trigger in WORKFLOW_TRIGGER_TYPES else 'manual'
    structured = _js_strict_equals(record.get('definition_version'), 3)
    raw_tasks = record['tasks'] if isinstance(record.get('tasks'), list) else []
    tasks = [_normalize_task(task, index, structured) for index, task in enumerate(raw_tasks)]
    references = []
    for entry in record['reference_inputs'] if isinstance(record.get('reference_inputs'), list) else []:
        if not isinstance(entry, dict):
            continue
        document_id = _text(entry.get('document_id'))
        scope_type = entry.get('scope_type')
        reference = {
            'id': _text(entry.get('id')) or _new_id(),
            'name': safe_workflow_alias(entry.get('name'), f"ref_{document_id or 'document'}"),
            'document_id': document_id,
            'scope_type': scope_type if isinstance(scope_type, str) and scope_type in WORKFLOW_REFERENCE_SCOPES else 'personal',
            'scope_id': _text(entry.get('scope_id')) or '',
        }
        if reference['document_id']:
            references.append(reference)
    unsupported_schedule = trigger != 'manual' and workflow_schedule_for_editor(record.get('schedule')) is None
    if structured and any('unrecognized_inputs' in task or 'unrecognized_configuration' in task for task in tasks):
        readonly_reason = WORKFLOW_UNSUPPORTED_TASKS_REASON
    elif unsupported_schedule:
        readonly_reason = WORKFLOW_UNSUPPORTED_SCHEDULE_REASON
    else:
        readonly_reason = ''

    result = dict(record)
    result['definition_version'] = _number_in_range(record.get('definition_version', UNDEFINED), 2, 1, 999)
    if revision:
        result['definition_revision'] = revision
    result['id'] = _text(record.get('id')) or UNDEFINED
    result['name'] = _text(record.get('name'))
    result['description'] = _text(record.get('description'))
    result['runner_type'] = 'agent' if record.get('runner_type') == 'agent' else 'model'
    result['selected_agent'] = _agent_reference(record.get('selected_agent'))
    result['model_endpoint_id'] = _text(record.get('model_endpoint_id'))
    result['model_id'] = _text(record.get('model_id'))
    result['m365_run_as_user_id'] = _text(record.get('m365_run_as_user_id'))
    result['chat_capabilities_enabled'] = record.get('chat_capabilities_enabled') is True
    result['trigger_type'] = trigger
    if unsupported_schedule:
        result['schedule'] = copy.deepcopy(record.get('schedule', UNDEFINED))
    else:
        result['schedule'] = workflow_schedule_for_editor(record.get('schedule')) or {'unit': 'minutes', 'value': 15}
    result['is_enabled'] = record.get('is_enabled') is not False
    result['error_handling'] = {
        'strategy': 'continue' if error_handling.get('strategy') == 'continue' else 'halt',
        'retry_count': _number_in_range(error_handling.get('retry_count', UNDEFINED), 0, 0, 5),
    }
    result['tasks'] = tasks or [_legacy_workflow_task(record) or create_workflow_task(0)]
    result['reference_inputs'] = references
    if readonly_reason:
        result['editor_readonly_reason'] = readonly_reason
    if 'durable_execution' in record:
        result['durable_execution'] = record['durable_execution'] is True
    return result


def _stored_alert_fields(workflow):
    record = workflow if isinstance(workflow, dict) else {}
    return {field: record[field] for field in WORKFLOW_ALERT_FIELDS if field in record}


def workflow_alerts_for_save(draft, original):
    """``workflowAlertsForSave``: the draft's alert fields only when they differ from the loaded ones."""
    loaded = _stored_alert_fields(original)
    drafted = _stored_alert_fields(draft)
    if same_editor_value(loaded, drafted):
        return {}
    return copy.deepcopy(drafted)


def workflow_for_save(draft, original):
    """``workflowForSave`` for the personal scope, as the JSON the save route receives.

    ``draft`` is the editor draft after a JSON round trip, and ``original`` is the stored record
    normalized as the editor loads it (``normalize_workflow_definition``), or None for a new draft.
    Raises ``WorkflowEditorProjectionError`` where the editor refuses to save.
    """
    if _js_truthy(draft.get('editor_readonly_reason')):
        raise WorkflowEditorProjectionError(
            'workflow_read_only',
            'This workflow contains unsupported executable fields and cannot be saved by this editor.',
        )
    draft_version = draft.get('definition_version')
    if original is not None and original['definition_version'] >= 3 and (
        not _is_number(draft_version) or draft_version < original['definition_version']
    ):
        raise WorkflowEditorProjectionError(
            'workflow_read_only', 'This workflow cannot be downgraded without losing executable fields.',
        )
    base = copy.deepcopy(original) if original is not None else new_workflow_definition()
    original_has_durable = 'durable_execution' in original if original is not None else False
    include_durable = original is None or original_has_durable or draft.get('durable_execution') is True
    runner_type = draft.get('runner_type', UNDEFINED)
    original_id = original.get('id', UNDEFINED) if original is not None else UNDEFINED
    run_as = draft.get('m365_run_as_user_id', UNDEFINED)
    if _nullish(run_as):
        run_as = original.get('m365_run_as_user_id', UNDEFINED) if original is not None else UNDEFINED
    tasks = draft.get('tasks') or []
    structured = _js_strict_equals(draft_version, 3)

    next_record = dict(base)
    next_record['id'] = draft.get('id', UNDEFINED) if _nullish(original_id) else original_id
    next_record['definition_version'] = 3 if structured else 2
    next_record['definition_revision'] = (
        original.get('definition_revision', UNDEFINED) if original is not None else UNDEFINED
    )
    next_record['name'] = _js_trim(draft['name'])
    next_record['description'] = _js_trim(draft['description'])
    next_record['runner_type'] = runner_type
    next_record['selected_agent'] = (
        draft['selected_agent'] if runner_type == 'agent' and _js_truthy(draft.get('selected_agent')) else UNDEFINED
    )
    for field in ('model_endpoint_id', 'model_id'):
        value = draft.get(field, UNDEFINED)
        next_record[field] = (value if _js_truthy(value) else '') if runner_type == 'model' else ''
    next_record['m365_run_as_user_id'] = _text(run_as)
    for field in ('chat_capabilities_enabled', 'trigger_type', 'schedule', 'is_enabled', 'error_handling'):
        next_record[field] = draft.get(field, UNDEFINED)
    next_record['tasks'] = [{**task, 'order': index + 1} for index, task in enumerate(tasks)]
    next_record['task_prompt'] = _js_trim(tasks[0]['instructions']) if tasks else ''
    next_record['reference_inputs'] = draft.get('reference_inputs', UNDEFINED)
    if structured:
        next_record['flow'] = copy.deepcopy(draft.get('flow', UNDEFINED))
        next_record['limits'] = copy.deepcopy(draft.get('limits', UNDEFINED))
    if include_durable:
        next_record['durable_execution'] = draft.get('durable_execution') is True
    next_record.update(workflow_alerts_for_save(draft, original))
    if not include_durable:
        next_record.pop('durable_execution', None)
    return strip_undefined(normalize_workflow_definition(next_record))


def editor_original(stored_editor_record):
    """The ``original`` the editor holds for a stored record: its normalized form."""
    if stored_editor_record is None:
        return None
    return normalize_workflow_definition(copy.deepcopy(stored_editor_record))


# ---------------------------------------------------------------------------
# workflowAlertConfig (workflowAlerts.ts)
# ---------------------------------------------------------------------------

def workflow_legacy_alert_rules(priority):
    if priority not in WORKFLOW_ALERT_PRIORITIES or priority == 'none':
        return []
    return [
        {
            'id': 'legacy-run-failed', 'name': 'Run failed', 'enabled': True, 'severity': 'high', 'delivery': 'popup',
            'scope': {'type': 'final', 'task_id': ''}, 'condition': {'type': 'run_status', 'statuses': ['failed']},
            'order': 1,
        },
        {
            'id': 'legacy-run-completed', 'name': 'Run completed', 'enabled': True, 'severity': priority,
            'delivery': 'popup', 'scope': {'type': 'final', 'task_id': ''},
            'condition': {'type': 'run_status', 'statuses': ['completed']}, 'order': 2,
        },
    ]


def workflow_alert_config(workflow):
    """``workflowAlertConfig``: the four alert fields the editor edits for a draft."""
    record = workflow if isinstance(workflow, dict) else {}
    stored_rules = record['alert_rules'] if isinstance(record.get('alert_rules'), list) else None
    stored_mode = str(record.get('alert_mode') or '').strip().lower()
    stored_priority = str(record.get('alert_priority') or 'none').strip().lower()
    priority = stored_priority if stored_priority in WORKFLOW_ALERT_PRIORITIES else 'none'
    evaluation = record['alert_evaluation'] if isinstance(record.get('alert_evaluation'), dict) else {}
    on_error = str(evaluation.get('on_error') or 'skip').strip().lower() or 'skip'

    def settings(mode, rules):
        return {
            'alert_mode': mode, 'alert_priority': priority, 'alert_rules': rules,
            'alert_evaluation': {**evaluation, 'on_error': on_error},
        }

    if stored_mode in WORKFLOW_ALERT_MODES:
        return settings(stored_mode, stored_rules if stored_rules is not None else [])
    if stored_rules:
        return settings('rules', stored_rules)
    if priority != 'none':
        return settings('rules', workflow_legacy_alert_rules(priority))
    return settings('off', [])


# ---------------------------------------------------------------------------
# Change keys and labels (workflowChangeTracking.ts)
# ---------------------------------------------------------------------------

WORKFLOW_TASK_ORDER_KEY = 'tasks:order'
WORKFLOW_REFERENCE_ORDER_KEY = 'references:order'
_KEY_SCOPES = ('task', 'node', 'reference', 'region')
_WORKFLOW_KEY_SPECS = (
    ('name', 'Workflow name', ('name',)),
    ('description', 'Description', ('description',)),
    ('runner_type', 'Runner type', ('runner_type',)),
    ('selected_agent', 'Agent', ('selected_agent',)),
    ('model', 'Model', ('model_endpoint_id', 'model_id')),
    ('m365_run_as_user_id', 'Microsoft 365 Run as', ('m365_run_as_user_id',)),
    ('schedule', 'Trigger and schedule', ('trigger_type', 'schedule')),
    ('error_handling', 'Error handling', ('error_handling',)),
    ('is_enabled', 'Workflow enabled', ('is_enabled',)),
    ('chat_capabilities_enabled', 'Chat capabilities', ('chat_capabilities_enabled',)),
    ('durable_execution', 'Durable execution', ('durable_execution',)),
    ('file_sync', 'File Sync', ('file_sync',)),
    ('limits', 'Flow limits', ('limits',)),
    ('alerts', 'Alerts', WORKFLOW_ALERT_FIELDS),
    ('definition_version', 'Workflow format', ('definition_version',)),
)
_WORKFLOW_KEY_LABELS = {key: label for key, label, _fields in _WORKFLOW_KEY_SPECS}
_TRAILING_WORKFLOW_KEYS = ('alerts', 'definition_version')
_TASK_FIELD_LABELS = {
    'name': 'Task name', 'instructions': 'Instructions', 'runner': 'Task runner',
    'document_action': 'Document action', 'reference_ids': 'Task references', 'inputs': 'Inputs',
    'input_processing': 'Input processing', 'output_contract': 'Output contract', 'approval': 'Approval',
    'publication': 'Publication', 'run_when': 'Run when', 'placement': 'Position in flow',
}
_NODE_FIELD_LABELS = {
    'placement': 'Position in flow', 'kind': 'Block type', 'condition': 'Condition', 'inputs': 'Inputs',
    'iterable': 'Items to loop over', 'item_key': 'Item key', 'max_items': 'Maximum items',
    'max_iterations': 'Maximum rounds', 'state': 'Repeat state', 'until': 'Stop condition',
    'exports': 'Exports', 'join': 'Join exports', 'target': 'Route target', 'source': 'Collect source',
    'output_contract': 'Output contract',
}
_NODE_KIND_LABELS = {
    'task': 'Task', 'if': 'If / else', 'route': 'Forward route', 'for_each': 'For each',
    'repeat_until': 'Repeat until', 'collect': 'Collect',
}
_REFERENCE_FIELD_LABELS = {'name': 'Reference name', 'document': 'Document'}
_ITEM_NOUNS = {'task': 'task', 'node': 'block', 'reference': 'reference'}
_TASK_FIELD_RANK = {field: rank for rank, field in enumerate(_TASK_FIELD_LABELS)}
_NODE_FIELD_RANK = {field: rank for rank, field in enumerate(_NODE_FIELD_LABELS)}
_REFERENCE_FIELD_RANK = {field: rank for rank, field in enumerate(_REFERENCE_FIELD_LABELS)}
_TASK_SKIPPED_FIELDS = frozenset({'id', 'order'})
_REGION_BRANCHES = {'if': ('then', 'else'), 'for_each': ('body',), 'repeat_until': ('body',)}
_FLOW_WALK_DEPTH = 32


def _encode_segment(identifier):
    return identifier.replace('%', '%25').replace(':', '%3A')


def _decode_segment(segment):
    return re.sub(r'%(25|3A)', lambda match: '%' if match.group(1) == '25' else ':', segment)


def workflow_task_key(task_id, field=None):
    key = f'task:{_encode_segment(task_id)}'
    return f'{key}:{field}' if field else key


def workflow_reference_key(reference_id, field=None):
    key = f'reference:{_encode_segment(reference_id)}'
    return f'{key}:{field}' if field else key


def _parse_key(key):
    if key == WORKFLOW_TASK_ORDER_KEY:
        return {'scope': 'order', 'list': 'tasks'}
    if key == WORKFLOW_REFERENCE_ORDER_KEY:
        return {'scope': 'order', 'list': 'references'}
    parts = key.split(':')
    if len(parts) >= 2 and parts[0] in _KEY_SCOPES:
        return {'scope': parts[0], 'id': _decode_segment(parts[1]), 'field': ':'.join(parts[2:])}
    return {'scope': 'workflow', 'field': key}


def _item_key(key):
    parts = key.split(':')
    if len(parts) >= 2 and parts[0] in ('task', 'node', 'reference'):
        return f'{parts[0]}:{parts[1]}'
    return None


def _is_row(value):
    return isinstance(value, dict) and isinstance(value.get('id'), str)


def _is_region_row(value):
    return _is_row(value) and isinstance(value.get('nodes'), list)


def _index_list(value):
    by_id = {}
    for item in value if isinstance(value, list) else []:
        if _is_row(item) and item['id'] not in by_id:
            by_id[item['id']] = item
    return by_id


def _index_flow(flow):
    nodes = {}
    regions = {}
    task_nodes = {}
    order = []

    def walk(region, depth, owner=None):
        if region['id'] in regions:
            return
        node_ids = []
        regions[region['id']] = {'node_ids': node_ids, 'owner': owner}
        for node in region['nodes']:
            if not _is_row(node) or not isinstance(node.get('kind'), str) or node['id'] in nodes:
                continue
            task_id = node.get('task_id') if node['kind'] == 'task' and isinstance(node.get('task_id'), str) else None
            nodes[node['id']] = {'node': node, 'kind': node['kind'], 'region_id': region['id'], 'task_id': task_id}
            node_ids.append(node['id'])
            order.append(node['id'])
            if task_id is not None and task_id not in task_nodes:
                task_nodes[task_id] = node['id']
            if depth >= _FLOW_WALK_DEPTH:
                continue
            for branch in _REGION_BRANCHES.get(node['kind'], ()):
                child = node.get(branch)
                if _is_region_row(child):
                    walk(child, depth + 1, node['id'])

    walk(flow, 0)
    return {'root_id': flow['id'], 'nodes': nodes, 'regions': regions, 'task_nodes': task_nodes, 'order': order}


def _index_definition(definition):
    flow = _index_flow(definition['flow']) if _is_region_row(definition.get('flow')) else None
    return {
        'structured': _js_strict_equals(definition.get('definition_version'), 3) and flow is not None,
        'tasks': _index_list(definition.get('tasks')),
        'references': _index_list(definition.get('reference_inputs')),
        'flow': flow,
    }


def index_workflow_flow(definition):
    """Index a draft's v3 flow like the change tracker does, or return ``None`` without one.

    Returns ``{root_id, nodes, regions, task_nodes, order}``: ``nodes`` maps a node ID to
    ``{node, kind, region_id, task_id}``, ``regions`` maps a region ID to ``{node_ids, owner}``,
    ``task_nodes`` maps a task ID to its first node, and ``order`` is the walk order.
    """
    flow = definition.get('flow') if isinstance(definition, dict) else None
    return _index_flow(flow) if _is_region_row(flow) else None


def _task_node_entry(index, task_id):
    flow = index['flow']
    node_id = flow['task_nodes'].get(task_id) if flow else None
    return flow['nodes'].get(node_id) if node_id is not None else None


def _same_own(left, right, field):
    has = field in left
    return has == (field in right) and (not has or same_editor_value(left[field], right[field]))


def _field_names(left, right, skipped):
    names = {}
    for record in (left, right):
        for name in record or {}:
            if name not in skipped:
                names[name] = True
    return list(names)


def _same_relative_order(left, right):
    if left == right:
        return True
    in_left = set(left)
    in_right = set(right)
    return [item for item in left if item in in_right] == [item for item in right if item in in_left]


def _reference_document(reference):
    return {field: value for field, value in reference.items() if field not in ('id', 'name')}


def workflow_changed_keys(before, after):
    """The change keys whose values differ, in the editor's insertion order (``keyDelta``).

    The flow is not diffed: ``workflow_assist_violation`` refuses any candidate that changes it, and
    for an unchanged flow the editor's flow diff reports nothing.
    """
    changed = {}
    for key, _label, fields in _WORKFLOW_KEY_SPECS:
        if any(not _same_own(before, after, field) for field in fields):
            changed[key] = True
    a = _index_definition(before)
    b = _index_definition(after)
    for task_id in a['tasks']:
        if task_id not in b['tasks']:
            changed[workflow_task_key(task_id)] = True
    for task_id, entry in b['tasks'].items():
        previous = a['tasks'].get(task_id)
        if previous is None:
            changed[workflow_task_key(task_id)] = True
            for field in _field_names(entry, None, _TASK_SKIPPED_FIELDS):
                changed[workflow_task_key(task_id, field)] = True
            node = _task_node_entry(b, task_id)
            if node:
                changed[workflow_task_key(task_id, 'placement')] = True
            if node and 'run_when' in node['node']:
                changed[workflow_task_key(task_id, 'run_when')] = True
            continue
        for field in _field_names(previous, entry, _TASK_SKIPPED_FIELDS):
            if not _same_own(previous, entry, field):
                changed[workflow_task_key(task_id, field)] = True
        before_node = _task_node_entry(a, task_id)
        after_node = _task_node_entry(b, task_id)
        if (before_node or {}).get('region_id') != (after_node or {}).get('region_id'):
            changed[workflow_task_key(task_id, 'placement')] = True
        if (before_node is not None or after_node is not None) and not same_editor_value(
            _own((before_node or {}).get('node'), 'run_when'), _own((after_node or {}).get('node'), 'run_when'),
        ):
            changed[workflow_task_key(task_id, 'run_when')] = True
    if not b['structured'] and list(a['tasks']) != list(b['tasks']):
        if not _same_relative_order(list(a['tasks']), list(b['tasks'])):
            changed[WORKFLOW_TASK_ORDER_KEY] = True
    for reference_id in a['references']:
        if reference_id not in b['references']:
            changed[workflow_reference_key(reference_id)] = True
    for reference_id, entry in b['references'].items():
        previous = a['references'].get(reference_id)
        if previous is None:
            changed[workflow_reference_key(reference_id)] = True
            for field in _REFERENCE_FIELD_LABELS:
                changed[workflow_reference_key(reference_id, field)] = True
            continue
        if not _same_own(previous, entry, 'name'):
            changed[workflow_reference_key(reference_id, 'name')] = True
        if not same_editor_value(_reference_document(previous), _reference_document(entry)):
            changed[workflow_reference_key(reference_id, 'document')] = True
    if list(a['references']) != list(b['references']):
        if not _same_relative_order(list(a['references']), list(b['references'])):
            changed[WORKFLOW_REFERENCE_ORDER_KEY] = True
    return list(changed)


def _humanize(name):
    text = _js_trim(name.replace('_', ' '))
    return f'{text[0].upper()}{text[1:]}' if text else name


def _text_of(value):
    return value if isinstance(value, str) and _js_trim(value) else ''


def _task_label(item):
    return _text_of((item or {}).get('name')) or 'Untitled task'


def _reference_label(item):
    return _text_of((item or {}).get('name')) or 'Untitled reference'


def _item_label(index, scope, identifier):
    if scope == 'task':
        return _task_label(index['tasks'].get(identifier))
    if scope == 'reference':
        return _reference_label(index['references'].get(identifier))
    entry = index['flow']['nodes'].get(identifier) if index['flow'] else None
    if not entry:
        return f'Block ({identifier})'
    if entry['kind'] == 'task':
        return _task_label(index['tasks'].get(entry['task_id']) if entry['task_id'] is not None else None)
    return f"{_NODE_KIND_LABELS.get(entry['kind']) or _humanize(entry['kind'])} ({identifier})"


def _node_item_key(entry):
    if entry['kind'] != 'task':
        return f"node:{_encode_segment(entry['node']['id'])}"
    return workflow_task_key(entry['task_id']) if entry['task_id'] is not None else None


def workflow_changes(before, after):
    """Each change between two drafts in the editor's reading order (``diffWorkflowChanges``).

    Each entry is ``{key, kind, label, owner_label, target: {focus_key, node_id?}, summary}``; the
    key is the one the editor's change list and Jump to use. Summaries are plain text.
    """
    changed = workflow_changed_keys(before, after)
    if not changed:
        return []
    changed_set = set(changed)
    base = _index_definition(before)
    nxt = _index_definition(after)
    changes = []
    emitted = set()
    added = set()
    removed = set()
    fields_by_item = {}
    for key in changed:
        item_key = _item_key(key)
        if item_key and item_key != key:
            fields_by_item.setdefault(item_key, []).append(key)

    def push(change):
        if change['key'] in emitted:
            return
        emitted.add(change['key'])
        change['summary'] = (
            f"{change['label']}: {change['owner_label']}" if change['kind'] in ('added', 'removed')
            else f"{change['owner_label']}: {change['label']}"
        )
        changes.append(change)

    def describe(key, info):
        scope = info['scope']
        if scope == 'workflow':
            field = info['field']
            return {
                'key': key, 'kind': 'version' if field == 'definition_version' else 'field',
                'label': _WORKFLOW_KEY_LABELS.get(field) or _humanize(field), 'owner_label': 'Workflow',
                'target': {'focus_key': key},
            }
        if scope == 'order':
            return {
                'key': key, 'kind': 'order', 'label': 'Task order' if info['list'] == 'tasks' else 'Reference order',
                'owner_label': 'Workflow', 'target': {'focus_key': key},
            }
        field = info.get('field') or ''
        kind = 'placement' if field == 'placement' else 'field'
        if scope == 'task':
            target = {'focus_key': key}
            node_id = nxt['flow']['task_nodes'].get(info['id']) if nxt['flow'] else None
            if node_id is not None:
                target['node_id'] = node_id
            return {
                'key': key, 'kind': kind, 'label': _TASK_FIELD_LABELS.get(field) or _humanize(field),
                'owner_label': _task_label(nxt['tasks'].get(info['id']) or base['tasks'].get(info['id'])),
                'target': target,
            }
        if scope == 'reference':
            return {
                'key': key, 'kind': kind, 'label': _REFERENCE_FIELD_LABELS.get(field) or _humanize(field),
                'owner_label': _reference_label(
                    nxt['references'].get(info['id']) or base['references'].get(info['id']),
                ),
                'target': {'focus_key': key},
            }
        return {
            'key': key, 'kind': kind, 'label': _NODE_FIELD_LABELS.get(field) or _humanize(field),
            'owner_label': _item_label(nxt, 'node', info['id']),
            'target': {'focus_key': key, 'node_id': info['id']},
        }

    def emit_key(key):
        if key not in changed_set or key in emitted:
            return
        push(describe(key, _parse_key(key)))

    def emit_fields(item_key, rank):
        keys = fields_by_item.get(item_key)
        if not keys:
            return
        start = len(item_key) + 1
        for key in sorted(keys, key=lambda value: (rank.get(value[start:], len(rank)), value[start:])):
            emit_key(key)

    def item_change(key, kind):
        info = _parse_key(key)
        target = {'focus_key': key}
        if kind == 'added' and info['scope'] == 'task' and nxt['flow']:
            node_id = nxt['flow']['task_nodes'].get(info['id'])
            if node_id is not None:
                target['node_id'] = node_id
        elif kind == 'added' and info['scope'] == 'node':
            target['node_id'] = info['id']
        push({
            'key': key, 'kind': kind,
            'label': f"{'Added' if kind == 'added' else 'Removed'} {_ITEM_NOUNS.get(info['scope'], 'item')}",
            'owner_label': _item_label(nxt if kind == 'added' else base, info['scope'], info['id']),
            'target': target,
        })

    def emit_task(task_id):
        key = workflow_task_key(task_id)
        if task_id in base['tasks']:
            emit_fields(key, _TASK_FIELD_RANK)
            return
        added.add(key)
        item_change(key, 'added')

    for key, _label, _fields in _WORKFLOW_KEY_SPECS:
        if key not in _TRAILING_WORKFLOW_KEYS:
            emit_key(key)
    emit_key(WORKFLOW_REFERENCE_ORDER_KEY)
    for reference_id in nxt['references']:
        key = workflow_reference_key(reference_id)
        if reference_id in base['references']:
            emit_fields(key, _REFERENCE_FIELD_RANK)
            continue
        added.add(key)
        item_change(key, 'added')
    for reference_id in base['references']:
        if reference_id in nxt['references']:
            continue
        key = workflow_reference_key(reference_id)
        removed.add(key)
        item_change(key, 'removed')
    def control_node(index, node_id):
        entry = index['flow']['nodes'].get(node_id) if index['flow'] else None
        return entry if entry and entry['kind'] != 'task' else None

    def is_added(entry):
        if entry['kind'] == 'task':
            return entry['task_id'] is not None and entry['task_id'] in nxt['tasks'] and entry['task_id'] not in base['tasks']
        return control_node(base, entry['node']['id']) is None

    def is_removed(entry):
        if entry['kind'] == 'task':
            return entry['task_id'] is not None and entry['task_id'] in base['tasks'] and entry['task_id'] not in nxt['tasks']
        return control_node(nxt, entry['node']['id']) is None

    # The flow never changes, so a changed task node's group root is the node itself.
    if nxt['structured'] and nxt['flow']:
        flow = nxt['flow']
        for node_id in flow['order']:
            entry = flow['nodes'][node_id]
            key = _node_item_key(entry)
            if not key:
                continue
            if is_added(entry):
                added.add(key)
                item_change(key, 'added')
            elif entry['kind'] == 'task':
                emit_fields(key, _TASK_FIELD_RANK)
            else:
                emit_fields(key, _NODE_FIELD_RANK)
        for task_id in nxt['tasks']:
            if task_id not in flow['task_nodes']:
                emit_task(task_id)
    else:
        emit_key(WORKFLOW_TASK_ORDER_KEY)
        for task_id in nxt['tasks']:
            emit_task(task_id)
    if base['structured'] and base['flow']:
        flow = base['flow']
        for node_id in flow['order']:
            entry = flow['nodes'][node_id]
            key = _node_item_key(entry)
            if not key or not is_removed(entry):
                continue
            removed.add(key)
            item_change(key, 'removed')
    for task_id in base['tasks']:
        key = workflow_task_key(task_id)
        if task_id in nxt['tasks'] or key in removed:
            continue
        removed.add(key)
        item_change(key, 'removed')
    for key in _TRAILING_WORKFLOW_KEYS:
        emit_key(key)
    for key in changed:
        item_key = _item_key(key)
        if item_key != key and not (item_key and (item_key in added or item_key in removed)):
            emit_key(key)
    return changes
