#!/usr/bin/env python3
# test_chat_evidence_ledger.py
"""
Functional test for the generic chat result and evidence ledger.
Version: 0.250.063
Implemented in: 0.250.059

This test ensures orchestration evidence remains output-neutral, provenance-aware,
permission-aware, safely compacted, and explicit about unsupported or failed evidence.
"""

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
ROUTE_BACKEND_CHATS = SINGLE_APP_ROOT / 'route_backend_chats.py'
sys.path.insert(0, str(SINGLE_APP_ROOT))

from functions_chat_orchestration import build_turn_orchestration_plan  # noqa: E402
from functions_evidence_ledger import (  # noqa: E402
    EVIDENCE_LEDGER_GUIDANCE_MARKER,
    add_artifact,
    add_citation,
    add_conflict,
    add_evidence_requirement,
    add_evidence_source,
    add_execution_failure,
    add_fact,
    add_missing_evidence,
    add_result,
    build_evidence_ledger_guidance_message,
    compact_evidence_ledger_for_model,
    create_evidence_ledger,
    create_evidence_ledger_from_plan,
)


def _assert_raises(expected_exception, callback):
    try:
        callback()
    except expected_exception:
        return
    raise AssertionError(f'Expected {expected_exception.__name__}')


def test_plan_initializes_output_neutral_ledger():
    plan = build_turn_orchestration_plan(
        'Create a whiteboard sketch grounded in my public LinkedIn profile.',
        run_id='run-plan-ledger',
        conversation_id='conversation-1',
        web_search_enabled=True,
        image_generation_available=True,
    )

    ledger = create_evidence_ledger_from_plan(
        plan,
        user_message_id='message-1',
        created_at='2026-07-14T00:00:00+00:00',
    )

    assert ledger['run_id'] == plan['run_id']
    assert ledger['task_profile'] == 'grounded_image_generation'
    assert ledger['requested_output'] == {
        'type': 'image_proposal',
        'task_type': 'image_generation',
    }
    assert ledger['requirements'] == [{
        'id': 'public_web',
        'description': 'Public web',
        'source_types': [
            'public_web',
            'web_search',
            'url_access',
            'source_review',
            'deep_research',
        ],
        'required': True,
        'status': 'pending',
    }]
    assert ledger['sources'][0]['id'] == 'web_search'
    assert ledger['sources'][0]['requirement_ids'] == ['public_web']
    assert ledger['facts'] == []
    assert ledger['results'] == []
    json.dumps(ledger)

    discovery_plan = build_turn_orchestration_plan(
        'Create an image grounded in verified facts.',
        run_id='run-evidence-discovery-ledger',
        image_generation_available=True,
    )
    discovery_ledger = create_evidence_ledger_from_plan(
        discovery_plan,
        user_message_id='message-evidence-discovery',
    )
    assert discovery_ledger['sources'][0]['id'] == 'evidence_discovery'
    assert discovery_ledger['sources'][0]['requirement_ids'] == ['unspecified_grounding']


