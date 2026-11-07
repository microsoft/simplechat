# test_orchestration_analysis_citation_delivery.py
"""Native Analyze/Compare citations reach Compose, messages and streamed delivery.

Version: 0.261.419
Implemented in: 0.261.356
Retained analyses after downstream failure covered in: 0.261.398
Debug-only saved-findings publication correlation implemented in: 0.261.419

The actual headless execution, source producers, result store and message finalizer
run with existing offline model/source/storage fixtures. No external harness is changed.
"""

import hashlib
import importlib
import json
import logging
import re

import pytest

from functions_citation_tracking import build_cited_source_subsets
from functions_orchestration_execution import refresh_harness_delivery
from test_orchestration_harness_execution import harness, initialized_application
from test_orchestration_internal_analysis import findings_from_original_source
from test_orchestration_reason_render_pipeline import narrative_io
from test_support.orchestration_harness_execution import compose_step, decoded_frames, input_binding


# Re-export shared fixtures for pytest's name-based discovery.
__all__ = ["harness", "initialized_application", "narrative_io"]


@pytest.mark.parametrize('capability,output', [
    ('document_analyze', 'findings'), ('document_analyze', 'records'), ('document_analyze', 'report'),
    ('document_compare', 'comparison'), ('document_compare', 'report'),
])
@pytest.mark.parametrize('delivery', ['execute', 'refresh'])
@pytest.mark.parametrize('debug', [False, True])
def test_native_citations_reach_model_saved_answer_and_done_frame(
    harness, narrative_io, capability, output, delivery, debug, monkeypatch, caplog, capsys,
):
    telemetry = importlib.import_module("functions_appinsights")
    logger = logging.getLogger("test.saved_analysis.publication")
    monkeypatch.setattr(telemetry, "get_appinsights_logger", lambda: logger)
    monkeypatch.setattr(telemetry, "_load_logging_settings", lambda: {"enable_debug_logging": debug})
    monkeypatch.setattr(telemetry, "_azure_monitor_configured", True)
    caplog.set_level(logging.DEBUG, logger=logger.name)
    publications = []

    def observe_publication(message, **properties):
        persisted = harness.assistant_messages()
        assert persisted, "Publication diagnostics must follow durable message persistence."
        publications.append(properties)
        telemetry.debug_print(message, **properties)

    monkeypatch.setattr(harness.execution, "debug_print", observe_publication)
    document_ids = ['document-1'] if capability == 'document_analyze' else ['document-1', 'target-1']
    if capability == 'document_analyze':
        arguments = {'document_ids': document_ids, 'doc_scope': 'personal', 'analysis_prompt': 'Summarize with sources.'}
        if output == "findings":
            arguments["analysis_options"] = {"version": "analysis-options-v2", "mode": "source_observations"}
        outputs = [
            {'name': 'findings', 'kind': 'records-v1'}, {'name': 'records', 'kind': 'records-v1'},
            {'name': 'coverage', 'kind': 'structured-v1'}, {'name': 'report', 'kind': 'markdown-v1'},
        ]
        if output == "findings":
            outputs = [item for item in outputs if item["name"] in {"findings", "coverage"}]
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
    if capability == 'document_analyze':
        descriptors = message['metadata']['saved_analyses']
        assert len(descriptors) == 1
        assert descriptors[0]['message_id'] == message['id']
        assert descriptors[0]['validation_status'] == 'valid'
        assert done['metadata']['saved_analyses'] == descriptors
        assert len(publications) == 1
        properties = publications[0]
        assert properties["record_count"] == descriptors[0]["record_count"]
        assert properties["source_count"] == descriptors[0]["source_count"]
        assert properties["descriptor_count"] == 1
        assert properties["available"] is True
        for field, raw in (
            ("conversation_id_hash", "conversation-1"), ("run_id_hash", "run-1"),
            ("message_id_hash", message["id"]), ("producer_run_id_hash", "run-1"),
            ("producer_step_id_hash", "source"),
        ):
            assert properties[field] == hashlib.sha256(raw.encode()).hexdigest()
        if output == "findings":
            assert properties["analysis_semantics"] == "source_observations"
    else:
        assert not publications
    traces = [record for record in caplog.records
              if "[SAVED_ANALYSIS] Findings published" in getattr(record, "sc_message", "")]
    expected_traces = int(debug and capability == "document_analyze")
    assert len(traces) == expected_traces
    console = capsys.readouterr().out
    assert ("[SAVED_ANALYSIS] Findings published" in console) == bool(expected_traces)
    if traces:
        trace = traces[0]
        for key, value in publications[0].items():
            if key != "category" and value is not None:
                assert getattr(trace, f"sc_{key}") == value
        safe = {key: value for key, value in trace.__dict__.items() if key.startswith("sc_")}
        serialized = json.dumps(safe)
        for forbidden in ("Summarize with sources", "document-1", "conversation-1", "run-1",
                          message["id"], "raw_analysis_items", "file_name", "quote", "prompt"):
            assert forbidden not in serialized
    assert harness.blobs.file_uploads == 0


