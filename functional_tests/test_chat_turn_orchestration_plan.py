#!/usr/bin/env python3
# test_chat_turn_orchestration_plan.py
"""
Functional test for the chat turn orchestration planning foundation.
Version: 0.250.067
Implemented in: 0.250.058

This test ensures every turn receives a direct or coordinated plan, selected
capabilities are required attempts, and grounded image generation remains a
task profile rather than the core orchestration abstraction.
"""

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
ROUTE_BACKEND_CHATS = SINGLE_APP_ROOT / 'route_backend_chats.py'
CONFIG_FILE = SINGLE_APP_ROOT / 'config.py'
sys.path.insert(0, str(SINGLE_APP_ROOT))

from functions_chat_orchestration import (  # noqa: E402
    ORCHESTRATION_GUIDANCE_MARKER,
    build_turn_orchestration_guidance_message,
    build_turn_orchestration_plan,
)


def test_simple_request_uses_direct_plan():
    plan = build_turn_orchestration_plan(
        'Explain recursion with a short example.',
        run_id='run-direct',
        image_generation_available=True,
    )

    assert plan['mode'] == 'direct'
    assert plan['task_profile'] == 'direct_answer'
    assert plan['requires_evidence_before_finalization'] is False
    assert plan['requested_evidence_sources'] == []
    assert plan['steps'] == [{
        'id': 'finalize_response',
        'type': 'finalize',
        'capability': 'response',
        'origin': 'orchestrator',
        'required': True,
        'status': 'pending',
        'depends_on': [],
    }]
    assert build_turn_orchestration_guidance_message(plan) == ''


def test_selected_capabilities_are_required_attempts():
    plan = build_turn_orchestration_plan(
        'Compare the evidence and summarize it.',
        run_id='run-selected',
        conversation_id='conversation-1',
        selected_agent={'id': 'agent-1', 'name': 'Research Agent'},
        selected_action={'type': 'comparison'},
        selected_document_ids=['doc-1', 'doc-2'],
        document_scope='group',
        active_group_ids=['group-1'],
        tags=['roadmap'],
        web_search_enabled=True,
        model_deployment='gpt-4.1',
        model_id='model-1',
        model_endpoint_id='endpoint-1',
        model_provider='azure_openai',
        reasoning_effort='medium',
        prompt_info={'id': 'prompt-1', 'content': 'must not be persisted in the plan'},
    )

    assert plan['mode'] == 'coordinated'
    assert plan['task_profile'] == 'grounded_answer'
    assert plan['selected_capabilities'] == [
        'selected_agent',
        'selected_action',
        'selected_documents',
        'web_search',
    ]
    assert all(source['required'] for source in plan['sources'])
    assert all(source['origin'] == 'selection' for source in plan['sources'])
    assert plan['steps'][-1]['depends_on'] == [
        'collect_selected_agent',
        'execute_selected_action',
        'collect_selected_documents',
        'collect_web_search',
    ]
    selected_action_step = next(
        step for step in plan['steps'] if step['id'] == 'execute_selected_action'
    )
    assert selected_action_step['depends_on'] == [
        'collect_selected_agent',
        'collect_selected_documents',
    ]
    assert plan['policy']['central_finalizer_required'] is True
    assert plan['selection_snapshot'] == {
        'conversation_id': 'conversation-1',
        'agent_id': 'agent-1',
        'action_type': 'comparison',
        'selected_document_ids': ['doc-1', 'doc-2'],
        'document_scope': 'group',
        'active_group_ids': ['group-1'],
        'active_public_workspace_ids': [],
        'tags': ['roadmap'],
        'conversation_document_ids': [],
        'toggles': {
            'workspace_search': False,
            'web_search': True,
            'url_access': False,
            'source_review': False,
            'deep_research': False,
            'user_workspace_context': False,
        },
        'selected_image_reference_count': 0,
        'model': {
            'deployment': 'gpt-4.1',
            'model_id': 'model-1',
            'endpoint_id': 'endpoint-1',
            'provider': 'azure_openai',
            'reasoning_effort': 'medium',
        },
        'prompt_id': 'prompt-1',
    }
    assert 'must not be persisted' not in json.dumps(plan)

    guidance = build_turn_orchestration_guidance_message(plan)
    assert 'Do not add a source-status note or list sources merely to report successful attempts.' in guidance
    assert 'Only mention source execution status when a required source was skipped' in guidance
    assert 'or produced partial results.' in guidance


