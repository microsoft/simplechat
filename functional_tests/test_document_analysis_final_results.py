# test_document_analysis_final_results.py
"""
Functional tests for the built-in narrative Analyze producer.
Version: 0.261.109
Implemented in: 0.261.109

Exercise the real source resolution, windowing, retry, cancellation and producer
functions with original narrative documents and deterministic SDK responses.
No Azure resources, generated code or already-final result fixtures are used.
"""

import hashlib
import json
from copy import deepcopy

import pytest

from test_support.app_stubs import import_app_module
from test_support.document_analysis import (
    USER_ID,
    FixtureAnalysisClient,
    document_analysis_runtime,
    extract_fixture_findings,
    original_document,
)
from test_support.versioning import assert_app_version_at_least


def run_analysis(runtime, documents, client=None, **options):
    client = client or FixtureAnalysisClient()
    arguments = {
        'user_id': USER_ID,
        'analysis_prompt': 'Explain the risks in these documents.',
        'document_ids': list(documents),
        'invoke_prompt': client.invoke_prompt,
        'doc_scope': 'all',
        'window_size': 1,
        'max_documents': max(10, len(documents)),
        'max_retries_per_window': 0,
        'result_version': 'analyze-final-v1',
    }
    arguments.update(options)
    return runtime.producer.run_document_analysis(**arguments), client


def source_manifest_for(documents):
    sources = []
    for document_id, fixture in documents.items():
        document = fixture['document']
        sources.append({
            'document_id': document_id,
            'scope': document['scope'],
            'scope_id': document.get('group_id') or document.get('public_workspace_id') or document['user_id'],
            'source_version': document.get('version'),
            'source_revision': document.get('_etag'),
            'authorization_status': 'authorized',
        })
    return sources


@pytest.mark.parametrize('source_count', [1, 10, 100, 300, 500])
def test_narrative_scale_accounts_for_original_sources_without_collection_model_calls(source_count, monkeypatch):
    documents = {
        f'contract-{index}': original_document(
            f'contract-{index}', [f'Contract {index} relies on a sole supplier for replacement parts.'],
        )
        for index in range(1, source_count + 1)
    }
    with document_analysis_runtime(documents) as runtime:
        def legacy_intent_must_not_run(*args, **kwargs):
            raise AssertionError('The new mode must not use phrase-based collection preservation.')

        monkeypatch.setattr(runtime.producer, '_build_analysis_intent', legacy_intent_must_not_run)
        events = []
        result, client = run_analysis(
            runtime, documents, activity_callback=events.append,
            max_documents=3 if source_count == 1 else source_count,
        )
        records = result['authoritative_result']['value']
        validation = result['analysis_validation']
        coverage = validation['coverage']
        assert result['analysis_result_version'] == 'analyze-final-v1'
        assert result['authoritative_result']['kind'] == 'records'
        assert validation['status'] == 'valid'
        assert len(records) == source_count
        assert len({record['record_id'] for record in records}) == source_count
        assert coverage['assigned_sources'] == coverage['completed_sources'] == source_count
        assert coverage['assigned_work_units'] == coverage['completed_work_units'] == source_count
        assert coverage['failed_work_units'] == coverage['pending_work_units'] == 0
        assert len(runtime.source_reads) == source_count * 2
        assert len(client.calls) == source_count
        assert {call['stage'] for call in client.calls} == {'window_analysis'}
        assert all(call['metadata']['assigned_document_ids'] == [call['metadata']['document_id']] for call in client.calls)
        assert max(len(call['prompt']) for call in client.calls) < 4000
        assert result['analysis_metrics']['model_calls'] == {
            'planning': 0, 'extraction': source_count, 'local_consolidation': 0,
            'reporting': 0, 'retries': 0, 'total': source_count,
        }
        durations = result['analysis_metrics']['durations_ms']
        assert all(value >= 0 for value in durations.values())
        assert durations['total'] >= max(durations.values())
        assert result['analysis_metrics']['provider_internal_calls'] == 'unobserved'
        evidence = {item['evidence_id']: item for item in result['analysis_evidence']}
        for record in records:
            original = documents[record['document_id']]
            assert record['source']['file_name'] == original['document']['file_name']
            assert record['source']['source_version'] == 1
            assert record['source']['source_revision'].startswith('sha256-')
            assert record['values'] == {
                'finding': 'Single-supplier dependency',
                'explanation': 'An interruption at the sole supplier could delay service delivery.',
            }
            passage = evidence[record['evidence_refs'][0]]
            location = passage['location']
            assert passage['source'] == record['source']
            assert original['chunks'][0]['chunk_text'][location['start_char']:location['end_char']] == passage['text']
        assert result['reply'] == result['analysis_reply']
        assert 'Single-supplier dependency' in result['analysis_reply']
        assert '"finding_key"' not in result['analysis_reply']
        assert '<DocumentSlice>' not in result['analysis_reply']
        assert len(result['raw_analysis_items']) == source_count
        assert events[-1]['progress']['overall']['percent'] == 97
        assert events[-1]['progress']['overall']['status'] == 'running'
        assert events[-1]['progress']['overall']['phase'] == 'ready_to_save'
        assert all(
            event['progress']['overall']['percent'] < 100
            for event in events if event['type'] != 'reduction_completed'
        )
        assert {'consolidation_started', 'reporting_started'} <= {event['type'] for event in events}