def test_selected_image_evidence_preserves_lineage_without_secrets():
    plan = build_turn_orchestration_plan(
        'Create a portrait using the attached headshot as a reference.',
        run_id='run-selected-image',
        conversation_id='conversation-2',
        selected_image_reference_count=1,
        image_generation_available=True,
    )
    ledger = create_evidence_ledger_from_plan(plan, user_message_id='message-2')

    source = add_evidence_source(
        ledger,
        'selected_image',
        'succeeded',
        source_id='selected_images',
        summary='The selected headshot is available as a visual reference.',
        authorization_status='authorized',
        metadata={
            'mime_type': 'image/png',
            'access_token': 'must-not-survive',
            'binary_preview': b'not-model-context',
        },
        raw_metadata={
            'vision_payload': {'api_key': 'must-not-survive'},
        },
    )
    citation = add_citation(
        ledger,
        source['id'],
        citation_id='citation-headshot',
        title='Selected headshot',
        uri='https://example.test/headshot.png?sig=private-token',
        locator='selected image',
    )
    artifact = add_artifact(
        ledger,
        'image_reference',
        artifact_id='artifact-headshot',
        name='Headshot reference',
        source_ids=[source['id']],
        reference='/artifacts/headshot?sig=private-token#fragment',
    )
    fact = add_fact(
        ledger,
        'The selected image is a head-and-shoulders portrait.',
        [source['id']],
        requirement_ids=['selected_images'],
    )
    result = add_result(
        ledger,
        'visual_reference_summary',
        'One authorized portrait reference is ready for finalization.',
        source_ids=[source['id']],
        requirement_ids=['selected_images'],
        citation_ids=[citation['id']],
        artifact_ids=[artifact['id']],
    )

    serialized = json.dumps(ledger)
    assert ledger['requirements'][0]['status'] == 'satisfied'
    assert source['citation_ids'] == ['citation-headshot']
    assert source['artifact_ids'] == ['artifact-headshot']
    assert fact['source_ids'] == ['selected_images']
    assert result['artifact_ids'] == ['artifact-headshot']
    assert citation['uri'] == 'https://example.test/headshot.png'
    assert artifact['reference'] == '/artifacts/headshot'
    assert 'must-not-survive' not in serialized
    assert 'not-model-context' not in serialized


def test_missing_public_evidence_and_unsupported_facts_stay_separate():
    plan = build_turn_orchestration_plan(
        'Summarize my public LinkedIn profile.',
        run_id='run-missing-public-profile',
        conversation_id='conversation-3',
    )
    ledger = create_evidence_ledger_from_plan(plan, user_message_id='message-3')
    source = add_evidence_source(
        ledger,
        'public_web',
        'not_found',
        source_id='public_web',
        summary='No verified matching profile was found.',
        authorization_status='not_required',
    )
    add_missing_evidence(
        ledger,
        'public_web',
        'public_web',
        'not_found',
        'No verified LinkedIn profile was found.',
        source_id=source['id'],
    )
    unsupported = add_fact(
        ledger,
        'The user is a product executive.',
        [],
        requirement_ids=['public_web'],
        confidence='unsupported',
    )

    assert ledger['requirements'][0]['status'] == 'unsatisfied'
    assert ledger['facts'] == []
    assert ledger['unsupported_facts'] == [unsupported]
    assert ledger['missing_or_failed'][0]['kind'] == 'missing_evidence'
    guidance = build_evidence_ledger_guidance_message(ledger)
    assert EVIDENCE_LEDGER_GUIDANCE_MARKER in guidance
    assert 'Do not present unsupported_facts as factual content' in guidance
    assert 'No verified LinkedIn profile was found.' in guidance


def test_execution_failure_updates_permission_aware_source_state():
    plan = build_turn_orchestration_plan(
        'Use the selected agent to gather profile evidence.',
        run_id='run-agent-denied',
        selected_agent={'id': 'agent-1'},
    )
    ledger = create_evidence_ledger_from_plan(plan, user_message_id='message-4')

    failure = add_execution_failure(
        ledger,
        'selected_agent',
        'unauthorized',
        'The selected agent could not access the requested profile data.',
        source_id='selected_agent',
        step_id='collect_selected_agent',
    )

    assert failure['kind'] == 'execution_failure'
    assert ledger['sources'][0]['status'] == 'unauthorized'
    assert ledger['sources'][0]['authorization_status'] == 'denied'
    _assert_raises(
        ValueError,
        lambda: add_fact(
            ledger,
            'Denied profile content must not become a supported fact.',
            ['selected_agent'],
        ),
    )


