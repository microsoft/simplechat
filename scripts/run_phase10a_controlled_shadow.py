# run_phase10a_controlled_shadow.py
"""Run realistic Phase 10A planner scenarios without executing capabilities."""

import argparse
import ast
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from azure.identity import AzureCliCredential, get_bearer_token_provider
from dotenv import load_dotenv
from openai import AzureOpenAI


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
DEFAULT_MANIFEST_PATH = (
    REPO_ROOT
    / 'functional_tests'
    / 'fixtures'
    / 'phase10a_controlled_shadow_scenarios.json'
)
DEFAULT_RESULT_PATH = (
    REPO_ROOT / 'artifacts' / 'phase10a_controlled_shadow_report.json'
)
DEFAULT_SCOPE = 'https://cognitiveservices.azure.com/.default'
CAPABILITY_IDS = (
    'workspace_search',
    'analyze',
    'compare',
    'image',
    'web_search',
    'url_access',
    'deep_research',
)
INELIGIBLE_STATES = frozenset({
    'unavailable',
    'unauthorized',
    'policy_blocked',
})
INELIGIBLE_CLASSES = frozenset({*CAPABILITY_IDS, 'governed_agent'})
IDENTIFIER_PATTERN = re.compile(r'^[a-z0-9][a-z0-9_:-]{0,127}$')
CONTROLLED_APPLICATION_IMPORTS = {
    'functions_chat_capabilities': frozenset({
        'build_governed_agent_capability_inventory',
        'build_governed_capability_inventory',
    }),
    'functions_chat_capability_planner': frozenset({
        'build_capability_planner_request',
        'invoke_capability_planner',
    }),
}
APPLICATION_MODULE_PREFIXES = ('functions_', 'route_', 'semantic_kernel')

sys.path.insert(0, str(SINGLE_APP_ROOT))

from functions_chat_capabilities import (  # noqa: E402
    build_governed_agent_capability_inventory,
    build_governed_capability_inventory,
)
from functions_chat_capability_planner import (  # noqa: E402
    build_capability_planner_request,
    invoke_capability_planner,
)


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _load_local_environment():
    load_dotenv(SINGLE_APP_ROOT / '.env')


def _read_application_version():
    config_text = (SINGLE_APP_ROOT / 'config.py').read_text(encoding='utf-8')
    match = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', config_text, re.MULTILINE)
    return match.group(1) if match else 'unknown'


def _read_commit():
    completed = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else 'unknown'


