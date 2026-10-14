# functions_workflow_document_selection.py
"""Strict, metadata-only task document selectors shared by preview and execution."""

import copy
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import os
import time

import regex


MAX_RECENT_WINDOW_MINUTES = 365 * 24 * 60
MAX_FILTER_DEPTH = 4
MAX_FILTER_CONDITIONS = 32
MAX_SELECTION_CANDIDATES = 10000
SELECTION_DEADLINE_SECONDS = 30
REGEX_TIMEOUT_SECONDS = 0.02
FILE_TYPES = (
    'pdf', 'csv', 'xlsx', 'xls', 'xlsm', 'docx', 'doc', 'pptx', 'ppt',
    'txt', 'md', 'json', 'xml', 'html', 'htm', 'tsv', 'png', 'jpg', 'jpeg', 'tiff',
)
TEXT_OPERATORS = ('equals', 'starts_with', 'contains', 'regex')
FILTER_FIELDS = ('filename', 'tags', 'file_type', 'classification', 'author', 'keywords')
_selected_sources = ContextVar('workflow_selected_document_sources', default=None)


@contextmanager
def selected_document_sources(entries, actor):
    scopes = {}
    for entry in entries:
        document = entry['document']
        identity = document['document_id']
        scope = (document['scope_type'], document['scope_id'])
        if identity in scopes and scopes[identity] != scope:
            raise DocumentSelectionError(
                'document_selection_identity_conflict',
                'Selected documents share an identifier across workspaces. Choose one of those workspaces for this task.',
            )
        scopes[identity] = scope
    token = _selected_sources.set((actor, scopes))
    try:
        yield
    finally:
        _selected_sources.reset(token)


def selected_source_matches(actor, document_id, scope, scope_id=None):
    """Bind native ID-based readers to the exact selected workspace, never cached permission."""
    active = _selected_sources.get()
    if active is None or active[0] != actor or document_id not in active[1]:
        return True
    expected_scope, expected_id = active[1][document_id]
    return scope == expected_scope and (scope == 'personal' or scope_id == expected_id)


def selected_document_context_validator(actor, validator=None):
    active = _selected_sources.get()
    if active is None or active[0] != actor:
        return validator

    def validate(context, identity):
        scope = context.get('scope')
        scope_id = context.get('group_id') if scope == 'group' else context.get('public_workspace_id')
        return selected_source_matches(actor, identity, scope, scope_id) and (
            validator is None or validator(context, identity)
        )
    return validate


