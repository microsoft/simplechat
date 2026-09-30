# functions_workflow_assist_operations.py
"""
Handles, the model's view of a draft, and the operations the AI workflow assistant may apply.

Version: 0.261.206
Implemented in: 0.261.206

The model never sees a raw document, reference, agent, endpoint, task, node or rule ID (roadmap
gotcha 28). Everything it may name has a request-local handle: ``task_N``, ``node_N``, ``agent_N``,
``model_N``, ``alert_N``, ``doc_N`` and ``ref_N``, plus the alias of each shared reference. The
server maps handles back and refuses anything else.

The model answers with a closed JSON envelope. Its operations come from a fixed allowlist, and each
one is checked against its own schema before anything is applied. ``apply_assist_operations`` then
applies them to a deep copy of the editor draft, structurally and without normalization, so the
candidate differs from the draft only where an operation changed it (gotcha 25).

Every error message here is server-authored. None echoes model output, a handle the model sent,
or document text, because the messages feed the correction round and the logs.

It imports nothing that reaches Azure, so it loads cheaply in tests and in the assistant core.
"""

import copy
import json
import re
import uuid

from jsonschema import Draft202012Validator

from functions_workflow_assist_editor import (
    WORKFLOW_ALIAS_PATTERN,
    WORKFLOW_OUTPUT_KINDS,
    WORKFLOW_REFERENCE_SCOPES,
    WORKFLOW_SCHEDULE_DAYS,
    WORKFLOW_SCHEDULE_FREQUENCIES,
    WORKFLOW_SCHEDULE_UNITS,
    create_workflow_task,
    index_workflow_flow,
    js_trim,
    js_truthy,
    safe_workflow_alias,
    same_editor_value,
    workflow_alert_config,
    workflow_schedule_for_editor,
)
from functions_workflow_definitions import WorkflowPublicValidationError
from functions_workflow_schedules import (
    enforce_workflow_schedule_minimum,
    normalize_workflow_schedule,
    workflow_schedule_minimum_applies,
    workflow_schedule_timezones,
)


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

ASSIST_MAX_TASKS = 100
ASSIST_MAX_REFERENCES = 100
ASSIST_MAX_OPERATIONS = 64
ASSIST_MAX_TARGET_DOCUMENTS = 50
ASSIST_REPLY_MAX_LENGTH = 1500
ASSIST_WORKFLOW_NAME_MAX_LENGTH = 200
ASSIST_WORKFLOW_DESCRIPTION_MAX_LENGTH = 4000
ASSIST_TASK_NAME_MAX_LENGTH = 120
ASSIST_TASK_INSTRUCTIONS_MAX_LENGTH = 12000
ASSIST_ALERT_MAX_RULES = 20
ASSIST_ALERT_NAME_MAX_LENGTH = 120
ASSIST_ALERT_VALUE_MAX_LENGTH = 400
ASSIST_ALERT_MAX_VALUES = 25
ASSIST_ALERT_REGEX_MAX_LENGTH = 200
ASSIST_ALERT_PROMPT_MAX_LENGTH = 2000
ASSIST_TIMEZONE_MAX_LENGTH = 64
ASSIST_REFERENCE_ID_MAX_LENGTH = 128
ASSIST_ALIAS_MAX_LENGTH = 64
# A known ID shorter than this is too generic to recognize inside a label.
ASSIST_MIN_SCRUBBED_ID_LENGTH = 8
ASSIST_SCRUB_PREFIX_LENGTH = 24

ASSIST_OUTCOMES = ('changed', 'explained', 'question')
ASSIST_ALERT_SEVERITIES = ('info', 'low', 'medium', 'high', 'critical')
ASSIST_ALERT_DELIVERIES = ('default', 'notify_only', 'popup')
ASSIST_ALERT_SCOPES = ('final', 'any_task', 'task')
ASSIST_ALERT_PRIORITIES = ('low', 'medium', 'high')
ASSIST_ALERT_CONDITIONS = ('run_status', 'task_status', 'text_match', 'model_evaluation', 'agent_signal', 'no_output')
ASSIST_ALERT_RUN_STATUSES = ('completed', 'failed', 'cancelled', 'completed_with_task_errors')
ASSIST_ALERT_TASK_STATUSES = ('succeeded', 'failed')
ASSIST_ALERT_TEXT_MODES = ('contains_any', 'contains_all', 'not_contains', 'regex')
# Conditions that read run-level facts. The editor resets their scope to final when one is chosen
# (WORKFLOW_ALERT_SCOPELESS_CONDITIONS in workflowAlerts.ts), so the assistant only writes final.
ASSIST_SCOPELESS_CONDITIONS = frozenset({'run_status', 'agent_signal'})

HANDLE_PATTERN = r'^[A-Za-z][A-Za-z0-9_-]{0,63}$'
TASK_HANDLE_PATTERN = r'^(task|new)_[1-9][0-9]{0,2}$'
NEW_TASK_KEY_PATTERN = r'^new_[1-9][0-9]{0,2}$'
TASK_POSITION_PATTERN = r'^((task|new)_[1-9][0-9]{0,2}|start)$'
AGENT_HANDLE_PATTERN = r'^agent_[1-9][0-9]{0,3}$'
MODEL_HANDLE_PATTERN = r'^model_[1-9][0-9]{0,3}$'
WORKFLOW_MODEL_HANDLE_PATTERN = r'^(model_[1-9][0-9]{0,3}|default_model)$'
ALERT_HANDLE_PATTERN = r'^alert_[1-9][0-9]?$'
TIME_OF_DAY_PATTERN = r'^([01][0-9]|2[0-3]):[0-5][0-9]$'
TEXT_PATTERN = r'\S'
_HANDLE_PATTERNS = frozenset({
    HANDLE_PATTERN, TASK_HANDLE_PATTERN, NEW_TASK_KEY_PATTERN, TASK_POSITION_PATTERN, AGENT_HANDLE_PATTERN,
    MODEL_HANDLE_PATTERN, WORKFLOW_MODEL_HANDLE_PATTERN, ALERT_HANDLE_PATTERN,
})

# A user's reference alias that looks like a server handle is shown under a server handle instead.
_RESERVED_HANDLE = re.compile(r'(?:task|new|node|ref|doc|agent|model|alert|shared)_[0-9]+|default_model', re.IGNORECASE)
# C0 controls other than tab, line feed and carriage return, plus DEL.
_CONTROL_CHARACTERS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_LINE_BREAKS = re.compile(r'[\r\n\u0085\u2028\u2029]')


class AssistApplyError(Exception):
    """The model's operations cannot be applied. ``messages`` are server-authored and content-free."""

    def __init__(self, messages):
        self.messages = [str(message) for message in messages]
        super().__init__('; '.join(self.messages))


class _OperationError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _string(value):
    return value if isinstance(value, str) else ''


def model_text(value, label, max_length, *, multiline=False, required=True):
    """Check one piece of model-written text and return it trimmed, or raise ``_OperationError``."""
    if not isinstance(value, str):
        raise _OperationError(f'{label} must be text.')
    text = js_trim(value)
    if required and not text:
        raise _OperationError(f'{label} must not be blank.')
    if len(text) > max_length:
        raise _OperationError(f'{label} must be {max_length} characters or fewer.')
    if _CONTROL_CHARACTERS.search(text):
        raise _OperationError(f'{label} must not contain control characters.')
    if not multiline and _LINE_BREAKS.search(text):
        raise _OperationError(f'{label} must be a single line.')
    return text


def clean_reply(value):
    """The model's reply as display text: control characters other than line breaks and tabs removed."""
    return js_trim(_CONTROL_CHARACTERS.sub('', _string(value)))


def _list_of_strings(value):
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, str) and item]


def collect_known_ids(*values, exclude_keys=('model_id',)):
    """Every string held under an ``id``, ``*_id`` or ``*_ids`` key, for recognizing IDs in labels.

    Model IDs are deployment names the model may see, so they are skipped.
    """
    found = set()
    stack = list(values)
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, item in node.items():
                if isinstance(item, (dict, list)):
                    stack.append(item)
                if not isinstance(key, str) or key in exclude_keys:
                    continue
                if key == 'id' or key.endswith('_id') or key.endswith('_ids'):
                    if isinstance(item, str) and item:
                        found.add(item)
                    elif isinstance(item, list):
                        found.update(entry for entry in item if isinstance(entry, str) and entry)
        elif isinstance(node, list):
            stack.extend(node)
    return found


class IdMatcher:
    """Recognizes a known ID, or a sanitized or truncated form of one, inside free text."""

    def __init__(self, known_ids):
        needles = set()
        for identifier in known_ids:
            if not isinstance(identifier, str) or len(identifier) < ASSIST_MIN_SCRUBBED_ID_LENGTH:
                continue
            sanitized = re.sub(r'[^A-Za-z0-9_-]+', '_', identifier)
            for form in (identifier, sanitized):
                needles.add(form.casefold())
                if len(form) > ASSIST_SCRUB_PREFIX_LENGTH:
                    needles.add(form[:ASSIST_SCRUB_PREFIX_LENGTH].casefold())
        self._needles = sorted(needles, key=len, reverse=True)

    def contains_id(self, text):
        folded = _string(text).casefold()
        return any(needle in folded for needle in self._needles)


# ---------------------------------------------------------------------------
# Document identities
# ---------------------------------------------------------------------------
# An identity is ``(scope_type, scope_id, document_id)`` with a personal scope keyed by the owner's
# user ID. A document whose scope cannot be known is ``('unknown', '', document_id)``: the model may
# see it, but the assistant cannot place it anywhere else.

UNKNOWN_SCOPE = 'unknown'