def test_complementary_windows_merge_values_and_keep_both_passages_without_reduction():
    documents = {'oversight': original_document('oversight', [
        'The service owner is Mira.',
        'Reviews take place every quarter.',
    ])}
    with document_analysis_runtime(documents) as runtime:
        result, client = run_analysis(runtime, documents, max_reduction_rounds=1)
        records = result['authoritative_result']['value']
        assert len(records) == 1
        assert records[0]['values'] == {'owner': 'Mira', 'review_frequency': 'quarterly'}
        assert len(records[0]['evidence_refs']) == 2
        assert len(client.calls) == 2
        assert result['coverage']['processed_windows'] == 2
        assert result['analysis_validation']['coverage']['completed_sources'] == 1
        assert all(item['resolution'] == 'accepted' for item in result['analysis_diagnostics']['candidates'])


def test_zero_or_multiple_findings_are_not_missing_source_coverage():
    documents = {
        'schedule': original_document('schedule', ['The equipment schedule lists blue desks.']),
        'supplier': original_document('supplier', [
            'The contract depends on a sole supplier.',
            'An exit penalty applies to early cancellation.',
        ]),
        'renewal': original_document('renewal', [
            'The renewal depends on a sole supplier.',
            'The renewal depends on a sole supplier.',
        ]),
    }
    with document_analysis_runtime(documents) as runtime:
        result, client = run_analysis(runtime, documents)
        assert len(result['authoritative_result']['value']) == 3
        assert len(client.calls) == 5
        assert result['analysis_validation']['status'] == 'valid'
        coverage = result['analysis_validation']['coverage']
        assert coverage['completed_sources'] == 3
        assert coverage['completed_work_units'] == 5
        assert all(source['status'] == 'complete' for source in coverage['sources'])
        assert result['analysis_validation']['issues'] == []
        assert result['analysis_sources'][0]['file_name'] == 'schedule.txt'
        assert 'schedule.txt: 1/1 windows processed' in result['analysis_reply']
        assert all(
            unit['document_id'] in documents and unit['source']['document_id'] == unit['document_id']
            for unit in coverage['work_units']
        )


def test_empty_findings_are_a_successful_empty_result_not_an_extraction_failure():
    documents = {'schedule': original_document('schedule', ['The equipment schedule lists blue desks.'])}
    with document_analysis_runtime(documents) as runtime:
        result, client = run_analysis(runtime, documents)
        assert result['authoritative_result'] == {'kind': 'records', 'value': []}
        assert result['analysis_validation']['status'] == 'valid'
        assert result['analysis_validation']['coverage']['completed_sources'] == 1
        assert result['analysis_evidence'] == []
        assert runtime.results.get_document_analysis_export_rows(result) == []
        assert 'No finalized findings' in result['analysis_reply']
        assert len(client.calls) == 1


def test_unpaged_original_chunks_are_not_lost_by_page_windowing():
    documents = {'supplier': original_document('supplier', [
        'The agreement names a sole supplier.',
        'An exit penalty applies to early cancellation.',
    ])}
    documents['supplier']['chunks'][1]['page_number'] = None
    with document_analysis_runtime(documents) as runtime:
        result, client = run_analysis(runtime, documents)
        assert len(client.calls) == 2
        assert len(result['authoritative_result']['value']) == 2
        assert result['coverage']['processed_chunks'] == result['coverage']['total_chunks'] == 2
        assert result['analysis_validation']['coverage']['status'] == 'complete'
        assert {item['location']['chunk_sequence'] for item in result['analysis_evidence']} == {1, 2}


