# test_chat_capability_planner_route.py
"""
Functional test for chat capability planner route placement and isolation.
Version: 0.250.077
Implemented in: 0.250.069; planner-first Assist corrected in 0.250.077

This test ensures Shadow remains isolated while Assist builds only the safe
inventory before the planner and cannot use heuristic capability suggestions.
"""

import copy
import importlib
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
sys.path.insert(0, str(SINGLE_APP_ROOT))

from functions_chat_capability_planner import (  # noqa: E402
    build_capability_planner_request,
    capability_planner_shadow_is_eligible,
    compare_capability_planner_shadow,
)


def _inventory(*, discoverable=True):
    return {
        'version': 1,
        'capabilities': [
            {
                'id': 'web_search',
                'category': 'retrieval',
                'state': 'unselected',
                'discoverable': discoverable,
                'read_only': True,
                'external_data': True,
                'risk_class': 'external_read',
                'latency_class': 'seconds',
                'cost_class': 'standard',
                'evidence_types': ['public_web'],
                'input_ready': True,
                'requires_user_choice': True,
            }
        ],
        'agents': [],
    }


def test_shadow_eligibility_excludes_off_resume_cancelled_and_empty_inventory():
    request = build_capability_planner_request('Find current sources.', _inventory())
    shadow = {'chat_capability_planner_mode': 'shadow'}

    assert capability_planner_shadow_is_eligible(shadow, request) is True
    assert capability_planner_shadow_is_eligible(
        {'chat_capability_planner_mode': 'off'},
        request,
    ) is False
    assert capability_planner_shadow_is_eligible(
        shadow,
        request,
        is_resume=True,
    ) is False
    assert capability_planner_shadow_is_eligible(
        shadow,
        request,
        cancel_requested=True,
    ) is False
    unavailable_request = build_capability_planner_request(
        'Find current sources.',
        _inventory(discoverable=False),
    )
    assert capability_planner_shadow_is_eligible(
        shadow,
        unavailable_request,
    ) is False


def test_shadow_comparison_does_not_mutate_deterministic_control():
    deterministic = {
        'recommended_option_id': 'web_search',
        'options': [
            {
                'id': 'web_search',
                'capability_ids': ['web_search'],
            }
        ],
    }
    original = copy.deepcopy(deterministic)
    comparison = compare_capability_planner_shadow(
        {
            'status': 'valid',
            'decision': 'direct',
            'candidate_plans': [],
            'recommended_plan_id': None,
        },
        deterministic,
    )

    assert comparison == {
        'planner_decision': 'direct',
        'deterministic_decision': 'propose',
        'agreement_category': 'decision_disagreement',
    }
    assert deterministic == original


def test_streaming_route_orders_shadow_before_unchanged_deterministic_plan():
    route_source = (
        SINGLE_APP_ROOT / 'route_backend_chats.py'
    ).read_text(encoding='utf-8')
    stream_start = route_source.index('def generate(publish_background_event=None):')
    discovery_index = route_source.index(
        'capability_discovery = _build_server_capability_discovery(',
        stream_start,
    )
    control_index = route_source.index(
        "capability_recommendation = capability_discovery.get('recommendation')",
        discovery_index,
    )
    request_builder_index = route_source.index(
        'def build_active_capability_planner_request():',
        control_index,
    )
    request_index = route_source.index(
        'capability_planner_request = (\n'
        '                        build_active_capability_planner_request()',
        request_builder_index,
    )
    invoke_index = route_source.index(
        'capability_planner_result = invoke_capability_planner(',
        request_index,
    )
    compare_index = route_source.index(
        'compare_capability_planner_shadow(',
        invoke_index,
    )
    auto_index = route_source.index(
        "auto_capability_ids = list(capability_discovery.get('auto_capability_ids') or [])",
        compare_index,
    )
    plan_index = route_source.index(
        'turn_orchestration_plan = build_turn_orchestration_plan(',
        auto_index,
    )

    assert discovery_index < control_index < request_index < invoke_index
    assert invoke_index < compare_index < auto_index < plan_index
    assert 'capability_planner' not in route_source[auto_index:plan_index]
    assert 'and not capability_resume_context' in route_source[
        control_index:request_index
    ]
    assert "['selected_agent']" in route_source[
        request_builder_index:request_index
    ]