def reference_identity(reference, user_id):
    """The identity of a ``reference_inputs`` entry, scoped as the editor would save it."""
    scope_type = reference.get('scope_type')
    scope_type = scope_type if isinstance(scope_type, str) and scope_type in WORKFLOW_REFERENCE_SCOPES else 'personal'
    scope_id = user_id if scope_type == 'personal' else _string(reference.get('scope_id'))
    return (scope_type, scope_id, _string(reference.get('document_id')))


def _action_scope(action, user_id):
    """The scope every document of a ``document_action`` shares, or ``None`` when it is unknown.

    ``evidenceFromAction`` reads the first group or public workspace ID; with more than one, which
    document belongs to which is unknown, so the assistant treats the scope as unknown.
    """
    scope_type = action.get('doc_scope')
    if scope_type == 'personal':
        return ('personal', user_id)
    if scope_type not in ('group', 'public'):
        return None
    field = 'active_group_ids' if scope_type == 'group' else 'active_public_workspace_id'
    raw = action.get(field)
    if not isinstance(raw, list):
        return None
    scope_ids = [item for item in raw if isinstance(item, str) and item]
    if len(set(scope_ids)) != 1:
        return None
    return (scope_type, scope_ids[0])


def action_document_identities(action, user_id):
    """The identities of a ``document_action``'s selected documents, in order and without repeats."""
    if not isinstance(action, dict):
        return []
    document_ids = action.get('document_ids')
    if not isinstance(document_ids, list):
        return []
    scope = _action_scope(action, user_id)
    identities = []
    for document_id in document_ids:
        if not isinstance(document_id, str) or not document_id:
            continue
        identity = (scope[0], scope[1], document_id) if scope else (UNKNOWN_SCOPE, '', document_id)
        if identity not in identities:
            identities.append(identity)
    return identities


def document_action_mode(action):
    """``actionMode`` (WorkflowTaskFields.tsx): how the editor presents a task's document action."""
    if not isinstance(action, dict) or action.get('type') == 'none':
        return 'none'
    action_type = action.get('type')
    if action_type == 'analyze':
        return 'current_item' if action.get('target_mode') == 'current_item' else 'analyze'
    if action_type == 'comparison':
        return 'comparison'
    if action_type == 'search':
        document_ids = action.get('document_ids')
        return 'search_selected' if isinstance(document_ids, list) and document_ids else 'search_relevance'
    return 'preserve'


def _selection_scope(identities):
    """``documentActionScope`` over identities."""
    scope_types = {identity[0] for identity in identities}
    group_ids = []
    public_ids = []
    for scope_type, scope_id, _document_id in identities:
        target = group_ids if scope_type == 'group' else public_ids if scope_type == 'public' else None
        if target is not None and scope_id and scope_id not in target:
            target.append(scope_id)
    doc_scope = identities[0][0] if len(scope_types) == 1 and identities else 'all'
    return doc_scope, group_ids, public_ids


def document_action_from_selection(action_type, identities, *, relevance=False, analysis_mode='combined'):
    """``documentActionFromSelection`` for known-scope identities."""
    if action_type == 'search' and relevance:
        return {
            'type': 'search', 'doc_scope': 'all', 'active_group_ids': [], 'active_public_workspace_id': [],
            'document_ids': [], 'target_mode': 'selected', 'analysis_mode': analysis_mode,
        }
    doc_scope, group_ids, public_ids = _selection_scope(identities)
    return {
        'type': action_type, 'doc_scope': doc_scope, 'active_group_ids': group_ids,
        'active_public_workspace_id': public_ids, 'document_ids': [identity[2] for identity in identities],
        'target_mode': 'selected', 'analysis_mode': analysis_mode,
    }


def comparison_action_from_selection(left, right):
    """``comparisonActionFromSelection`` for known-scope identities."""
    identities = [left, *right]
    doc_scope, group_ids, public_ids = _selection_scope(identities)
    return {
        'type': 'comparison', 'doc_scope': doc_scope, 'active_group_ids': group_ids,
        'active_public_workspace_id': public_ids, 'document_ids': [identity[2] for identity in identities],
        'target_mode': 'selected', 'analysis_mode': 'combined', 'left_document_id': left[2],
        'right_document_ids': [identity[2] for identity in right],
    }


# ---------------------------------------------------------------------------
# Handles
# ---------------------------------------------------------------------------

