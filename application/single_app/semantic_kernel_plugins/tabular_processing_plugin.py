# tabular_processing_plugin.py
"""
TabularProcessingPlugin for Semantic Kernel: provides data analysis operations
on tabular files (CSV, XLSX, XLS, XLSM) stored in Azure Blob Storage.

Works with workspace documents (user-documents, group-documents, public-documents)
and chat-uploaded documents (personal-chat container).
"""
import asyncio
import copy
from datetime import date, datetime
import io
import json
import logging
import re
import warnings
import pandas
from typing import Annotated, Dict, List, Optional, Set
from urllib.parse import urlsplit, urlunsplit
from semantic_kernel.functions import kernel_function
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger
from functions_appinsights import log_event
from config import (
    CLIENTS,
    TABULAR_EXTENSIONS,
    storage_account_user_documents_container_name,
    storage_account_personal_chat_container_name,
    storage_account_group_documents_container_name,
    storage_account_public_documents_container_name,
)


class TabularProcessingPlugin:
    """Provides data analysis functions on tabular files stored in blob storage."""

    SUPPORTED_EXTENSIONS = tuple(f'.{extension}' for extension in sorted(TABULAR_EXTENSIONS))
    DISCOVERY_FUNCTION_NAMES = (
        'list_tabular_files',
        'describe_tabular_file',
    )
    ANALYSIS_FUNCTION_NAMES = (
        'lookup_value',
        'get_distinct_values',
        'count_rows',
        'aggregate_column',
        'filter_rows',
        'search_rows',
        'query_tabular_data',
        'filter_rows_by_related_values',
        'count_rows_by_related_values',
        'group_by_aggregate',
        'group_by_datetime_component',
    )
    THOUGHT_EXCLUDED_PARAMETER_NAMES = (
        'user_id',
        'conversation_id',
        'group_id',
        'public_workspace_id',
    )
    DAY_NAME_ORDER = [
        'Monday',
        'Tuesday',
        'Wednesday',
        'Thursday',
        'Friday',
        'Saturday',
        'Sunday'
    ]
    MONTH_NAME_ORDER = [
        'January',
        'February',
        'March',
        'April',
        'May',
        'June',
        'July',
        'August',
        'September',
        'October',
        'November',
        'December'
    ]
    RELATIONSHIP_COLUMN_HINT_TOKENS = {
        'account',
        'alias',
        'assignee',
        'category',
        'customer',
        'email',
        'employee',
        'engineer',
        'group',
        'id',
        'manager',
        'member',
        'name',
        'owner',
        'person',
        'resource',
        'se',
        'solution',
        'team',
        'user',
    }
    RELATIONSHIP_HINT_LIMIT = 10
    RELATIONSHIP_VALUE_SAMPLE_LIMIT = 500
    RELATIONSHIP_SHARED_VALUE_LIMIT = 5
    SOURCE_VALUE_MATCH_COUNT_LIMIT = 100

    def __init__(self):
        self._df_cache = {}  # Per-instance cache: (container, blob_name, sheet_name) -> DataFrame
        self._blob_data_cache = {}  # Per-instance cache: (container, blob_name) -> raw bytes
        self._workbook_metadata_cache = {}  # Per-instance cache: (container, blob_name) -> workbook metadata
        self._default_sheet_overrides = {}  # (container, blob_name) -> default sheet name
        self._resolved_blob_location_overrides = {}  # (source, filename) -> (container, blob_name)

    @classmethod
    def get_discovery_function_names(cls):
        """Return discovery-oriented kernel function names exposed by the plugin."""
        return cls.DISCOVERY_FUNCTION_NAMES

    @classmethod
    def get_analysis_function_names(cls):
        """Return analytical kernel function names exposed by the plugin."""
        return cls.ANALYSIS_FUNCTION_NAMES

    @classmethod
    def get_thought_excluded_parameter_names(cls):
        """Return parameter names omitted from user-visible thought payloads."""
        return cls.THOUGHT_EXCLUDED_PARAMETER_NAMES

    def set_default_sheet(self, container_name: str, blob_name: str, sheet_name: str):
        """Set the default sheet for a workbook so the model doesn't need to specify it."""
        self._default_sheet_overrides[(container_name, blob_name)] = sheet_name

    def remember_resolved_blob_location(self, source: str, filename: str, container_name: str, blob_name: str):
        """Remember a resolved blob location so later tool calls can reuse it without resupplying scope ids."""
        normalized_filename = str(filename or '').strip()
        if not normalized_filename:
            return

        normalized_source = str(source or '').strip().lower()
        if normalized_source:
            self._resolved_blob_location_overrides[(normalized_source, normalized_filename)] = (container_name, blob_name)

        inferred_source = self._infer_source_from_container(container_name)
        if inferred_source:
            self._resolved_blob_location_overrides[(inferred_source, normalized_filename)] = (container_name, blob_name)

    def _infer_source_from_container(self, container_name: str) -> Optional[str]:
        """Infer the logical tabular source from the backing blob container name."""
        if container_name == storage_account_user_documents_container_name:
            return 'workspace'
        if container_name == storage_account_personal_chat_container_name:
            return 'chat'
        if container_name == storage_account_group_documents_container_name:
            return 'group'
        if container_name == storage_account_public_documents_container_name:
            return 'public'
        return None

    def _get_resolved_blob_location_override(self, source: str, filename: str) -> Optional[tuple]:
        """Return a remembered blob location override when one is available for this analysis run."""
        normalized_filename = str(filename or '').strip()
        if not normalized_filename:
            return None

        normalized_source = str(source or '').strip().lower()
        exact_match = self._resolved_blob_location_overrides.get((normalized_source, normalized_filename))
        if exact_match:
            return exact_match

        filename_matches = [
            blob_location
            for (override_source, override_filename), blob_location in self._resolved_blob_location_overrides.items()
            if override_filename == normalized_filename
        ]
        if len(filename_matches) == 1:
            return filename_matches[0]

        return None

    def _get_blob_service_client(self):
        """Get the blob service client from CLIENTS cache."""
        client = CLIENTS.get("storage_account_office_docs_client")
        if not client:
            raise RuntimeError("Blob storage client not available. Enhanced citations must be enabled.")
        return client

    def _list_tabular_blobs(self, container_name: str, prefix: str) -> List[str]:
        """List all tabular file blobs under a given prefix."""
        client = self._get_blob_service_client()
        container_client = client.get_container_client(container_name)
        blobs = []
        for blob in container_client.list_blobs(name_starts_with=prefix):
            name_lower = blob['name'].lower()
            if any(name_lower.endswith(ext) for ext in self.SUPPORTED_EXTENSIONS):
                blobs.append(blob['name'])
        return blobs

    def _download_tabular_blob_bytes(self, container_name: str, blob_name: str) -> bytes:
        """Download a blob once and reuse the raw bytes across sheet-aware operations."""
        cache_key = (container_name, blob_name)
        if cache_key in self._blob_data_cache:
            return self._blob_data_cache[cache_key]

        client = self._get_blob_service_client()
        blob_client = client.get_blob_client(container=container_name, blob=blob_name)
        stream = blob_client.download_blob()
        data = stream.readall()
        self._blob_data_cache[cache_key] = data
        return data

    def _get_excel_engine(self, blob_name: str) -> Optional[str]:
        """Return the pandas Excel engine for a workbook, or None for CSV files."""
        name_lower = blob_name.lower()
        if name_lower.endswith('.xlsx') or name_lower.endswith('.xlsm'):
            return 'openpyxl'
        if name_lower.endswith('.xls'):
            return 'xlrd'
        return None

    def _get_workbook_metadata(self, container_name: str, blob_name: str) -> dict:
        """Return workbook metadata including available sheet names for Excel files."""
        cache_key = (container_name, blob_name)
        if cache_key in self._workbook_metadata_cache:
            return copy.deepcopy(self._workbook_metadata_cache[cache_key])

        engine = self._get_excel_engine(blob_name)
        metadata = {
            'is_workbook': bool(engine),
            'sheet_names': [],
            'sheet_count': 0,
            'default_sheet': None,
        }

        if engine:
            data = self._download_tabular_blob_bytes(container_name, blob_name)
            excel_file = pandas.ExcelFile(io.BytesIO(data), engine=engine)
            sheet_names = list(excel_file.sheet_names)
            metadata.update({
                'sheet_names': sheet_names,
                'sheet_count': len(sheet_names),
                'default_sheet': sheet_names[0] if sheet_names else None,
            })

        self._workbook_metadata_cache[cache_key] = copy.deepcopy(metadata)
        return copy.deepcopy(metadata)

    def _resolve_sheet_selection(
        self,
        container_name: str,
        blob_name: str,
        sheet_name: Optional[str] = None,
        sheet_index: Optional[str] = None,
        require_explicit_sheet: bool = False,
    ) -> tuple:
        """Resolve a workbook sheet selection and enforce explicit choice when required."""
        workbook_metadata = self._get_workbook_metadata(container_name, blob_name)
        if not workbook_metadata.get('is_workbook'):
            return None, workbook_metadata

        available_sheets = workbook_metadata.get('sheet_names', [])
        if not available_sheets:
            raise ValueError(f"Workbook '{blob_name}' does not contain any readable sheets.")

        matched_sheet_name = self._match_workbook_sheet_name(sheet_name, available_sheets)
        if matched_sheet_name:
            return matched_sheet_name, workbook_metadata

        normalized_sheet_name = (sheet_name or '').strip()
        if normalized_sheet_name:
            raise ValueError(
                f"Sheet '{normalized_sheet_name}' was not found in workbook '{blob_name}'. "
                f"Available sheets: {available_sheets}."
            )

        normalized_sheet_index = None if sheet_index is None else str(sheet_index).strip()
        if normalized_sheet_index not in (None, ''):
            try:
                resolved_sheet_index = int(normalized_sheet_index)
            except ValueError as exc:
                raise ValueError(
                    f"sheet_index must be an integer for workbook '{blob_name}'."
                ) from exc

            if resolved_sheet_index < 0 or resolved_sheet_index >= len(available_sheets):
                raise ValueError(
                    f"sheet_index {resolved_sheet_index} is out of range for workbook '{blob_name}'. "
                    f"Available sheets: {available_sheets}."
                )
            return available_sheets[resolved_sheet_index], workbook_metadata

        if len(available_sheets) == 1:
            return available_sheets[0], workbook_metadata

        # Use pre-selected default sheet if one was set by the orchestration layer
        override_key = (container_name, blob_name)
        if override_key in self._default_sheet_overrides:
            override_sheet = self._default_sheet_overrides[override_key]
            matched_override_sheet = self._match_workbook_sheet_name(override_sheet, available_sheets)
            if matched_override_sheet:
                return matched_override_sheet, workbook_metadata

        if require_explicit_sheet:
            raise ValueError(
                f"Workbook '{blob_name}' has multiple sheets: {available_sheets}. "
                "Specify sheet_name or sheet_index on analytical calls."
            )

        return workbook_metadata.get('default_sheet'), workbook_metadata

    def _match_workbook_sheet_name(self, requested_sheet_name: Optional[str], available_sheets: List[str]) -> Optional[str]:
        """Match a workbook sheet name while tolerating trailing whitespace and case drift."""
        raw_sheet_name = None if requested_sheet_name is None else str(requested_sheet_name)
        normalized_sheet_name = (raw_sheet_name or '').strip()
        if not normalized_sheet_name:
            return None

        for candidate in available_sheets:
            if candidate == raw_sheet_name:
                return candidate

        for candidate in available_sheets:
            if candidate.strip() == normalized_sheet_name:
                return candidate

        raw_sheet_name_casefold = (raw_sheet_name or '').casefold()
        if raw_sheet_name_casefold:
            for candidate in available_sheets:
                if candidate.casefold() == raw_sheet_name_casefold:
                    return candidate

        normalized_sheet_name_casefold = normalized_sheet_name.casefold()
        for candidate in available_sheets:
            if candidate.strip().casefold() == normalized_sheet_name_casefold:
                return candidate

        return None

    def _filter_rows_across_sheets(
        self,
        container_name: str,
        blob_name: str,
        filename: str,
        column: str,
        operator_str: str,
        value: str,
        additional_filter_column: Optional[str] = None,
        additional_filter_operator: str = 'equals',
        additional_filter_value=None,
        normalize_match: bool = False,
        max_rows: int = 100,
    ) -> Optional[str]:
        """Search for matching rows across all sheets that contain the requested column.

        Returns a combined JSON result when matches are found on any sheet,
        or None if the workbook is not multi-sheet (caller should fall through).
        """
        workbook_metadata = self._get_workbook_metadata(container_name, blob_name)
        if not workbook_metadata.get('is_workbook'):
            return None

        available_sheets = workbook_metadata.get('sheet_names', [])
        if len(available_sheets) <= 1:
            return None

        combined_results = []
        sheets_searched = []
        sheets_matched = []
        total_matches = 0

        for sheet in available_sheets:
            df = self._read_tabular_blob_to_dataframe(
                container_name,
                blob_name,
                sheet_name=sheet,
            )
            df = self._try_numeric_conversion(df)

            if column not in df.columns:
                continue

            try:
                filtered_df, applied_filters = self._apply_optional_dataframe_filters(
                    df,
                    filter_column=column,
                    filter_operator=operator_str,
                    filter_value=value,
                    additional_filter_column=additional_filter_column,
                    additional_filter_operator=additional_filter_operator,
                    additional_filter_value=additional_filter_value,
                    normalize_match=normalize_match,
                )
            except (KeyError, ValueError):
                continue

            sheets_searched.append(sheet)

            sheet_matches = len(filtered_df)
            if sheet_matches == 0:
                continue

            sheets_matched.append(sheet)
            total_matches += sheet_matches
            remaining_capacity = max(0, max_rows - len(combined_results))
            if remaining_capacity > 0:
                filtered = filtered_df.head(remaining_capacity)
                for row in filtered.to_dict(orient='records'):
                    row['_sheet'] = sheet
                    combined_results.append(row)

        if not sheets_searched:
            return None

        log_event(
            f"[TabularProcessingPlugin] Cross-sheet filter_rows: "
            f"searched {len(sheets_searched)} sheets, "
            f"matched on {len(sheets_matched)} ({sheets_matched}), "
            f"total_matches={total_matches}",
            level=logging.INFO,
        )

        return json.dumps({
            "filename": filename,
            "selected_sheet": "ALL (cross-sheet search)",
            "sheets_searched": sheets_searched,
            "sheets_matched": sheets_matched,
            "filter_applied": applied_filters,
            "total_matches": total_matches,
            "returned_rows": len(combined_results),
            "data": combined_results,
        }, indent=2, default=str)

    def _search_rows_across_sheets(
        self,
        container_name: str,
        blob_name: str,
        filename: str,
        search_value: str,
        search_columns=None,
        search_operator: str = 'contains',
        return_columns=None,
        query_expression: Optional[str] = None,
        filter_column: Optional[str] = None,
        filter_operator: str = 'equals',
        filter_value=None,
        additional_filter_column: Optional[str] = None,
        additional_filter_operator: str = 'equals',
        additional_filter_value=None,
        normalize_match: bool = False,
        max_rows: int = 100,
    ) -> Optional[str]:
        """Search rows across worksheets when the relevant text column is unknown or broad."""
        workbook_metadata = self._get_workbook_metadata(container_name, blob_name)
        if not workbook_metadata.get('is_workbook'):
            return None

        available_sheets = workbook_metadata.get('sheet_names', [])
        if len(available_sheets) <= 1:
            return None

        requested_search_columns = self._parse_optional_column_list_argument(search_columns)
        requested_return_columns = self._parse_optional_column_list_argument(return_columns)
        combined_results = []
        sheets_searched = []
        sheets_matched = []
        total_matches = 0
        applied_filters = []
        searched_columns = []
        seen_searched_columns = set()
        matched_columns = []
        seen_matched_columns = set()

        for sheet in available_sheets:
            df = self._read_tabular_blob_to_dataframe(
                container_name,
                blob_name,
                sheet_name=sheet,
            )
            df = self._try_numeric_conversion(df)

            try:
                filtered_df, sheet_filters = self._apply_optional_dataframe_filters(
                    df,
                    query_expression=query_expression,
                    filter_column=filter_column,
                    filter_operator=filter_operator,
                    filter_value=filter_value,
                    additional_filter_column=additional_filter_column,
                    additional_filter_operator=additional_filter_operator,
                    additional_filter_value=additional_filter_value,
                    normalize_match=normalize_match,
                )
            except KeyError:
                continue
            except Exception as query_error:
                return json.dumps({
                    'error': f"Query/filter error: {query_error}",
                    'filename': filename,
                    'selected_sheet': 'ALL (cross-sheet search)',
                }, indent=2, default=str)

            remaining_capacity = max(0, max_rows - len(combined_results))
            if remaining_capacity <= 0:
                break

            try:
                search_result = self._search_dataframe_rows(
                    filtered_df,
                    search_value=search_value,
                    search_columns=requested_search_columns,
                    search_operator=search_operator,
                    return_columns=requested_return_columns,
                    normalize_match=normalize_match,
                    max_rows=remaining_capacity,
                )
            except KeyError:
                continue
            except ValueError as search_error:
                return json.dumps({
                    'error': str(search_error),
                    'filename': filename,
                    'selected_sheet': 'ALL (cross-sheet search)',
                }, indent=2, default=str)

            sheets_searched.append(sheet)
            applied_filters = sheet_filters or applied_filters
            for column_name in search_result['searched_columns']:
                lowered_name = str(column_name).lower()
                if lowered_name in seen_searched_columns:
                    continue
                seen_searched_columns.add(lowered_name)
                searched_columns.append(column_name)

            sheet_match_count = int(search_result['total_matches'])
            total_matches += sheet_match_count
            if sheet_match_count > 0:
                sheets_matched.append(sheet)

            for column_name in search_result['matched_columns']:
                lowered_name = str(column_name).lower()
                if lowered_name in seen_matched_columns:
                    continue
                seen_matched_columns.add(lowered_name)
                matched_columns.append(column_name)

            for row in search_result['data']:
                row['_sheet'] = sheet
                combined_results.append(row)

        if not sheets_searched:
            if requested_search_columns:
                return json.dumps({
                    'error': 'None of the requested search_columns were found on any worksheet during cross-sheet search.',
                    'filename': filename,
                    'selected_sheet': 'ALL (cross-sheet search)',
                    'search_columns': requested_search_columns,
                }, indent=2, default=str)
            return None

        log_event(
            f"[TabularProcessingPlugin] Cross-sheet search_rows: "
            f"searched {len(sheets_searched)} sheets, "
            f"matched on {len(sheets_matched)} ({sheets_matched}), "
            f"total_matches={total_matches}",
            level=logging.INFO,
        )

        return json.dumps({
            'filename': filename,
            'selected_sheet': 'ALL (cross-sheet search)',
            'search_value': search_value,
            'search_operator': search_operator,
            'searched_columns': searched_columns,
            'matched_columns': matched_columns,
            'return_columns': requested_return_columns,
            'sheets_searched': sheets_searched,
            'sheets_matched': sheets_matched,
            'filter_applied': applied_filters,
            'normalize_match': normalize_match,
            'total_matches': total_matches,
            'returned_rows': len(combined_results),
            'data': combined_results,
        }, indent=2, default=str)

    def _lookup_value_across_sheets(
        self,
        container_name: str,
        blob_name: str,
        filename: str,
        lookup_column: str,
        lookup_value_str: str,
        target_column: Optional[str] = None,
        match_operator: str = "equals",
        normalize_match: bool = False,
        max_rows: int = 25,
    ) -> Optional[str]:
        """Look up matching rows across all sheets that contain the lookup column.

        Returns a combined JSON result when matches are found,
        or None if the workbook is not multi-sheet.
        """
        workbook_metadata = self._get_workbook_metadata(container_name, blob_name)
        if not workbook_metadata.get('is_workbook'):
            return None

        available_sheets = workbook_metadata.get('sheet_names', [])
        if len(available_sheets) <= 1:
            return None

        combined_results = []
        sheets_searched = []
        sheets_matched = []
        total_matches = 0
        operator = (match_operator or 'equals').strip().lower()
        normalized_lookup_value = str(lookup_value_str)

        for sheet in available_sheets:
            df = self._read_tabular_blob_to_dataframe(
                container_name,
                blob_name,
                sheet_name=sheet,
            )
            df = self._try_numeric_conversion(df)

            if lookup_column not in df.columns:
                continue

            sheets_searched.append(sheet)
            try:
                mask = self._build_series_match_mask(
                    df[lookup_column],
                    operator,
                    normalized_lookup_value,
                    normalize_match=normalize_match,
                )
            except ValueError:
                mask = self._build_series_match_mask(
                    df[lookup_column],
                    'equals',
                    normalized_lookup_value,
                    normalize_match=normalize_match,
                )

            sheet_matches = int(mask.sum())
            if sheet_matches == 0:
                continue

            sheets_matched.append(sheet)
            total_matches += sheet_matches
            remaining_capacity = max(0, max_rows - len(combined_results))
            if remaining_capacity > 0:
                matched_df = df[mask].head(remaining_capacity)
                if target_column and target_column in df.columns:
                    for _, row in matched_df.iterrows():
                        combined_results.append({
                            '_sheet': sheet,
                            lookup_column: row[lookup_column],
                            target_column: row[target_column],
                            '_full_row': {str(k): v for k, v in row.to_dict().items()},
                        })
                else:
                    for row in matched_df.to_dict(orient='records'):
                        row['_sheet'] = sheet
                        combined_results.append(row)

        if not sheets_searched:
            return None

        log_event(
            f"[TabularProcessingPlugin] Cross-sheet lookup_value: "
            f"searched {len(sheets_searched)} sheets, "
            f"matched on {len(sheets_matched)} ({sheets_matched}), "
            f"total_matches={total_matches}",
            level=logging.INFO,
        )

        return json.dumps({
            "filename": filename,
            "selected_sheet": "ALL (cross-sheet search)",
            "sheets_searched": sheets_searched,
            "sheets_matched": sheets_matched,
            "total_matches": total_matches,
            "returned_rows": len(combined_results),
            "data": combined_results,
        }, indent=2, default=str)

    def _query_tabular_data_across_sheets(
        self,
        container_name: str,
        blob_name: str,
        filename: str,
        query_expression: str,
        max_rows: int = 100,
    ) -> Optional[str]:
        """Execute a pandas query expression across all sheets of a multi-sheet workbook.

        Returns a combined JSON result when any sheet produces matches,
        or None if the workbook is not multi-sheet.
        """
        workbook_metadata = self._get_workbook_metadata(container_name, blob_name)
        if not workbook_metadata.get('is_workbook'):
            return None

        available_sheets = workbook_metadata.get('sheet_names', [])
        if len(available_sheets) <= 1:
            return None

        combined_results = []
        sheets_searched = []
        sheets_matched = []
        total_matches = 0
        query_errors = []

        for sheet in available_sheets:
            df = self._read_tabular_blob_to_dataframe(
                container_name,
                blob_name,
                sheet_name=sheet,
            )
            df = self._try_numeric_conversion(df)

            try:
                result_df, _ = self._apply_query_expression_with_fallback(
                    df,
                    query_expression=query_expression,
                    normalize_match=False,
                )
            except Exception as query_error:
                query_errors.append({
                    'sheet_name': sheet,
                    'error': str(query_error),
                })
                continue

            sheets_searched.append(sheet)
            sheet_matches = len(result_df)
            if sheet_matches == 0:
                continue

            sheets_matched.append(sheet)
            total_matches += sheet_matches
            remaining_capacity = max(0, max_rows - len(combined_results))
            if remaining_capacity > 0:
                for row in result_df.head(remaining_capacity).to_dict(orient='records'):
                    row['_sheet'] = sheet
                    combined_results.append(row)

        if not sheets_searched:
            if query_errors:
                unique_errors = []
                seen_errors = set()
                for query_error in query_errors:
                    normalized_error = str(query_error.get('error') or '').strip()
                    if not normalized_error or normalized_error in seen_errors:
                        continue
                    seen_errors.add(normalized_error)
                    unique_errors.append(normalized_error)

                return json.dumps({
                    "error": (
                        "Query error: the expression could not be evaluated on any worksheet during cross-sheet search. "
                        "Use simple DataFrame.query() syntax with existing column names, or provide sheet_name to target a specific worksheet."
                    ),
                    "filename": filename,
                    "selected_sheet": "ALL (cross-sheet search)",
                    "query_expression": query_expression,
                    "sheets_evaluated": [
                        query_error['sheet_name'] for query_error in query_errors
                    ],
                    "details": unique_errors[:3],
                }, indent=2, default=str)
            return None

        log_event(
            f"[TabularProcessingPlugin] Cross-sheet query_tabular_data: "
            f"searched {len(sheets_searched)} sheets, "
            f"matched on {len(sheets_matched)} ({sheets_matched}), "
            f"total_matches={total_matches}",
            level=logging.INFO,
        )

        return json.dumps({
            "filename": filename,
            "selected_sheet": "ALL (cross-sheet search)",
            "sheets_searched": sheets_searched,
            "sheets_matched": sheets_matched,
            "total_matches": total_matches,
            "returned_rows": len(combined_results),
            "data": combined_results,
        }, indent=2, default=str)

    def _count_rows_across_sheets(
        self,
        container_name: str,
        blob_name: str,
        filename: str,
        filter_column: Optional[str] = None,
        filter_operator: str = 'equals',
        filter_value=None,
        additional_filter_column: Optional[str] = None,
        additional_filter_operator: str = 'equals',
        additional_filter_value=None,
        query_expression: Optional[str] = None,
        normalize_match: bool = False,
    ) -> Optional[str]:
        """Count rows across all worksheets that satisfy optional filters or queries."""
        workbook_metadata = self._get_workbook_metadata(container_name, blob_name)
        if not workbook_metadata.get('is_workbook'):
            return None

        available_sheets = workbook_metadata.get('sheet_names', [])
        if len(available_sheets) <= 1:
            return None

        sheets_searched = []
        sheets_matched = []
        total_count = 0
        query_errors = []
        applied_filters = []

        for sheet in available_sheets:
            df = self._read_tabular_blob_to_dataframe(
                container_name,
                blob_name,
                sheet_name=sheet,
            )
            df = self._try_numeric_conversion(df)

            try:
                filtered_df, sheet_filters = self._apply_optional_dataframe_filters(
                    df,
                    query_expression=query_expression,
                    filter_column=filter_column,
                    filter_operator=filter_operator,
                    filter_value=filter_value,
                    additional_filter_column=additional_filter_column,
                    additional_filter_operator=additional_filter_operator,
                    additional_filter_value=additional_filter_value,
                    normalize_match=normalize_match,
                )
            except KeyError:
                continue
            except Exception as query_error:
                if query_expression:
                    query_errors.append({
                        'sheet_name': sheet,
                        'error': str(query_error),
                    })
                continue

            sheets_searched.append(sheet)
            applied_filters = sheet_filters or applied_filters
            sheet_count = len(filtered_df)
            total_count += sheet_count
            if sheet_count > 0:
                sheets_matched.append(sheet)

        if not sheets_searched:
            if query_errors:
                unique_errors = []
                seen_errors = set()
                for query_error in query_errors:
                    normalized_error = str(query_error.get('error') or '').strip()
                    if not normalized_error or normalized_error in seen_errors:
                        continue
                    seen_errors.add(normalized_error)
                    unique_errors.append(normalized_error)

                return json.dumps({
                    'error': (
                        'Query error: the expression could not be evaluated on any worksheet during cross-sheet row counting. '
                        'Use simple DataFrame.query() syntax with existing column names, or provide sheet_name to target a specific worksheet.'
                    ),
                    'filename': filename,
                    'selected_sheet': 'ALL (cross-sheet search)',
                    'query_expression': query_expression,
                    'details': unique_errors[:3],
                }, indent=2, default=str)
            return None

        return json.dumps({
            'filename': filename,
            'selected_sheet': 'ALL (cross-sheet search)',
            'sheets_searched': sheets_searched,
            'sheets_matched': sheets_matched,
            'filter_applied': applied_filters,
            'row_count': total_count,
            'normalize_match': normalize_match,
        }, indent=2, default=str)

    def _get_distinct_values_across_sheets(
        self,
        container_name: str,
        blob_name: str,
        filename: str,
        column: str,
        query_expression: Optional[str] = None,
        filter_column: Optional[str] = None,
        filter_operator: str = 'equals',
        filter_value=None,
        additional_filter_column: Optional[str] = None,
        additional_filter_operator: str = 'equals',
        additional_filter_value=None,
        extract_mode: Optional[str] = None,
        extract_pattern: Optional[str] = None,
        url_path_segments: Optional[int] = None,
        normalize_match: bool = False,
        max_values: int = 100,
    ) -> Optional[str]:
        """Return distinct values for a column across all worksheets that contain it."""
        workbook_metadata = self._get_workbook_metadata(container_name, blob_name)
        if not workbook_metadata.get('is_workbook'):
            return None

        available_sheets = workbook_metadata.get('sheet_names', [])
        if len(available_sheets) <= 1:
            return None

        sheets_searched = []
        sheets_matched = []
        distinct_display_values = {}
        matched_cell_count = 0
        extracted_match_count = 0
        query_errors = []
        applied_filters = []

        for sheet in available_sheets:
            df = self._read_tabular_blob_to_dataframe(
                container_name,
                blob_name,
                sheet_name=sheet,
            )
            if column not in df.columns:
                continue

            try:
                filtered_df, sheet_filters = self._apply_optional_dataframe_filters(
                    df,
                    query_expression=query_expression,
                    filter_column=filter_column,
                    filter_operator=filter_operator,
                    filter_value=filter_value,
                    additional_filter_column=additional_filter_column,
                    additional_filter_operator=additional_filter_operator,
                    additional_filter_value=additional_filter_value,
                    normalize_match=normalize_match,
                )
            except KeyError:
                continue
            except Exception as query_error:
                if query_expression:
                    query_errors.append({
                        'sheet_name': sheet,
                        'error': str(query_error),
                    })
                continue

            sheets_searched.append(sheet)
            applied_filters = sheet_filters or applied_filters
            sheet_distinct_values, sheet_matched_cells, sheet_extracted_matches = self._collect_distinct_display_values(
                filtered_df[column],
                normalize_match=normalize_match,
                extract_mode=extract_mode,
                extract_pattern=extract_pattern,
                url_path_segments=url_path_segments,
            )
            matched_cell_count += sheet_matched_cells
            extracted_match_count += sheet_extracted_matches
            for canonical_key, display_value in sheet_distinct_values.items():
                distinct_display_values.setdefault(canonical_key, display_value)

            sheet_match_count = sheet_matched_cells if extract_mode else len(filtered_df)
            if sheet_match_count > 0:
                sheets_matched.append(sheet)

        if not sheets_searched:
            if query_errors:
                unique_errors = []
                seen_errors = set()
                for query_error in query_errors:
                    normalized_error = str(query_error.get('error') or '').strip()
                    if not normalized_error or normalized_error in seen_errors:
                        continue
                    seen_errors.add(normalized_error)
                    unique_errors.append(normalized_error)

                return json.dumps({
                    'error': (
                        'Query error: the expression could not be evaluated on any worksheet during cross-sheet distinct-value discovery. '
                        'Use simple DataFrame.query() syntax with existing column names, or provide sheet_name to target a specific worksheet.'
                    ),
                    'filename': filename,
                    'selected_sheet': 'ALL (cross-sheet search)',
                    'query_expression': query_expression,
                    'details': unique_errors[:3],
                }, indent=2, default=str)
            return None

        ordered_values = sorted(distinct_display_values.values(), key=lambda item: item.casefold())
        response_payload = {
            'filename': filename,
            'selected_sheet': 'ALL (cross-sheet search)',
            'column': column,
            'sheets_searched': sheets_searched,
            'sheets_matched': sheets_matched,
            'filter_applied': applied_filters,
            'normalize_match': normalize_match,
            'distinct_count': len(ordered_values),
            'returned_values': min(len(ordered_values), int(max_values)),
            'values': ordered_values[:int(max_values)],
            'values_limited': len(ordered_values) > int(max_values),
        }
        if extract_mode:
            response_payload.update({
                'extract_mode': extract_mode,
                'extract_pattern': extract_pattern if extract_mode == 'regex' else None,
                'url_path_segments': url_path_segments if extract_mode == 'url' else None,
                'matched_cell_count': matched_cell_count,
                'extracted_match_count': extracted_match_count,
            })
        return json.dumps(response_payload, indent=2, default=str)

    def _evaluate_related_value_membership(
        self,
        container_name: str,
        blob_name: str,
        filename: str,
        source_sheet_name: str,
        source_value_column: str,
        target_sheet_name: str,
        target_match_column: str,
        source_sheet_index: Optional[str] = None,
        target_sheet_index: Optional[str] = None,
        source_query_expression: Optional[str] = None,
        source_filter_column: Optional[str] = None,
        source_filter_operator: str = 'equals',
        source_filter_value=None,
        target_query_expression: Optional[str] = None,
        target_filter_column: Optional[str] = None,
        target_filter_operator: str = 'equals',
        target_filter_value=None,
        source_alias_column: Optional[str] = None,
        target_alias_column: Optional[str] = None,
        normalize_match: bool = True,
        max_rows: int = 100,
    ) -> dict:
        """Evaluate a semi-join between a source cohort and a target fact worksheet."""
        source_sheet, workbook_metadata = self._resolve_sheet_selection(
            container_name,
            blob_name,
            sheet_name=source_sheet_name,
            sheet_index=source_sheet_index,
            require_explicit_sheet=True,
        )
        target_sheet, workbook_metadata = self._resolve_sheet_selection(
            container_name,
            blob_name,
            sheet_name=target_sheet_name,
            sheet_index=target_sheet_index,
            require_explicit_sheet=True,
        )

        source_df = self._read_tabular_blob_to_dataframe(
            container_name,
            blob_name,
            sheet_name=source_sheet,
            require_explicit_sheet=True,
        )
        target_df = self._read_tabular_blob_to_dataframe(
            container_name,
            blob_name,
            sheet_name=target_sheet,
            require_explicit_sheet=True,
        )

        source_df = self._try_numeric_conversion(source_df)
        target_df = self._try_numeric_conversion(target_df)

        source_required_columns = [source_value_column]
        if source_alias_column:
            source_required_columns.append(source_alias_column)
        if source_filter_column:
            source_required_columns.append(source_filter_column)

        target_required_columns = [target_match_column]
        if target_alias_column:
            target_required_columns.append(target_alias_column)
        if target_filter_column:
            target_required_columns.append(target_filter_column)

        for required_column in source_required_columns:
            if required_column not in source_df.columns:
                return self._build_missing_column_error_payload(
                    container_name,
                    blob_name,
                    filename,
                    workbook_metadata,
                    source_sheet,
                    required_column,
                    related_columns=[source_value_column, source_alias_column, source_filter_column],
                    available_columns=list(source_df.columns),
                )

        for required_column in target_required_columns:
            if required_column not in target_df.columns:
                return self._build_missing_column_error_payload(
                    container_name,
                    blob_name,
                    filename,
                    workbook_metadata,
                    target_sheet,
                    required_column,
                    related_columns=[target_match_column, target_alias_column, target_filter_column],
                    available_columns=list(target_df.columns),
                )

        try:
            filtered_source_df, source_filters = self._apply_optional_dataframe_filters(
                source_df,
                query_expression=source_query_expression,
                filter_column=source_filter_column,
                filter_operator=source_filter_operator,
                filter_value=source_filter_value,
                normalize_match=normalize_match,
            )
        except KeyError as missing_source_column_error:
            missing_source_column = str(missing_source_column_error).strip("'")
            return self._build_missing_column_error_payload(
                container_name,
                blob_name,
                filename,
                workbook_metadata,
                source_sheet,
                missing_source_column,
                related_columns=[source_value_column, source_alias_column],
                available_columns=list(source_df.columns),
            )
        except Exception as source_filter_error:
            return {
                'error': f"Source filter/query error on sheet '{source_sheet}': {source_filter_error}",
                'filename': filename,
                'selected_sheet': source_sheet if workbook_metadata.get('is_workbook') else None,
            }

        try:
            filtered_target_df, target_filters = self._apply_optional_dataframe_filters(
                target_df,
                query_expression=target_query_expression,
                filter_column=target_filter_column,
                filter_operator=target_filter_operator,
                filter_value=target_filter_value,
                normalize_match=normalize_match,
            )
        except KeyError as missing_target_column_error:
            missing_target_column = str(missing_target_column_error).strip("'")
            return self._build_missing_column_error_payload(
                container_name,
                blob_name,
                filename,
                workbook_metadata,
                target_sheet,
                missing_target_column,
                related_columns=[target_match_column, target_alias_column],
                available_columns=list(target_df.columns),
            )
        except Exception as target_filter_error:
            return {
                'error': f"Target filter/query error on sheet '{target_sheet}': {target_filter_error}",
                'filename': filename,
                'selected_sheet': target_sheet if workbook_metadata.get('is_workbook') else None,
            }

        source_member_map = {}
        variant_to_source_keys = {}
        for _, source_row in filtered_source_df.iterrows():
            display_value = str(source_row.get(source_value_column, '')).strip()
            value_variants = set()
            for column_name in [source_value_column, source_alias_column]:
                if not column_name:
                    continue
                value_variants.update(
                    self._extract_cell_value_variants(
                        source_row.get(column_name),
                        normalize_match=normalize_match,
                    )
                )

            if not value_variants:
                continue

            primary_variants = self._extract_cell_value_variants(
                source_row.get(source_value_column),
                normalize_match=normalize_match,
            )
            primary_key = sorted(primary_variants or value_variants)[0]
            existing_member = source_member_map.setdefault(
                primary_key,
                {
                    'display_value': display_value or primary_key,
                    'value_variants': set(),
                    'matched_target_row_count': 0,
                },
            )
            existing_member['value_variants'].update(value_variants)
            for value_variant in value_variants:
                variant_to_source_keys.setdefault(value_variant, set()).add(primary_key)

        source_compare_values = set()
        for source_member in source_member_map.values():
            source_compare_values.update(source_member['value_variants'])

        matched_target_rows = []
        matched_target_value_variants = set()
        for _, target_row in filtered_target_df.iterrows():
            target_value_variants = set()
            for column_name in [target_match_column, target_alias_column]:
                if not column_name:
                    continue
                target_value_variants.update(
                    self._extract_cell_value_variants(
                        target_row.get(column_name),
                        normalize_match=normalize_match,
                    )
                )

            matched_variants = sorted(target_value_variants & source_compare_values)
            if not matched_variants:
                continue

            matched_source_keys = sorted({
                source_key
                for matched_variant in matched_variants
                for source_key in variant_to_source_keys.get(matched_variant, set())
            })
            if not matched_source_keys:
                continue

            matched_target_value_variants.update(matched_variants)
            for source_key in matched_source_keys:
                source_member_map[source_key]['matched_target_row_count'] += 1

            matched_row_payload = target_row.to_dict()
            matched_row_payload['_matched_on'] = matched_variants[:3]
            matched_row_payload['_matched_source_values'] = [
                source_member_map[source_key]['display_value']
                for source_key in matched_source_keys[:3]
            ]
            matched_target_rows.append(matched_row_payload)

        matched_source_values = []
        unmatched_source_values = []
        for source_member in source_member_map.values():
            if source_member['matched_target_row_count'] > 0:
                matched_source_values.append(source_member['display_value'])
            else:
                unmatched_source_values.append(source_member['display_value'])

        source_value_match_counts = sorted(
            [
                {
                    'source_value': source_member['display_value'],
                    'matched_target_row_count': source_member['matched_target_row_count'],
                }
                for source_member in source_member_map.values()
            ],
            key=lambda item: (-item['matched_target_row_count'], item['source_value'].casefold())
        )
        source_value_match_count_limit = self.SOURCE_VALUE_MATCH_COUNT_LIMIT

        matched_target_row_count = len(matched_target_rows)
        return {
            'filename': filename,
            'selected_sheet': target_sheet if workbook_metadata.get('is_workbook') else None,
            'relationship_type': 'set_membership',
            'source_sheet': source_sheet,
            'source_value_column': source_value_column,
            'source_alias_column': source_alias_column,
            'target_sheet': target_sheet,
            'target_match_column': target_match_column,
            'target_alias_column': target_alias_column,
            'normalize_match': normalize_match,
            'source_filter_applied': source_filters,
            'target_filter_applied': target_filters,
            'source_cohort_size': len(source_member_map),
            'matched_source_value_count': len(matched_source_values),
            'matched_source_values_sample': matched_source_values[:10],
            'unmatched_source_value_count': len(unmatched_source_values),
            'unmatched_source_values_sample': unmatched_source_values[:10],
            'source_value_match_counts_returned': min(len(source_value_match_counts), source_value_match_count_limit),
            'source_value_match_counts_limited': len(source_value_match_counts) > source_value_match_count_limit,
            'source_value_match_counts': source_value_match_counts[:source_value_match_count_limit],
            'target_rows_scanned': len(filtered_target_df),
            'matched_target_row_count': matched_target_row_count,
            'returned_rows': min(matched_target_row_count, max_rows),
            'rows_limited': matched_target_row_count > max_rows,
            'data': matched_target_rows[:max_rows],
        }

    def _format_datetime_column_label(self, value) -> str:
        """Render date-like Excel header labels into stable analysis-friendly strings."""
        timestamp_value = pandas.Timestamp(value)

        if (
            timestamp_value.hour == 0
            and timestamp_value.minute == 0
            and timestamp_value.second == 0
            and timestamp_value.microsecond == 0
        ):
            if timestamp_value.day == 1:
                return timestamp_value.strftime('%b-%y')
            return timestamp_value.strftime('%Y-%m-%d')

        return timestamp_value.strftime('%Y-%m-%d %H:%M:%S')

    def _normalize_column_label(self, label, fallback_index: int) -> str:
        """Convert arbitrary DataFrame column labels into stable string names."""
        if label is None or (not isinstance(label, str) and pandas.isna(label)):
            return f"Column {fallback_index}"

        if isinstance(label, pandas.Timestamp):
            return self._format_datetime_column_label(label)

        if isinstance(label, datetime):
            return self._format_datetime_column_label(label)

        if isinstance(label, date):
            return self._format_datetime_column_label(datetime.combine(label, datetime.min.time()))

        normalized_label = str(label).strip()
        return normalized_label or f"Column {fallback_index}"

    def _normalize_dataframe_columns(self, df: pandas.DataFrame) -> pandas.DataFrame:
        """Rename DataFrame columns to unique, JSON-safe string labels."""
        normalized_df = df.copy()
        normalized_columns = []
        normalized_label_counts = {}

        for column_index, column_label in enumerate(normalized_df.columns, start=1):
            base_label = self._normalize_column_label(column_label, column_index)
            occurrence_count = normalized_label_counts.get(base_label, 0) + 1
            normalized_label_counts[base_label] = occurrence_count

            if occurrence_count == 1:
                normalized_columns.append(base_label)
            else:
                normalized_columns.append(f"{base_label} ({occurrence_count})")

        normalized_df.columns = normalized_columns
        return normalized_df

    def _normalize_entity_match_text(self, value) -> Optional[str]:
        """Normalize entity-style text for stable name and owner comparisons."""
        if value is None or (not isinstance(value, str) and pandas.isna(value)):
            return None

        normalized = str(value).casefold().replace('&', ' and ')
        normalized = re.sub(r"[`'\u2018\u2019\u201b]+", '', normalized)
        normalized = re.sub(r'[^0-9a-z]+', ' ', normalized)
        normalized = ' '.join(normalized.split())
        return normalized or None

    def _extract_cell_value_variants(self, value, normalize_match: bool = False) -> Set[str]:
        """Return one or more comparable value variants from a cell, including aliases."""
        if value is None or (not isinstance(value, str) and pandas.isna(value)):
            return set()

        raw_text = str(value).strip()
        if not raw_text:
            return set()

        parts = [raw_text]
        if ';' in raw_text or '|' in raw_text:
            split_parts = re.split(r'[;|]+', raw_text)
            parts = [part.strip() for part in split_parts if part.strip()]

        variants = set()
        for part in parts:
            if normalize_match:
                normalized_part = self._normalize_entity_match_text(part)
            else:
                normalized_part = part.casefold().strip()
            if normalized_part:
                variants.add(normalized_part)

        return variants

    def _normalize_distinct_extraction_arguments(
        self,
        extract_mode: Optional[str] = None,
        extract_pattern: Optional[str] = None,
        url_path_segments: Optional[str] = None,
    ) -> tuple:
        """Validate and normalize optional embedded extraction arguments."""
        normalized_extract_mode = str(extract_mode or '').strip().lower() or None
        if normalized_extract_mode not in {None, 'url', 'regex'}:
            raise ValueError("Unsupported extract_mode. Use 'url' or 'regex'.")

        normalized_extract_pattern = str(extract_pattern or '').strip() or None
        if normalized_extract_mode == 'regex' and not normalized_extract_pattern:
            raise ValueError('extract_pattern is required when extract_mode is regex.')
        if normalized_extract_mode != 'regex':
            normalized_extract_pattern = None

        parsed_url_path_segments = None
        if url_path_segments not in (None, ''):
            try:
                parsed_url_path_segments = int(url_path_segments)
            except (TypeError, ValueError):
                raise ValueError('url_path_segments must be an integer when provided.')
            if parsed_url_path_segments < 0:
                raise ValueError('url_path_segments must be zero or greater when provided.')

        if normalized_extract_mode != 'url':
            parsed_url_path_segments = None

        return normalized_extract_mode, normalized_extract_pattern, parsed_url_path_segments

    def _normalize_embedded_url_match(self, raw_match, url_path_segments: Optional[int] = None) -> Optional[str]:
        """Normalize an extracted URL for stable distinct-value analysis."""
        cleaned_match = str(raw_match or '').strip().rstrip('.,;:!?)]}\"\'')
        if not cleaned_match:
            return None

        parsed_url = urlsplit(cleaned_match)
        if not parsed_url.scheme or not parsed_url.netloc:
            return cleaned_match

        path_segments = [segment for segment in parsed_url.path.split('/') if segment]
        if url_path_segments is not None:
            path_segments = path_segments[:url_path_segments]

        normalized_path = ''
        if path_segments:
            normalized_path = '/' + '/'.join(path_segments)

        return urlunsplit((
            parsed_url.scheme.lower(),
            parsed_url.netloc.lower(),
            normalized_path,
            '',
            '',
        ))

    def _extract_embedded_matches_from_text(
        self,
        value,
        extract_mode: Optional[str] = None,
        extract_pattern: Optional[str] = None,
        url_path_segments: Optional[int] = None,
    ) -> List[str]:
        """Extract embedded URL or regex matches from a composite text cell."""
        if value is None or (not isinstance(value, str) and pandas.isna(value)):
            return []

        rendered_text = str(value).strip()
        if not rendered_text or not extract_mode:
            return []

        normalized_extract_mode = str(extract_mode or '').strip().lower()
        extracted_matches = []

        if normalized_extract_mode == 'url':
            for raw_match in re.findall(r'https?://[^\s<>"\'\]\)]+', rendered_text, flags=re.IGNORECASE):
                normalized_match = self._normalize_embedded_url_match(
                    raw_match,
                    url_path_segments=url_path_segments,
                )
                if normalized_match:
                    extracted_matches.append(normalized_match)
        elif normalized_extract_mode == 'regex':
            compiled_pattern = re.compile(extract_pattern, flags=re.IGNORECASE)
            for match in compiled_pattern.finditer(rendered_text):
                candidate_value = None
                if match.lastindex:
                    for group_value in match.groups():
                        if group_value:
                            candidate_value = group_value
                            break
                if candidate_value is None:
                    candidate_value = match.group(0)

                cleaned_candidate = str(candidate_value or '').strip().rstrip('.,;:!?)]}\"\'')
                if cleaned_candidate:
                    extracted_matches.append(cleaned_candidate)
        else:
            raise ValueError("Unsupported extract_mode. Use 'url' or 'regex'.")

        unique_matches = []
        seen_matches = set()
        for extracted_match in extracted_matches:
            canonical_match = str(extracted_match).casefold().strip()
            if not canonical_match or canonical_match in seen_matches:
                continue
            seen_matches.add(canonical_match)
            unique_matches.append(str(extracted_match).strip())

        return unique_matches

    def _collect_distinct_value_candidates(
        self,
        value,
        normalize_match: bool = False,
        extract_mode: Optional[str] = None,
        extract_pattern: Optional[str] = None,
        url_path_segments: Optional[int] = None,
    ) -> List[dict]:
        """Return display/canonical pairs for raw or embedded distinct-value extraction."""
        normalized_extract_mode = str(extract_mode or '').strip().lower() or None

        if normalized_extract_mode:
            candidates = []
            for extracted_match in self._extract_embedded_matches_from_text(
                value,
                extract_mode=normalized_extract_mode,
                extract_pattern=extract_pattern,
                url_path_segments=url_path_segments,
            ):
                display_value = str(extracted_match).strip()
                if not display_value:
                    continue

                if normalized_extract_mode == 'url':
                    canonical_key = display_value.casefold()
                elif normalize_match:
                    canonical_key = self._normalize_entity_match_text(display_value)
                else:
                    canonical_key = display_value.casefold()

                if not canonical_key:
                    continue

                candidates.append({
                    'display_value': display_value,
                    'canonical_key': canonical_key,
                })

            return candidates

        if value is None or (not isinstance(value, str) and pandas.isna(value)):
            return []

        display_value = str(value).strip()
        if not display_value:
            return []

        compare_variants = self._extract_cell_value_variants(
            value,
            normalize_match=normalize_match,
        )
        if not compare_variants:
            return []

        return [{
            'display_value': display_value,
            'canonical_key': sorted(compare_variants)[0],
        }]

    def _collect_distinct_display_values(
        self,
        series: pandas.Series,
        normalize_match: bool = False,
        extract_mode: Optional[str] = None,
        extract_pattern: Optional[str] = None,
        url_path_segments: Optional[int] = None,
    ) -> tuple:
        """Collect display values and counts for deterministic distinct-value analysis."""
        distinct_display_values = {}
        matched_cell_count = 0
        extracted_match_count = 0

        for cell_value in series.tolist():
            candidates = self._collect_distinct_value_candidates(
                cell_value,
                normalize_match=normalize_match,
                extract_mode=extract_mode,
                extract_pattern=extract_pattern,
                url_path_segments=url_path_segments,
            )
            if not candidates:
                continue

            matched_cell_count += 1
            extracted_match_count += len(candidates)
            for candidate in candidates:
                distinct_display_values.setdefault(
                    candidate['canonical_key'],
                    candidate['display_value'],
                )

        return distinct_display_values, matched_cell_count, extracted_match_count

    def _parse_optional_column_list_argument(self, raw_columns) -> Optional[List[str]]:
        """Parse an optional comma-separated or JSON-array column list argument."""
        if raw_columns is None:
            return None

        candidate_values = None
        if isinstance(raw_columns, (list, tuple, set)):
            candidate_values = list(raw_columns)
        else:
            rendered_columns = str(raw_columns).strip()
            if not rendered_columns:
                return None
            if rendered_columns.casefold() in {'*', 'all', 'all_columns', 'all columns'}:
                return None

            if rendered_columns.startswith('['):
                try:
                    parsed_columns = json.loads(rendered_columns)
                except Exception:
                    parsed_columns = None
                if isinstance(parsed_columns, list):
                    candidate_values = parsed_columns

            if candidate_values is None:
                candidate_values = re.split(r'[,;|\n]+', rendered_columns)

        normalized_columns = []
        seen_columns = set()
        for candidate_value in candidate_values:
            normalized_column = str(candidate_value or '').strip()
            if not normalized_column:
                continue
            lowered_column = normalized_column.casefold()
            if lowered_column in seen_columns:
                continue
            seen_columns.add(lowered_column)
            normalized_columns.append(normalized_column)

        return normalized_columns or None

    def _search_dataframe_rows(
        self,
        df: pandas.DataFrame,
        search_value,
        search_columns=None,
        search_operator: str = 'contains',
        return_columns=None,
        normalize_match: bool = False,
        max_rows: int = 100,
    ) -> dict:
        """Search one or more columns in a DataFrame and return row-context results."""
        requested_search_columns = self._parse_optional_column_list_argument(search_columns)
        requested_return_columns = self._parse_optional_column_list_argument(return_columns)

        if requested_search_columns:
            resolved_search_columns = [
                column_name for column_name in requested_search_columns
                if column_name in df.columns
            ]
            if not resolved_search_columns:
                raise KeyError(requested_search_columns[0])
        else:
            resolved_search_columns = list(df.columns)

        resolved_return_columns = [
            column_name for column_name in (requested_return_columns or [])
            if column_name in df.columns
        ]

        combined_mask = pandas.Series([False] * len(df), index=df.index)
        column_masks = {}
        for column_name in resolved_search_columns:
            column_mask = self._build_series_match_mask(
                df[column_name],
                search_operator,
                search_value,
                normalize_match=normalize_match,
            ).fillna(False)
            column_masks[column_name] = column_mask
            combined_mask = combined_mask | column_mask

        matched_df = df[combined_mask]
        matched_columns = []
        seen_matched_columns = set()
        result_rows = []

        for row_index, row in matched_df.head(int(max_rows)).iterrows():
            row_matched_columns = []
            for column_name in resolved_search_columns:
                if not bool(column_masks[column_name].loc[row_index]):
                    continue
                row_matched_columns.append(column_name)
                lowered_column = column_name.casefold()
                if lowered_column not in seen_matched_columns:
                    seen_matched_columns.add(lowered_column)
                    matched_columns.append(column_name)

            if resolved_return_columns:
                row_payload = {
                    column_name: row.get(column_name)
                    for column_name in resolved_return_columns
                }
            else:
                row_payload = {
                    str(key): value for key, value in row.to_dict().items()
                }

            row_payload['_matched_columns'] = row_matched_columns
            row_payload['_matched_values'] = {
                column_name: row.get(column_name)
                for column_name in row_matched_columns
            }
            result_rows.append(row_payload)

        return {
            'searched_columns': resolved_search_columns,
            'matched_columns': matched_columns,
            'return_columns': resolved_return_columns or None,
            'total_matches': len(matched_df),
            'returned_rows': len(result_rows),
            'data': result_rows,
        }

    def _build_series_match_mask(
        self,
        series: pandas.Series,
        operator: str,
        value,
        normalize_match: bool = False,
    ) -> pandas.Series:
        """Build a boolean mask for a comparison against a DataFrame column."""
        op = (operator or 'equals').strip().lower()

        numeric_value = None
        try:
            numeric_value = float(value)
        except (ValueError, TypeError):
            numeric_value = None

        if op in {'==', 'equals'}:
            if numeric_value is not None and pandas.api.types.is_numeric_dtype(series):
                return series == numeric_value
            if normalize_match:
                normalized_value = self._normalize_entity_match_text(value)
                normalized_series = series.map(self._normalize_entity_match_text)
                return normalized_series == normalized_value
            return series.astype(str).str.lower() == str(value).lower()

        if op == '!=':
            if numeric_value is not None and pandas.api.types.is_numeric_dtype(series):
                return series != numeric_value
            if normalize_match:
                normalized_value = self._normalize_entity_match_text(value)
                normalized_series = series.map(self._normalize_entity_match_text)
                return normalized_series != normalized_value
            return series.astype(str).str.lower() != str(value).lower()

        if op == '>':
            if numeric_value is None:
                return pandas.Series([False] * len(series), index=series.index)
            return series > numeric_value

        if op == '<':
            if numeric_value is None:
                return pandas.Series([False] * len(series), index=series.index)
            return series < numeric_value

        if op == '>=':
            if numeric_value is None:
                return pandas.Series([False] * len(series), index=series.index)
            return series >= numeric_value

        if op == '<=':
            if numeric_value is None:
                return pandas.Series([False] * len(series), index=series.index)
            return series <= numeric_value

        if normalize_match:
            normalized_value = self._normalize_entity_match_text(value)
            normalized_series = series.map(self._normalize_entity_match_text).fillna('')
            if not normalized_value:
                return pandas.Series([False] * len(series), index=series.index)

            if op == 'contains':
                return normalized_series.str.contains(normalized_value, regex=False, na=False)
            if op == 'startswith':
                return normalized_series.str.startswith(normalized_value, na=False)
            if op == 'endswith':
                return normalized_series.str.endswith(normalized_value, na=False)
        else:
            text_series = series.astype(str)
            value_text = str(value)
            if op == 'contains':
                return text_series.str.contains(value_text, case=False, na=False)
            if op == 'startswith':
                return text_series.str.lower().str.startswith(value_text.lower())
            if op == 'endswith':
                return text_series.str.lower().str.endswith(value_text.lower())

        raise ValueError(f"Unsupported operator: {operator}")

    def _normalize_pseudo_query_column_reference(self, raw_column_name: str) -> str:
        """Normalize a reviewer-style query column reference into a DataFrame column name."""
        normalized_column_name = str(raw_column_name or '').strip()
        if normalized_column_name.startswith('`') and normalized_column_name.endswith('`'):
            normalized_column_name = normalized_column_name[1:-1]
        return normalized_column_name.strip()

    def _build_pseudo_query_string_method_mask(
        self,
        series: pandas.Series,
        operator: str,
        value,
        case_sensitive: bool = False,
        normalize_match: bool = False,
    ) -> pandas.Series:
        """Build a boolean mask for reviewer-style string method clauses."""
        if normalize_match and not case_sensitive:
            return self._build_series_match_mask(
                series,
                operator,
                value,
                normalize_match=True,
            )

        if not case_sensitive:
            return self._build_series_match_mask(
                series,
                operator,
                value,
                normalize_match=False,
            )

        text_series = series.astype(str)
        value_text = str(value)
        if operator == 'contains':
            return text_series.str.contains(value_text, regex=False, case=True, na=False)
        if operator == 'startswith':
            return text_series.str.startswith(value_text, na=False)
        if operator == 'endswith':
            return text_series.str.endswith(value_text, na=False)

        raise ValueError(f"Unsupported operator: {operator}")

    def _apply_reviewer_style_query_expression(
        self,
        df: pandas.DataFrame,
        query_expression: str,
        normalize_match: bool = False,
    ) -> Optional[pandas.DataFrame]:
        """Apply limited reviewer-style pseudo-pandas filters when DataFrame.query syntax is invalid."""
        rendered_query_expression = str(query_expression or '').strip()
        if not rendered_query_expression:
            return df

        lowered_expression = rendered_query_expression.casefold()
        if ' or ' in lowered_expression or '||' in rendered_query_expression or '|' in rendered_query_expression:
            return None

        clause_texts = [
            clause.strip()
            for clause in re.split(r'\s+(?i:and)\s+|&&', rendered_query_expression)
            if clause.strip()
        ]
        if not clause_texts:
            return None

        notnull_pattern = re.compile(
            r"^\s*(?P<column>`[^`]+`|[A-Za-z_][A-Za-z0-9_]*)\s*\.\s*notnull\(\)\s*$",
            flags=re.IGNORECASE,
        )
        isnull_pattern = re.compile(
            r"^\s*(?P<column>`[^`]+`|[A-Za-z_][A-Za-z0-9_]*)\s*\.\s*isnull\(\)\s*$",
            flags=re.IGNORECASE,
        )
        string_method_pattern = re.compile(
            r"^\s*(?P<column>`[^`]+`|[A-Za-z_][A-Za-z0-9_]*)"
            r"(?:\s*\.\s*astype\(\s*str\s*\))?\s*\.\s*str\s*\.\s*"
            r"(?P<method>contains|startswith|endswith)\(\s*"
            r"(?P<quote>['\"])(?P<value>.*?)(?P=quote)(?P<args>[^)]*)\)\s*$",
            flags=re.IGNORECASE,
        )
        equality_pattern = re.compile(
            r"^\s*(?P<column>`[^`]+`|[A-Za-z_][A-Za-z0-9_]*)\s*"
            r"(?P<operator>==|!=)\s*"
            r"(?P<quote>['\"])(?P<value>.*?)(?P=quote)\s*$",
            flags=re.IGNORECASE,
        )
        null_literal_pattern = re.compile(
            r"^\s*(?P<column>`[^`]+`|[A-Za-z_][A-Za-z0-9_]*)\s*"
            r"(?P<operator>==|!=)\s*"
            r"(?P<null_literal>null|none|nan)\s*$",
            flags=re.IGNORECASE,
        )

        filtered_df = df
        matched_any_clause = False

        for clause_text in clause_texts:
            normalized_clause_text = clause_text.strip()
            while normalized_clause_text.startswith('(') and normalized_clause_text.endswith(')'):
                normalized_clause_text = normalized_clause_text[1:-1].strip()

            match = notnull_pattern.match(normalized_clause_text)
            if match:
                column_name = self._normalize_pseudo_query_column_reference(match.group('column'))
                if column_name not in filtered_df.columns:
                    raise KeyError(column_name)
                filtered_df = filtered_df[filtered_df[column_name].notna()]
                matched_any_clause = True
                continue

            match = isnull_pattern.match(normalized_clause_text)
            if match:
                column_name = self._normalize_pseudo_query_column_reference(match.group('column'))
                if column_name not in filtered_df.columns:
                    raise KeyError(column_name)
                filtered_df = filtered_df[filtered_df[column_name].isna()]
                matched_any_clause = True
                continue

            match = string_method_pattern.match(normalized_clause_text)
            if match:
                column_name = self._normalize_pseudo_query_column_reference(match.group('column'))
                if column_name not in filtered_df.columns:
                    raise KeyError(column_name)

                method_name = str(match.group('method') or '').strip().lower()
                operator_name = {
                    'contains': 'contains',
                    'startswith': 'startswith',
                    'endswith': 'endswith',
                }.get(method_name)
                if not operator_name:
                    return None

                args_text = str(match.group('args') or '').replace(' ', '').casefold()
                if 'regex=true' in args_text:
                    return None
                case_sensitive = 'case=true' in args_text

                mask = self._build_pseudo_query_string_method_mask(
                    filtered_df[column_name],
                    operator_name,
                    match.group('value'),
                    case_sensitive=case_sensitive,
                    normalize_match=normalize_match,
                )
                filtered_df = filtered_df[mask]
                matched_any_clause = True
                continue

            match = equality_pattern.match(normalized_clause_text)
            if match:
                column_name = self._normalize_pseudo_query_column_reference(match.group('column'))
                if column_name not in filtered_df.columns:
                    raise KeyError(column_name)

                operator_name = 'equals' if match.group('operator') == '==' else '!='
                mask = self._build_series_match_mask(
                    filtered_df[column_name],
                    operator_name,
                    match.group('value'),
                    normalize_match=normalize_match,
                )
                filtered_df = filtered_df[mask]
                matched_any_clause = True
                continue

            match = null_literal_pattern.match(normalized_clause_text)
            if match:
                column_name = self._normalize_pseudo_query_column_reference(match.group('column'))
                if column_name not in filtered_df.columns:
                    raise KeyError(column_name)

                if match.group('operator') == '==':
                    filtered_df = filtered_df[filtered_df[column_name].isna()]
                else:
                    filtered_df = filtered_df[filtered_df[column_name].notna()]
                matched_any_clause = True
                continue

            return None

        return filtered_df if matched_any_clause else None

    def _apply_query_expression_with_fallback(
        self,
        df: pandas.DataFrame,
        query_expression: Optional[str] = None,
        normalize_match: bool = False,
    ) -> tuple:
        """Apply DataFrame.query syntax first, then fall back to limited reviewer-style parsing."""
        if not query_expression:
            return df, False

        try:
            return df.query(query_expression), False
        except Exception as query_error:
            fallback_df = self._apply_reviewer_style_query_expression(
                df,
                query_expression,
                normalize_match=normalize_match,
            )
            if fallback_df is not None:
                return fallback_df, True
            raise query_error

    def _apply_optional_dataframe_filters(
        self,
        df: pandas.DataFrame,
        query_expression: Optional[str] = None,
        filter_column: Optional[str] = None,
        filter_operator: str = 'equals',
        filter_value=None,
        additional_filter_column: Optional[str] = None,
        additional_filter_operator: str = 'equals',
        additional_filter_value=None,
        normalize_match: bool = False,
    ) -> tuple:
        """Apply optional query and up to two single-column filters to a DataFrame."""
        filtered_df = df
        applied_filters = []

        if query_expression:
            filtered_df, used_reviewer_style_fallback = self._apply_query_expression_with_fallback(
                filtered_df,
                query_expression=query_expression,
                normalize_match=normalize_match,
            )
            applied_filters.append(
                f"query_expression={query_expression}"
                + (' [reviewer-style fallback]' if used_reviewer_style_fallback else '')
            )

        structured_filters = [
            {
                'column': filter_column,
                'operator': filter_operator,
                'value': filter_value,
                'column_argument': 'filter_column',
                'value_argument': 'filter_value',
            },
            {
                'column': additional_filter_column,
                'operator': additional_filter_operator,
                'value': additional_filter_value,
                'column_argument': 'additional_filter_column',
                'value_argument': 'additional_filter_value',
            },
        ]

        for filter_spec in structured_filters:
            current_filter_column = filter_spec['column']
            if not current_filter_column:
                continue

            if current_filter_column not in filtered_df.columns:
                raise KeyError(current_filter_column)

            current_filter_value = filter_spec['value']
            if current_filter_value is None:
                raise ValueError(
                    f"{filter_spec['value_argument']} is required when {filter_spec['column_argument']} is provided."
                )

            current_filter_operator = filter_spec['operator'] or 'equals'
            mask = self._build_series_match_mask(
                filtered_df[current_filter_column],
                current_filter_operator,
                current_filter_value,
                normalize_match=normalize_match,
            )
            filtered_df = filtered_df[mask]
            applied_filters.append(
                f"{current_filter_column} {current_filter_operator} {current_filter_value}"
                + (' [normalized]' if normalize_match else '')
            )

        return filtered_df, applied_filters

    def _column_name_tokens(self, column_name: str) -> List[str]:
        """Tokenize a column label for relationship heuristics."""
        normalized = re.sub(r'[^0-9a-z]+', ' ', str(column_name or '').casefold())
        return [token for token in normalized.split() if token]

    def _build_relationship_column_profile(self, column_name: str, series: pandas.Series) -> dict:
        """Build a compact column profile used for workbook relationship inference."""
        tokens = self._column_name_tokens(column_name)
        non_null_series = series.dropna()
        name_hint_score = sum(1 for token in tokens if token in self.RELATIONSHIP_COLUMN_HINT_TOKENS)
        is_identifier_like = any(token == 'id' or token.endswith('id') for token in tokens)
        is_entity_like = name_hint_score > 0 or is_identifier_like
        distinct_count = int(non_null_series.astype(str).nunique(dropna=True)) if not non_null_series.empty else 0

        normalized_values = []
        seen_values = set()
        for raw_value in non_null_series.astype(str):
            normalized_value = self._normalize_entity_match_text(raw_value)
            if not normalized_value or normalized_value in seen_values:
                continue
            seen_values.add(normalized_value)
            normalized_values.append(normalized_value)
            if len(normalized_values) >= self.RELATIONSHIP_VALUE_SAMPLE_LIMIT:
                break

        return {
            'column_name': column_name,
            'normalized_column_name': ' '.join(tokens),
            'tokens': tokens,
            'name_hint_score': name_hint_score,
            'is_identifier_like': is_identifier_like,
            'is_entity_like': is_entity_like,
            'distinct_count': distinct_count,
            'normalized_value_set': set(normalized_values),
            'sample_distinct_count': len(normalized_values),
            'is_numeric': pandas.api.types.is_numeric_dtype(series),
        }

    def _infer_sheet_role_hint(self, sheet_name: str, row_count: int, column_profiles: List[dict], max_row_count: int) -> dict:
        """Infer whether a worksheet looks like a fact, dimension, or metadata table."""
        normalized_sheet_name = str(sheet_name or '').casefold()
        entity_profiles = [profile for profile in column_profiles if profile['is_entity_like']]
        natural_key_profiles = [
            profile for profile in entity_profiles
            if profile['distinct_count'] >= max(2, row_count - 1)
        ]
        repeated_entity_profiles = [
            profile for profile in entity_profiles
            if 0 < profile['distinct_count'] < row_count
        ]
        join_columns = [
            profile['column_name']
            for profile in sorted(
                column_profiles,
                key=lambda item: (-item['name_hint_score'], item['distinct_count'], item['column_name'].casefold())
            )
            if profile['is_entity_like']
        ][:5]

        if any(token in normalized_sheet_name for token in ('meta', 'config', 'summary', 'readme', 'about')):
            return {
                'role': 'metadata',
                'reason': 'sheet name suggests metadata or workbook configuration',
                'row_count': row_count,
                'likely_join_columns': join_columns,
            }

        if row_count >= max(25, max_row_count // 2 or 1) and repeated_entity_profiles:
            return {
                'role': 'fact',
                'reason': 'larger table contains repeated entity values consistent with transactional rows',
                'row_count': row_count,
                'likely_join_columns': join_columns,
            }

        if natural_key_profiles and row_count <= max(200, max_row_count // 4 or 1):
            return {
                'role': 'dimension',
                'reason': 'smaller table contains near-unique entity keys suitable for cohort or lookup joins',
                'row_count': row_count,
                'likely_join_columns': join_columns,
            }

        if row_count <= 5 and not entity_profiles and len(column_profiles) <= 6:
            return {
                'role': 'metadata',
                'reason': 'very small table with limited columns',
                'row_count': row_count,
                'likely_join_columns': join_columns,
            }

        if join_columns and row_count <= max(200, max_row_count // 4 or 1):
            return {
                'role': 'dimension',
                'reason': 'smaller table with entity-like or identifier-like columns',
                'row_count': row_count,
                'likely_join_columns': join_columns,
            }

        if row_count >= max(25, max_row_count // 2 or 1):
            return {
                'role': 'fact',
                'reason': 'larger table likely containing repeated transactional or milestone-style rows',
                'row_count': row_count,
                'likely_join_columns': join_columns,
            }

        return {
            'role': 'unknown',
            'reason': 'insufficient evidence to confidently classify worksheet role',
            'row_count': row_count,
            'likely_join_columns': join_columns,
        }

    def _build_workbook_relationship_metadata(self, sheet_dataframes: Dict[str, pandas.DataFrame]) -> dict:
        """Infer likely worksheet roles and relationship hints from workbook data."""
        if len(sheet_dataframes) <= 1:
            return {
                'sheet_role_hints': {},
                'relationship_hints': [],
            }

        max_row_count = max((len(dataframe) for dataframe in sheet_dataframes.values()), default=0)
        column_profiles_by_sheet = {}
        sheet_role_hints = {}

        for sheet_name, dataframe in sheet_dataframes.items():
            column_profiles = [
                self._build_relationship_column_profile(column_name, dataframe[column_name])
                for column_name in dataframe.columns
            ]
            candidate_profiles = [
                profile for profile in column_profiles
                if profile['is_entity_like']
                or profile['distinct_count'] <= max(50, len(dataframe))
            ]
            column_profiles_by_sheet[sheet_name] = candidate_profiles[:8]
            sheet_role_hints[sheet_name] = self._infer_sheet_role_hint(
                sheet_name,
                len(dataframe),
                candidate_profiles,
                max_row_count,
            )

        relationship_hints = []
        sheet_names = list(sheet_dataframes.keys())
        for left_index, left_sheet in enumerate(sheet_names):
            for right_sheet in sheet_names[left_index + 1:]:
                left_profiles = column_profiles_by_sheet.get(left_sheet, [])
                right_profiles = column_profiles_by_sheet.get(right_sheet, [])
                left_role_hint = sheet_role_hints.get(left_sheet, {})
                right_role_hint = sheet_role_hints.get(right_sheet, {})

                for left_profile in left_profiles:
                    for right_profile in right_profiles:
                        overlap_values = sorted(
                            left_profile['normalized_value_set'] & right_profile['normalized_value_set']
                        )
                        overlap_count = len(overlap_values)
                        token_overlap_count = len(
                            set(left_profile['tokens']) & set(right_profile['tokens'])
                        )
                        exact_column_name_match = (
                            left_profile['normalized_column_name']
                            and left_profile['normalized_column_name'] == right_profile['normalized_column_name']
                        )

                        if overlap_count == 0:
                            continue
                        if overlap_count < 2 and not exact_column_name_match and token_overlap_count == 0:
                            continue

                        left_distinct = max(1, left_profile['sample_distinct_count'])
                        right_distinct = max(1, right_profile['sample_distinct_count'])
                        overlap_ratio_vs_smaller = round(overlap_count / min(left_distinct, right_distinct), 3)

                        if left_role_hint.get('role') == 'dimension' and right_role_hint.get('role') == 'fact':
                            reference_sheet = left_sheet
                            reference_profile = left_profile
                            reference_role = left_role_hint.get('role')
                            fact_sheet = right_sheet
                            fact_profile = right_profile
                            fact_role = right_role_hint.get('role')
                        elif right_role_hint.get('role') == 'dimension' and left_role_hint.get('role') == 'fact':
                            reference_sheet = right_sheet
                            reference_profile = right_profile
                            reference_role = right_role_hint.get('role')
                            fact_sheet = left_sheet
                            fact_profile = left_profile
                            fact_role = left_role_hint.get('role')
                        elif len(sheet_dataframes[left_sheet]) <= len(sheet_dataframes[right_sheet]):
                            reference_sheet = left_sheet
                            reference_profile = left_profile
                            reference_role = left_role_hint.get('role')
                            fact_sheet = right_sheet
                            fact_profile = right_profile
                            fact_role = right_role_hint.get('role')
                        else:
                            reference_sheet = right_sheet
                            reference_profile = right_profile
                            reference_role = right_role_hint.get('role')
                            fact_sheet = left_sheet
                            fact_profile = left_profile
                            fact_role = left_role_hint.get('role')

                        relationship_hints.append({
                            'reference_sheet': reference_sheet,
                            'reference_column': reference_profile['column_name'],
                            'reference_role': reference_role,
                            'fact_sheet': fact_sheet,
                            'fact_column': fact_profile['column_name'],
                            'fact_role': fact_role,
                            'normalized_overlap_count': overlap_count,
                            'reference_distinct_count': reference_profile['sample_distinct_count'],
                            'fact_distinct_count': fact_profile['sample_distinct_count'],
                            'overlap_ratio_vs_smaller_set': overlap_ratio_vs_smaller,
                            'exact_column_name_match': bool(exact_column_name_match),
                            'shared_name_token_count': token_overlap_count,
                            'sample_overlap_values': overlap_values[:self.RELATIONSHIP_SHARED_VALUE_LIMIT],
                        })

        relationship_hints.sort(
            key=lambda item: (
                -item['normalized_overlap_count'],
                -item['overlap_ratio_vs_smaller_set'],
                -int(item['exact_column_name_match']),
                -item['shared_name_token_count'],
                item['reference_sheet'].casefold(),
                item['fact_sheet'].casefold(),
            )
        )

        return {
            'sheet_role_hints': sheet_role_hints,
            'relationship_hints': relationship_hints[:self.RELATIONSHIP_HINT_LIMIT],
        }

    def _build_sheet_schema_summary(self, df: pandas.DataFrame, sheet_name: Optional[str], preview_rows: int = 3) -> dict:
        """Build a compact schema summary for a single table or worksheet."""
        df = self._normalize_dataframe_columns(df)
        df_numeric = self._try_numeric_conversion(df.copy())
        return {
            'selected_sheet': sheet_name,
            'row_count': len(df),
            'column_count': len(df.columns),
            'columns': list(df.columns),
            'dtypes': {col: str(dtype) for col, dtype in df_numeric.dtypes.items()},
            'preview': df.head(preview_rows).to_dict(orient='records'),
            'null_counts': df.isnull().sum().to_dict(),
        }

    def _build_workbook_schema_summary(self, container_name: str, blob_name: str, filename: str, preview_rows: int = 3) -> dict:
        """Build a workbook-aware schema summary for prompt preload and file description."""
        workbook_metadata = self._get_workbook_metadata(container_name, blob_name)
        if not workbook_metadata.get('is_workbook'):
            df = self._read_tabular_blob_to_dataframe(container_name, blob_name)
            summary = self._build_sheet_schema_summary(df, None, preview_rows=preview_rows)
            summary.update({
                'filename': filename,
                'is_workbook': False,
                'sheet_names': [],
                'sheet_count': 0,
            })
            return summary

        per_sheet_schemas = {}
        sheet_dataframes = {}
        for workbook_sheet_name in workbook_metadata.get('sheet_names', []):
            df = self._read_tabular_blob_to_dataframe(
                container_name,
                blob_name,
                sheet_name=workbook_sheet_name,
            )
            sheet_dataframes[workbook_sheet_name] = df.copy()
            per_sheet_schemas[workbook_sheet_name] = self._build_sheet_schema_summary(
                df,
                workbook_sheet_name,
                preview_rows=preview_rows,
            )

        relationship_metadata = self._build_workbook_relationship_metadata(sheet_dataframes)

        return {
            'filename': filename,
            'is_workbook': True,
            'sheet_names': workbook_metadata.get('sheet_names', []),
            'sheet_count': workbook_metadata.get('sheet_count', 0),
            'selected_sheet': None,
            'per_sheet_schemas': per_sheet_schemas,
            'sheet_role_hints': relationship_metadata.get('sheet_role_hints', {}),
            'relationship_hints': relationship_metadata.get('relationship_hints', []),
        }

    def _find_candidate_sheets_for_columns(
        self,
        container_name: str,
        blob_name: str,
        column_names: List[str],
        exclude_sheet: Optional[str] = None,
    ) -> List[str]:
        """Return workbook sheets that contain one or more requested columns, ordered by best match."""
        workbook_metadata = self._get_workbook_metadata(container_name, blob_name)
        if not workbook_metadata.get('is_workbook'):
            return []

        normalized_targets = []
        seen_targets = set()
        for column_name in column_names or []:
            normalized_column_name = str(column_name or '').strip().lower()
            if not normalized_column_name or normalized_column_name in seen_targets:
                continue
            seen_targets.add(normalized_column_name)
            normalized_targets.append(normalized_column_name)

        if not normalized_targets:
            return []

        normalized_exclude_sheet = str(exclude_sheet or '').strip().lower()
        ranked_candidates = []
        for sheet_name in workbook_metadata.get('sheet_names', []):
            if normalized_exclude_sheet and sheet_name.lower() == normalized_exclude_sheet:
                continue

            dataframe = self._read_tabular_blob_to_dataframe(
                container_name,
                blob_name,
                sheet_name=sheet_name,
            )
            normalized_columns = {str(column).strip().lower() for column in dataframe.columns}
            matched_columns = [
                target_column for target_column in normalized_targets
                if target_column in normalized_columns
            ]
            if not matched_columns:
                continue

            ranked_candidates.append((len(matched_columns), sheet_name))

        ranked_candidates.sort(key=lambda item: (-item[0], item[1].lower()))
        return [sheet_name for _, sheet_name in ranked_candidates]

    def _build_missing_column_error_payload(
        self,
        container_name: str,
        blob_name: str,
        filename: str,
        workbook_metadata: dict,
        selected_sheet: Optional[str],
        missing_column: str,
        related_columns: Optional[List[str]] = None,
        available_columns: Optional[List[str]] = None,
    ) -> dict:
        """Build a workbook-aware missing-column payload that points retries at better candidate sheets."""
        available_columns = available_columns or []
        payload = {
            'error': f"Column '{missing_column}' not found. Available: {available_columns}",
            'filename': filename,
            'missing_column': missing_column,
            'selected_sheet': selected_sheet if workbook_metadata.get('is_workbook') else None,
        }

        if workbook_metadata.get('is_workbook') and workbook_metadata.get('sheet_count', 0) > 1:
            candidate_sheets = self._find_candidate_sheets_for_columns(
                container_name,
                blob_name,
                [missing_column] + list(related_columns or []),
                exclude_sheet=selected_sheet,
            )
            if candidate_sheets:
                payload['candidate_sheets'] = candidate_sheets
                payload['error'] = (
                    f"Column '{missing_column}' not found on sheet '{selected_sheet}'. "
                    f"Available: {available_columns}. Candidate sheets: {candidate_sheets}"
                )

        return payload

    def _read_tabular_blob_to_dataframe(
        self,
        container_name: str,
        blob_name: str,
        sheet_name: Optional[str] = None,
        sheet_index: Optional[str] = None,
        require_explicit_sheet: bool = False,
    ) -> pandas.DataFrame:
        """Download a blob and read it into a pandas DataFrame. Uses per-instance cache."""
        resolved_sheet_name, workbook_metadata = self._resolve_sheet_selection(
            container_name,
            blob_name,
            sheet_name=sheet_name,
            sheet_index=sheet_index,
            require_explicit_sheet=require_explicit_sheet,
        )
        sheet_cache_key = resolved_sheet_name or '__default__'
        cache_key = (container_name, blob_name, sheet_cache_key)
        if cache_key in self._df_cache:
            log_event(
                f"[TabularProcessingPlugin] Cache hit for {blob_name}"
                + (f" [{resolved_sheet_name}]" if resolved_sheet_name else ''),
                level=logging.DEBUG,
            )
            return self._df_cache[cache_key].copy()

        data = self._download_tabular_blob_bytes(container_name, blob_name)

        name_lower = blob_name.lower()
        if name_lower.endswith('.csv'):
            df = pandas.read_csv(io.BytesIO(data), keep_default_na=False, dtype=str)
        elif name_lower.endswith('.xlsx') or name_lower.endswith('.xlsm'):
            df = pandas.read_excel(
                io.BytesIO(data),
                engine='openpyxl',
                keep_default_na=False,
                dtype=str,
                sheet_name=resolved_sheet_name,
            )
        elif name_lower.endswith('.xls'):
            df = pandas.read_excel(
                io.BytesIO(data),
                engine='xlrd',
                keep_default_na=False,
                dtype=str,
                sheet_name=resolved_sheet_name,
            )
        else:
            raise ValueError(f"Unsupported tabular file type: {blob_name}")

        df = self._normalize_dataframe_columns(df)
        self._df_cache[cache_key] = df
        log_event(
            f"[TabularProcessingPlugin] Cached DataFrame for {blob_name}"
            + (f" [{resolved_sheet_name}]" if resolved_sheet_name else '')
            + f" ({len(df)} rows)",
            level=logging.DEBUG,
        )
        return df.copy()

    def _try_numeric_conversion(self, df: pandas.DataFrame) -> pandas.DataFrame:
        """Attempt to convert string columns to numeric where possible."""
        for col in df.columns:
            if pandas.api.types.is_datetime64_any_dtype(df[col]) or pandas.api.types.is_timedelta64_dtype(df[col]):
                continue
            try:
                df[col] = pandas.to_numeric(df[col])
            except (ValueError, TypeError):
                pass
        return df

    def _parse_datetime_like_series(self, series: pandas.Series) -> pandas.Series:
        """Best-effort parsing for datetime and time-like values."""
        if pandas.api.types.is_datetime64_any_dtype(series):
            return pandas.to_datetime(series, errors='coerce')

        cleaned_series = series.astype(str).str.strip()
        cleaned_series = cleaned_series.replace({
            '': None,
            'nan': None,
            'NaN': None,
            'nat': None,
            'NaT': None,
            'none': None,
            'None': None,
        })

        parsed = pandas.Series(pandas.NaT, index=series.index, dtype='datetime64[ns]')

        common_formats = [
            '%m/%d/%Y %I:%M:%S %p',
            '%m/%d/%Y %I:%M %p',
            '%m/%d/%Y %H:%M:%S',
            '%m/%d/%Y %H:%M',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.%f',
            '%Y-%m-%d',
            '%m/%d/%Y',
        ]

        for datetime_format in common_formats:
            remaining_mask = parsed.isna() & cleaned_series.notna()
            if not remaining_mask.any():
                break

            parsed.loc[remaining_mask] = pandas.to_datetime(
                cleaned_series[remaining_mask],
                format=datetime_format,
                errors='coerce'
            )

        remaining_mask = parsed.isna() & cleaned_series.notna()
        if remaining_mask.any():
            digits = cleaned_series[remaining_mask].str.replace(r'[^0-9]', '', regex=True)

            hhmm_mask = digits.str.match(r'^\d{3,4}$', na=False)
            if hhmm_mask.any():
                hhmm_values = digits[hhmm_mask].str.zfill(4)
                parsed.loc[hhmm_values.index] = pandas.to_datetime(
                    hhmm_values,
                    format='%H%M',
                    errors='coerce'
                )

            remaining_mask = parsed.isna() & cleaned_series.notna()
            if remaining_mask.any():
                digits = cleaned_series[remaining_mask].str.replace(r'[^0-9]', '', regex=True)
                hhmmss_mask = digits.str.match(r'^\d{5,6}$', na=False)
                if hhmmss_mask.any():
                    hhmmss_values = digits[hhmmss_mask].str.zfill(6)
                    parsed.loc[hhmmss_values.index] = pandas.to_datetime(
                        hhmmss_values,
                        format='%H%M%S',
                        errors='coerce'
                    )

            remaining_mask = parsed.isna() & cleaned_series.notna()
            if remaining_mask.any():
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    parsed.loc[remaining_mask] = pandas.to_datetime(
                        cleaned_series[remaining_mask],
                        errors='coerce'
                    )

        return parsed

    def _normalize_datetime_component(self, component: str) -> str:
        """Normalize datetime component aliases to a canonical value."""
        normalized = (component or '').strip().lower()
        aliases = {
            'years': 'year',
            'months': 'month',
            'monthname': 'month_name',
            'month_name': 'month_name',
            'days': 'day',
            'dayofmonth': 'day',
            'dates': 'date',
            'hours': 'hour',
            'hour_of_day': 'hour',
            'timeofday': 'hour',
            'time_of_day': 'hour',
            'minutes': 'minute',
            'dayofweek': 'day_name',
            'day_of_week': 'day_name',
            'weekday': 'day_name',
            'weekday_name': 'day_name',
            'day_name': 'day_name',
            'weekdaynumber': 'weekday_number',
            'weekday_number': 'weekday_number',
            'quarters': 'quarter',
        }
        return aliases.get(normalized, normalized)

    def _extract_datetime_component(self, parsed_series: pandas.Series, component: str) -> pandas.Series:
        """Extract a supported datetime component from a parsed datetime series."""
        normalized = self._normalize_datetime_component(component)

        if normalized == 'year':
            return parsed_series.dt.year
        if normalized == 'month':
            return parsed_series.dt.month
        if normalized == 'month_name':
            month_names = parsed_series.dt.month_name()
            ordered_months = pandas.Categorical(
                month_names,
                categories=self.MONTH_NAME_ORDER,
                ordered=True
            )
            return pandas.Series(ordered_months, index=parsed_series.index)
        if normalized == 'day':
            return parsed_series.dt.day
        if normalized == 'date':
            return parsed_series.dt.strftime('%Y-%m-%d')
        if normalized == 'hour':
            return parsed_series.dt.hour
        if normalized == 'minute':
            return parsed_series.dt.minute
        if normalized == 'day_name':
            day_names = parsed_series.dt.day_name()
            ordered_days = pandas.Categorical(
                day_names,
                categories=self.DAY_NAME_ORDER,
                ordered=True
            )
            return pandas.Series(ordered_days, index=parsed_series.index)
        if normalized == 'weekday_number':
            return parsed_series.dt.dayofweek
        if normalized == 'quarter':
            return parsed_series.dt.quarter
        if normalized == 'week':
            return parsed_series.dt.isocalendar().week.astype(int)

        raise ValueError(
            f"Unsupported datetime component '{component}'. "
            "Use year, month, month_name, day, date, hour, minute, day_name, weekday_number, quarter, or week."
        )

    def _parse_boolean_argument(self, value, default=True) -> bool:
        """Parse common string boolean values for plugin inputs."""
        if isinstance(value, bool):
            return value
        if value is None:
            return default

        normalized = str(value).strip().lower()
        if normalized in {'true', '1', 'yes', 'y', 'on'}:
            return True
        if normalized in {'false', '0', 'no', 'n', 'off'}:
            return False
        return default

    def _ordered_grouped_results(self, grouped: pandas.Series, component: str) -> pandas.Series:
        """Return grouped results in a natural chronological order where possible."""
        normalized = self._normalize_datetime_component(component)
        if normalized == 'day_name':
            return grouped.reindex([day for day in self.DAY_NAME_ORDER if day in grouped.index])
        if normalized == 'month_name':
            return grouped.reindex([month for month in self.MONTH_NAME_ORDER if month in grouped.index])
        return grouped.sort_index()

    def _series_to_json_dict(self, series: pandas.Series) -> dict:
        """Convert a pandas Series into a JSON-safe dictionary."""
        safe_dict = {}
        for index, value in series.items():
            safe_dict[str(index)] = value.item() if hasattr(value, 'item') else value
        return safe_dict

    def _scalar_to_json_value(self, value):
        """Convert a scalar value to a JSON-safe representation."""
        if pandas.isna(value):
            return None
        return value.item() if hasattr(value, 'item') else value

    def _build_grouped_summary(self, grouped: pandas.Series) -> dict:
        """Build generic summary fields for grouped metric outputs."""
        if grouped.empty:
            return {}

        descending_values = grouped.sort_values(ascending=False)
        ascending_values = grouped.sort_values(ascending=True)
        summary = {
            'highest_group': str(descending_values.index[0]),
            'highest_value': self._scalar_to_json_value(descending_values.iloc[0]),
            'lowest_group': str(ascending_values.index[0]),
            'lowest_value': self._scalar_to_json_value(ascending_values.iloc[0]),
            'average_group_value': self._scalar_to_json_value(grouped.mean()),
            'median_group_value': self._scalar_to_json_value(grouped.median()),
        }

        if len(descending_values) > 1:
            summary['second_highest_group'] = str(descending_values.index[1])
            summary['second_highest_value'] = self._scalar_to_json_value(descending_values.iloc[1])

        return summary

    def _resolve_blob_location(self, user_id: str, conversation_id: str, filename: str, source: str,
                               group_id: str = None, public_workspace_id: str = None) -> tuple:
        """Resolve container name and blob path from source type."""
        source = source.lower().strip()
        if source == 'chat':
            container = storage_account_personal_chat_container_name
            blob_path = f"{user_id}/{conversation_id}/{filename}"
        elif source == 'workspace':
            container = storage_account_user_documents_container_name
            blob_path = f"{user_id}/{filename}"
        elif source == 'group':
            if not group_id:
                raise ValueError("group_id is required for source='group'")
            container = storage_account_group_documents_container_name
            blob_path = f"{group_id}/{filename}"
        elif source == 'public':
            if not public_workspace_id:
                raise ValueError("public_workspace_id is required for source='public'")
            container = storage_account_public_documents_container_name
            blob_path = f"{public_workspace_id}/{filename}"
        else:
            raise ValueError(f"Unknown source '{source}'. Use 'workspace', 'chat', 'group', or 'public'.")
        return container, blob_path

    def _resolve_blob_location_with_fallback(self, user_id: str, conversation_id: str, filename: str, source: str,
                                              group_id: str = None, public_workspace_id: str = None) -> tuple:
        """Try primary source first, then fall back to other containers if blob not found."""
        source = source.lower().strip()
        override = self._get_resolved_blob_location_override(source, filename)
        if override:
            return override

        attempts = []

        # Primary attempt based on specified source
        try:
            primary = self._resolve_blob_location(user_id, conversation_id, filename, source, group_id, public_workspace_id)
            attempts.append(primary)
        except ValueError:
            pass

        # Fallback attempts in priority order (skip the primary source)
        if source != 'workspace':
            attempts.append((storage_account_user_documents_container_name, f"{user_id}/{filename}"))
        if source != 'group' and group_id:
            attempts.append((storage_account_group_documents_container_name, f"{group_id}/{filename}"))
        if source != 'public' and public_workspace_id:
            attempts.append((storage_account_public_documents_container_name, f"{public_workspace_id}/{filename}"))
        if source != 'chat':
            attempts.append((storage_account_personal_chat_container_name, f"{user_id}/{conversation_id}/{filename}"))

        client = self._get_blob_service_client()
        for container, blob_path in attempts:
            try:
                blob_client = client.get_blob_client(container=container, blob=blob_path)
                if blob_client.exists():
                    log_event(f"[TabularProcessingPlugin] Found blob at {container}/{blob_path}", level=logging.DEBUG)
                    return container, blob_path
            except Exception:
                continue

        # If nothing found, return primary for the original error message
        if attempts:
            return attempts[0]
        raise ValueError(f"Could not resolve blob location for {filename}")

    @kernel_function(
        description=(
            "List all tabular data files available for a user. Checks workspace documents "
            "(user-documents container), chat-uploaded documents (personal-chat container), "
            "and optionally group or public workspace documents. "
            "Returns a JSON list of available files with their source."
        ),
        name="list_tabular_files"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    async def list_tabular_files(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON list of available tabular files"]:
        """List all tabular files available for the user across all accessible containers."""
        def _sync_work():
            results = []
            try:
                workspace_prefix = f"{user_id}/"
                workspace_blobs = self._list_tabular_blobs(
                    storage_account_user_documents_container_name, workspace_prefix
                )
                for blob in workspace_blobs:
                    filename = blob.split('/')[-1]
                    workbook_metadata = self._get_workbook_metadata(
                        storage_account_user_documents_container_name,
                        blob,
                    )
                    results.append({
                        "filename": filename,
                        "blob_path": blob,
                        "source": "workspace",
                        "container": storage_account_user_documents_container_name,
                        "sheet_names": workbook_metadata.get('sheet_names', []),
                        "sheet_count": workbook_metadata.get('sheet_count', 0),
                    })
            except Exception as e:
                log_event(f"[TabularProcessingPlugin] Error listing workspace blobs: {e}", level=logging.WARNING)

            try:
                chat_prefix = f"{user_id}/{conversation_id}/"
                chat_blobs = self._list_tabular_blobs(
                    storage_account_personal_chat_container_name, chat_prefix
                )
                for blob in chat_blobs:
                    filename = blob.split('/')[-1]
                    workbook_metadata = self._get_workbook_metadata(
                        storage_account_personal_chat_container_name,
                        blob,
                    )
                    results.append({
                        "filename": filename,
                        "blob_path": blob,
                        "source": "chat",
                        "container": storage_account_personal_chat_container_name,
                        "sheet_names": workbook_metadata.get('sheet_names', []),
                        "sheet_count": workbook_metadata.get('sheet_count', 0),
                    })
            except Exception as e:
                log_event(f"[TabularProcessingPlugin] Error listing chat blobs: {e}", level=logging.WARNING)

            if group_id:
                try:
                    group_prefix = f"{group_id}/"
                    group_blobs = self._list_tabular_blobs(
                        storage_account_group_documents_container_name, group_prefix
                    )
                    for blob in group_blobs:
                        filename = blob.split('/')[-1]
                        workbook_metadata = self._get_workbook_metadata(
                            storage_account_group_documents_container_name,
                            blob,
                        )
                        results.append({
                            "filename": filename,
                            "blob_path": blob,
                            "source": "group",
                            "container": storage_account_group_documents_container_name,
                            "sheet_names": workbook_metadata.get('sheet_names', []),
                            "sheet_count": workbook_metadata.get('sheet_count', 0),
                        })
                except Exception as e:
                    log_event(f"[TabularProcessingPlugin] Error listing group blobs: {e}", level=logging.WARNING)

            if public_workspace_id:
                try:
                    public_prefix = f"{public_workspace_id}/"
                    public_blobs = self._list_tabular_blobs(
                        storage_account_public_documents_container_name, public_prefix
                    )
                    for blob in public_blobs:
                        filename = blob.split('/')[-1]
                        workbook_metadata = self._get_workbook_metadata(
                            storage_account_public_documents_container_name,
                            blob,
                        )
                        results.append({
                            "filename": filename,
                            "blob_path": blob,
                            "source": "public",
                            "container": storage_account_public_documents_container_name,
                            "sheet_names": workbook_metadata.get('sheet_names', []),
                            "sheet_count": workbook_metadata.get('sheet_count', 0),
                        })
                except Exception as e:
                    log_event(f"[TabularProcessingPlugin] Error listing public blobs: {e}", level=logging.WARNING)

            return json.dumps(results, indent=2)
        return await asyncio.to_thread(_sync_work)

    @kernel_function(
        description=(
            "Get a summary of a tabular file including column names, row count, data types, "
            "and a preview of the first few rows."
        ),
        name="describe_tabular_file"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    async def describe_tabular_file(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        sheet_name: Annotated[Optional[str], "Optional worksheet name for Excel files. When omitted on multi-sheet workbooks, the response returns workbook-level sheet schemas."] = None,
        sheet_index: Annotated[Optional[str], "Optional zero-based worksheet index for Excel files. Ignored when sheet_name is provided."] = None,
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON summary of the tabular file"]:
        """Get schema and preview of a tabular file."""
        def _sync_work():
            try:
                container, blob_path = self._resolve_blob_location_with_fallback(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )
                workbook_metadata = self._get_workbook_metadata(container, blob_path)

                if workbook_metadata.get('is_workbook') and workbook_metadata.get('sheet_count', 0) > 1 and not (sheet_name or sheet_index):
                    summary = self._build_workbook_schema_summary(
                        container,
                        blob_path,
                        filename,
                        preview_rows=3,
                    )
                else:
                    selected_sheet, workbook_metadata = self._resolve_sheet_selection(
                        container,
                        blob_path,
                        sheet_name=sheet_name,
                        sheet_index=sheet_index,
                        require_explicit_sheet=False,
                    )
                    df = self._read_tabular_blob_to_dataframe(
                        container,
                        blob_path,
                        sheet_name=selected_sheet,
                        require_explicit_sheet=False,
                    )
                    summary = self._build_sheet_schema_summary(df, selected_sheet, preview_rows=5)
                    summary.update({
                        "filename": filename,
                        "is_workbook": workbook_metadata.get('is_workbook', False),
                        "sheet_names": workbook_metadata.get('sheet_names', []),
                        "sheet_count": workbook_metadata.get('sheet_count', 0),
                    })

                return json.dumps(summary, indent=2, default=str)
            except Exception as e:
                log_event(f"[TabularProcessingPlugin] Error describing file: {e}", level=logging.WARNING)
                return json.dumps({"error": str(e)})
        return await asyncio.to_thread(_sync_work)

    @kernel_function(
        description=(
            "Look up one or more rows by label/category in a tabular file and return the value from a target column. "
            "Best for questions like 'What was Total Assets in Nov-25?' or 'What was Net Worth in Dec-25?'."
        ),
        name="lookup_value"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    async def lookup_value(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        lookup_column: Annotated[str, "The label/category column to search, such as Accounts or Category"],
        lookup_value: Annotated[str, "The row label/category value to search for, such as Total Assets"],
        target_column: Annotated[str, "The target column containing the desired value, such as Nov-25"],
        match_operator: Annotated[str, "Match operator: equals, contains, startswith, endswith"] = "equals",
        normalize_match: Annotated[str, "Whether to normalize string/entity matching for text comparisons (true/false)"] = "false",
        sheet_name: Annotated[Optional[str], "Optional worksheet name for Excel files. Required for analytical calls on multi-sheet workbooks unless sheet_index is provided."] = None,
        sheet_index: Annotated[Optional[str], "Optional zero-based worksheet index for Excel files. Ignored when sheet_name is provided."] = None,
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        max_rows: Annotated[str, "Maximum matching rows to return"] = "25",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON result containing matching rows and target-column values"]:
        """Look up values from a target column for matching rows."""
        def _sync_work():
            try:
                normalize_match_flag = self._parse_boolean_argument(normalize_match, default=False)
                container, blob_path = self._resolve_blob_location_with_fallback(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )
                # When no explicit sheet_name is given, try cross-sheet search first
                normalized_sheet = (sheet_name or '').strip()
                normalized_sheet_idx = None if sheet_index is None else str(sheet_index).strip()
                if not normalized_sheet and normalized_sheet_idx in (None, ''):
                    cross_sheet_result = self._lookup_value_across_sheets(
                        container, blob_path, filename,
                        lookup_column, lookup_value, target_column,
                        match_operator=match_operator,
                        normalize_match=normalize_match_flag,
                        max_rows=int(max_rows),
                    )
                    if cross_sheet_result is not None:
                        return cross_sheet_result
                selected_sheet, workbook_metadata = self._resolve_sheet_selection(
                    container,
                    blob_path,
                    sheet_name=sheet_name,
                    sheet_index=sheet_index,
                    require_explicit_sheet=True,
                )
                df = self._read_tabular_blob_to_dataframe(
                    container,
                    blob_path,
                    sheet_name=selected_sheet,
                    require_explicit_sheet=True,
                )
                df = self._try_numeric_conversion(df)

                if lookup_column not in df.columns:
                    return json.dumps(
                        self._build_missing_column_error_payload(
                            container,
                            blob_path,
                            filename,
                            workbook_metadata,
                            selected_sheet,
                            lookup_column,
                            related_columns=[target_column],
                            available_columns=list(df.columns),
                        )
                    )
                if target_column not in df.columns:
                    return json.dumps(
                        self._build_missing_column_error_payload(
                            container,
                            blob_path,
                            filename,
                            workbook_metadata,
                            selected_sheet,
                            target_column,
                            related_columns=[lookup_column],
                            available_columns=list(df.columns),
                        )
                    )

                operator = (match_operator or 'equals').strip().lower()
                normalized_lookup_value = str(lookup_value)

                try:
                    mask = self._build_series_match_mask(
                        df[lookup_column],
                        operator,
                        normalized_lookup_value,
                        normalize_match=normalize_match_flag,
                    )
                except ValueError:
                    return json.dumps({"error": f"Unsupported match_operator: {match_operator}"})

                limit = int(max_rows)
                matches = df[mask].head(limit)
                response = {
                    "filename": filename,
                    "selected_sheet": selected_sheet if workbook_metadata.get('is_workbook') else None,
                    "lookup_column": lookup_column,
                    "lookup_value": lookup_value,
                    "target_column": target_column,
                    "match_operator": operator,
                    "normalize_match": normalize_match_flag,
                    "total_matches": int(mask.sum()),
                    "returned_rows": len(matches),
                    "data": matches.to_dict(orient='records'),
                }

                if len(matches) == 1:
                    response["value"] = matches.iloc[0][target_column]

                return json.dumps(response, indent=2, default=str)
            except Exception as e:
                log_event(f"[TabularProcessingPlugin] Error looking up value: {e}", level=logging.WARNING)
                return json.dumps({"error": str(e)})
        return await asyncio.to_thread(_sync_work)

    @kernel_function(
        description=(
            "Return deterministic distinct values for a column, with optional query_expression, up to two column filters, and optional embedded URL or regex extraction from composite text cells. "
            "Use this to build a canonical cohort from a worksheet before counting or joining related rows. Narrow the original text column first when category membership depends on surrounding cell context."
        ),
        name="get_distinct_values"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    async def get_distinct_values(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        column: Annotated[str, "The column from which to return distinct values"],
        query_expression: Annotated[Optional[str], "Optional pandas DataFrame.query() expression to apply before collecting distinct values"] = None,
        filter_column: Annotated[Optional[str], "Optional column to filter on before collecting distinct values"] = None,
        filter_operator: Annotated[str, "Optional filter operator when filter_column is provided"] = "equals",
        filter_value: Annotated[Optional[str], "Optional filter value when filter_column is provided"] = None,
        additional_filter_column: Annotated[Optional[str], "Optional second column to filter on before collecting distinct values"] = None,
        additional_filter_operator: Annotated[str, "Optional filter operator when additional_filter_column is provided"] = "equals",
        additional_filter_value: Annotated[Optional[str], "Optional filter value when additional_filter_column is provided"] = None,
        extract_mode: Annotated[Optional[str], "Optional embedded extraction mode: 'url' or 'regex'"] = None,
        extract_pattern: Annotated[Optional[str], "Optional regex pattern when extract_mode is 'regex'"] = None,
        url_path_segments: Annotated[Optional[str], "Optional number of URL path segments to keep when extract_mode is 'url'"] = None,
        normalize_match: Annotated[str, "Whether to normalize string/entity matching and deduplication (true/false)"] = "true",
        sheet_name: Annotated[Optional[str], "Optional worksheet name for Excel files. When omitted, the plugin may perform a cross-sheet distinct-value search."] = None,
        sheet_index: Annotated[Optional[str], "Optional zero-based worksheet index for Excel files. Ignored when sheet_name is provided."] = None,
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        max_values: Annotated[str, "Maximum distinct values to return"] = "100",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON result containing deterministic distinct values and counts"]:
        """Return deterministic distinct values from a worksheet or across worksheets."""
        def _sync_work():
            try:
                normalize_match_flag = self._parse_boolean_argument(normalize_match, default=True)
                normalized_extract_mode, normalized_extract_pattern, parsed_url_path_segments = self._normalize_distinct_extraction_arguments(
                    extract_mode=extract_mode,
                    extract_pattern=extract_pattern,
                    url_path_segments=url_path_segments,
                )
                container, blob_path = self._resolve_blob_location_with_fallback(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )

                normalized_sheet = (sheet_name or '').strip()
                normalized_sheet_idx = None if sheet_index is None else str(sheet_index).strip()
                if not normalized_sheet and normalized_sheet_idx in (None, ''):
                    cross_sheet_result = self._get_distinct_values_across_sheets(
                        container,
                        blob_path,
                        filename,
                        column,
                        query_expression=query_expression,
                        filter_column=filter_column,
                        filter_operator=filter_operator,
                        filter_value=filter_value,
                        additional_filter_column=additional_filter_column,
                        additional_filter_operator=additional_filter_operator,
                        additional_filter_value=additional_filter_value,
                        extract_mode=normalized_extract_mode,
                        extract_pattern=normalized_extract_pattern,
                        url_path_segments=parsed_url_path_segments,
                        normalize_match=normalize_match_flag,
                        max_values=int(max_values),
                    )
                    if cross_sheet_result is not None:
                        return cross_sheet_result

                selected_sheet, workbook_metadata = self._resolve_sheet_selection(
                    container,
                    blob_path,
                    sheet_name=sheet_name,
                    sheet_index=sheet_index,
                    require_explicit_sheet=True,
                )
                df = self._read_tabular_blob_to_dataframe(
                    container,
                    blob_path,
                    sheet_name=selected_sheet,
                    require_explicit_sheet=True,
                )

                if column not in df.columns:
                    return json.dumps(
                        self._build_missing_column_error_payload(
                            container,
                            blob_path,
                            filename,
                            workbook_metadata,
                            selected_sheet,
                            column,
                            related_columns=[
                                candidate_column for candidate_column in (filter_column, additional_filter_column)
                                if candidate_column
                            ] or None,
                            available_columns=list(df.columns),
                        )
                    )

                try:
                    filtered_df, applied_filters = self._apply_optional_dataframe_filters(
                        df,
                        query_expression=query_expression,
                        filter_column=filter_column,
                        filter_operator=filter_operator,
                        filter_value=filter_value,
                        additional_filter_column=additional_filter_column,
                        additional_filter_operator=additional_filter_operator,
                        additional_filter_value=additional_filter_value,
                        normalize_match=normalize_match_flag,
                    )
                except KeyError as missing_column_error:
                    missing_column = str(missing_column_error).strip("'")
                    return json.dumps(
                        self._build_missing_column_error_payload(
                            container,
                            blob_path,
                            filename,
                            workbook_metadata,
                            selected_sheet,
                            missing_column,
                            related_columns=[
                                candidate_column for candidate_column in (column, filter_column, additional_filter_column)
                                if candidate_column
                            ],
                            available_columns=list(df.columns),
                        )
                    )
                except Exception as query_error:
                    return json.dumps({
                        'error': f"Query/filter error: {query_error}",
                        'filename': filename,
                        'selected_sheet': selected_sheet if workbook_metadata.get('is_workbook') else None,
                    })

                distinct_display_values, matched_cell_count, extracted_match_count = self._collect_distinct_display_values(
                    filtered_df[column],
                    normalize_match=normalize_match_flag,
                    extract_mode=normalized_extract_mode,
                    extract_pattern=normalized_extract_pattern,
                    url_path_segments=parsed_url_path_segments,
                )

                ordered_values = sorted(distinct_display_values.values(), key=lambda item: item.casefold())
                limit = int(max_values)
                response_payload = {
                    'filename': filename,
                    'selected_sheet': selected_sheet if workbook_metadata.get('is_workbook') else None,
                    'column': column,
                    'filter_applied': applied_filters,
                    'normalize_match': normalize_match_flag,
                    'distinct_count': len(ordered_values),
                    'returned_values': min(len(ordered_values), limit),
                    'values': ordered_values[:limit],
                    'values_limited': len(ordered_values) > limit,
                }
                if normalized_extract_mode:
                    response_payload.update({
                        'extract_mode': normalized_extract_mode,
                        'extract_pattern': normalized_extract_pattern if normalized_extract_mode == 'regex' else None,
                        'url_path_segments': parsed_url_path_segments if normalized_extract_mode == 'url' else None,
                        'matched_cell_count': matched_cell_count,
                        'extracted_match_count': extracted_match_count,
                    })
                return json.dumps(response_payload, indent=2, default=str)
            except Exception as e:
                log_event(f"[TabularProcessingPlugin] Error getting distinct values: {e}", level=logging.WARNING)
                return json.dumps({"error": str(e)})

        return await asyncio.to_thread(_sync_work)

    @kernel_function(
        description=(
            "Return a deterministic row count after applying an optional query_expression and up to two filter conditions. "
            "Use this instead of estimating counts from partial returned rows when the user asks how many or what percentage."
        ),
        name="count_rows"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    async def count_rows(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        query_expression: Annotated[Optional[str], "Optional pandas DataFrame.query() expression to apply before counting rows"] = None,
        filter_column: Annotated[Optional[str], "Optional column to filter on before counting rows"] = None,
        filter_operator: Annotated[str, "Optional filter operator when filter_column is provided"] = "equals",
        filter_value: Annotated[Optional[str], "Optional filter value when filter_column is provided"] = None,
        additional_filter_column: Annotated[Optional[str], "Optional second column to filter on before counting rows"] = None,
        additional_filter_operator: Annotated[str, "Optional filter operator when additional_filter_column is provided"] = "equals",
        additional_filter_value: Annotated[Optional[str], "Optional filter value when additional_filter_column is provided"] = None,
        normalize_match: Annotated[str, "Whether to normalize string/entity matching for text comparisons (true/false)"] = "false",
        sheet_name: Annotated[Optional[str], "Optional worksheet name for Excel files. When omitted, the plugin may perform a cross-sheet row count."] = None,
        sheet_index: Annotated[Optional[str], "Optional zero-based worksheet index for Excel files. Ignored when sheet_name is provided."] = None,
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON result containing a deterministic row count"]:
        """Count rows deterministically after optional filters or queries."""
        def _sync_work():
            try:
                normalize_match_flag = self._parse_boolean_argument(normalize_match, default=False)
                container, blob_path = self._resolve_blob_location_with_fallback(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )

                normalized_sheet = (sheet_name or '').strip()
                normalized_sheet_idx = None if sheet_index is None else str(sheet_index).strip()
                if not normalized_sheet and normalized_sheet_idx in (None, ''):
                    cross_sheet_result = self._count_rows_across_sheets(
                        container,
                        blob_path,
                        filename,
                        filter_column=filter_column,
                        filter_operator=filter_operator,
                        filter_value=filter_value,
                        additional_filter_column=additional_filter_column,
                        additional_filter_operator=additional_filter_operator,
                        additional_filter_value=additional_filter_value,
                        query_expression=query_expression,
                        normalize_match=normalize_match_flag,
                    )
                    if cross_sheet_result is not None:
                        return cross_sheet_result

                selected_sheet, workbook_metadata = self._resolve_sheet_selection(
                    container,
                    blob_path,
                    sheet_name=sheet_name,
                    sheet_index=sheet_index,
                    require_explicit_sheet=True,
                )
                df = self._read_tabular_blob_to_dataframe(
                    container,
                    blob_path,
                    sheet_name=selected_sheet,
                    require_explicit_sheet=True,
                )
                df = self._try_numeric_conversion(df)

                try:
                    filtered_df, applied_filters = self._apply_optional_dataframe_filters(
                        df,
                        query_expression=query_expression,
                        filter_column=filter_column,
                        filter_operator=filter_operator,
                        filter_value=filter_value,
                        additional_filter_column=additional_filter_column,
                        additional_filter_operator=additional_filter_operator,
                        additional_filter_value=additional_filter_value,
                        normalize_match=normalize_match_flag,
                    )
                except KeyError as missing_column_error:
                    missing_column = str(missing_column_error).strip("'")
                    return json.dumps(
                        self._build_missing_column_error_payload(
                            container,
                            blob_path,
                            filename,
                            workbook_metadata,
                            selected_sheet,
                            missing_column,
                            related_columns=[
                                candidate_column for candidate_column in (filter_column, additional_filter_column)
                                if candidate_column
                            ] or None,
                            available_columns=list(df.columns),
                        )
                    )
                except Exception as query_error:
                    return json.dumps({
                        'error': f"Query/filter error: {query_error}",
                        'filename': filename,
                        'selected_sheet': selected_sheet if workbook_metadata.get('is_workbook') else None,
                    })

                return json.dumps({
                    'filename': filename,
                    'selected_sheet': selected_sheet if workbook_metadata.get('is_workbook') else None,
                    'rows_scanned': len(df),
                    'row_count': len(filtered_df),
                    'filter_applied': applied_filters,
                    'normalize_match': normalize_match_flag,
                }, indent=2, default=str)
            except Exception as e:
                log_event(f"[TabularProcessingPlugin] Error counting rows: {e}", level=logging.WARNING)
                return json.dumps({"error": str(e)})

        return await asyncio.to_thread(_sync_work)

    @kernel_function(
        description=(
            "Execute an aggregation operation on a column of a tabular file. "
            "Supported operations: sum, mean, count, min, max, median, std, nunique, value_counts."
        ),
        name="aggregate_column"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    async def aggregate_column(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        column: Annotated[str, "The column name to aggregate"],
        operation: Annotated[str, "Aggregation: sum, mean, count, min, max, median, std, nunique, value_counts"],
        sheet_name: Annotated[Optional[str], "Optional worksheet name for Excel files. Required for analytical calls on multi-sheet workbooks unless sheet_index is provided."] = None,
        sheet_index: Annotated[Optional[str], "Optional zero-based worksheet index for Excel files. Ignored when sheet_name is provided."] = None,
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON result of the aggregation"]:
        """Execute an aggregation operation on a column."""
        def _sync_work():
            try:
                container, blob_path = self._resolve_blob_location_with_fallback(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )
                selected_sheet, workbook_metadata = self._resolve_sheet_selection(
                    container,
                    blob_path,
                    sheet_name=sheet_name,
                    sheet_index=sheet_index,
                    require_explicit_sheet=True,
                )
                df = self._read_tabular_blob_to_dataframe(
                    container,
                    blob_path,
                    sheet_name=selected_sheet,
                    require_explicit_sheet=True,
                )
                df = self._try_numeric_conversion(df)

                if column not in df.columns:
                    return json.dumps(
                        self._build_missing_column_error_payload(
                            container,
                            blob_path,
                            filename,
                            workbook_metadata,
                            selected_sheet,
                            column,
                            available_columns=list(df.columns),
                        )
                    )

                series = df[column]
                op = operation.lower().strip()

                if op == 'sum':
                    result = series.sum()
                elif op == 'mean':
                    result = series.mean()
                elif op == 'count':
                    result = series.count()
                elif op == 'min':
                    result = series.min()
                elif op == 'max':
                    result = series.max()
                elif op == 'median':
                    result = series.median()
                elif op == 'std':
                    result = series.std()
                elif op == 'nunique':
                    result = series.nunique()
                elif op == 'value_counts':
                    result = self._series_to_json_dict(series.value_counts())
                else:
                    return json.dumps({"error": f"Unsupported operation: {operation}. Use sum, mean, count, min, max, median, std, nunique, value_counts."})

                return json.dumps({
                    "filename": filename,
                    "selected_sheet": selected_sheet if workbook_metadata.get('is_workbook') else None,
                    "column": column,
                    "operation": op,
                    "result": result,
                }, indent=2, default=str)
            except Exception as e:
                log_event(f"[TabularProcessingPlugin] Error aggregating column: {e}", level=logging.WARNING)
                return json.dumps({"error": str(e)})
        return await asyncio.to_thread(_sync_work)

    @kernel_function(
        description=(
            "Filter rows in a tabular file based on conditions and return matching rows. "
            "Supports operators: ==, !=, >, <, >=, <=, contains, startswith, endswith. "
            "A second column filter can be applied for compound text or literal matching. Use this as the text-search tool when the full cell or row context matters."
        ),
        name="filter_rows"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    async def filter_rows(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        column: Annotated[str, "The column to filter on"],
        operator: Annotated[str, "Operator: ==, !=, >, <, >=, <=, contains, startswith, endswith"],
        value: Annotated[str, "The value to compare against"],
        additional_filter_column: Annotated[Optional[str], "Optional second column to filter on"] = None,
        additional_filter_operator: Annotated[str, "Optional filter operator when additional_filter_column is provided"] = "equals",
        additional_filter_value: Annotated[Optional[str], "Optional filter value when additional_filter_column is provided"] = None,
        normalize_match: Annotated[str, "Whether to normalize string/entity matching for text comparisons (true/false)"] = "false",
        sheet_name: Annotated[Optional[str], "Optional worksheet name for Excel files. Required for analytical calls on multi-sheet workbooks unless sheet_index is provided."] = None,
        sheet_index: Annotated[Optional[str], "Optional zero-based worksheet index for Excel files. Ignored when sheet_name is provided."] = None,
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        max_rows: Annotated[str, "Maximum rows to return"] = "100",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON list of matching rows"]:
        """Filter rows based on a condition."""
        def _sync_work():
            try:
                normalize_match_flag = self._parse_boolean_argument(normalize_match, default=False)
                container, blob_path = self._resolve_blob_location_with_fallback(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )
                # When no explicit sheet_name is given, try cross-sheet search first
                normalized_sheet = (sheet_name or '').strip()
                normalized_sheet_idx = None if sheet_index is None else str(sheet_index).strip()
                if not normalized_sheet and normalized_sheet_idx in (None, ''):
                    cross_sheet_result = self._filter_rows_across_sheets(
                        container,
                        blob_path,
                        filename,
                        column,
                        operator,
                        value,
                        additional_filter_column=additional_filter_column,
                        additional_filter_operator=additional_filter_operator,
                        additional_filter_value=additional_filter_value,
                        normalize_match=normalize_match_flag,
                        max_rows=int(max_rows),
                    )
                    if cross_sheet_result is not None:
                        return cross_sheet_result
                selected_sheet, workbook_metadata = self._resolve_sheet_selection(
                    container,
                    blob_path,
                    sheet_name=sheet_name,
                    sheet_index=sheet_index,
                    require_explicit_sheet=True,
                )
                df = self._read_tabular_blob_to_dataframe(
                    container,
                    blob_path,
                    sheet_name=selected_sheet,
                    require_explicit_sheet=True,
                )
                df = self._try_numeric_conversion(df)

                if column not in df.columns:
                    return json.dumps(
                        self._build_missing_column_error_payload(
                            container,
                            blob_path,
                            filename,
                            workbook_metadata,
                            selected_sheet,
                            column,
                            related_columns=[additional_filter_column] if additional_filter_column else None,
                            available_columns=list(df.columns),
                        )
                    )

                try:
                    filtered_df, applied_filters = self._apply_optional_dataframe_filters(
                        df,
                        filter_column=column,
                        filter_operator=operator,
                        filter_value=value,
                        additional_filter_column=additional_filter_column,
                        additional_filter_operator=additional_filter_operator,
                        additional_filter_value=additional_filter_value,
                        normalize_match=normalize_match_flag,
                    )
                except KeyError as missing_column_error:
                    missing_column = str(missing_column_error).strip("'")
                    return json.dumps(
                        self._build_missing_column_error_payload(
                            container,
                            blob_path,
                            filename,
                            workbook_metadata,
                            selected_sheet,
                            missing_column,
                            related_columns=[candidate_column for candidate_column in (column, additional_filter_column) if candidate_column],
                            available_columns=list(df.columns),
                        )
                    )
                except ValueError as filter_error:
                    return json.dumps({"error": str(filter_error)})

                limit = int(max_rows)
                filtered = filtered_df.head(limit)
                return json.dumps({
                    "filename": filename,
                    "selected_sheet": selected_sheet if workbook_metadata.get('is_workbook') else None,
                    "filter_applied": applied_filters,
                    "normalize_match": normalize_match_flag,
                    "total_matches": len(filtered_df),
                    "returned_rows": len(filtered),
                    "data": filtered.to_dict(orient='records')
                }, indent=2, default=str)
            except Exception as e:
                log_event(f"[TabularProcessingPlugin] Error filtering rows: {e}", level=logging.WARNING)
                return json.dumps({"error": str(e)})
        return await asyncio.to_thread(_sync_work)

    @kernel_function(
        description=(
            "Search one or more columns, or all columns when search_columns is omitted, for a value or phrase and return matching rows with row-context metadata. "
            "Use this when the relevant column is unclear or when you need to search an entire worksheet or workbook for a topic before deciding which returned content is relevant."
        ),
        name="search_rows"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    async def search_rows(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        search_value: Annotated[str, "The text or value to search for"],
        search_columns: Annotated[Optional[str], "Optional comma-separated columns to search. Omit to search all columns."] = None,
        search_operator: Annotated[str, "Search operator: equals, contains, startswith, endswith"] = "contains",
        return_columns: Annotated[Optional[str], "Optional comma-separated columns to include in each result row. Omit to return the full row."] = None,
        query_expression: Annotated[Optional[str], "Optional pandas DataFrame.query() expression to apply before searching"] = None,
        filter_column: Annotated[Optional[str], "Optional first column filter to narrow the search cohort"] = None,
        filter_operator: Annotated[str, "Optional filter operator when filter_column is provided"] = "equals",
        filter_value: Annotated[Optional[str], "Optional filter value when filter_column is provided"] = None,
        additional_filter_column: Annotated[Optional[str], "Optional second column filter to narrow the search cohort"] = None,
        additional_filter_operator: Annotated[str, "Optional filter operator when additional_filter_column is provided"] = "equals",
        additional_filter_value: Annotated[Optional[str], "Optional filter value when additional_filter_column is provided"] = None,
        normalize_match: Annotated[str, "Whether to normalize string/entity matching for text comparisons (true/false)"] = "false",
        sheet_name: Annotated[Optional[str], "Optional worksheet name for Excel files. When omitted, the plugin may perform a cross-sheet search."] = None,
        sheet_index: Annotated[Optional[str], "Optional zero-based worksheet index for Excel files. Ignored when sheet_name is provided."] = None,
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        max_rows: Annotated[str, "Maximum matching rows to return"] = "100",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON result containing matching rows, matched columns, and search metadata"]:
        """Search rows across one or more columns while preserving row context."""
        def _sync_work():
            try:
                normalize_match_flag = self._parse_boolean_argument(normalize_match, default=False)
                parsed_search_columns = self._parse_optional_column_list_argument(search_columns)
                parsed_return_columns = self._parse_optional_column_list_argument(return_columns)
                container, blob_path = self._resolve_blob_location_with_fallback(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )

                normalized_sheet = (sheet_name or '').strip()
                normalized_sheet_idx = None if sheet_index is None else str(sheet_index).strip()
                if not normalized_sheet and normalized_sheet_idx in (None, ''):
                    cross_sheet_result = self._search_rows_across_sheets(
                        container,
                        blob_path,
                        filename,
                        search_value=search_value,
                        search_columns=parsed_search_columns,
                        search_operator=search_operator,
                        return_columns=parsed_return_columns,
                        query_expression=query_expression,
                        filter_column=filter_column,
                        filter_operator=filter_operator,
                        filter_value=filter_value,
                        additional_filter_column=additional_filter_column,
                        additional_filter_operator=additional_filter_operator,
                        additional_filter_value=additional_filter_value,
                        normalize_match=normalize_match_flag,
                        max_rows=int(max_rows),
                    )
                    if cross_sheet_result is not None:
                        return cross_sheet_result

                selected_sheet, workbook_metadata = self._resolve_sheet_selection(
                    container,
                    blob_path,
                    sheet_name=sheet_name,
                    sheet_index=sheet_index,
                    require_explicit_sheet=True,
                )
                df = self._read_tabular_blob_to_dataframe(
                    container,
                    blob_path,
                    sheet_name=selected_sheet,
                    require_explicit_sheet=True,
                )
                df = self._try_numeric_conversion(df)

                try:
                    filtered_df, applied_filters = self._apply_optional_dataframe_filters(
                        df,
                        query_expression=query_expression,
                        filter_column=filter_column,
                        filter_operator=filter_operator,
                        filter_value=filter_value,
                        additional_filter_column=additional_filter_column,
                        additional_filter_operator=additional_filter_operator,
                        additional_filter_value=additional_filter_value,
                        normalize_match=normalize_match_flag,
                    )
                except KeyError as missing_column_error:
                    missing_column = str(missing_column_error).strip("'")
                    return json.dumps(
                        self._build_missing_column_error_payload(
                            container,
                            blob_path,
                            filename,
                            workbook_metadata,
                            selected_sheet,
                            missing_column,
                            related_columns=[
                                candidate_column
                                for candidate_column in (
                                    *(parsed_search_columns or []),
                                    *(parsed_return_columns or []),
                                    filter_column,
                                    additional_filter_column,
                                )
                                if candidate_column and candidate_column != missing_column
                            ] or None,
                            available_columns=list(df.columns),
                        )
                    )
                except Exception as query_error:
                    return json.dumps({
                        'error': f"Query/filter error: {query_error}",
                        'filename': filename,
                        'selected_sheet': selected_sheet if workbook_metadata.get('is_workbook') else None,
                    })

                try:
                    search_result = self._search_dataframe_rows(
                        filtered_df,
                        search_value=search_value,
                        search_columns=parsed_search_columns,
                        search_operator=search_operator,
                        return_columns=parsed_return_columns,
                        normalize_match=normalize_match_flag,
                        max_rows=int(max_rows),
                    )
                except KeyError as missing_column_error:
                    missing_column = str(missing_column_error).strip("'")
                    return json.dumps(
                        self._build_missing_column_error_payload(
                            container,
                            blob_path,
                            filename,
                            workbook_metadata,
                            selected_sheet,
                            missing_column,
                            related_columns=[
                                candidate_column
                                for candidate_column in (
                                    *(parsed_search_columns or []),
                                    *(parsed_return_columns or []),
                                    filter_column,
                                    additional_filter_column,
                                )
                                if candidate_column and candidate_column != missing_column
                            ] or None,
                            available_columns=list(df.columns),
                        )
                    )
                except ValueError as search_error:
                    return json.dumps({
                        'error': str(search_error),
                        'filename': filename,
                        'selected_sheet': selected_sheet if workbook_metadata.get('is_workbook') else None,
                    })

                return json.dumps({
                    'filename': filename,
                    'selected_sheet': selected_sheet if workbook_metadata.get('is_workbook') else None,
                    'search_value': search_value,
                    'search_operator': search_operator,
                    'searched_columns': search_result['searched_columns'],
                    'matched_columns': search_result['matched_columns'],
                    'return_columns': search_result['return_columns'],
                    'filter_applied': applied_filters,
                    'normalize_match': normalize_match_flag,
                    'total_matches': search_result['total_matches'],
                    'returned_rows': search_result['returned_rows'],
                    'data': search_result['data'],
                }, indent=2, default=str)
            except Exception as e:
                log_event(f"[TabularProcessingPlugin] Error searching rows: {e}", level=logging.WARNING)
                return json.dumps({"error": str(e)})

        return await asyncio.to_thread(_sync_work)

    @kernel_function(
        description=(
            "Execute a pandas query expression against a tabular file for advanced analysis. "
            "The query string uses pandas DataFrame.query() syntax. "
            "Examples: 'Age > 30 and State == \"CA\"', 'Price < 100'"
        ),
        name="query_tabular_data"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    async def query_tabular_data(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        query_expression: Annotated[str, "Pandas query expression (e.g. 'Age > 30 and State == \"CA\"')"],
        sheet_name: Annotated[Optional[str], "Optional worksheet name for Excel files. Required for analytical calls on multi-sheet workbooks unless sheet_index is provided."] = None,
        sheet_index: Annotated[Optional[str], "Optional zero-based worksheet index for Excel files. Ignored when sheet_name is provided."] = None,
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        max_rows: Annotated[str, "Maximum rows to return"] = "100",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON result of the query"]:
        """Execute a pandas query expression against a tabular file."""
        def _sync_work():
            try:
                container, blob_path = self._resolve_blob_location_with_fallback(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )
                # When no explicit sheet_name is given, try cross-sheet query first
                normalized_sheet = (sheet_name or '').strip()
                normalized_sheet_idx = None if sheet_index is None else str(sheet_index).strip()
                if not normalized_sheet and normalized_sheet_idx in (None, ''):
                    cross_sheet_result = self._query_tabular_data_across_sheets(
                        container, blob_path, filename, query_expression,
                        max_rows=int(max_rows),
                    )
                    if cross_sheet_result is not None:
                        return cross_sheet_result
                selected_sheet, workbook_metadata = self._resolve_sheet_selection(
                    container,
                    blob_path,
                    sheet_name=sheet_name,
                    sheet_index=sheet_index,
                    require_explicit_sheet=True,
                )
                df = self._read_tabular_blob_to_dataframe(
                    container,
                    blob_path,
                    sheet_name=selected_sheet,
                    require_explicit_sheet=True,
                )
                df = self._try_numeric_conversion(df)

                result_df, used_reviewer_style_fallback = self._apply_query_expression_with_fallback(
                    df,
                    query_expression=query_expression,
                    normalize_match=False,
                )
                limit = int(max_rows)
                return json.dumps({
                    "filename": filename,
                    "selected_sheet": selected_sheet if workbook_metadata.get('is_workbook') else None,
                    "query_expression": query_expression,
                    "query_expression_fallback": used_reviewer_style_fallback,
                    "total_matches": len(result_df),
                    "returned_rows": min(len(result_df), limit),
                    "data": result_df.head(limit).to_dict(orient='records')
                }, indent=2, default=str)
            except Exception as e:
                log_event(f"[TabularProcessingPlugin] Error querying data: {e}", level=logging.WARNING)
                return json.dumps({"error": f"Query error: {str(e)}. Ensure column names and values are correct."})
        return await asyncio.to_thread(_sync_work)

    @kernel_function(
        description=(
            "Filter rows in one worksheet where the target match column belongs to a cohort defined by values from another worksheet. "
            "Use this for relational workbook questions such as facts owned by a cohort or records tied to a reference sheet membership list."
        ),
        name="filter_rows_by_related_values"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    async def filter_rows_by_related_values(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        source_sheet_name: Annotated[str, "Worksheet that defines the cohort or reference values"],
        source_value_column: Annotated[str, "Column on the source worksheet that contains the canonical cohort values"],
        target_sheet_name: Annotated[str, "Worksheet containing the fact rows to filter"],
        target_match_column: Annotated[str, "Column on the target worksheet that should match the source cohort values"],
        source_query_expression: Annotated[Optional[str], "Optional pandas DataFrame.query() expression to narrow the source cohort"] = None,
        source_filter_column: Annotated[Optional[str], "Optional source-sheet filter column"] = None,
        source_filter_operator: Annotated[str, "Optional source-sheet filter operator"] = "equals",
        source_filter_value: Annotated[Optional[str], "Optional source-sheet filter value"] = None,
        target_query_expression: Annotated[Optional[str], "Optional pandas DataFrame.query() expression to narrow target rows before matching"] = None,
        target_filter_column: Annotated[Optional[str], "Optional target-sheet filter column"] = None,
        target_filter_operator: Annotated[str, "Optional target-sheet filter operator"] = "equals",
        target_filter_value: Annotated[Optional[str], "Optional target-sheet filter value"] = None,
        source_alias_column: Annotated[Optional[str], "Optional alternate or alias source column used for normalized matching"] = None,
        target_alias_column: Annotated[Optional[str], "Optional alternate or alias target column used for normalized matching"] = None,
        normalize_match: Annotated[str, "Whether to normalize entity-style text matching across worksheets (true/false)"] = "true",
        source_sheet_index: Annotated[Optional[str], "Optional zero-based source worksheet index if sheet name is not used"] = None,
        target_sheet_index: Annotated[Optional[str], "Optional zero-based target worksheet index if sheet name is not used"] = None,
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        max_rows: Annotated[str, "Maximum related target rows to return"] = "100",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON result containing explainable set-membership filtering output"]:
        """Filter target rows by membership in a source-sheet cohort."""
        def _sync_work():
            try:
                normalize_match_flag = self._parse_boolean_argument(normalize_match, default=True)
                container, blob_path = self._resolve_blob_location_with_fallback(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )
                result_payload = self._evaluate_related_value_membership(
                    container,
                    blob_path,
                    filename,
                    source_sheet_name=source_sheet_name,
                    source_value_column=source_value_column,
                    target_sheet_name=target_sheet_name,
                    target_match_column=target_match_column,
                    source_sheet_index=source_sheet_index,
                    target_sheet_index=target_sheet_index,
                    source_query_expression=source_query_expression,
                    source_filter_column=source_filter_column,
                    source_filter_operator=source_filter_operator,
                    source_filter_value=source_filter_value,
                    target_query_expression=target_query_expression,
                    target_filter_column=target_filter_column,
                    target_filter_operator=target_filter_operator,
                    target_filter_value=target_filter_value,
                    source_alias_column=source_alias_column,
                    target_alias_column=target_alias_column,
                    normalize_match=normalize_match_flag,
                    max_rows=int(max_rows),
                )
                return json.dumps(result_payload, indent=2, default=str)
            except Exception as e:
                log_event(f"[TabularProcessingPlugin] Error filtering rows by related values: {e}", level=logging.WARNING)
                return json.dumps({"error": str(e)})

        return await asyncio.to_thread(_sync_work)

    @kernel_function(
        description=(
            "Count rows in one worksheet where the target match column belongs to a cohort defined by another worksheet. "
            "Use this for deterministic numerator/denominator calculations and percentages across related sheets."
        ),
        name="count_rows_by_related_values"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    async def count_rows_by_related_values(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        source_sheet_name: Annotated[str, "Worksheet that defines the cohort or reference values"],
        source_value_column: Annotated[str, "Column on the source worksheet that contains the canonical cohort values"],
        target_sheet_name: Annotated[str, "Worksheet containing the fact rows to count"],
        target_match_column: Annotated[str, "Column on the target worksheet that should match the source cohort values"],
        source_query_expression: Annotated[Optional[str], "Optional pandas DataFrame.query() expression to narrow the source cohort"] = None,
        source_filter_column: Annotated[Optional[str], "Optional source-sheet filter column"] = None,
        source_filter_operator: Annotated[str, "Optional source-sheet filter operator"] = "equals",
        source_filter_value: Annotated[Optional[str], "Optional source-sheet filter value"] = None,
        target_query_expression: Annotated[Optional[str], "Optional pandas DataFrame.query() expression to narrow target rows before matching"] = None,
        target_filter_column: Annotated[Optional[str], "Optional target-sheet filter column"] = None,
        target_filter_operator: Annotated[str, "Optional target-sheet filter operator"] = "equals",
        target_filter_value: Annotated[Optional[str], "Optional target-sheet filter value"] = None,
        source_alias_column: Annotated[Optional[str], "Optional alternate or alias source column used for normalized matching"] = None,
        target_alias_column: Annotated[Optional[str], "Optional alternate or alias target column used for normalized matching"] = None,
        normalize_match: Annotated[str, "Whether to normalize entity-style text matching across worksheets (true/false)"] = "true",
        source_sheet_index: Annotated[Optional[str], "Optional zero-based source worksheet index if sheet name is not used"] = None,
        target_sheet_index: Annotated[Optional[str], "Optional zero-based target worksheet index if sheet name is not used"] = None,
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON result containing an explainable relational row count"]:
        """Count target rows by membership in a source-sheet cohort."""
        def _sync_work():
            try:
                normalize_match_flag = self._parse_boolean_argument(normalize_match, default=True)
                container, blob_path = self._resolve_blob_location_with_fallback(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )
                result_payload = self._evaluate_related_value_membership(
                    container,
                    blob_path,
                    filename,
                    source_sheet_name=source_sheet_name,
                    source_value_column=source_value_column,
                    target_sheet_name=target_sheet_name,
                    target_match_column=target_match_column,
                    source_sheet_index=source_sheet_index,
                    target_sheet_index=target_sheet_index,
                    source_query_expression=source_query_expression,
                    source_filter_column=source_filter_column,
                    source_filter_operator=source_filter_operator,
                    source_filter_value=source_filter_value,
                    target_query_expression=target_query_expression,
                    target_filter_column=target_filter_column,
                    target_filter_operator=target_filter_operator,
                    target_filter_value=target_filter_value,
                    source_alias_column=source_alias_column,
                    target_alias_column=target_alias_column,
                    normalize_match=normalize_match_flag,
                    max_rows=50,
                )
                if 'error' not in result_payload:
                    result_payload['row_count'] = result_payload.get('matched_target_row_count', 0)
                    result_payload.pop('data', None)
                    result_payload.pop('returned_rows', None)
                    result_payload.pop('rows_limited', None)
                return json.dumps(result_payload, indent=2, default=str)
            except Exception as e:
                log_event(f"[TabularProcessingPlugin] Error counting rows by related values: {e}", level=logging.WARNING)
                return json.dumps({"error": str(e)})

        return await asyncio.to_thread(_sync_work)

    @kernel_function(
        description=(
            "Perform a group-by aggregation on a tabular file. "
            "Groups data by one column and aggregates another column. "
            "Supported operations: sum, mean, count, min, max, median, std. "
            "Returns top grouped results plus highest and lowest group summary fields."
        ),
        name="group_by_aggregate"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    async def group_by_aggregate(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        group_by_column: Annotated[str, "The column to group by"],
        aggregate_column: Annotated[str, "The column to aggregate"],
        operation: Annotated[str, "Aggregation operation: sum, mean, count, min, max, median, std"],
        sheet_name: Annotated[Optional[str], "Optional worksheet name for Excel files. Required for analytical calls on multi-sheet workbooks unless sheet_index is provided."] = None,
        sheet_index: Annotated[Optional[str], "Optional zero-based worksheet index for Excel files. Ignored when sheet_name is provided."] = None,
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        top_n: Annotated[str, "How many top groups to return in descending or ascending order"] = "10",
        sort_descending: Annotated[str, "Whether top_results should be sorted descending (true/false)"] = "true",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON result of the group-by aggregation"]:
        """Group by one column and aggregate another."""
        def _sync_work():
            try:
                container, blob_path = self._resolve_blob_location_with_fallback(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )
                selected_sheet, workbook_metadata = self._resolve_sheet_selection(
                    container,
                    blob_path,
                    sheet_name=sheet_name,
                    sheet_index=sheet_index,
                    require_explicit_sheet=True,
                )
                df = self._read_tabular_blob_to_dataframe(
                    container,
                    blob_path,
                    sheet_name=selected_sheet,
                    require_explicit_sheet=True,
                )
                df = self._try_numeric_conversion(df)

                for col in [group_by_column, aggregate_column]:
                    if col not in df.columns:
                        related_columns = [group_by_column, aggregate_column]
                        related_columns = [column_name for column_name in related_columns if column_name != col]
                        return json.dumps(
                            self._build_missing_column_error_payload(
                                container,
                                blob_path,
                                filename,
                                workbook_metadata,
                                selected_sheet,
                                col,
                                related_columns=related_columns,
                                available_columns=list(df.columns),
                            )
                        )

                op = operation.lower().strip()
                if op not in {'count', 'sum', 'mean', 'min', 'max', 'median', 'std'}:
                    return json.dumps({
                        "error": "Unsupported operation. Use count, sum, mean, min, max, median, or std."
                    })

                grouped = df.groupby(group_by_column)[aggregate_column].agg(op)
                grouped = grouped.dropna()
                if grouped.empty:
                    return json.dumps({"error": "No grouped results were produced."})

                top_limit = max(1, int(top_n))
                descending = self._parse_boolean_argument(sort_descending, default=True)
                top_results = grouped.sort_values(ascending=not descending).head(top_limit)
                ordered_results = grouped.sort_index()
                summary = self._build_grouped_summary(grouped)

                return json.dumps({
                    "filename": filename,
                    "selected_sheet": selected_sheet if workbook_metadata.get('is_workbook') else None,
                    "group_by": group_by_column,
                    "aggregate_column": aggregate_column,
                    "operation": op,
                    "groups": len(grouped),
                    "top_results": self._series_to_json_dict(top_results),
                    "result": self._series_to_json_dict(ordered_results),
                    **summary,
                }, indent=2, default=str)
            except Exception as e:
                log_event(f"[TabularProcessingPlugin] Error in group-by: {e}", level=logging.WARNING)
                return json.dumps({"error": str(e)})
        return await asyncio.to_thread(_sync_work)

    @kernel_function(
        description=(
            "Group a tabular file by a component extracted from a datetime-like column and aggregate a metric. "
            "Use this for time-based questions such as peak hours, busiest weekdays, or monthly trends. "
            "Supported datetime components: year, month, month_name, day, date, hour, minute, day_name, "
            "weekday_number, quarter, week. Supported operations: count, sum, mean, min, max, median, std. "
            "An optional pandas query filter can be applied before grouping. Returns top grouped results plus highest and lowest summary fields."
        ),
        name="group_by_datetime_component"
    )
    @plugin_function_logger("TabularProcessingPlugin")
    async def group_by_datetime_component(
        self,
        user_id: Annotated[str, "The user ID (from Scope ID in Conversation Metadata)"],
        conversation_id: Annotated[str, "The conversation ID (from Conversation Metadata)"],
        filename: Annotated[str, "The filename of the tabular file"],
        datetime_column: Annotated[str, "The datetime-like column to extract a component from"],
        datetime_component: Annotated[str, "Component: year, month, month_name, day, date, hour, minute, day_name, weekday_number, quarter, or week"],
        aggregate_column: Annotated[Optional[str], "The numeric column to aggregate. Leave empty and use operation='count' to count rows."] = "",
        operation: Annotated[str, "Aggregation operation: count, sum, mean, min, max, median, std"] = "count",
        sheet_name: Annotated[Optional[str], "Optional worksheet name for Excel files. Required for analytical calls on multi-sheet workbooks unless sheet_index is provided."] = None,
        sheet_index: Annotated[Optional[str], "Optional zero-based worksheet index for Excel files. Ignored when sheet_name is provided."] = None,
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        filter_expression: Annotated[Optional[str], "Optional pandas query filter applied before grouping"] = "",
        top_n: Annotated[str, "How many top groups to return in descending order"] = "10",
        sort_descending: Annotated[str, "Whether top_results should be sorted descending (true/false)"] = "true",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON result of the datetime component grouping analysis"]:
        """Group data by a datetime component and aggregate a metric."""
        def _sync_work():
            try:
                container, blob_path = self._resolve_blob_location_with_fallback(
                    user_id,
                    conversation_id,
                    filename,
                    source,
                    group_id=group_id,
                    public_workspace_id=public_workspace_id
                )
                selected_sheet, workbook_metadata = self._resolve_sheet_selection(
                    container,
                    blob_path,
                    sheet_name=sheet_name,
                    sheet_index=sheet_index,
                    require_explicit_sheet=True,
                )
                df = self._read_tabular_blob_to_dataframe(
                    container,
                    blob_path,
                    sheet_name=selected_sheet,
                    require_explicit_sheet=True,
                )
                df = self._try_numeric_conversion(df)

                if filter_expression:
                    try:
                        df = df.query(filter_expression)
                    except Exception as query_error:
                        return json.dumps({
                            "error": f"Filter query error: {query_error}. Ensure column names and values are correct."
                        })

                if datetime_column not in df.columns:
                    related_columns = [aggregate_column] if aggregate_column else []
                    return json.dumps(
                        self._build_missing_column_error_payload(
                            container,
                            blob_path,
                            filename,
                            workbook_metadata,
                            selected_sheet,
                            datetime_column,
                            related_columns=related_columns,
                            available_columns=list(df.columns),
                        )
                    )

                parsed_datetime = self._parse_datetime_like_series(df[datetime_column])
                valid_mask = parsed_datetime.notna()
                if not valid_mask.any():
                    return json.dumps({
                        "error": (
                            f"Could not parse any datetime values from column '{datetime_column}'. "
                            "Try a different datetime column or inspect the file schema preview."
                        )
                    })

                filtered_df = df.loc[valid_mask].copy()
                parsed_datetime = parsed_datetime.loc[valid_mask]
                component_values = self._extract_datetime_component(parsed_datetime, datetime_component)

                component_column_name = f"__datetime_component_{self._normalize_datetime_component(datetime_component)}"
                filtered_df[component_column_name] = component_values

                op = (operation or 'count').strip().lower()
                if op not in {'count', 'sum', 'mean', 'min', 'max', 'median', 'std'}:
                    return json.dumps({
                        "error": "Unsupported operation. Use count, sum, mean, min, max, median, or std."
                    })

                aggregate_column_name = (aggregate_column or '').strip()
                if op == 'count' and not aggregate_column_name:
                    grouped = filtered_df.groupby(component_column_name).size()
                else:
                    if not aggregate_column_name:
                        return json.dumps({
                            "error": "aggregate_column is required unless operation='count'."
                        })
                    if aggregate_column_name not in filtered_df.columns:
                        return json.dumps(
                            self._build_missing_column_error_payload(
                                container,
                                blob_path,
                                filename,
                                workbook_metadata,
                                selected_sheet,
                                aggregate_column_name,
                                related_columns=[datetime_column],
                                available_columns=list(filtered_df.columns),
                            )
                        )
                    grouped = filtered_df.groupby(component_column_name)[aggregate_column_name].agg(op)

                grouped = grouped.dropna()
                if grouped.empty:
                    return json.dumps({
                        "error": "No grouped results were produced after filtering and datetime parsing."
                    })

                top_limit = max(1, int(top_n))
                descending = self._parse_boolean_argument(sort_descending, default=True)
                top_results = grouped.sort_values(ascending=not descending).head(top_limit)
                ordered_results = self._ordered_grouped_results(grouped, datetime_component)
                summary = self._build_grouped_summary(grouped)

                return json.dumps({
                    "filename": filename,
                    "selected_sheet": selected_sheet if workbook_metadata.get('is_workbook') else None,
                    "datetime_column": datetime_column,
                    "datetime_component": self._normalize_datetime_component(datetime_component),
                    "aggregate_column": aggregate_column_name or None,
                    "operation": op,
                    "filter_expression": filter_expression or None,
                    "parsed_rows": int(valid_mask.sum()),
                    "dropped_rows": int((~valid_mask).sum()),
                    "groups": int(len(grouped)),
                    "top_results": self._series_to_json_dict(top_results),
                    "result": self._series_to_json_dict(ordered_results),
                    **summary,
                }, indent=2, default=str)
            except Exception as e:
                log_event(f"[TabularProcessingPlugin] Error in datetime component grouping: {e}", level=logging.WARNING)
                return json.dumps({"error": str(e)})
        return await asyncio.to_thread(_sync_work)
