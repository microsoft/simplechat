# test_assistant_citation_artifact_storage.py
"""
Functional test for assistant citation artifact storage.
Version: 0.240.013
Implemented in: 0.240.013

This test ensures assistant messages keep compact agent citation summaries while
the full raw citation payload is preserved in linked artifact records that can
be rehydrated for exports or later analysis.
"""

import os
import sys
from copy import deepcopy
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / 'application' / 'single_app'
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from functions_message_artifacts import (  # noqa: E402
    ASSISTANT_ARTIFACT_CHUNK_ROLE,
    ASSISTANT_ARTIFACT_ROLE,
    build_agent_citation_artifact_documents,
    build_message_artifact_payload_map,
    filter_assistant_artifact_items,
    hydrate_agent_citations_from_artifacts,
)


CONFIG_FILE = APP_ROOT / 'config.py'
ROUTE_FILE = APP_ROOT / 'route_backend_chats.py'


def build_sample_tabular_citation(row_count=12):
    """Return a representative tabular citation with enough rows to compact."""
    rows = []
    for index in range(row_count):
        rows.append({
            'TaxpayerID': f'TP{index:06d}',
            'Name': f'Taxpayer {index}',
            'Status': 'Active' if index % 2 == 0 else 'Closed',
            'NoticeAmount': 1000 + index,
            'NoticeDate': f'2026-03-{(index % 28) + 1:02d}',
        })

    return {
        'tool_name': 'TabularProcessingPlugin.filter_rows',
        'function_name': 'filter_rows',
        'plugin_name': 'TabularProcessingPlugin',
        'function_arguments': {
            'user_id': 'user-123',
            'conversation_id': 'conversation-456',
            'filename': 'irs_treasury_multi_tab_workbook.xlsx',
            'sheet_name': 'Notices',
            'column': 'TaxpayerID',
            'operator': '==',
            'value': 'TP000123',
            'max_rows': '25',
            'source': 'workspace',
        },
        'function_result': {
            'filename': 'irs_treasury_multi_tab_workbook.xlsx',
            'selected_sheet': 'Notices',
            'total_matches': row_count,
            'returned_rows': row_count,
            'data': rows,
        },
        'duration_ms': 42.5,
        'timestamp': '2026-04-01T00:00:00Z',
        'success': True,
        'error_message': None,
    }


def test_agent_citation_artifacts_keep_parent_message_compact():
    """Verify compact citations retain references while raw payloads move to artifact docs."""
    citation = build_sample_tabular_citation(row_count=12)
    compact_citations, artifact_docs = build_agent_citation_artifact_documents(
        conversation_id='conversation-456',
        assistant_message_id='conversation-456_assistant_1',
        agent_citations=[citation],
        created_timestamp='2026-04-01T00:00:00Z',
        user_info={'user_id': 'user-123'},
    )

    assert len(compact_citations) == 1, compact_citations
    assert artifact_docs, 'Expected raw citation artifact documents to be created.'
    assert artifact_docs[0]['role'] == ASSISTANT_ARTIFACT_ROLE, artifact_docs[0]
    assert compact_citations[0]['artifact_id'] == 'conversation-456_assistant_1_artifact_1', compact_citations[0]
    assert compact_citations[0]['raw_payload_externalized'] is True, compact_citations[0]
    assert compact_citations[0]['function_result']['total_matches'] == 12, compact_citations[0]
    assert compact_citations[0]['function_result']['returned_rows'] == 12, compact_citations[0]
    assert len(compact_citations[0]['function_result']['sample_rows']) == 3, compact_citations[0]
    assert compact_citations[0]['function_result']['sample_rows_limited'] is True, compact_citations[0]
    assert 'user_id' not in compact_citations[0]['function_arguments'], compact_citations[0]
    assert 'conversation_id' not in compact_citations[0]['function_arguments'], compact_citations[0]


def test_artifact_payloads_rehydrate_full_agent_citations():
    """Verify export hydration restores the preserved raw payload from artifact docs."""
    citation = build_sample_tabular_citation(row_count=9)
    compact_citations, artifact_docs = build_agent_citation_artifact_documents(
        conversation_id='conversation-789',
        assistant_message_id='conversation-789_assistant_1',
        agent_citations=[citation],
        created_timestamp='2026-04-01T00:00:00Z',
    )

    artifact_payload_map = build_message_artifact_payload_map(artifact_docs)
    hydrated_messages = hydrate_agent_citations_from_artifacts([
        {
            'id': 'conversation-789_assistant_1',
            'role': 'assistant',
            'agent_citations': deepcopy(compact_citations),
        }
    ], artifact_payload_map)

    hydrated_citation = hydrated_messages[0]['agent_citations'][0]
    assert hydrated_citation['function_name'] == 'filter_rows', hydrated_citation
    assert hydrated_citation['plugin_name'] == 'TabularProcessingPlugin', hydrated_citation
    assert len(hydrated_citation['function_result']['data']) == 9, hydrated_citation
    assert hydrated_citation['function_result']['data'][0]['TaxpayerID'] == 'TP000000', hydrated_citation


def test_filter_assistant_artifact_items_excludes_child_records():
    """Verify assistant artifact docs stay out of visible chat histories."""
    visible_items = filter_assistant_artifact_items([
        {'id': 'assistant-1', 'role': 'assistant'},
        {'id': 'artifact-1', 'role': ASSISTANT_ARTIFACT_ROLE},
        {'id': 'artifact-1_chunk_1', 'role': ASSISTANT_ARTIFACT_CHUNK_ROLE},
        {'id': 'user-1', 'role': 'user'},
    ])

    visible_ids = [item['id'] for item in visible_items]
    assert visible_ids == ['assistant-1', 'user-1'], visible_ids


def test_config_and_route_reference_phase_one_storage_fix():
    """Verify the application version and route integration reflect phase one."""
    config_content = CONFIG_FILE.read_text(encoding='utf-8')
    route_content = ROUTE_FILE.read_text(encoding='utf-8')

    assert 'VERSION = "0.240.013"' in config_content, 'Expected config.py version 0.240.013'
    assert 'persist_agent_citation_artifacts(' in route_content, 'Expected chat routes to persist citation artifacts.'
    assert 'filter_assistant_artifact_items(all_messages)' in route_content, 'Expected chat history assembly to exclude assistant artifact docs.'


if __name__ == '__main__':
    test_agent_citation_artifacts_keep_parent_message_compact()
    test_artifact_payloads_rehydrate_full_agent_citations()
    test_filter_assistant_artifact_items_excludes_child_records()
    test_config_and_route_reference_phase_one_storage_fix()
    print('✅ Assistant citation artifact storage verified.')