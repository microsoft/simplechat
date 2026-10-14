# test_workflow_authoring_sdk_boundaries.py
"""
SDK-shaped runtime coverage for storage owners in the workflow authoring modules.
Version: 0.261.335
Implemented in: 0.261.332
Personal workflow owner-runtime coverage added in: 0.261.335

The inventory fingerprints whole modules. These unchanged storage functions
therefore need renewed owner-runtime evidence when selectors/telemetry change
their modules. External I/O is blocked; real owners use the existing SDK-default
conditional Cosmos double. This is representative, not exhaustive coverage.
"""

import ast
import importlib
import sys
import uuid
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from azure.core.exceptions import AzureError
from azure.cosmos._cosmos_responses import CosmosDict
from azure.cosmos.exceptions import CosmosResourceNotFoundError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'application' / 'single_app'))
# The shared offline bootstrap imports real application owners from this path.
from test_orchestration_harness_execution import initialized_application
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_support import workflow_assist as wa


class WorkflowQueryContainer(AtomicMemoryContainer):
    """SDK-default points and the bounded query subset used by these store owners."""

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        rows = super().query_items(
            query.replace('SELECT TOP 1 *', 'SELECT *'), parameters, partition_key, **kwargs,
        )
        self.queries[-1] = (query, deepcopy(parameters), partition_key)
        values = {entry['name']: entry['value'] for entry in parameters or []}
        if '@workflow_id' in values:
            rows = [row for row in rows if row.get('workflow_id') == values['@workflow_id']]
        if '@source' in values:
            rows = [row for row in rows if (row.get('origin') or {}).get('source') == values['@source']]
        if 'c.origin.one_time = true' in query:
            rows = [row for row in rows if (row.get('origin') or {}).get('one_time') is True]
        if 'c.origin.one_time != true' in query:
            rows = [row for row in rows if (row.get('origin') or {}).get('one_time') is not True]
        if 'c.deleting != true' in query:
            rows = [row for row in rows if row.get('deleting') is not True]
        if '@since' in values:
            rows = [row for row in rows if row.get('created_at', '') >= values['@since']]
        if '@trigger_types' in values:
            rows = [row for row in rows if row.get('trigger_type') in values['@trigger_types']
                    and row.get('is_enabled') is True and row.get('next_run_at')
                    and row['next_run_at'] <= values['@now_iso']]
        if 'ORDER BY c.started_at DESC' in query:
            rows.sort(key=lambda row: row.get('started_at', ''), reverse=True)
        if 'ORDER BY c.created_at ASC' in query:
            rows.sort(key=lambda row: row.get('created_at', ''))
        if query.startswith('SELECT VALUE COUNT(1)'):
            return [len(rows)]
        return rows[:1] if query.startswith('SELECT TOP 1 *') else rows


@pytest.fixture
def owners(initialized_application, monkeypatch):
    runner = importlib.import_module('functions_workflow_runner')
    search = importlib.import_module('functions_search_service')
    conversations = AtomicMemoryContainer('id')
    messages = AtomicMemoryContainer('conversation_id')
    # Bind the exact route helper bodies without registering the web-only agent
    # decorators; SDK responses, ownership checks, and projections remain real.
    path = ROOT / 'application' / 'single_app' / 'route_backend_workflows.py'
    nodes = [node for node in ast.parse(path.read_text(encoding='utf-8')).body
             if isinstance(node, ast.FunctionDef) and node.name in {
                 '_load_workflow_conversation', '_load_group_workflow_conversation', '_normalize_identifier',
             }]
    namespace = {'cosmos_conversations_container': conversations,
                 'CosmosResourceNotFoundError': CosmosResourceNotFoundError}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    routes = SimpleNamespace(**namespace)
    for module in (runner, search):
        monkeypatch.setattr(module, 'cosmos_conversations_container', conversations)
    for module in (runner, search):
        monkeypatch.setattr(module, 'cosmos_messages_container', messages)
    monkeypatch.setattr(runner, 'bump_conversation_cache_version', lambda *_args, **_kwargs: None)
    return SimpleNamespace(runner=runner, routes=routes, search=search,
                           conversations=conversations, messages=messages)