def test_conflicts_remain_provisional_even_after_every_window_completes():
    documents = {
        'notice': original_document('notice', [
            'Required termination notice is 30 days.',
            'Required termination notice is 90 days.',
        ]),
        'supplier': original_document('supplier', ['There is a sole supplier for this service.']),
    }
    with document_analysis_runtime(documents) as runtime:
        result, client = run_analysis(runtime, documents)
        records = result['authoritative_result']['value']
        assert [record['document_id'] for record in records] == ['supplier']
        assert result['analysis_validation']['status'] == 'partial'
        assert result['analysis_validation']['coverage']['status'] == 'complete'
        assert result['analysis_validation']['unresolved_candidate_count'] == 2
        provisional = [
            candidate for candidate in result['analysis_diagnostics']['candidates']
            if candidate['resolution'] == 'unresolved'
        ]
        assert {candidate['values']['notice_days'] for candidate in provisional} == {30, 90}
        assert len({candidate['record_id'] for candidate in provisional}) == 1
        assert len(result['analysis_evidence']) == 3
        assert any(issue['code'] == 'conflicting_values' for issue in result['analysis_validation']['issues'])
        assert 'notice_days' not in runtime.results.get_document_analysis_export_rows(result)[0]
        assert 'Partial' in result['analysis_reply']
        assert 'Source windows disagree' in result['analysis_reply']
        assert len(client.calls) == 3


def test_duplicate_candidates_and_window_replays_are_idempotent(monkeypatch):
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    with document_analysis_runtime(documents) as runtime:
        original_builder = runtime.search.build_document_chunk_windows

        def replay_window(*args, **kwargs):
            windows = original_builder(*args, **kwargs)
            return windows + deepcopy(windows)

        def repeated_candidate(prompt):
            payload = json.loads(extract_fixture_findings(prompt))
            payload['findings'] *= 2
            return json.dumps(payload)

        monkeypatch.setattr(runtime.search, 'build_document_chunk_windows', replay_window)
        result, client = run_analysis(runtime, documents, FixtureAnalysisClient(repeated_candidate))
        assert len(client.calls) == 1
        assert result['coverage']['total_windows'] == result['coverage']['processed_windows'] == 1
        assert len(result['authoritative_result']['value']) == 1
        assert len(result['analysis_diagnostics']['candidates']) == 1
        assert len(result['analysis_evidence']) == 1
        replayed = runtime.results.finalize_document_analysis_result(
            result['analysis_sources'],
            result['analysis_validation']['coverage']['work_units'] * 2,
            result['analysis_diagnostics']['candidates'] * 2,
            result['analysis_evidence'] * 2,
        )
        assert replayed['authoritative_result'] == result['authoritative_result']
        assert replayed['analysis_diagnostics'] == result['analysis_diagnostics']
        assert replayed['analysis_evidence'] == result['analysis_evidence']
        assert replayed['analysis_validation']['status'] == 'valid'


def test_reused_candidate_identity_with_different_payload_is_not_last_writer_wins():
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    with document_analysis_runtime(documents) as runtime:
        result, _client = run_analysis(runtime, documents)
        candidate = result['analysis_diagnostics']['candidates'][0]
        changed = deepcopy(candidate)
        changed['values']['explanation'] = 'A contradictory replay.'
        replayed = runtime.results.finalize_document_analysis_result(
            result['analysis_sources'], result['analysis_validation']['coverage']['work_units'],
            [candidate, changed], result['analysis_evidence'],
        )
        assert replayed['authoritative_result']['value'] == []
        assert replayed['analysis_validation']['status'] == 'partial'
        assert any(issue['code'] == 'candidate_replay_conflict' for issue in replayed['analysis_validation']['issues'])


def test_conflicting_work_unit_replays_cannot_certify_source_coverage():
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    with document_analysis_runtime(documents) as runtime:
        result, _client = run_analysis(runtime, documents)
        completed = result['analysis_validation']['coverage']['work_units'][0]
        failed = {**deepcopy(completed), 'status': 'failed'}
        versions = [completed, failed, completed, failed]
        replayed = runtime.results.finalize_document_analysis_result(
            result['analysis_sources'], versions, result['analysis_diagnostics']['candidates'],
            result['analysis_evidence'],
        )
        reversed_replay = runtime.results.finalize_document_analysis_result(
            result['analysis_sources'], list(reversed(versions)), result['analysis_diagnostics']['candidates'],
            result['analysis_evidence'],
        )
        assert replayed == reversed_replay
        assert replayed['authoritative_result']['value'] == []
        assert replayed['analysis_validation']['coverage']['completed_sources'] == 0
        assert replayed['analysis_validation']['status'] == 'invalid'