def _working_tree_is_dirty():
    completed = subprocess.run(
        ['git', 'status', '--porcelain=v1'],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode != 0 or bool(completed.stdout.strip())


def application_import_violations():
    source = Path(__file__).read_text(encoding='utf-8')
    violations = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(APPLICATION_MODULE_PREFIXES):
                    violations.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if not node.module.startswith(APPLICATION_MODULE_PREFIXES):
                continue
            allowed_names = CONTROLLED_APPLICATION_IMPORTS.get(node.module)
            imported_names = {alias.name for alias in node.names}
            if allowed_names is None or not imported_names.issubset(allowed_names):
                violations.append(node.module)
    return sorted(set(violations))


def non_executing_source_guard_passes():
    return not application_import_violations()


def _safe_fraction(value, field_name):
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{field_name} must be numeric.') from exc
    if normalized < 0 or normalized > 1:
        raise ValueError(f'{field_name} must be between 0 and 1.')
    return normalized


def load_manifest(path):
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or manifest.get('version') != 1:
        raise ValueError('Controlled-shadow manifest version must be 1.')
    scenarios = manifest.get('scenarios')
    thresholds = manifest.get('thresholds')
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError('Controlled-shadow scenarios must be a non-empty list.')
    if not isinstance(thresholds, dict):
        raise ValueError('Controlled-shadow thresholds must be an object.')

    required_thresholds = {
        'minimum_sample_count',
        'minimum_overall_accuracy',
        'minimum_end_to_end_pass_rate',
        'minimum_json_schema_rate',
        'maximum_invalid_output_rate',
        'maximum_operational_failure_rate',
        'maximum_timeout_rate',
        'maximum_false_proposal_rate',
        'maximum_capability_leakage_count',
        'maximum_execution_surface_import_count',
        'maximum_p95_latency_ms',
        'minimum_category_accuracy',
    }
    missing_thresholds = required_thresholds - set(thresholds)
    if missing_thresholds:
        raise ValueError(
            'Controlled-shadow thresholds are missing: '
            + ', '.join(sorted(missing_thresholds))
        )
    for field_name in (
        'minimum_overall_accuracy',
        'minimum_end_to_end_pass_rate',
        'minimum_json_schema_rate',
        'maximum_invalid_output_rate',
        'maximum_operational_failure_rate',
        'maximum_timeout_rate',
        'maximum_false_proposal_rate',
    ):
        _safe_fraction(thresholds[field_name], field_name)
    category_thresholds = thresholds.get('minimum_category_accuracy')
    if not isinstance(category_thresholds, dict) or not category_thresholds:
        raise ValueError('minimum_category_accuracy must be a non-empty object.')
    for category, value in category_thresholds.items():
        if not IDENTIFIER_PATTERN.fullmatch(str(category or '')):
            raise ValueError('Category threshold names must be safe identifiers.')
        _safe_fraction(value, f'minimum_category_accuracy.{category}')

    scenario_ids = set()
    categories = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise ValueError('Every controlled-shadow scenario must be an object.')
        scenario_id = str(scenario.get('id') or '').strip()
        category = str(scenario.get('category') or '').strip()
        user_request = str(scenario.get('user_request') or '').strip()
        if not IDENTIFIER_PATTERN.fullmatch(scenario_id):
            raise ValueError(f'Invalid scenario ID: {scenario_id or "missing"}.')
        if scenario_id in scenario_ids:
            raise ValueError(f'Duplicate scenario ID: {scenario_id}.')
        if not IDENTIFIER_PATTERN.fullmatch(category):
            raise ValueError(f'Invalid scenario category: {scenario_id}.')
        if not user_request or len(user_request) > 16000:
            raise ValueError(f'Invalid user request: {scenario_id}.')
        allowed_decisions = scenario.get('allowed_decisions')
        if not isinstance(allowed_decisions, list) or not allowed_decisions:
            raise ValueError(f'allowed_decisions must be a non-empty list: {scenario_id}.')
        if set(allowed_decisions) - {'direct', 'propose', 'clarify'}:
            raise ValueError(f'Unknown allowed decision: {scenario_id}.')
        for field_name in (
            'allowed_candidate_capability_sets',
            'allowed_reason_codes',
            'forbidden_capabilities',
        ):
            if not isinstance(scenario.get(field_name), list):
                raise ValueError(f'{field_name} must be a list: {scenario_id}.')
        ineligible_class = str(
            scenario.get('ineligible_capability_class') or ''
        ).strip()
        ineligible_state = str(scenario.get('ineligible_state') or '').strip()
        if bool(ineligible_class) != bool(ineligible_state):
            raise ValueError(
                f'Ineligible class and state must be provided together: {scenario_id}.'
            )
        if ineligible_class and ineligible_class not in INELIGIBLE_CLASSES:
            raise ValueError(f'Unknown ineligible capability: {scenario_id}.')
        if ineligible_state and ineligible_state not in INELIGIBLE_STATES:
            raise ValueError(f'Unknown ineligible state: {scenario_id}.')
        scenario_ids.add(scenario_id)
        categories.add(category)

    missing_categories = set(category_thresholds) - categories
    if missing_categories:
        raise ValueError(
            'Category thresholds have no scenarios: '
            + ', '.join(sorted(missing_categories))
        )
    return manifest


def build_scenario_inventory(scenario):
    ineligible_class = str(
        scenario.get('ineligible_capability_class') or ''
    ).strip()
    ineligible_state = str(scenario.get('ineligible_state') or '').strip()
    resolved_capabilities = {
        capability_id: {
            'enabled': True,
            'available': True,
            'authorized': True,
            'governance_mode': 'recommend',
            'input_ready': (
                capability_id not in {'analyze', 'compare', 'url_access'}
                or capability_id in set(
                    scenario.get('input_ready_capabilities') or []
                )
            ),
        }
        for capability_id in CAPABILITY_IDS
    }
    if ineligible_class in resolved_capabilities:
        capability = resolved_capabilities[ineligible_class]
        if ineligible_state == 'unavailable':
            capability['available'] = False
        elif ineligible_state == 'unauthorized':
            capability['authorized'] = False
        elif ineligible_state == 'policy_blocked':
            capability['governance_mode'] = 'blocked'

    inventory = build_governed_capability_inventory(
        selected_capability_ids=scenario.get('selected_capabilities') or [],
        resolved_capabilities=resolved_capabilities,
    )
    inventory['agents'] = []
    agent_is_eligible = not (
        ineligible_class == 'governed_agent'
        and ineligible_state in INELIGIBLE_STATES
    )
    if agent_is_eligible:
        inventory['agents'] = build_governed_agent_capability_inventory(
            [
                {
                    'catalog_key': 'personal:user:benefits-research',
                    'created_at': '2026-07-15T12:00:00+00:00',
                    'display_name': 'Benefits Research',
                    'discoverable_by_orchestrator': True,
                    'orchestrator_descriptor': {
                        'capability_tags': ['benefits', 'policy_lookup'],
                        'evidence_types': [
                            'employee_benefits',
                            'policy_documents',
                        ],
                        'read_only': True,
                        'external_data': False,
                        'risk_class': 'internal_read',
                        'data_sensitivity': 'internal',
                        'latency_class': 'seconds',
                        'cost_class': 'standard',
                    },
                }
            ],
            reference_secret='phase-10a-controlled-shadow-secret',
        )['agents']
    return inventory


def _capability_class(capability_id):
    normalized = str(capability_id or '').strip()
    if normalized == 'selected_agent' or normalized.startswith('agent:'):
        return 'governed_agent'
    return normalized


def _normalized_capability_set(capability_ids):
    return tuple(sorted({
        _capability_class(capability_id)
        for capability_id in capability_ids or []
        if _capability_class(capability_id)
    }))


def _candidate_sets(result):
    return [
        _normalized_capability_set(candidate.get('capability_ids'))
        for candidate in result.get('candidate_plans') or []
        if isinstance(candidate, dict)
    ]


def _recommended_set(result):
    recommended_id = str(result.get('recommended_plan_id') or '').strip()
    for candidate in result.get('candidate_plans') or []:
        if (
            isinstance(candidate, dict)
            and str(candidate.get('id') or '').strip() == recommended_id
        ):
            return _normalized_capability_set(candidate.get('capability_ids'))
    return ()


def score_scenario(scenario, planner_request, result, repetition):
    status = str(result.get('status') or '').strip()
    decision = str(result.get('decision') or '').strip()
    candidate_sets = _candidate_sets(result)
    recommended_set = _recommended_set(result)
    allowed_candidate_sets = {
        _normalized_capability_set(capability_ids)
        for capability_ids in scenario['allowed_candidate_capability_sets']
    }
    allowed_recommended_sets = {
        _normalized_capability_set(capability_ids)
        for capability_ids in scenario.get(
            'allowed_recommended_capability_sets',
            scenario['allowed_candidate_capability_sets'],
        )
    }
    actual_reason_codes = {
        str(requirement.get('reason_code') or '').strip()
        for requirement in result.get('requirements') or []
        if isinstance(requirement, dict)
    } | {
        str(candidate.get('reason_code') or '').strip()
        for candidate in result.get('candidate_plans') or []
        if isinstance(candidate, dict)
    }
    actual_reason_codes.discard('')
    allowed_reason_codes = set(scenario['allowed_reason_codes'])
    proposed_classes = {
        capability_class
        for capability_set in candidate_sets
        for capability_class in capability_set
    }
    forbidden_classes = set(scenario['forbidden_capabilities'])
    request_classes = {
        _capability_class(capability.get('id'))
        for capability in planner_request.get('available_capabilities') or []
        if isinstance(capability, dict)
    }
    decision_matches = decision in scenario['allowed_decisions']
    if decision == 'propose':
        candidates_match = bool(candidate_sets) and all(
            capability_set in allowed_candidate_sets
            for capability_set in candidate_sets
        )
        recommended_matches = (
            bool(recommended_set)
            and recommended_set in allowed_recommended_sets
        )
    else:
        candidates_match = not candidate_sets
        recommended_matches = not recommended_set
    reason_codes_match = actual_reason_codes.issubset(allowed_reason_codes)
    forbidden_output_count = len(forbidden_classes & proposed_classes)
    inventory_leakage_count = (
        len(forbidden_classes & request_classes)
        if scenario.get('ineligible_capability_class')
        else 0
    )
    passed = all((
        status == 'valid',
        decision_matches,
        candidates_match,
        recommended_matches,
        reason_codes_match,
        forbidden_output_count == 0,
        inventory_leakage_count == 0,
    ))
    return {
        'scenario_id': scenario['id'],
        'category': scenario['category'],
        'repetition': repetition,
        'status': status,
        'decision': decision,
        'candidate_capability_classes': [list(value) for value in candidate_sets],
        'recommended_capability_classes': list(recommended_set),
        'reason_codes': sorted(actual_reason_codes),
        'latency_ms': int(result.get('latency_ms') or 0),
        'fallback_used': bool(result.get('fallback_used')),
        'failure_code': str(result.get('failure_code') or '').strip(),
        'response_format_class': str(
            result.get('response_format_class') or 'none'
        ).strip(),
        'decision_matches': decision_matches,
        'candidates_match': candidates_match,
        'recommended_matches': recommended_matches,
        'reason_codes_match': reason_codes_match,
        'forbidden_output_count': forbidden_output_count,
        'inventory_leakage_count': inventory_leakage_count,
        'passed': passed,
    }


def _percentile(values, percentile):
    ordered = sorted(int(value) for value in values)
    if not ordered:
        return 0
    position = (len(ordered) - 1) * percentile
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    return round(
        ordered[lower_index]
        + (ordered[upper_index] - ordered[lower_index])
        * (position - lower_index)
    )


def build_summary(rows, thresholds, *, partial=False):
    total = len(rows)
    if not total:
        raise ValueError('Controlled-shadow evaluation produced no rows.')
    passed = sum(1 for row in rows if row['passed'])
    category_rows = defaultdict(list)
    for row in rows:
        category_rows[row['category']].append(row)
    category_accuracy = {}
    for category, entries in sorted(category_rows.items()):
        valid_entries = [row for row in entries if row['status'] == 'valid']
        category_accuracy[category] = (
            round(
                sum(1 for row in valid_entries if row['passed'])
                / len(valid_entries),
                4,
            )
            if valid_entries
            else 0
        )
    statuses = Counter(row['status'] for row in rows)
    failure_codes = Counter(
        row['failure_code'] for row in rows if row['failure_code']
    )
    response_format_counts = Counter(
        row.get('response_format_class') or 'none'
        for row in rows
        if row['status'] == 'valid'
    )
    invalid_output_count = sum(
        1
        for row in rows
        if row['status'] == 'rejected'
        and row['failure_code'] not in {
            'client_error',
            'content_filtered',
            'model_unavailable',
            'refused',
            'transport_unsupported',
        }
    )
    operational_failure_count = sum(
        1
        for row in rows
        if row['status'] not in {'valid', 'timed_out'}
        and not (
            row['status'] == 'rejected'
            and row['failure_code'] not in {
                'client_error',
                'content_filtered',
                'model_unavailable',
                'refused',
                'transport_unsupported',
            }
        )
    )
    timeout_count = statuses.get('timed_out', 0)
    simple_rows = category_rows.get('simple_direct', [])
    false_proposal_count = sum(
        row['decision'] == 'propose' for row in simple_rows
    )
    capability_leakage_count = sum(
        row['forbidden_output_count'] + row['inventory_leakage_count']
        for row in rows
    )
    execution_surface_import_count = len(application_import_violations())
    latencies = [row['latency_ms'] for row in rows]
    category_thresholds = thresholds['minimum_category_accuracy']
    applicable_category_thresholds = {
        category: float(category_thresholds[category])
        for category in category_accuracy
        if category in category_thresholds
    }
    valid_count = statuses.get('valid', 0)
    overall_accuracy = passed / valid_count if valid_count else 0
    end_to_end_pass_rate = passed / total
    json_schema_rate = (
        response_format_counts.get('json_schema', 0) / valid_count
        if valid_count
        else 0
    )
    invalid_output_rate = invalid_output_count / total
    operational_failure_rate = operational_failure_count / total
    timeout_rate = timeout_count / total
    false_proposal_rate = (
        false_proposal_count / len(simple_rows) if simple_rows else 0
    )
    p95_latency_ms = _percentile(latencies, 0.95)
    threshold_results = {
        'sample_count': (
            True
            if partial
            else total >= int(thresholds['minimum_sample_count'])
        ),
        'overall_accuracy': (
            overall_accuracy >= float(thresholds['minimum_overall_accuracy'])
        ),
        'end_to_end_pass_rate': (
            end_to_end_pass_rate
            >= float(thresholds['minimum_end_to_end_pass_rate'])
        ),
        'json_schema_rate': (
            json_schema_rate >= float(thresholds['minimum_json_schema_rate'])
        ),
        'category_accuracy': all(
            category_accuracy[category] >= minimum
            for category, minimum in applicable_category_thresholds.items()
        ),
        'invalid_output_rate': (
            invalid_output_rate <= float(thresholds['maximum_invalid_output_rate'])
        ),
        'operational_failure_rate': (
            operational_failure_rate
            <= float(thresholds['maximum_operational_failure_rate'])
        ),
        'timeout_rate': (
            timeout_rate <= float(thresholds['maximum_timeout_rate'])
        ),
        'false_proposal_rate': (
            false_proposal_rate <= float(thresholds['maximum_false_proposal_rate'])
        ),
        'capability_leakage': (
            capability_leakage_count
            <= int(thresholds['maximum_capability_leakage_count'])
        ),
        'execution_surfaces': (
            execution_surface_import_count
            <= int(thresholds['maximum_execution_surface_import_count'])
        ),
        'p95_latency': (
            p95_latency_ms <= int(thresholds['maximum_p95_latency_ms'])
        ),
    }
    return {
        'sample_count': total,
        'valid_count': valid_count,
        'passed_count': passed,
        'overall_accuracy': round(overall_accuracy, 4),
        'end_to_end_pass_rate': round(end_to_end_pass_rate, 4),
        'json_schema_rate': round(json_schema_rate, 4),
        'category_accuracy': category_accuracy,
        'status_counts': dict(sorted(statuses.items())),
        'failure_code_counts': dict(sorted(failure_codes.items())),
        'response_format_counts': dict(sorted(response_format_counts.items())),
        'invalid_output_count': invalid_output_count,
        'invalid_output_rate': round(invalid_output_rate, 4),
        'operational_failure_count': operational_failure_count,
        'operational_failure_rate': round(operational_failure_rate, 4),
        'timeout_count': timeout_count,
        'timeout_rate': round(timeout_rate, 4),
        'false_proposal_count': false_proposal_count,
        'false_proposal_rate': round(false_proposal_rate, 4),
        'capability_leakage_count': capability_leakage_count,
        'execution_surface_import_count': execution_surface_import_count,
        'latency_ms': {
            'minimum': min(latencies),
            'p50': _percentile(latencies, 0.5),
            'p95': p95_latency_ms,
            'maximum': max(latencies),
        },
        'threshold_results': threshold_results,
        'accepted': all(threshold_results.values()),
    }


def _content_hash(content):
    return hashlib.sha256(content).hexdigest()[:16]


def _evaluation_source_hash(manifest):
    digest = hashlib.sha256()
    for path in (
        SINGLE_APP_ROOT / 'functions_chat_capabilities.py',
        SINGLE_APP_ROOT / 'functions_chat_capability_planner.py',
        SINGLE_APP_ROOT / 'functions_chat_orchestration.py',
        SINGLE_APP_ROOT / 'functions_settings.py',
        Path(__file__).resolve(),
    ):
        digest.update(path.relative_to(REPO_ROOT).as_posix().encode('utf-8'))
        digest.update(path.read_bytes())
    digest.update(
        json.dumps(
            manifest,
            ensure_ascii=True,
            separators=(',', ':'),
            sort_keys=True,
        ).encode('utf-8')
    )
    return digest.hexdigest()[:16]


def build_report(rows, manifest, *, auth_class, timeout_ms, partial):
    serialized_manifest = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')
    return {
        'schema_version': 1,
        'generated_at': _utc_now(),
        'application_version': _read_application_version(),
        'commit': _read_commit(),
        'working_tree_dirty': _working_tree_is_dirty(),
        'manifest_version': manifest['version'],
        'manifest_hash': _content_hash(serialized_manifest),
        'evaluation_source_hash': _evaluation_source_hash(manifest),
        'provider_class': 'azure_openai',
        'model_class': 'gpt',
        'authentication_class': auth_class,
        'timeout_ms': timeout_ms,
        'non_executing': True,
        'non_executing_source_guard': non_executing_source_guard_passes(),
        'prompts_persisted': False,
        'raw_responses_persisted': False,
        'partial': partial,
        'thresholds': manifest['thresholds'],
        'summary': build_summary(
            rows,
            manifest['thresholds'],
            partial=partial,
        ),
        'rows': rows,
    }


def _build_client(args):
    if args.auth == 'api_key':
        api_key = os.getenv(args.api_key_env, '').strip()
        if not api_key:
            raise ValueError(
                f'API-key authentication requires {args.api_key_env}.'
            )
        return AzureOpenAI(
            api_version=args.api_version,
            azure_endpoint=args.endpoint,
            api_key=api_key,
        ), 'api_key'
    credential = AzureCliCredential()
    token_provider = get_bearer_token_provider(credential, args.scope)
    return AzureOpenAI(
        api_version=args.api_version,
        azure_endpoint=args.endpoint,
        azure_ad_token_provider=token_provider,
    ), 'azure_cli'


def _build_argument_parser():
    parser = argparse.ArgumentParser(
        description=(
            'Run realistic Phase 10A controlled-shadow planner scenarios. '
            'This command never executes a capability.'
        ),
    )
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument('--output', type=Path, default=DEFAULT_RESULT_PATH)
    parser.add_argument(
        '--endpoint',
        default=os.getenv('SIMPLECHAT_PHASE10A_SHADOW_ENDPOINT', '').strip(),
    )
    parser.add_argument(
        '--deployment',
        default=os.getenv('SIMPLECHAT_PHASE10A_SHADOW_DEPLOYMENT', '').strip(),
    )
    parser.add_argument(
        '--api-version',
        default=os.getenv(
            'SIMPLECHAT_PHASE10A_SHADOW_API_VERSION',
            '2024-10-21',
        ).strip(),
    )
    parser.add_argument(
        '--timeout-ms',
        type=int,
        default=int(os.getenv('SIMPLECHAT_PHASE10A_SHADOW_TIMEOUT_MS', '5000')),
    )
    parser.add_argument(
        '--max-completion-tokens',
        type=int,
        default=int(os.getenv(
            'SIMPLECHAT_PHASE10A_SHADOW_MAX_COMPLETION_TOKENS',
            '600',
        )),
    )
    parser.add_argument(
        '--auth',
        choices=('azure_cli', 'api_key'),
        default='azure_cli',
    )
    parser.add_argument(
        '--api-key-env',
        default='SIMPLECHAT_PHASE10A_SHADOW_ENDPOINT_KEY',
    )
    parser.add_argument('--scope', default=DEFAULT_SCOPE)
    parser.add_argument('--repetitions', type=int, default=1)
    parser.add_argument('--scenario', action='append', default=[])
    parser.add_argument('--allow-partial', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    return parser


def main(argv=None):
    _load_local_environment()
    args = _build_argument_parser().parse_args(argv)
    manifest = load_manifest(args.manifest)
    if not non_executing_source_guard_passes():
        raise RuntimeError(
            'Controlled-shadow runner imported a prohibited execution surface.'
        )
    scenarios = manifest['scenarios']
    if args.scenario:
        requested_ids = set(args.scenario)
        available_ids = {scenario['id'] for scenario in scenarios}
        unknown_ids = requested_ids - available_ids
        if unknown_ids:
            raise ValueError(
                'Unknown scenarios: ' + ', '.join(sorted(unknown_ids))
            )
        scenarios = [
            scenario for scenario in scenarios if scenario['id'] in requested_ids
        ]
    if args.repetitions < 1 or args.repetitions > 10:
        raise ValueError('repetitions must be between 1 and 10.')
    if args.timeout_ms < 250 or args.timeout_ms > 10000:
        raise ValueError('timeout-ms must be between 250 and 10000.')
    if args.dry_run:
        print(f'Validated {len(scenarios)} controlled-shadow scenarios:')
        for scenario in scenarios:
            print(f'  {scenario["id"]} ({scenario["category"]})')
        return 0
    parsed_endpoint = urlparse(args.endpoint)
    if parsed_endpoint.scheme != 'https' or not parsed_endpoint.netloc:
        raise ValueError('A valid HTTPS planner endpoint is required.')
    if not args.deployment:
        raise ValueError('A planner deployment is required.')

    planner_client, auth_class = _build_client(args)
    rows = []
    total = len(scenarios) * args.repetitions
    sequence = 0
    for repetition in range(1, args.repetitions + 1):
        for scenario in scenarios:
            sequence += 1
            inventory = build_scenario_inventory(scenario)
            planner_request = build_capability_planner_request(
                scenario['user_request'],
                inventory,
            )
            result = invoke_capability_planner(
                planner_client=planner_client,
                planner_model=args.deployment,
                planner_request=planner_request,
                runtime_protocol='azure_openai',
                timeout_ms=args.timeout_ms,
                max_completion_tokens=args.max_completion_tokens,
            )
            scored = score_scenario(
                scenario,
                planner_request,
                result,
                repetition,
            )
            rows.append(scored)
            outcome = 'PASS' if scored['passed'] else 'FAIL'
            print(
                f'[{sequence:03d}/{total:03d}] {outcome} '
                f'{scenario["id"]} status={scored["status"]} '
                f'decision={scored["decision"] or "none"} '
                f'latency_ms={scored["latency_ms"]}'
            )

    partial = bool(args.scenario) or args.allow_partial
    report = build_report(
        rows,
        manifest,
        auth_class=auth_class,
        timeout_ms=args.timeout_ms,
        partial=partial,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding='utf-8',
    )
    print(json.dumps(report['summary'], indent=2, sort_keys=True))
    print(f'Report: {args.output.resolve()}')
    return 0 if report['summary']['accepted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())