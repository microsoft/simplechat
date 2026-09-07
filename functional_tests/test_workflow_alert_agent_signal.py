#!/usr/bin/env python3
# test_workflow_alert_agent_signal.py
"""
Functional test for agent raised workflow alert signals.
Version: 0.250.213
Implemented in: 0.250.213

This test ensures an agent can raise an alert signal during a workflow run, that
the signal is normalized and matched by agent_signal rules, that a signal can
escalate a rule's severity but never lower it, and that the plugin function is
gated so it cannot fabricate a notification outside an active workflow run.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_support.versioning import assert_app_version_at_least

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'application' / 'single_app'))

from functions_workflow_alerts import (  # noqa: E402
    build_workflow_alert_facts,
    evaluate_workflow_alert_rules,
    normalize_agent_alert_signal,
    normalize_alert_rules,
)


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def build_workflow(rules):
    return {
        'id': 'workflow-1',
        'name': 'Threat watch',
        'alert_mode': 'rules',
        'alert_rules': normalize_alert_rules(rules),
    }


def decide(workflow, signals, run_record=None):
    facts = build_workflow_alert_facts(
        workflow,
        run_record or {'status': 'completed', 'success': True},
        {'reply': 'run output', 'agent_alert_signals': signals},
    )
    return evaluate_workflow_alert_rules(workflow, facts)


def test_agent_signal_normalization():
    """Signals are normalized to a supported severity with trimmed text."""
    print("Testing agent signal normalization...")
    signal = normalize_agent_alert_signal({
        'severity': '  HIGH ',
        'title': '  Breach   detected  ',
        'reason': 'Unrecognized\n sign-in   from a new region.',
        'signal_name': ' suspicious-signin ',
    })
    assert signal['severity'] == 'high'
    assert signal['title'] == 'Breach detected'
    assert signal['reason'] == 'Unrecognized sign-in from a new region.'
    assert signal['signal_name'] == 'suspicious-signin'

    # An unknown severity falls back to medium rather than raising mid-run.
    assert normalize_agent_alert_signal({'severity': 'catastrophic'})['severity'] == 'medium'
    assert normalize_agent_alert_signal({})['severity'] == 'medium'
    assert normalize_agent_alert_signal(None)['severity'] == 'medium'
    print("Agent signal normalization passed.")


def test_agent_signal_matches_and_escalates_but_never_lowers():
    """The rule severity is a floor the agent can raise, not a ceiling it can lower."""
    print("Testing signal severity floor...")
    workflow = build_workflow([
        {'id': 'r1', 'name': 'Agent raised', 'severity': 'medium',
         'condition': {'type': 'agent_signal', 'min_severity': 'info'}},
    ])

    decision = decide(workflow, [{'severity': 'critical', 'reason': 'Active intrusion.'}])
    assert decision['should_alert'] is True
    assert decision['severity'] == 'critical'
    assert decision['reasons'] == ['Active intrusion.']

    # A quieter signal still alerts at the rule's configured severity.
    decision = decide(workflow, [{'severity': 'info', 'reason': 'Minor note.'}])
    assert decision['should_alert'] is True
    assert decision['severity'] == 'medium'
    print("Signal severity floor passed.")


def test_min_severity_filters_noisy_signals():
    """Signals below the rule's minimum severity are ignored."""
    print("Testing min severity filtering...")
    workflow = build_workflow([
        {'id': 'r1', 'name': 'Only serious signals', 'severity': 'high',
         'condition': {'type': 'agent_signal', 'min_severity': 'high'}},
    ])

    assert decide(workflow, [{'severity': 'medium', 'reason': 'meh'}])['should_alert'] is False
    assert decide(workflow, [{'severity': 'high', 'reason': 'serious'}])['should_alert'] is True
    assert decide(workflow, [])['should_alert'] is False
    print("Min severity filtering passed.")


def test_named_signals_route_to_their_own_rules():
    """Distinct named signals can drive distinct rules and severities."""
    print("Testing named signal routing...")
    workflow = build_workflow([
        {'id': 'certs', 'name': 'Expiring certificates', 'severity': 'medium',
         'condition': {'type': 'agent_signal', 'signal_name': 'expiring-certificates'}},
        {'id': 'breach', 'name': 'Suspected breach', 'severity': 'critical',
         'condition': {'type': 'agent_signal', 'signal_name': 'suspected-breach'}},
    ])

    decision = decide(workflow, [{'severity': 'low', 'signal_name': 'expiring-certificates', 'reason': 'Cert expires.'}])
    assert decision['should_alert'] is True
    assert decision['severity'] == 'medium'
    assert decision['winning_rule_name'] == 'Expiring certificates'

    decision = decide(workflow, [
        {'severity': 'low', 'signal_name': 'expiring-certificates', 'reason': 'Cert expires.'},
        {'severity': 'low', 'signal_name': 'suspected-breach', 'reason': 'Odd traffic.'},
    ])
    assert decision['severity'] == 'critical'
    assert {match['rule_name'] for match in decision['matched_rules']} == {
        'Expiring certificates',
        'Suspected breach',
    }

    decision = decide(workflow, [{'severity': 'critical', 'signal_name': 'unrelated', 'reason': 'x'}])
    assert decision['should_alert'] is False
    print("Named signal routing passed.")