@pytest.mark.parametrize('first_value,second_value', [(None, 0), (True, 1), ([1], [2]), (1, 1.0)])
def test_incompatible_values_are_not_arbitrarily_coerced_or_unioned(first_value, second_value):
    documents = {'observations': original_document('observations', [
        f'Reported value: {json.dumps(first_value)}',
        f'Reported value: {json.dumps(second_value)}',
    ])}

    def response(prompt):
        source = prompt.split('<DocumentSlice>\n', 1)[1].split('\n</DocumentSlice>', 1)[0]
        quote = source.split('] ', 1)[1]
        chunk_sequence = 1 if 'window 1 ' in prompt else 2
        return json.dumps({'findings': [{
            'finding_key': 'reported_value', 'status': 'supported', 'issues': [],
            'values': {'reported_value': json.loads(quote.split(': ', 1)[1])},
            'evidence': [{'chunk_sequence': chunk_sequence, 'quote': quote}],
        }]})

    with document_analysis_runtime(documents) as runtime:
        result, _client = run_analysis(runtime, documents, FixtureAnalysisClient(response))
        assert result['authoritative_result']['value'] == []
        assert result['analysis_validation']['unresolved_candidate_count'] == 2
        assert result['analysis_validation']['coverage']['completed_sources'] == 1
        assert any(issue['code'] == 'conflicting_values' for issue in result['analysis_validation']['issues'])


@pytest.mark.parametrize('bad_output', [
    'Not JSON.',
    '{"findings":[],"findings":[]}',
    '{"findings":[]} Unexpected trailing response',
    '{"findings":[],"score":NaN}',
    '{"findings":[],"score":1e999}',
])
def test_invalid_nonempty_responses_do_not_become_success_after_retry(bad_output):
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    with document_analysis_runtime(documents) as runtime:
        result, client = run_analysis(
            runtime, documents, FixtureAnalysisClient(lambda prompt: bad_output), max_retries_per_window=1,
        )
        assert result['authoritative_result']['value'] == []
        assert result['analysis_validation']['status'] == 'invalid'
        assert result['coverage']['processed_windows'] == 0
        assert result['coverage']['failed_windows'] == 1
        assert len(client.calls) == 2
        assert result['analysis_metrics']['model_calls']['retries'] == 1
        assert len(result['raw_analysis_items']) == 2


def test_retry_records_observed_calls_without_exposing_provider_errors():
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    attempts = 0

    def response(prompt):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError('private-provider-credential')
        return extract_fixture_findings(prompt)

    with document_analysis_runtime(documents) as runtime:
        events = []
        result, client = run_analysis(
            runtime, documents, FixtureAnalysisClient(response),
            max_retries_per_window=1, activity_callback=events.append,
        )
        assert len(result['authoritative_result']['value']) == 1
        assert result['analysis_validation']['status'] == 'valid'
        assert result['coverage']['retries'] == 1
        assert result['analysis_metrics']['model_calls']['extraction'] == len(client.calls) == 2
        assert result['analysis_metrics']['model_calls']['retries'] == 1
        assert 'private-provider-credential' not in json.dumps([result, events])


def test_failed_assigned_source_leaves_supported_subset_explicitly_partial():
    documents = {
        'supplier': original_document('supplier', ['There is a sole supplier for this service.']),
        'failed': original_document('failed', ['An exit penalty applies to early cancellation.']),
    }

    def response(prompt):
        return 'Incomplete response' if 'Preferred source name: failed.txt' in prompt else extract_fixture_findings(prompt)

    with document_analysis_runtime(documents) as runtime:
        result, _client = run_analysis(runtime, documents, FixtureAnalysisClient(response))
        assert result['analysis_validation']['status'] == 'partial'
        assert [record['document_id'] for record in result['authoritative_result']['value']] == ['supplier']
        coverage = result['analysis_validation']['coverage']
        assert coverage['assigned_sources'] == 2
        assert coverage['completed_sources'] == 1
        assert coverage['completed_work_units'] == coverage['failed_work_units'] == 1
        assert len(coverage['work_units']) == 2
        assert 'failed.txt: 0/1 windows processed' in result['analysis_reply']


