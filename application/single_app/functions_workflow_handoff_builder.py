# functions_workflow_handoff_builder.py
"""Pure builder for one-time workflow hand-offs from chat orchestration.

A hand-off blueprint names one loop and exactly two tasks: one task that reviews each document
and one that writes the report. This module maps a checked blueprint and its server-side handle
map to a ``definition_version`` 3 durable workflow: a For each over the named documents or a
bounded workspace query, a current-item Analyze task in its body, a complete Collect and a
saved-record report task whose text is the workflow's output. It also builds the disclosure a
hand-off card shows, so the user sees how many documents the run covers before approving it.

Everything here is deterministic and reads nothing: no settings load, no storage and no Flask.
Ids come from the caller's ``derived_id`` and alert rules from its ``alert_fields``, so the draft
service keeps a single definition of both.
"""

from copy import deepcopy

from functions_workflow_limits import WORKFLOW_MAX_EXECUTION_ADMISSIONS, get_workflow_loop_item_limit
from functions_workflow_loop_schema import WORKFLOW_LOOP_MAX_ITEMS, normalize_workflow_iterable


HANDOFF_LOOP_SOURCE_DOCUMENTS = 'documents'
HANDOFF_LOOP_SOURCE_QUERY = 'workspace_query'
HANDOFF_LOOP_SOURCES = (HANDOFF_LOOP_SOURCE_DOCUMENTS, HANDOFF_LOOP_SOURCE_QUERY)
HANDOFF_SELECTION_ALL = 'all_matches'
HANDOFF_SELECTION_BEST = 'best_n'
HANDOFF_SELECTION_MODES = (HANDOFF_SELECTION_ALL, HANDOFF_SELECTION_BEST)
HANDOFF_HANDLE_KINDS = ('documents', 'scopes', 'agents')
HANDOFF_SCOPE_TYPES = ('personal', 'group', 'public')

HANDOFF_TASK_COUNT = 2
HANDOFF_MAX_DOCUMENTS = 25
HANDOFF_MAX_SCOPES = 100
HANDOFF_MAX_TAGS = 100
HANDOFF_TAG_MAX_LENGTH = 256
HANDOFF_CONTENT_MAX_LENGTH = 4000

# Every node a run starts costs one execution admission. Each document costs two: its loop item
# and its task attempt. The For each control, the Collect and the report cost one each. The
# reserve keeps the remaining admissions free for the runner's own bookkeeping, so the largest
# hand-off still fits the run's admission budget.
HANDOFF_ADMISSIONS_PER_ITEM = 2
HANDOFF_FIXED_ADMISSIONS = 3
HANDOFF_ADMISSION_RESERVE = 997
HANDOFF_MAX_LOOP_ITEMS = min(
    WORKFLOW_LOOP_MAX_ITEMS,
    (WORKFLOW_MAX_EXECUTION_ADMISSIONS - HANDOFF_FIXED_ADMISSIONS - HANDOFF_ADMISSION_RESERVE)
    // HANDOFF_ADMISSIONS_PER_ITEM,
)
HANDOFF_DEADLINE_SECONDS = 86400

HANDOFF_ALERTS = {'mode': 'every_run', 'severity': 'info'}
HANDOFF_ANALYZE_ACTION = 'analyze'
HANDOFF_LOOP_ID = 'each'
HANDOFF_BODY_ID = 'body-region'
HANDOFF_BODY_NODE_ID = 'body-node'
HANDOFF_COLLECT_ID = 'collect'
HANDOFF_REPORT_NODE_ID = 'report-node'
HANDOFF_FLOW_ID = 'root'
HANDOFF_ITEM_KEY = 'source_identity'
HANDOFF_FINDINGS_OUTPUT = 'findings'
HANDOFF_REPORT_OUTPUT = 'report'

HANDOFF_SCOPE_LABELS = {
    'personal': 'Your personal workspace',
    'group': 'A group workspace',
    'public': 'A public workspace',
}
HANDOFF_PAUSE_NOTE = (
    'If more match when the run starts, it pauses before reviewing any; '
    'cancel it and ask again with a narrower request.'
)


