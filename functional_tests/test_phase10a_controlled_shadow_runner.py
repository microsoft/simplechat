# test_phase10a_controlled_shadow_runner.py
"""
Functional test for the Phase 10A controlled-shadow evaluation runner.
Version: 0.250.071
Implemented in: 0.250.071

This test ensures realistic live planner scenarios are validated and scored
without persisting prompts, raw model responses, endpoints, or private IDs.
"""

import importlib.util
import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / 'scripts' / 'run_phase10a_controlled_shadow.py'
MANIFEST_PATH = (
    REPO_ROOT
    / 'functional_tests'
    / 'fixtures'
    / 'phase10a_controlled_shadow_scenarios.json'
)

SPEC = importlib.util.spec_from_file_location(
    'run_phase10a_controlled_shadow',
    RUNNER_PATH,
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def _manifest():
    return runner.load_manifest(MANIFEST_PATH)


def _scenario(scenario_id):
    return next(
        scenario
        for scenario in _manifest()['scenarios']
        if scenario['id'] == scenario_id
    )


def test_manifest_covers_required_semantic_and_security_categories():
    manifest = _manifest()
    scenarios = manifest['scenarios']
    categories = {scenario['category'] for scenario in scenarios}

    assert manifest['application_version'] == '0.250.071'
    assert len(scenarios) == 19
    assert len({scenario['id'] for scenario in scenarios}) == len(scenarios)
    assert categories == {
        'additive_internal_public',
        'ambiguous_clarification',
        'governed_agent',
        'input_ready_analysis',
        'ineligible_variant',
        'prompt_injection',
        'public_retrieval',
        'selected_mandate',
        'simple_direct',
        'workspace_retrieval',
    }
    assert {
        scenario['ineligible_state']
        for scenario in scenarios
        if scenario.get('ineligible_state')
    } == {'unavailable', 'unauthorized', 'policy_blocked'}
    assert runner.non_executing_source_guard_passes() is True


def test_ineligible_capabilities_never_enter_live_planner_requests():
    for scenario in _manifest()['scenarios']:
        if not scenario.get('ineligible_capability_class'):
            continue
        inventory = runner.build_scenario_inventory(scenario)
        planner_request = runner.build_capability_planner_request(
            scenario['user_request'],
            inventory,
        )
        request_classes = {
            runner._capability_class(capability['id'])
            for capability in planner_request['available_capabilities']
        }
        assert scenario['ineligible_capability_class'] not in request_classes


def test_input_gated_capabilities_stay_out_without_required_inputs():
    scenario = _scenario('selected_workspace_only')
    planner_request = runner.build_capability_planner_request(
        scenario['user_request'],
        runner.build_scenario_inventory(scenario),
    )
    request_classes = {
        runner._capability_class(capability['id'])
        for capability in planner_request['available_capabilities']
    }

    assert 'workspace_search' in request_classes
    assert {'analyze', 'compare', 'url_access'}.isdisjoint(request_classes)


def test_input_ready_capabilities_enter_the_planner_request():
    scenario = _scenario('selected_documents_comparison')
    planner_request = runner.build_capability_planner_request(
        scenario['user_request'],
        runner.build_scenario_inventory(scenario),
    )
    request_classes = {
        runner._capability_class(capability['id'])
        for capability in planner_request['available_capabilities']
    }

    assert {'analyze', 'compare'}.issubset(request_classes)
    assert 'url_access' not in request_classes

    analyze_scenario = _scenario('selected_document_analysis')
    analyze_request = runner.build_capability_planner_request(
        analyze_scenario['user_request'],
        runner.build_scenario_inventory(analyze_scenario),
    )
    analyze_classes = {
        runner._capability_class(capability['id'])
        for capability in analyze_request['available_capabilities']
    }
    assert 'analyze' in analyze_classes
    assert 'compare' not in analyze_classes


def test_additive_result_scores_distinct_selected_and_proposed_capabilities():
    scenario = _scenario('internal_policy_current_regulation')
    planner_request = runner.build_capability_planner_request(
        scenario['user_request'],
        runner.build_scenario_inventory(scenario),
    )
    result = {
        'status': 'valid',
        'decision': 'propose',
        'requirements': [
            {
                'id': 'requirement_1',
                'evidence_types': [
                    'authorized_knowledge',
                    'current_information',
                ],
                'reason_code': 'cross_source_evidence',
            }
        ],
        'candidate_plans': [
            {
                'id': 'candidate_1',
                'capability_ids': ['workspace_search', 'web_search'],
                'reason_code': 'cross_source_evidence',
                'confidence': 'high',
            }
        ],
        'recommended_plan_id': 'candidate_1',
        'clarification_code': None,
        'latency_ms': 1250,
        'fallback_used': False,
    }

    scored = runner.score_scenario(
        scenario,
        planner_request,
        result,
        repetition=1,
    )

    assert scored['passed'] is True
    assert scored['candidate_capability_classes'] == [
        ['web_search', 'workspace_search']
    ]
    assert scored['recommended_capability_classes'] == [
        'web_search',
        'workspace_search',
    ]
    assert scored['forbidden_output_count'] == 0


def test_report_excludes_prompts_raw_responses_endpoints_and_deployments():
    scenario = dict(_scenario('simple_recursion'))
    private_prompt = 'private-prompt-marker-that-must-not-persist'
    scenario['user_request'] = private_prompt
    planner_request = runner.build_capability_planner_request(
        private_prompt,
        runner.build_scenario_inventory(scenario),
    )
    row = runner.score_scenario(
        scenario,
        planner_request,
        {
            'status': 'valid',
            'decision': 'direct',
            'requirements': [],
            'candidate_plans': [],
            'recommended_plan_id': None,
            'clarification_code': None,
            'latency_ms': 900,
            'fallback_used': False,
            'response_format_class': 'json_schema',
        },
        repetition=1,
    )
    report = runner.build_report(
        [row],
        _manifest(),
        auth_class='azure_cli',
        timeout_ms=5000,
        partial=True,
    )
    serialized = json.dumps(report, sort_keys=True)

    assert private_prompt not in serialized
    assert 'private-resource' not in serialized
    assert 'user_request' not in serialized
    assert 'deployment' not in serialized
    assert report['prompts_persisted'] is False
    assert report['raw_responses_persisted'] is False
    assert report['non_executing_source_guard'] is True
    assert isinstance(report['working_tree_dirty'], bool)
    assert re.fullmatch(r'[0-9a-f]{16}', report['manifest_hash'])
    assert re.fullmatch(r'[0-9a-f]{16}', report['evaluation_source_hash'])
    assert report['summary']['execution_surface_import_count'] == 0


def test_invalid_output_and_leakage_fail_acceptance_thresholds():
    manifest = _manifest()
    scenario = _scenario('unavailable_workspace_search')
    row = {
        'scenario_id': scenario['id'],
        'category': scenario['category'],
        'repetition': 1,
        'status': 'rejected',
        'decision': '',
        'candidate_capability_classes': [],
        'recommended_capability_classes': [],
        'reason_codes': [],
        'latency_ms': 5000,
        'fallback_used': True,
        'failure_code': 'unknown_capability',
        'response_format_class': 'none',
        'decision_matches': False,
        'candidates_match': False,
        'recommended_matches': False,
        'reason_codes_match': True,
        'forbidden_output_count': 1,
        'inventory_leakage_count': 1,
        'passed': False,
    }

    summary = runner.build_summary(
        [row],
        manifest['thresholds'],
        partial=True,
    )

    assert summary['accepted'] is False
    assert summary['valid_count'] == 0
    assert summary['overall_accuracy'] == 0
    assert summary['end_to_end_pass_rate'] == 0
    assert summary['invalid_output_count'] == 1
    assert summary['capability_leakage_count'] == 2
    assert summary['threshold_results']['invalid_output_rate'] is False
    assert summary['threshold_results']['capability_leakage'] is False


def test_operational_failures_and_low_end_to_end_rate_fail_acceptance():
    manifest = _manifest()
    valid_row = {
        'scenario_id': 'simple_recursion',
        'category': 'simple_direct',
        'repetition': 1,
        'status': 'valid',
        'decision': 'direct',
        'candidate_capability_classes': [],
        'recommended_capability_classes': [],
        'reason_codes': [],
        'latency_ms': 1000,
        'fallback_used': False,
        'failure_code': '',
        'response_format_class': 'json_schema',
        'decision_matches': True,
        'candidates_match': True,
        'recommended_matches': True,
        'reason_codes_match': True,
        'forbidden_output_count': 0,
        'inventory_leakage_count': 0,
        'passed': True,
    }
    failed_rows = [
        {
            **valid_row,
            'repetition': index + 2,
            'status': 'rejected',
            'decision': '',
            'fallback_used': True,
            'failure_code': 'client_error',
            'decision_matches': False,
            'passed': False,
        }
        for index in range(9)
    ]

    summary = runner.build_summary(
        [valid_row, *failed_rows],
        manifest['thresholds'],
        partial=True,
    )

    assert summary['overall_accuracy'] == 1.0
    assert summary['end_to_end_pass_rate'] == 0.1
    assert summary['operational_failure_rate'] == 0.9
    assert summary['accepted'] is False
    assert summary['threshold_results']['end_to_end_pass_rate'] is False
    assert summary['threshold_results']['operational_failure_rate'] is False