def test_material_unresolved_requirements_are_reported_without_inventing_values():
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    with document_analysis_runtime(documents) as runtime:
        result, client = run_analysis(runtime, documents, FixtureAnalysisClient(lambda prompt: json.dumps({
            'findings': [], 'issues': ['Required scoring weights were not specified.'],
        })))
        assert result['authoritative_result']['value'] == []
        assert result['analysis_validation']['status'] == 'partial'
        assert 'unresolved task requirement' in result['analysis_reply']
        assert 'Required scoring weights were not specified.' in json.dumps(result['analysis_diagnostics'])
        assert 'Required scoring weights were not specified.' not in json.dumps(result['analysis_validation'])
        checks = {check['name']: check['status'] for check in result['analysis_validation']['checks']}
        assert checks['factual_accuracy_and_entailment'] == 'not_performed'
        assert checks['mathematical_correctness'] == 'not_performed'
        assert len(client.calls) == 1


@pytest.mark.parametrize('uncertainty', ['unresolved', 'wrong_window', 'missing_evidence'])
def test_collected_but_unsupported_candidates_are_not_authoritative(uncertainty):
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}

    def response(prompt):
        payload = json.loads(extract_fixture_findings(prompt))
        candidate = payload['findings'][0]
        if uncertainty == 'unresolved':
            candidate['status'] = 'unresolved'
        elif uncertainty == 'wrong_window':
            candidate['evidence'][0]['chunk_sequence'] = 22
        else:
            candidate['evidence'] = []
        return json.dumps(payload)

    with document_analysis_runtime(documents) as runtime:
        result, _client = run_analysis(runtime, documents, FixtureAnalysisClient(response))
        assert result['authoritative_result']['value'] == []
        assert result['analysis_validation']['coverage']['completed_sources'] == 1
        assert result['analysis_validation']['status'] == 'partial'
        assert result['analysis_validation']['unresolved_candidate_count'] == 1
        assert result['analysis_diagnostics']['candidates'][0]['resolution'] == 'unresolved'


def test_supported_window_cannot_hide_an_unresolved_candidate_for_the_same_finding():
    documents = {'supplier': original_document('supplier', [
        'There is a sole supplier for this service.',
        'There is still a sole supplier for this service.',
    ])}

    def response(prompt):
        payload = json.loads(extract_fixture_findings(prompt))
        if payload['findings'][0]['evidence'][0]['chunk_sequence'] == 2:
            payload['findings'][0]['status'] = 'unresolved'
        return json.dumps(payload)

    with document_analysis_runtime(documents) as runtime:
        result, _client = run_analysis(runtime, documents, FixtureAnalysisClient(response))
        assert result['authoritative_result']['value'] == []
        assert result['analysis_validation']['unresolved_candidate_count'] == 2
        assert result['analysis_validation']['coverage']['status'] == 'complete'


def test_model_source_claims_cannot_replace_resolved_lineage():
    documents = {'supplier': original_document(
        'supplier', ['There is a sole supplier for this service.'], scope='group', scope_id='trusted-group',
    )}

    def response(prompt):
        payload = json.loads(extract_fixture_findings(prompt))
        payload['findings'][0].update({
            'document_id': 'other-document', 'record_id': 'invented', 'source': {'scope_id': 'other-group'},
        })
        return json.dumps(payload)

    with document_analysis_runtime(documents) as runtime:
        result, _client = run_analysis(
            runtime, documents, FixtureAnalysisClient(response), doc_scope='group', active_group_ids=['trusted-group'],
        )
        record = result['authoritative_result']['value'][0]
        assert record['document_id'] == record['source']['document_id'] == 'supplier'
        assert record['source']['scope'] == 'group'
        assert record['source']['scope_id'] == 'trusted-group'
        assert record['record_id'] != 'invented'
        assert result['analysis_sources'] == [record['source']]


def test_source_revision_and_record_identity_change_when_original_text_changes():
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    with document_analysis_runtime(documents) as runtime:
        first, _client = run_analysis(runtime, documents)
        repeated, _client = run_analysis(runtime, documents)
        assert first['authoritative_result'] == repeated['authoritative_result']
        documents['supplier']['chunks'][0]['chunk_text'] = 'There is a different sole supplier for this service.'
        changed, _client = run_analysis(runtime, documents)
        assert first['analysis_sources'][0]['source_revision'] != changed['analysis_sources'][0]['source_revision']
        assert first['authoritative_result']['value'][0]['record_id'] != changed['authoritative_result']['value'][0]['record_id']