class DocumentSelectionError(ValueError):
    """An application-owned code and safe message, never regex/provider input."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.public_message = message


class DocumentSelectionLimitError(DocumentSelectionError):
    def __init__(self, count, limit):
        super().__init__(
            'document_selection_limit_exceeded',
            f'This selection has at least {count} matching documents. Narrow it to {limit} or fewer before running.',
        )
        self.count, self.limit, self.count_exact = count, limit, False


def validate_recent_window(value):
    if type(value) is not int or not 1 <= value <= MAX_RECENT_WINDOW_MINUTES:
        raise DocumentSelectionError(
            'document_selection_window_invalid', 'Choose a whole-number window from 1 minute to 365 days.',
        )
    return value


def normalize_document_selection(value):
    if not isinstance(value, dict) or value.keys() - {'scopes', 'filters', 'on_empty'}:
        raise DocumentSelectionError('document_selection_invalid', 'Review the document selection settings.')
    scopes = value.get('scopes')
    if not isinstance(scopes, list) or not 1 <= len(scopes) <= 20:
        raise DocumentSelectionError('document_selection_scope_invalid', 'Choose between 1 and 20 workspaces.')
    seen = set()
    for scope in scopes:
        if not isinstance(scope, dict) or scope.keys() - {'scope_type', 'scope_id'}:
            raise DocumentSelectionError('document_selection_scope_invalid', 'Choose an available workspace.')
        kind = scope.get('scope_type')
        identifier = scope.get('scope_id')
        if kind not in ('personal', 'group', 'public') or (
            kind == 'personal' and identifier not in (None, '')
        ) or (kind != 'personal' and (
            not isinstance(identifier, str) or not identifier.strip() or identifier != identifier.strip() or len(identifier) > 256
        )):
            raise DocumentSelectionError('document_selection_scope_invalid', 'Choose an available workspace.')
        key = (kind, identifier or '')
        if key in seen:
            raise DocumentSelectionError('document_selection_scope_invalid', 'Remove duplicate workspaces.')
        seen.add(key)
    if value.get('on_empty') not in ('report', 'error'):
        raise DocumentSelectionError('document_selection_invalid', 'Choose how to handle no matching documents.')
    filters = value.get('filters', {'operator': 'and', 'conditions': []})
    count = 0

    def visit(node, depth):
        nonlocal count
        count += 1
        if count > MAX_FILTER_CONDITIONS or depth > MAX_FILTER_DEPTH or not isinstance(node, dict):
            raise DocumentSelectionError(
                'document_selection_filter_invalid', 'Use at most 32 conditions or groups and 4 total filter levels.',
            )
        if 'conditions' in node:
            if node.keys() - {'operator', 'conditions'} or node.get('operator') not in ('and', 'or'):
                raise DocumentSelectionError('document_selection_filter_invalid', 'Choose Match all or Match any.')
            children = node['conditions']
            if not isinstance(children, list) or (depth > 1 and not children):
                raise DocumentSelectionError('document_selection_filter_invalid', 'Add a condition or remove the empty group.')
            for child in children:
                visit(child, depth + 1)
            return
        if node.keys() - {'field', 'operator', 'value', 'match_case'}:
            raise DocumentSelectionError('document_selection_filter_invalid', 'The document filter contains unsupported fields.')
        field, operator, operand = node.get('field'), node.get('operator'), node.get('value')
        if field not in FILTER_FIELDS or type(node.get('match_case', False)) is not bool:
            raise DocumentSelectionError('document_selection_filter_invalid', 'Choose a supported document filter.')
        if field in ('tags', 'file_type'):
            if operator not in (('has_any',) if field == 'file_type' else ('has_any', 'has_all')) or (
                not isinstance(operand, list) or not 1 <= len(operand) <= 100
                or any(not isinstance(item, str) or not item.strip() or len(item) > 256 for item in operand)
                or len(set(operand)) != len(operand)
            ):
                raise DocumentSelectionError('document_selection_filter_invalid', 'Select one or more unique values.')
            if field == 'file_type' and any(item not in FILE_TYPES for item in operand):
                raise DocumentSelectionError('document_selection_filter_invalid', 'Choose a supported file extension.')
        elif operator not in TEXT_OPERATORS or (
            not isinstance(operand, str) or not operand.strip() or len(operand) > 256
        ) or (operator == 'regex' and field != 'filename'):
            raise DocumentSelectionError('document_selection_filter_invalid', 'Enter a supported metadata condition.')
        if operator == 'regex':
            try:
                regex.compile(operand, 0 if node.get('match_case') else regex.IGNORECASE)
            except regex.error as exc:
                raise DocumentSelectionError(
                    'document_selection_regex_invalid', 'The filename regular expression is invalid. Review its syntax.',
                ) from exc

    visit(filters, 1)
    return {**copy.deepcopy(value), 'filters': copy.deepcopy(filters)}


class DocumentSelectionMatcher:
    """Compile once; all matching is exact typed metadata evaluation, not intent routing."""

    def __init__(self, selection, window_minutes, *, now=None):
        self.selection = normalize_document_selection(selection)
        self.captured_at = int(time.time() if now is None else now)
        self.cutoff = self.captured_at - validate_recent_window(window_minutes) * 60
        self.patterns = {}

        def compile_patterns(node):
            if 'conditions' in node:
                for child in node['conditions']:
                    compile_patterns(child)
            elif node['operator'] == 'regex':
                self.patterns[id(node)] = regex.compile(
                    node['value'], 0 if node.get('match_case') else regex.IGNORECASE,
                )
        compile_patterns(self.selection['filters'])

    def matches(self, document):
        timestamp = document.get('_ts')
        if type(timestamp) not in (int, float) or not self.cutoff <= timestamp <= self.captured_at:
            return False

        def evaluate(node):
            if 'conditions' in node:
                children = node['conditions']
                return (all if node['operator'] == 'and' else any)(evaluate(child) for child in children) if children else True
            field, operator, value = node['field'], node['operator'], node['value']
            raw = {
                'filename': document.get('file_name'), 'tags': document.get('tags'),
                'file_type': [os.path.splitext(str(document.get('file_name') or ''))[1].lower().lstrip('.')],
                'classification': document.get('document_classification'),
                'author': document.get('authors'), 'keywords': document.get('keywords'),
            }[field]
            if field in ('filename', 'classification') and not isinstance(raw, str):
                return False
            if field == 'tags' and not isinstance(raw, list):
                return False
            values = raw if isinstance(raw, list) else [raw]
            values = [item for item in values if isinstance(item, str)]
            if operator == 'regex':
                try:
                    return any(self.patterns[id(node)].search(item, timeout=REGEX_TIMEOUT_SECONDS) is not None for item in values)
                except TimeoutError as exc:
                    raise DocumentSelectionError(
                        'document_selection_regex_timeout', 'The filename expression took too long. Use a simpler pattern.',
                    ) from exc
            fold = (lambda item: item) if node.get('match_case') else str.casefold
            actual = [fold(item) for item in values]
            if isinstance(value, list):
                wanted = [fold(item) for item in value]
                return (all if operator == 'has_all' else any)(item in actual for item in wanted)
            wanted = fold(value)
            return any(
                item == wanted if operator == 'equals' else item.startswith(wanted) if operator == 'starts_with'
                else wanted in item for item in actual
            )
        return evaluate(self.selection['filters'])


def filter_schema(depth=MAX_FILTER_DEPTH):
    predicate = {
        'type': 'object', 'additionalProperties': False, 'required': ['field', 'operator', 'value'],
        'properties': {
            'field': {'enum': list(FILTER_FIELDS)},
            'operator': {'enum': [*TEXT_OPERATORS, 'has_any', 'has_all']},
            'value': {'oneOf': [
                {'type': 'string', 'minLength': 1, 'maxLength': 256},
                {'type': 'array', 'minItems': 1, 'maxItems': 100, 'uniqueItems': True,
                 'items': {'type': 'string', 'minLength': 1, 'maxLength': 256}},
            ]},
            'match_case': {'type': 'boolean'},
        },
    }
    if depth == 1:
        return predicate
    return {'oneOf': [predicate, {
        'type': 'object', 'additionalProperties': False, 'required': ['operator', 'conditions'],
        'properties': {
            'operator': {'enum': ['and', 'or']},
            'conditions': {'type': 'array', 'maxItems': MAX_FILTER_CONDITIONS, 'items': filter_schema(depth - 1)},
        },
    }]}


def resolve_document_selection(workflow, action, settings, *, actor_user_id, limit, check=None, readers=None, run_id=None):
    """Reuse the authorized, current-version catalog boundary for preview and runtime."""
    # This authorized runtime boundary loads the cloud-backed document reader, not the pure contract.
    from functions_appinsights import log_event
    from functions_workflow_loop_inputs import iter_workflow_loop_documents
    from functions_workflow_limits import WorkflowLoopLimitError

    task_id = (workflow.get('active_task') or {}).get('id')
    correlation = {
        'step_id_hash': hashlib.sha256(str(task_id).encode('utf-8')).hexdigest() if task_id else None,
        'run_id_hash': hashlib.sha256(str(run_id).encode('utf-8')).hexdigest() if run_id else None,
    }
    try:
        matcher = DocumentSelectionMatcher(action['document_selection'], action.get('recent_window_minutes'))
    except DocumentSelectionError as exc:
        log_event('[WORKFLOW_DOCUMENT_SELECTION] Validation refused', extra={**correlation, 'validation_code': exc.code})
        raise
    merge_extensions = None
    if action.get('type') == 'merge':
        # The merge contract is cloud-free; file-type constraints precede the matching limit.
        from functions_document_actions import MERGE_KIND_EXTENSIONS
        merge_extensions = MERGE_KIND_EXTENSIONS[action['merge_kind']]
    started = time.monotonic()
    candidates = 0
    timestamps = {}

    def check_budget():
        if check is not None:
            check()
        if time.monotonic() - started > SELECTION_DEADLINE_SECONDS:
            raise DocumentSelectionError('document_selection_incomplete', 'Selection took too long. Narrow the window or filters.')

    def matches(document, _filters):
        nonlocal candidates
        candidates += 1
        if candidates > MAX_SELECTION_CANDIDATES:
            raise DocumentSelectionError('document_selection_incomplete', 'Too many candidate documents. Narrow the window or filters.')
        matched = matcher.matches(document) and (
            merge_extensions is None or os.path.splitext(str(document.get('file_name') or ''))[1].lower() in merge_extensions
        )
        if matched:
            timestamps[document.get('id')] = document.get('_ts', 0)
        return matched

    capture = {}
    iterable = {
        'kind': 'workspace_query', 'scopes': matcher.selection['scopes'],
        'filters': {}, 'selection': {'mode': 'all_matches'},
    }
    try:
        entries = list(iter_workflow_loop_documents(
            workflow, iterable, actor_user_id=actor_user_id, max_items=limit, settings=settings,
            match_filters=matches, check=check_budget, capture_metadata=capture, **(readers or {}),
        ))
        if not capture.get('complete') or not capture.get('count_exact'):
            raise DocumentSelectionError('document_selection_incomplete', 'The complete document selection could not be confirmed.')
    except WorkflowLoopLimitError as exc:
        error = DocumentSelectionLimitError(exc.count, exc.limit)
        log_event('[WORKFLOW_DOCUMENT_SELECTION] Matching limit exceeded', extra={
            **correlation, 'failure_code': error.code, 'matched_count_lower_bound': error.count, 'limit': error.limit,
        })
        raise error from exc
    except (DocumentSelectionError, ValueError, PermissionError) as exc:
        log_event('[WORKFLOW_DOCUMENT_SELECTION] Selection refused', extra={
            **correlation, 'failure_code': getattr(exc, 'code', 'document_selection_failed'),
            'candidate_count': candidates, 'duration_ms': int((time.monotonic() - started) * 1000),
        })
        raise
    entries.sort(key=lambda entry: (
        -timestamps.get(entry['document']['document_id'], 0),
        entry['document']['scope_type'], entry['document']['scope_id'], entry['document']['document_id'],
    ))
    log_event('[WORKFLOW_DOCUMENT_SELECTION] Selection completed', extra={
        **correlation, 'output_code': 'matched' if entries else 'no_matches', 'candidate_count': candidates,
        'matched_count': len(entries), 'window_minutes': action['recent_window_minutes'],
        'duration_ms': int((time.monotonic() - started) * 1000),
    })
    return {'entries': entries, 'count': len(entries), 'count_exact': True, 'cutoff_ts': matcher.cutoff, 'limit': limit}
