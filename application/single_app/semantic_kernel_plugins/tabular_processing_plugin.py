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
import warnings
import pandas
from typing import Annotated, Optional, List
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
        'aggregate_column',
        'filter_rows',
        'query_tabular_data',
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

    def __init__(self):
        self._df_cache = {}  # Per-instance cache: (container, blob_name, sheet_name) -> DataFrame
        self._blob_data_cache = {}  # Per-instance cache: (container, blob_name) -> raw bytes
        self._workbook_metadata_cache = {}  # Per-instance cache: (container, blob_name) -> workbook metadata
        self._default_sheet_overrides = {}  # (container, blob_name) -> default sheet name

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

        normalized_sheet_name = (sheet_name or '').strip()
        if normalized_sheet_name:
            for candidate in available_sheets:
                if candidate == normalized_sheet_name:
                    return candidate, workbook_metadata
            for candidate in available_sheets:
                if candidate.lower() == normalized_sheet_name.lower():
                    return candidate, workbook_metadata
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
            for candidate in available_sheets:
                if candidate == override_sheet or candidate.lower() == override_sheet.lower():
                    return candidate, workbook_metadata

        if require_explicit_sheet:
            raise ValueError(
                f"Workbook '{blob_name}' has multiple sheets: {available_sheets}. "
                "Specify sheet_name or sheet_index on analytical calls."
            )

        return workbook_metadata.get('default_sheet'), workbook_metadata

    def _filter_rows_across_sheets(
        self,
        container_name: str,
        blob_name: str,
        filename: str,
        column: str,
        operator_str: str,
        value: str,
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

            sheets_searched.append(sheet)
            series = df[column]
            op = operator_str.strip().lower()

            numeric_value = None
            try:
                numeric_value = float(value)
            except (ValueError, TypeError):
                pass

            if op in ('==', 'equals'):
                if numeric_value is not None and pandas.api.types.is_numeric_dtype(series):
                    mask = series == numeric_value
                else:
                    mask = series.astype(str).str.lower() == value.lower()
            elif op == '!=':
                if numeric_value is not None and pandas.api.types.is_numeric_dtype(series):
                    mask = series != numeric_value
                else:
                    mask = series.astype(str).str.lower() != value.lower()
            elif op == '>':
                mask = series > numeric_value if numeric_value is not None else pandas.Series([False] * len(series))
            elif op == '<':
                mask = series < numeric_value if numeric_value is not None else pandas.Series([False] * len(series))
            elif op == '>=':
                mask = series >= numeric_value if numeric_value is not None else pandas.Series([False] * len(series))
            elif op == '<=':
                mask = series <= numeric_value if numeric_value is not None else pandas.Series([False] * len(series))
            elif op == 'contains':
                mask = series.astype(str).str.contains(value, case=False, na=False)
            elif op == 'startswith':
                mask = series.astype(str).str.lower().str.startswith(value.lower())
            elif op == 'endswith':
                mask = series.astype(str).str.lower().str.endswith(value.lower())
            else:
                continue

            sheet_matches = int(mask.sum())
            if sheet_matches == 0:
                continue

            sheets_matched.append(sheet)
            total_matches += sheet_matches
            remaining_capacity = max(0, max_rows - len(combined_results))
            if remaining_capacity > 0:
                filtered = df[mask].head(remaining_capacity)
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
            "total_matches": total_matches,
            "returned_rows": len(combined_results),
            "data": combined_results,
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
            series = df[lookup_column]

            if operator in {'equals', '=='}:
                mask = series.astype(str).str.lower() == normalized_lookup_value.lower()
            elif operator == 'contains':
                mask = series.astype(str).str.contains(normalized_lookup_value, case=False, na=False)
            elif operator == 'startswith':
                mask = series.astype(str).str.lower().str.startswith(normalized_lookup_value.lower())
            elif operator == 'endswith':
                mask = series.astype(str).str.lower().str.endswith(normalized_lookup_value.lower())
            else:
                mask = series.astype(str).str.lower() == normalized_lookup_value.lower()

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
                result_df = df.query(query_expression)
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
        for workbook_sheet_name in workbook_metadata.get('sheet_names', []):
            df = self._read_tabular_blob_to_dataframe(
                container_name,
                blob_name,
                sheet_name=workbook_sheet_name,
            )
            per_sheet_schemas[workbook_sheet_name] = self._build_sheet_schema_summary(
                df,
                workbook_sheet_name,
                preview_rows=preview_rows,
            )

        return {
            'filename': filename,
            'is_workbook': True,
            'sheet_names': workbook_metadata.get('sheet_names', []),
            'sheet_count': workbook_metadata.get('sheet_count', 0),
            'selected_sheet': None,
            'per_sheet_schemas': per_sheet_schemas,
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

                series = df[lookup_column]
                operator = (match_operator or 'equals').strip().lower()
                normalized_lookup_value = str(lookup_value)

                if operator in {'equals', '=='}:
                    mask = series.astype(str).str.lower() == normalized_lookup_value.lower()
                elif operator == 'contains':
                    mask = series.astype(str).str.contains(normalized_lookup_value, case=False, na=False)
                elif operator == 'startswith':
                    mask = series.astype(str).str.lower().str.startswith(normalized_lookup_value.lower())
                elif operator == 'endswith':
                    mask = series.astype(str).str.lower().str.endswith(normalized_lookup_value.lower())
                else:
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
            "Supports operators: ==, !=, >, <, >=, <=, contains, startswith, endswith."
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
                container, blob_path = self._resolve_blob_location_with_fallback(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )
                # When no explicit sheet_name is given, try cross-sheet search first
                normalized_sheet = (sheet_name or '').strip()
                normalized_sheet_idx = None if sheet_index is None else str(sheet_index).strip()
                if not normalized_sheet and normalized_sheet_idx in (None, ''):
                    cross_sheet_result = self._filter_rows_across_sheets(
                        container, blob_path, filename, column, operator, value,
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
                    return json.dumps({"error": f"Column '{column}' not found. Available: {list(df.columns)}"})

                series = df[column]
                op = operator.strip().lower()

                numeric_value = None
                try:
                    numeric_value = float(value)
                except (ValueError, TypeError):
                    pass

                if op == '==' or op == 'equals':
                    if numeric_value is not None and pandas.api.types.is_numeric_dtype(series):
                        mask = series == numeric_value
                    else:
                        mask = series.astype(str).str.lower() == value.lower()
                elif op == '!=':
                    if numeric_value is not None and pandas.api.types.is_numeric_dtype(series):
                        mask = series != numeric_value
                    else:
                        mask = series.astype(str).str.lower() != value.lower()
                elif op == '>':
                    mask = series > numeric_value
                elif op == '<':
                    mask = series < numeric_value
                elif op == '>=':
                    mask = series >= numeric_value
                elif op == '<=':
                    mask = series <= numeric_value
                elif op == 'contains':
                    mask = series.astype(str).str.contains(value, case=False, na=False)
                elif op == 'startswith':
                    mask = series.astype(str).str.lower().str.startswith(value.lower())
                elif op == 'endswith':
                    mask = series.astype(str).str.lower().str.endswith(value.lower())
                else:
                    return json.dumps({"error": f"Unsupported operator: {operator}"})

                limit = int(max_rows)
                filtered = df[mask].head(limit)
                return json.dumps({
                    "filename": filename,
                    "selected_sheet": selected_sheet if workbook_metadata.get('is_workbook') else None,
                    "total_matches": int(mask.sum()),
                    "returned_rows": len(filtered),
                    "data": filtered.to_dict(orient='records')
                }, indent=2, default=str)
            except Exception as e:
                log_event(f"[TabularProcessingPlugin] Error filtering rows: {e}", level=logging.WARNING)
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

                result_df = df.query(query_expression)
                limit = int(max_rows)
                return json.dumps({
                    "filename": filename,
                    "selected_sheet": selected_sheet if workbook_metadata.get('is_workbook') else None,
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