@pytest.fixture
def personal_store(owners, monkeypatch):
    personal = importlib.import_module('functions_personal_workflows')
    workflows = WorkflowQueryContainer('user_id')
    runs = WorkflowQueryContainer('user_id')
    items = WorkflowQueryContainer('run_id')
    monkeypatch.setattr(personal, 'cosmos_conversations_container', owners.conversations)
    monkeypatch.setattr(personal, 'cosmos_personal_workflows_container', workflows)
    monkeypatch.setattr(personal, 'cosmos_personal_workflow_runs_container', runs)
    monkeypatch.setattr(personal, 'cosmos_personal_workflow_run_items_container', items)
    monkeypatch.setattr(personal, '_utc_now_iso', lambda: '2026-10-14T12:00:00+00:00')
    return SimpleNamespace(personal=personal, workflows=workflows, runs=runs, items=items, owners=owners)


def seed_conversation(owners, **extra):
    record = {'id': 'conversation', 'user_id': wa.USER_ID, 'chat_type': 'workflow',
              'workflow_id': wa.WORKFLOW_ID, 'workspace_type': 'personal', **extra}
    response = owners.conversations.upsert_item(record)
    assert isinstance(response, CosmosDict)
    return response


def test_search_upload_owners_consume_real_sdk_point_documents(owners):
    seed_conversation(owners)
    response = owners.messages.upsert_item({
        'id': 'upload', 'conversation_id': 'conversation', 'role': 'file',
        'filename': 'upload.txt', 'file_content': 'Uploaded text.', 'metadata': {},
    })
    assert isinstance(response, CosmosDict)
    allowed = owners.search._authorize_chat_upload_conversation(wa.USER_ID, 'conversation')
    denied = owners.search._authorize_chat_upload_conversation(wa.OTHER_USER_ID, 'conversation')
    context = owners.search._resolve_chat_upload_context('upload', wa.USER_ID, 'conversation')
    assert allowed and not denied
    assert context['document']['comparison_text'] == 'Uploaded text.'


def test_assist_base_owner_projects_sdk_workflow_without_metadata(initialized_application):
    runtime = importlib.import_module('functions_workflow_assist_runtime')
    store = AtomicMemoryContainer('user_id')
    stored = store.upsert_item(wa.stored_workflow())
    assert isinstance(stored, CosmosDict) and '_etag' in stored
    base = runtime.read_workflow_base(store, wa.USER_ID, wa.WORKFLOW_ID)
    assert type(base) is dict and base['id'] == wa.WORKFLOW_ID and '_etag' not in base


def test_activity_route_owners_project_and_check_sdk_conversations(owners):
    seed_conversation(owners)
    personal = owners.routes._load_workflow_conversation(wa.USER_ID, 'conversation')
    assert type(personal) is dict and personal['id'] == 'conversation' and '_etag' not in personal
    with pytest.raises(PermissionError):
        owners.routes._load_workflow_conversation(wa.OTHER_USER_ID, 'conversation')
    seed_conversation(owners, workspace_type='group', group_id='group-one')
    group = owners.routes._load_group_workflow_conversation('group-one', 'conversation')
    assert type(group) is dict and group['group_id'] == 'group-one' and '_etag' not in group
    with pytest.raises(PermissionError):
        owners.routes._load_group_workflow_conversation('group-two', 'conversation')


def test_runner_conversation_and_replayed_user_message_accept_sdk_points(owners, monkeypatch):
    seed_conversation(owners, title='Old workflow title')
    workflow = {**wa.stored_workflow(), 'conversation_id': 'conversation'}
    conversation = owners.runner._ensure_workflow_conversation(workflow)
    assert conversation['title'] == f"Workflow: {workflow['name']}"
    stored = owners.conversations.read_item('conversation', 'conversation')
    assert isinstance(stored, CosmosDict) and stored['title'] == conversation['title']
    run_id = 'run-one'
    message_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'workflow-user:{run_id}'))
    owners.messages.upsert_item({
        'id': message_id, 'conversation_id': 'conversation',
        'metadata': {'workflow': {'run_id': run_id}},
    })
    monkeypatch.setattr(owners.runner, 'current_workflow_execution', lambda: SimpleNamespace(run_id=run_id))
    replay = owners.runner._create_user_message('conversation', workflow, 'manual', run_id)
    assert isinstance(replay, CosmosDict) and replay['id'] == message_id and replay['_etag']