def test_grounded_image_is_a_coordinated_task_profile():
    plan = build_turn_orchestration_plan(
        'Create a whiteboard sketch of my work life grounded in M365 and my public LinkedIn profile.',
        run_id='run-grounded-image',
        selected_image_reference_count=1,
        image_generation_available=True,
    )

    assert plan['task_type'] == 'image_generation'
    assert plan['task_profile'] == 'grounded_image_generation'
    assert plan['image_generation_requested'] is True
    assert plan['grounded_image_generation_requested'] is True
    assert plan['requires_evidence_before_finalization'] is True
    assert plan['requested_evidence_sources'] == [
        'selected_images',
        'enterprise_data',
        'public_web',
    ]
    assert plan['finalizer'] == 'image_proposal'

    guidance = build_turn_orchestration_guidance_message(plan)
    assert ORCHESTRATION_GUIDANCE_MARKER in guidance
    assert 'Do not emit a simpleimage proposal until' in guidance
    assert 'selected_images, enterprise_data, public_web' in guidance


def test_generic_image_request_does_not_require_evidence():
    prompts = [
        'Create a cat picture in a watercolor style.',
        'Draw a landscape.',
        'Generate a logo from this text.',
        'Create a logo based on my description.',
    ]

    for index, prompt in enumerate(prompts):
        plan = build_turn_orchestration_plan(
            prompt,
            run_id=f'run-simple-image-{index}',
            image_generation_available=True,
        )

        assert plan['mode'] == 'direct'
        assert plan['task_profile'] == 'image_generation'
        assert plan['grounded_image_generation_requested'] is False
        assert plan['requested_evidence_sources'] == []
        assert plan['finalizer'] == 'image_proposal'


def test_selected_image_question_is_not_generation():
    plan = build_turn_orchestration_plan(
        'What is this image about?',
        run_id='run-image-question',
        selected_image_reference_count=1,
        image_generation_available=True,
    )

    assert plan['task_type'] == 'answer'
    assert plan['task_profile'] == 'grounded_answer'
    assert plan['image_generation_requested'] is False
    assert plan['grounded_image_generation_requested'] is False
    assert plan['requested_evidence_sources'] == ['selected_images']


def test_grounding_in_prior_messages_uses_conversation_evidence():
    plan = build_turn_orchestration_plan(
        'Create an infographic and ground it in the information above.',
        run_id='run-prior-grounding',
        prior_citation_count=2,
        image_generation_available=True,
    )

    assert plan['mode'] == 'coordinated'
    assert plan['task_profile'] == 'grounded_image_generation'
    assert plan['evidence_requirements'] == ['conversation_evidence']
    assert plan['requested_evidence_sources'] == ['conversation_evidence']
    assert plan['sources'][0]['metadata']['available_citation_count'] == 2


def test_unspecified_grounding_requires_evidence_discovery():
    plan = build_turn_orchestration_plan(
        'Create an image grounded in verified facts.',
        run_id='run-unspecified-grounding',
        image_generation_available=True,
    )

    assert plan['mode'] == 'coordinated'
    assert plan['task_profile'] == 'grounded_image_generation'
    assert plan['evidence_requirements'] == ['unspecified_grounding']
    assert plan['requested_evidence_sources'] == ['evidence_discovery']
    assert plan['steps'][0] == {
        'id': 'plan_evidence_discovery',
        'type': 'plan',
        'capability': 'evidence_discovery',
        'origin': 'request',
        'required': True,
        'status': 'pending',
        'depends_on': [],
    }
    assert plan['steps'][-1]['depends_on'] == ['plan_evidence_discovery']


def test_non_image_enterprise_request_is_still_coordinated():
    prompts = [
        ('Use my Microsoft 365 calendar to summarize my priorities this week.', 'enterprise_data'),
        ('Draw insights from the SQL data.', 'structured_data'),
        ('Draw a chart from the SQL data.', 'structured_data'),
    ]

    for index, (prompt, expected_source) in enumerate(prompts):
        plan = build_turn_orchestration_plan(
            prompt,
            run_id=f'run-enterprise-answer-{index}',
            image_generation_available=True,
        )

        assert plan['mode'] == 'coordinated'
        assert plan['task_type'] == 'answer'
        assert plan['task_profile'] == 'grounded_answer'
        assert plan['requested_evidence_sources'] == [expected_source]
        assert plan['finalizer'] == 'response'