def handoff_effective_loop_limit(settings):
    """Return the most documents one hand-off may cover under the current settings.

    The administrator's loop item limit, never above ``HANDOFF_MAX_LOOP_ITEMS``. ``settings`` is
    required: loading settings here could write their defaults. Raises ``WorkflowLoopLimitError``
    for a misconfigured administrator limit.
    """
    if settings is None:
        raise ValueError('Pass the application settings to read the hand-off loop limit.')
    return min(HANDOFF_MAX_LOOP_ITEMS, get_workflow_loop_item_limit(settings))


def handoff_loop_bound(loop, limit):
    """Return the disclosed N for a checked loop: the exact count, the best_n count or ``limit``."""
    if loop['source'] == HANDOFF_LOOP_SOURCE_DOCUMENTS:
        return len(loop['documents'])
    if loop['selection'] == HANDOFF_SELECTION_BEST:
        return int(loop['count'])
    return int(limit)


def handoff_handle_uses(blueprint):
    """Return where each handle is used: ``{kind: {handle: [path parts, ...]}}``, in blueprint order."""
    uses = {kind: {} for kind in HANDOFF_HANDLE_KINDS}
    loop = blueprint['loop']
    if loop['source'] == HANDOFF_LOOP_SOURCE_DOCUMENTS:
        for position, handle in enumerate(loop['documents']):
            uses['documents'].setdefault(handle, []).append(('loop', 'documents', position))
    else:
        for position, handle in enumerate(loop['scopes']):
            uses['scopes'].setdefault(handle, []).append(('loop', 'scopes', position))
    for index, task in enumerate(blueprint['tasks']):
        runner = task.get('runner') or {}
        if runner.get('type') == 'agent':
            uses['agents'].setdefault(runner['agent_ref'], []).append(('tasks', index, 'runner', 'agent_ref'))
    return uses


def _iterable_scope(record, *, document_id=None):
    # The loop schema reads a personal scope as the running user's own, so it names no scope id.
    entry = {'scope_type': record['scope_type']}
    if record['scope_type'] != 'personal':
        entry['scope_id'] = record['scope_id']
    if document_id is not None:
        entry['document_id'] = document_id
    return entry


def handoff_iterable(blueprint, handles, *, max_items):
    """Return the normalized For each iterable for a checked blueprint and its handle map.

    Raises ``WorkflowDefinitionError`` when the loop schema refuses it, such as two handles that
    name the same document or scope.
    """
    loop = blueprint['loop']
    if loop['source'] == HANDOFF_LOOP_SOURCE_DOCUMENTS:
        iterable = {
            'kind': HANDOFF_LOOP_SOURCE_DOCUMENTS,
            'documents': [
                _iterable_scope(handles['documents'][handle], document_id=handles['documents'][handle]['document_id'])
                for handle in loop['documents']
            ],
        }
    else:
        if loop['selection'] == HANDOFF_SELECTION_BEST:
            selection = {'mode': HANDOFF_SELECTION_BEST, 'count': int(loop['count'])}
        else:
            selection = {'mode': HANDOFF_SELECTION_ALL}
        iterable = {
            'kind': HANDOFF_LOOP_SOURCE_QUERY,
            'scopes': [_iterable_scope(handles['scopes'][handle]) for handle in loop['scopes']],
            'filters': {'tags': list(loop['tags'])} if loop.get('tags') else {},
            'selection': selection,
        }
        if loop.get('content'):
            iterable['content'] = {'mode': 'keyword', 'query': loop['content']}
    return normalize_workflow_iterable(iterable, max_items=max_items)


def _count_text(count, noun):
    return f'{count:,} {noun}' if count != 1 else f'1 {noun[:-1]}'


def handoff_disclosure(blueprint, handles, *, max_items):
    """Return what a hand-off covers, for its card: display text and counts, never ids.

    Named documents give their exact count. A workspace query gives "up to N", where N is the
    best_n count or, for every match, ``max_items``; ``scope_count`` and ``scope_names`` name the
    workspaces it searches. They are 0 and ``[]`` for named documents.
    """
    loop = blueprint['loop']
    if loop['source'] == HANDOFF_LOOP_SOURCE_DOCUMENTS:
        count = len(loop['documents'])
        return {
            'kind': HANDOFF_LOOP_SOURCE_DOCUMENTS,
            'count': count,
            'limit_behavior': 'exact',
            'text': _count_text(count, 'documents'),
            'scope_count': 0,
            'scope_names': [],
        }
    scope_names = []
    for handle in loop['scopes']:
        record = handles['scopes'][handle]
        scope_names.append(str(record.get('name') or HANDOFF_SCOPE_LABELS.get(record['scope_type'], 'A workspace')))
    if loop['selection'] == HANDOFF_SELECTION_BEST:
        limit = int(loop['count'])
        behavior = 'best_n'
        text = f'up to {_count_text(limit, "best-matching documents")}'
    else:
        limit = int(max_items)
        behavior = 'pause'
        text = f'up to {_count_text(limit, "matching documents")}. {HANDOFF_PAUSE_NOTE}'
    return {
        'kind': HANDOFF_LOOP_SOURCE_QUERY,
        'limit': limit,
        'limit_behavior': behavior,
        'text': text,
        'scope_count': len(scope_names),
        'scope_names': scope_names,
    }


