# document_search_plugin.py

import logging
from typing import Annotated, Any, Dict, List, Optional, Union

from semantic_kernel.functions import kernel_function

from content_screening.contracts import ScreeningError
from functions_authentication import get_current_user_id
from functions_appinsights import log_event
from public_chat_scope_state import current_public_chat_scope
from functions_agent_document_citations import annotate_document_search_payload
from native_document_evidence import NativeInspectionRequestError
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
    get_document_accessibility_payload,
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
                    'name': 'get_document_accessibility_report',
                    'description': 'Return the full stored accessibility, structure, and formatting (font, size, colour) metadata for one workspace document.',
                    'parameters': [
                        {'name': 'document_id', 'type': 'str', 'description': 'Document id to read metadata for.', 'required': True},
                        {'name': 'doc_scope', 'type': 'str', 'description': 'all, personal, group, or public.', 'required': False},
                        {'name': 'sections', 'type': 'str', 'description': 'Optional comma-separated sections: accessibility, style, issues.', 'required': False},
                        {'name': 'page_number', 'type': 'int', 'description': 'Optional page or slide number whose chunk text is also returned.', 'required': False},
                        {'name': 'native_section', 'type': 'str', 'description': 'Excel: all, comments, tables, objects, image_analyses, property_records, custom_properties, extended_properties, defined_names, hyperlinks, validations. PDF/PPTX: all, properties, structure, objects, artifacts, content, issues. Choose all for broad audits or an explicit section for focused questions.', 'required': False},
                        {'name': 'native_cursor', 'type': 'str', 'description': 'Opaque next_cursor from excel_inspection.page or native_inspection.page. Pass unchanged with the same document and native_section; never construct or edit it.', 'required': False},
                        {'name': 'native_page_size', 'type': 'int', 'description': 'Native inventory records per response, between 1 and 200, with a separate byte limit.', 'required': False},
                        {'name': 'sheet_name', 'type': 'str', 'description': 'Worksheet for an optional saved-cell range read.', 'required': False},
                        {'name': 'cell_range', 'type': 'str', 'description': 'Optional Excel A1 range, at most 2000 cells, without executing formulas.', 'required': False},
                    ],
                    'returns': {'type': 'dict', 'description': 'Stored accessibility metadata, style inventory, and issues.'},
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
        scope = 'public' if current_public_chat_scope(self._get_user_id()) else self._resolve_doc_scope(requested_scope)
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
        aggregate = current_public_chat_scope(self._get_user_id())
        if aggregate:
            requested = normalize_search_id_list(active_public_workspace_id) or aggregate['workspace_ids']
            resolved = intersect_allowed_search_ids(requested, self._get_additional_fields().get('allowed_public_workspace_ids'))
            resolved = [value for value in normalize_search_id_list(resolved) if value in aggregate['workspace_ids']]
            if not resolved:
                raise DocumentSearchScopeError("Document search workspace is not allowed for this action.")
            return resolved
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

    # bac-check: ignore - get_document_accessibility_payload resolves document scope against the current user before reads.
    @plugin_function_logger('DocumentSearchPlugin')
    @kernel_function(
        name='get_document_accessibility_report',
        description=(
            'Return the complete stored accessibility, structure, and formatting metadata for one accessible '
            'workspace document: PDF tag tree and document properties, Word and PowerPoint structure, '
            'Excel workbook properties, cell notes/threaded comments, object alt text/decorative flags, '
            'sheet layout and headers/footers with explicit native inspection coverage limits, and the stored '
            'style inventory (fonts, sizes, colours, emphasis, outlier runs, paragraph styles, page setup). '
            'Use it to build custom style-guide or accessibility checks. This is extracted metadata, not a '
            'WCAG or PDF/UA conformance result. Use sections to limit the output and page_number to also '
            'return that page\'s stored chunk text. '
            'For Word .docx/.docm/.dotx review comments, request sections=comments; word_inspection '
            'contains exact comment threads, anchors and available resolution metadata from the authorized '
            'original. Missing originals or malformed comment parts are errors, not empty inventories. '
            'For Excel, inspect native_section and follow excel_inspection.page.next_cursor until has_more '
            'is false when the question requires every record. Compatibility notes are not extra comments. '
            'Use native_section=all for a broad supported workbook inventory, or request a named section '
            'for a focused question. All-section records carry inventory_section; all does not enumerate '
            'every saved cell or execute formulas/macros. '
            'Use sheet_name and cell_range for actual saved values and formula caches; do not infer them '
            'from a schema preview. Existing stored originals are inspected without requiring re-upload. '
            'PDF/PPTX retained authorized active sources are inspected locally on request. Follow '
            'native_inspection.page.next_cursor with native_cursor while has_more is true. '
            'Native field states distinguish absent, present_empty, present_value and inaccessible; '
            'an empty normalized alt_text alone does not establish a stored blank. Native logical '
            'bindings are not visual order. native_audit contains the exact source-grounded audit facts. '
            'A missing property or unsupported check is information to disclose alongside supported '
            'findings, not evidence that the whole inspection failed. '
            'The payload carries a "citation" value; copy it verbatim into your answer when you use it.'
        ),
    )
    def get_document_accessibility_report(
        self,
        document_id: Annotated[str, 'Document id to read accessibility and formatting metadata for.'],
        doc_scope: Annotated[str, 'all, personal, group, or public.'] = '',
        sections: Annotated[str, 'Optional comma-separated sections: accessibility, style, issues, comments. Defaults to accessibility/style/issues; Word comments are opt-in.'] = '',
        page_number: Annotated[int, 'Optional 1-based stored page/slide or Excel evidence segment number, not an Excel printed page.'] = 0,
        active_group_ids: Annotated[str, 'Optional comma-separated group ids when resolving group content.'] = '',
        active_public_workspace_id: Annotated[str, 'Optional public workspace id when resolving public content.'] = '',
        native_section: Annotated[str, 'Excel: all, comments, objects, tables, property_records, custom_properties, extended_properties, defined_names, hyperlinks, validations, image_analyses. PDF/PPTX: all, properties, structure, objects, artifacts, content, issues. Use all for broad audits or a named section for focused questions. Default comments maps to all only for PDF/PPTX.'] = 'comments',
        native_cursor: Annotated[str, 'Opaque next_cursor from excel_inspection.page or native_inspection.page. Copy unchanged with the same document and native_section; do not construct or modify it.'] = '',
        native_page_size: Annotated[int, 'Native inventory page size from 1 through 200; responses also have a byte budget.'] = 100,
        sheet_name: Annotated[str, 'Worksheet name for optional direct saved-cell inspection.'] = '',
        cell_range: Annotated[str, 'Optional A1 range with at most 2000 cells; reads saved values/formulas, never recalculates.'] = '',
    ) -> Annotated[dict, 'Stored accessibility, style inventory, and issue metadata for one document.']:
        try:
            return annotate_document_search_payload(
                self._call_scope_limited_document_operation(
                    get_document_accessibility_payload,
                    self._resolve_doc_scope_requests(doc_scope),
                    document_id=document_id,
                    user_id=self._get_user_id(),
                    active_group_ids=self._resolve_allowed_group_ids(active_group_ids),
                    active_public_workspace_id=self._resolve_allowed_public_workspace_ids(active_public_workspace_id),
                    sections=sections,
                    page_number=page_number if int(page_number or 0) > 0 else None,
                    native_section=native_section, native_cursor=native_cursor or None,
                    native_page_size=native_page_size, sheet_name=sheet_name or None,
                    cell_range=cell_range or None,
                ),
                'get_document_accessibility_report',
            )
        except NativeInspectionRequestError as error:
            log_event(
                "[DOCUMENT_METADATA] Native inspection request rejected.",
                level=logging.WARNING, extra={
                    "error_type": type(error).__name__, "validation_code": error.code,
                    "argument_field": error.argument_field, "validation_rule": error.validation_rule,
                },
            )
            return {
                "error": error.public_message, "error_code": error.code,
                "validation_rule": error.validation_rule,
            }
        except ScreeningError as error:
            return {"error": error.public_message, "error_code": error.code, "status_code": error.status_code}
        except DocumentSearchScopeError as error:
            return {'error': str(error)}
        except Exception as error:
            log_event(
                "[DOCUMENT_METADATA] Document inspection action failed.",
                level=logging.WARNING, extra={"error_type": type(error).__name__},
            )
            return {'error': 'Unable to inspect the requested document or workbook range.'}

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