def _rows(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def is_structured_draft(draft):
    """Whether a draft is a v3 flow, which the assistant may not restructure."""
    version = draft.get('definition_version') if isinstance(draft, dict) else None
    return _is_int(version) and version == 3 or isinstance(version, float) and version == 3.0


def _agent_key(agent):
    return (
        _string(agent.get('id')), agent.get('is_global') is True, agent.get('is_group') is True,
        _string(agent.get('group_id')),
    )


def request_document_identity(reference, user_id):
    """The identity of a `#` document authorized by ``resolve_scope_references``."""
    scope = reference.get('scope') if isinstance(reference.get('scope'), dict) else {}
    scope_type = scope.get('kind')
    scope_id = user_id if scope_type == 'personal' else _string(scope.get('id'))
    return (scope_type, scope_id, _string(reference.get('id')))


class AssistHandles:
    """Request-local handles for everything the model may name, and the maps back to IDs.

    ``draft`` is the parsed editor draft, ``options`` the editor options for the caller
    (``get_workflow_editor_options``), and ``request_documents`` the `#` documents
    ``resolve_scope_references`` authorized for this request, in request order. Handles are
    only meaningful within one request.
    """

    def __init__(self, draft, *, user_id, options=None, request_documents=()):
        self.user_id = user_id
        self.options = options if isinstance(options, dict) else {}
        self.structured = is_structured_draft(draft)
        request_documents = [item for item in request_documents if isinstance(item, dict)]
        self.matcher = IdMatcher(collect_known_ids(draft, self.options, request_documents) | {user_id})
        self._by_handle = {}

        self.task_handles = {}
        for position, task in enumerate(_rows(draft.get('tasks')), start=1):
            handle = f'task_{position}'
            self.task_handles[task['id']] = handle
            self._register(handle, ('task', task['id']))

        self.flow_index = index_workflow_flow(draft) if self.structured else None
        self.node_handles = {}
        for position, node_id in enumerate((self.flow_index or {}).get('order') or (), start=1):
            handle = f'node_{position}'
            self.node_handles[node_id] = handle
            self._register(handle, ('node', node_id))

        self.agents = []
        self.agent_handles = {}
        for position, agent in enumerate(_rows(self.options.get('agents')), start=1):
            if not _string(agent.get('id')):
                continue
            handle = f'agent_{position}'
            self.agents.append((handle, agent))
            self.agent_handles.setdefault(_agent_key(agent), handle)
            self._register(handle, ('agent', agent))

        self.models = []
        self.model_handles = {}
        for position, model in enumerate(_rows(self.options.get('models')), start=1):
            if not _string(model.get('endpoint_id')) or not _string(model.get('model_id')):
                continue
            handle = f'model_{position}'
            self.models.append((handle, model))
            self.model_handles.setdefault((model['endpoint_id'], model['model_id']), handle)
            self._register(handle, ('model', model))
        default_model = self.options.get('default_model')
        self.default_model = default_model if isinstance(default_model, dict) and default_model.get('valid') is True else None
        if self.default_model is not None:
            self._register('default_model', ('default_model', self.default_model))

        self.alert_handles = []
        for position, _rule in enumerate(workflow_alert_config(draft)['alert_rules'], start=1):
            handle = f'alert_{position}'
            self.alert_handles.append(handle)
            self._register(handle, ('alert', position - 1))

        # References show under their alias when it is safe to show, else as shared_N.
        self.reference_handles = {}
        self.reference_names = {}
        self.documents = {}
        self.identity_handles = {}
        references = _rows(draft.get('reference_inputs'))
        folded_aliases = {}
        for reference in references:
            name = reference.get('name')
            if isinstance(name, str):
                folded_aliases[name.casefold()] = folded_aliases.get(name.casefold(), 0) + 1
        for position, reference in enumerate(references, start=1):
            name = reference.get('name')
            safe = (
                isinstance(name, str) and WORKFLOW_ALIAS_PATTERN.fullmatch(name)
                and not _RESERVED_HANDLE.fullmatch(name) and name.casefold() not in _RESERVED_WORDS
                and folded_aliases.get(name.casefold()) == 1 and not self.matcher.contains_id(name)
            )
            handle = name if safe else f'shared_{position}'
            if handle.casefold() in self._by_handle:
                handle = f'shared_{position}'
            identity = reference_identity(reference, user_id)
            self.reference_handles[reference['id']] = handle
            self.reference_names[reference['id']] = name if safe else f'Shared document {position}'
            self._register(handle, ('reference', reference['id']))
            self.documents[handle] = {'identity': identity, 'label': self.reference_names[reference['id']]}
            self.identity_handles.setdefault(identity, handle)

        # Documents already targeted by a task's document action, where no reference names them.
        position = 0
        for task in _rows(draft.get('tasks')):
            for identity in action_document_identities(task.get('document_action'), user_id):
                if identity in self.identity_handles:
                    continue
                position += 1
                handle = f'doc_{position}'
                self._register(handle, ('document', identity))
                self.documents[handle] = {'identity': identity, 'label': f'Document {position}'}
                self.identity_handles[identity] = handle

        # The request's `#` documents, which the caller may read now.
        self.request_handles = []
        position = 0
        for reference in request_documents:
            identity = request_document_identity(reference, user_id)
            label = sanitize_label(reference.get('label'))
            handle = self.identity_handles.get(identity)
            if handle is None:
                position += 1
                handle = f'ref_{position}'
                self._register(handle, ('document', identity))
                self.documents[handle] = {'identity': identity, 'label': ''}
                self.identity_handles[identity] = handle
            entry = self.documents[handle]
            entry['requested'] = True
            if label and not self.matcher.contains_id(label):
                entry['file_label'] = label
            if handle not in self.request_handles:
                self.request_handles.append(handle)
        for handle in self.request_handles:
            entry = self.documents[handle]
            if not entry['label']:
                entry['label'] = entry.get('file_label') or f'Attached document {self.request_handles.index(handle) + 1}'

    def _register(self, handle, target):
        self._by_handle[handle.casefold()] = target

    def resolve(self, handle):
        """``(kind, value)`` for a handle the model sent, or ``None``."""
        if not isinstance(handle, str):
            return None
        return self._by_handle.get(handle.casefold())

    def agent_label(self, agent, position):
        label = _string(agent.get('display_name')) or _string(agent.get('name'))
        label = sanitize_label(label)
        return label if label and not self.matcher.contains_id(label) else f'Agent {position}'

    def model_label(self, model, position):
        label = sanitize_label(model.get('label'))
        return label if label and not self.matcher.contains_id(label) else f'Model {position}'

    def agent_handle(self, agent):
        return self.agent_handles.get(_agent_key(agent)) if isinstance(agent, dict) else None

    def model_handle(self, endpoint_id, model_id):
        return self.model_handles.get((_string(endpoint_id), _string(model_id)))


_RESERVED_WORDS = frozenset({'start', 'all', 'none', 'auto', 'selected', 'tasks', 'relevance'})
_LABEL_CONTROL = re.compile('[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]')


def sanitize_label(value, limit=200):
    """A display label as plain single-line text, bounded."""
    if not isinstance(value, str):
        return ''
    text = js_trim(_LABEL_CONTROL.sub(' ', value))
    text = re.sub(r'\s+', ' ', text)
    return text[:limit].rstrip()


# ---------------------------------------------------------------------------
# The model's view of the draft
# ---------------------------------------------------------------------------

_ALERT_CONDITION_KEYS = (
    'type', 'statuses', 'mode', 'pattern', 'values', 'case_sensitive', 'outcome', 'prompt', 'signal_name', 'min_severity',
)


def file_sync_supplies_analyze_targets(draft):
    """``workflowFileSyncProvidesAnalyzeTargets``: File Sync hands Analyze its changed documents."""
    config = draft.get('file_sync') if isinstance(draft, dict) else None
    return isinstance(config, dict) and config.get('enabled') is True and config.get('use_changed_documents') is not False


def alert_rule_enabled(rule):
    """``workflowAlertRuleEnabled``."""
    if 'enabled' not in rule:
        return True
    value = rule['enabled']
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


def _trigger_view(draft):
    trigger_type = draft.get('trigger_type')
    if trigger_type == 'file_sync':
        return {'type': 'file_sync', 'editable': False}
    if trigger_type != 'interval':
        return {'type': 'manual'}
    schedule = workflow_schedule_for_editor(draft.get('schedule'))
    if schedule is None:
        return {'type': 'unsupported', 'editable': False}
    if schedule.get('kind') == 'calendar':
        view = {'type': 'calendar', 'frequency': schedule['frequency'], 'time_of_day': schedule['time_of_day'],
                'timezone': schedule['timezone']}
        if schedule['frequency'] == 'weekly':
            view['days_of_week'] = schedule['days_of_week']
        if schedule['frequency'] == 'monthly':
            view['day_of_month'] = schedule['day_of_month']
        return view
    return {'type': 'interval', 'unit': schedule['unit'], 'value': schedule['value']}


def _workflow_runner_view(draft, handles):
    if draft.get('runner_type') == 'agent':
        return {'type': 'agent', 'agent': handles.agent_handle(draft.get('selected_agent'))}
    endpoint_id = _string(draft.get('model_endpoint_id'))
    model_id = _string(draft.get('model_id'))
    if not endpoint_id and not model_id:
        return {'type': 'model', 'model': 'default_model'}
    return {'type': 'model', 'model': handles.model_handle(endpoint_id, model_id)}


def _task_runner_view(runner, handles):
    runner = runner if isinstance(runner, dict) else {}
    runner_type = runner.get('type')
    if runner_type == 'agent':
        return {'type': 'agent', 'agent': handles.agent_handle(runner.get('selected_agent'))}
    if runner_type == 'model':
        return {'type': 'model', 'model': handles.model_handle(runner.get('model_endpoint_id'), runner.get('model_id'))}
    return {'type': 'inherit'}


def _document_handles(handles, identities):
    return [handles.identity_handles.get(identity) for identity in identities]


def _document_target_view(task, handles, user_id, changed_files):
    action = task.get('document_action')
    mode = document_action_mode(action)
    if mode == 'none':
        return None
    if mode == 'current_item':
        return {'action': 'current_loop_document', 'editable': False}
    if mode == 'preserve':
        return {'action': 'advanced', 'editable': False}
    identities = action_document_identities(action, user_id)
    analysis_mode = action.get('analysis_mode') if action.get('analysis_mode') in ('combined', 'per_document') else 'combined'
    if mode == 'comparison':
        # splitComparisonEvidence: the named left document, else the first; the named right
        # documents, else every other document.
        left_id = action.get('left_document_id')
        right_ids = [item for item in action.get('right_document_ids') or [] if isinstance(item, str)] \
            if isinstance(action.get('right_document_ids'), list) else []
        left = next((item for item in identities if item[2] == left_id), identities[0] if identities else None)
        if right_ids:
            right = [item for item in identities if item[2] in right_ids]
        else:
            right = [item for item in identities if left is None or item[2] != left[2]]
        return {
            'action': 'comparison',
            'left': handles.identity_handles.get(left) if left else None,
            'right': _document_handles(handles, right),
        }
    if mode == 'search_relevance':
        return {'action': 'search', 'search_mode': 'relevance', 'analysis_mode': analysis_mode}
    view = {
        'action': 'analyze' if mode == 'analyze' else 'search',
        'documents': _document_handles(handles, identities),
        'analysis_mode': analysis_mode,
    }
    if mode == 'search_selected':
        view['search_mode'] = 'selected'
    if mode == 'analyze' and not identities and changed_files:
        view['documents_from'] = 'file_sync_changed_documents'
    return view


def _task_view(task, handles, draft, changed_files):
    user_id = handles.user_id
    view = {
        'task': handles.task_handles[task['id']],
        'name': _string(task.get('name')),
        'instructions': _string(task.get('instructions')),
    }
    publication = js_truthy(task.get('publication'))
    if publication:
        view['publication'] = True
    else:
        view['runner'] = _task_runner_view(task.get('runner'), handles)
    if handles.structured:
        view['inputs'] = 'flow'
    else:
        inputs = task.get('inputs')
        if inputs is None:
            view['inputs'] = 'auto'
        elif isinstance(inputs, list) and not inputs:
            view['inputs'] = 'none'
        else:
            view['inputs'] = [
                {'from': handles.task_handles.get(entry.get('task_id')), 'output': _string(entry.get('output')) or 'text'}
                for entry in _rows(inputs)
            ]
    reference_ids = task.get('reference_ids')
    if reference_ids is None:
        view['references'] = 'all'
    elif isinstance(reference_ids, list) and not reference_ids:
        view['references'] = 'none'
    else:
        view['references'] = [
            handles.reference_handles[item] for item in reference_ids
            if isinstance(item, str) and item in handles.reference_handles
        ]
    if not publication:
        view['document_target'] = _document_target_view(task, handles, user_id, changed_files)
    approval = task.get('approval')
    if isinstance(approval, dict) and approval.get('required') is True:
        view['approval_required'] = True
    if handles.flow_index:
        node_id = handles.flow_index['task_nodes'].get(task['id'])
        if node_id is not None:
            view['flow_node'] = handles.node_handles.get(node_id)
    return view


def _alert_rule_view(rule, handle, handles):
    scope = rule.get('scope') if isinstance(rule.get('scope'), dict) else {}
    scope_view = {'type': scope.get('type') if scope.get('type') in ASSIST_ALERT_SCOPES else 'final'}
    if scope_view['type'] == 'task':
        scope_view['task'] = handles.task_handles.get(scope.get('task_id'))
    condition = rule.get('condition') if isinstance(rule.get('condition'), dict) else {}
    return {
        'rule': handle,
        'name': _string(rule.get('name')),
        'enabled': alert_rule_enabled(rule),
        'severity': _string(rule.get('severity')) or 'medium',
        'delivery': _string(rule.get('delivery')) or 'default',
        'scope': scope_view,
        'condition': {key: copy.deepcopy(condition[key]) for key in _ALERT_CONDITION_KEYS if key in condition},
    }


def build_draft_view(draft, handles):
    """The draft as the model sees it: handles in every structural slot, and no raw IDs."""
    changed_files = file_sync_supplies_analyze_targets(draft)
    alerts = workflow_alert_config(draft)
    view = {
        'format': 'flow' if handles.structured else 'tasks',
        'name': _string(draft.get('name')),
        'description': _string(draft.get('description')),
        'runner': _workflow_runner_view(draft, handles),
        'trigger': _trigger_view(draft),
        'alerts': {
            'mode': alerts['alert_mode'],
            'priority': alerts['alert_priority'],
            'rules': [
                _alert_rule_view(rule, handles.alert_handles[index], handles)
                for index, rule in enumerate(alerts['alert_rules'])
                if isinstance(rule, dict) and index < len(handles.alert_handles)
            ],
        },
        'run_as_configured': bool(_string(draft.get('m365_run_as_user_id'))),
        'shared_references': [
            {'reference': handles.reference_handles[reference['id']], 'name': handles.reference_names[reference['id']]}
            for reference in _rows(draft.get('reference_inputs'))
        ],
        'tasks': [_task_view(task, handles, draft, changed_files) for task in _rows(draft.get('tasks'))],
    }
    if handles.flow_index:
        flow = []
        for node_id in handles.flow_index['order']:
            entry = handles.flow_index['nodes'][node_id]
            region = handles.flow_index['regions'].get(entry['region_id']) or {}
            item = {'node': handles.node_handles[node_id], 'kind': entry['kind']}
            if entry['task_id'] is not None:
                item['task'] = handles.task_handles.get(entry['task_id'])
            if region.get('owner') is not None:
                item['inside'] = handles.node_handles.get(region['owner'])
            flow.append(item)
        view['flow'] = flow
    documents = []
    for handle, entry in handles.documents.items():
        if handle in handles.reference_handles.values():
            continue
        documents.append({'document': handle, 'label': entry['label'], 'placeable': entry['identity'][0] != UNKNOWN_SCOPE})
    view['task_documents'] = [item for item in documents if not handles.documents[item['document']].get('requested')]
    view['attached_documents'] = [
        {'document': handle, 'label': handles.documents[handle].get('file_label') or handles.documents[handle]['label']}
        for handle in handles.request_handles
    ]
    return view


def build_options_view(handles):
    """The agents, models and limits the caller may choose from, by handle."""
    options = handles.options
    schedule = options.get('schedule') if isinstance(options.get('schedule'), dict) else {}
    view = {
        'agents': [
            {
                'agent': handle, 'label': handles.agent_label(agent, position),
                'scope': 'global' if agent.get('is_global') is True else 'group' if agent.get('is_group') is True else 'personal',
                'loop_eligible': agent.get('loop_eligible') is True,
            }
            for position, (handle, agent) in enumerate(handles.agents, start=1)
        ],
        'models': [
            {'model': handle, 'label': handles.model_label(model, position), 'loop_eligible': model.get('loop_eligible') is True}
            for position, (handle, model) in enumerate(handles.models, start=1)
        ],
        'default_model': (
            {'model': 'default_model', 'loop_eligible': handles.default_model.get('loop_eligible') is True}
            if handles.default_model is not None else None
        ),
        'max_tasks': assist_max_tasks(options),
        'minimum_interval_seconds': schedule.get('min_interval_seconds') if _is_int(schedule.get('min_interval_seconds')) else 0,
    }
    return view


def assist_max_tasks(options):
    limit = options.get('max_tasks') if isinstance(options, dict) else None
    return min(ASSIST_MAX_TASKS, limit) if _is_int(limit) and limit > 0 else ASSIST_MAX_TASKS


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

def _str(max_length, *, min_length=1, pattern=TEXT_PATTERN):
    schema = {'type': 'string', 'minLength': min_length, 'maxLength': max_length}
    if pattern and min_length:
        schema['pattern'] = pattern
    return schema


def _handle(pattern=HANDLE_PATTERN):
    return {'type': 'string', 'pattern': pattern}


def _handles(max_items, pattern=HANDLE_PATTERN):
    return {'type': 'array', 'minItems': 1, 'maxItems': max_items, 'uniqueItems': True, 'items': _handle(pattern)}


def _when(field, value, then):
    return {'if': {'required': [field], 'properties': {field: {'const': value}}}, 'then': then}


def _forbid(*fields):
    return {'not': {'anyOf': [{'required': [field]} for field in fields]}} if len(fields) > 1 else {'not': {'required': [fields[0]]}}


def _operation(name, properties=None, required=(), all_of=()):
    schema = {
        'type': 'object',
        'additionalProperties': False,
        'required': ['op', *required],
        'properties': {'op': {'const': name}, **(properties or {})},
    }
    if all_of:
        schema['allOf'] = list(all_of)
    return schema


_TASK = _handle(TASK_HANDLE_PATTERN)
_CONDITION_SCHEMAS = {
    'run_status': {
        'statuses': {'type': 'array', 'minItems': 1, 'maxItems': 4, 'uniqueItems': True,
                     'items': {'enum': list(ASSIST_ALERT_RUN_STATUSES)}},
    },
    'task_status': {
        'statuses': {'type': 'array', 'minItems': 1, 'maxItems': 2, 'uniqueItems': True,
                     'items': {'enum': list(ASSIST_ALERT_TASK_STATUSES)}},
    },
    'text_match': {
        'mode': {'enum': list(ASSIST_ALERT_TEXT_MODES)},
        'values': {'type': 'array', 'minItems': 1, 'maxItems': ASSIST_ALERT_MAX_VALUES,
                   'items': _str(ASSIST_ALERT_VALUE_MAX_LENGTH)},
        'pattern': _str(ASSIST_ALERT_REGEX_MAX_LENGTH),
        'case_sensitive': {'type': 'boolean'},
    },
    'model_evaluation': {'prompt': _str(ASSIST_ALERT_PROMPT_MAX_LENGTH)},
    'agent_signal': {
        'signal_name': _str(ASSIST_ALERT_NAME_MAX_LENGTH, min_length=0),
        'min_severity': {'enum': list(ASSIST_ALERT_SEVERITIES)},
    },
    'no_output': {},
}
_CONDITION_REQUIRED = {
    'run_status': ['statuses'], 'task_status': ['statuses'], 'text_match': ['mode'], 'model_evaluation': ['prompt'],
}
_CONDITION = {
    'type': 'object',
    'required': ['type'],
    'properties': {'type': {'enum': list(ASSIST_ALERT_CONDITIONS)}},
    'allOf': [
        _when('type', condition_type, {
            'additionalProperties': False,
            'required': _CONDITION_REQUIRED.get(condition_type, []),
            'properties': {'type': {'const': condition_type}, **fields},
        })
        for condition_type, fields in _CONDITION_SCHEMAS.items()
    ] + [
        {'if': {'required': ['type', 'mode'], 'properties': {'type': {'const': 'text_match'}, 'mode': {'const': 'regex'}}},
         'then': {'required': ['pattern'], **_forbid('values', 'case_sensitive')}},
        {'if': {'required': ['type', 'mode'], 'properties': {'type': {'const': 'text_match'}, 'mode': {'not': {'const': 'regex'}}}},
         'then': {'required': ['values'], **_forbid('pattern')}},
    ],
}

OPERATION_SCHEMAS = {
    'set_name': _operation('set_name', {'name': _str(ASSIST_WORKFLOW_NAME_MAX_LENGTH)}, ['name']),
    'set_description': _operation(
        'set_description', {'description': _str(ASSIST_WORKFLOW_DESCRIPTION_MAX_LENGTH, min_length=0)}, ['description'],
    ),
    'set_trigger_manual': _operation('set_trigger_manual'),
    'set_schedule_interval': _operation('set_schedule_interval', {
        'unit': {'enum': list(WORKFLOW_SCHEDULE_UNITS)},
        'value': {'type': 'integer', 'minimum': 1, 'maximum': 59},
    }, ['unit', 'value'], [
        _when('unit', 'hours', {'properties': {'value': {'maximum': 24}}}),
    ]),
    'set_schedule_calendar': _operation('set_schedule_calendar', {
        'frequency': {'enum': list(WORKFLOW_SCHEDULE_FREQUENCIES)},
        'days_of_week': {'type': 'array', 'minItems': 1, 'maxItems': 7, 'uniqueItems': True,
                         'items': {'enum': list(WORKFLOW_SCHEDULE_DAYS)}},
        'day_of_month': {'type': 'integer', 'minimum': 1, 'maximum': 31},
        'time_of_day': {'type': 'string', 'pattern': TIME_OF_DAY_PATTERN},
        'timezone': _str(ASSIST_TIMEZONE_MAX_LENGTH),
    }, ['frequency', 'time_of_day'], [
        _when('frequency', 'weekly', {'required': ['days_of_week'], **_forbid('day_of_month')}),
        _when('frequency', 'monthly', {'required': ['day_of_month'], **_forbid('days_of_week')}),
        {'if': {'required': ['frequency'], 'properties': {'frequency': {'enum': ['daily', 'weekdays']}}},
         'then': _forbid('days_of_week', 'day_of_month')},
    ]),
    'set_alert_mode': _operation('set_alert_mode', {
        'mode': {'enum': ['off', 'every_run', 'rules']},
        'priority': {'enum': list(ASSIST_ALERT_PRIORITIES)},
    }, ['mode'], [
        {'if': {'required': ['mode'], 'properties': {'mode': {'not': {'const': 'every_run'}}}}, 'then': _forbid('priority')},
    ]),
    'add_alert_rule': _operation('add_alert_rule', {
        'name': _str(ASSIST_ALERT_NAME_MAX_LENGTH, min_length=0),
        'severity': {'enum': list(ASSIST_ALERT_SEVERITIES)},
        'delivery': {'enum': list(ASSIST_ALERT_DELIVERIES)},
        'scope': {
            'type': 'object', 'additionalProperties': False, 'required': ['type'],
            'properties': {'type': {'enum': list(ASSIST_ALERT_SCOPES)}, 'task': _TASK},
            'allOf': [
                _when('type', 'task', {'required': ['task']}),
                {'if': {'required': ['type'], 'properties': {'type': {'not': {'const': 'task'}}}}, 'then': _forbid('task')},
            ],
        },
        'condition': _CONDITION,
    }, ['severity', 'condition']),
    'remove_alert_rule': _operation('remove_alert_rule', {'rule': _handle(ALERT_HANDLE_PATTERN)}, ['rule']),
    'set_workflow_runner': _operation('set_workflow_runner', {
        'runner': {'enum': ['agent', 'model']},
        'agent': _handle(AGENT_HANDLE_PATTERN),
        'model': _handle(WORKFLOW_MODEL_HANDLE_PATTERN),
    }, ['runner'], [
        _when('runner', 'agent', {'required': ['agent'], **_forbid('model')}),
        _when('runner', 'model', {'required': ['model'], **_forbid('agent')}),
    ]),
    'set_task_runner': _operation('set_task_runner', {
        'task': _TASK,
        'runner': {'enum': ['inherit', 'agent', 'model']},
        'agent': _handle(AGENT_HANDLE_PATTERN),
        'model': _handle(MODEL_HANDLE_PATTERN),
    }, ['task', 'runner'], [
        _when('runner', 'inherit', _forbid('agent', 'model')),
        _when('runner', 'agent', {'required': ['agent'], **_forbid('model')}),
        _when('runner', 'model', {'required': ['model'], **_forbid('agent')}),
    ]),
    'add_task': _operation('add_task', {
        'key': _handle(NEW_TASK_KEY_PATTERN),
        'name': _str(ASSIST_TASK_NAME_MAX_LENGTH),
        'instructions': _str(ASSIST_TASK_INSTRUCTIONS_MAX_LENGTH),
        'after': _handle(TASK_POSITION_PATTERN),
    }, ['key', 'name', 'instructions']),
    'remove_task': _operation('remove_task', {'task': _TASK}, ['task']),
    'move_task': _operation('move_task', {'task': _TASK, 'after': _handle(TASK_POSITION_PATTERN)}, ['task', 'after']),
    'set_task_name': _operation('set_task_name', {'task': _TASK, 'name': _str(ASSIST_TASK_NAME_MAX_LENGTH)}, ['task', 'name']),
    'set_task_instructions': _operation('set_task_instructions', {
        'task': _TASK, 'instructions': _str(ASSIST_TASK_INSTRUCTIONS_MAX_LENGTH),
    }, ['task', 'instructions']),
    'set_task_inputs': _operation('set_task_inputs', {
        'task': _TASK,
        'mode': {'enum': ['auto', 'none', 'tasks']},
        'from': _handles(ASSIST_MAX_TASKS, TASK_HANDLE_PATTERN),
    }, ['task', 'mode'], [
        _when('mode', 'tasks', {'required': ['from']}),
        {'if': {'required': ['mode'], 'properties': {'mode': {'not': {'const': 'tasks'}}}}, 'then': _forbid('from')},
    ]),
    'bind_reference': _operation('bind_reference', {
        'document': _handle(),
        'tasks': {'oneOf': [{'const': 'all'}, _handles(ASSIST_MAX_TASKS, TASK_HANDLE_PATTERN)]},
    }, ['document', 'tasks']),
    'set_task_references': _operation('set_task_references', {
        'task': _TASK,
        'mode': {'enum': ['all', 'none', 'selected']},
        'references': _handles(ASSIST_MAX_REFERENCES),
    }, ['task', 'mode'], [
        _when('mode', 'selected', {'required': ['references']}),
        {'if': {'required': ['mode'], 'properties': {'mode': {'not': {'const': 'selected'}}}}, 'then': _forbid('references')},
    ]),
    'unbind_reference': _operation('unbind_reference', {'reference': _handle()}, ['reference']),
    'set_task_document_target': _operation('set_task_document_target', {
        'task': _TASK,
        'action': {'enum': ['analyze', 'search', 'comparison']},
        'documents': _handles(ASSIST_MAX_TARGET_DOCUMENTS),
        'left': _handle(),
        'right': _handles(ASSIST_MAX_TARGET_DOCUMENTS - 1),
        'search_mode': {'enum': ['selected', 'relevance']},
        'analysis_mode': {'enum': ['combined', 'per_document']},
    }, ['task', 'action'], [
        _when('action', 'comparison', {'required': ['left', 'right'], **_forbid('documents', 'search_mode', 'analysis_mode')}),
        _when('action', 'analyze', {'required': ['documents'], **_forbid('left', 'right', 'search_mode')}),
        _when('action', 'search', _forbid('left', 'right')),
        {'if': {'required': ['action', 'search_mode'], 'properties': {'action': {'const': 'search'}, 'search_mode': {'const': 'relevance'}}},
         'then': _forbid('documents')},
        {'if': {'required': ['action'], 'properties': {'action': {'const': 'search'}},
                'not': {'required': ['search_mode'], 'properties': {'search_mode': {'const': 'relevance'}}}},
         'then': {'required': ['documents']}},
    ]),
    'clear_task_document_target': _operation('clear_task_document_target', {'task': _TASK}, ['task']),
}
OPERATION_NAMES = tuple(OPERATION_SCHEMAS)

ENVELOPE_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['outcome', 'reply'],
    'properties': {
        'outcome': {'enum': list(ASSIST_OUTCOMES)},
        'reply': {'type': 'string', 'minLength': 1, 'maxLength': ASSIST_REPLY_MAX_LENGTH, 'pattern': TEXT_PATTERN},
        'operations': {
            'type': 'array', 'maxItems': ASSIST_MAX_OPERATIONS,
            'items': {'type': 'object', 'required': ['op'], 'properties': {'op': {'enum': list(OPERATION_NAMES)}}},
        },
        'email_tasks': _handles(ASSIST_MAX_TASKS, TASK_HANDLE_PATTERN) | {'minItems': 0},
    },
    'allOf': [
        {'if': {'properties': {'outcome': {'const': 'changed'}}},
         'then': {'required': ['operations'], 'properties': {'operations': {'minItems': 1}}},
         'else': {'properties': {'operations': {'maxItems': 0}, 'email_tasks': {'maxItems': 0}}}},
    ],
}

