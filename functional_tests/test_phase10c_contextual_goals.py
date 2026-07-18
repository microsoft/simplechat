#!/usr/bin/env python3
# test_phase10c_contextual_goals.py
"""
Functional test for Phase 10C bounded contextual goals.
Version: 0.250.076
Implemented in: 0.250.076

This test ensures planning context contains only bounded active user turns,
opaque refs bind to exact documents, and prior-turn external egress remains a
server-authored choice even when retrieval is already selected.
"""

import copy
import importlib
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
sys.path.insert(0, str(SINGLE_APP_ROOT))

from functions_chat_capabilities import (  # noqa: E402
    build_contextual_egress_recommendation,
    build_governed_capability_inventory,
    get_capability_option_revalidation_error,
)
from functions_chat_capability_choices import (  # noqa: E402
    CapabilityChoiceError,
    add_sensitive_external_query_options,
)
from functions_chat_contextual_goals import (  # noqa: E402
    load_bounded_prior_user_turns,
    planner_prior_user_turns,
    read_exact_goal_source_messages,
    resolve_planner_goal_source_messages,
)


def _message(
    message_id,
    role,
    content,
    timestamp,
    thread_id,
    previous_thread_id='',
    *,
    active=True,
    deleted=False,
    masked=False,
    masked_ranges=None,
    generated_artifact=False,
    attempt=1,
):
    return {
        'id': message_id,
        'conversation_id': 'conversation-1',
        'role': role,
        'content': content,
        'timestamp': timestamp,
        'metadata': {
            'is_deleted': deleted,
            'masked': masked,
            'masked_ranges': list(masked_ranges or []),
            'is_generated_chat_artifact': generated_artifact,
            'thread_info': {
                'thread_id': thread_id,
                'previous_thread_id': previous_thread_id,
                'thread_attempt': attempt,
                'active_thread': active,
            },
        },
    }


class _FakeContainer:
    def __init__(self, messages):
        self.messages = {
            message['id']: copy.deepcopy(message)
            for message in messages
        }
        self.query_calls = []
        self.read_calls = []

    @staticmethod
    def _is_active_user(message):
        metadata = message.get('metadata') or {}
        thread_info = metadata.get('thread_info') or {}
        return bool(
            message.get('conversation_id') == 'conversation-1'
            and message.get('role') == 'user'
            and metadata.get('is_deleted') is not True
            and metadata.get('masked') is not True
            and not (metadata.get('masked_ranges') or [])
            and metadata.get('is_generated_chat_artifact') is not True
            and thread_info.get('active_thread') is not False
        )

    def query_items(self, *, query, parameters, partition_key):
        self.query_calls.append({
            'query': query,
            'parameters': copy.deepcopy(parameters),
            'partition_key': partition_key,
        })
        assert partition_key == 'conversation-1'
        parameter_map = {
            parameter['name']: parameter['value']
            for parameter in parameters
        }
        assert parameter_map['@conversation_id'] == 'conversation-1'
        candidates = [
            copy.deepcopy(message)
            for message in self.messages.values()
            if self._is_active_user(message)
        ]
        thread_id = parameter_map.get('@thread_id')
        if thread_id:
            candidates = [
                message
                for message in candidates
                if str(
                    message.get('metadata', {}).get(
                        'thread_info', {}
                    ).get('thread_id') or ''
                ) == thread_id
            ]
            candidates.sort(
                key=lambda message: (
                    message['metadata']['thread_info']['thread_attempt'],
                    message['timestamp'],
                ),
                reverse=True,
            )
            return candidates[:2]
        candidates.sort(key=lambda message: message['timestamp'], reverse=True)
        return candidates[:2]

    def read_item(self, *, item, partition_key):
        self.read_calls.append((item, partition_key))
        assert partition_key == 'conversation-1'
        return copy.deepcopy(self.messages[item])


