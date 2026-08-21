#!/usr/bin/env python3
# test_workflow_alert_rules.py
"""
Functional test for conditional workflow alert rules.
Version: 0.250.213
Implemented in: 0.250.213

This test ensures workflow alerts only fire when a declared condition is met,
that the highest matching severity wins while every matched rule is reported,
that a run matching nothing produces no notification at all, and that legacy
workflows carrying only alert_priority keep alerting through migrated rules.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_support.versioning import assert_app_version_at_least

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'application' / 'single_app'))

from functions_workflow_alerts import (  # noqa: E402
    WORKFLOW_ALERT_SEVERITY_ORDER,
    build_legacy_alert_rules,
    build_workflow_alert_facts,
    evaluate_workflow_alert_rules,
    get_alert_severity_rank,
    normalize_alert_rules,
    normalize_workflow_alert_settings,
    resolve_workflow_alert_config,
    summarize_alert_decision,
    validate_alert_regex,
)


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def build_workflow(rules, mode='rules', evaluation=None):
    return {
        'id': 'workflow-1',
        'name': 'Certificate watch',
        'user_id': 'user-1',
        'alert_mode': mode,
        'alert_rules': normalize_alert_rules(rules),
        'alert_evaluation': evaluation or {'on_error': 'skip'},
    }


def decide(workflow, run_record, execution_result=None, model_evaluator=None):
    facts = build_workflow_alert_facts(workflow, run_record, execution_result or {})
    return evaluate_workflow_alert_rules(workflow, facts, model_evaluator=model_evaluator)


def test_severity_ladder_and_delivery_defaults():
    """Info and low stay in the bell; medium and above interrupt with the pop-up."""
    print("Testing severity ladder and delivery defaults...")
    assert WORKFLOW_ALERT_SEVERITY_ORDER == ('info', 'low', 'medium', 'high', 'critical')
    assert get_alert_severity_rank('critical') > get_alert_severity_rank('high')
    assert get_alert_severity_rank('info') < get_alert_severity_rank('low')

    quiet = build_workflow([
        {'id': 'r1', 'name': 'Quiet', 'severity': 'info',
         'condition': {'type': 'run_status', 'statuses': ['completed']}},
    ])
    decision = decide(quiet, {'status': 'completed', 'success': True}, {'reply': 'done'})
    assert decision['should_alert'] is True
    assert decision['severity'] == 'info'
    assert decision['delivery'] == 'notify_only'

    loud = build_workflow([
        {'id': 'r1', 'name': 'Loud', 'severity': 'high',
         'condition': {'type': 'run_status', 'statuses': ['completed']}},
    ])
    decision = decide(loud, {'status': 'completed', 'success': True}, {'reply': 'done'})
    assert decision['delivery'] == 'popup'

    override = build_workflow([
        {'id': 'r1', 'name': 'Quiet but loud', 'severity': 'info', 'delivery': 'popup',
         'condition': {'type': 'run_status', 'statuses': ['completed']}},
    ])
    decision = decide(override, {'status': 'completed', 'success': True}, {'reply': 'done'})
    assert decision['delivery'] == 'popup'
    print("Severity ladder and delivery defaults passed.")


def test_no_matching_rule_produces_no_alert():
    """A run that matches nothing must stay completely silent."""
    print("Testing silent runs...")
    workflow = build_workflow([
        {'id': 'r1', 'name': 'Only on failure', 'severity': 'high',
         'condition': {'type': 'run_status', 'statuses': ['failed']}},
    ])
    decision = decide(workflow, {'status': 'completed', 'success': True}, {'reply': 'nothing notable'})
    assert decision['should_alert'] is False
    assert not decision['matched_rules']
    assert summarize_alert_decision(decision) == 'No alert rule matched this run.'

    off_workflow = build_workflow([
        {'id': 'r1', 'name': 'Anything', 'severity': 'high',
         'condition': {'type': 'run_status', 'statuses': ['completed']}},
    ], mode='off')
    decision = decide(off_workflow, {'status': 'completed', 'success': True}, {'reply': 'x'})
    assert decision['should_alert'] is False
    print("Silent runs passed.")


def test_highest_severity_wins_and_lists_every_match():
    """Every matched rule is reported, and the loudest one sets the severity."""
    print("Testing highest severity resolution...")
    workflow = build_workflow([
        {'id': 'quiet', 'name': 'Ran', 'severity': 'info',
         'condition': {'type': 'run_status', 'statuses': ['completed']}},
        {'id': 'loud', 'name': 'Expiring found', 'severity': 'critical',
         'condition': {'type': 'text_match', 'mode': 'contains_any', 'values': ['EXPIRING']}},
        {'id': 'middle', 'name': 'Warning seen', 'severity': 'medium',
         'condition': {'type': 'text_match', 'mode': 'contains_any', 'values': ['warning']}},
    ])
    decision = decide(
        workflow,
        {'status': 'completed', 'success': True},
        {'reply': 'warning: 3 certificates EXPIRING soon'},
    )

    assert decision['should_alert'] is True
    assert decision['severity'] == 'critical'
    assert decision['winning_rule_name'] == 'Expiring found'
    matched_names = {match['rule_name'] for match in decision['matched_rules']}
    assert matched_names == {'Ran', 'Expiring found', 'Warning seen'}
    assert 'Expiring found' in summarize_alert_decision(decision)
    print("Highest severity resolution passed.")


def test_failure_category_is_separate_from_severity():
    """Run and task errors are categorized as failures whatever severity the owner picked."""
    print("Testing failure category...")
    workflow = build_workflow([
        {'id': 'r1', 'name': 'Run failed', 'severity': 'low',
         'condition': {'type': 'run_status', 'statuses': ['failed']}},
    ])
    decision = decide(workflow, {'status': 'failed', 'success': False, 'error': 'boom'})
    assert decision['should_alert'] is True
    assert decision['severity'] == 'low'
    assert decision['category'] == 'failure'

    task_workflow = build_workflow([
        {'id': 'r1', 'name': 'Task failed', 'severity': 'medium',
         'scope': {'type': 'any_task'},
         'condition': {'type': 'task_status', 'statuses': ['failed']}},
    ])
    decision = decide(
        task_workflow,
        {'status': 'completed', 'success': True},
        {
            'reply': 'partial',
            'task_results': [
                {'task': {'id': 't1', 'name': 'Collect'}, 'status': 'failed', 'error': 'timeout', 'result': {}},
                {'task': {'id': 't2', 'name': 'Report'}, 'status': 'succeeded', 'result': {'reply': 'ok'}},
            ],
        },
    )
    assert decision['should_alert'] is True
    assert decision['category'] == 'failure'
    assert 'Collect' in decision['matched_rules'][0]['reason']

    success_workflow = build_workflow([
        {'id': 'r1', 'name': 'Found something', 'severity': 'critical',
         'condition': {'type': 'text_match', 'mode': 'contains_any', 'values': ['found']}},
    ])
    decision = decide(success_workflow, {'status': 'completed', 'success': True}, {'reply': 'found it'})
    assert decision['category'] == 'alert'
    print("Failure category passed.")


def test_completed_with_task_errors_is_its_own_status():
    """A run that completes while a task errored can be alerted on separately."""
    print("Testing completed_with_task_errors...")
    workflow = build_workflow([
        {'id': 'r1', 'name': 'Partial completion', 'severity': 'high',
         'condition': {'type': 'run_status', 'statuses': ['completed_with_task_errors']}},
    ])
    decision = decide(
        workflow,
        {'status': 'completed', 'success': True},
        {
            'reply': 'done',
            'task_error_count': 1,
            'task_results': [
                {'task': {'id': 't1', 'name': 'Collect'}, 'status': 'failed', 'error': 'nope', 'result': {}},
            ],
        },
    )
    assert decision['should_alert'] is True
    assert decision['category'] == 'failure'

    clean_decision = decide(workflow, {'status': 'completed', 'success': True}, {'reply': 'done'})
    assert clean_decision['should_alert'] is False
    print("completed_with_task_errors passed.")


def test_text_match_modes_and_scoping():
    """Text conditions honor each match mode and the configured scope."""
    print("Testing text match modes and scoping...")
    execution_result = {
        'reply': 'Summary: all systems nominal',
        'task_results': [
            {'task': {'id': 't1', 'name': 'Scan'}, 'status': 'succeeded',
             'result': {'reply': 'Detected 4 CRITICAL findings and 2 warnings'}},
            {'task': {'id': 't2', 'name': 'Summarize'}, 'status': 'succeeded',
             'result': {'reply': 'Summary: all systems nominal'}},
        ],
    }
    run_record = {'status': 'completed', 'success': True}

    # Final output does not contain CRITICAL, but a task output does.
    final_scope = build_workflow([
        {'id': 'r1', 'name': 'Final', 'severity': 'high', 'scope': {'type': 'final'},
         'condition': {'type': 'text_match', 'mode': 'contains_any', 'values': ['CRITICAL']}},
    ])
    assert decide(final_scope, run_record, execution_result)['should_alert'] is False

    any_task_scope = build_workflow([
        {'id': 'r1', 'name': 'Any task', 'severity': 'high', 'scope': {'type': 'any_task'},
         'condition': {'type': 'text_match', 'mode': 'contains_any', 'values': ['CRITICAL']}},
    ])
    decision = decide(any_task_scope, run_record, execution_result)
    assert decision['should_alert'] is True
    assert 'Scan' in decision['matched_rules'][0]['reason']

    specific_task_scope = build_workflow([
        {'id': 'r1', 'name': 'Only summarize', 'severity': 'high',
         'scope': {'type': 'task', 'task_id': 't2'},
         'condition': {'type': 'text_match', 'mode': 'contains_any', 'values': ['CRITICAL']}},
    ])
    assert decide(specific_task_scope, run_record, execution_result)['should_alert'] is False

    contains_all = build_workflow([
        {'id': 'r1', 'name': 'Both terms', 'severity': 'high', 'scope': {'type': 'any_task'},
         'condition': {'type': 'text_match', 'mode': 'contains_all', 'values': ['CRITICAL', 'warnings']}},
    ])
    assert decide(contains_all, run_record, execution_result)['should_alert'] is True

    contains_all_miss = build_workflow([
        {'id': 'r1', 'name': 'Both terms', 'severity': 'high', 'scope': {'type': 'any_task'},
         'condition': {'type': 'text_match', 'mode': 'contains_all', 'values': ['CRITICAL', 'unrelated']}},
    ])
    assert decide(contains_all_miss, run_record, execution_result)['should_alert'] is False

    not_contains = build_workflow([
        {'id': 'r1', 'name': 'Missing signoff', 'severity': 'medium', 'scope': {'type': 'final'},
         'condition': {'type': 'text_match', 'mode': 'not_contains', 'values': ['signed off']}},
    ])
    assert decide(not_contains, run_record, execution_result)['should_alert'] is True

    regex_rule = build_workflow([
        {'id': 'r1', 'name': 'Counted findings', 'severity': 'high', 'scope': {'type': 'any_task'},
         'condition': {'type': 'text_match', 'mode': 'regex', 'pattern': r'\d+ CRITICAL'}},
    ])
    assert decide(regex_rule, run_record, execution_result)['should_alert'] is True

    case_sensitive = build_workflow([
        {'id': 'r1', 'name': 'Exact case', 'severity': 'high', 'scope': {'type': 'any_task'},
         'condition': {'type': 'text_match', 'mode': 'contains_any', 'values': ['critical'],
                       'case_sensitive': True}},
    ])
    assert decide(case_sensitive, run_record, execution_result)['should_alert'] is False
    print("Text match modes and scoping passed.")


def test_file_sync_no_output_and_agent_signal_conditions():
    """File Sync outcomes, empty output and agent raised signals all drive alerts."""
    print("Testing file sync, no output and agent signal conditions...")
    changes_rule = build_workflow([
        {'id': 'r1', 'name': 'New documents', 'severity': 'medium',
         'condition': {'type': 'file_sync', 'outcome': 'changes_found'}},
    ])
    decision = decide(
        changes_rule,
        {'status': 'completed', 'success': True, 'file_sync': {'changed_documents': [{'id': 'doc-1'}]}},
        {'reply': 'ok'},
    )
    assert decision['should_alert'] is True
    assert decision['category'] == 'alert'

    decision = decide(
        changes_rule,
        {'status': 'completed', 'success': True, 'file_sync': {'changed_documents': []}},
        {'reply': 'ok'},
    )
    assert decision['should_alert'] is False

    sync_failed_rule = build_workflow([
        {'id': 'r1', 'name': 'Sync broke', 'severity': 'high',
         'condition': {'type': 'file_sync', 'outcome': 'sync_failed'}},
    ])
    decision = decide(
        sync_failed_rule,
        {'status': 'completed', 'success': True, 'file_sync': {'error': 'blob unreachable'}},
        {'reply': 'ok'},
    )
    assert decision['should_alert'] is True
    assert decision['category'] == 'failure'

    no_output_rule = build_workflow([
        {'id': 'r1', 'name': 'Nothing came back', 'severity': 'medium',
         'condition': {'type': 'no_output'}},
    ])
    assert decide(no_output_rule, {'status': 'completed', 'success': True}, {'reply': ''})['should_alert'] is True
    assert decide(no_output_rule, {'status': 'completed', 'success': True}, {'reply': 'x'})['should_alert'] is False

    signal_rule = build_workflow([
        {'id': 'r1', 'name': 'Agent flagged it', 'severity': 'low',
         'condition': {'type': 'agent_signal', 'min_severity': 'medium'}},
    ])
    decision = decide(
        signal_rule,
        {'status': 'completed', 'success': True},
        {
            'reply': 'ok',
            'agent_alert_signals': [
                {'severity': 'critical', 'title': 'Breach detected', 'reason': 'Unrecognized sign-in from a new region.'},
            ],
        },
    )
    assert decision['should_alert'] is True
    # The agent can escalate above the rule floor but never below it.
    assert decision['severity'] == 'critical'
    assert 'Unrecognized sign-in' in decision['matched_rules'][0]['reason']

    decision = decide(
        signal_rule,
        {'status': 'completed', 'success': True},
        {'reply': 'ok', 'agent_alert_signals': [{'severity': 'info', 'title': 'FYI'}]},
    )
    assert decision['should_alert'] is False

    named_signal_rule = build_workflow([
        {'id': 'r1', 'name': 'Only cert signals', 'severity': 'high',
         'condition': {'type': 'agent_signal', 'signal_name': 'expiring-certificates', 'min_severity': 'info'}},
    ])
    decision = decide(
        named_signal_rule,
        {'status': 'completed', 'success': True},
        {'reply': 'ok', 'agent_alert_signals': [{'severity': 'high', 'signal_name': 'other-signal'}]},
    )
    assert decision['should_alert'] is False
    print("File sync, no output and agent signal conditions passed.")


def test_legacy_alert_priority_migration_preserves_behavior():
    """Workflows with only alert_priority keep alerting through editable rules."""
    print("Testing legacy migration...")
    legacy_workflow = {'id': 'w', 'name': 'Legacy', 'alert_priority': 'low'}
    config = resolve_workflow_alert_config(legacy_workflow)
    assert config['alert_mode'] == 'rules'
    assert [rule['name'] for rule in config['alert_rules']] == ['Run failed', 'Run completed']
    assert config['alert_rules'][0]['severity'] == 'high'
    assert config['alert_rules'][1]['severity'] == 'low'
    # Legacy alerts always opened the modal, so migration pins delivery to popup.
    assert all(rule['delivery'] == 'popup' for rule in config['alert_rules'])

    decision = decide(legacy_workflow, {'status': 'completed', 'success': True}, {'reply': 'x'})
    assert decision['should_alert'] is True
    assert decision['severity'] == 'low'
    assert decision['delivery'] == 'popup'

    decision = decide(legacy_workflow, {'status': 'failed', 'success': False, 'error': 'boom'})
    assert decision['severity'] == 'high'
    assert decision['category'] == 'failure'

    # Cancelled runs stayed silent before and must stay silent now.
    decision = decide(legacy_workflow, {'status': 'cancelled', 'success': False})
    assert decision['should_alert'] is False

    silent_legacy = resolve_workflow_alert_config({'id': 'w', 'alert_priority': 'none'})
    assert silent_legacy['alert_mode'] == 'off'
    assert build_legacy_alert_rules('none') == []
    print("Legacy migration passed.")


def test_every_run_mode_matches_previous_behavior():
    """The legacy every-run mode remains selectable and behaves as before."""
    print("Testing every_run mode...")
    workflow = {'id': 'w', 'name': 'Noisy', 'alert_mode': 'every_run', 'alert_priority': 'medium'}
    decision = decide(workflow, {'status': 'completed', 'success': True}, {'reply': 'x'})
    assert decision['should_alert'] is True
    assert decision['severity'] == 'medium'
    assert decision['delivery'] == 'popup'
    assert decision['category'] == 'alert'

    decision = decide(workflow, {'status': 'failed', 'success': False, 'error': 'boom'})
    assert decision['category'] == 'failure'

    decision = decide(workflow, {'status': 'cancelled', 'success': False})
    assert decision['should_alert'] is False
    print("every_run mode passed.")


def test_rule_validation_rejects_bad_configuration():
    """Invalid rules fail at save time rather than silently misbehaving at run time."""
    print("Testing rule validation...")
    for bad_pattern in ['(a+)+', '([a-z]*)*', 'x' * 500, '(unclosed']:
        try:
            validate_alert_regex(bad_pattern)
            raise AssertionError(f'Expected regex rejection for {bad_pattern!r}')
        except ValueError:
            pass
    assert validate_alert_regex(r'\d+ CRITICAL') is not None

    def expect_value_error(callback, label):
        try:
            callback()
        except ValueError:
            return
        raise AssertionError(f'Expected ValueError for {label}')

    expect_value_error(
        lambda: normalize_alert_rules([{'condition': {'type': 'unknown_condition'}}]),
        'unknown condition type',
    )
    expect_value_error(
        lambda: normalize_alert_rules([{'severity': 'urgent', 'condition': {'type': 'no_output'}}]),
        'unsupported severity',
    )
    expect_value_error(
        lambda: normalize_alert_rules([{'condition': {'type': 'run_status', 'statuses': ['exploded']}}]),
        'unsupported run status',
    )
    expect_value_error(
        lambda: normalize_alert_rules([{'condition': {'type': 'model_evaluation', 'prompt': ''}}]),
        'empty model evaluation prompt',
    )
    expect_value_error(
        lambda: normalize_alert_rules(
            [{'scope': {'type': 'task', 'task_id': 'missing'}, 'condition': {'type': 'no_output'}}],
            task_ids=['t1'],
        ),
        'task scope referencing an unknown task',
    )
    expect_value_error(
        lambda: normalize_workflow_alert_settings({'alert_mode': 'rules', 'alert_rules': []}),
        'rules mode without any rules',
    )
    expect_value_error(
        lambda: normalize_workflow_alert_settings({'alert_mode': 'every_run', 'alert_priority': 'none'}),
        'every_run mode without a priority',
    )
    expect_value_error(
        lambda: normalize_workflow_alert_settings({'alert_mode': 'sometimes'}),
        'unknown alert mode',
    )

    # A rule without an explicit name is described from its condition.
    normalized = normalize_alert_rules([{'condition': {'type': 'run_status', 'statuses': ['failed']}}])
    assert normalized[0]['name'] == 'Run status is failed'
    assert normalized[0]['id']
    print("Rule validation passed.")


def test_save_settings_keeps_legacy_clients_alerting():
    """Clients that only send alert_priority still end up with working rules."""
    print("Testing save settings compatibility...")
    settings = normalize_workflow_alert_settings({'alert_priority': 'high'})
    assert settings['alert_mode'] == 'rules'
    assert settings['alert_priority'] == 'high'
    assert len(settings['alert_rules']) == 2

    settings = normalize_workflow_alert_settings({'alert_priority': 'none'})
    assert settings['alert_mode'] == 'off'
    assert settings['alert_rules'] == []

    # Clearing every rule without picking a mode turns alerts off instead of failing.
    settings = normalize_workflow_alert_settings(
        {'alert_rules': []},
        existing_workflow={'alert_mode': 'rules', 'alert_rules': [
            {'id': 'r1', 'severity': 'high', 'condition': {'type': 'no_output'}},
        ]},
    )
    assert settings['alert_mode'] == 'off'

    settings = normalize_workflow_alert_settings({'alert_evaluation': {'on_error': 'alert'},
                                                  'alert_mode': 'off'})
    assert settings['alert_evaluation']['on_error'] == 'alert'
    print("Save settings compatibility passed.")


def test_alert_rule_contracts_are_wired_through_the_stack():
    """The rule engine is referenced by the save paths, runner, UI and notifications."""
    print("Testing stack wiring contracts...")
    assert_app_version_at_least("0.250.213")

    personal_content = read_text("application/single_app/functions_personal_workflows.py")
    group_content = read_text("application/single_app/functions_group_workflows.py")
    runner_content = read_text("application/single_app/functions_workflow_runner.py")
    notifications_content = read_text("application/single_app/functions_notifications.py")
    activity_content = read_text("application/single_app/functions_workflow_activity.py")
    workspace_template = read_text("application/single_app/templates/workspace.html")
    group_template = read_text("application/single_app/templates/group_workspaces.html")
    workflow_js = read_text("application/single_app/static/js/workspace/workspace_workflows.js")
    notifications_js = read_text("application/single_app/static/js/notifications.js")
    base_template = read_text("application/single_app/templates/base.html")

    assert 'from functions_workflow_alerts import normalize_workflow_alert_settings' in personal_content
    assert "'alert_rules': alert_settings['alert_rules']," in personal_content
    assert 'from functions_workflow_alerts import normalize_workflow_alert_settings' in group_content
    assert "'alert_rules': alert_settings['alert_rules']," in group_content

    assert 'from functions_workflow_alerts import (' in runner_content
    assert 'def _workflow_alert_rules_need_model_evaluation(alert_config, facts):' in runner_content
    assert 'def _build_workflow_alert_model_evaluator(workflow, settings=None):' in runner_content
    assert "if not decision.get('should_alert'):" in runner_content
    assert "'category': decision.get('category') or 'alert'," in runner_content
    assert "'delivery': decision.get('delivery') or 'popup'," in runner_content
    assert 'def _record_workflow_alert_decision(workflow, run_record, decision):' in runner_content

    assert "'info': {" in notifications_content
    assert "'critical': {" in notifications_content
    assert 'def _get_workflow_alert_category(notification):' in notifications_content
    assert 'def _get_workflow_alert_delivery(notification):' in notifications_content
    assert 'WORKFLOW_ALERT_DELIVERY_NOTIFY_ONLY' in notifications_content

    assert 'resolve_workflow_alert_config' in activity_content
    assert "'alert_rules': [" in activity_content

    for template in (workspace_template, group_template):
        assert 'id="workflow-alert-mode"' in template
        assert 'id="workflow-alert-rules-list"' in template
        assert 'id="workflow-alert-rule-add-btn"' in template
        assert 'id="workflow-alert-evaluation-on-error"' in template

    assert 'function renderWorkflowAlertRules()' in workflow_js
    assert 'function collectWorkflowAlertRulesPayload()' in workflow_js
    assert 'function validateWorkflowAlertRules()' in workflow_js
    assert 'alert_mode: getWorkflowAlertMode(),' in workflow_js
    assert 'alert_rules: collectWorkflowAlertRulesPayload(),' in workflow_js
    assert 'function buildLegacyWorkflowAlertRules(priority)' in workflow_js

    assert "normalizedPriority === 'critical'" in notifications_js
    assert "normalizedPriority === 'info'" in notifications_js
    assert 'function getWorkflowAlertDelivery(notification)' in notifications_js
    assert "getWorkflowAlertDelivery(notification) === 'notify_only'" in notifications_js
    assert '[data-priority="critical"]' in base_template
    assert '[data-category="failure"]' in base_template
    print("Stack wiring contracts passed.")


if __name__ == '__main__':
    tests = [
        test_severity_ladder_and_delivery_defaults,
        test_no_matching_rule_produces_no_alert,
        test_highest_severity_wins_and_lists_every_match,
        test_failure_category_is_separate_from_severity,
        test_completed_with_task_errors_is_its_own_status,
        test_text_match_modes_and_scoping,
        test_file_sync_no_output_and_agent_signal_conditions,
        test_legacy_alert_priority_migration_preserves_behavior,
        test_every_run_mode_matches_previous_behavior,
        test_rule_validation_rejects_bad_configuration,
        test_save_settings_keeps_legacy_clients_alerting,
        test_alert_rule_contracts_are_wired_through_the_stack,
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
