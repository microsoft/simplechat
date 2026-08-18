#!/usr/bin/env python3
# test_workflow_alert_model_evaluation.py
"""
Functional test for model evaluated workflow alert conditions.
Version: 0.250.213
Implemented in: 0.250.213

This test ensures plain-English alert conditions are judged in a single batched
model call, that the call is skipped entirely when a deterministic rule already
matched at a higher severity, and that a malformed or failed evaluation honors
the configured on_error behavior instead of silently misfiring.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_support.versioning import assert_app_version_at_least

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'application' / 'single_app'))

from functions_workflow_alerts import (  # noqa: E402
    WORKFLOW_ALERT_EVALUATION_TEXT_LIMIT,
    build_model_evaluation_prompt,
    build_workflow_alert_facts,
    evaluate_workflow_alert_rules,
    normalize_alert_rules,
    parse_model_evaluation_response,
)


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def build_workflow(rules, evaluation=None):
    return {
        'id': 'workflow-1',
        'name': 'Certificate watch',
        'alert_mode': 'rules',
        'alert_rules': normalize_alert_rules(rules),
        'alert_evaluation': evaluation or {'on_error': 'skip'},
    }


def decide(workflow, run_record, execution_result=None, model_evaluator=None):
    facts = build_workflow_alert_facts(workflow, run_record, execution_result or {})
    return evaluate_workflow_alert_rules(workflow, facts, model_evaluator=model_evaluator)


class RecordingEvaluator:
    """Stand-in for the runner supplied model callable."""

    def __init__(self, response):
        self.response = response
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_model_condition_matches_and_reports_its_reason():
    """A matched plain-English condition alerts with the model's own explanation."""
    print("Testing model evaluated match...")
    workflow = build_workflow([
        {'id': 'm1', 'name': 'Expiring certificates', 'severity': 'high',
         'condition': {'type': 'model_evaluation', 'prompt': 'any certificate expires within 14 days'}},
    ])
    evaluator = RecordingEvaluator(
        '{"results": [{"rule_id": "m1", "matched": true, "reason": "Two certificates expire in 3 days."}]}'
    )

    decision = decide(
        workflow,
        {'status': 'completed', 'success': True},
        {'reply': 'cert A expires in 3 days, cert B expires in 3 days'},
        model_evaluator=evaluator,
    )

    assert decision['should_alert'] is True
    assert decision['severity'] == 'high'
    assert decision['reasons'] == ['Two certificates expire in 3 days.']
    assert decision['model_evaluation']['used'] is True
    assert len(evaluator.prompts) == 1
    print("Model evaluated match passed.")


def test_model_condition_not_matched_stays_silent():
    """A condition the model rejects produces no notification."""
    print("Testing model evaluated non-match...")
    workflow = build_workflow([
        {'id': 'm1', 'name': 'Expiring certificates', 'severity': 'high',
         'condition': {'type': 'model_evaluation', 'prompt': 'any certificate expires within 14 days'}},
    ])
    evaluator = RecordingEvaluator(
        '{"results": [{"rule_id": "m1", "matched": false, "reason": "Nothing expires soon."}]}'
    )

    decision = decide(
        workflow,
        {'status': 'completed', 'success': True},
        {'reply': 'all certificates are valid for another year'},
        model_evaluator=evaluator,
    )
    assert decision['should_alert'] is False
    assert len(evaluator.prompts) == 1
    print("Model evaluated non-match passed.")


def test_multiple_model_conditions_use_a_single_batched_call():
    """Every model evaluated rule is judged in one call, not one call per rule."""
    print("Testing batched evaluation...")
    workflow = build_workflow([
        {'id': 'm1', 'name': 'Expiring certs', 'severity': 'medium',
         'condition': {'type': 'model_evaluation', 'prompt': 'any certificate expires soon'}},
        {'id': 'm2', 'name': 'Failed logins', 'severity': 'high',
         'condition': {'type': 'model_evaluation', 'prompt': 'repeated failed sign-ins were reported'}},
        {'id': 'm3', 'name': 'Quota warnings', 'severity': 'low',
         'condition': {'type': 'model_evaluation', 'prompt': 'a quota is close to exhaustion'}},
    ])
    evaluator = RecordingEvaluator(
        '{"results": ['
        '{"rule_id": "m1", "matched": true, "reason": "One cert expires."},'
        '{"rule_id": "m2", "matched": true, "reason": "12 failed sign-ins."},'
        '{"rule_id": "m3", "matched": false, "reason": "Quota is fine."}'
        ']}'
    )

    decision = decide(
        workflow,
        {'status': 'completed', 'success': True},
        {'reply': 'cert expiring, 12 failed sign-ins observed'},
        model_evaluator=evaluator,
    )

    assert len(evaluator.prompts) == 1
    assert decision['severity'] == 'high'
    matched_ids = {match['rule_id'] for match in decision['matched_rules']}
    assert matched_ids == {'m1', 'm2'}
    assert 'm1' in evaluator.prompts[0] and 'm2' in evaluator.prompts[0] and 'm3' in evaluator.prompts[0]
    print("Batched evaluation passed.")


