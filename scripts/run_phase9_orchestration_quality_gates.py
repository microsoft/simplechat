# run_phase9_orchestration_quality_gates.py
"""Run deterministic and optional live Phase 9 orchestration quality gates."""

import argparse
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPILE_TARGETS = (
    'application/single_app/functions_orchestration_evaluation.py',
    'application/single_app/functions_orchestration_runtime.py',
    'application/single_app/route_backend_chats.py',
)
AUTOMATED_TEST_TARGETS = (
    'functional_tests/test_phase9_orchestration_golden_scenarios.py',
    'functional_tests/test_phase9_orchestration_observability.py',
    'functional_tests/test_chat_turn_orchestration_plan.py',
    'functional_tests/test_chat_evidence_ledger.py',
    'functional_tests/test_chat_evidence_collectors.py',
    'functional_tests/test_agent_action_evidence_contract.py',
    'functional_tests/test_central_synthesis_contract.py',
    'functional_tests/test_orchestration_runtime.py',
    'functional_tests/test_chat_capability_discovery.py',
    'functional_tests/test_chat_capability_choice_contract.py',
    'functional_tests/test_chat_capability_choice_persistence.py',
    'functional_tests/test_chat_capability_choice_route.py',
    'functional_tests/test_chat_governed_agent_discovery.py',
    'functional_tests/test_image_proposal_pipeline.py',
    'functional_tests/test_image_proposal_approval_route.py',
    'functional_tests/test_chat_capability_usage_metadata.py',
    'functional_tests/test_dual_foundry_agent_support.py',
    'functional_tests/test_agents_catalog_feature.py',
    'functional_tests/test_personal_agent_user_id_saved.py',
    'functional_tests/test_document_action_phase_progress_status.py',
    'functional_tests/test_document_action_conversation_scope_metadata.py',
    'functional_tests/test_document_action_token_usage_aggregation.py',
    'functional_tests/test_chat_document_action_followup_persistence.py',
    'functional_tests/test_chat_navigation_unified_shell.py',
    'functional_tests/test_chat_thoughts_completed_progress_summary.py',
    'functional_tests/test_document_action_debug_logging.py',
    'functional_tests/test_document_action_stream_reconnect.py',
    'functional_tests/test_document_actions_and_comparison_feature.py',
    'functional_tests/test_document_analysis_feature.py',
    'functional_tests/test_document_analysis_progress_and_limits.py',
    'functional_tests/test_document_analysis_scope_select_fix.py',
    'functional_tests/route_tests/test_route_blueprint_policy_inventory.py',
    'functional_tests/route_tests/test_route_unauthenticated_policy_contract.py',
    'functional_tests/route_tests/test_route_policy_test_coverage.py',
    'ui_tests/test_chat_capability_choice_card.py',
    'ui_tests/test_phase9_orchestration_live_smoke.py',
)
LIVE_REQUIRED_ENVIRONMENT = (
    'SIMPLECHAT_PHASE9_LIVE_MANIFEST',
    'SIMPLECHAT_UI_BASE_URL',
)


def _repo_python():
    candidates = (
        REPO_ROOT / '.venv' / 'Scripts' / 'python.exe',
        REPO_ROOT / '.venv' / 'bin' / 'python',
    )
    return next((str(candidate) for candidate in candidates if candidate.exists()), sys.executable)


def _run(command, *, environment):
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        check=False,
    )
    return completed.returncode


def _validate_live_environment(environment):
    missing = [name for name in LIVE_REQUIRED_ENVIRONMENT if not environment.get(name)]
    has_authentication = bool(
        environment.get('SIMPLECHAT_UI_ACCESS_TOKEN')
        or environment.get('SIMPLECHAT_UI_STORAGE_STATE')
        or environment.get('SIMPLECHAT_UI_ADMIN_STORAGE_STATE')
    )
    if not has_authentication:
        missing.append(
            'SIMPLECHAT_UI_ACCESS_TOKEN or SIMPLECHAT_UI_STORAGE_STATE'
        )
    if missing:
        raise ValueError(
            'Live smoke requires: ' + ', '.join(missing)
        )


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description='Run Phase 9 orchestration compile, functional, security, UI-contract, and optional live-smoke gates.',
    )
    parser.add_argument(
        '--live-smoke',
        action='store_true',
        help='Require and execute the controlled deployed-environment smoke manifest.',
    )
    parser.add_argument(
        '--junit-xml',
        help='Optional workspace-relative or absolute JUnit XML output path.',
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List the deterministic gate targets without running them.',
    )
    parser.add_argument(
        '--pytest-arg',
        action='append',
        default=[],
        help='Additional argument passed to pytest; repeat for multiple arguments.',
    )
    return parser


def main(argv=None):
    args = build_argument_parser().parse_args(argv)
    if args.list:
        print('Compile targets:')
        for target in COMPILE_TARGETS:
            print(f'  {target}')
        print('Pytest targets:')
        for target in AUTOMATED_TEST_TARGETS:
            print(f'  {target}')
        return 0

    environment = os.environ.copy()
    environment['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    if args.live_smoke:
        _validate_live_environment(environment)
        environment['SIMPLECHAT_PHASE9_LIVE_REQUIRED'] = '1'

    python_executable = _repo_python()
    compile_command = [
        python_executable,
        '-m',
        'py_compile',
        *COMPILE_TARGETS,
    ]
    compile_exit_code = _run(compile_command, environment=environment)
    if compile_exit_code:
        return compile_exit_code

    pytest_command = [
        python_executable,
        '-m',
        'pytest',
        '-q',
        *AUTOMATED_TEST_TARGETS,
    ]
    if args.junit_xml:
        junit_path = Path(args.junit_xml)
        if not junit_path.is_absolute():
            junit_path = REPO_ROOT / junit_path
        junit_path.parent.mkdir(parents=True, exist_ok=True)
        pytest_command.append(f'--junitxml={junit_path}')
    pytest_command.extend(args.pytest_arg)
    return _run(pytest_command, environment=environment)


if __name__ == '__main__':
    raise SystemExit(main())