def test_trusted_file_hash_provenance_survives_without_becoming_access_or_chunk_freshness():
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    manifest = source_manifest_for(documents)
    file_hash = hashlib.sha256(b'Original uploaded file bytes, before indexed-text extraction.').hexdigest()
    manifest[0]['content_sha256'] = file_hash
    with document_analysis_runtime(documents) as runtime:
        result, client = run_analysis(runtime, documents, source_manifest=manifest)
        assert len(client.calls) == 1
        source = result['analysis_sources'][0]
        assert source['content_sha256'] == file_hash
        assert source['content_fingerprint'] != f'sha256-{file_hash}'
        for item in (
            result['authoritative_result']['value'] + result['analysis_evidence']
            + result['analysis_diagnostics']['candidates']
        ):
            assert item['source']['content_sha256'] == file_hash
        assert file_hash not in result['analysis_reply']
        denied = FixtureAnalysisClient()
        with pytest.raises(LookupError):
            run_analysis(runtime, documents, denied, user_id='not-the-owner', source_manifest=manifest)
        assert denied.calls == []


@pytest.mark.parametrize('source_count', [1, 101, 500])
def test_outer_manifest_revisions_survive_serialized_metadata_and_snapshot_checks(source_count):
    documents = {
        f'contract-{index}': original_document(f'contract-{index}', ['There is a sole supplier for this service.'])
        for index in range(source_count)
    }
    for document_id, fixture in documents.items():
        fixture['document']['_etag'] = f'"{document_id}-revision-1"'
    source_by_id = {source['document_id']: source for source in source_manifest_for(documents)}
    resolver_calls = []

    def resolver(document_ids, **context):
        resolver_calls.append(list(document_ids))
        return [dict(source_by_id[document_id], storage_locator={'blob_path': 'private-manifest-locator'})
                for document_id in document_ids]

    with document_analysis_runtime(documents) as runtime:
        access = import_app_module('functions_analysis_access')
        manifest = access.resolve_analysis_source_manifest(list(documents), USER_ID, resolver=resolver)
        original_manifest = deepcopy(manifest)
        payload = runtime.search.get_document_chunks_payload(next(iter(documents)), user_id=USER_ID)
        assert '_etag' not in payload['document']
        result, client = run_analysis(runtime, documents, source_manifest=list(reversed(manifest)))
        assert manifest == original_manifest
        assert len(client.calls) == len(result['authoritative_result']['value']) == source_count
        assert len(result['analysis_sources']) == source_count
        for record in result['authoritative_result']['value']:
            source = record['source']
            assert source['source_version'] == source_by_id[record['document_id']]['source_version']
            assert source['source_revision'] == source_by_id[record['document_id']]['source_revision']
            assert source['content_fingerprint'].startswith('sha256-')
        source_records = {source['document_id']: source for source in result['analysis_sources']}
        for item in result['analysis_evidence'] + result['analysis_diagnostics']['candidates']:
            assert item['source'] == source_records[item['document_id']]
        assert 'private-manifest-locator' not in json.dumps(result)
        assert access.authorize_analysis_sources(
            USER_ID, result['analysis_sources'], require_snapshot=True, resolver=resolver,
        ) == {'source_count': source_count, 'source_snapshot_changed': False}
        assert all(len(batch) <= 100 for batch in resolver_calls)


def test_manifest_binding_only_counts_assigned_sources_and_preserves_empty_results():
    documents = {
        'supplier': original_document('supplier', ['There is a sole supplier for this service.']),
        'schedule': original_document('schedule', ['The equipment schedule lists blue desks.']),
    }
    manifest = source_manifest_for(documents)
    for entry in manifest:
        entry['source_revision'] = f'{entry["document_id"]}-etag'
    manifest.extend([
        deepcopy(manifest[0]),
        {
            'document_id': 'assigned-to-another-batch', 'scope': 'personal', 'scope_id': USER_ID,
            'authorization_status': 'unresolved',
        },
    ])
    with document_analysis_runtime(documents) as runtime:
        result, client = run_analysis(runtime, documents, source_manifest=manifest)
        assert len(client.calls) == 2
        assert len(result['authoritative_result']['value']) == 1
        assert result['analysis_validation']['coverage']['completed_sources'] == 2
        assert [source['document_id'] for source in result['analysis_sources']] == list(documents)
        assert result['analysis_sources'][1]['source_revision'] == 'schedule-etag'


@pytest.mark.parametrize('invalid_manifest', [
    [],
    {},
    [{}],
    [{
        'document_id': 'supplier', 'scope': 'personal', 'scope_id': USER_ID,
        'authorization_status': 'unresolved',
    }],
    [
        {'document_id': 'supplier', 'scope': 'personal', 'scope_id': USER_ID, 'source_revision': 'first'},
        {'document_id': 'supplier', 'scope': 'personal', 'scope_id': USER_ID, 'source_revision': 'conflict'},
    ],
])
def test_incomplete_or_conflicting_manifests_do_not_start_extraction(invalid_manifest):
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    with document_analysis_runtime(documents) as runtime:
        client = FixtureAnalysisClient()
        with pytest.raises(runtime.results.AnalysisResultUnavailable):
            run_analysis(runtime, documents, client, source_manifest=invalid_manifest)
        assert runtime.source_reads == []
        assert client.calls == []