def test_model_call_is_skipped_when_it_cannot_change_the_outcome():
    """No tokens are spent when a deterministic rule already outranks every model rule."""
    print("Testing skip optimization...")
    workflow = build_workflow([
        {'id': 'd1', 'name': 'Run failed', 'severity': 'critical',
         'condition': {'type': 'run_status', 'statuses': ['failed']}},
        {'id': 'm1', 'name': 'Expiring certs', 'severity': 'high',
         'condition': {'type': 'model_evaluation', 'prompt': 'any certificate expires soon'}},
    ])
    evaluator = RecordingEvaluator('{"results": []}')

    decision = decide(
        workflow,
        {'status': 'failed', 'success': False, 'error': 'boom'},
        {},
        model_evaluator=evaluator,
    )

    assert decision['should_alert'] is True
    assert decision['severity'] == 'critical'
    assert evaluator.prompts == []
    assert decision['model_evaluation']['used'] is False
    assert decision['model_evaluation']['skipped_rule_ids'] == ['m1']

    # A model rule that outranks the deterministic match is still evaluated.
    louder_workflow = build_workflow([
        {'id': 'd1', 'name': 'Run completed', 'severity': 'low',
         'condition': {'type': 'run_status', 'statuses': ['completed']}},
        {'id': 'm1', 'name': 'Expiring certs', 'severity': 'critical',
         'condition': {'type': 'model_evaluation', 'prompt': 'any certificate expires soon'}},
    ])
    louder_evaluator = RecordingEvaluator(
        '{"results": [{"rule_id": "m1", "matched": true, "reason": "Cert expires tomorrow."}]}'
    )
    decision = decide(
        louder_workflow,
        {'status': 'completed', 'success': True},
        {'reply': 'cert expires tomorrow'},
        model_evaluator=louder_evaluator,
    )
    assert len(louder_evaluator.prompts) == 1
    assert decision['severity'] == 'critical'
    print("Skip optimization passed.")


def test_malformed_and_failed_evaluations_honor_on_error():
    """An unusable verdict either stays silent or alerts, exactly as configured."""
    print("Testing on_error handling...")
    rules = [
        {'id': 'm1', 'name': 'Expiring certs', 'severity': 'high',
         'condition': {'type': 'model_evaluation', 'prompt': 'any certificate expires soon'}},
    ]

    skip_workflow = build_workflow(rules, evaluation={'on_error': 'skip'})
    decision = decide(
        skip_workflow,
        {'status': 'completed', 'success': True},
        {'reply': 'x'},
        model_evaluator=RecordingEvaluator('I could not decide.'),
    )
    assert decision['should_alert'] is False
    assert decision['model_evaluation']['error']

    alert_workflow = build_workflow(rules, evaluation={'on_error': 'alert'})
    decision = decide(
        alert_workflow,
        {'status': 'completed', 'success': True},
        {'reply': 'x'},
        model_evaluator=RecordingEvaluator('I could not decide.'),
    )
    assert decision['should_alert'] is True
    assert decision['severity'] == 'high'
    assert decision['category'] == 'failure'

    # A raised exception is treated the same way as an unparseable verdict.
    decision = decide(
        alert_workflow,
        {'status': 'completed', 'success': True},
        {'reply': 'x'},
        model_evaluator=RecordingEvaluator(RuntimeError('model endpoint unavailable')),
    )
    assert decision['should_alert'] is True
    assert 'model endpoint unavailable' in decision['model_evaluation']['error']

    # Without an evaluator the rule is reported as unevaluated rather than matched.
    decision = decide(
        skip_workflow,
        {'status': 'completed', 'success': True},
        {'reply': 'x'},
        model_evaluator=None,
    )
    assert decision['should_alert'] is False
    assert decision['model_evaluation']['error'] == 'No model evaluator was available for this run.'
    print("on_error handling passed.")


