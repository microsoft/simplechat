# document_search_plugin.py

from typing import Annotated, Any, Dict, List, Optional, Union

from semantic_kernel.functions import kernel_function

from content_screening.contracts import ScreeningError
from functions_authentication import get_current_user_id
from functions_agent_document_citations import annotate_document_search_payload
from functions_search import (
    SEARCH_DEFAULT_TOP_N,
    SEARCH_MAX_TOP_N,
    normalize_search_id_list,
    normalize_search_scope,
    normalize_search_top_n,
)
from functions_search_service import (
    SUMMARY_DEFAULT_FINAL_TARGET,
    SUMMARY_DEFAULT_WINDOW_SUMMARY_TARGET,
    SUMMARY_DEFAULT_WINDOW_UNIT,
    get_document_chunks_payload,
    search_documents as run_document_search,
    summarize_document_content,
)
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


DOCUMENT_SEARCH_SCOPES = ("personal", "group", "public")
WINDOW_TARGET_LENGTH_LIMITS = (1, 10)
FINAL_TARGET_LENGTH_LIMITS = (1, 20)


class DocumentSearchScopeError(ValueError):
    """Raised when an action configuration disallows the requested document scope."""


def normalize_allowed_search_scopes(additional_fields: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(additional_fields, dict) or "allowed_scopes" not in additional_fields:
        return list(DOCUMENT_SEARCH_SCOPES)

    raw_scopes = additional_fields.get("allowed_scopes")
    if not isinstance(raw_scopes, list):
        return list(DOCUMENT_SEARCH_SCOPES)

    allowed_scopes = []
    for raw_scope in raw_scopes:
        scope = str(raw_scope or "").strip().lower()
        if scope in DOCUMENT_SEARCH_SCOPES and scope not in allowed_scopes:
            allowed_scopes.append(scope)
    return allowed_scopes


def resolve_allowed_scope_requests(requested_scope: str, allowed_scopes: List[str]) -> List[str]:
    normalized_scope = normalize_search_scope(requested_scope)
    allowed_scope_set = set(allowed_scopes)
    if normalized_scope != "all":
        return [normalized_scope] if normalized_scope in allowed_scope_set else []

    if all(scope in allowed_scope_set for scope in DOCUMENT_SEARCH_SCOPES):
        return ["all"]

    return [scope for scope in DOCUMENT_SEARCH_SCOPES if scope in allowed_scope_set]


def intersect_allowed_search_ids(runtime_ids: Any, allowed_ids: Any) -> Union[List[str], str]:
    normalized_allowed_ids = normalize_search_id_list(allowed_ids)
    if not normalized_allowed_ids:
        return runtime_ids

    normalized_runtime_ids = normalize_search_id_list(runtime_ids)
    if not normalized_runtime_ids:
        return normalized_allowed_ids

    allowed_id_set = set(normalized_allowed_ids)
    return [scope_id for scope_id in normalized_runtime_ids if scope_id in allowed_id_set]


def parse_page_target_length(value: Any, min_pages: int, max_pages: int) -> Optional[int]:
    text_value = str(value or "").strip().lower()
    if not text_value:
        return None

    if text_value.endswith("page"):
        text_value = text_value[:-4].strip()
    elif text_value.endswith("pages"):
        text_value = text_value[:-5].strip()

    try:
        pages = int(text_value)
    except (TypeError, ValueError):
        return None

    if pages < min_pages:
        return min_pages
    return min(pages, max_pages)


def normalize_summary_target_length(value: Any, fallback_value: str, min_pages: int, max_pages: int) -> str:
    text_value = str(value or "").strip()
    if not text_value:
        text_value = fallback_value

    parsed_pages = parse_page_target_length(text_value, min_pages, max_pages)
    if parsed_pages is None:
        return text_value
    return f"{parsed_pages} pages"


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

    def _get_additional_fields(self) -> Dict[str, Any]:
        if isinstance(self.manifest, dict) and isinstance(self.manifest.get('additionalFields'), dict):
            return self.manifest['additionalFields']
        return {}

    def _coerce_positive_int(self, value):
        try:
            coerced_value = int(value)
        except (TypeError, ValueError):
            return None
        return coerced_value if coerced_value > 0 else None

    def _resolve_doc_scope(self, requested_scope: str) -> str:
        if str(requested_scope or '').strip():
            return normalize_search_scope(requested_scope)

        return normalize_search_scope(self._get_additional_fields().get('default_doc_scope', 'all'))

    def _resolve_doc_scope_requests(self, requested_scope: str) -> List[str]:
        scope = self._resolve_doc_scope(requested_scope)
        allowed_scopes = normalize_allowed_search_scopes(self._get_additional_fields())
        scope_requests = resolve_allowed_scope_requests(scope, allowed_scopes)
        if not scope_requests:
            raise DocumentSearchScopeError("Document search scope is not allowed for this action.")
        return scope_requests

    def _resolve_top_n(self, requested_top_n: int) -> int:
        top_n_value = self._coerce_positive_int(requested_top_n)
        if top_n_value:
            return normalize_search_top_n(top_n_value, SEARCH_DEFAULT_TOP_N, SEARCH_MAX_TOP_N)

        manifest_top_n = self._coerce_positive_int(self._get_additional_fields().get('default_top_n'))
        if manifest_top_n:
            return normalize_search_top_n(manifest_top_n, SEARCH_DEFAULT_TOP_N, SEARCH_MAX_TOP_N)

        return SEARCH_DEFAULT_TOP_N

    def _resolve_window_unit(self, requested_window_unit: str) -> str:
        if str(requested_window_unit or '').strip():
            return requested_window_unit

        return self._get_additional_fields().get('default_window_unit', SUMMARY_DEFAULT_WINDOW_UNIT)

    def _resolve_optional_window_value(self, requested_value: int, manifest_key: str):
        explicit_value = self._coerce_positive_int(requested_value)
        if explicit_value:
            return explicit_value

        return self._coerce_positive_int(self._get_additional_fields().get(manifest_key))

    def _resolve_focus_instructions(self, requested_focus_instructions: str) -> str:
        if str(requested_focus_instructions or '').strip():
            return requested_focus_instructions

        return self._get_additional_fields().get('default_focus_instructions', '')

    def _resolve_target_length(self, requested_value: str, manifest_key: str, fallback_value: str) -> str:
        if str(requested_value or '').strip():
            raw_value = requested_value
        else:
            raw_value = self._get_additional_fields().get(manifest_key, fallback_value)

        if manifest_key == 'default_window_target_length':
            return normalize_summary_target_length(
                raw_value,
                fallback_value,
                WINDOW_TARGET_LENGTH_LIMITS[0],
                WINDOW_TARGET_LENGTH_LIMITS[1],
            )
        if manifest_key == 'default_final_target_length':
            return normalize_summary_target_length(
                raw_value,
                fallback_value,
                FINAL_TARGET_LENGTH_LIMITS[0],
                FINAL_TARGET_LENGTH_LIMITS[1],
            )
        return str(raw_value or fallback_value)

    def _resolve_allowed_group_ids(self, active_group_ids: Any) -> Union[List[str], str]:
        return intersect_allowed_search_ids(
            active_group_ids,
            self._get_additional_fields().get('allowed_group_ids'),
        )

    def _resolve_allowed_public_workspace_ids(self, active_public_workspace_id: Any) -> Union[List[str], str]:
        return intersect_allowed_search_ids(
            active_public_workspace_id,
            self._get_additional_fields().get('allowed_public_workspace_ids'),
        )

    def _run_scope_limited_search(
        self,
        query,
        user_id,
        top_n,
        scope_requests,
        document_ids,
        tags_filter,
        active_group_ids,
        active_public_workspace_id,
    ):
        if len(scope_requests) == 1:
            return run_document_search(
                query=query,
                user_id=user_id,
                top_n=top_n,
                doc_scope=scope_requests[0],
                document_ids=document_ids,
                tags_filter=tags_filter,
                active_group_ids=active_group_ids,
                active_public_workspace_id=active_public_workspace_id,
                include_all_public_workspaces=scope_requests[0] == "public",
            )

        merged_results = []
        for scope in scope_requests:
            scoped_payload = run_document_search(
                query=query,
                user_id=user_id,
                top_n=top_n,
                doc_scope=scope,
                document_ids=document_ids,
                tags_filter=tags_filter,
                active_group_ids=active_group_ids,
                active_public_workspace_id=active_public_workspace_id,
                include_all_public_workspaces=scope == "public",
            )
            merged_results.extend(scoped_payload.get("results", []))

        merged_results = merged_results[:top_n]
        unique_document_ids = {
            result.get("document_id")
            for result in merged_results
            if result.get("document_id")
        }
        return {
            "query": query,
            "scope": "all",
            "allowed_scopes": scope_requests,
            "top_n": top_n,
            "document_ids": normalize_search_id_list(document_ids),
            "tags_filter": normalize_search_id_list(tags_filter),
            "group_ids": normalize_search_id_list(active_group_ids),
            "active_public_workspace_id": active_public_workspace_id,
            "result_count": len(merged_results),
            "document_count": len(unique_document_ids),
            "results": merged_results,
        }

    def _call_scope_limited_document_operation(self, operation, scope_requests, **kwargs):
        last_lookup_error = None
        for scope in scope_requests:
            try:
                return operation(doc_scope=scope, **kwargs)
            except LookupError as error:
                last_lookup_error = error
        if last_lookup_error:
            raise last_lookup_error
        raise DocumentSearchScopeError("Document search scope is not allowed for this action.")

    # bac-check: ignore - run_document_search resolves requested workspace ids through current-user scope resolvers.
    @plugin_function_logger('DocumentSearchPlugin')
    @kernel_function(
        name='search_documents',
        description=(
            'Run hybrid document search over accessible workspaces and return chunk-level results with document ids. '
            'Every result carries a "citation" value; copy it verbatim into your answer whenever you use that excerpt.'
        ),
    )
    def search_documents(
        self,
        query: Annotated[str, 'Natural-language query to run against accessible documents.'],
        doc_scope: Annotated[str, 'all, personal, group, or public.'] = '',
        top_n: Annotated[int, 'Maximum number of chunk results to return.'] = 0,
        document_ids: Annotated[str, 'Optional comma-separated document ids to restrict the search.'] = '',
        tags_filter: Annotated[str, 'Optional comma-separated document tags that must all match.'] = '',
        active_group_ids: Annotated[str, 'Optional comma-separated group ids when searching group content.'] = '',
        active_public_workspace_id: Annotated[str, 'Optional public workspace id when searching public content.'] = '',
    ) -> Annotated[dict, 'Search results and request metadata.']:
        try:
            return annotate_document_search_payload(
                self._run_scope_limited_search(
                    query=query,
                    user_id=self._get_user_id(),
                    top_n=self._resolve_top_n(top_n),
                    scope_requests=self._resolve_doc_scope_requests(doc_scope),
                    document_ids=document_ids,
                    tags_filter=tags_filter,
                    active_group_ids=self._resolve_allowed_group_ids(active_group_ids),
                    active_public_workspace_id=self._resolve_allowed_public_workspace_ids(active_public_workspace_id),
                ),
                'search_documents',
            )
        except ScreeningError as error:
            return {"error": error.public_message, "error_code": error.code, "status_code": error.status_code}
        except DocumentSearchScopeError as error:
            return {'error': str(error)}
        except Exception as e:
            return {'error': str(e)}

    # bac-check: ignore - get_document_chunks_payload resolves document scope against the current user before reads.
    @plugin_function_logger('DocumentSearchPlugin')
    @kernel_function(
        name='retrieve_document_chunks',
        description=(
            'Retrieve ordered chunks for one accessible document, optionally selecting one window of chunks. '
            'Every chunk carries a "citation" value; copy it verbatim into your answer whenever you use that chunk.'
        ),
    )
    def retrieve_document_chunks(
        self,
        document_id: Annotated[str, 'Document id to retrieve chunk content from.'],
        doc_scope: Annotated[str, 'all, personal, group, or public.'] = '',
        window_unit: Annotated[str, 'pages or chunks for chunk windowing.'] = '',
        window_size: Annotated[int, 'Optional explicit number of pages or chunks per window.'] = 0,
        window_percent: Annotated[int, 'Optional percentage of the document to include per window.'] = 0,
        window_number: Annotated[int, 'Optional 1-based window number to return instead of the full document.'] = 0,
        active_group_ids: Annotated[str, 'Optional comma-separated group ids when resolving group content.'] = '',
        active_public_workspace_id: Annotated[str, 'Optional public workspace id when resolving public content.'] = '',
    ) -> Annotated[dict, 'Ordered chunks and window metadata for one document.']:
        try:
            return annotate_document_search_payload(
                self._call_scope_limited_document_operation(
                    get_document_chunks_payload,
                    self._resolve_doc_scope_requests(doc_scope),
                    document_id=document_id,
                    user_id=self._get_user_id(),
                    active_group_ids=self._resolve_allowed_group_ids(active_group_ids),
                    active_public_workspace_id=self._resolve_allowed_public_workspace_ids(active_public_workspace_id),
                    window_unit=self._resolve_window_unit(window_unit),
                    window_size=self._resolve_optional_window_value(window_size, 'default_window_size'),
                    window_percent=self._resolve_optional_window_value(window_percent, 'default_window_percent'),
                    window_number=window_number if int(window_number or 0) > 0 else None,
                ),
                'retrieve_document_chunks',
            )
        except ScreeningError as error:
            return {"error": error.public_message, "error_code": error.code, "status_code": error.status_code}
        except DocumentSearchScopeError as error:
            return {'error': str(error)}
        except Exception as e:
            return {'error': str(e)}

    # bac-check: ignore - summarize_document_content delegates to get_document_chunks_payload's current-user scope check.
    @plugin_function_logger('DocumentSearchPlugin')
    @kernel_function(
        name='summarize_document',
        description=(
            'Summarize one accessible document hierarchically across ordered chunk windows, with optional focus guidance. '
            'The payload carries a "citation" value; copy it verbatim into your answer when you use the summary.'
        ),
    )
    def summarize_document(
        self,
        document_id: Annotated[str, 'Document id to summarize.'],
        doc_scope: Annotated[str, 'all, personal, group, or public.'] = '',
        focus_instructions: Annotated[str, 'Optional focus areas such as risks, deadlines, or architectural decisions.'] = '',
        final_target_length: Annotated[str, 'Desired final summary length, for example 2 pages or 500 words.'] = '',
        window_target_length: Annotated[str, 'Target length for each first-pass window summary.'] = '',
        window_unit: Annotated[str, 'pages or chunks for chunk windowing.'] = '',
        window_size: Annotated[int, 'Optional explicit number of pages or chunks per window.'] = 0,
        window_percent: Annotated[int, 'Optional percentage of the document to include per first-pass window.'] = 0,
        active_group_ids: Annotated[str, 'Optional comma-separated group ids when resolving group content.'] = '',
        active_public_workspace_id: Annotated[str, 'Optional public workspace id when resolving public content.'] = '',
    ) -> Annotated[dict, 'Final summary text plus stage and window metadata.']:
        try:
            return annotate_document_search_payload(
                self._call_scope_limited_document_operation(
                    summarize_document_content,
                    self._resolve_doc_scope_requests(doc_scope),
                    document_id=document_id,
                    user_id=self._get_user_id(),
                    active_group_ids=self._resolve_allowed_group_ids(active_group_ids),
                    active_public_workspace_id=self._resolve_allowed_public_workspace_ids(active_public_workspace_id),
                    focus_instructions=self._resolve_focus_instructions(focus_instructions),
                    final_target_length=self._resolve_target_length(final_target_length, 'default_final_target_length', SUMMARY_DEFAULT_FINAL_TARGET),
                    window_target_length=self._resolve_target_length(window_target_length, 'default_window_target_length', SUMMARY_DEFAULT_WINDOW_SUMMARY_TARGET),
                    window_unit=self._resolve_window_unit(window_unit),
                    window_size=self._resolve_optional_window_value(window_size, 'default_window_size'),
                    window_percent=self._resolve_optional_window_value(window_percent, 'default_window_percent'),
                ),
                'summarize_document',
            )
        except ScreeningError as error:
            return {"error": error.public_message, "error_code": error.code, "status_code": error.status_code}
        except DocumentSearchScopeError as error:
            return {'error': str(error)}
        except Exception as e:
            return {'error': str(e)}