def test_connector_detection_is_source_neutral():
    scenarios = [
        ('Create an infographic using customer churn from SQL.', 'structured_data'),
        ('Create a diagram based on our Salesforce pipeline.', 'business_system'),
        ('Create a team visual using Graph.', 'enterprise_data'),
        ('Create a profile image using my LinkedIn public profile.', 'public_web'),
    ]

    for index, (prompt, expected_source) in enumerate(scenarios):
        plan = build_turn_orchestration_plan(
            prompt,
            run_id=f'run-connector-{index}',
            image_generation_available=True,
        )

        assert plan['task_profile'] == 'grounded_image_generation'
        assert expected_source in plan['requested_evidence_sources']


def test_selected_sources_cover_equivalent_evidence_requirements():
    web_plan = build_turn_orchestration_plan(
        'Create a profile visual using my LinkedIn public profile.',
        run_id='run-web-alias',
        web_search_enabled=True,
        image_generation_available=True,
    )
    assert web_plan['requested_evidence_sources'] == ['web_search']
    assert web_plan['evidence_requirements'] == ['public_web']
    assert [step['id'] for step in web_plan['steps']] == [
        'collect_web_search',
        'finalize_image_proposal',
    ]

    workspace_plan = build_turn_orchestration_plan(
        'Summarize the selected documents.',
        run_id='run-workspace-alias',
        selected_document_ids=['doc-1'],
    )
    assert workspace_plan['requested_evidence_sources'] == ['selected_documents']
    assert workspace_plan['evidence_requirements'] == ['workspace_search']


def test_string_zero_image_count_does_not_create_selected_image_source():
    plan = build_turn_orchestration_plan(
        'What happened?',
        run_id='run-zero-image-count',
        selected_image_reference_count='0',
    )

    assert plan['mode'] == 'direct'
    assert plan['selection_snapshot']['selected_image_reference_count'] == 0
    assert 'selected_images' not in plan['requested_evidence_sources']


def test_plan_is_json_serializable():
    plan = build_turn_orchestration_plan(
        'Use the previous citations and selected documents to draft a brief.',
        run_id='run-json',
        selected_document_ids=['doc-1'],
        prior_citation_count=3,
    )

    serialized = json.dumps(plan)
    assert 'conversation_evidence' in serialized
    conversation_source = next(
        source for source in plan['sources'] if source['id'] == 'conversation_evidence'
    )
    assert conversation_source['metadata']['available_citation_count'] == 3


def test_context_sources_are_distinct_from_user_selections():
    plan = build_turn_orchestration_plan(
        'Draft the response from the available context.',
        run_id='run-context',
        selected_agent={'id': 'agent-1'},
        conversation_document_ids=['upload-1'],
        assigned_knowledge_enabled=True,
    )

    assert plan['selected_capabilities'] == ['selected_agent']
    source_origins = {source['id']: source['origin'] for source in plan['sources']}
    assert source_origins == {
        'selected_agent': 'selection',
        'conversation_documents': 'conversation',
        'assigned_knowledge': 'agent_configuration',
    }


def test_discovered_capabilities_preserve_original_selection_provenance():
    original_selection = {
        'conversation_id': 'conversation-1',
        'toggles': {
            'workspace_search': False,
            'web_search': False,
            'url_access': False,
            'source_review': False,
            'deep_research': False,
        },
    }
    plan = build_turn_orchestration_plan(
        'What are the current county rules?',
        run_id='child-run',
        parent_run_id='parent-run',
        conversation_id='conversation-1',
        web_search_enabled=True,
        deep_research_enabled=True,
        capability_origins={
            'web_search': 'discovery_approved',
            'deep_research': 'discovery_approved',
        },
        selection_snapshot_override=original_selection,
    )

    assert plan['selection_snapshot'] == original_selection
    assert plan['selected_capabilities'] == []
    assert plan['effective_capabilities'] == ['web_search', 'deep_research']
    assert {source['origin'] for source in plan['sources']} == {'discovery_approved'}
    assert all(source['required'] for source in plan['sources'])
    assert plan['parent_run_id'] == 'parent-run'
    assert 'approved_capability_discovery' in plan['reason_codes']

    compare_plan = build_turn_orchestration_plan(
        'Compare the selected documents.',
        run_id='compare-child-run',
        selected_action={'type': 'comparison'},
        selected_document_ids=['doc-1', 'doc-2'],
        capability_origins={'compare': 'discovery_approved'},
        selection_snapshot_override=original_selection,
    )
    selected_action_source = next(
        source
        for source in compare_plan['sources']
        if source['id'] == 'selected_action'
    )
    assert selected_action_source['origin'] == 'discovery_approved'
    assert selected_action_source['required'] is True

    image_plan = build_turn_orchestration_plan(
        'Create an infographic about recursion.',
        run_id='image-child-run',
        image_generation_available=True,
        capability_origins={'image': 'discovery_approved'},
        selection_snapshot_override=original_selection,
    )
    assert image_plan['finalizer'] == 'image_proposal'
    assert image_plan['steps'][-1]['origin'] == 'discovery_approved'
    assert image_plan['steps'][-1]['required'] is True
    assert image_plan['effective_capabilities'] == ['image']
    assert image_plan['selected_capabilities'] == []


