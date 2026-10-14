# test_workflow_authoring_sdk_boundaries.py
"""
SDK-shaped runtime coverage for storage owners in the workflow authoring modules.
Version: 0.261.332
Implemented in: 0.261.332

The inventory fingerprints whole modules. These unchanged storage functions
therefore need renewed owner-runtime evidence when selectors/telemetry change
their modules. External I/O is blocked; real owners use the existing SDK-default
conditional Cosmos double. This is representative, not exhaustive coverage.
"""

import ast
import importlib
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from azure.cosmos._cosmos_responses import CosmosDict
from azure.cosmos.exceptions import CosmosResourceNotFoundError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'application' / 'single_app'))
# The shared offline bootstrap imports real application owners from this path.
from test_orchestration_harness_execution import initialized_application
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_support import workflow_assist as wa


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