def _context_messages():
    return [
        _message(
            'user-0',
            'user',
            'Find JPMorgan press releases.',
            '2026-07-17T10:00:00+00:00',
            'thread-0',
        ),
        _message(
            'assistant-0',
            'assistant',
            'SECRET assistant URL https://private.example',
            '2026-07-17T10:00:01+00:00',
            'thread-0',
        ),
        _message(
            'user-1-inactive',
            'user',
            'Use an inactive edit.',
            '2026-07-17T10:01:00+00:00',
            'thread-1',
            'thread-0',
            active=False,
            attempt=1,
        ),
        _message(
            'user-1',
            'user',
            'Use the past three years.',
            '2026-07-17T10:01:01+00:00',
            'thread-1',
            'thread-0',
            attempt=2,
        ),
        _message(
            'user-deleted',
            'user',
            'SECRET deleted turn.',
            '2026-07-17T10:02:00+00:00',
            'thread-deleted',
            'thread-1',
            deleted=True,
        ),
        _message(
            'user-partially-masked',
            'user',
            'SECRET partially masked turn.',
            '2026-07-17T10:02:01+00:00',
            'thread-partial',
            'thread-1',
            masked_ranges=[{'start': 0, 'end': 6}],
        ),
        _message(
            'user-generated-artifact',
            'user',
            'SECRET generated artifact.',
            '2026-07-17T10:02:02+00:00',
            'thread-artifact',
            'thread-1',
            generated_artifact=True,
        ),
    ]


def test_context_loader_follows_two_active_user_hops_only():
    container = _FakeContainer(_context_messages())

    state = load_bounded_prior_user_turns(
        container,
        conversation_id='conversation-1',
    )

    assert [
        message['id']
        for message in state['prior_user_messages']
    ] == ['user-0', 'user-1']
    assert state['predecessor_thread_id'] == 'thread-1'
    assert planner_prior_user_turns(state) == [
        {'role': 'user', 'text': 'Find JPMorgan press releases.'},
        {'role': 'user', 'text': 'Use the past three years.'},
    ]
    assert len(container.query_calls) == 2
    assert all(
        call['partition_key'] == 'conversation-1'
        and '@conversation_id' in {
            parameter['name']
            for parameter in call['parameters']
        }
        and 'c.role = "user"' in call['query']
        for call in container.query_calls
    )


def test_context_loader_falls_back_past_one_malformed_latest_response():
    for malformed_response in (
        _message(
            'user-response-empty',
            'user',
            '',
            '2026-07-17T10:02:00+00:00',
            'thread-response',
            'thread-1',
        ),
        {
            **_message(
                'user-response-no-thread',
                'user',
                'Virginia',
                '2026-07-17T10:02:00+00:00',
                'thread-response',
                'thread-1',
            ),
            'metadata': {},
        },
    ):
        container = _FakeContainer([
            *_context_messages(),
            malformed_response,
        ])

        state = load_bounded_prior_user_turns(
            container,
            conversation_id='conversation-1',
        )

        assert [
            message['id']
            for message in state['prior_user_messages']
        ] == ['user-0', 'user-1']
        assert state['predecessor_thread_id'] == 'thread-1'
        assert 'SELECT TOP 2 * FROM c' in container.query_calls[0]['query']


def test_context_loader_rejects_ambiguous_active_attempts():
    messages = _context_messages()
    messages.append(_message(
        'user-0-conflict',
        'user',
        'Conflicting active attempt.',
        '2026-07-17T10:00:02+00:00',
        'thread-0',
        attempt=2,
    ))
    container = _FakeContainer(messages)

    try:
        load_bounded_prior_user_turns(
            container,
            conversation_id='conversation-1',
        )
        raise AssertionError('ambiguous active attempts must fail closed')
    except CapabilityChoiceError as exc:
        assert exc.code == 'goal_source_thread_ambiguous'


def test_opaque_goal_refs_bind_to_exact_request_local_documents():
    container = _FakeContainer(_context_messages())
    state = load_bounded_prior_user_turns(
        container,
        conversation_id='conversation-1',
    )
    current_message = _message(
        'user-2',
        'user',
        'Yes, search.',
        '2026-07-17T10:03:00+00:00',
        'thread-2',
        'thread-1',
    )
    planner_request = {
        'dialogue_context': [
            {'ref': 'turn_0', 'role': 'user', 'text': 'Find JPMorgan press releases.'},
            {'ref': 'turn_1', 'role': 'user', 'text': 'Use the past three years.'},
            {'ref': 'turn_2', 'role': 'user', 'text': 'Yes, search.'},
        ],
    }
    planner_result = {
        'goal_turn_refs': ['turn_0', 'turn_2'],
    }

    resolved = resolve_planner_goal_source_messages(
        planner_request,
        planner_result,
        state,
        current_message,
    )

    assert [message['id'] for message in resolved] == ['user-0', 'user-2']
    stored_goal = {
        'source_user_message_ids': ['user-0', 'user-2'],
    }
    container.messages['user-2'] = current_message
    reread = read_exact_goal_source_messages(
        container,
        conversation_id='conversation-1',
        stored_goal=stored_goal,
    )
    assert [message['id'] for message in reread] == ['user-0', 'user-2']
    assert container.read_calls == [
        ('user-0', 'conversation-1'),
        ('user-2', 'conversation-1'),
    ]


