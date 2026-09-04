# azure_billing_plugin.py
"""
Azure Billing Plugin for Semantic Kernel
- Supports user (Entra ID) and service principal authentication
- Uses Azure Cost Management REST API for billing, budgets, alerts, forecasting
- Renders dynamic SimpleChat inline charts for Cost Management data
- Returns tabular data as CSV for minimal token usage
- Requires user_impersonation for user auth on 40a69793-8fe6-4db1-9591-dbc5c57b17d8 (Azure Service Management)
"""

import io
import requests
import csv
import logging
import time
import re
import datetime
from typing import Dict, Any, List, Optional, Union
import json
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel.functions import kernel_function
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger
from functions_authentication import get_valid_access_token_for_plugins
from functions_appinsights import log_event
from functions_debug import debug_print
from azure.core.credentials import AccessToken, TokenCredential
from semantic_kernel_plugins.chart_plugin import ChartPlugin


RESOURCE_ID_REGEX = r"^/subscriptions/(?P<subscriptionId>[a-fA-F0-9-]+)/?(?:resourceGroups/(?P<resourceGroupName>[^/]+))?$"
TIME_FRAME_TYPE = ["MonthToDate", "BillingMonthToDate", "WeekToDate", "Custom"] # "TheLastMonth, TheLastBillingMonth" are not supported in MAG
QUERY_TYPE = ["Usage", "ActualCost", "AmortizedCost"]
GRANULARITY_TYPE = ["None", "Daily", "Monthly", "Accumulated"]
GROUPING_TYPE = ["Dimension", "TagKey"]
AGGREGATION_FUNCTIONS = ["Sum"] #, "Average", "Min", "Max", "Count", "None"]
AGGREGATION_COLUMNS= ["Cost", "CostUSD", "PreTaxCost", "PreTaxCostUSD"]
DEFAULT_GROUPING_DIMENSIONS = ["None", "BillingPeriod", "ChargeType", "Frequency", "MeterCategory", "MeterId", "MeterSubCategory", "Product", "ResourceGroupName", "ResourceLocation", "ResourceType", "ServiceFamily", "ServiceName", "SubscriptionId", "SubscriptionName", "Tag"]
SUPPORTED_GRAPH_TYPES = ["pie", "column_stacked", "column_grouped", "line", "area"]
GRAPH_TYPE_TO_INLINE_CHART_KIND = {
    "pie": "pie",
    "column_stacked": "stacked_bar",
    "column_grouped": "bar",
    "line": "line",
    "area": "area",
}
AZURE_BILLING_AUTH_FAILURE_MESSAGE = (
    "Azure Billing service principal authentication failed. "
    "Check Application Insights for [AzureBilling] details."
)