def _task_runner(task, handles):
    runner = task.get('runner') or {'type': 'model'}
    if runner['type'] == 'agent':
        return {'type': 'agent', 'selected_agent': dict(handles['agents'][runner['agent_ref']])}
    # The workflow runs on the default model; a blueprint never names one.
    return {'type': 'inherit'}


def _records_contract(**extra):
    return {'kind': 'records', 'schema': {'type': 'array', 'items': {'type': 'object'}}, **extra}


def _node_output(node_id, output, expected_kind, *, name):
    return {
        'name': name,
        'source': {'kind': 'node_output', 'node_id': node_id, 'output': output, 'scope': 'current'},
        'required': True,
        'expected_kind': expected_kind,
        'allow_partial': False,
    }


def _item_task(task, handles, task_id):
    return {
        'id': task_id,
        'type': 'instructions',
        'name': task['title'],
        'instructions': task['instructions'],
        'runner': _task_runner(task, handles),
        'document_action': {
            'type': HANDOFF_ANALYZE_ACTION,
            'target_mode': 'current_item',
            'loop_id': HANDOFF_LOOP_ID,
            'analysis_mode': 'combined',
        },
        'inputs': [{
            'name': 'item',
            'source': {'kind': 'loop_item', 'loop_id': HANDOFF_LOOP_ID, 'scope': 'current'},
            'required': True,
            'expected_kind': 'json',
            'allow_partial': False,
        }],
        'reference_ids': [],
        'output_contract': _records_contract(),
    }


def _report_task(task, handles, task_id):
    return {
        'id': task_id,
        'type': 'instructions',
        'name': task['title'],
        'instructions': task['instructions'],
        'runner': _task_runner(task, handles),
        'document_action': {'type': 'none'},
        'inputs': [_node_output(HANDOFF_COLLECT_ID, 'records', 'records', name=HANDOFF_FINDINGS_OUTPUT)],
        # The runner pages and reduces the saved records, which bounds the report's input.
        'input_processing': 'saved_record_report',
        'reference_ids': [],
        'output_contract': {'kind': 'text'},
    }


def _flow(iterable, max_items, item_task_id, report_task_id):
    return {
        'id': HANDOFF_FLOW_ID,
        'nodes': [
            {
                'id': HANDOFF_LOOP_ID,
                'kind': 'for_each',
                'inputs': [],
                'iterable': iterable,
                'item_key': HANDOFF_ITEM_KEY,
                'max_items': max_items,
                'body': {
                    'id': HANDOFF_BODY_ID,
                    'nodes': [{'id': HANDOFF_BODY_NODE_ID, 'kind': 'task', 'task_id': item_task_id}],
                    'outputs': [_node_output(HANDOFF_BODY_NODE_ID, 'records', 'records', name=HANDOFF_FINDINGS_OUTPUT)],
                },
            },
            {
                'id': HANDOFF_COLLECT_ID,
                'kind': 'collect',
                'source': {'loop_id': HANDOFF_LOOP_ID, 'output': HANDOFF_FINDINGS_OUTPUT},
                'output_contract': _records_contract(require_complete_coverage=True, allow_partial=False),
            },
            {'id': HANDOFF_REPORT_NODE_ID, 'kind': 'task', 'task_id': report_task_id},
        ],
        'outputs': [{
            'name': HANDOFF_REPORT_OUTPUT,
            'source': {'kind': 'node_output', 'node_id': HANDOFF_REPORT_NODE_ID, 'output': 'text'},
            'expected_kind': 'text',
        }],
    }


