# document_analysis.py
"""Original-source fixtures and isolated SDK seams for the real Analyze producer.

Version: 0.261.122
Implemented in: 0.261.109
"""

import importlib
import json
import re
import sys
import types
from contextlib import contextmanager
from copy import deepcopy

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from test_support.app_stubs import stubbed_config


USER_ID = 'analysis-fixture-user'


def original_document(document_id, paragraphs, scope='personal', scope_id=None):
    document = {
        'id': document_id,
        'file_name': f'{document_id}.txt',
        'title': f'Display title for {document_id}',
        'version': 1,
        'user_id': USER_ID,
        'scope': scope,
        'group_id': scope_id if scope == 'group' else None,
        'public_workspace_id': scope_id if scope == 'public' else None,
    }
    return {
        'document': document,
        'chunks': [
            {
                'id': f'{document_id}-chunk-{index}',
                'document_id': document_id,
                'chunk_sequence': index,
                'page_number': index,
                'chunk_text': text,
            }
            for index, text in enumerate(paragraphs, start=1)
        ],
    }


def _module(name, **attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    return module


@contextmanager
def document_analysis_runtime(documents):
    """Load real retrieval/windowing/producer code with only I/O dependencies doubled."""
    source_reads = []
    screening_reads = []

    def screening_container(scope):
        def read_item(item, partition_key):
            screening_reads.append((scope, item))
            fixture = documents.get(item)
            if partition_key != item or fixture is None or fixture['document']['scope'] != scope:
                raise CosmosResourceNotFoundError(status_code=404, message='Fixture document not found.')
            return deepcopy(fixture['document'])

        return types.SimpleNamespace(read_item=read_item)

    def read_document(user_id, document_id, group_id=None, public_workspace_id=None, **kwargs):
        source_reads.append(('metadata', document_id))
        fixture = documents.get(document_id)
        if user_id != USER_ID or fixture is None:
            return None
        document = fixture['document']
        if document.get('group_id') != group_id or document.get('public_workspace_id') != public_workspace_id:
            return None
        return deepcopy(document)

    def read_chunks(document_id, **kwargs):
        source_reads.append(('chunks', document_id))
        return deepcopy(documents[document_id]['chunks'])

    public_ids = [
        fixture['document']['public_workspace_id'] for fixture in documents.values()
        if fixture['document'].get('public_workspace_id')
    ]
    group_ids = [
        fixture['document']['group_id'] for fixture in documents.values()
        if fixture['document'].get('group_id')
    ]
    def assert_group_role(user_id, group_id, **kwargs):
        if user_id != USER_ID or group_id not in group_ids:
            raise PermissionError('Fixture group access denied.')

    stubs = {
        'functions_content': _module('functions_content'),
        'functions_documents': _module('functions_documents', get_document_record=read_document,
                                      get_ordered_document_chunks=read_chunks),
        'functions_group': _module(
            'functions_group', get_user_groups=lambda user_id: [{'id': key} for key in group_ids],
            assert_group_role=assert_group_role,
        ),
        'functions_public_workspaces': _module(
            'functions_public_workspaces',
            get_user_visible_public_workspace_docs=lambda *args, **kwargs: [],
            get_user_visible_public_workspace_ids_from_settings=lambda user_id: public_ids,
            find_public_workspace_by_id=lambda workspace_id: {'id': workspace_id} if workspace_id in public_ids else None,
        ),
        'utils_cache': _module(
            'utils_cache', generate_search_cache_key=lambda *args, **kwargs: '',
            get_cached_search_results=lambda *args, **kwargs: None,
            cache_search_results=lambda *args, **kwargs: None, DEBUG_ENABLED=False,
        ),
        'functions_service_health': _module(
            'functions_service_health', SemanticSearchQuotaExceededError=RuntimeError,
            clear_semantic_search_quota_warning=lambda *args, **kwargs: None,
            is_semantic_search_quota_error=lambda *args, **kwargs: False,
            record_semantic_search_quota_exceeded=lambda *args, **kwargs: None,
        ),
        'functions_model_endpoint_identity_header': _module(
            'functions_model_endpoint_identity_header',
            build_model_endpoint_identity_headers=lambda *args, **kwargs: {},
        ),
    }
    with stubbed_config(
        CLIENTS={}, cognitive_services_scope='fixture-scope',
        cosmos_conversations_container=None, cosmos_messages_container=None,
        cosmos_user_documents_container=screening_container('personal'),
        cosmos_group_documents_container=screening_container('group'),
        cosmos_public_documents_container=screening_container('public'),
        cosmos_content_screening_container=None,
    ):
        targets = ('functions_search', 'functions_search_service', 'functions_document_analysis', 'functions_debug')
        originals = {name: sys.modules.get(name) for name in (*stubs, *targets)}
        try:
            sys.modules.update(stubs)
            for name in targets:
                sys.modules.pop(name, None)
            producer = importlib.import_module('functions_document_analysis')
            search = importlib.import_module('functions_search_service')
            results = importlib.import_module('functions_document_analysis_results')
            cancellation = importlib.import_module('functions_mixed_source_orchestration')
            yield types.SimpleNamespace(
                producer=producer, search=search, results=results,
                source_reads=source_reads, cancellation=cancellation,
                screening_reads=screening_reads,
            )
        finally:
            # Only restore our app seams. Removing newly imported native SDK modules
            # from sys.modules can make a later test initialize their extension twice.
            for name, module in originals.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module


def extract_fixture_findings(prompt):
    """A deterministic model oracle reading only original passages in its request."""
    excerpt = prompt.split('<DocumentSlice>\n', 1)[1].rsplit('\n</DocumentSlice>', 1)[0]
    findings = []
    for match in re.finditer(r'\[(?:Page (\d+), )?Chunk (\d+)\] ([^\n]+)', excerpt):
        _page, chunk, quote = match.groups()
        key = None
        values = {}
        if 'sole supplier' in quote:
            key = 'supplier_dependency'
            values = {
                'finding': 'Single-supplier dependency',
                'explanation': 'An interruption at the sole supplier could delay service delivery.',
            }
        elif 'exit penalty' in quote:
            key = 'exit_cost'
            values = {
                'finding': 'Cost of ending the contract',
                'explanation': 'The exit penalty could make it expensive to change providers.',
            }
        elif 'service owner is Mira' in quote:
            key = 'oversight'
            values = {'owner': 'Mira'}
        elif 'Reviews take place every quarter' in quote:
            key = 'oversight'
            values = {'review_frequency': 'quarterly'}
        elif 'Required termination notice is' in quote:
            key = 'termination_notice'
            values = {'notice_days': int(re.search(r'(\d+) days', quote).group(1))}
        if key:
            findings.append({
                'finding_key': key,
                'values': values,
                'status': 'supported',
                'issues': [],
                'evidence': [{'chunk_sequence': int(chunk), 'quote': quote}],
            })
    return json.dumps({'findings': findings})


class FixtureAnalysisClient:
    """OpenAI chat-completions double behind the existing invoke_prompt seam."""

    def __init__(self, response_builder=extract_fixture_findings):
        self.calls = []
        self.response_builder = response_builder
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, *, messages, model):
        content = self.response_builder(messages[-1]['content'])
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))])

    def invoke_prompt(self, prompt, stage='window_analysis', metadata=None):
        self.calls.append({'stage': stage, 'metadata': deepcopy(metadata), 'prompt': prompt})
        if stage != 'window_analysis':
            raise AssertionError('Candidate collection and reporting must not invoke a collection-rewrite model call.')
        response = self.chat.completions.create(
            model='fixture-model', messages=[{'role': 'user', 'content': prompt}],
        )
        return response.choices[0].message.content