def test_shadow_metadata_is_user_turn_only_and_configured_model_is_server_owned():
    route_source = (
        SINGLE_APP_ROOT / 'route_backend_chats.py'
    ).read_text(encoding='utf-8')
    assert route_source.count("user_metadata['capability_planner_shadow']") == 1
    assert "'capability_planner_shadow':" not in route_source

    resolver_start = route_source.index(
        'def _resolve_chat_capability_planner_runtime('
    )
    resolver_end = route_source.index(
        'def _build_capability_planner_shadow_evaluation_events(',
        resolver_start,
    )
    resolver_source = route_source[resolver_start:resolver_end]
    assert "'chat_capability_planner_model_endpoint_id'" in resolver_source
    assert "planner_settings.get('chat_capability_planner_model_id')" in resolver_source
    assert 'data.get(' not in resolver_source


def test_configured_planner_ignores_colliding_user_endpoint(monkeypatch):
    route_backend_chats = importlib.import_module('route_backend_chats')
    diagnostic_messages = []

    def endpoint(scope, deployment):
        return {
            'id': 'shared-endpoint-id',
            '_endpoint_scope': scope,
            'enabled': True,
            'provider': 'aoai',
            'connection': {
                'endpoint': f'https://{scope}.example.test',
                'openai_api_version': '2025-01-01-preview',
            },
            'auth': {'type': 'api_key', 'api_key': f'{scope}-secret'},
            'models': [
                {
                    'id': 'planner-model-id',
                    'deploymentName': deployment,
                    'enabled': True,
                }
            ],
        }

    monkeypatch.setattr(
        route_backend_chats,
        'get_streaming_model_endpoint_candidates',
        lambda *args, **kwargs: [
            endpoint('user', 'user-controlled-deployment'),
            endpoint('global', 'admin-controlled-deployment'),
        ],
    )
    monkeypatch.setattr(
        route_backend_chats,
        'keyvault_model_endpoint_get_helper',
        lambda endpoint_config, *args, **kwargs: endpoint_config,
    )
    monkeypatch.setattr(
        route_backend_chats,
        'build_streaming_multi_endpoint_client',
        lambda auth, provider, endpoint_url, api_version, deployment_name='': {
            'endpoint': endpoint_url,
            'deployment': deployment_name,
        },
    )
    monkeypatch.setattr(
        route_backend_chats,
        'debug_print',
        diagnostic_messages.append,
    )

    resolved = route_backend_chats.resolve_streaming_multi_endpoint_gpt_config(
        {'enable_multi_model_endpoints': True},
        {
            'model_endpoint_id': 'shared-endpoint-id',
            'model_id': 'planner-model-id',
        },
        'current-user',
        required_endpoint_scope='global',
    )

    assert resolved[0] == {
        'endpoint': 'https://global.example.test',
        'deployment': 'admin-controlled-deployment',
    }
    assert resolved[1] == 'admin-controlled-deployment'
    assert resolved[6] == 'shared-endpoint-id'
    assert resolved[7] == 'planner-model-id'
    diagnostics = ' '.join(diagnostic_messages)
    for forbidden_value in (
        'shared-endpoint-id',
        'planner-model-id',
        'admin-controlled-deployment',
        'https://global.example.test',
        '2025-01-01-preview',
        'global-secret',
    ):
        assert forbidden_value not in diagnostics
    assert 'provider_class=aoai' in diagnostics
    assert 'protocol=azure_openai' in diagnostics


def test_planner_runtime_uses_exact_selected_chat_model_without_admin_selection():
    route_backend_chats = importlib.import_module('route_backend_chats')
    selected_chat_client = object()

    runtime = route_backend_chats._resolve_chat_capability_planner_runtime(
        settings={},
        planner_settings={
            'chat_capability_planner_mode': 'assist',
            'chat_capability_planner_model_source': 'same_as_chat',
            'chat_capability_planner_model_endpoint_id': '',
            'chat_capability_planner_model_id': '',
        },
        user_id='current-user',
        active_group_ids=[],
        same_chat_client=selected_chat_client,
        same_chat_model='gpt-5.6-luna',
        same_chat_provider='aoai',
        same_chat_endpoint='https://selected.example.test',
    )

    assert runtime['client'] is selected_chat_client
    assert runtime['model'] == 'gpt-5.6-luna'
    assert runtime['runtime_protocol'] == 'azure_openai'