def test_runner_delivery_owners_mutate_sdk_points_and_mirror_a_reply(owners):
    seed_conversation(owners)
    owners.messages.upsert_item({
        'id': 'posted', 'conversation_id': 'conversation',
        'metadata': {'posted_via': 'agent_action'},
    })
    hidden = owners.runner._hide_run_posts_superseded_by_reply(
        wa.stored_workflow(), 'conversation', ['posted'], {'id': 'reply'}, False,
    )
    assert hidden == ['posted']
    posted = owners.messages.read_item('posted', 'conversation')
    assert owners.runner.WORKFLOW_REPLY_SUPERSEDED_METADATA_KEY in posted['metadata']
    hidden_conversation = owners.runner._hide_workflow_conversation_after_delivery('conversation')
    assert hidden_conversation is True
    conversation = owners.conversations.read_item('conversation', 'conversation')
    mirrored = owners.runner._mirror_assistant_message_to_personal_conversation(
        wa.stored_workflow(), {'id': 'reply', 'content': 'The summary.'}, conversation, [],
    )
    stored = owners.messages.read_item(mirrored['id'], 'conversation')
    assert isinstance(stored, CosmosDict) and stored['content'] == 'The summary.'


def test_runner_query_owners_consume_plain_query_rows(owners):
    owners.messages.upsert_item({
        'id': 'message', 'conversation_id': 'conversation', 'thread_id': 'prior-thread',
    })
    thread = owners.runner._get_latest_thread_id('conversation')
    assert thread == 'prior-thread'
    documents = AtomicMemoryContainer('user_id')
    documents.upsert_item({'id': 'document', 'user_id': wa.USER_ID, 'file_name': 'Tim.pdf',
                           'version': 1, '_ts': 100})
    rows = owners.runner._query_recent_documents(documents, 'SELECT * FROM c', [], 10)
    merged = owners.runner._query_merge_candidate_documents(
        documents, 'c.user_id = @user_id', [{'name': '@user_id', 'value': wa.USER_ID}], ['.pdf'],
    )
    assert rows and merged and type(rows[0]) is type(merged[0]) is dict
    assert rows[0]['id'] == merged[0]['id'] == 'document'


def test_history_owner_consumes_real_query_rows(initialized_application, monkeypatch):
    config = importlib.import_module('config')
    results = importlib.import_module('functions_workflow_results')
    store = AtomicMemoryContainer('run_id')
    store.upsert_item({
        'id': 'task-item', 'workflow_id': wa.WORKFLOW_ID, 'run_id': 'run-one',
        'item_type': 'task', 'task_id': 'one', 'workflow_result': {},
    })
    monkeypatch.setattr(config, 'cosmos_personal_workflow_run_items_container', store)
    results.authorize_workflow_run_read(wa.stored_workflow(), 'run-one')
    assert store.queries and store.queries[-1][2] == 'run-one'


def test_run_owner_consumes_sdk_replayed_message_before_model_processing(owners, monkeypatch):
    class ProbeStop(BaseException):
        pass

    seed_conversation(owners, title='Workflow: Document review')
    owners.messages.upsert_item({
        'id': 'cached-message', 'conversation_id': 'conversation',
        'metadata': {'thread_info': {'thread_id': 'thread'}},
    })
    runner = owners.runner
    progress = []
    monkeypatch.setattr(runner, 'get_settings', lambda: {})
    monkeypatch.setattr(runner, '_get_workflow_run_record', lambda *_args: {
        'user_message_id': 'cached-message', 'file_sync_checked': True,
    })
    monkeypatch.setattr(runner, '_save_workflow_run_record', lambda _workflow, record: progress.append(dict(record)))
    monkeypatch.setattr(runner, '_raise_if_workflow_run_cancelled', lambda *_args: None)
    monkeypatch.setattr(runner, '_apply_workflow_run_time_context', lambda workflow, _start: workflow)
    monkeypatch.setattr(runner, 'ThoughtTracker', lambda **_kwargs: SimpleNamespace())

    def stop_before_model(*_args, **_kwargs):
        raise ProbeStop

    monkeypatch.setattr(runner, '_add_workflow_activity_thought', stop_before_model)
    with pytest.raises(ProbeStop):
        runner._run_authorized_workflow_impl(
            {**wa.stored_workflow(), 'conversation_id': 'conversation'}, run_id='run-one',
        )
    assert progress[-1]['user_message_id'] == 'cached-message'
    assert progress[-1]['assistant_message_id']