def test_response_parsing_tolerates_common_model_formatting():
    """Fenced or chatty JSON is still parsed, but nonsense is rejected."""
    print("Testing response parsing...")
    verdicts = parse_model_evaluation_response(
        '```json\n{"results": [{"rule_id": "m1", "matched": true, "reason": "Found it."}]}\n```'
    )
    assert verdicts['m1']['matched'] is True
    assert verdicts['m1']['reason'] == 'Found it.'

    verdicts = parse_model_evaluation_response(
        'Sure! {"results": [{"rule_id": "m1", "matched": "yes", "reason": "Found it."}]} Hope that helps.'
    )
    assert verdicts['m1']['matched'] is True

    verdicts = parse_model_evaluation_response('{"results": [{"rule_id": "m1", "matched": false}]}')
    assert verdicts['m1']['matched'] is False

    for bad_response in ['', 'no json here', '{"other": []}', '[]']:
        try:
            parse_model_evaluation_response(bad_response)
            raise AssertionError(f'Expected rejection for {bad_response!r}')
        except ValueError:
            pass
    print("Response parsing passed.")


def test_prompt_includes_scoped_output_and_is_truncated():
    """The prompt carries the scoped output but stays bounded in size."""
    print("Testing prompt construction...")
    rules = normalize_alert_rules([
        {'id': 'm1', 'name': 'Scan review', 'severity': 'high', 'scope': {'type': 'any_task'},
         'condition': {'type': 'model_evaluation', 'prompt': 'the scan reported anything unusual'}},
    ])
    workflow = {'id': 'w', 'name': 'Scanner', 'alert_mode': 'rules', 'alert_rules': rules}
    facts = build_workflow_alert_facts(
        workflow,
        {'status': 'completed', 'success': True},
        {
            'reply': 'final summary',
            'task_results': [
                {'task': {'id': 't1', 'name': 'Scan'}, 'status': 'succeeded',
                 'result': {'reply': 'unusual traffic spike detected'}},
            ],
        },
    )

    prompt = build_model_evaluation_prompt(rules, facts)
    assert 'unusual traffic spike detected' in prompt
    assert 'the scan reported anything unusual' in prompt
    assert 'rule_id: m1' in prompt
    assert '"results"' in prompt
    assert 'Run status: completed' in prompt

    long_facts = build_workflow_alert_facts(
        workflow,
        {'status': 'completed', 'success': True},
        {
            'reply': 'x',
            'task_results': [
                {'task': {'id': 't1', 'name': 'Scan'}, 'status': 'succeeded',
                 'result': {'reply': 'y' * (WORKFLOW_ALERT_EVALUATION_TEXT_LIMIT * 3)}},
            ],
        },
    )
    long_prompt = build_model_evaluation_prompt(rules, long_facts)
    assert len(long_prompt) < WORKFLOW_ALERT_EVALUATION_TEXT_LIMIT + 2000
    print("Prompt construction passed.")


def test_runner_supplies_the_model_evaluator():
    """The runner builds the evaluator only when a model evaluated rule is present."""
    print("Testing runner evaluator wiring...")
    assert_app_version_at_least("0.250.213")
    runner_content = read_text("application/single_app/functions_workflow_runner.py")

    assert 'def _build_workflow_alert_model_evaluator(workflow, settings=None):' in runner_content
    assert '_resolve_model_workflow_client(workflow, evaluation_settings)' in runner_content
    assert 'if _workflow_alert_rules_need_model_evaluation(alert_config, facts):' in runner_content
    assert 'model_evaluator=model_evaluator' in runner_content
    assert "'role': 'system'," in runner_content
    assert 'temperature=0,' in runner_content

    workflow_js = read_text("application/single_app/static/js/workspace/workspace_workflows.js")
    assert 'model_evaluation' in workflow_js
    assert 'workflowAlertEvaluationOnErrorSelect' in workflow_js
    print("Runner evaluator wiring passed.")


if __name__ == '__main__':
    tests = [
        test_model_condition_matches_and_reports_its_reason,
        test_model_condition_not_matched_stays_silent,
        test_multiple_model_conditions_use_a_single_batched_call,
        test_model_call_is_skipped_when_it_cannot_change_the_outcome,
        test_malformed_and_failed_evaluations_honor_on_error,
        test_response_parsing_tolerates_common_model_formatting,
        test_prompt_includes_scoped_output_and_is_truncated,
        test_runner_supplies_the_model_evaluator,
    ]

    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {test.__name__}: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