def test_clarification_linked_prior_ref_retains_exact_response_turn():
    container = _FakeContainer(_context_messages())
    state = load_bounded_prior_user_turns(
        container,
        conversation_id='conversation-1',
    )
    current_message = _message(
        'user-2',
        'user',
        'Virginia and Fairfax County',
        '2026-07-17T10:03:00+00:00',
        'thread-2',
        'thread-1',
    )
    resolved = resolve_planner_goal_source_messages(
        {
            'dialogue_context': [
                {
                    'ref': 'turn_0',
                    'role': 'user',
                    'text': 'Find JPMorgan press releases.',
                },
                {
                    'ref': 'turn_1',
                    'role': 'user',
                    'text': 'Use the past three years.',
                },
                {
                    'ref': 'turn_2',
                    'role': 'user',
                    'text': 'Virginia and Fairfax County',
                },
            ],
            'structured_state': {
                'type': 'clarification',
                'source_goal_ref': 'turn_0',
                'status': 'resolved',
                'code': 'jurisdiction_required',
            },
        },
        {'goal_turn_refs': ['turn_0']},
        state,
        current_message,
    )

    assert [message['id'] for message in resolved] == ['user-0', 'user-2']


def _selected_web_inventory():
    resolved = {
        capability_id: {
            'enabled': True,
            'available': True,
            'authorized': True,
            'governance_mode': 'recommend',
        }
        for capability_id in (
            'workspace_search',
            'analyze',
            'compare',
            'image',
            'web_search',
            'url_access',
            'deep_research',
        )
    }
    return build_governed_capability_inventory(
        selected_capability_ids=['web_search'],
        resolved_capabilities=resolved,
    )


def test_selected_external_capability_gets_context_only_egress_choice():
    inventory = _selected_web_inventory()
    recommendation = build_contextual_egress_recommendation(
        {
            'status': 'valid',
            'decision': 'direct',
            'prior_goal_included': True,
            'requirements': [],
        },
        inventory,
        {'selected_capability_ids': ['web_search']},
    )

    option = recommendation['options'][0]
    assert option['kind'] == 'context'
    assert option['capability_ids'] == []
    assert option['effective_capability_ids'] == ['web_search']
    assert option['external_data'] is True
    assert option['id'].startswith('context:')
    assert get_capability_option_revalidation_error(option, inventory) is None

    changed_option = copy.deepcopy(option)
    changed_option['cost_class'] = 'none'
    assert get_capability_option_revalidation_error(
        changed_option,
        inventory,
    ) == 'capability_plan_policy_changed'

    sensitive = add_sensitive_external_query_options(
        recommendation,
        'Search parcel records for 1234 Main Street, Fairfax VA 22030.',
    )
    sensitive_option = next(
        candidate
        for candidate in sensitive['options']
        if candidate['id'].endswith('_with_sensitive_inputs')
    )
    assert sensitive_option['kind'] == 'context'
    assert sensitive_option['sensitive_input_types'] == ['street_address']
    assert get_capability_option_revalidation_error(
        sensitive_option,
        inventory,
    ) is None