_ENVELOPE_VALIDATOR = Draft202012Validator(ENVELOPE_SCHEMA)
_OPERATION_VALIDATORS = {name: Draft202012Validator(schema) for name, schema in OPERATION_SCHEMAS.items()}
_MAX_SCHEMA_ERRORS = 12
_TYPE_NAMES = {'string': 'text', 'integer': 'a whole number', 'array': 'a list', 'object': 'an object', 'boolean': 'true or false'}


def operation_schema_catalog():
    """The allowlist as the system message shows it: each operation's JSON schema."""
    return copy.deepcopy(OPERATION_SCHEMAS)


def _field_path(error):
    parts = [str(part) if isinstance(part, str) else f'[{part}]' for part in error.absolute_path]
    text = ''
    for part in parts:
        text = f'{text}{part}' if part.startswith('[') or not text else f'{text}.{part}'
    return text


def _schema_error_message(error):
    """A message built only from the schema and the instance's schema-defined keys: never its values."""
    field = _field_path(error)
    subject = f'Field {field}' if field else 'The value'
    keyword = error.validator
    value = error.validator_value
    if keyword == 'required':
        instance = error.instance if isinstance(error.instance, dict) else {}
        missing = [name for name in value if name not in instance]
        names = ', '.join(missing) or 'a required field'
        return f'{subject} is missing {names}.'
    if keyword == 'additionalProperties':
        allowed = ', '.join(sorted(error.schema.get('properties') or {}))
        return f'{subject} has a field it does not accept. Use only: {allowed}.'
    if keyword == 'not':
        inner = value.get('anyOf') if isinstance(value, dict) else None
        names = [item['required'][0] for item in inner] if isinstance(inner, list) else (value.get('required') or [])
        return f'{subject} must not include {", ".join(names)} with these choices.'
    if keyword == 'enum':
        return f'{subject} must be one of: {", ".join(str(item) for item in value)}.'
    if keyword == 'const':
        return f'{subject} must be {value}.'
    if keyword == 'type':
        return f'{subject} must be {_TYPE_NAMES.get(value, value)}.'
    if keyword == 'pattern':
        if value == TEXT_PATTERN:
            return f'{subject} must not be blank.'
        if value == TIME_OF_DAY_PATTERN:
            return f'{subject} must be a 24-hour time such as 07:00.'
        if value in _HANDLE_PATTERNS:
            return f'{subject} must be a handle from the draft or choices.'
        return f'{subject} has an invalid format.'
    if keyword in ('minLength', 'maxLength'):
        return f'{subject} must be {"at least" if keyword == "minLength" else "at most"} {value} characters.'
    if keyword in ('minItems', 'maxItems'):
        return f'{subject} must have {"at least" if keyword == "minItems" else "at most"} {value} items.'
    if keyword == 'uniqueItems':
        return f'{subject} must not repeat an item.'
    if keyword in ('minimum', 'maximum'):
        return f'{subject} must be {"at least" if keyword == "minimum" else "at most"} {value}.'
    if keyword == 'oneOf':
        return f'{subject} must be "all" or a list of task handles.'
    return f'{subject} is not valid.'