class AzureBillingPlugin(BasePlugin):
    def __init__(self, manifest: Dict[str, Any]):
        super().__init__(manifest)
        self.manifest = manifest
        self.additionalFields = manifest.get('additionalFields', {})
        self.auth = manifest.get('auth', {})
        endpoint = manifest.get('endpoint', 'https://management.azure.com').rstrip('/')
        if not endpoint.startswith('https://'):
            # Remove any leading http:// and force https://
            endpoint = 'https://' + endpoint.lstrip('http://').lstrip('https://')
        self.endpoint = endpoint
        self.metadata_dict = manifest.get('metadata', {})
        self.api_version = self.additionalFields.get('apiVersion', '2023-03-01')
        self.grouping_dimensions: List[str] = list(DEFAULT_GROUPING_DIMENSIONS)

    def _get_token(self) -> Optional[str]:
        """Get an access token for Azure REST API calls."""
        auth_type = self.auth.get('type')
        if auth_type == 'servicePrincipal':
            # Service principal: use client credentials
            tenant_id = self.auth.get('tenantId')
            client_id = self.auth.get('identity')
            client_secret = self.auth.get('key')

            # Determine AAD authority host based on management endpoint (public, gov, china)
            host = self.endpoint.lower()
            if "management.usgovcloudapi.net" in host:
                aad_authority_host = "login.microsoftonline.us"
            elif "management.azure.com" in host:
                aad_authority_host = "login.microsoftonline.com"
            else:
                aad_authority_host = "login.microsoftonline.com"

            if not tenant_id or not client_id or not client_secret:
                raise ValueError("Service principal auth requires tenantId, identity (client id), and key (client secret) in manifest 'auth'.")

            token_url = f"https://{aad_authority_host}/{tenant_id}/oauth2/v2.0/token"
            data = {
                'grant_type': 'client_credentials',
                'client_id': client_id,
                'client_secret': client_secret,
                'scope': f'{self.endpoint.rstrip('/')}/.default'
            }
            try:
                resp = requests.post(token_url, data=data, timeout=10)
                resp.raise_for_status()
            except requests.exceptions.HTTPError as e:
                status_code = getattr(getattr(e, 'response', None), 'status_code', None)
                log_event(
                    "[AzureBilling] Service principal token request failed.",
                    extra={"status_code": status_code, "error_type": type(e).__name__},
                    level=logging.ERROR,
                )
                raise RuntimeError(AZURE_BILLING_AUTH_FAILURE_MESSAGE) from e
            except requests.exceptions.RequestException as e:
                log_event(
                    "[AzureBilling] Service principal token request error.",
                    extra={"error_type": type(e).__name__},
                    level=logging.ERROR,
                )
                raise RuntimeError(AZURE_BILLING_AUTH_FAILURE_MESSAGE) from e
            try:
                token = resp.json().get('access_token')
            except ValueError:
                log_event(
                    "[AzureBilling] Token endpoint returned invalid JSON.",
                    extra={"status_code": getattr(resp, 'status_code', None)},
                    level=logging.ERROR,
                )
                raise RuntimeError(AZURE_BILLING_AUTH_FAILURE_MESSAGE)
            if not token:
                log_event(
                    "[AzureBilling] Token endpoint response did not include an access token.",
                    extra={"status_code": getattr(resp, 'status_code', None)},
                    level=logging.ERROR,
                )
                raise RuntimeError(AZURE_BILLING_AUTH_FAILURE_MESSAGE)
            return token
        else:
            class UserTokenCredential(TokenCredential):
                def __init__(self, scope):
                    self.scope = scope

                def get_token(self, *args, **kwargs):
                    token_result = get_valid_access_token_for_plugins(scopes=[self.scope])
                    if isinstance(token_result, dict) and token_result.get("access_token"):
                        token = token_result["access_token"]
                    elif isinstance(token_result, dict) and token_result.get("error"):
                        # Propagate error up to plugin
                        raise Exception(token_result)
                    else:
                        raise RuntimeError("Could not acquire user access token for Log Analytics API.")
                    expires_on = int(time.time()) + 300
                    return AccessToken(token, expires_on)
            # User: use session token helper
            scope = f"{self.endpoint.rstrip('/')}/.default"
            credential = UserTokenCredential(scope)
            return credential.get_token(scope).token

    def _get_headers(self) -> Dict[str, str]:
        token = self._get_token()
        if isinstance(token, dict) and ("error" in token or "consent_url" in token):
            return token
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

    def _get(self, url: str, params: Dict[str, Any] = None) -> Any:
        headers = self._get_headers()
        if isinstance(headers, dict) and ("error" in headers or "consent_url" in headers):
            return headers
        if params:
            debug_print(f"GET {url} with params: {params}")
            resp = requests.get(url, headers=headers, params=params)
        else:
            debug_print(f"GET {url} without params")
            resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def _post(self, url: str, data: Dict[str, Any]) -> Any:
        headers = self._get_headers()
        resp = requests.post(url, headers=headers, json=data)
        resp.raise_for_status()
        return resp.json()

    def _csv_from_table(self, rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return ''
        all_keys = set()
        for row in rows:
            all_keys.update(row.keys())
        fieldnames = list(all_keys)
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

    def _flatten_dict(self, d: Dict[str, Any], parent_key: str = '', sep: str = '.') -> Dict[str, Any]:
        """Flatten a nested dict into a single-level dict with dotted keys.

        Example: {'properties': {'details': {'threshold': 0.8}}} => {'properties.details.threshold': 0.8}
        """
        items = {}
        for k, v in (d or {}).items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.update(self._flatten_dict(v, new_key, sep=sep))
            else:
                items[new_key] = v
        return items

    def _parse_csv_to_rows(self, data_csv: Union[str, List[str]]) -> List[Dict[str, Any]]:
        """Parse CSV content (string or list-of-lines) into list[dict].

        - Accepts a CSV string or a list of CSV lines.
        - Converts numeric-looking fields to float where possible.
        """
        # Accept list of lines or full string
        if isinstance(data_csv, list):
            csv_text = "\n".join(data_csv)
        else:
            csv_text = str(data_csv)

        f = io.StringIO(csv_text)
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            parsed = {}
            for k, v in row.items():
                if v is None:
                    parsed[k] = None
                    continue
                s = v.strip()
                # Try int then float conversion; leave as string if neither
                if s == '':
                    parsed[k] = ''
                else:
                    # remove thousands separators
                    s_clean = s.replace(',', '')
                    try:
                        if re.match(r'^-?\d+$', s_clean):
                            parsed[k] = int(s_clean)
                        else:
                            # float detection (handles scientific notation)
                            if re.match(r'^-?\d*\.?\d+(e[-+]?\d+)?$', s_clean, re.IGNORECASE):
                                parsed[k] = float(s_clean)
                            else:
                                parsed[k] = s
                    except Exception:
                        parsed[k] = s
            rows.append(parsed)
        return rows

    def _coerce_rows_for_plot(self, data) -> List[Dict[str, Any]]:
        """Normalize incoming data into a list of row dictionaries for plotting."""
        if isinstance(data, list):
            if not data:
                raise ValueError("No data provided for plotting")
            first = data[0]
            if isinstance(first, dict):
                try:
                    return [dict(row) for row in data]
                except Exception as exc:
                    raise ValueError("data must contain serializable dictionaries") from exc
            if isinstance(first, str):
                return self._parse_csv_to_rows(data)
            raise ValueError("data must be a list of dicts, a CSV string, or a list of CSV lines")
        if isinstance(data, str):
            if not data.strip():
                raise ValueError("No data provided for plotting")
            return self._parse_csv_to_rows(data)
        raise ValueError("data must be a list of dicts, a CSV string, or a list of CSV lines")

    def _build_plot_hints(self, rows: List[Dict[str, Any]], columns: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Generate plotting hints based on the returned Cost Management rows."""
        hints: Dict[str, Any] = {
            "available_graph_types": SUPPORTED_GRAPH_TYPES,
            "row_count": len(rows or []),
            "label_candidates": [],
            "numeric_candidates": [],
            "recommended": {}
        }

        if not rows:
            return hints

        sample = rows[0]
        numeric_candidates = [k for k, v in sample.items() if isinstance(v, (int, float))]
        resource_preferred = [
            "ResourceType",
            "ResourceGroupName",
            "ResourceName",
            "ResourceLocation",
            "ServiceName",
            "Product",
            "MeterCategory",
            "MeterSubCategory",
            "SubscriptionName",
            "SubscriptionId"
        ]
        temporal_terms = ("date", "time", "month", "period")
        temporal_candidates: List[str] = []
        label_candidates: List[str] = []

        for key, value in sample.items():
            if isinstance(value, (int, float)):
                continue
            if key not in label_candidates:
                label_candidates.append(key)
            lowered = key.lower()
            if any(term in lowered for term in temporal_terms) and key not in temporal_candidates:
                temporal_candidates.append(key)

        ordered_labels: List[str] = []
        for preferred in resource_preferred:
            if preferred in sample and preferred not in ordered_labels:
                ordered_labels.append(preferred)

        for key in label_candidates:
            if key not in ordered_labels and key not in temporal_candidates:
                ordered_labels.append(key)

        for temporal in temporal_candidates:
            if temporal not in ordered_labels:
                ordered_labels.append(temporal)

        hints["label_candidates"] = ordered_labels or label_candidates
        hints["numeric_candidates"] = numeric_candidates

        cost_focused = [k for k in numeric_candidates if "cost" in k.lower()]
        if cost_focused:
            y_keys = cost_focused[:3]
        else:
            y_keys = numeric_candidates[:3]

        pie_label = next((k for k in ordered_labels if "resource" in k.lower()), None)
        if not pie_label and ordered_labels:
            pie_label = ordered_labels[0]

        pie_value = y_keys[0] if y_keys else None
        hints["recommended"]["pie"] = {
            "graph_type": "pie",
            "x_keys": [pie_label] if pie_label else [],
            "y_keys": [pie_value] if pie_value else []
        }

        temporal_primary = next((k for k in ordered_labels if any(term in k.lower() for term in temporal_terms)), None)
        stack_candidate = next((k for k in ordered_labels if k != temporal_primary), None)
        default_x_keys: List[str] = []

        if temporal_primary:
            default_x_keys.append(temporal_primary)
            if stack_candidate:
                default_x_keys.append(stack_candidate)
            default_graph_type = "line" if len(y_keys) <= 2 else "column_grouped"
        else:
            if ordered_labels:
                default_x_keys.append(ordered_labels[0])
            default_graph_type = "column_stacked" if len(y_keys) > 1 else "pie"

        hints["recommended"]["default"] = {
            "graph_type": default_graph_type,
            "x_keys": default_x_keys,
            "y_keys": y_keys
        }

        if columns:
            column_summary = []
            for column in columns:
                if not isinstance(column, dict):
                    continue
                column_summary.append({
                    "name": column.get("name") or column.get("displayName"),
                    "type": column.get("type") or column.get("dataType"),
                })
            hints["columns"] = column_summary

        return hints

    def _iso_utc(self, dt: datetime.datetime) -> str:
        return dt.astimezone(datetime.timezone.utc).isoformat()

    def _add_months(self, dt: datetime.datetime, months: int) -> datetime.datetime:
        # Add (or subtract) months without external deps.
        year = dt.year + (dt.month - 1 + months) // 12
        month = (dt.month - 1 + months) % 12 + 1
        day = min(dt.day, [31,
                        29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
                        31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month-1])
        return dt.replace(year=year, month=month, day=day)

    def _first_day_of_month(self, dt: datetime.datetime) -> datetime.datetime:
        return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def _last_day_of_month(self, dt: datetime.datetime) -> datetime.datetime:
        # move to first of next month then subtract one second
        next_month = self._add_months(self._first_day_of_month(dt), 1)
        return next_month - datetime.timedelta(seconds=1)

    def _last_n_months_timeperiod(self, n: int):
        now = datetime.datetime.now(datetime.timezone.utc)
        start = self._add_months(now, -n)
        return {"from": self._iso_utc(start), "to": self._iso_utc(now)}

    def _previous_n_months_timeperiod(self, n: int):
        today = datetime.datetime.now(datetime.timezone.utc)
        first_this_month = self._first_day_of_month(today)
        last_of_prev = first_this_month - datetime.timedelta(seconds=1)
        first_of_earliest = self._first_day_of_month(self._add_months(first_this_month, -n))
        # ensure full days for readability
        return {
            "from": self._iso_utc(first_of_earliest),
            "to": self._iso_utc(last_of_prev.replace(hour=23, minute=59, second=59, microsecond=0))
        }

    def _parse_datetime_to_utc(
        self,
        value: Union[str, datetime.datetime, datetime.date],
        field_name: str,
    ) -> datetime.datetime:
        """Normalize supported datetime inputs into timezone-aware UTC datetimes."""

        if value is None:
            raise ValueError(f"{field_name} must be provided when using a custom range.")

        if isinstance(value, datetime.datetime):
            dt_value = value
        elif isinstance(value, datetime.date):
            dt_value = datetime.datetime.combine(value, datetime.time.min)
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                raise ValueError(f"{field_name} must be a non-empty ISO-8601 string.")
            normalized = text[:-1] + "+00:00" if text[-1] in {"Z", "z"} else text
            if "T" not in normalized and " " not in normalized:
                raise ValueError(
                    f"{field_name} must include a time component (e.g., 2025-11-30T23:59:59Z)."
                )
            try:
                dt_value = datetime.datetime.fromisoformat(normalized)
            except ValueError as exc:
                raise ValueError(
                    f"{field_name} must be ISO-8601 formatted (e.g., 2025-11-30T23:59:59Z or 2025-11-30T23:59:59-05:00)."
                ) from exc
        else:
            raise ValueError(
                f"{field_name} must be a string, datetime, or date instance."
            )

        if dt_value.tzinfo is None:
            dt_value = dt_value.replace(tzinfo=datetime.timezone.utc)
        else:
            dt_value = dt_value.astimezone(datetime.timezone.utc)

        return dt_value

    def _build_custom_time_period(
        self,
        start_datetime: Optional[Union[str, datetime.datetime, datetime.date]],
        end_datetime: Optional[Union[str, datetime.datetime, datetime.date]],
    ) -> Dict[str, str]:
        """Return a Custom timeframe dictionary derived from start/end inputs or defaults."""

        if start_datetime is None and end_datetime is None:
            now = datetime.datetime.now(datetime.timezone.utc)
            month_start = self._first_day_of_month(now)
            return {"from": self._iso_utc(month_start), "to": self._iso_utc(now)}

        if (start_datetime is None) != (end_datetime is None):
            raise ValueError("start_datetime and end_datetime must both be provided.")

        start_dt = self._parse_datetime_to_utc(start_datetime, "start_datetime")
        end_dt = self._parse_datetime_to_utc(end_datetime, "end_datetime")

        if start_dt > end_dt:
            raise ValueError("start_datetime must be earlier than end_datetime")

        return {"from": self._iso_utc(start_dt), "to": self._iso_utc(end_dt)}

    def _normalize_enum(self, value: Optional[str], choices: List[str]) -> Optional[str]:
        """
        Normalize a string to one of the canonical choices in a case-insensitive way.
        Returns the canonical choice if matched, otherwise None.
        """
        if value is None:
            return None
        if not isinstance(value, str):
            return None
        v = value.strip()
        # quick exact match
        if v in choices:
            return v
        # case-insensitive match
        lower_map = {c.lower(): c for c in choices}
        return lower_map.get(v.lower())

    @property
    def display_name(self) -> str:
        return "Azure Billing"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "name": self.metadata_dict.get("name", "azure_billing_plugin"),
            "type": "azure_billing",
            "description": "Azure Billing plugin for cost, budgets, alerts, forecasting, CSV export, and dynamic inline charting.",
            "methods": self._collect_kernel_methods_for_metadata()
        }

    @kernel_function(description="Generate plotting hints for Cost Management data so callers can intentionally choose chart parameters.")
    @plugin_function_logger("AzureBillingPlugin")
    def suggest_plot_config(self, data, columns: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        if columns is not None and not isinstance(columns, list):
            return {"status": "error", "error": "columns must be a list of column metadata entries"}
        try:
            rows = self._coerce_rows_for_plot(data)
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}
        except Exception as exc:  # pragma: no cover - defensive path
            logging.exception("Unexpected error while preparing data for plot hints")
            return {"status": "error", "error": f"Failed to parse data for plot hints: {exc}"}

        if not rows:
            return {"status": "error", "error": "No data provided for plotting"}

        hints = self._build_plot_hints(rows, columns)
        return hints

    @kernel_function(description="Build a dynamic SimpleChat chart from provided data. Supports pie, column_stacked, column_grouped, line, and area.",)
    @plugin_function_logger("AzureBillingPlugin")
    def plot_chart(self,
                    conversation_id: str,
                    data,
                    x_keys: Optional[List[str]] = None,
                    y_keys: Optional[List[str]] = None,
                    graph_type: str = "line",
                    title: str = "",
                    xlabel: str = "",
                    ylabel: str = "",
                    filename: str = "chart.png",
                    figsize: Optional[List[float]] = [7.0, 5.0]) -> Dict[str, Any]:
        return self.plot_custom_chart(
                    conversation_id=conversation_id,
                    data=data,
                    x_keys=x_keys,
                    y_keys=y_keys,
                    graph_type=graph_type,
                    title=title,
                    xlabel=xlabel,
                    ylabel=ylabel,
                    filename=filename,
                    figsize=figsize
        )

    def _coerce_number_for_chart(self, value: Any, field_name: str) -> float:
        """Normalize chart numeric values while keeping validation errors explicit."""

        if value in (None, ""):
            return 0.0
        if isinstance(value, bool):
            raise ValueError(f"{field_name} must be numeric.")
        if isinstance(value, (int, float)):
            return float(value)

        try:
            return float(str(value).strip().replace(",", ""))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be numeric.") from exc

    def _aggregate_rows_for_series_chart(
        self,
        rows: List[Dict[str, Any]],
        x_key: str,
        series_key: str,
        value_key: str,
    ) -> List[Dict[str, Any]]:
        """Sum duplicate x/series pairs before sending data to the inline chart renderer."""

        ordered_keys: List[tuple[str, str]] = []
        totals: Dict[tuple[str, str], float] = {}
        for row in rows:
            label = str(row.get(x_key, "") or "Unknown")
            series = str(row.get(series_key, "") or "Unknown")
            aggregate_key = (label, series)
            if aggregate_key not in totals:
                ordered_keys.append(aggregate_key)
                totals[aggregate_key] = 0.0
            totals[aggregate_key] += self._coerce_number_for_chart(row.get(value_key), value_key)

        return [
            {
                x_key: label,
                series_key: series,
                value_key: totals[(label, series)],
            }
            for label, series in ordered_keys
        ]

    def _build_inline_chart_data(
        self,
        rows: List[Dict[str, Any]],
        graph_type: str,
        x_key: str,
        y_keys_list: List[str],
        stack_col: Optional[str],
    ) -> Dict[str, Any]:
        """Build the row payload expected by the shared SimpleChat chart action."""

        if graph_type == "pie":
            return {
                "rows": rows,
                "labelField": x_key,
                "valueField": y_keys_list[0],
            }

        if stack_col and y_keys_list:
            value_key = y_keys_list[0]
            return {
                "rows": self._aggregate_rows_for_series_chart(rows, x_key, stack_col, value_key),
                "xField": x_key,
                "seriesField": stack_col,
                "valueField": value_key,
            }

        return {
            "rows": rows,
            "xField": x_key,
            "yFields": y_keys_list,
        }

    def _build_inline_chart_options(
        self,
        graph_type: str,
        x_key: str,
        y_keys_list: List[str],
        xlabel: str,
        ylabel: str,
    ) -> Dict[str, Any]:
        """Return display options understood by the SimpleChat inline chart renderer."""

        return {
            "beginAtZero": True,
            "legendPosition": "top",
            "showDataTable": True,
            "showLegend": True,
            "smooth": graph_type in {"line", "area"},
            "stacked": graph_type == "column_stacked",
            "xAxisLabel": xlabel or x_key,
            "yAxisLabel": ylabel or (y_keys_list[0] if len(y_keys_list) == 1 else "Values"),
        }

    def _build_inline_chart_result(
        self,
        graph_type: str,
        rows: List[Dict[str, Any]],
        x_key: str,
        y_keys_list: List[str],
        stack_col: Optional[str],
        title: str,
        xlabel: str,
        ylabel: str,
    ) -> Dict[str, Any]:
        """Use the shared chart plugin to produce validated simplechart markdown."""

        chart_kind = GRAPH_TYPE_TO_INLINE_CHART_KIND[graph_type]
        chart_data = self._build_inline_chart_data(rows, graph_type, x_key, y_keys_list, stack_col)
        chart_options = self._build_inline_chart_options(graph_type, x_key, y_keys_list, xlabel, ylabel)
        chart_plugin = ChartPlugin({"chart_capabilities": {chart_kind: True}})
        chart_result = chart_plugin.create_chart(
            chart_type=chart_kind,
            chart_data_json=json.dumps(chart_data, separators=(",", ":")),
            title=title or "Azure cost chart",
            x_axis_label=chart_options["xAxisLabel"],
            y_axis_label=chart_options["yAxisLabel"],
            options_json=json.dumps(chart_options, separators=(",", ":")),
        )

        if not chart_result.get("success"):
            return {
                "status": "error",
                "error": chart_result.get("error") or "Failed to build inline chart payload.",
                "error_type": chart_result.get("error_type", "validation"),
            }

        return chart_result

    def plot_custom_chart(self,
                          conversation_id: str,
                          data,
                          x_keys: Optional[List[str]] = None,
                          y_keys: Optional[List[str]] = None,
                          graph_type: str = "line",
                          title: str = "",
                          xlabel: str = "",
                          ylabel: str = "",
                          filename: str = "chart.png",
                          figsize: Optional[List[float]] = [7.0, 5.0]) -> Dict[str, Any]:
        """
        General plotting function.

        - data: list of dict rows (e.g., [{'date': '2025-10-01', 'cost': 12.3, 'type': 'A'}, ...])
        - x_keys: list of keys to use for x axis (required for non-pie charts); first key is primary x-axis, additional keys are used for stacking/grouping
        - y_keys: list of keys to plot on y axis (if None and graph_type is not pie, autodetect numeric columns)
        - graph_type: one of ['pie', 'column_stacked', 'column_grouped', 'line', 'area']
        - returns a structured dict with chart_payload and chart_markdown for SimpleChat inline rendering
        """
        graph_type = graph_type.lower() if isinstance(graph_type, str) else str(graph_type)
        if graph_type not in SUPPORTED_GRAPH_TYPES:
            raise ValueError(f"Unsupported graph_type '{graph_type}'. Supported: {SUPPORTED_GRAPH_TYPES}")
        try:
            rows = self._coerce_rows_for_plot(data)
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}
        except Exception as exc:
            logging.exception("Failed to parse input data for plotting")
            return {"status": "error", "error": f"Failed to parse data for plotting: {str(exc)}"}

        if not rows:
            return {"status": "error", "error": "No data provided for plotting"}

        hints = self._build_plot_hints(rows, None)
        recommended_defaults = hints.get("recommended", {}).get("default", {})
        recommended_pie = hints.get("recommended", {}).get("pie", {})

        def ensure_list(value) -> List[Any]:
            if value is None:
                return []
            if isinstance(value, list):
                return list(value)
            if isinstance(value, tuple):
                return list(value)
            if isinstance(value, str):
                return [value]
            if hasattr(value, '__iter__'):
                return list(value)
            return [value]

        x_keys_list = ensure_list(x_keys)
        y_keys_list = ensure_list(y_keys)

        if graph_type == "pie":
            if not y_keys_list:
                y_keys_list = ensure_list(recommended_pie.get("y_keys") or recommended_defaults.get("y_keys"))
            if len(y_keys_list) > 1:
                y_keys_list = y_keys_list[:1]
            if not y_keys_list:
                raise ValueError("Pie chart requires a numeric column for values")

            if not x_keys_list:
                x_keys_list = ensure_list(recommended_pie.get("x_keys") or recommended_defaults.get("x_keys"))
            if len(x_keys_list) > 1:
                x_keys_list = x_keys_list[:1]
            if not x_keys_list:
                sample_row = rows[0]
                for candidate in sample_row.keys():
                    if candidate in hints.get("label_candidates", []):
                        x_keys_list = [candidate]
                        break
            if not x_keys_list:
                raise ValueError("Pie chart requires a label column (x_keys)")

            x_key = x_keys_list[0]
            stack_col = None
        else:
            if not y_keys_list:
                y_keys_list = ensure_list(recommended_defaults.get("y_keys"))
            if not y_keys_list:
                sample_row = rows[0]
                y_keys_list = [k for k, v in sample_row.items() if isinstance(v, (int, float))]
            if not y_keys_list:
                raise ValueError("Could not autodetect numeric columns for y axis. Provide y_keys explicitly.")

            if not x_keys_list:
                x_keys_list = ensure_list(recommended_defaults.get("x_keys"))
            if not x_keys_list:
                sample_row = rows[0]
                for key, value in sample_row.items():
                    if not isinstance(value, (int, float)):
                        x_keys_list = [key]
                        break
            if not x_keys_list:
                raise ValueError("x_keys is required for this chart type")
            if len(x_keys_list) > 2:
                x_keys_list = x_keys_list[:2]

            x_key = x_keys_list[0]
            stack_col = x_keys_list[1] if len(x_keys_list) > 1 else None

        try:
            chart_result = self._build_inline_chart_result(
                graph_type=graph_type,
                rows=rows,
                x_key=x_key,
                y_keys_list=y_keys_list,
                stack_col=stack_col,
                title=title,
                xlabel=xlabel,
                ylabel=ylabel,
            )
            if chart_result.get("status") == "error":
                return chart_result

            return {
                "status": "ok",
                "type": "inline_chart",
                "chart_type": chart_result.get("chart_type"),
                "chart_payload": chart_result.get("chart_payload"),
                "chart_markdown": chart_result.get("chart_markdown"),
                "summary": chart_result.get("summary", ""),
                "metadata": {
                    "graph_type": graph_type,
                    "chart_type": chart_result.get("chart_type"),
                    "conversation_id": conversation_id,
                    "x_keys": x_keys_list,
                    "y_keys": y_keys_list,
                    "stack_key": stack_col,
                    "recommendations": hints.get("recommended", {}),
                    "renderer": "simplechart",
                }
            }
        except Exception as ex:
            logging.exception("Error while generating inline chart")
            return {"status": "error", "error": f"Error while generating inline chart: {str(ex)}"}


    @plugin_function_logger("AzureBillingPlugin")
    @kernel_function(description="List all subscriptions and resource groups accessible to the user/service principal.")
    def list_subscriptions_and_resourcegroups(self) -> str:
        url = f"{self.endpoint}/subscriptions?api-version=2020-01-01"
        subs = self._get(url).get('value', [])
        if isinstance(subs, dict) and ("error" in subs or "consent_url" in subs):
            return subs
        result = []
        for sub in subs:
            sub_id = sub.get('subscriptionId')
            sub_name = sub.get('displayName')
            rg_url = f"{self.endpoint}/subscriptions/{sub_id}/resourcegroups?api-version=2021-04-01"
            rgs = self._get(rg_url).get('value', [])
            result.append({
                "subscriptionId": sub_id,
                "subscriptionName": sub_name,
                "resourceGroups": [rg.get('name') for rg in rgs]
            })
        return self._csv_from_table(result)

    @plugin_function_logger("AzureBillingPlugin")
    @kernel_function(description="List all subscriptions accessible to the user/service principal.")
    def list_subscriptions(self) -> str:
        url = f"{self.endpoint}/subscriptions?api-version=2020-01-01"
        data = self._get(url)
        if isinstance(data, dict) and ("error" in data or "consent_url" in data):
            return data
        subs = data.get('value', [])
        return self._csv_from_table(subs)

    @plugin_function_logger("AzureBillingPlugin")
    @kernel_function(description="List all resource groups in a subscription.")
    def list_resource_groups(self, subscription_id: str) -> str:
        url = f"{self.endpoint}/subscriptions/{subscription_id}/resourcegroups?api-version=2020-01-01"
        data = self._get(url)
        if isinstance(data, dict) and ("error" in data or "consent_url" in data):
            return data
        rgs = data.get('value', [])
        return self._csv_from_table(rgs)

    @kernel_function(description="Get cost forecast with custom duration and granularity.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_forecast(self, resourceId: str, forecast_period_months: int = 12, granularity: str = "Monthly", lookback_months: Optional[int] = None) -> str:
        """
        #Get cost forecast for a given period and granularity.
        #scope: /subscriptions/{id} or /subscriptions/{id}/resourceGroups/{rg}
        #forecast_period_months: Number of months to forecast (default 12)
        #granularity: "Daily", "Monthly", "Weekly"
        #lookback_months: If provided, use last N months as historical data for forecasting
        """
        url = f"{self.endpoint.rstrip('/')}/{resourceId.lstrip('/').rstrip('/')}/providers/Microsoft.CostManagement/query?api-version={self.api_version}"
        timeframe = "Custom"
        # Calculate start/end dates for forecast
        today = datetime.datetime.utcnow().date()
        start_date = today
        end_date = today + datetime.timedelta(days=forecast_period_months * 30)
        # If lookback_months is set, use that for historical data
        if lookback_months:
            hist_start = today - datetime.timedelta(days=lookback_months * 30)
            hist_end = today
        else:
            hist_start = None
            hist_end = None
        query = {
            "type": "Forecast",
            "timeframe": timeframe,
            "timePeriod": {
                "from": start_date.isoformat(),
                "to": end_date.isoformat()
            },
            "dataset": {"granularity": granularity}
        }
        # Optionally add historical data window
        if hist_start and hist_end:
            query["historicalTimePeriod"] = {
                "from": hist_start.isoformat(),
                "to": hist_end.isoformat()
            }
        data = self._post(url, query)
        if isinstance(data, dict) and ("error" in data or "consent_url" in data):
            return data
        rows = data.get('properties', {}).get('rows', [])
        columns = [c['name'] for c in data.get('properties', {}).get('columns', [])]
        result = [dict(zip(columns, row)) for row in rows]
        return self._csv_from_table(result)

    @kernel_function(description="Get budgets for a subscription or resource group.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_budgets(self, subscription_id: str, resource_group_name: Optional[str] = None) -> str:
        if resource_group_name:
            scope = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}"
        else:
            scope = f"/subscriptions/{subscription_id}"
        url = f"{self.endpoint.rstrip('/')}{scope}/providers/Microsoft.CostManagement/budgets?api-version={self.api_version}"
        data = self._get(url)
        if isinstance(data, dict) and ("error" in data or "consent_url" in data):
            return data
        budgets = data.get('value', [])
        return self._csv_from_table(budgets)

    @kernel_function(description="Get cost alerts.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_alerts(self, subscription_id: str, resource_group_name: Optional[str] = None) -> str:
        if resource_group_name:
            scope = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}"
        else:
            scope = f"/subscriptions/{subscription_id}"
        url = f"{self.endpoint.rstrip('/')}{scope}/providers/Microsoft.CostManagement/alerts?api-version={self.api_version}"
        data = self._get(url)
        if isinstance(data, dict) and ("error" in data or "consent_url" in data):
            return data
        alerts = data.get('value', [])
        return self._csv_from_table(alerts)

    @kernel_function(description="Get specific cost alert by ID.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_specific_alert(self, subscription_id: str, alertId: str , resource_group_name: Optional[str] = None) -> str:
        if resource_group_name:
            scope = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}"
        else:
            scope = f"/subscriptions/{subscription_id}"
        url = f"{self.endpoint.rstrip('/')}{scope}/providers/Microsoft.CostManagement/alerts/{alertId}?api-version={self.api_version}"
        data = self._get(url)
        if isinstance(data, dict) and ("error" in data or "consent_url" in data):
            return data
        # Flatten nested properties for CSV friendliness
        if isinstance(data, dict):
            flat = self._flatten_dict(data)
            # Convert lists to JSON strings for CSV
            for k, v in list(flat.items()):
                if isinstance(v, (list, dict)):
                    try:
                        flat[k] = json.dumps(v)
                    except Exception:
                        flat[k] = str(v)
            return self._csv_from_table([flat])
        else:
            # Fallback: return raw JSON string in a single column
            return self._csv_from_table([{"raw": json.dumps(data)}])

    @kernel_function(description="Run an Azure Cost Management query and return rows, column metadata, and plotting hints for manual chart selection. Requires explicit start/end datetimes and always uses a Custom timeframe.")
    @plugin_function_logger("AzureBillingPlugin")
    def run_data_query(self,
        conversation_id: str,
        subscription_id: str,
        aggregations: List[Dict[str, Any]],
        groupings: List[Dict[str, Any]],
        start_datetime: Union[str, datetime.datetime, datetime.date],
        end_datetime: Union[str, datetime.datetime, datetime.date],
        query_type: str = "Usage",
        granularity: str = "Daily",
        resource_group_name: Optional[str] = None,
        query_filter: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute an Azure Cost Management query and return structured results.

        Callers must supply start_datetime and end_datetime (ISO-8601 strings or
        datetime objects). The outgoing payload always uses a Custom timeframe with a
        fully populated timePeriod object.

        Returns a dict containing:
            - rows: list of result dictionaries
            - columns: metadata about returned columns
            - csv: CSV-formatted string of the results
            - plot_hints: heuristic suggestions for plotting the data
            - query: the query payload that was submitted
            - scope/api_version: request context details
        """
        if resource_group_name:
            scope = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}"
        else:
            scope = f"/subscriptions/{subscription_id}"
        url = f"{self.endpoint.rstrip('/')}{scope}/providers/Microsoft.CostManagement/query?api-version={self.api_version}"
        if not self._normalize_enum(query_type, QUERY_TYPE):
            raise ValueError(f"Invalid query_type: {query_type}. Must be one of {QUERY_TYPE}.")
        if not self._normalize_enum(granularity, GRANULARITY_TYPE):
            raise ValueError(f"Invalid granularity: {granularity}. Must be one of {GRANULARITY_TYPE}.")

        if start_datetime is None or end_datetime is None:
            return {
                "status": "error",
                "error": "start_datetime and end_datetime are required for run_data_query.",
                "expected_format": "ISO-8601 timestamp with time component (e.g., 2025-11-01T00:00:00Z).",
                "example": {
                    "start_datetime": "2025-11-01T00:00:00Z",
                    "end_datetime": "2025-11-30T23:59:59Z"
                }
            }
        try:
            time_period = self._build_custom_time_period(start_datetime, end_datetime)
        except ValueError as exc:
            return {
                "status": "error",
                "error": str(exc),
                "expected_format": "ISO-8601 timestamp with time component (e.g., 2025-11-01T00:00:00Z).",
                "example": {
                    "start_datetime": "2025-11-01T00:00:00Z",
                    "end_datetime": "2025-11-30T23:59:59Z"
                }
            }

        query = {
            "type": query_type,
            "timeframe": "Custom",
            "dataset": {
                "granularity": granularity
            },
            "timePeriod": time_period,
        }
        if not aggregations:
            return {
                "status": "error",
                "error": "Aggregations list cannot be empty; supply at least one aggregation entry.",
                "example": [
                    {"name": "totalCost", "function": "Sum", "column": "PreTaxCost"}
                ]
            }
        if not groupings:
            return {
                "status": "error",
                "error": "Groupings list cannot be empty; include at least one Dimension/Tag grouping.",
                "example": [
                    {"type": "Dimension", "name": "ResourceType"}
                ]
            }
        # Validate and normalize aggregations (if provided)
        if aggregations:
            if not isinstance(aggregations, list):
                return {"status": "error", "error": "aggregations must be a list of aggregation definitions", "example": [{"name": "totalCost", "function": "Sum", "column": "PreTaxCost"}]}
            if len(aggregations) > 2:
                logging.warning("More than 2 aggregations provided; only the first 2 will be used")
            agg_map: Dict[str, Any] = {}
            for agg in aggregations[:2]:
                if not isinstance(agg, dict):
                    return {"status": "error", "error": "Each aggregation must be a dict", "example": [{"name": "totalCost", "function": "Sum", "column": "PreTaxCost"}]}

                # Determine aggregation alias (outer key) and underlying column + function
                # Support these shapes:
                # 1) flat: {"name": "totalCost", "function": "Sum", "column": "PreTaxCost"}
                # 2) nested: {"name": "totalCost", "aggregation": {"name": "PreTaxCost", "function": "Sum"}}
                # We will produce agg_map[alias] = {"name": <columnName>, "function": <fn>}

                alias = agg.get('name')
                column_name = None
                function = None

                if 'aggregation' in agg and isinstance(agg['aggregation'], dict):
                    sub = agg['aggregation']
                    # sub.get('name') is the column name in nested form
                    column_name = sub.get('name') or sub.get('column') or agg.get('column')
                    function = sub.get('function') or agg.get('function')
                    # allow sub to specify other properties but we'll only keep name and function for compatibility
                else:
                    # flat form
                    column_name = agg.get('column') or agg.get('name_of_column') or agg.get('columnName')
                    function = agg.get('function')

                if not alias:
                    return {"status": "error", "error": "Aggregation entry missing aggregation alias in 'name' field", "example": [{"name": "totalCost", "aggregation": {"name": "PreTaxCost", "function": "Sum"}}]}
                if not function:
                    return {"status": "error", "error": f"Aggregation '{alias}' missing 'function'", "example": [{"name": alias, "aggregation": {"name": "PreTaxCost", "function": "Sum"}}]}
                if not self._normalize_enum(function, AGGREGATION_FUNCTIONS):
                    return {"status": "error", "error": f"Aggregation function '{function}' is invalid. Must be one of: {AGGREGATION_FUNCTIONS}", "example": [{"name": alias, "aggregation": {"name": "PreTaxCost", "function": "Sum"}}]}

                details: Dict[str, Any] = {}
                # per your requested shape, the inner object should include the column as 'name'
                if column_name:
                    details['name'] = column_name
                details['function'] = function

                agg_map[alias] = details
            query["dataset"]["aggregation"] = agg_map

        # Validate and normalize groupings (if provided)
        if groupings:
            if not isinstance(groupings, list):
                return {"status": "error", "error": "groupings must be a list of grouping definitions", "example": [{"type": "Dimension", "name": "ResourceLocation"}]}
            if len(groupings) > 2:
                logging.warning("More than 2 groupings provided; only the first 2 will be used")
            normalized_groupings: List[Dict[str, str]] = []
            for grp in groupings[:2]:
                if not isinstance(grp, dict):
                    return {"status": "error", "error": "Each grouping must be a dict with 'type' and 'name'", "example": [{"type": "Dimension", "name": "ResourceType"}]}
                gtype = grp.get('type')
                gname = grp.get('name')
                if not gtype or not self._normalize_enum(gtype, GROUPING_TYPE):
                    return {"status": "error", "error": f"Grouping type '{gtype}' is invalid. Must be one of: {GROUPING_TYPE}", "example": [{"type": "Dimension", "name": "ResourceType"}]}
                if not gname or not self._normalize_enum(gname, self.grouping_dimensions):
                    return {"status": "error", "error": f"Grouping name '{gname}' is invalid. Must be one of: {self.grouping_dimensions}", "example": [{"type": "Dimension", "name": "ResourceType"}]}
                normalized_groupings.append({'type': gtype, 'name': gname})
            query["dataset"]["grouping"] = normalized_groupings
        if query_filter:
            query["dataset"]["filter"] = query_filter
        # No additional validation required; _build_custom_time_period enforces shape
        logging.debug("Running Cost Management query with payload: %s", json.dumps(query, indent=2))
        data = self._post(url, query)
        if isinstance(data, dict) and ("error" in data or "consent_url" in data):
            return data
        rows = data.get('properties', {}).get('rows', [])
        column_objects = data.get('properties', {}).get('columns', [])
        column_names = [c.get('name') for c in column_objects]
        result_rows = [dict(zip(column_names, row)) for row in rows]
        csv_output = self._csv_from_table(result_rows)

        columns_meta: List[Dict[str, Any]] = []
        for col in column_objects:
            if not isinstance(col, dict):
                continue
            columns_meta.append({
                "name": col.get('name') or col.get('displayName'),
                "type": col.get('type') or col.get('dataType'),
                "dataType": col.get('dataType'),
                "unit": col.get('unit')
            })

        plot_hints = self._build_plot_hints(result_rows, column_objects)

        return {
            "status": 200,
            "conversation_id": conversation_id,
            "scope": scope,
            "api_version": self.api_version,
            "query": query,
            "row_count": len(result_rows),
            "columns": columns_meta,
            "csv": csv_output,
            "plot_hints": plot_hints,
        }

    @kernel_function(description="Return available configuration options for Azure Billing report queries.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_query_configuration_options(self, subscription_id: str, resource_group_name: Optional[str] = None) -> Dict[str, Any]:
        get_dimension_results = self.get_grouping_dimensions(subscription_id, resource_group_name)
        if isinstance(get_dimension_results, dict) and ("error" in get_dimension_results or "consent_url" in get_dimension_results):
            return get_dimension_results
        if isinstance(get_dimension_results, list):
            # Store a per-instance copy to prevent cross-request state bleed.
            self.grouping_dimensions = list(get_dimension_results) or list(DEFAULT_GROUPING_DIMENSIONS)
        return {
            "TIME_FRAME_TYPE": TIME_FRAME_TYPE,
            "QUERY_TYPE": QUERY_TYPE,
            "GRANULARITY_TYPE": GRANULARITY_TYPE,
            "GROUPING_TYPE": GROUPING_TYPE,
            "GROUPING_DIMENSIONS": self.grouping_dimensions,
            "AGGREGATION_FUNCTIONS": AGGREGATION_FUNCTIONS,
            "AGGREGATION_COLUMNS": AGGREGATION_COLUMNS,
            "NOTE": "Not all combinations are available for all queries."
        }

    @kernel_function(description="Get available cost dimensions for Azure Billing.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_grouping_dimensions(self, subscription_id: str, resource_group_name: Optional[str] = None) -> List[str]:
        if resource_group_name:
            scope = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}"
        else:
            scope = f"/subscriptions/{subscription_id}"
        # Use the Cost Management query endpoint to retrieve available dimensions/categories
        # Note: some Cost Management responses return a 'value' array where each item has a
        # 'properties' object containing a 'category' property. We handle that shape and
        # fall back to other common fields.
        url = f"{self.endpoint.rstrip('/')}{scope}/providers/Microsoft.CostManagement/dimensions?api-version={self.api_version}&$expand=properties/data"
        data = self._get(url)
        if isinstance(data, dict) and ("error" in data or "consent_url" in data):
            return data

        values = data.get('value', []) if isinstance(data, dict) else []
        dims = []
        for item in values:
            if not isinstance(item, dict):
                continue
            # Preferred location: item['properties']['category']
            props = item.get('properties') if isinstance(item.get('properties'), dict) else {}
            cat = props.get('category') or props.get('Category')
            if not cat:
                # fallback to name/displayName
                cat = item.get('name') or props.get('name') or props.get('displayName')
            if cat:
                dims.append(cat)

        # dedupe while preserving order
        seen = set()
        deduped = []
        for d in dims:
            if d not in seen:
                seen.add(d)
                deduped.append(d)
        return deduped

    @kernel_function(description="Run a sample or provided Cost Management query and return the columns metadata (name + type). Useful for discovering which columns can be used for aggregation and grouping.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_query_columns(self, subscription_id: str, resource_group_name: Optional[str] = None, query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Discover columns for a Cost Management query.

        - subscription_id: required
        - resource_group_name: optional
        - query: optional Cost Management query dict; if omitted a minimal Usage MonthToDate query is used

        Returns a list of {"name": <colName>, "type": <colType>}.
        """
        if resource_group_name:
            scope = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}"
        else:
            scope = f"/subscriptions/{subscription_id}"
        url = f"{self.endpoint.rstrip('/')}" + f"{scope}/providers/Microsoft.CostManagement/query?api-version={self.api_version}"

        if not query:
            query = {
                "type": "Usage",
                "timeframe": "MonthToDate",
                "dataset": {"granularity": "None"}
            }

        data = self._post(url, query)
        if isinstance(data, dict) and ("error" in data or "consent_url" in data):
            return data

        # Two possible shapes: properties.columns or value[].properties.columns
        cols = []
        props = data.get('properties') if isinstance(data, dict) else None
        if props and isinstance(props, dict) and props.get('columns'):
            cols = props.get('columns', [])
        else:
            # Inspect value[] items for properties.columns
            values = data.get('value', []) if isinstance(data, dict) else []
            for item in values:
                if not isinstance(item, dict):
                    continue
                p = item.get('properties') if isinstance(item.get('properties'), dict) else {}
                if p.get('columns'):
                    cols = p.get('columns')
                    break

        result = []
        for c in cols or []:
            if not isinstance(c, dict):
                continue
            name = c.get('name') or c.get('displayName')
            typ = c.get('type') or c.get('dataType') or c.get('data', {}).get('type') if isinstance(c.get('data'), dict) else c.get('type')
            result.append({"name": name, "type": typ})

        return result

    @kernel_function(description="Return only aggregatable (numeric) columns from a sample or provided query.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_aggregatable_columns(self, subscription_id: str, resource_group_name: Optional[str] = None, query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Returns columns suitable for aggregation (numeric types). Uses `get_query_columns` internally.
        """
        cols = self.get_query_columns(subscription_id, resource_group_name, query)
        if isinstance(cols, dict) and ("error" in cols or "consent_url" in cols):
            return cols
        numeric_types = {"Number", "Double", "Integer", "Decimal", "Long", "Float"}
        agg = [c for c in (cols or []) if (c.get('type') in numeric_types or (isinstance(c.get('type'), str) and c.get('type').lower() == 'number'))]
        return agg


    @kernel_function(description="Get the expected formatting, in JSON, for run_data_query parameters.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_run_data_query_format(self) -> Dict[str, Any]:
        """
        Returns an example JSON object describing the expected parameters for run_data_query.
        Includes required/optional fields, types, valid values, and reflects the latest method signature.
        """
        return {
            "conversation_id": "<string, required - reuse this when calling plot_chart for traceability>",
            "subscription_id": "<string, required>",
            "resource_group_name": "<string, optional>",
            "query_type": f"<string, optional, one of {QUERY_TYPE}>",
            "start_datetime": "<string, required - ISO-8601 timestamp with time (e.g., 2025-11-01T00:00:00Z)>",
            "end_datetime": "<string, required - ISO-8601 timestamp with time (e.g., 2025-11-30T23:59:59Z)>",
            "granularity": f"<string, optional, one of {GRANULARITY_TYPE}>",
            "aggregations": [
                {
                    "name": "totalCost",
                    "function": f"<string, required, one of {AGGREGATION_FUNCTIONS}>",
                    "column": f"<string, required, one of {AGGREGATION_COLUMNS}>"
                }
            ],
            "groupings": [
                {
                    "type": f"<string, required, one of {GROUPING_TYPE}>",
                    "name": f"<string, required, one of {self.grouping_dimensions}>"
                }
            ],
            "query_filter": "<object, optional – Cost Management filter definition>",
            "example_request": {
                "conversation_id": "abc123",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "query_type": "Usage",
                "start_datetime": "2025-04-01T00:00:00-04:00",
                "end_datetime": "2025-09-30T23:59:59-04:00",
                "granularity": "Daily",
                "aggregations": [
                    {"name": "totalCost", "function": "Sum", "column": "PreTaxCost"}
                ],
                "groupings": [
                    {"type": "Dimension", "name": "ResourceType"}
                ]
            },
            "example_response": {
                "status": "ok",
                "row_count": 3,
                "rows": [
                    {"ResourceType": "microsoft.compute/virtualmachines", "PreTaxCost": 12694.43},
                    {"ResourceType": "microsoft.compute/disks", "PreTaxCost": 4715.20},
                    {"ResourceType": "microsoft.keyvault/vaults", "PreTaxCost": 201.11}
                ],
                "columns": [
                    {"name": "ResourceType", "type": "String"},
                    {"name": "PreTaxCost", "type": "Number"}
                ],
                "plot_hints": {
                    "recommended": {
                        "default": {
                            "graph_type": "column_stacked",
                            "x_keys": ["ResourceType"],
                            "y_keys": ["PreTaxCost"]
                        },
                        "pie": {
                            "graph_type": "pie",
                            "x_keys": ["ResourceType"],
                            "y_keys": ["PreTaxCost"]
                        }
                    }
                }
            },
            "workflow": [
                "Call run_data_query to retrieve rows, columns, csv, and plot_hints.",
                "Always provide start_datetime and end_datetime using ISO-8601 strings (e.g., 2025-11-01T00:00:00Z).",
                "Always supply at least one aggregation entry; the plugin no longer infers defaults when none are provided.",
                "Include at least one grouping (Dimension + name) so the query can bucket the data.",
                "Inspect plot_hints['recommended'] for suggested x_keys, y_keys, and chart types.",
                "Pass rows (or the csv string) plus the chosen keys into plot_chart to return chart_markdown for inline rendering."
            ]
        }

    # Returns the expected input data format for plot_custom_chart
    @kernel_function(description="Get the expected input data format for plot_custom_chart dynamic inline charting as JSON.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_plot_chart_format(self) -> Dict[str, Any]:
        """
        Returns an example object describing the expected 'data' parameter for plot_custom_chart.
        The 'data' field should be a CSV string (with headers and rows), matching the output format of run_data_query.
        """
        return {
            "conversationId": "<string, required>",
            "data": "<list of dict rows OR CSV string – rows returned from run_data_query['rows']>",
            "x_keys": ["ResourceType"],
            "y_keys": ["PreTaxCost"],
            "graph_type": "pie",
            "title": "Cost share by resource type",
            "xlabel": "Resource Type",
            "ylabel": "Cost (USD)",
            "filename": "<string, optional and ignored - retained for backward compatibility>",
            "figsize": "<array, optional and ignored - retained for backward compatibility>",
            "output": {
                "type": "inline_chart",
                "chart_markdown": "```simplechart\\n{...}\\n```",
                "chart_payload": "<validated SimpleChat Chart.js payload>"
            },
            "notes": [
                "Feed the list returned in run_data_query['rows'] directly, or supply the CSV from run_data_query['csv'].",
                "Pick x_keys/y_keys from run_data_query['plot_hints']['recommended'] to ensure compatible chart input.",
                "Pie charts require exactly one numeric y_key; stacked/grouped charts accept multiple.",
                "plot_chart returns chart_markdown for SimpleChat inline rendering; filename and figsize are retained only for backward-compatible callers and are ignored."
            ]
        }