@pytest.mark.parametrize('field,value', [
    ('scope_id', 'different-owner'),
    ('scope', 'group'),
    ('source_version', 2),
])
def test_manifest_cannot_relabel_a_different_resolved_source_or_visible_version(field, value):
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    manifest = source_manifest_for(documents)
    manifest[0][field] = value
    with document_analysis_runtime(documents) as runtime:
        client = FixtureAnalysisClient()
        with pytest.raises(runtime.results.AnalysisResultUnavailable):
            run_analysis(runtime, documents, client, source_manifest=manifest)
        assert client.calls == []


def test_manifest_revision_and_retrieved_content_both_contribute_to_identity():
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    manifest = source_manifest_for(documents)
    manifest[0]['source_revision'] = 'etag-1'
    with document_analysis_runtime(documents) as runtime:
        first, _client = run_analysis(runtime, documents, source_manifest=manifest)
        manifest[0]['source_revision'] = 'etag-2'
        revision_changed, _client = run_analysis(runtime, documents, source_manifest=manifest)
        first_source = first['analysis_sources'][0]
        changed_source = revision_changed['analysis_sources'][0]
        assert first_source['content_fingerprint'] == changed_source['content_fingerprint']
        assert first_source['source_revision'] != changed_source['source_revision']
        assert first['authoritative_result']['value'][0]['record_id'] != revision_changed['authoritative_result']['value'][0]['record_id']
        documents['supplier']['chunks'][0]['chunk_text'] = 'There is a different sole supplier for this service.'
        content_changed, _client = run_analysis(runtime, documents, source_manifest=manifest)
        assert content_changed['analysis_sources'][0]['source_revision'] == 'etag-2'
        assert content_changed['analysis_sources'][0]['content_fingerprint'] != changed_source['content_fingerprint']
        assert content_changed['authoritative_result']['value'][0]['record_id'] != revision_changed['authoritative_result']['value'][0]['record_id']
        access = import_app_module('functions_analysis_access')
        with pytest.raises(access.AnalysisResultUnavailable):
            access.authorize_analysis_sources(
                USER_ID, first['analysis_sources'], require_snapshot=True,
                resolver=lambda document_ids, **context: deepcopy(manifest),
            )


def test_unknown_manifest_revision_is_not_replaced_with_a_datastore_fingerprint_claim():
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    manifest = source_manifest_for(documents)
    manifest[0].update({'source_version': None, 'source_revision': None})
    with document_analysis_runtime(documents) as runtime:
        result, _client = run_analysis(runtime, documents, source_manifest=manifest)
        source = result['analysis_sources'][0]
        assert source['source_version'] is None
        assert source['source_revision'] is None
        assert source['content_fingerprint'].startswith('sha256-')
        access = import_app_module('functions_analysis_access')
        with pytest.raises(access.AnalysisResultUnavailable):
            access.authorize_analysis_sources(
                USER_ID, result['analysis_sources'], require_snapshot=True,
                resolver=lambda document_ids, **context: deepcopy(manifest),
            )


def test_saved_report_and_export_helpers_do_not_extract_or_change_values(monkeypatch):
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    with document_analysis_runtime(documents) as runtime:
        result, client = run_analysis(runtime, documents)
        saved = json.dumps(result)
        del result
        reloaded = json.loads(saved)
        read_count = len(runtime.source_reads)

        def unexpected_extraction(*args, **kwargs):
            raise AssertionError('Formatting saved data must not extract source content.')

        monkeypatch.setattr(runtime.producer, '_get_search_service_helpers', unexpected_extraction)
        monkeypatch.setattr(client, 'invoke_prompt', unexpected_extraction)
        assert runtime.results.build_document_analysis_report(reloaded) == reloaded['analysis_reply']
        first_rows = runtime.results.get_document_analysis_export_rows(reloaded)
        second_rows = runtime.results.get_document_analysis_export_rows(reloaded)
        assert first_rows == second_rows == [reloaded['authoritative_result']['value'][0]['values']]
        assert set(first_rows[0]) == {'finding', 'explanation'}
        first_rows[0]['finding'] = 'Changed by an export consumer'
        assert runtime.results.get_document_analysis_export_rows(reloaded) == second_rows
        assert len(runtime.source_reads) == read_count
        assert len(client.calls) == 1