# ---------------------------------------------------------------------------
# Applying operations
# ---------------------------------------------------------------------------

class AssistApplyContext:
    """Facts the operations are applied against, besides the draft and its handles.

    ``time_zone`` is the request's IANA time zone, already validated, or None. ``stored_workflow``
    is the saved record of a saved base, or None for a new draft. The schedule minimum exempts the
    interval it already runs on, and a new reference never reuses one of its reference IDs for a
    different document.
    """

    def __init__(self, *, time_zone=None, stored_workflow=None):
        self.time_zone = time_zone if isinstance(time_zone, str) and time_zone else None
        self.stored_workflow = stored_workflow if isinstance(stored_workflow, dict) else None


def _new_uuid():
    return str(uuid.uuid4())


def _same_number(value, expected):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == expected


def _unique_name(base, taken, limit=ASSIST_ALIAS_MAX_LENGTH):
    """``base``, else ``base_2``, ``base_3``… within ``limit``, unused by ``taken`` in any letter case."""
    folded = {name.casefold() for name in taken if isinstance(name, str)}
    if base.casefold() not in folded:
        return base
    counter = 2
    while True:
        suffix = f'_{counter}'
        name = f'{base[:limit - len(suffix)]}{suffix}'
        if name.casefold() not in folded:
            return name
        counter += 1