def build_handoff_definition(blueprint, handles, *, workflow_id, max_items, derived_id, alert_fields):
    """Map a checked hand-off blueprint to the version 3 workflow payload a save accepts.

    ``blueprint`` has passed the hand-off schema and names only handles in ``handles``, the
    normalized server-side handle map. ``max_items`` is the disclosed N, which becomes the For
    each's ``max_items``. The workflow is manual, paused, runs without Microsoft 365 or Run as,
    alerts to the bell on every run and halts on the first error. Deterministic: the same
    blueprint, handles, workflow id and N always give the same payload. Raises ``ValueError`` for
    an N outside 1 to ``HANDOFF_MAX_LOOP_ITEMS`` and ``WorkflowDefinitionError`` for a loop the
    loop schema refuses.
    """
    if type(max_items) is not int or not 1 <= max_items <= HANDOFF_MAX_LOOP_ITEMS:
        raise ValueError('The hand-off item limit is not valid.')
    if len(blueprint['tasks']) != HANDOFF_TASK_COUNT:
        raise ValueError('A hand-off has exactly two tasks.')
    iterable = handoff_iterable(blueprint, handles, max_items=max_items)
    item_task_id = derived_id(workflow_id, 'task', 0)
    report_task_id = derived_id(workflow_id, 'task', 1)
    item_task, report_task = blueprint['tasks']
    return {
        'name': blueprint['name'],
        'description': blueprint.get('description', ''),
        'definition_version': 3,
        'durable_execution': True,
        'runner_type': 'model',
        'model_endpoint_id': '',
        'model_id': '',
        'chat_capabilities_enabled': False,
        'error_handling': {'strategy': 'halt', 'retry_count': 0},
        'limits': {'max_executions': WORKFLOW_MAX_EXECUTION_ADMISSIONS, 'deadline_seconds': HANDOFF_DEADLINE_SECONDS},
        'is_enabled': False,
        'trigger_type': 'manual',
        'tasks': [
            _item_task(item_task, handles, item_task_id),
            _report_task(report_task, handles, report_task_id),
        ],
        'reference_inputs': [],
        'flow': _flow(iterable, max_items, item_task_id, report_task_id),
        **alert_fields(dict(HANDOFF_ALERTS), workflow_id),
        'm365_run_as_user_id': '',
    }


def handoff_loop_preview(workflow):
    """Return the ``{iterable, max_items}`` body the loop input preview accepts, or ``None``.

    Read from a built hand-off workflow, so a card can count the matching documents before the
    user accepts, with the same route the workflow editor uses.
    """
    flow = workflow.get('flow') if isinstance(workflow, dict) else None
    for node in (flow.get('nodes') if isinstance(flow, dict) else None) or ():
        if isinstance(node, dict) and node.get('kind') == 'for_each' and node.get('id') == HANDOFF_LOOP_ID:
            return {'iterable': deepcopy(node.get('iterable')), 'max_items': node.get('max_items')}
    return None


__all__ = [
    'HANDOFF_ADMISSIONS_PER_ITEM',
    'HANDOFF_ADMISSION_RESERVE',
    'HANDOFF_ALERTS',
    'HANDOFF_ANALYZE_ACTION',
    'HANDOFF_CONTENT_MAX_LENGTH',
    'HANDOFF_DEADLINE_SECONDS',
    'HANDOFF_FIXED_ADMISSIONS',
    'HANDOFF_HANDLE_KINDS',
    'HANDOFF_LOOP_ID',
    'HANDOFF_LOOP_SOURCES',
    'HANDOFF_LOOP_SOURCE_DOCUMENTS',
    'HANDOFF_LOOP_SOURCE_QUERY',
    'HANDOFF_MAX_DOCUMENTS',
    'HANDOFF_MAX_LOOP_ITEMS',
    'HANDOFF_MAX_SCOPES',
    'HANDOFF_MAX_TAGS',
    'HANDOFF_SCOPE_TYPES',
    'HANDOFF_SELECTION_ALL',
    'HANDOFF_SELECTION_BEST',
    'HANDOFF_SELECTION_MODES',
    'HANDOFF_TAG_MAX_LENGTH',
    'HANDOFF_TASK_COUNT',
    'build_handoff_definition',
    'handoff_disclosure',
    'handoff_effective_loop_limit',
    'handoff_handle_uses',
    'handoff_iterable',
    'handoff_loop_bound',
    'handoff_loop_preview',
]