def test_conflicts_preserve_both_supported_sources():
    ledger = create_evidence_ledger(
        'answer',
        'conversation-5',
        'message-5',
        {'type': 'response'},
        run_id='run-conflict',
    )
    add_evidence_source(
        ledger,
        'workspace_search',
        'succeeded',
        source_id='workspace-search-1',
        authorization_status='authorized',
    )
    add_evidence_source(
        ledger,
        'web_search',
        'succeeded',
        source_id='web-search-1',
        authorization_status='not_required',
    )
    workspace_fact = add_fact(
        ledger,
        'The launch date is August 1.',
        ['workspace-search-1'],
        fact_id='fact-workspace-date',
    )
    web_fact = add_fact(
        ledger,
        'The launch date is August 15.',
        ['web-search-1'],
        fact_id='fact-web-date',
    )
    conflict = add_conflict(
        ledger,
        'The workspace and public source report different launch dates.',
        ['workspace-search-1', 'web-search-1'],
        fact_ids=[workspace_fact['id'], web_fact['id']],
    )

    assert conflict['status'] == 'unresolved'
    assert len(ledger['facts']) == 2
    assert conflict['source_ids'] == ['workspace-search-1', 'web-search-1']


def test_compaction_is_bounded_valid_json_and_omits_sensitive_payloads():
    ledger = create_evidence_ledger(
        'report',
        'conversation-6',
        'message-6',
        {'type': 'report'},
        run_id='run-compaction',
    )
    for index in range(20):
        source_id = f'source-{index}'
        add_evidence_source(
            ledger,
            'computed_output',
            'succeeded',
            source_id=source_id,
            summary=f'Computed source {index}: ' + ('evidence ' * 80),
            authorization_status='authorized',
            metadata={
                'row_count': index,
                'api_key': f'secret-{index}',
                'payload': b'binary-data',
            },
            raw_metadata={'connection_string': f'connection-{index}'},
        )
        add_fact(
            ledger,
            f'Computed fact {index}: ' + ('supported detail ' * 80),
            [source_id],
        )

    compact = compact_evidence_ledger_for_model(ledger, max_chars=1800)
    parsed = json.loads(compact)

    assert len(compact) <= 1800
    assert parsed['version'] == 1
    assert parsed['compaction']['truncated'] is True
    assert 'secret-' not in compact
    assert 'connection-' not in compact
    assert 'binary-data' not in compact