def _producer_kind(task):
    """``producer.output_contract?.kind ?? 'any'``."""
    contract = task.get('output_contract')
    kind = contract.get('kind') if isinstance(contract, dict) else None
    return 'any' if kind is None else kind


def _is_legacy_binding(value):
    """``isLegacyWorkflowBinding``: a classic task input names the task it reads."""
    return isinstance(value, dict) and 'task_id' in value


def _invalid_input_pairs(workflow):
    """``(consumer, producer)`` pairs whose producer is missing or does not come first."""
    tasks = _rows(workflow.get('tasks'))
    positions = {task.get('id'): index for index, task in enumerate(tasks) if isinstance(task.get('id'), str)}
    pairs = set()
    for index, task in enumerate(tasks):
        inputs = task.get('inputs')
        for binding in inputs if isinstance(inputs, list) else []:
            if not _is_legacy_binding(binding):
                continue
            producer_id = binding.get('task_id')
            producer = positions.get(producer_id) if isinstance(producer_id, str) else None
            if producer is None or producer >= index:
                pairs.add((str(task.get('id')), json.dumps(producer_id, sort_keys=True, default=str)))
    return pairs


class _Applier:
    """Applies operations, in order, to a deep copy of the draft."""

    def __init__(self, draft, handles, context):
        self.draft = draft
        self.handles = handles
        self.context = context
        self.user_id = handles.user_id
        self.candidate = copy.deepcopy(draft)
        self.structured = handles.structured
        self.max_tasks = assist_max_tasks(handles.options)
        schedule = handles.options.get('schedule') if isinstance(handles.options.get('schedule'), dict) else {}
        minimum = schedule.get('min_interval_seconds')
        self.min_interval_seconds = minimum if _is_int(minimum) and minimum > 0 else 0
        self.new_tasks = {}
        self.added_tasks = []
        self.removed_tasks = set()
        self.touched_tasks = set()
        self.new_references = []
        self.removed_references = []
        self.placed = set()
        self.alert_settings = None
        self.alert_rules = None
        self.added_rules = 0
        self.email_tasks = []

    # -- lookups ---------------------------------------------------------

    def _tasks(self):
        return self.candidate['tasks']

    def _task_index(self, task_id):
        for index, task in enumerate(self._tasks()):
            if task.get('id') == task_id:
                return index
        return -1

    def _task_id(self, handle):
        if handle.startswith('new_'):
            task_id = self.new_tasks.get(handle)
            if task_id is None:
                raise _OperationError('It names a new task that no earlier add_task created.')
        else:
            target = self.handles.resolve(handle)
            if target is None or target[0] != 'task':
                raise _OperationError('It names a task that is not in the draft.')
            task_id = target[1]
        if task_id in self.removed_tasks:
            raise _OperationError('It names a task that an earlier operation removed.')
        return task_id

    def _task(self, handle):
        task_id = self._task_id(handle)
        index = self._task_index(task_id)
        if index < 0:
            raise _OperationError('It names a task that is not in the draft.')
        return index, self._tasks()[index]

    def _renumber(self):
        # workflowTasksInOrder: renumber only the tasks whose order no longer matches.
        for position, task in enumerate(self._tasks(), start=1):
            if not _same_number(task.get('order'), position):
                task['order'] = position

    def _agent(self, handle):
        target = self.handles.resolve(handle)
        if target is None or target[0] != 'agent':
            raise _OperationError('It names an agent that is not one of the choices.')
        return target[1]

    def _model(self, handle):
        target = self.handles.resolve(handle)
        if handle == 'default_model':
            if target is None:
                raise _OperationError('The default model is not available here. Choose one of the models.')
            return None
        if target is None or target[0] != 'model':
            raise _OperationError('It names a model that is not one of the choices.')
        return target[1]

    def _references(self):
        references = self.candidate.get('reference_inputs')
        if not isinstance(references, list):
            references = []
            self.candidate['reference_inputs'] = references
        return references

    def _reference_by_id(self, reference_id):
        return next((item for item in _rows(self.candidate.get('reference_inputs')) if item.get('id') == reference_id), None)

    def _reference_for_identity(self, identity):
        return next(
            (item for item in _rows(self.candidate.get('reference_inputs'))
             if reference_identity(item, self.user_id) == identity),
            None,
        )

    def _document(self, handle):
        """``(identity, reference or None, label)`` for a document handle the model sent."""
        target = self.handles.resolve(handle)
        if target is None or target[0] not in ('reference', 'document'):
            raise _OperationError('It names a document that is not in the draft or the request.')
        if target[0] == 'reference':
            reference = self._reference_by_id(target[1])
            if reference is None:
                raise _OperationError('It names a shared reference that an earlier operation removed.')
            return reference_identity(reference, self.user_id), reference, ''
        entry = self.handles.documents.get(self.handles.identity_handles.get(target[1])) or {}
        return target[1], self._reference_for_identity(target[1]), entry.get('file_label') or ''

    @staticmethod
    def _known_scope(identity):
        if identity[0] == UNKNOWN_SCOPE:
            raise _OperationError(
                'The workspace of that document is not known, so the assistant cannot place it. '
                'Ask the user to add it with the document picker.'
            )
        return identity

    @staticmethod
    def _set(record, field, value):
        if field in record and same_editor_value(record[field], value):
            return False
        record[field] = value
        return True

    # -- workflow ----------------------------------------------------------

    def op_set_name(self, op):
        self._set(self.candidate, 'name', model_text(op['name'], 'The name', ASSIST_WORKFLOW_NAME_MAX_LENGTH))

    def op_set_description(self, op):
        description = model_text(
            op['description'], 'The description', ASSIST_WORKFLOW_DESCRIPTION_MAX_LENGTH, multiline=True, required=False,
        )
        self._set(self.candidate, 'description', description)

    # -- trigger and schedule ---------------------------------------------

    def _check_trigger_editable(self, *, schedule=True):
        trigger_type = self.candidate.get('trigger_type')
        if trigger_type == 'file_sync':
            raise _OperationError('This workflow runs on File Sync changes, which the assistant cannot change yet.')
        if schedule and trigger_type == 'interval' and workflow_schedule_for_editor(self.candidate.get('schedule')) is None:
            raise _OperationError('The current schedule uses options the editor cannot show, so the assistant cannot change it.')

    def _current_calendar_timezone(self):
        schedule = workflow_schedule_for_editor(self.candidate.get('schedule'))
        if schedule and schedule.get('kind') == 'calendar' and schedule['timezone'] in workflow_schedule_timezones():
            return schedule['timezone']
        return None

    def _set_schedule(self, schedule):
        try:
            normalized = normalize_workflow_schedule(schedule)
            if self.min_interval_seconds and workflow_schedule_minimum_applies(normalized, self.context.stored_workflow):
                enforce_workflow_schedule_minimum(normalized, self.min_interval_seconds)
        except WorkflowPublicValidationError as exc:
            # Schedule messages name only fixed limits and choices, never the value sent.
            raise _OperationError(str(exc)) from None
        self._set(self.candidate, 'trigger_type', 'interval')
        self._set(self.candidate, 'schedule', schedule)

    def op_set_trigger_manual(self, op):
        # The trigger select changes only trigger_type and keeps the schedule.
        self._check_trigger_editable(schedule=False)
        self._set(self.candidate, 'trigger_type', 'manual')

    def op_set_schedule_interval(self, op):
        self._check_trigger_editable()
        current = self.candidate.get('schedule')
        shown = workflow_schedule_for_editor(current)
        # The editor edits an interval in place and starts a fresh one when leaving a calendar schedule.
        base = current if isinstance(current, dict) and shown is not None and shown.get('kind') != 'calendar' else {}
        self._set_schedule({**base, 'unit': op['unit'], 'value': op['value']})

    def op_set_schedule_calendar(self, op):
        self._check_trigger_editable()
        if 'timezone' in op:
            timezone = model_text(op['timezone'], 'The time zone', ASSIST_TIMEZONE_MAX_LENGTH)
            if timezone not in workflow_schedule_timezones():
                raise _OperationError('The time zone must be an IANA time zone name, such as America/New_York.')
        else:
            # changeRepeats keeps a calendar schedule's time zone, else uses the browser's.
            timezone = self._current_calendar_timezone() or self.context.time_zone
            if not timezone:
                raise _OperationError('No time zone is known for this schedule. Ask the user which time zone to use.')
        frequency = op['frequency']
        days = op.get('days_of_week') or []
        self._set_schedule({
            'kind': 'calendar',
            'frequency': frequency,
            'days_of_week': [day for day in WORKFLOW_SCHEDULE_DAYS if day in days] if frequency == 'weekly' else [],
            'day_of_month': op['day_of_month'] if frequency == 'monthly' else None,
            'time_of_day': op['time_of_day'],
            'timezone': timezone,
        })

    # -- alerts ------------------------------------------------------------

    def _alerts(self):
        # workflowAlertsEdited: the first alert edit works on all four fields of the resolved config.
        if self.alert_settings is None:
            config = workflow_alert_config(self.candidate)
            self.alert_settings = {
                'alert_mode': config['alert_mode'],
                'alert_priority': config['alert_priority'],
                'alert_evaluation': copy.deepcopy(config['alert_evaluation']),
            }
            self.alert_rules = [(index, copy.deepcopy(rule)) for index, rule in enumerate(config['alert_rules'])]
        return self.alert_settings

    def op_set_alert_mode(self, op):
        settings = self._alerts()
        settings['alert_mode'] = op['mode']
        if 'priority' in op:
            settings['alert_priority'] = op['priority']

    def _alert_condition(self, raw):
        condition_type = raw['type']
        if condition_type in ('run_status', 'task_status'):
            return {'type': condition_type, 'statuses': list(raw['statuses'])}
        if condition_type == 'text_match':
            if raw['mode'] == 'regex':
                pattern = model_text(raw['pattern'], 'The pattern', ASSIST_ALERT_REGEX_MAX_LENGTH)
                return {'type': condition_type, 'mode': 'regex', 'pattern': pattern, 'values': [], 'case_sensitive': False}
            values = []
            for value in raw['values']:
                text = model_text(value, 'Each match value', ASSIST_ALERT_VALUE_MAX_LENGTH)
                if text not in values:
                    values.append(text)
            return {
                'type': condition_type, 'mode': raw['mode'], 'values': values,
                'case_sensitive': raw.get('case_sensitive') is True,
            }
        if condition_type == 'model_evaluation':
            prompt = model_text(raw['prompt'], 'The condition', ASSIST_ALERT_PROMPT_MAX_LENGTH, multiline=True)
            return {'type': condition_type, 'prompt': prompt}
        if condition_type == 'agent_signal':
            return {
                'type': condition_type,
                'signal_name': model_text(raw.get('signal_name', ''), 'The signal name', ASSIST_ALERT_NAME_MAX_LENGTH,
                                          required=False),
                'min_severity': raw.get('min_severity', 'info'),
            }
        return {'type': condition_type}

    def op_add_alert_rule(self, op):
        self._alerts()
        condition = self._alert_condition(op['condition'])
        scope = op.get('scope') or {'type': 'final'}
        if condition['type'] in ASSIST_SCOPELESS_CONDITIONS and scope['type'] != 'final':
            raise _OperationError('Run status and agent signal rules watch the whole run, so their scope must be final.')
        task_id = self._task_id(scope['task']) if scope['type'] == 'task' else ''
        # newWorkflowAlertRule's shape, with the model's choices.
        self.alert_rules.append((None, {
            'id': _new_uuid(),
            'name': model_text(op.get('name', ''), 'The rule name', ASSIST_ALERT_NAME_MAX_LENGTH, required=False),
            'enabled': True,
            'severity': op['severity'],
            'delivery': op.get('delivery', 'default'),
            'scope': {'type': scope['type'], 'task_id': task_id},
            'condition': condition,
        }))
        self.added_rules += 1

    def op_remove_alert_rule(self, op):
        self._alerts()
        target = self.handles.resolve(op['rule'])
        if target is None or target[0] != 'alert':
            raise _OperationError('It names an alert rule that is not in the draft.')
        for position, (index, _rule) in enumerate(self.alert_rules):
            if index == target[1]:
                del self.alert_rules[position]
                return
        raise _OperationError('It names an alert rule that an earlier operation removed.')

    # -- runners -----------------------------------------------------------

    def op_set_workflow_runner(self, op):
        if op['runner'] == 'agent':
            agent = self._agent(op['agent'])
            current = self.candidate.get('selected_agent')
            # The runner select changes only runner_type; the agent picker writes the chosen option.
            if not (isinstance(current, dict) and _agent_key(current) == _agent_key(agent)):
                self.candidate['selected_agent'] = copy.deepcopy(agent)
            self._set(self.candidate, 'runner_type', 'agent')
            return
        model = self._model(op['model'])
        self._set(self.candidate, 'runner_type', 'model')
        self._set(self.candidate, 'model_endpoint_id', '' if model is None else model['endpoint_id'])
        self._set(self.candidate, 'model_id', '' if model is None else model['model_id'])

    def op_set_task_runner(self, op):
        _index, task = self._task(op['task'])
        if js_truthy(task.get('publication')):
            raise _OperationError('A publication task has no runner to change.')
        current = task.get('runner') if isinstance(task.get('runner'), dict) else {}
        runner_type = op['runner']
        # TaskRunnerFields writes a fresh runner of the chosen type.
        if runner_type == 'inherit':
            if current.get('type') == 'inherit':
                return
            runner = {'type': 'inherit'}
        elif runner_type == 'agent':
            agent = self._agent(op['agent'])
            selected = current.get('selected_agent')
            if current.get('type') == 'agent' and isinstance(selected, dict) and _agent_key(selected) == _agent_key(agent):
                return
            runner = {'type': 'agent', 'selected_agent': copy.deepcopy(agent)}
        else:
            model = self._model(op['model'])
            if (current.get('type') == 'model' and current.get('model_endpoint_id') == model['endpoint_id']
                    and current.get('model_id') == model['model_id']):
                return
            runner = {'type': 'model', 'model_endpoint_id': model['endpoint_id'], 'model_id': model['model_id']}
        task['runner'] = runner
        self.touched_tasks.add(task['id'])

    # -- tasks -------------------------------------------------------------

    def _refuse_structured(self):
        if self.structured:
            raise _OperationError(
                'This workflow is a flow. Only the flow editor adds, removes, moves or connects its tasks.'
            )

    def _position_after(self, handle, moving_id=None):
        if handle == 'start':
            return 0
        task_id = self._task_id(handle)
        if task_id == moving_id:
            raise _OperationError('A task cannot be placed after itself.')
        index = self._task_index(task_id)
        if index < 0:
            raise _OperationError('It names a task that is not in the draft.')
        return index + 1

    def op_add_task(self, op):
        self._refuse_structured()
        key = op['key']
        if key in self.new_tasks:
            raise _OperationError('Each add_task needs its own key.')
        tasks = self._tasks()
        if len(tasks) >= self.max_tasks:
            raise _OperationError(f'A workflow can have at most {self.max_tasks} tasks.')
        position = self._position_after(op['after']) if 'after' in op else len(tasks)
        task = create_workflow_task(len(tasks))
        task['id'] = _new_uuid()
        task['name'] = model_text(op['name'], 'The task name', ASSIST_TASK_NAME_MAX_LENGTH)
        task['instructions'] = model_text(
            op['instructions'], 'The instructions', ASSIST_TASK_INSTRUCTIONS_MAX_LENGTH, multiline=True,
        )
        tasks.insert(position, task)
        self._renumber()
        self.new_tasks[key] = task['id']
        self.added_tasks.append(task['id'])
        self.touched_tasks.add(task['id'])

    def op_remove_task(self, op):
        self._refuse_structured()
        index, task = self._task(op['task'])
        tasks = self._tasks()
        if len(tasks) <= 1:
            raise _OperationError('A workflow needs at least one task.')
        if task.get('approval') is not None:
            raise _OperationError('The task has an approval step, which only the user can remove.')
        del tasks[index]
        self._renumber()
        self.removed_tasks.add(task['id'])
        self.touched_tasks.discard(task['id'])
        # A later task's inputs from the removed task go with it.
        for other in tasks:
            inputs = other.get('inputs')
            if isinstance(inputs, list) and any(_is_legacy_binding(item) and item.get('task_id') == task['id'] for item in inputs):
                other['inputs'] = [
                    item for item in inputs if not (_is_legacy_binding(item) and item.get('task_id') == task['id'])
                ]

    def op_move_task(self, op):
        self._refuse_structured()
        index, task = self._task(op['task'])
        target = self._position_after(op['after'], moving_id=task['id'])
        tasks = self._tasks()
        del tasks[index]
        tasks.insert(target - 1 if target > index else target, task)
        self._renumber()

    def op_set_task_name(self, op):
        _index, task = self._task(op['task'])
        self._set(task, 'name', model_text(op['name'], 'The task name', ASSIST_TASK_NAME_MAX_LENGTH))

    def op_set_task_instructions(self, op):
        _index, task = self._task(op['task'])
        instructions = model_text(op['instructions'], 'The instructions', ASSIST_TASK_INSTRUCTIONS_MAX_LENGTH, multiline=True)
        if self._set(task, 'instructions', instructions):
            self.touched_tasks.add(task['id'])

    def op_set_task_inputs(self, op):
        self._refuse_structured()
        _index, task = self._task(op['task'])
        inputs = task.get('inputs')
        mode = op['mode']
        # TaskInputs: automatic removes the field, none is an empty list, and bound tasks are listed.
        if mode == 'auto':
            if inputs is not None:
                del task['inputs']
            return
        if mode == 'none':
            if not (isinstance(inputs, list) and not inputs):
                task['inputs'] = []
            return
        producers = []
        for handle in op['from']:
            producer_id = self._task_id(handle)
            if producer_id == task['id']:
                raise _OperationError('A task cannot take input from itself.')
            if producer_id not in producers:
                producers.append(producer_id)
        existing = [item for item in inputs if _is_legacy_binding(item)] if isinstance(inputs, list) else []
        bindings = [item for item in existing if item.get('task_id') in producers]
        bound = {item.get('task_id') for item in bindings}
        names = [item.get('name') for item in bindings]
        for producer_id in producers:
            if producer_id in bound:
                continue
            producer = self._tasks()[self._task_index(producer_id)]
            # The editor does not keep input names unique; the save requires it, so a repeat gets a suffix.
            name = _unique_name(safe_workflow_alias(producer.get('name'), 'input'), names)
            names.append(name)
            bindings.append({
                'name': name, 'task_id': producer_id, 'output': 'authoritative', 'required': True,
                'expected_kind': _producer_kind(producer),
            })
        if not (isinstance(inputs, list) and same_editor_value(inputs, bindings)):
            task['inputs'] = bindings

    # -- documents ---------------------------------------------------------

    def _new_reference(self, identity, label):
        references = self._references()
        if len(references) >= ASSIST_MAX_REFERENCES:
            raise _OperationError(f'A workflow can have at most {ASSIST_MAX_REFERENCES} shared references.')
        scope_type, scope_id, document_id = identity
        name = _unique_name(safe_workflow_alias(label, 'reference'), [item.get('name') for item in _rows(references)])
        # The picker's ID, unless it is too long or another document already uses it.
        taken = {item.get('id') for item in _rows(references)}
        stored = self.context.stored_workflow or {}
        taken.update(
            item.get('id') for item in _rows(stored.get('reference_inputs'))
            if reference_identity(item, self.user_id) != identity
        )
        reference_id = f'{scope_type}:{scope_id}:{document_id}'
        if len(reference_id) > ASSIST_REFERENCE_ID_MAX_LENGTH or reference_id in taken:
            reference_id = _new_uuid()
        reference = {
            'id': reference_id, 'name': name, 'document_id': document_id, 'scope_type': scope_type, 'scope_id': scope_id,
        }
        references.append(reference)
        self.new_references.append(reference_id)
        return reference

    def op_bind_reference(self, op):
        identity, reference, label = self._document(op['document'])
        created = reference is None
        if created:
            reference = self._new_reference(self._known_scope(identity), label)
        reference_id = reference['id']
        if op['tasks'] == 'all':
            listed = None
        else:
            listed = {self._task_id(handle) for handle in op['tasks']}
        others = [item.get('id') for item in _rows(self.candidate.get('reference_inputs')) if item is not reference]
        for task in self._tasks():
            reference_ids = task.get('reference_ids')
            if listed is None or task['id'] in listed:
                if isinstance(reference_ids, list) and reference_id not in reference_ids:
                    task['reference_ids'] = [*reference_ids, reference_id]
            elif created and reference_ids is None:
                # A task reading every reference keeps reading only the ones it had.
                task['reference_ids'] = list(others)
        self.placed.add(identity)

    def op_set_task_references(self, op):
        _index, task = self._task(op['task'])
        current = task.get('reference_ids')
        mode = op['mode']
        if mode == 'all':
            if 'reference_ids' in task and current is not None:
                del task['reference_ids']
            return
        if mode == 'none':
            if not (isinstance(current, list) and not current):
                task['reference_ids'] = []
            return
        selected = []
        for handle in op['references']:
            identity, reference, _label = self._document(handle)
            if reference is None:
                raise _OperationError('It names a document that is not a shared reference. Use bind_reference first.')
            if reference['id'] not in selected:
                selected.append(reference['id'])
            self.placed.add(identity)
        if not (isinstance(current, list) and same_editor_value(current, selected)):
            task['reference_ids'] = selected

    def op_unbind_reference(self, op):
        _identity, reference, _label = self._document(op['reference'])
        if reference is None:
            raise _OperationError('It names a document that is not a shared reference.')
        references = self._references()
        for position, item in enumerate(references):
            if item is reference:
                del references[position]
                break
        for task in self._tasks():
            reference_ids = task.get('reference_ids')
            if isinstance(reference_ids, list) and reference['id'] in reference_ids:
                task['reference_ids'] = [item for item in reference_ids if item != reference['id']]
        self.removed_references.append(reference['id'])

    def _check_document_target(self, task):
        if js_truthy(task.get('publication')):
            raise _OperationError('A publication task has no document action.')
        mode = document_action_mode(task.get('document_action'))
        if mode == 'current_item':
            raise _OperationError('The task analyzes the current loop document, which only the flow editor changes.')
        if mode == 'preserve':
            raise _OperationError('The task has an advanced document action that the assistant cannot change.')

    def _target_identity(self, handle):
        identity, _reference, _label = self._document(handle)
        return self._known_scope(identity)

    def op_set_task_document_target(self, op):
        _index, task = self._task(op['task'])
        self._check_document_target(task)
        current = task.get('document_action')
        current_mode = current.get('analysis_mode') if isinstance(current, dict) else None
        analysis_mode = op.get('analysis_mode') or (current_mode if current_mode in ('combined', 'per_document') else 'combined')
        action = op['action']
        if action == 'comparison':
            left = self._target_identity(op['left'])
            right = []
            for handle in op['right']:
                identity = self._target_identity(handle)
                if identity == left:
                    raise _OperationError('The left document cannot also be a right document.')
                if identity not in right:
                    right.append(identity)
            new_action = comparison_action_from_selection(left, right)
            placed = [left, *right]
        elif action == 'search' and op.get('search_mode') == 'relevance':
            new_action = document_action_from_selection('search', [], relevance=True, analysis_mode=analysis_mode)
            placed = []
        else:
            placed = []
            for handle in op['documents']:
                identity = self._target_identity(handle)
                if identity not in placed:
                    placed.append(identity)
            new_action = document_action_from_selection(action, placed, analysis_mode=analysis_mode)
        if not (isinstance(current, dict) and same_editor_value(current, new_action)):
            task['document_action'] = new_action
            self.touched_tasks.add(task['id'])
        self.placed.update(placed)

    def op_clear_task_document_target(self, op):
        _index, task = self._task(op['task'])
        self._check_document_target(task)
        if document_action_mode(task.get('document_action')) != 'none':
            task['document_action'] = {'type': 'none'}
            self.touched_tasks.add(task['id'])

    # -- finishing ---------------------------------------------------------

    def finish(self, output):
        """End-of-apply checks, then the alert fields; returns problems as server-authored messages."""
        messages = []
        if self.alert_settings is not None:
            messages.extend(self._finish_alerts())
            rules = [rule for _index, rule in self.alert_rules]
        else:
            rules = workflow_alert_config(self.candidate)['alert_rules']
        if self.removed_tasks and any(self._watches_removed_task(rule) for rule in rules):
            messages.append('An alert rule watches a task that this reply removes. Remove that rule too, or keep the task.')
        if not self.structured and _invalid_input_pairs(self.candidate) - _invalid_input_pairs(self.draft):
            messages.append('A task takes input from a task that is missing or comes after it. Inputs must come from earlier tasks.')
        for handle in output.get('email_tasks') or []:
            try:
                task_id = self._task_id(handle)
            except _OperationError:
                messages.append('email_tasks names a task that is not in the changed workflow.')
                break
            if task_id not in self.email_tasks:
                self.email_tasks.append(task_id)
        return messages

    def _watches_removed_task(self, rule):
        scope = rule.get('scope') if isinstance(rule, dict) else None
        return isinstance(scope, dict) and scope.get('type') == 'task' and scope.get('task_id') in self.removed_tasks

    def _finish_alerts(self):
        settings = self.alert_settings
        rules = [rule for _index, rule in self.alert_rules]
        messages = []
        if self.added_rules and settings['alert_mode'] != 'rules':
            messages.append('Alert rules only send alerts when the alert mode is rules. Set the mode to rules, or leave the rule out.')
        if settings['alert_mode'] == 'every_run' and settings['alert_priority'] == 'none':
            messages.append('Alerts on every run need a priority: low, medium or high.')
        if settings['alert_mode'] == 'rules' and not rules:
            messages.append('The rules alert mode needs at least one alert rule.')
        if len(rules) > ASSIST_ALERT_MAX_RULES:
            messages.append(f'A workflow can have at most {ASSIST_ALERT_MAX_RULES} alert rules.')
        final = {
            'alert_mode': settings['alert_mode'], 'alert_priority': settings['alert_priority'],
            'alert_rules': rules, 'alert_evaluation': settings['alert_evaluation'],
        }
        # Nothing is written when the alerts end up as they began.
        if not messages and not same_editor_value(final, workflow_alert_config(self.draft)):
            self.candidate.update(copy.deepcopy(final))
        return messages

    def info(self):
        task_order = [task['id'] for task in self._tasks()]
        return {
            'added_tasks': [task_id for task_id in self.added_tasks if task_id not in self.removed_tasks],
            'removed_tasks': [task['id'] for task in _rows(self.draft.get('tasks')) if task.get('id') in self.removed_tasks],
            'touched_tasks': [task_id for task_id in task_order if task_id in self.touched_tasks],
            'new_references': [item for item in self.new_references if item not in self.removed_references],
            'placed_documents': set(self.placed),
            'email_tasks': list(self.email_tasks),
        }