def test_plugin_function_is_registered_and_gated():
    """raise_workflow_alert is exposed as a capability and refuses outside a run."""
    print("Testing plugin registration and gating...")
    assert_app_version_at_least("0.250.213")

    operations_content = read_text("application/single_app/functions_simplechat_operations.py")
    plugin_content = read_text("application/single_app/semantic_kernel_plugins/simplechat_plugin.py")
    runner_content = read_text("application/single_app/functions_workflow_runner.py")

    assert '"raise_workflow_alert": "raise_workflow_alert",' in operations_content
    assert '"key": "raise_workflow_alert",' in operations_content
    # The capability is opt-in so existing agents do not silently gain the ability
    # to create notifications when this capability is added.
    assert '"default_enabled": False,' in operations_content
    assert 'definition.get("default_enabled", True)' in operations_content
    assert 'def raise_workflow_alert_for_current_user(' in operations_content
    assert 'if not is_workflow_alert_signal_scope_active():' in operations_content
    assert 'raise PermissionError(' in operations_content
    assert 'Workflow alerts can only be raised while a workflow run is executing.' in operations_content
    # The runner import must stay lazy because the runner imports this module.
    assert 'from functions_workflow_runner import (' in operations_content

    assert 'raise_workflow_alert_for_current_user,' in plugin_content
    assert 'def raise_workflow_alert(' in plugin_content
    assert '@kernel_function(description="Raise an alert signal for the workflow run currently executing.' in plugin_content

    # The admin capability toggles mirror the backend registry in both stepper modules.
    for stepper_path in (
        "application/single_app/static/js/agent_modal_stepper.js",
        "application/single_app/static/js/plugin_modal_stepper.js",
    ):
        stepper_content = read_text(stepper_path)
        assert "key: 'raise_workflow_alert'," in stepper_content
        assert 'defaultEnabled: false' in stepper_content
        assert 'defaults[definition.key] = definition.defaultEnabled !== false;' in stepper_content

    assert "_workflow_alert_signal_context = ContextVar('workflow_alert_signals', default=None)" in runner_content
    assert 'def workflow_alert_signal_scope(workflow=None, run_id=None):' in runner_content
    assert 'def is_workflow_alert_signal_scope_active():' in runner_content
    assert 'def record_workflow_alert_signal(severity, title=\'\', reason=\'\', signal_name=\'\'):' in runner_content
    assert 'def get_workflow_alert_signals():' in runner_content
    assert 'with workflow_alert_signal_scope(workflow, resolved_run_id):' in runner_content
    assert "execution_result['agent_alert_signals'] = get_workflow_alert_signals()" in runner_content
    print("Plugin registration and gating passed.")


def test_signal_scope_is_per_run():
    """The signal buffer is scoped to one run so signals never leak between runs."""
    print("Testing per-run signal scope...")
    runner_content = read_text("application/single_app/functions_workflow_runner.py")

    # The scope is entered in the public entry point and reset in a finally block,
    # so a failed run cannot leave signals behind for the next one.
    assert 'token = _workflow_alert_signal_context.set(scope)' in runner_content
    assert '_workflow_alert_signal_context.reset(token)' in runner_content
    assert 'def _run_personal_workflow_impl(' in runner_content
    assert 'return _run_personal_workflow_impl(' in runner_content

    # Group workflows delegate to the same entry point, so they get the same scope.
    assert 'def run_group_workflow(' in runner_content
    assert 'return run_personal_workflow(' in runner_content
    print("Per-run signal scope passed.")


if __name__ == '__main__':
    tests = [
        test_agent_signal_normalization,
        test_agent_signal_matches_and_escalates_but_never_lowers,
        test_min_severity_filters_noisy_signals,
        test_named_signals_route_to_their_own_rules,
        test_plugin_function_is_registered_and_gated,
        test_signal_scope_is_per_run,
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
