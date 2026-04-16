# document_search_plugin.py

from typing import Annotated, Any, Dict

from semantic_kernel.functions import kernel_function

from functions_authentication import get_current_user_id
from functions_search_service import (
    get_document_chunks_payload,
    search_documents as run_document_search,
    summarize_document_content,
)
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


class DocumentSearchPlugin(BasePlugin):
    def __init__(self, manifest: Dict[str, Any] = None):
        super().__init__(manifest)

    @property
    def display_name(self) -> str:
        return 'Document Search'

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            'name': 'document_search_plugin',
            'type': 'search',
            'description': (
                'Hybrid document search, exhaustive chunk retrieval, and hierarchical document summarization '
                'for personal, group, and public workspaces.'
            ),
            'methods': [
                {
                    'name': 'search_documents',
                    'description': 'Run relevance-ranked hybrid search and return chunk-level results with document ids.',
                    'parameters': [
                        {'name': 'query', 'type': 'str', 'description': 'Natural-language search query.', 'required': True},
                        {'name': 'doc_scope', 'type': 'str', 'description': 'all, personal, group, or public.', 'required': False},
                        {'name': 'top_n', 'type': 'int', 'description': 'Maximum number of results to return.', 'required': False},
                    ],
                    'returns': {'type': 'dict', 'description': 'Search results with scope and document metadata.'},
                },
                {
                    'name': 'retrieve_document_chunks',
                    'description': 'Retrieve ordered chunks for one accessible document, optionally in windows.',
                    'parameters': [
                        {'name': 'document_id', 'type': 'str', 'description': 'Document id to retrieve.', 'required': True},
                        {'name': 'doc_scope', 'type': 'str', 'description': 'all, personal, group, or public.', 'required': False},
                        {'name': 'window_number', 'type': 'int', 'description': 'Optional 1-based window number to return.', 'required': False},
                    ],
                    'returns': {'type': 'dict', 'description': 'Ordered chunks and window metadata.'},
                },
                {
                    'name': 'summarize_document',
                    'description': 'Summarize a document hierarchically across ordered chunk windows.',
                    'parameters': [
                        {'name': 'document_id', 'type': 'str', 'description': 'Document id to summarize.', 'required': True},
                        {'name': 'focus_instructions', 'type': 'str', 'description': 'Optional focus areas to emphasize.', 'required': False},
                        {'name': 'final_target_length', 'type': 'str', 'description': 'Desired final summary length.', 'required': False},
                    ],
                    'returns': {'type': 'dict', 'description': 'Summary text plus stage and window metadata.'},
                },
            ],
        }

    def _get_user_id(self):
        user_id = get_current_user_id()
        if not user_id:
            raise RuntimeError('User context is unavailable for document search')
        return user_id

    @plugin_function_logger('DocumentSearchPlugin')
    @kernel_function(
        name='search_documents',
        description='Run hybrid document search over accessible workspaces and return chunk-level results with document ids.',
    )
    def search_documents(
        self,
        query: Annotated[str, 'Natural-language query to run against accessible documents.'],
        doc_scope: Annotated[str, 'all, personal, group, or public.'] = 'all',
        top_n: Annotated[int, 'Maximum number of chunk results to return.'] = 12,
        document_ids: Annotated[str, 'Optional comma-separated document ids to restrict the search.'] = '',
        tags_filter: Annotated[str, 'Optional comma-separated document tags that must all match.'] = '',
        active_group_ids: Annotated[str, 'Optional comma-separated group ids when searching group content.'] = '',
        active_public_workspace_id: Annotated[str, 'Optional public workspace id when searching public content.'] = '',
    ) -> Annotated[dict, 'Search results and request metadata.']:
        try:
            return run_document_search(
                query=query,
                user_id=self._get_user_id(),
                top_n=top_n,
                doc_scope=doc_scope,
                document_ids=document_ids,
                tags_filter=tags_filter,
                active_group_ids=active_group_ids,
                active_public_workspace_id=active_public_workspace_id,
            )
        except Exception as e:
            return {'error': str(e)}

    @plugin_function_logger('DocumentSearchPlugin')
    @kernel_function(
        name='retrieve_document_chunks',
        description='Retrieve ordered chunks for one accessible document, optionally selecting one window of chunks.',
    )
    def retrieve_document_chunks(
        self,
        document_id: Annotated[str, 'Document id to retrieve chunk content from.'],
        doc_scope: Annotated[str, 'all, personal, group, or public.'] = 'all',
        window_unit: Annotated[str, 'pages or chunks for chunk windowing.'] = 'pages',
        window_size: Annotated[int, 'Optional explicit number of pages or chunks per window.'] = 0,
        window_percent: Annotated[int, 'Optional percentage of the document to include per window.'] = 0,
        window_number: Annotated[int, 'Optional 1-based window number to return instead of the full document.'] = 0,
        active_group_ids: Annotated[str, 'Optional comma-separated group ids when resolving group content.'] = '',
        active_public_workspace_id: Annotated[str, 'Optional public workspace id when resolving public content.'] = '',
    ) -> Annotated[dict, 'Ordered chunks and window metadata for one document.']:
        try:
            return get_document_chunks_payload(
                document_id=document_id,
                user_id=self._get_user_id(),
                doc_scope=doc_scope,
                active_group_ids=active_group_ids,
                active_public_workspace_id=active_public_workspace_id,
                window_unit=window_unit,
                window_size=window_size if int(window_size or 0) > 0 else None,
                window_percent=window_percent if int(window_percent or 0) > 0 else None,
                window_number=window_number if int(window_number or 0) > 0 else None,
            )
        except Exception as e:
            return {'error': str(e)}

    @plugin_function_logger('DocumentSearchPlugin')
    @kernel_function(
        name='summarize_document',
        description='Summarize one accessible document hierarchically across ordered chunk windows, with optional focus guidance.',
    )
    def summarize_document(
        self,
        document_id: Annotated[str, 'Document id to summarize.'],
        doc_scope: Annotated[str, 'all, personal, group, or public.'] = 'all',
        focus_instructions: Annotated[str, 'Optional focus areas such as risks, deadlines, or architectural decisions.'] = '',
        final_target_length: Annotated[str, 'Desired final summary length, for example 2 pages or 500 words.'] = '2 pages',
        window_target_length: Annotated[str, 'Target length for each first-pass window summary.'] = '2 pages',
        window_unit: Annotated[str, 'pages or chunks for chunk windowing.'] = 'pages',
        window_size: Annotated[int, 'Optional explicit number of pages or chunks per window.'] = 0,
        window_percent: Annotated[int, 'Optional percentage of the document to include per first-pass window.'] = 0,
        active_group_ids: Annotated[str, 'Optional comma-separated group ids when resolving group content.'] = '',
        active_public_workspace_id: Annotated[str, 'Optional public workspace id when resolving public content.'] = '',
    ) -> Annotated[dict, 'Final summary text plus stage and window metadata.']:
        try:
            return summarize_document_content(
                document_id=document_id,
                user_id=self._get_user_id(),
                doc_scope=doc_scope,
                active_group_ids=active_group_ids,
                active_public_workspace_id=active_public_workspace_id,
                focus_instructions=focus_instructions,
                final_target_length=final_target_length,
                window_target_length=window_target_length,
                window_unit=window_unit,
                window_size=window_size if int(window_size or 0) > 0 else None,
                window_percent=window_percent if int(window_percent or 0) > 0 else None,
            )
        except Exception as e:
            return {'error': str(e)}