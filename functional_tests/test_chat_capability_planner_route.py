# test_chat_capability_planner_route.py
"""
Functional test for chat capability planner route placement and isolation.
Version: 0.250.069
Implemented in: 0.250.069

This test ensures shadow planning runs only on eligible new turns after safe
discovery and cannot alter deterministic recommendation or execution state.
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
    request_index = route_source.index(
        'capability_planner_request = build_capability_planner_request(',
        control_index,
    )
    invoke_index = route_source.index(
        'capability_planner_shadow_result = invoke_capability_planner(',
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
    assert "['selected_agent']" in route_source[request_index:invoke_index]


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


def test_planner_cancellation_precedes_plan_and_persistence():
    route_source = (
        SINGLE_APP_ROOT / 'route_backend_chats.py'
    ).read_text(encoding='utf-8')
    invoke_index = route_source.index(
        'capability_planner_shadow_result = invoke_capability_planner('
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
        'cosmos_messages_container.upsert_item(user_message_doc)',
        auto_index,
    )

    assert invoke_index < cancel_index < auto_index < persist_index
    assert '_build_stream_cancel_event(' in route_source[cancel_index:auto_index]
    assert 'message_persisted=False' in route_source[cancel_index:auto_index]