def test_personal_conversation_owner_authorizes_sdk_point_documents(personal_store):
    store = personal_store
    point = seed_conversation(store.owners)
    assert isinstance(point, CosmosDict) and type(point) is not dict
    conversation_id = store.personal._normalize_personal_workflow_conversation_id(
        wa.USER_ID, {'conversation_id': 'conversation'},
    )
    assert conversation_id == 'conversation'
    with pytest.raises(PermissionError):
        store.personal._normalize_personal_workflow_conversation_id(
            wa.OTHER_USER_ID, {'conversation_id': 'conversation'},
        )
    with pytest.raises(ValueError):
        store.personal._normalize_personal_workflow_conversation_id(
            wa.USER_ID, {'conversation_id': 'missing'},
        )
    seed_conversation(store.owners, group_id='group-one')
    with pytest.raises(PermissionError):
        store.personal._normalize_personal_workflow_conversation_id(
            wa.USER_ID, {'conversation_id': 'conversation'},
        )


def test_personal_workflow_read_and_due_owners_project_sdk_points_and_query_rows(personal_store):
    store = personal_store
    point = store.workflows.upsert_item({
        **wa.stored_workflow(), 'trigger_type': 'interval', 'is_enabled': True,
        'next_run_at': '2026-10-14T11:00:00+00:00', 'updated_at': '2026-10-14T10:00:00+00:00',
    })
    store.workflows.upsert_item({
        **wa.stored_workflow(), 'id': 'manual', 'trigger_type': 'manual', 'is_enabled': False,
    })
    store.workflows.upsert_item({**wa.stored_workflow(), 'user_id': wa.OTHER_USER_ID})
    loaded = store.personal.get_personal_workflow(wa.USER_ID, wa.WORKFLOW_ID)
    foreign = store.personal.get_personal_workflow('missing-owner', wa.WORKFLOW_ID)
    workflows = store.personal.get_personal_workflows(wa.USER_ID)
    due = store.personal.get_due_personal_workflows(limit=1)
    query_rows = store.workflows.query_items('SELECT * FROM c', partition_key=wa.USER_ID)
    assert isinstance(point, CosmosDict) and '_etag' in point
    assert type(loaded) is dict and loaded['id'] == wa.WORKFLOW_ID and '_etag' not in loaded
    assert foreign is None
    assert {row['id'] for row in workflows} == {wa.WORKFLOW_ID, 'manual'}
    assert all(type(row) is dict and '_etag' not in row for row in workflows + due)
    assert len(due) == 1 and due[0]['trigger_type'] == 'interval'
    assert query_rows and all(type(row) is dict for row in query_rows)


def test_personal_workflow_count_owners_consume_scalar_queries_and_fail_closed(personal_store):
    store = personal_store
    for identifier, one_time, deleting, user_id in [
        ('active', False, False, wa.USER_ID), ('deleted', False, True, wa.USER_ID),
        ('handoff', True, True, wa.USER_ID), ('foreign', False, False, wa.OTHER_USER_ID),
    ]:
        store.workflows.upsert_item({
            'id': identifier, 'user_id': user_id, 'deleting': deleting,
            'created_at': '2026-10-14T10:00:00+00:00',
            'origin': {'source': 'orchestration', 'one_time': one_time},
        })
    recurring = store.personal.count_personal_orchestration_workflows(wa.USER_ID)
    handoff = store.personal.count_personal_handoff_workflows_since(
        wa.USER_ID, '2026-10-14T00:00:00+00:00',
    )
    assert recurring == handoff == 1
    assert all(query[2] == wa.USER_ID for query in store.workflows.queries)
    store.workflows.fail_queries = True
    with pytest.raises(AzureError):
        store.personal.count_personal_orchestration_workflows(wa.USER_ID)
    with pytest.raises(AzureError):
        store.personal.count_personal_handoff_workflows_since(wa.USER_ID, '2026-10-14T00:00:00+00:00')


