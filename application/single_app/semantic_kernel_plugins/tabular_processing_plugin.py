# tabular_processing_plugin.py
"""
TabularProcessingPlugin for Semantic Kernel: provides data analysis operations
on tabular files (CSV, XLSX, XLS, XLSM) stored in Azure Blob Storage.

Works with workspace documents (user-documents, group-documents, public-documents)
and chat-uploaded documents (personal-chat container).
"""
import asyncio
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

    SUPPORTED_EXTENSIONS = {'.csv', '.xlsx', '.xls', '.xlsm'}
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
        self._df_cache = {}  # Per-instance cache: (container, blob_name) -> DataFrame

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

    def _read_tabular_blob_to_dataframe(self, container_name: str, blob_name: str) -> pandas.DataFrame:
        """Download a blob and read it into a pandas DataFrame. Uses per-instance cache."""
        cache_key = (container_name, blob_name)
        if cache_key in self._df_cache:
            log_event(f"[TabularProcessingPlugin] Cache hit for {blob_name}", level=logging.DEBUG)
            return self._df_cache[cache_key].copy()

        client = self._get_blob_service_client()
        blob_client = client.get_blob_client(container=container_name, blob=blob_name)
        stream = blob_client.download_blob()
        data = stream.readall()

        name_lower = blob_name.lower()
        if name_lower.endswith('.csv'):
            df = pandas.read_csv(io.BytesIO(data), keep_default_na=False, dtype=str)
        elif name_lower.endswith('.xlsx') or name_lower.endswith('.xlsm'):
            df = pandas.read_excel(io.BytesIO(data), engine='openpyxl', keep_default_na=False, dtype=str)
        elif name_lower.endswith('.xls'):
            df = pandas.read_excel(io.BytesIO(data), engine='xlrd', keep_default_na=False, dtype=str)
        else:
            raise ValueError(f"Unsupported tabular file type: {blob_name}")

        self._df_cache[cache_key] = df
        log_event(f"[TabularProcessingPlugin] Cached DataFrame for {blob_name} ({len(df)} rows)", level=logging.DEBUG)
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
                    results.append({
                        "filename": filename,
                        "blob_path": blob,
                        "source": "workspace",
                        "container": storage_account_user_documents_container_name
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
                    results.append({
                        "filename": filename,
                        "blob_path": blob,
                        "source": "chat",
                        "container": storage_account_personal_chat_container_name
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
                        results.append({
                            "filename": filename,
                            "blob_path": blob,
                            "source": "group",
                            "container": storage_account_group_documents_container_name
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
                        results.append({
                            "filename": filename,
                            "blob_path": blob,
                            "source": "public",
                            "container": storage_account_public_documents_container_name
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
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON summary of the tabular file"]:
        """Get schema and preview of a tabular file."""
        def _sync_work():
            try:
                container, blob_path = self._resolve_blob_location(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )
                df = self._read_tabular_blob_to_dataframe(container, blob_path)
                df_numeric = self._try_numeric_conversion(df.copy())

                summary = {
                    "filename": filename,
                    "row_count": len(df),
                    "column_count": len(df.columns),
                    "columns": list(df.columns),
                    "dtypes": {col: str(dtype) for col, dtype in df_numeric.dtypes.items()},
                    "preview": df.head(5).to_dict(orient='records'),
                    "null_counts": df.isnull().sum().to_dict()
                }
                return json.dumps(summary, indent=2, default=str)
            except Exception as e:
                log_event(f"[TabularProcessingPlugin] Error describing file: {e}", level=logging.WARNING)
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
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON result of the aggregation"]:
        """Execute an aggregation operation on a column."""
        def _sync_work():
            try:
                container, blob_path = self._resolve_blob_location(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )
                df = self._read_tabular_blob_to_dataframe(container, blob_path)
                df = self._try_numeric_conversion(df)

                if column not in df.columns:
                    return json.dumps({"error": f"Column '{column}' not found. Available: {list(df.columns)}"})

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
                    result = series.value_counts().to_dict()
                else:
                    return json.dumps({"error": f"Unsupported operation: {operation}. Use sum, mean, count, min, max, median, std, nunique, value_counts."})

                return json.dumps({"column": column, "operation": op, "result": result}, indent=2, default=str)
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
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        max_rows: Annotated[str, "Maximum rows to return"] = "100",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON list of matching rows"]:
        """Filter rows based on a condition."""
        def _sync_work():
            try:
                container, blob_path = self._resolve_blob_location(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )
                df = self._read_tabular_blob_to_dataframe(container, blob_path)
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
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        max_rows: Annotated[str, "Maximum rows to return"] = "100",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON result of the query"]:
        """Execute a pandas query expression against a tabular file."""
        def _sync_work():
            try:
                container, blob_path = self._resolve_blob_location(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )
                df = self._read_tabular_blob_to_dataframe(container, blob_path)
                df = self._try_numeric_conversion(df)

                result_df = df.query(query_expression)
                limit = int(max_rows)
                return json.dumps({
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
        source: Annotated[str, "Source: 'workspace', 'chat', 'group', or 'public'"] = "chat",
        top_n: Annotated[str, "How many top groups to return in descending or ascending order"] = "10",
        sort_descending: Annotated[str, "Whether top_results should be sorted descending (true/false)"] = "true",
        group_id: Annotated[Optional[str], "Group ID (for group workspace documents)"] = None,
        public_workspace_id: Annotated[Optional[str], "Public workspace ID (for public workspace documents)"] = None,
    ) -> Annotated[str, "JSON result of the group-by aggregation"]:
        """Group by one column and aggregate another."""
        def _sync_work():
            try:
                container, blob_path = self._resolve_blob_location(
                    user_id, conversation_id, filename, source,
                    group_id=group_id, public_workspace_id=public_workspace_id
                )
                df = self._read_tabular_blob_to_dataframe(container, blob_path)
                df = self._try_numeric_conversion(df)

                for col in [group_by_column, aggregate_column]:
                    if col not in df.columns:
                        return json.dumps({"error": f"Column '{col}' not found. Available: {list(df.columns)}"})

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
                container, blob_path = self._resolve_blob_location(
                    user_id,
                    conversation_id,
                    filename,
                    source,
                    group_id=group_id,
                    public_workspace_id=public_workspace_id
                )
                df = self._read_tabular_blob_to_dataframe(container, blob_path)
                df = self._try_numeric_conversion(df)

                if filter_expression:
                    try:
                        df = df.query(filter_expression)
                    except Exception as query_error:
                        return json.dumps({
                            "error": f"Filter query error: {query_error}. Ensure column names and values are correct."
                        })

                if datetime_column not in df.columns:
                    return json.dumps({
                        "error": f"Column '{datetime_column}' not found. Available: {list(df.columns)}"
                    })

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
                        return json.dumps({
                            "error": f"Column '{aggregate_column_name}' not found. Available: {list(filtered_df.columns)}"
                        })
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
