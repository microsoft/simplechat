# test_orchestration_search_citation_delivery.py
"""Search citations reach ordinary answers, saved messages and replayed delivery.

Version: 0.261.365
Implemented in: 0.261.365

Real headless execution, search adapters, retained storage and finalization run
against offline external I/O. Only the chosen answer's source lineage is delivered.
"""

from copy import deepcopy
import importlib
import json

import pytest

from functions_citation_tracking import build_cited_source_subsets
from functions_orchestration_execution import refresh_harness_delivery
from test_orchestration_harness_execution import harness, initialized_application
from test_orchestration_reason_render_pipeline import narrative_io
from test_support.orchestration_harness_execution import compose_step, decoded_frames, input_binding


__all__ = ['harness', 'initialized_application', 'narrative_io']


@pytest.mark.parametrize('output', ['evidence', 'prepared'])
@pytest.mark.parametrize('delivery', ['execute', 'refresh'])
def test_search_citations_reach_model_message_and_done_frame(harness, narrative_io, monkeypatch, output, delivery):
    hits = [
        {
            'document_id': 'document-1', 'id': 'document-1_2', 'page_number': 2, 'chunk_sequence': 2,
            'file_name': 'Source.md', 'chunk_text': 'Reviews are due in 10 business days.',
        },
        {
            'document_id': 'document-1', 'id': 'document-1_5', 'page_number': 5, 'chunk_sequence': 5,
            'file_name': 'Source.md', 'chunk_text': 'Rowan is the responsible owner.',
        },
    ]
    searches = []

    def search(*args, **kwargs):
        searches.append((args, kwargs))
        return deepcopy(hits)

    monkeypatch.setattr(importlib.import_module('functions_search'), 'hybrid_search', search)
    prompt = 'What do I need to know before starting an acquisition under this policy?'
    answer = (
        'Allow 10 business days for the review. (Source: Source.md, Page: 2) [#document-1_2]\n\n'
        'Rowan is responsible. (Source: Source.md, Page: 5) [#document-1_5]'
    )

    def reply():
        messages = harness.model_calls[-1]['messages']
        payload = json.loads(messages[-1]['content'])
        assert payload['request'] == prompt
        citations = payload['inputs']['passages']['document_citations']
        assert [item['citation_id'] for item in citations] == [hit['id'] for hit in hits]
        assert any('copy its citation value verbatim' in message['content'] for message in messages)
        if output == 'evidence':
            excerpts = {item['evidence_id']: item['text'] for item in payload['inputs']['passages']['value']}
            assert [excerpts[item['evidence_id']] for item in citations] == [hit['chunk_text'] for hit in hits]
        return answer

    harness.create([
        {
            'step_id': 'search', 'capability_id': 'document_search',
            'arguments': {'query': prompt, 'document_ids': ['document-1'], 'doc_scope': 'personal'},
        },
        compose_step(inputs={'passages': {'binding': input_binding('search', output), 'allow_partial': False}}),
    ], replies=[reply], final_response=input_binding('prepare'), user_message=prompt, resolved_message=prompt,
        seeds={'document_ids': ['document-1'], 'doc_scope': 'personal'},
        original_seeds={'document_ids': ['document-1'], 'doc_scope': 'personal'})
    execution = harness.prepare()
    try:
        if delivery == 'execute':
            frames = execution.execute()
        else:
            result = harness.run_engine(execution)
            assert result['status'] == 'completed', result
            message_id = f'assistant_orchestration_{harness.execution.fingerprint("run-1")[:40]}'
            execution.lease.publish_message({
                'id': message_id, 'conversation_id': 'conversation-1', 'role': 'assistant',
                'content': 'Saved answer awaiting delivery.', 'timestamp': '2026-10-21T00:00:00+00:00',
                'metadata': {'orchestration': {'run_id': 'run-1', 'status': 'completed'}},
                **execution.answer_model.metadata(),
            })
            record = execution.lease.update({
                'citations': [], 'assistant_message_id': message_id,
                'assistant_message_created_at': '2026-10-21T00:00:00+00:00',
                'message_saved': True, 'finalization_status': 'saved',
            })
            services = harness.services()
            with harness.publication_only(services):
                frames = refresh_harness_delivery(
                    record, services=services, settings=harness.settings, lease=execution.lease,
                )
        done = decoded_frames(frames)[-1]
        assert done['status'] == 'completed', done
        messages = harness.assistant_messages()
        assert len(messages) == 1
        message = messages[0]
        citations = message['hybrid_citations']
        assert citations == done['hybrid_citations'] == harness.read()['citations']
        assert [item['citation_id'] for item in citations] == [hit['id'] for hit in hits]
        assert message['content'] == done['full_content'] == answer
        tracked = build_cited_source_subsets(answer, citations)
        assert [item['citation_id'] for item in tracked['cited_hybrid_citations']] == [hit['id'] for hit in hits]
        conversation = harness.conversations.read_item('conversation-1', 'conversation-1')
        assert conversation['used_documents'][0]['citation_ids'] == [hit['id'] for hit in hits]
        assert len(searches) == len(harness.model_calls) == 1
        assert harness.blobs.file_uploads == 0
    finally:
        execution.close()