def test_compaction_never_retains_dangling_provenance_references():
    ledger = create_evidence_ledger(
        'report',
        'conversation-compact-lineage',
        'message-compact-lineage',
        {'type': 'report'},
        run_id='run-compact-lineage',
    )
    add_evidence_requirement(
        ledger,
        'Use public evidence.',
        ['web_search'],
        requirement_id='public_web',
    )
    for index in range(4):
        add_evidence_source(
            ledger,
            'web_search',
            'succeeded',
            source_id=f'source-{index}',
            summary=f'Source {index}: ' + ('large source summary ' * 80),
            requirement_ids=['public_web'],
            authorization_status='not_required',
        )

    add_evidence_source(
        ledger,
        'web_search',
        'succeeded',
        source_id='source-3',
        citations=[{
            'citation_id': 'citation-3',
            'title': 'Public source',
            'uri': 'https://example.test/source-3?sig=private',
        }],
        artifacts=[{
            'id': 'artifact-3',
            'type': 'source_archive',
            'name': 'Archived source',
        }],
    )
    fact = add_fact(
        ledger,
        'A supported fact from the final source.',
        ['source-3'],
        requirement_ids=['public_web'],
        fact_id='fact-3',
    )
    add_result(
        ledger,
        'report_section',
        'A result linked to the final source.',
        source_ids=['source-3'],
        requirement_ids=['public_web'],
        citation_ids=['citation-3'],
        artifact_ids=['artifact-3'],
        result_id='result-3',
    )
    add_conflict(
        ledger,
        'Two sources disagree about the supported fact.',
        ['source-2', 'source-3'],
        fact_ids=[fact['id'], add_fact(
            ledger,
            'A conflicting fact from the prior source.',
            ['source-2'],
            requirement_ids=['public_web'],
            fact_id='fact-2',
        )['id']],
        conflict_id='conflict-1',
    )
    add_missing_evidence(
        ledger,
        'public_web',
        'web_search',
        'partial',
        'One requested detail was not available.',
        source_id='source-3',
    )

    for max_chars in range(512, 3001, 41):
        compact = json.loads(compact_evidence_ledger_for_model(ledger, max_chars=max_chars))
        retained_ids = {
            section: {entry['id'] for entry in compact.get(section, [])}
            for section in (
                'requirements',
                'sources',
                'facts',
                'citations',
                'artifacts',
            )
        }
        for source in compact.get('sources', []):
            assert set(source['requirement_ids']).issubset(retained_ids['requirements'])
            assert 'citation_ids' not in source
            assert 'artifact_ids' not in source
        for citation in compact.get('citations', []):
            assert citation['source_id'] in retained_ids['sources']
        for artifact in compact.get('artifacts', []):
            assert set(artifact['source_ids']).issubset(retained_ids['sources'])
        for compact_fact in compact.get('facts', []) + compact.get('unsupported_facts', []):
            assert set(compact_fact['source_ids']).issubset(retained_ids['sources'])
            assert set(compact_fact['requirement_ids']).issubset(retained_ids['requirements'])
        for result in compact.get('results', []):
            assert set(result['source_ids']).issubset(retained_ids['sources'])
            assert set(result['requirement_ids']).issubset(retained_ids['requirements'])
            assert set(result['citation_ids']).issubset(retained_ids['citations'])
            assert set(result['artifact_ids']).issubset(retained_ids['artifacts'])
        for conflict in compact.get('conflicts', []):
            assert set(conflict['source_ids']).issubset(retained_ids['sources'])
            assert set(conflict['fact_ids']).issubset(retained_ids['facts'])
            assert set(conflict['requirement_ids']).issubset(retained_ids['requirements'])
        for gap in compact.get('missing_or_failed', []):
            assert not gap.get('source_id') or gap['source_id'] in retained_ids['sources']
            assert set(gap['requirement_ids']).issubset(retained_ids['requirements'])


def test_unknown_provenance_references_are_rejected():
    ledger = create_evidence_ledger(
        'answer',
        'conversation-7',
        'message-7',
        {'type': 'response'},
    )

    _assert_raises(
        ValueError,
        lambda: add_fact(ledger, 'Unsupported provenance reference.', ['missing-source']),
    )
    _assert_raises(
        ValueError,
        lambda: add_result(
            ledger,
            'answer',
            'Unknown citation reference.',
            citation_ids=['missing-citation'],
        ),
    )


def test_supported_chat_paths_persist_one_shared_ledger_per_turn():
    route_source = ROUTE_BACKEND_CHATS.read_text(encoding='utf-8')

    assert 'from functions_evidence_ledger import (' in route_source
    assert '    create_evidence_ledger_from_plan,' in route_source
    assert route_source.count('turn_evidence_ledger = create_evidence_ledger_from_plan(') == 2
    assert route_source.count("user_metadata['evidence_ledger'] = turn_evidence_ledger") >= 4
    assert route_source.count("'evidence_ledger': turn_evidence_ledger,") >= 6
    assert 'conversation_id=conversation_id,\n            user_message_id=user_message_id,' in route_source
    assert 'conversation_id=conversation_id,\n                    user_message_id=user_message_id,' in route_source


if __name__ == '__main__':
    tests = [
        test_plan_initializes_output_neutral_ledger,
        test_selected_image_evidence_preserves_lineage_without_secrets,
        test_missing_public_evidence_and_unsupported_facts_stay_separate,
        test_execution_failure_updates_permission_aware_source_state,
        test_conflicts_preserve_both_supported_sources,
        test_compaction_is_bounded_valid_json_and_omits_sensitive_payloads,
        test_compaction_never_retains_dangling_provenance_references,
        test_unknown_provenance_references_are_rejected,
        test_supported_chat_paths_persist_one_shared_ledger_per_turn,
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