def test_pending_failed_and_successful_empty_work_are_distinct():
    documents = {'schedule': original_document('schedule', ['The equipment schedule lists blue desks.'])}
    with document_analysis_runtime(documents) as runtime:
        source_payload = runtime.search.get_document_chunks_payload('schedule', user_id=USER_ID)
        source = runtime.results.build_analysis_source('schedule', source_payload)
        window = runtime.search.build_document_chunk_windows(source_payload['chunks'])[0]
        work = runtime.results.build_analysis_work_unit(source, window, runtime.producer._serialize_window_range(window))
        pending = runtime.results.finalize_document_analysis_result([source], [work], [], [])
        failed = runtime.results.finalize_document_analysis_result([source], [{**work, 'status': 'failed'}], [], [])
        empty = runtime.results.finalize_document_analysis_result([source], [{**work, 'status': 'completed'}], [], [])
        assert pending['analysis_validation']['status'] == 'pending'
        assert failed['analysis_validation']['status'] == 'invalid'
        assert empty['analysis_validation']['status'] == 'valid'


def test_same_original_sources_need_fewer_calls_than_legacy_collection():
    documents = {
        f'contract-{index}': original_document(f'contract-{index}', [
            'There is a sole supplier for this service.',
            'An exit penalty applies to early cancellation.',
        ])
        for index in range(10)
    }
    legacy_calls = []

    def legacy_invoke(prompt, stage='window_analysis', metadata=None):
        legacy_calls.append(stage)
        if stage == 'window_analysis':
            payload = json.loads(extract_fixture_findings(prompt))
            return payload['findings'][0]['values']['explanation']
        return 'A consolidated qualitative summary.'

    with document_analysis_runtime(documents) as runtime:
        legacy, _client = run_analysis(runtime, documents, result_version=None, invoke_prompt=legacy_invoke)
        final, client = run_analysis(runtime, documents)
        assert legacy['coverage']['processed_windows'] == final['coverage']['processed_windows'] == 20
        assert legacy_calls.count('window_analysis') == 20
        assert legacy_calls.count('reduction') == 13
        assert len(client.calls) == final['analysis_metrics']['model_calls']['total'] == 20
        assert len(final['authoritative_result']['value']) == 20


def test_report_failure_leaves_final_values_available_for_format_only_retry(monkeypatch):
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    with document_analysis_runtime(documents) as runtime:
        def failed_report(result):
            raise RuntimeError('private-report-error')

        monkeypatch.setattr(runtime.producer, 'build_document_analysis_report', failed_report)
        result, client = run_analysis(runtime, documents)
        assert len(result['authoritative_result']['value']) == 1
        assert result['analysis_validation']['presentation_status'] == 'unavailable'
        assert 'private-report-error' not in result['analysis_reply']
        assert 'Single-supplier dependency' in runtime.results.build_document_analysis_report(result)
        assert len(client.calls) == 1


@pytest.mark.parametrize('cancel_phase', ['model_response', 'reporting_started', 'reduction_completed'])
def test_cancellation_does_not_return_a_stale_final_result(cancel_phase):
    documents = {'supplier': original_document('supplier', ['There is a sole supplier for this service.'])}
    canceled = False

    def response(prompt):
        nonlocal canceled
        if cancel_phase == 'model_response':
            canceled = True
        return extract_fixture_findings(prompt)

    def activity(event):
        nonlocal canceled
        if event['type'] == cancel_phase:
            canceled = True

    with document_analysis_runtime(documents) as runtime:
        client = FixtureAnalysisClient(response)
        with pytest.raises(runtime.cancellation.MixedSourceCancellationError):
            run_analysis(
                runtime, documents, client, cancel_requested=lambda: canceled, activity_callback=activity,
            )
        assert len(client.calls) == 1


def test_existing_configured_limits_still_fail_before_reading_sources():
    with document_analysis_runtime({}) as runtime:
        assert runtime.producer.CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS == 3
        assert runtime.producer.WORKFLOW_DOCUMENT_ANALYSIS_MAX_DOCUMENTS == 10
        for limit in (3, 10):
            with pytest.raises(ValueError, match=f'up to {limit} documents'):
                run_analysis(runtime, {str(index): {} for index in range(limit + 1)}, max_documents=limit)
        assert runtime.source_reads == []
    assert_app_version_at_least('0.261.106')