def test_planner_runtime_treats_incomplete_configured_ids_as_selected_chat_model():
    route_backend_chats = importlib.import_module('route_backend_chats')
    selected_chat_client = object()

    runtime = route_backend_chats._resolve_chat_capability_planner_runtime(
        settings={},
        planner_settings={
            'chat_capability_planner_mode': 'assist',
            'chat_capability_planner_model_source': 'configured',
            'chat_capability_planner_model_endpoint_id': 'global-endpoint',
            'chat_capability_planner_model_id': '',
        },
        user_id='current-user',
        active_group_ids=[],
        same_chat_client=selected_chat_client,
        same_chat_model='gpt-5.6-luna',
        same_chat_provider='aoai',
        same_chat_endpoint='https://selected.example.test',
    )

    assert runtime['client'] is selected_chat_client
    assert runtime['model'] == 'gpt-5.6-luna'


def test_assist_discovery_builds_inventory_without_heuristic_classification(
    monkeypatch,
):
    route_backend_chats = importlib.import_module('route_backend_chats')
    inventory = _inventory()

    monkeypatch.setattr(
        route_backend_chats,
        '_resolve_server_chat_capability_inventory',
        lambda **kwargs: copy.deepcopy(inventory),
    )
    monkeypatch.setattr(
        route_backend_chats,
        '_attach_governed_agent_inventory',
        lambda current_inventory, **kwargs: current_inventory,
    )
    monkeypatch.setattr(
        route_backend_chats,
        'classify_capability_requirements',
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError('Assist must not run the built-in heuristic classifier.')
        ),
    )
    monkeypatch.setattr(
        route_backend_chats,
        'classify_agent_capability_requirements',
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError('Assist must not run the agent heuristic classifier.')
        ),
    )

    discovery = route_backend_chats._build_server_capability_discovery(
        settings={},
        user_id='current-user',
        user_email='user@example.test',
        user_roles=[],
        user_message='Find current public evidence.',
        selected_capability_ids=[],
        enable_deterministic_matching=False,
    )

    assert discovery == {
        'inventory': inventory,
        'requirements': [],
        'auto_capability_ids': [],
        'recommendation': None,
    }


def test_planner_cancellation_precedes_plan_and_persistence():
    route_source = (
        SINGLE_APP_ROOT / 'route_backend_chats.py'
    ).read_text(encoding='utf-8')
    invoke_index = route_source.index(
        'capability_planner_result = invoke_capability_planner('
    )
    cancel_index = route_source.index(
        'if stream_cancel_requested():',
        invoke_index,
    )
    auto_index = route_source.index(
        "auto_capability_ids = list(capability_discovery.get('auto_capability_ids') or [])",
        cancel_index,
    )
    persist_index = route_source.index(
        'persist_stream_user_message(user_metadata)',
        auto_index,
    )

    assert invoke_index < cancel_index < auto_index < persist_index
    assert '_build_stream_cancel_event(' in route_source[cancel_index:auto_index]
    assert 'message_persisted=False' in route_source[cancel_index:auto_index]