def test_downstream_failure_publishes_native_analysis_readable_through_the_real_message_boundary(
    harness, narrative_io,
):
    def reply():
        prompt = harness.model_calls[-1]['messages'][-1]['content']
        if '<DocumentSlice>\n' in prompt and '"findings" list' in prompt:
            payload = json.loads(findings_from_original_source(prompt))
            for finding in payload['findings']:
                finding['finding_key'] = 'shared-review-subject'
            return json.dumps(payload)
        raise RuntimeError('Offline final-answer provider failure.')

    harness.create(
        [
            {
                'step_id': 'source', 'capability_id': 'document_analyze',
                'arguments': {
                    'document_ids': ['document-1'], 'doc_scope': 'personal',
                    'analysis_prompt': 'Retain the source observations.',
                    'analysis_options': {'version': 'analysis-options-v2', 'mode': 'source_observations'},
                },
                'outputs': [{'name': 'findings', 'kind': 'records-v1'},
                            {'name': 'coverage', 'kind': 'structured-v1'}],
            },
            compose_step(inputs={'evidence': {
                'binding': input_binding('source', 'findings'), 'allow_partial': False,
            }}),
        ],
        replies=[reply] * 30, final_response=input_binding('prepare'),
        seeds={'document_ids': ['document-1'], 'doc_scope': 'personal'},
        original_seeds={'document_ids': ['document-1'], 'doc_scope': 'personal'},
    )
    execution = harness.prepare()
    frames = execution.execute()
    execution.close()
    done = decoded_frames(frames)[-1]
    assert done['status'] == 'failed'
    assert done['outcome'] == 'partial'
    messages = harness.assistant_messages()
    assert len(messages) == 1
    descriptor = messages[0]['metadata']['saved_analyses'][0]
    assert descriptor['semantics']['mode'] == 'source_observations'
    assert descriptor['validation_status'] == 'valid'
    assert descriptor['message_id'] == messages[0]['id']
    saved = importlib.import_module('functions_saved_analysis')
    page = saved.read_saved_analysis_page('owner', saved.saved_analysis_context(descriptor))
    assert page['total_records'] == descriptor['record_count'] > 1
    assert len(page['records']) == descriptor['record_count']
    assert page['validation']['status'] == 'valid'
    assert done['metadata']['saved_analyses'] == messages[0]['metadata']['saved_analyses']


def test_failed_message_publication_emits_no_saved_findings_publication(harness, narrative_io, monkeypatch):
    def reply():
        prompt = harness.model_calls[-1]["messages"][-1]["content"]
        if "<DocumentSlice>\n" in prompt and '"findings" list' in prompt:
            return findings_from_original_source(prompt)
        return "Summary of the retained findings."

    harness.create(
        [
            {"step_id": "source", "capability_id": "document_analyze",
             "arguments": {"document_ids": ["document-1"], "doc_scope": "personal",
                           "analysis_prompt": "Review the document."},
             "outputs": [{"name": "findings", "kind": "records-v1"},
                         {"name": "coverage", "kind": "structured-v1"}]},
            compose_step(inputs={"evidence": {
                "binding": input_binding("source", "findings"), "allow_partial": False,
            }}),
        ],
        replies=[reply] * 30, final_response=input_binding("prepare"),
        seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
    )
    execution = harness.prepare()
    publications = []
    monkeypatch.setattr(harness.execution, "debug_print", lambda *args, **kwargs: publications.append(kwargs))

    def fail_publication(document):
        raise RuntimeError("PRIVATE_STORAGE_FAILURE")

    try:
        result = harness.run_engine(execution)
        assert result["status"] == "completed"
        record = harness.read()
        assert record["execution_steps"][0]["saved_analyses"]
        monkeypatch.setattr(execution.lease, "publish_message", fail_publication)
        with pytest.raises(RuntimeError, match="PRIVATE_STORAGE_FAILURE"):
            execution._finalize(result, None)
        assert not publications
        messages = harness.assistant_messages()
        assert not messages
    finally:
        execution.close()