def test_personal_run_read_write_and_latest_owners_project_sdk_responses(personal_store):
    store = personal_store
    first = store.personal.save_personal_workflow_run(wa.USER_ID, {
        'id': 'run-one', 'workflow_id': wa.WORKFLOW_ID, 'conversation_id': 'conversation',
        'started_at': '2026-10-14T10:00:00+00:00',
    })
    store.runs.upsert_item({
        'id': 'run-two', 'user_id': wa.USER_ID, 'workflow_id': wa.WORKFLOW_ID,
        'conversation_id': 'conversation', 'started_at': '2026-10-14T11:00:00+00:00',
    })
    store.runs.upsert_item({
        'id': 'other-workflow', 'user_id': wa.USER_ID, 'workflow_id': 'other-workflow',
        'conversation_id': 'conversation', 'started_at': '2026-10-14T12:00:00+00:00',
    })
    point = store.runs.read_item('run-one', wa.USER_ID)
    loaded = store.personal.get_personal_workflow_run(wa.USER_ID, 'run-one')
    foreign = store.personal.get_personal_workflow_run(wa.OTHER_USER_ID, 'run-one')
    listed = store.personal.list_personal_workflow_runs(wa.USER_ID, wa.WORKFLOW_ID, limit=1)
    latest = store.personal.get_latest_personal_workflow_run_for_conversation(
        wa.USER_ID, 'conversation', workflow_id=wa.WORKFLOW_ID,
    )
    assert isinstance(point, CosmosDict) and point['_etag']
    assert first['user_id'] == wa.USER_ID and foreign is None
    assert [row['id'] for row in listed] == ['run-two'] and latest['id'] == 'run-two'
    assert all(type(row) is dict and '_etag' not in row for row in [first, loaded, latest, *listed])


def test_personal_guarded_run_owner_retains_sdk_etags_and_concurrent_cancellation(personal_store):
    store = personal_store
    initial = store.runs.upsert_item({
        'id': 'guarded', 'user_id': wa.USER_ID, 'status': 'running',
        'chat_delivery': {'state': 'pending'},
    })

    def cancel_during_replace():
        current = store.runs.read_item('guarded', wa.USER_ID)
        store.runs.upsert_item({
            **current, 'status': 'cancelling', 'cancellation_requested_at': '2026-10-14T12:00:00+00:00',
        })

    store.runs.before_replace = cancel_during_replace
    guarded = store.personal._save_chat_started_workflow_run(wa.USER_ID, {
        'id': 'guarded', 'user_id': wa.USER_ID, 'status': 'running',
        'chat_delivery': {'state': 'stale'},
    })
    saved = store.personal.save_personal_workflow_run(wa.USER_ID, {
        'id': 'guarded', 'status': 'running', 'trigger_source': 'chat_orchestration',
    })
    assert isinstance(guarded, CosmosDict) and guarded['_etag'] != initial['_etag']
    assert guarded['status'] == saved['status'] == 'cancelling'
    assert saved['chat_delivery'] == {'state': 'pending'} and saved['cancellation_requested_at']
    assert type(saved) is dict and '_etag' not in saved


def test_personal_run_item_owners_project_sdk_points_and_hide_private_rows(personal_store):
    store = personal_store
    saved = store.personal.save_personal_workflow_run_item(wa.USER_ID, {
        'id': 'task-item', 'run_id': 'run-one', 'item_type': 'task', 'created_at': '2026-10-14T10:00:00+00:00',
    })
    store.items.upsert_item({
        'id': 'private-item', 'run_id': 'run-one', 'user_id': wa.USER_ID,
        'type': 'workflow_runtime_control', 'created_at': '2026-10-14T11:00:00+00:00',
    })
    point = store.items.read_item('task-item', 'run-one')
    loaded = store.personal.get_personal_workflow_run_item('run-one', 'task-item')
    private = store.personal.get_personal_workflow_run_item('run-one', 'private-item')
    foreign = store.personal.get_personal_workflow_run_item('other-run', 'task-item')
    listed = store.personal.list_personal_workflow_run_items('run-one', limit=1)
    assert isinstance(point, CosmosDict) and '_etag' in point
    assert private is foreign is None
    assert [row['id'] for row in listed] == ['task-item']
    assert all(type(row) is dict and '_etag' not in row for row in [saved, loaded, *listed])