def test_clarification_claim_precedes_planner_and_completion_follows_persistence():
    route_source = (
        SINGLE_APP_ROOT / 'route_backend_chats.py'
    ).read_text(encoding='utf-8')
    generator_start = route_source.index(
        'def generate(publish_background_event=None):'
    )
    worker_clarification_preflight = route_source.index(
        '_preflight_chat_clarification(',
        generator_start,
    )
    context_assembly = route_source.index(
        'load_bounded_prior_user_turns(',
        worker_clarification_preflight,
    )
    clarification_transition = route_source.index(
        ') = persist_chat_clarification_response_claim(',
        generator_start,
    )
    planner_invocation = route_source.index(
        'capability_planner_result = invoke_capability_planner(',
        clarification_transition,
    )
    final_clarification_source_validation = route_source.rindex(
        'validate_chat_clarification_source(',
        clarification_transition,
        planner_invocation,
    )
    final_clarification_request_rebuild = route_source.rindex(
        'build_active_capability_planner_request()',
        clarification_transition,
        planner_invocation,
    )
    clarification_invalidation = route_source.index(
        '_invalidate_chat_clarification_checkpoint(',
        final_clarification_source_validation,
    )
    claimed_response_persistence = route_source.index(
        '_persist_claimed_clarification_response_metadata(',
        clarification_transition,
    )
    claimed_response_new_insert = route_source.index(
        'cosmos_messages_container.upsert_item(\n'
        '                            claimed_clarification_user_doc',
        claimed_response_persistence,
    )
    user_persistence = route_source.index(
        'persist_stream_user_message(user_metadata)',
        planner_invocation,
    )
    dispatcher_definition = route_source.index(
        'def persist_stream_user_message(metadata):',
        planner_invocation,
    )
    terminal_completion_helper = route_source.index(
        'def complete_stream_capability_resume(assistant_message_id):',
        generator_start,
    )
    clarification_completion = route_source.index(
        ') = persist_chat_clarification_response_completion(',
        terminal_completion_helper,
    )
    first_terminal_output = route_source.index(
        'complete_stream_capability_resume(assistant_message_id)',
        planner_invocation,
    )

    assert (
        terminal_completion_helper
        < worker_clarification_preflight
        < context_assembly
        < clarification_transition
        < claimed_response_persistence
        < claimed_response_new_insert
        < final_clarification_source_validation
        < final_clarification_request_rebuild
        < planner_invocation
        < dispatcher_definition
        < user_persistence
        < first_terminal_output
    )
    generator_end = route_source.index(
        "@bp.route('/api/chat/stream/cancel/",
        dispatcher_definition,
    )
    assert 'upsert_item(user_message_doc)' not in route_source[
        dispatcher_definition:generator_end
    ]
    assert 'upsert_item(active_user_message_doc)' not in route_source[
        dispatcher_definition:generator_end
    ]
    worker_preflight_source = route_source[
        worker_clarification_preflight:context_assembly
    ]
    assert 'expected_clarification_id=(' in worker_preflight_source
    targeted_worker_context = route_source.index(
        "targeted_clarification = (",
        worker_clarification_preflight,
    )
    targeted_replay = route_source.index(
        "targeted_clarification.get('status')\n"
        "                            == 'resolved'",
        targeted_worker_context,
    )
    targeted_source = route_source.index(
        'targeted_source = validate_chat_clarification_source(',
        targeted_replay,
    )
    targeted_recovery = route_source.index(
        'pending_chat_clarification = targeted_clarification',
        targeted_source,
    )
    bounded_history_reload = route_source.index(
        'load_bounded_prior_user_turns(',
        targeted_recovery,
    )
    assert (
        worker_clarification_preflight
        < targeted_worker_context
        < targeted_replay
        < targeted_source
        < targeted_recovery
        < bounded_history_reload
    )
    targeted_context_source = route_source[
        targeted_source:bounded_history_reload
    ]
    assert "'prior_user_messages': [" in targeted_context_source
    assert 'targeted_source,' in targeted_context_source
    assert 'targeted_response,' in targeted_context_source
    expected_checkpoint_read = route_source.index(
        ') = read_chat_clarification_message(',
        context_assembly,
    )
    assert expected_checkpoint_read < clarification_transition
    assert route_source.count(
        'persist_chat_clarification_response_claim('
    ) == 1
    assert clarification_invalidation < planner_invocation
    claimed_response_read = route_source.index(
        'claimed_clarification_user_doc = (',
        clarification_transition,
    )
    claimed_response_validation = route_source.index(
        '_claimed_clarification_response_is_valid(',
        claimed_response_read,
    )
    claimed_response_invalidation = route_source.index(
        '_invalidate_chat_clarification_checkpoint(',
        claimed_response_validation,
    )
    assert (
        claimed_response_read
        < claimed_response_validation
        < claimed_response_invalidation
        < planner_invocation
    )
    assert route_source.count(
        'persist_chat_clarification_response_completion('
    ) == 4
    cleanup_helper = route_source.index(
        'def _finalize_stream_clarification_claim('
    )
    cleanup_completion = route_source.index(
        'persist_chat_clarification_response_completion(',
        cleanup_helper,
    )
    cleanup_invalidation = route_source.index(
        'persist_chat_clarification_invalidation(',
        cleanup_completion,
    )
    assert cleanup_helper < cleanup_completion < cleanup_invalidation
    reconciliation_completion = route_source.index(
        ') = persist_chat_clarification_response_completion(',
        clarification_completion + 1,
    )
    assert clarification_completion < reconciliation_completion < clarification_transition
    assert "'clarification_replayed': True" in route_source[
        reconciliation_completion:clarification_transition
    ]
    legacy_start = route_source.index(
        'def chat_api(server_request_data=None, server_resume_context=None):'
    )
    stream_route_start = route_source.index(
        "@bp.route('/api/chat/stream'",
        legacy_start,
    )
    assert 'resolved_chat_clarification' not in route_source[
        legacy_start:stream_route_start
    ]
    streaming_pointer = route_source.index(
        "'_clarification_id': (",
        planner_invocation,
    )
    assert streaming_pointer < user_persistence
    document_action_start = route_source.index(
        'def execute_document_action_chat_request('
    )
    first_contextual_action_revalidation = route_source.index(
        '_rebuild_claimed_contextual_goal(',
        document_action_start,
    )
    agent_resolution = route_source.index(
        '_resolve_canonical_chat_agent(',
        document_action_start,
    )
    task_document_resolution = route_source.index(
        '_resolve_conversation_task_documents(',
        document_action_start,
    )
    second_contextual_action_revalidation = route_source.index(
        '_rebuild_claimed_contextual_goal(',
        first_contextual_action_revalidation + 1,
    )
    selected_document_resolution = route_source.index(
        '_resolve_authorized_chat_selected_documents(',
        document_action_start,
    )
    third_contextual_action_revalidation = route_source.index(
        '_rebuild_claimed_contextual_goal(',
        second_contextual_action_revalidation + 1,
    )
    assigned_knowledge_retrieval = route_source.index(
        '_build_assigned_knowledge_reference_context(',
        document_action_start,
    )
    fourth_contextual_action_revalidation = route_source.index(
        '_rebuild_claimed_contextual_goal(',
        third_contextual_action_revalidation + 1,
    )
    workflow_prompt_build = route_source.index(
        '_build_document_action_prompt_with_assigned_knowledge_context(',
        document_action_start,
    )
    fifth_contextual_action_revalidation = route_source.index(
        '_rebuild_claimed_contextual_goal(',
        fourth_contextual_action_revalidation + 1,
    )
    workflow_execution = route_source.index(
        '_execute_document_action_workflow(',
        document_action_start,
    )
    assert (
        first_contextual_action_revalidation
        < agent_resolution
        < task_document_resolution
        < second_contextual_action_revalidation
        < selected_document_resolution
        < third_contextual_action_revalidation
        < assigned_knowledge_retrieval
        < fourth_contextual_action_revalidation
        < workflow_prompt_build
        < fifth_contextual_action_revalidation
        < workflow_execution
    )
    compatibility_preflight = route_source.index(
        '_preflight_chat_clarification(',
        route_source.index("@bp.route('/api/chat/stream'"),
    )
    compatibility_bridge = route_source.index(
        'if compatibility_mode:',
        compatibility_preflight,
    )
    assert compatibility_preflight < compatibility_bridge
    assert 'clarification_response_retry' in route_source[
        compatibility_preflight:compatibility_bridge
    ]
    assert 'clarification_response_idempotent' in route_source[
        clarification_transition:planner_invocation
    ]
    assert "'clarification_replayed': True" in route_source[
        clarification_transition:planner_invocation
    ]
    worker_context_revalidation = route_source.index(
        '_rebuild_authorized_contextual_goal(',
        generator_start,
    )
    model_initialization = route_source.index(
        'initialize_semantic_kernel(',
        worker_context_revalidation,
    )
    agent_resolution = route_source.index(
        '_resolve_canonical_chat_agent(',
        worker_context_revalidation,
    )
    final_context_revalidation = route_source.index(
        '_rebuild_exact_contextual_goal(',
        worker_context_revalidation,
    )
    assert worker_context_revalidation < model_initialization
    assert worker_context_revalidation < agent_resolution
    assert worker_context_revalidation < final_context_revalidation
    normal_assistant_metadata = route_source.index(
        "'agent_runtime': agent_runtime_metadata or None",
        planner_invocation,
    )
    normal_assistant_persistence = route_source.index(
        'cosmos_messages_container.upsert_item(assistant_doc)',
        normal_assistant_metadata,
    )
    final_response_metadata_persistence = route_source.index(
        'persist_stream_user_message(',
        normal_assistant_persistence,
    )
    normal_terminal_completion = route_source.index(
        'complete_stream_capability_resume(assistant_message_id)',
        normal_assistant_persistence,
    )
    capability_resume_logging_guard = route_source.index(
        'if capability_resume_context and resume_terminalized:',
        normal_terminal_completion,
    )
    assert (
        normal_assistant_persistence
        < final_response_metadata_persistence
        < normal_terminal_completion
        < capability_resume_logging_guard
    )
    assert 'except ChatClarificationError:\n                        raise' in (
        route_source[
            final_response_metadata_persistence:normal_terminal_completion
        ]
    )