def test_attached_headshot_is_detected_as_requested_image_evidence():
    plan = build_turn_orchestration_plan(
        'Create a sketch of my role using the attached headshot as a reference.',
        run_id='run-headshot',
        image_generation_available=True,
    )

    assert plan['task_profile'] == 'grounded_image_generation'
    assert plan['requested_evidence_sources'] == ['enterprise_data', 'selected_images']


def test_streaming_chat_path_persists_and_applies_plan():
    route_source = ROUTE_BACKEND_CHATS.read_text(encoding='utf-8')
    config_source = CONFIG_FILE.read_text(encoding='utf-8')

    assert 'VERSION = "0.250.067"' in config_source
    assert 'turn_orchestration_plan = build_turn_orchestration_plan(' in route_source
    assert 'requested_action_document_ids = _normalize_conversation_task_document_ids(' in route_source
    assert 'requested_action_document_ids\n            if requested_action_document_ids' in route_source
    assert 'requested_document_scope = document_scope' in route_source
    assert "'document_scope': requested_document_scope," in route_source
    assert "'active_group_ids': requested_active_group_ids," in route_source
    assert "'active_public_workspace_ids': requested_active_public_workspace_ids," in route_source
    assert "'tags': requested_tags_filter," in route_source
    assert route_source.count("user_metadata['orchestration'] = turn_orchestration_plan") >= 2
    assert "'orchestration': turn_orchestration_plan," in route_source
    assert 'conversation_history_for_api = maybe_append_turn_orchestration_system_message(' in route_source
    assert "'[Orchestration] Document action turn plan created'" in route_source
    assert "partial_error_payload = {" in route_source
    assert 'capability_discovery = _build_server_capability_discovery(' in route_source
    assert "turn_orchestration_run.status = 'awaiting_user_choice'" in route_source
    assert "'capability_proposal': proposal," in route_source
    assert "@bp.route('/api/chat/capability-proposals/<proposal_id>/decision'" in route_source
    assert '_claim_authorized_capability_resume(' in route_source
    assert 'persist_capability_resume_completion(' in route_source
    assert "data.get('_server_external_query') or user_message" in route_source
    assert 'compatibility_capability_inventory = _resolve_server_chat_capability_inventory(' in route_source
    assert "user_metadata['capability_provenance'] = compatibility_capability_provenance" in route_source
    assert "'capability_provenance': compatibility_capability_provenance," in route_source


if __name__ == '__main__':
    tests = [
        test_simple_request_uses_direct_plan,
        test_selected_capabilities_are_required_attempts,
        test_grounded_image_is_a_coordinated_task_profile,
        test_generic_image_request_does_not_require_evidence,
        test_selected_image_question_is_not_generation,
        test_grounding_in_prior_messages_uses_conversation_evidence,
        test_unspecified_grounding_requires_evidence_discovery,
        test_non_image_enterprise_request_is_still_coordinated,
        test_connector_detection_is_source_neutral,
        test_selected_sources_cover_equivalent_evidence_requirements,
        test_string_zero_image_count_does_not_create_selected_image_source,
        test_plan_is_json_serializable,
        test_context_sources_are_distinct_from_user_selections,
        test_discovered_capabilities_preserve_original_selection_provenance,
        test_attached_headshot_is_detected_as_requested_image_evidence,
        test_streaming_chat_path_persists_and_applies_plan,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            print('Passed')
            results.append(True)
        except Exception as exc:
            print(f'Failed: {exc}')
            results.append(False)

    passed = sum(results)
    total = len(results)
    print(f'\nResults: {passed}/{total} tests passed')
    sys.exit(0 if all(results) else 1)