def test_route_wiring_separates_contextual_and_external_queries_and_projects_metadata():
    chat_route = (SINGLE_APP_ROOT / 'route_backend_chats.py').read_text(
        encoding='utf-8'
    )
    backend_conversations = (
        SINGLE_APP_ROOT / 'route_backend_conversations.py'
    ).read_text(encoding='utf-8')
    frontend_conversations = (
        SINGLE_APP_ROOT / 'route_frontend_conversations.py'
    ).read_text(encoding='utf-8')

    assert "request_data['_server_contextual_goal_query']" in chat_route
    assert "request_data['_server_external_query']" in chat_route
    assert "data.get('_server_contextual_goal_query')" in chat_route
    assert "approved_user_turn_goal.get('contextual_query')" in chat_route
    assert "approved_user_turn_goal.get('external_query')" in chat_route
    assert 'contextual_external_execution = bool(' in chat_route
    assert 'contextual_url_ref_missing = bool(' in chat_route
    assert 'if contextual_url_ref_missing:' in chat_route
    assert "'execution_effective_capability_ids'" in chat_route
    assert chat_route.index('contextual_external_execution = bool(') < (
        chat_route.index('if web_search_enabled:', chat_route.index(
            'contextual_external_execution = bool('
        ))
    )
    assert chat_route.count('project_chat_metadata_for_client(') >= 8
    for raw_terminal_metadata in (
        "'metadata': assistant_doc.get('metadata', {}),",
        "'metadata': payload.get('metadata', {}),",
        "'metadata': safety_doc.get('metadata', {}),",
    ):
        assert raw_terminal_metadata not in chat_route
    assert backend_conversations.count('_project_message_for_client(') >= 2
    assert frontend_conversations.count('_project_message_for_client(') >= 3
    assert 'project_chat_metadata_for_client(' in frontend_conversations
    context_source = (
        SINGLE_APP_ROOT / 'functions_chat_contextual_goals.py'
    ).read_text(encoding='utf-8')
    exact_thread_query = context_source[
        context_source.index('def _read_active_user_turn_for_thread('):
        context_source.index('def load_bounded_prior_user_turns(')
    ]
    assert 'ORDER BY' not in exact_thread_query
    child_output_helper = chat_route[
        chat_route.index('def _find_persisted_clarification_child_output('):
        chat_route.index('def _distinct_authorized_document_ids(')
    ]
    assert 'ORDER BY' not in child_output_helper
    retry_route = backend_conversations[
        backend_conversations.index('def retry_message(message_id):'):
        backend_conversations.index('def edit_message(message_id):')
    ]
    edit_route = backend_conversations[
        backend_conversations.index('def edit_message(message_id):'):
        backend_conversations.index('def switch_attempt(message_id):')
    ]
    for route_source, request_id_field in (
        (retry_route, "'retry_user_message_id'"),
        (edit_route, "'edited_user_message_id'"),
    ):
        validation_index = route_source.index(
            '_validate_linked_clarification_retry('
        )
        deactivation_index = route_source.index(
            "msg['metadata']['thread_info']['active_thread'] = False"
        )
        clone_index = route_source.index(
            'new_user_message_id = '
        )
        assert validation_index < deactivation_index < clone_index
        validated_branch = route_source[validation_index:deactivation_index]
        assert request_id_field in validated_branch
        assert "clarification_retry['response_user_message_id']" in (
            validated_branch
        )


def test_url_access_readiness_can_use_bounded_prior_user_url(monkeypatch):
    route_backend_chats = importlib.import_module('route_backend_chats')
    monkeypatch.setattr(
        route_backend_chats,
        'normalize_capability_governance_modes',
        lambda settings: {
            capability_id: 'recommend'
            for capability_id in (
                'workspace_search',
                'analyze',
                'compare',
                'image',
                'web_search',
                'url_access',
                'deep_research',
            )
        },
    )
    monkeypatch.setattr(
        route_backend_chats,
        'get_enabled_document_action_types',
        lambda settings=None: [],
    )
    monkeypatch.setattr(
        route_backend_chats,
        'is_url_access_enabled_for_user',
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        route_backend_chats,
        'is_source_review_enabled_for_user',
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        route_backend_chats,
        'image_generation_is_enabled',
        lambda settings: False,
    )
    monkeypatch.setattr(
        route_backend_chats,
        '_web_search_capability_is_configured',
        lambda settings: False,
    )

    inventory = route_backend_chats._resolve_server_chat_capability_inventory(
        settings={'enable_url_access': True},
        user_id='user-1',
        user_email='user@example.com',
        user_roles=[],
        user_message=(
            'Review https://example.com/authorized-source\nReview that source.'
        ),
        selected_capability_ids=[],
    )
    current_only_inventory = (
        route_backend_chats._resolve_server_chat_capability_inventory(
            settings={'enable_url_access': True},
            user_id='user-1',
            user_email='user@example.com',
            user_roles=[],
            user_message='Review that source.',
            selected_capability_ids=[],
        )
    )

    url_access = next(
        entry
        for entry in inventory['capabilities']
        if entry['id'] == 'url_access'
    )
    current_only_url_access = next(
        entry
        for entry in current_only_inventory['capabilities']
        if entry['id'] == 'url_access'
    )
    assert url_access['input_ready'] is True
    assert current_only_url_access['input_ready'] is False
