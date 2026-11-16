# test_workflow_results_delivery.py
"""Real-owner workflow audit and result-publication regressions.

Version: 0.261.343
Implemented in: 0.261.343

The installed Cosmos SDK shapes every point/write response. Only external I/O
is doubled; conversation creation, invitation state, mirroring, notification
idempotency, owner checks and current group membership execute their real owners.
"""

import importlib
import io
from copy import deepcopy
from types import SimpleNamespace

import pytest
from azure.cosmos._cosmos_responses import CosmosDict
from flask import Flask, session

from test_orchestration_harness_execution import initialized_application
from test_support.orchestration_harness_execution import HarnessBlobIO
from test_support.orchestration_revisions import AtomicMemoryContainer


OWNER = '11111111-1111-4111-8111-111111111111'
MEMBER = '22222222-2222-4222-8222-222222222222'
OTHER = '33333333-3333-4333-8333-333333333333'
STARTED = '2026-10-16T17:00:00+00:00'
GROUP = 'workflow-group'


@pytest.fixture
def delivery(initialized_application, monkeypatch):
    runner = importlib.import_module('functions_workflow_runner')
    publisher = importlib.import_module('functions_workflow_results_delivery')
    collaboration = importlib.import_module('functions_collaboration')
    operations = importlib.import_module('functions_simplechat_operations')
    notifications = importlib.import_module('functions_notifications')
    groups = importlib.import_module('functions_group')
    conversations = AtomicMemoryContainer('id')
    messages = AtomicMemoryContainer('conversation_id')
    shared_conversations = AtomicMemoryContainer('id')
    shared_messages = AtomicMemoryContainer('conversation_id')
    states = AtomicMemoryContainer('user_id')
    notification_store = AtomicMemoryContainer('user_id')
    group_store = AtomicMemoryContainer('id')
    group_store.upsert_item({
        'id': GROUP, 'name': 'Workflow team', 'status': 'active',
        'owner': {'id': OWNER, 'displayName': 'Owner'},
        'users': [{'userId': MEMBER, 'displayName': 'Member', 'role': 'user'}],
    })
    for module in (runner, operations, collaboration):
        monkeypatch.setattr(module, 'cosmos_conversations_container', conversations)
        monkeypatch.setattr(module, 'cosmos_messages_container', messages)
    monkeypatch.setattr(collaboration, 'cosmos_collaboration_conversations_container', shared_conversations)
    monkeypatch.setattr(collaboration, 'cosmos_collaboration_messages_container', shared_messages)
    monkeypatch.setattr(collaboration, 'cosmos_collaboration_user_state_container', states)
    monkeypatch.setattr(runner, 'cosmos_collaboration_messages_container', shared_messages)
    monkeypatch.setattr(notifications, 'cosmos_notifications_container', notification_store)
    monkeypatch.setattr(groups, 'cosmos_groups_container', group_store)
    monkeypatch.setattr(operations, 'get_settings', lambda: {
        'enable_collaborative_conversations': True, 'enable_group_workspaces': True,
    })
    monkeypatch.setattr(operations, 'get_current_user_info', lambda: {
        'userId': session['user']['oid'], 'displayName': session['user']['name'], 'email': '',
    })
    def no_browser_directory_token(**_kwargs):
        raise AssertionError('Scheduled publication must not require a browser Graph token.')

    monkeypatch.setattr(operations, 'resolve_directory_user', no_browser_directory_token)
    for module in (runner, collaboration, operations, notifications):
        if hasattr(module, 'log_event'):
            monkeypatch.setattr(module, 'log_event', lambda *_args, **_kwargs: None)
        if hasattr(module, 'log_conversation_creation'):
            monkeypatch.setattr(module, 'log_conversation_creation', lambda **_kwargs: None)
        if hasattr(module, 'invalidate_conversation_cache_for_item'):
            monkeypatch.setattr(module, 'invalidate_conversation_cache_for_item', lambda *_args, **_kwargs: None)
        if hasattr(module, 'bump_conversation_cache_version'):
            monkeypatch.setattr(module, 'bump_conversation_cache_version', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(publisher, 'invalidate_conversation_cache_for_item', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, 'current_workflow_execution', lambda: None)
    monkeypatch.setattr(runner, '_merge_workflow_m365_items', lambda *_args: None)
    saves = []
    monkeypatch.setattr(runner, '_save_workflow_run_record', lambda _workflow, run: saves.append(deepcopy(run)))
    app = Flask(__name__)
    app.secret_key = 'offline-workflow-test'
    with app.test_request_context('/'):
        session['user'] = {'oid': OWNER, 'name': 'Workflow owner', 'roles': ['User']}
        yield SimpleNamespace(
            runner=runner, publisher=publisher, collaboration=collaboration, operations=operations,
            notifications=notifications, conversations=conversations, messages=messages,
            shared_conversations=shared_conversations, shared_messages=shared_messages,
            states=states, notification_store=notification_store, groups=group_store, saves=saves,
        )


def configuration(conversation_type='personal', mode='conversation', all_members=False):
    shared = conversation_type in {'shared', 'group_shared'}
    return {
        'version': 1, 'mode': mode, 'conversation_type': conversation_type,
        'recipient_ids': [MEMBER] if shared and not all_members else [],
        'all_group_members': all_members,
    }


def seed_run(delivery, *, run_id='run-one', conversation_type='personal', all_members=False):
    workflow = {
        'id': 'workflow-one', 'user_id': OWNER, 'name': 'Events roundup', 'runner_type': 'model',
        'schedule': {'kind': 'calendar', 'timezone': 'America/New_York'},
        'results_delivery': configuration(conversation_type, all_members=all_members),
    }
    if conversation_type.startswith('group'):
        workflow['group_id'] = GROUP
    run = {
        'id': run_id, 'workflow_id': workflow['id'], 'workflow_name': 'Events roundup',
        'started_at': STARTED, 'status': 'completed', 'success': True, 'user_id': OWNER,
    }
    audit = delivery.runner._ensure_workflow_conversation(workflow, run, run_id)
    run['conversation_id'] = audit['id']
    source = {
        'id': f'answer-{run_id}', 'conversation_id': audit['id'], 'role': 'assistant',
        'content': 'Here are the sourced events for the next ten days. [1]',
        'timestamp': STARTED, 'web_search_citations': [{'url': 'https://example.org/events', 'title': 'Events'}],
        'metadata': {
            'source': 'workflow', 'token_usage': {'total_tokens': 23},
            'workflow': {'run_id': run_id, 'private_task_prompt': 'Never publish this prompt'},
            'private_tool_log': 'Never publish this log',
        },
    }
    delivery.messages.upsert_item(source)
    return workflow, run, source


def publish(delivery, workflow, run, source):
    return delivery.runner._publish_configured_workflow_results(workflow, run, source, {})


def test_audit_new_runs_are_distinct_and_resume_preserves_binding_and_manual_title(delivery):
    workflow, first, _source = seed_run(delivery)
    workflow['conversation_id'] = first['conversation_id']
    second = {**first, 'id': 'run-two', 'conversation_id': None, 'started_at': '2026-10-16T17:00:01+00:00'}
    second_audit = delivery.runner._ensure_workflow_conversation(workflow, second, second['id'])
    assert second_audit['id'] != first['conversation_id']
    assert second_audit['title'] != delivery.conversations.read_item(first['conversation_id'], first['conversation_id'])['title']
    old_audit = delivery.conversations.read_item(first['conversation_id'], first['conversation_id'])
    assert isinstance(old_audit, CosmosDict) and old_audit['_etag']
    old_audit['title'] = 'My manually renamed audit'
    delivery.conversations.upsert_item(old_audit)
    resumed = delivery.runner._ensure_workflow_conversation({**workflow, 'name': 'Edited workflow'}, first, first['id'])
    assert resumed['id'] == first['conversation_id']
    assert resumed['title'] == 'My manually renamed audit'
    assert type(resumed) is dict


def test_old_inflight_audit_is_not_migrated_or_renamed(delivery):
    workflow, run, _source = seed_run(delivery)
    historic = delivery.conversations.read_item(run['conversation_id'], run['conversation_id'])
    historic['title'] = 'Workflow: Historic workflow'
    delivery.conversations.upsert_item(historic)
    historic = delivery.conversations.read_item(historic['id'], historic['id'])
    resumed = delivery.runner._ensure_workflow_conversation(workflow, run, run['id'])
    assert resumed['title'] == historic['title']
    assert resumed['_etag'] == historic['_etag']


def test_titles_use_snapshot_schedule_timezone_and_stable_seconds(delivery):
    workflow, run, _source = seed_run(delivery)
    title = delivery.publisher.workflow_run_title({**workflow, 'name': 'Edited name'}, run)
    assert title == 'Events roundup · Oct 16, 2026, 1:00:00 PM'
    assert 'Workflow:' not in title
    fallback = delivery.publisher.workflow_run_title({'name': 'Manual'}, {**run, 'workflow_name': 'Manual'})
    assert fallback == 'Manual · Oct 16, 2026, 5:00:00 PM'
    snapshot = delivery.publisher.workflow_run_title(
        {**workflow, 'schedule': {'timezone': 'Asia/Tokyo'}}, {**run, 'time_zone': 'America/New_York'},
    )
    assert snapshot == title


@pytest.mark.parametrize('conversation_type,chat_type', [
    ('personal', 'personal_single_user'), ('shared', 'personal_multi_user'),
    ('group', 'group-single-user'), ('group_shared', 'group_multi_user'),
])
def test_result_types_reuse_normal_access_invites_and_keep_audit_private(delivery, conversation_type, chat_type):
    workflow, run, source = seed_run(delivery, conversation_type=conversation_type)
    audit_id = run['conversation_id']
    receipt = publish(delivery, workflow, run, source)
    shared = conversation_type in {'shared', 'group_shared'}
    store = delivery.shared_conversations if shared else delivery.conversations
    conversation = store.read_item(receipt['conversation_id'], receipt['conversation_id'])
    assert isinstance(conversation, CosmosDict) and conversation['_etag']
    assert receipt['status'] == 'delivered'
    assert conversation['chat_type'] == chat_type
    assert conversation['workflow_id'] == workflow['id']
    assert conversation['title'] == 'Events roundup · Oct 16, 2026, 1:00:00 PM'
    message_store = delivery.shared_messages if shared else delivery.messages
    message = message_store.read_item(receipt['message_id'], receipt['conversation_id'])
    assert message['content'] == source['content']
    assert message['web_search_citations'] == source['web_search_citations']
    assert 'private_task_prompt' not in repr(dict(message))
    assert 'private_tool_log' not in repr(dict(message))
    assert audit_id not in repr(dict(message))
    assert run['conversation_id'] == audit_id
    audit = delivery.conversations.read_item(audit_id, audit_id)
    assert audit['is_hidden'] is True
    if shared:
        participant = next(person for person in conversation['participants'] if person['user_id'] == MEMBER)
        assert participant['status'] == 'pending'
        assert conversation['scope']['visibility_mode'] == 'invited_members'
        assert len(delivery.notification_store.items) == 1
        backing = delivery.conversations.read_item(conversation['source_conversation_id'], conversation['source_conversation_id'])
        assert backing['is_hidden'] and backing['id'] != audit_id
    elif conversation_type == 'group':
        assert conversation['user_id'] == OWNER and conversation['group_id'] == GROUP


@pytest.mark.parametrize('conversation_type,chat_type,actor', [
    ('personal', 'personal_single_user', OWNER),
    ('group', 'group-single-user', OWNER),
    ('shared', 'personal_multi_user', OWNER),
    ('shared', 'personal_multi_user', MEMBER),
    ('group_shared', 'group_multi_user', OWNER),
    ('group_shared', 'group_multi_user', MEMBER),
])
def test_results_accept_ordinary_followup_context_and_keep_delivered_answer_in_model_history(
    delivery, monkeypatch, conversation_type, chat_type, actor,
):
    """Use actual chat authorization/history owners, not a fabricated result link."""
    chats = importlib.import_module('route_backend_chats')
    shared_routes = importlib.import_module('route_backend_collaboration')
    monkeypatch.setattr(chats, 'cosmos_conversations_container', delivery.conversations)
    monkeypatch.setattr(chats, 'cosmos_messages_container', delivery.messages)
    monkeypatch.setattr(chats, 'debug_print', lambda *_args, **_kwargs: None)
    for module in (delivery.operations, delivery.collaboration):
        monkeypatch.setattr(module, 'log_chat_activity', lambda **_kwargs: None)
    workflow, run, source = seed_run(delivery, conversation_type=conversation_type)
    receipt = publish(delivery, workflow, run, source)
    shared = conversation_type in {'shared', 'group_shared'}
    store = delivery.shared_conversations if shared else delivery.conversations
    conversation = store.read_item(receipt['conversation_id'], receipt['conversation_id'])
    assert isinstance(conversation, CosmosDict)
    assert conversation['chat_type'] == chat_type and not conversation.get('is_hidden')
    assert conversation['workflow_provenance'] == {'workflow_id': workflow['id'], 'run_id': run['id']}
    current_user = {'user_id': actor, 'display_name': 'Conversation participant'}
    question = 'Which of those events should I prioritize, and why?'
    if shared:
        with pytest.raises(PermissionError):
            delivery.collaboration.assert_user_can_participate_in_collaboration_conversation(MEMBER, conversation)
        if actor == MEMBER:
            conversation, _state, participant = delivery.collaboration.record_personal_invite_response(
                conversation['id'], MEMBER, 'accept',
            )
            assert participant['status'] == 'accepted'
        access = delivery.collaboration.assert_user_can_participate_in_collaboration_conversation(actor, conversation)
        assert access is not None
        backing, conversation = delivery.collaboration.ensure_collaboration_source_conversation(
            conversation, current_user,
        )
        request_payload = shared_routes._build_collaboration_stream_request_payload({}, backing['id'], question)
        continued_id = request_payload['conversation_id']
        assert continued_id == conversation['source_conversation_id'] and continued_id != run['conversation_id']
        resolved, context = chats._resolve_authorized_conversation_context(actor, continued_id)
        assert context['is_collaboration_source'] is True
        assert context['collaboration_conversation_id'] == receipt['conversation_id']
    else:
        resolved, continued_id = chats._resolve_or_create_authorized_personal_conversation(actor, conversation['id'])
        assert continued_id == receipt['conversation_id']
        _resolved, context = chats._resolve_authorized_conversation_context(actor, continued_id)
        assert context['is_owner'] is True
    assert resolved['chat_type'] != 'workflow'
    if conversation_type.startswith('group'):
        primary = next(item for item in resolved['context'] if item.get('type') == 'primary')
        assert primary['scope'] == 'group' and primary['id'] == GROUP
    with pytest.raises(PermissionError):
        chats._resolve_authorized_conversation_context(OTHER, continued_id)
    with pytest.raises(PermissionError):
        chats._resolve_authorized_conversation_context(MEMBER, run['conversation_id'])
    session['user'] = {'oid': actor, 'name': current_user['display_name'], 'roles': ['User']}
    followup, updated = delivery.operations._persist_personal_conversation_message(
        conversation_item=resolved,
        current_user_info={'userId': actor, 'displayName': current_user['display_name']},
        content=question,
    )
    assert updated['id'] == continued_id and updated['chat_type'] == resolved['chat_type']
    messages = list(delivery.messages.query_items(
        query='SELECT * FROM c WHERE c.conversation_id = @conversation_id ORDER BY c.timestamp ASC',
        parameters=[{'name': '@conversation_id', 'value': continued_id}], partition_key=continued_id,
    ))
    history = chats.build_conversation_history_segments(
        messages, 10, user_message_id=followup['id'], fallback_user_message=question,
    )
    assert any(
        message['role'] == 'assistant' and source['content'] in message['content']
        for message in history['history_messages']
    )
    assert history['history_messages'][-1] == {'role': 'user', 'content': question}
    assert run['conversation_id'] not in repr(history['history_messages'])
    assert 'Never publish this prompt' not in repr(history['history_messages'])


@pytest.mark.parametrize('mode', ['history', 'task', 'legacy', 'chat'])
def test_delivery_modes_do_not_create_automatic_duplicates(delivery, mode):
    workflow, run, source = seed_run(delivery)
    if mode == 'legacy':
        workflow.pop('results_delivery')
    elif mode == 'chat':
        run.update(chat_delivery={'version': 1}, chat_invocation={'conversation_id': 'origin-chat'})
    else:
        workflow['results_delivery'] = configuration(mode=mode)
    before = len(delivery.conversations.items)
    receipt = publish(delivery, workflow, run, source)
    assert receipt is None
    assert len(delivery.conversations.items) == before
    assert 'results_delivery_receipt' not in run


def test_delivery_retry_reuses_message_invites_and_preserves_rename_pin_read_state(delivery, monkeypatch):
    workflow, run, source = seed_run(delivery, conversation_type='shared')
    real_notify = delivery.publisher._notify_result_invites
    attempts = []

    def interrupt_after_notification(*args):
        real_notify(*args)
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError('Injected interruption after invitation persisted')

    monkeypatch.setattr(delivery.publisher, '_notify_result_invites', interrupt_after_notification)
    with pytest.raises(RuntimeError):
        publish(delivery, workflow, run, source)
    pending = deepcopy(run['results_delivery_receipt'])
    assert pending['status'] == 'pending'
    assert not delivery.conversations.read_item(run['conversation_id'], run['conversation_id'])['is_hidden']
    assert len(delivery.shared_messages.items) == 1
    conversation = delivery.shared_conversations.read_item(pending['conversation_id'], pending['conversation_id'])
    conversation['title'] = 'My result title'
    delivery.shared_conversations.upsert_item(conversation)
    state = delivery.states.read_item(f'{OWNER}:{conversation["id"]}', OWNER)
    state.update(is_pinned=True, last_read_message_id=pending['message_id'])
    delivery.states.upsert_item(state)
    completed = publish(delivery, workflow, run, source)
    publish(delivery, workflow, run, source)
    assert completed['message_id'] == pending['message_id']
    assert len(delivery.shared_conversations.items) == 1
    assert len(delivery.shared_messages.items) == 1
    assert len(delivery.notification_store.items) == 1
    latest = delivery.shared_conversations.read_item(conversation['id'], conversation['id'])
    assert latest['title'] == 'My result title'
    state = delivery.states.read_item(state['id'], OWNER)
    assert state['is_pinned'] is True and state['last_read_message_id'] == pending['message_id']


def test_group_all_members_is_resolved_for_each_run_not_a_saved_audience(delivery):
    workflow, run, source = seed_run(delivery, conversation_type='group_shared', all_members=True)
    first = publish(delivery, workflow, run, source)
    assert first['recipient_ids'] == [MEMBER]
    group = delivery.groups.read_item(GROUP, GROUP)
    group['users'].append({'userId': OTHER, 'displayName': 'New member', 'role': 'user'})
    delivery.groups.upsert_item(group)
    second_workflow, second_run, second_source = seed_run(
        delivery, run_id='run-two', conversation_type='group_shared', all_members=True,
    )
    second = publish(delivery, second_workflow, second_run, second_source)
    assert second['recipient_ids'] == [MEMBER, OTHER]
    assert second['conversation_id'] != first['conversation_id']


def test_removed_group_recipient_or_owner_cannot_publish(delivery):
    workflow, run, source = seed_run(delivery, conversation_type='group_shared')
    group = delivery.groups.read_item(GROUP, GROUP)
    group['users'] = []
    delivery.groups.upsert_item(group)
    with pytest.raises(PermissionError):
        publish(delivery, workflow, run, source)
    assert not delivery.shared_conversations.items
    group['owner'] = {'id': OTHER}
    delivery.groups.upsert_item(group)
    with pytest.raises(PermissionError):
        publish(delivery, workflow, run, source)


def test_empty_outcome_never_publishes_or_hides_only_audit(delivery):
    workflow, run, source = seed_run(delivery)
    source['content'] = ''
    result = publish(delivery, workflow, run, source)
    assert result is None
    assert not delivery.conversations.read_item(run['conversation_id'], run['conversation_id'])['is_hidden']


def test_group_alert_links_exclude_private_audit_and_uninvited_readers(delivery):
    notifications = delivery.notifications
    notification = {'scope': 'group', 'group_id': GROUP}
    private_target = {
        'conversation_id': 'private-result', 'authorized_user_ids': [OWNER],
        'link_context': {'conversation_id': 'private-result', 'chat_type': 'group-single-user', 'group_id': GROUP},
    }
    shared_target = {
        'conversation_id': 'shared-result', 'authorized_user_ids': [OWNER, MEMBER],
        'link_context': {'conversation_id': 'shared-result', 'chat_type': 'group_multi_user', 'group_id': GROUP},
    }
    audit_target = {
        'conversation_id': 'audit', 'link_context': {'conversation_id': 'audit', 'chat_type': 'workflow', 'group_id': GROUP},
    }
    metadata = {'conversation_id': 'audit', 'link_targets': [private_target, shared_target, audit_target]}
    member_links = notifications._member_workflow_alert_links(notification, metadata, MEMBER)
    other_links = notifications._member_workflow_alert_links(notification, metadata, OTHER)
    assert [link['conversation_id'] for link in member_links] == ['shared-result']
    assert 'authorized_user_ids' not in member_links[0]
    assert other_links == []


@pytest.mark.parametrize('conversation_type', ['personal', 'shared'])
def test_generated_file_is_independently_published_and_retry_reuses_bytes(delivery, monkeypatch, conversation_type):
    workflow, run, source = seed_run(delivery, conversation_type=conversation_type)
    class PublicationBlobIO(HarnessBlobIO):
        def get_blob_client(self, **kwargs):
            client = super().get_blob_client(**kwargs)
            upload = client.upload_blob

            def upload_publication(stream=None, *, overwrite, **options):
                if overwrite and hasattr(stream, 'read'):
                    # Ordinary published copies use the existing mutable chat
                    # uploader; retained production outputs remain immutable.
                    upload(stream.read(), overwrite=True, **options)
                    self.file_uploads += 1
                else:
                    upload(stream, overwrite=overwrite, **options)

            client.upload_blob = upload_publication
            return client

    blobs = PublicationBlobIO()
    monkeypatch.setitem(delivery.runner.CLIENTS, 'storage_account_office_docs_client', blobs)
    content = b'event,date\nCommunity festival,2026-10-17\n'
    uploaded = delivery.operations.upload_generated_file_artifact_stream_for_user(
        OWNER, run['conversation_id'], 'events.csv', io.BytesIO(content), len(content),
        capability='analysis', output_format='csv', artifact_idempotency_key='original-events',
    )
    source['generated_artifacts'] = [{
        'artifact_message_id': uploaded['message']['id'], 'conversation_id': run['conversation_id'],
        'file_name': 'events.csv', 'output_format': 'csv',
    }]
    receipt = publish(delivery, workflow, run, source)
    store = delivery.shared_messages if conversation_type == 'shared' else delivery.messages
    result = store.read_item(receipt['message_id'], receipt['conversation_id'])
    card = result['generated_artifacts'][0]
    assert card['conversation_id'] != run['conversation_id']
    assert card['artifact_message_id'] != uploaded['message']['id']
    copied = delivery.messages.read_item(card['artifact_message_id'], card['conversation_id'])
    assert isinstance(copied, CosmosDict) and copied['_etag']
    assert not (copied.get('metadata') or {}).get('generated_artifact_source')
    retained = blobs.get_blob_client(container=copied['blob_container'], blob=copied['blob_path']).download_blob().readall()
    assert retained == content
    upload_count = blobs.file_uploads
    publish(delivery, workflow, run, source)
    assert blobs.file_uploads == upload_count == 2


@pytest.mark.parametrize('conversation_type', ['personal', 'shared'])
@pytest.mark.parametrize('storage', ['inline', 'chunked', 'blob'])
def test_generated_images_survive_publication_without_audit_references(delivery, monkeypatch, conversation_type, storage):
    images = importlib.import_module('functions_image_messages')
    workflow, run, source = seed_run(delivery, conversation_type=conversation_type)
    blobs = HarnessBlobIO()
    monkeypatch.setitem(delivery.runner.CLIENTS, 'storage_account_office_docs_client', blobs)
    content = 'data:image/png;base64,' + 'YWJj' * 120
    image = {
        'id': 'retained-image', 'conversation_id': run['conversation_id'], 'role': 'image',
        'timestamp': STARTED, 'content': content,
        'metadata': {'image_proposal': {'visualId': 'visual-one', 'source_assistant_message_id': source['id']}},
    }
    if storage == 'blob':
        image.update(
            file_content_source='blob', blob_container='images',
            blob_path=f"{OWNER}/{run['conversation_id']}/images/{image['id']}/image.png",
            content=f"/api/image/{image['id']}",
        )
        blobs.get_blob_client(container=image['blob_container'], blob=image['blob_path']).upload_blob(b'abc', overwrite=True)
        documents = [image]
    else:
        documents = images.build_image_message_documents(image, max_content_size=350 if storage == 'chunked' else 1500000)
    for document in documents:
        delivery.messages.upsert_item(document)
    source['metadata']['orchestration'] = {
        'generated_images': [{'message_id': image['id'], 'visual_id': 'visual-one', 'title': 'Events'}],
        'private_tool_log': 'Do not copy this log',
    }
    receipt = publish(delivery, workflow, run, source)
    shared = conversation_type == 'shared'
    store = delivery.shared_messages if shared else delivery.messages
    result = store.read_item(receipt['message_id'], receipt['conversation_id'])
    delivered_image_id = result['metadata']['orchestration']['generated_images'][0]['message_id']
    delivered_image = store.read_item(delivered_image_id, receipt['conversation_id'])
    assert isinstance(delivered_image, CosmosDict)
    assert run['conversation_id'] not in repr(dict(delivered_image))
    assert run['conversation_id'] not in repr(dict(result))
    assert 'private_tool_log' not in repr(dict(result))
    assert '```simpleimage' in result['content'] and '"visualId": "visual-one"' in result['content']
    if shared:
        metadata = delivered_image['metadata']
        copied = delivery.messages.read_item(metadata['source_message_id'], metadata['source_conversation_id'])
    else:
        copied = delivered_image
    if storage == 'blob':
        assert copied['content'] == f"/api/image/{copied['id']}"
        retained = blobs.get_blob_client(container=copied['blob_container'], blob=copied['blob_path']).download_blob().readall()
        assert retained == b'abc'
    else:
        chunks = [item for item in delivery.messages.items.values() if item.get('parent_message_id') == copied['id']]
        hydrated = images.reassemble_image_message_content(copied, chunks)
        assert hydrated == content
    before_messages = (len(delivery.messages.items), len(delivery.shared_messages.items))
    before_uploads = blobs.image_uploads
    publish(delivery, workflow, run, source)
    assert (len(delivery.messages.items), len(delivery.shared_messages.items)) == before_messages
    assert blobs.image_uploads == before_uploads


def test_invalid_retained_file_binding_fails_without_hiding_audit(delivery):
    workflow, run, source = seed_run(delivery)
    delivery.messages.upsert_item({
        'id': 'unbound-file', 'conversation_id': run['conversation_id'], 'role': 'file',
        'filename': 'events.csv',
        'metadata': {'generated_artifact_source_required': True, 'generated_artifact_source': {'kind': 'unknown'}},
    })
    source['generated_artifacts'] = [{'artifact_message_id': 'unbound-file'}]
    unavailable = importlib.import_module('functions_analysis_access').AnalysisResultUnavailable
    with pytest.raises(unavailable):
        publish(delivery, workflow, run, source)
    audit = delivery.conversations.read_item(run['conversation_id'], run['conversation_id'])
    assert not audit['is_hidden']
    assert run['results_delivery_receipt']['status'] == 'pending'


def test_actual_priority_alert_prefers_receipted_result_and_deduplicates(delivery, monkeypatch):
    workflow, run, source = seed_run(delivery)
    receipt = publish(delivery, workflow, run, source)
    audit = delivery.conversations.read_item(run['conversation_id'], run['conversation_id'])
    monkeypatch.setattr(delivery.runner, 'resolve_workflow_alert_config', lambda _workflow: {'alert_mode': 'rules'})
    monkeypatch.setattr(delivery.runner, '_workflow_alert_rules_need_model_evaluation', lambda *_args: False)
    monkeypatch.setattr(delivery.runner, 'evaluate_workflow_alert_rules', lambda *_args, **_kwargs: {
        'should_alert': True, 'severity': 'high', 'mode': 'rules', 'audience': 'owner',
    })
    first = delivery.runner._create_workflow_priority_alert(workflow, run, audit, {
        'alert_targets': [{'conversation_id': 'heuristically-preferred-other-result', 'link_url': '/chats'}],
    })
    repeated = delivery.runner._create_workflow_priority_alert(workflow, run, audit, {})
    assert first is not None and repeated is not None
    assert first['id'] == repeated['id']
    assert first['link_context']['conversation_id'] == receipt['conversation_id']
    assert [
        (target['label'], target['conversation_id']) for target in first['metadata']['link_targets']
    ] == [('Open results', receipt['conversation_id']), ('Run history', run['conversation_id'])]
    assert len(delivery.notification_store.items) == 1


@pytest.mark.parametrize('conversation_type', ['personal', 'shared'])
def test_retry_repairs_conversation_summary_after_message_only_write(delivery, monkeypatch, conversation_type):
    workflow, run, source = seed_run(delivery, conversation_type=conversation_type)
    shared = conversation_type == 'shared'
    store = delivery.shared_conversations if shared else delivery.conversations
    save = store.upsert_item
    failures = []

    def interrupt_summary(document):
        is_summary = document.get('message_count') == 1 if shared else document.get('workflow_result_message_id')
        if is_summary and not failures:
            failures.append(True)
            raise RuntimeError('Interrupted after message write, before summary write')
        return save(document)

    monkeypatch.setattr(store, 'upsert_item', interrupt_summary)
    with pytest.raises(RuntimeError, match='Interrupted'):
        publish(delivery, workflow, run, source)
    assert not delivery.conversations.read_item(run['conversation_id'], run['conversation_id'])['is_hidden']
    receipt = publish(delivery, workflow, run, source)
    conversation = store.read_item(receipt['conversation_id'], receipt['conversation_id'])
    if shared:
        assert conversation['message_count'] == 1
    else:
        assert conversation['has_unread_assistant_response'] is True
        assert conversation['last_unread_assistant_message_id'] == receipt['message_id']
    message_store = delivery.shared_messages if shared else delivery.messages
    published = [message for message in message_store.items.values() if message['conversation_id'] == receipt['conversation_id']]
    assert len(published) == 1