def apply_assist_operations(draft, output, handles, context):
    """Apply a schema-valid reply's operations to a deep copy of ``draft``.

    Returns ``(candidate, info)``. The candidate is the draft with only the operations' changes:
    it is not normalized, so it differs from the draft exactly where an operation changed it.
    Raises ``AssistApplyError`` with server-authored messages when any operation cannot be
    applied; nothing is applied then.
    """
    applier = _Applier(draft, handles, context)
    messages = []
    for position, operation in enumerate(output.get('operations') or [], start=1):
        name = operation['op']
        try:
            getattr(applier, f'op_{name}')(operation)
        except _OperationError as exc:
            messages.append(f'Operation {position} ({name}): {exc.message}')
            if len(messages) >= _MAX_SCHEMA_ERRORS:
                break
    if not messages:
        messages = applier.finish(output)
    if messages:
        raise AssistApplyError(messages)
    return applier.candidate, applier.info()


def _schema_errors(validator, instance, prefix):
    errors = sorted(validator.iter_errors(instance), key=lambda item: (list(map(str, item.absolute_path)), item.validator))
    return [f'{prefix}{_schema_error_message(error)}' for error in errors[:_MAX_SCHEMA_ERRORS]]


def validate_assist_output(output):
    """Schema errors in the model's parsed reply, as server-authored messages; empty when it is valid."""
    if not isinstance(output, dict):
        return ['The reply must be a JSON object.']
    messages = _schema_errors(_ENVELOPE_VALIDATOR, output, '')
    if messages:
        return messages
    for position, operation in enumerate(output.get('operations') or [], start=1):
        name = operation['op']
        prefix = f'Operation {position} ({name}): '
        messages.extend(_schema_errors(_OPERATION_VALIDATORS[name], operation, prefix))
        if len(messages) >= _MAX_SCHEMA_ERRORS:
            break
    return messages[:_MAX_SCHEMA_ERRORS]
