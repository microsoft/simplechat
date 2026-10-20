# test_orchestration_analysis_citation_delivery.py
"""Native Analyze/Compare citations reach Compose, messages and streamed delivery.

Version: 0.261.356
Implemented in: 0.261.356

The actual headless execution, source producers, result store and message finalizer
run with existing offline model/source/storage fixtures. No external harness is changed.
"""

import json
import re

import pytest

from functions_citation_tracking import build_cited_source_subsets
from functions_orchestration_execution import refresh_harness_delivery
from test_orchestration_harness_execution import harness, initialized_application
from test_orchestration_internal_analysis import findings_from_original_source
from test_orchestration_reason_render_pipeline import narrative_io
from test_support.orchestration_harness_execution import compose_step, decoded_frames, input_binding


@pytest.mark.parametrize('capability,output', [
    ('document_analyze', 'findings'), ('document_analyze', 'records'), ('document_analyze', 'report'),
    ('document_compare', 'comparison'), ('document_compare', 'report'),
])
@pytest.mark.parametrize('delivery', ['execute', 'refresh'])
def test_native_citations_reach_model_saved_answer_and_done_frame(harness, narrative_io, capability, output, delivery):
    document_ids = ['document-1'] if capability == 'document_analyze' else ['document-1', 'target-1']
    if capability == 'document_analyze':
        arguments = {'document_ids': document_ids, 'doc_scope': 'personal', 'analysis_prompt': 'Summarize with sources.'}
        outputs = [
            {'name': 'findings', 'kind': 'records-v1'}, {'name': 'records', 'kind': 'records-v1'},
            {'name': 'coverage', 'kind': 'structured-v1'}, {'name': 'report', 'kind': 'markdown-v1'},
        ]
    else:
        arguments = {'left_document_id': 'document-1', 'right_document_ids': ['target-1'],
                     'doc_scope': 'personal', 'comparison_prompt': 'Compare with source passages.'}
        outputs = [
            {'name': 'comparison', 'kind': 'comparison-v1'}, {'name': 'coverage', 'kind': 'structured-v1'},
            {'name': 'report', 'kind': 'markdown-v1'},
        ]

    def reply():
        messages = harness.model_calls[-1]['messages']
        prompt = messages[-1]['content']
        if '<DocumentSlice>\n' in prompt and '"findings" list' in prompt:
            return findings_from_original_source(prompt)
        markers = list(dict.fromkeys(re.findall(r'\(Source:.*?\)\s*\[#[^\]]+\]', prompt)))
        if prompt.startswith('{'):
            payload = json.loads(prompt)
            assert payload['inputs']['evidence']['document_citations']
            assert any('copy its citation value verbatim' in message['content'] for message in messages)
        assert markers, 'The real source/Compose boundary supplied no copyable citation markers.'
        return 'Findings from the supplied source. ' + ' '.join(markers)

    harness.create(
        [
            {'step_id': 'source', 'capability_id': capability, 'arguments': arguments, 'outputs': outputs},
            compose_step(inputs={'evidence': {'binding': input_binding('source', output), 'allow_partial': False}}),
        ],
        replies=[reply] * 30, final_response=input_binding('prepare'),
        seeds={'document_ids': document_ids, 'doc_scope': 'personal'},
        original_seeds={'document_ids': document_ids, 'doc_scope': 'personal'},
    )
    execution = harness.prepare()
    if delivery == 'execute':
        frames = execution.execute()
    else:
        result = harness.run_engine(execution)
        assert result['status'] == 'completed', result
        message_id = f'assistant_orchestration_{harness.execution.fingerprint("run-1")[:40]}'
        execution.lease.publish_message({
            'id': message_id, 'conversation_id': 'conversation-1', 'role': 'assistant',
            'content': 'Saved answer pending delivery.', 'timestamp': '2026-10-20T00:00:00+00:00',
            'metadata': {'orchestration': {'run_id': 'run-1', 'status': 'completed'}},
            **execution.answer_model.metadata(),
        })
        record = execution.lease.update({
            'citations': [], 'assistant_message_id': message_id,
            'assistant_message_created_at': '2026-10-20T00:00:00+00:00',
            'message_saved': True, 'finalization_status': 'saved',
        })
        calls = len(harness.model_calls)
        services = harness.services()
        with harness.publication_only(services):
            frames = refresh_harness_delivery(record, services=services, settings=harness.settings, lease=execution.lease)
        assert len(harness.model_calls) == calls
    execution.close()
    done = decoded_frames(frames)[-1]
    assert done['status'] == 'completed', done
    messages = harness.assistant_messages()
    assert len(messages) == 1
    message = messages[0]
    citations = message['hybrid_citations']
    assert citations == done['hybrid_citations'] == harness.read()['citations']
    assert {citation['document_id'] for citation in citations} == set(document_ids)
    assert all(citation['citation_id'] and citation['page_number'] for citation in citations)
    assert message['content'] == done['full_content']
    tracked = build_cited_source_subsets(message['content'], citations)
    assert {citation['document_id'] for citation in tracked['cited_hybrid_citations']} == set(document_ids)
    assert harness.blobs.file_uploads == 0
