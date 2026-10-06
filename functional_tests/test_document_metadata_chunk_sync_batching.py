#!/usr/bin/env python3
"""
Functional test for document metadata chunk sync batching.
Version: 0.261.051
Implemented in: 0.261.051

This test ensures that large document metadata updates can synchronize search
chunk metadata in resumable batches instead of requiring one long request.
"""

import os
import sys
import ast
import json
import traceback
from copy import deepcopy
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
sys.path.append(REPO_ROOT)
sys.path.append(APP_ROOT)

from test_support.versioning import assert_app_version_at_least


class FakeDocumentsContainer:
    def __init__(self, document):
        self.document = document

    def query_items(self, query, parameters, enable_cross_partition_query=True):
        return [self.document]


class FakeCosmosResourceNotFoundError(Exception):
    def __init__(self, message=None, status=None):
        super().__init__(message)
        self.status = status


def load_update_document_for_test(namespace):
    """Load the real update_document source into a controlled test namespace."""
    source_path = os.path.join(APP_ROOT, 'functions_documents.py')
    with open(source_path, 'r', encoding='utf-8') as source_file:
        module_ast = ast.parse(source_file.read(), filename=source_path)

    update_function = next(
        node for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name == 'update_document'
    )
    function_module = ast.Module(body=[update_function], type_ignores=[])
    ast.fix_missing_locations(function_module)
    exec(compile(function_module, source_path, 'exec'), namespace)
    return namespace['update_document']


def test_metadata_chunk_sync_batches_and_resumes():
    """Test chunk metadata synchronization continuation across batches."""
    print("Testing document metadata chunk sync batching...")
    assert_app_version_at_least("0.261.051")

    document = {
        'id': 'doc-large-xml',
        'user_id': 'user-123',
        'title': 'Large XML',
        'tags': [],
        'status': 'Processing Complete',
        'percentage_complete': 100,
    }
    chunks = [{'id': f'chunk-{index}'} for index in range(5)]
    chunk_updates = []
    upserted_documents = []
    namespace = {
        'datetime': datetime,
        'timezone': timezone,
        'json': json,
        'traceback': traceback,
        'CosmosResourceNotFoundError': FakeCosmosResourceNotFoundError,
        'cosmos_user_documents_container': FakeDocumentsContainer(document),
        'cosmos_group_documents_container': FakeDocumentsContainer(document),
        'cosmos_public_documents_container': FakeDocumentsContainer(document),
        'add_file_task_to_file_processing_log': lambda **kwargs: None,
        'calculate_processing_percentage': lambda doc: doc.get('percentage_complete', 0),
        'get_all_chunks': lambda document_id, user_id, group_id=None, public_workspace_id=None: chunks,
        'ensure_list': lambda value: value if isinstance(value, list) else [value],
        'update_chunk_metadata': lambda **kwargs: chunk_updates.append(kwargs),
        '_upsert_document_and_sync_access_index': (
            lambda container, doc, operation: upserted_documents.append(deepcopy(doc))
        ),
    }
    update_document = load_update_document_for_test(namespace)

    first_result = update_document(
        document_id='doc-large-xml',
        user_id='user-123',
        tags=['bills'],
        chunk_sync_limit=2,
    )

    assert first_result['updated'] is True
    assert first_result['chunk_sync']['complete'] is False
    assert first_result['chunk_sync']['next_offset'] == 2
    assert first_result['chunk_sync']['processed'] == 2
    assert first_result['chunk_sync']['total'] == 5
    assert [update['chunk_id'] for update in chunk_updates] == ['chunk-0', 'chunk-1']
    assert upserted_documents[-1]['tags'] == ['bills']

    second_result = update_document(
        document_id='doc-large-xml',
        user_id='user-123',
        tags=['bills'],
        chunk_sync_limit=10,
        chunk_sync_offset=2,
        chunk_sync_fields=['tags'],
    )

    assert second_result['updated'] is False
    assert second_result['chunk_sync']['complete'] is True
    assert second_result['chunk_sync']['next_offset'] is None
    assert second_result['chunk_sync']['processed'] == 3
    assert [update['chunk_id'] for update in chunk_updates] == [
        'chunk-0',
        'chunk-1',
        'chunk-2',
        'chunk-3',
        'chunk-4',
    ]
    assert all(update['document_tags'] == ['bills'] for update in chunk_updates)

    print("Document metadata chunk sync batching test passed.")
    return True


if __name__ == "__main__":
    success = test_metadata_chunk_sync_batches_and_resumes()
    sys.exit(0 if success else 1)