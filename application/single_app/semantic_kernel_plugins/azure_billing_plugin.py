# azure_billing_plugin.py
"""
Azure Billing Plugin for Semantic Kernel
- Supports user (Entra ID) and service principal authentication
- Uses Azure Cost Management REST API for billing, budgets, alerts, forecasting
- Renders graphs server-side as PNG (base64 for web, downloadable)
- Returns tabular data as CSV for minimal token usage
- Requires user_impersonation for user auth on 40a69793-8fe6-4db1-9591-dbc5c57b17d8 (Azure Service Management)
"""

import io
import base64
import requests
import csv
import inspect
import matplotlib.pyplot as plt
import logging
import time
import random
import re
import numpy as np
import datetime
from typing import Dict, Any, List, Optional, Union
import json
from collections import defaultdict
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel.functions import kernel_function
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger
from functions_authentication import get_valid_access_token, get_valid_access_token_for_plugins
from azure.identity import DefaultAzureCredential
from functions_debug import debug_print
from azure.core.credentials import AccessToken, TokenCredential
from semantic_kernel.contents import ImageContent
from config import cosmos_messages_container, cosmos_conversations_container


RESOURCE_ID_REGEX = r"^/subscriptions/(?P<subscriptionId>[a-fA-F0-9-]+)/?(?:resourceGroups/(?P<resourceGroupName>[^/]+))?$"
TIME_FRAME_TYPE = ["MonthToDate", "BillingMonthToDate", "WeekToDate", "Custom"] # "TheLastMonth, TheLastBillingMonth" are not supported in MAG
QUERY_TYPE = ["Usage", "ActualCost", "AmortizedCost"]
GRANULARITY_TYPE = ["None", "Daily", "Monthly", "Accumulated"]
GROUPING_TYPE = ["Dimension", "TagKey"]
AGGREGATION_FUNCTIONS = ["Sum"] #, "Average", "Min", "Max", "Count", "None"]
AGGREGATION_COLUMNS= ["Cost", "CostUSD", "PreTaxCost", "PreTaxCostUSD"]
GROUPING_DIMENSIONS = ["None", "BillingPeriod", "ChargeType", "Frequency", "MeterCategory", "MeterId", "MeterSubCategory", "Product", "ResourceGroupName", "ResourceLocation", "ResourceType", "ServiceFamily", "ServiceName", "SubscriptionId", "SubscriptionName", "Tag"]
SUPPORTED_GRAPH_TYPES = ["pie", "column_stacked", "column_grouped", "line", "area"]

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
                # Log the response text for diagnostics and raise a clear error
                resp_text = getattr(e.response, 'text', '') if hasattr(e, 'response') else ''
                logging.error("Failed to obtain service principal token. URL=%s, Error=%s, Response=%s", token_url, e, resp_text)
                raise RuntimeError(f"Failed to obtain service principal token: {e}. Response: {resp_text}")
            except requests.exceptions.RequestException as e:
                logging.error("Error requesting service principal token: %s", e)
                raise
            try:
                token = resp.json().get('access_token')
            except ValueError:
                logging.error("Invalid JSON returned from token endpoint: %s", resp.text)
                raise RuntimeError(f"Invalid JSON returned from token endpoint: {resp.text}")
            if not token:
                logging.error("Token endpoint did not return access_token. Response: %s", resp.text)
                raise RuntimeError(f"Token endpoint did not return access_token. Response: {resp.text}")
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

    def _fig_to_base64_dict(self, fig, filename: str = "chart.png") -> Dict[str, str]:
        """Convert a matplotlib Figure to a structured base64 dict.

        Returns: {"mime": "image/png", "filename": filename, "base64": <b64str>, "image_url": "data:image/png;base64,<b64>"}
        """
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight')
        fig.clf()
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode('utf-8')
        return {
            "mime": "image/png",
            "filename": filename,
            "base64": img_b64,
            "image_url": f"data:image/png;base64,{img_b64}"
        }

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

        default_graph_type = "column_grouped"
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

    def _iso_utc(dt: datetime.datetime) -> str:
        return dt.astimezone(datetime.timezone.utc).isoformat()

    def _add_months(dt: datetime.datetime, months: int) -> datetime.datetime:
        # Add (or subtract) months without external deps.
        year = dt.year + (dt.month - 1 + months) // 12
        month = (dt.month - 1 + months) % 12 + 1
        day = min(dt.day, [31,
                        29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
                        31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month-1])
        return dt.replace(year=year, month=month, day=day)

    def _first_day_of_month(dt: datetime.datetime) -> datetime.datetime:
        return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def _last_day_of_month(dt: datetime.datetime) -> datetime.datetime:
        # move to first of next month then subtract one second
        next_month = self._add_months(self._first_day_of_month(dt), 1)
        return next_month - datetime.timedelta(seconds=1)

    def _last_n_months_timeperiod(n: int):
        now = datetime.datetime.now(datetime.timezone.utc)
        start = self._add_months(now, -n)
        return {"from": self._iso_utc(start), "to": self._iso_utc(now)}

    def _previous_n_months_timeperiod(n: int):
        today = datetime.datetime.now(datetime.timezone.utc)
        first_this_month = self._first_day_of_month(today)
        last_of_prev = first_this_month - datetime.timedelta(seconds=1)
        first_of_earliest = self._first_day_of_month(self._add_months(first_this_month, -n))
        # ensure full days for readability
        return {
            "from": self._iso_utc(first_of_earliest),
            "to": self._iso_utc(last_of_prev.replace(hour=23, minute=59, second=59, microsecond=0))
        }

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
            "description": "Azure Billing plugin for cost, budgets, alerts, forecasting, CSV export, and PNG graphing.",
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

    @kernel_function(description="Plot a chart/graph from provided data. Supports pie, column_stacked, column_grouped, line, and area.",)
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
        - returns structured dict with mime, filename, base64, image_url and metadata
        """
        try:
            #print(f"[AzureBillingPlugin] plot_custom_chart called with conversation_id={conversation_id}, graph_type={graph_type},\n x_key={x_key},\n y_keys={y_keys},\n title={title},\n xlabel={xlabel},\n ylabel={ylabel},\n figsize={figsize},\n data:{data}")
            graph_type = graph_type.lower() if isinstance(graph_type, str) else str(graph_type)
            # Validate figsize: must be a list/tuple of two numbers if provided
            if figsize is None:
                figsize = [7.0, 5.0]
            elif isinstance(figsize, (list, tuple)):
                if len(figsize) != 2:
                    return {"status": "error", "error": "figsize must be a list of two numbers: [width, height]"}
                try:
                    figsize = [float(figsize[0]), float(figsize[1])]
                except Exception:
                    return {"status": "error", "error": "figsize elements must be numeric"}
            else:
                return {"status": "error", "error": "figsize must be a list of two numbers or null"}

        except Exception as ex:
            logging.exception("Unexpected error in plot_custom_chart parameter validation")
            return {"status": "error", "error": str(ex)}
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
            x_vals = None
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
            x_vals = [r.get(x_key) for r in rows]

        fig = None
        try:
            num_legend_items = 0
            if graph_type == "pie":
                num_legend_items = len(rows)
            elif graph_type == "column_stacked":
                if stack_col:
                    num_legend_items = len({r.get(stack_col) for r in rows if r.get(stack_col) is not None})
                else:
                    num_legend_items = len(y_keys_list)
            else:
                num_legend_items = len(y_keys_list)

            scaled_figsize = list(figsize)
            if num_legend_items > 6:
                extra_width = min(num_legend_items * 0.12, 5.0)
                scaled_figsize[0] = figsize[0] + extra_width
            elif num_legend_items > 3:
                scaled_figsize[1] = figsize[1] + 0.8

            fig, ax = plt.subplots(figsize=tuple(scaled_figsize))

            if graph_type == "pie":
                pie_x_key = x_keys_list[0]
                pie_y_key = y_keys_list[0]
                labels = [r.get(pie_x_key) for r in rows]
                labels_display = ["Unknown" if label in (None, "") else str(label) for label in labels]
                values = [float(r.get(pie_y_key) or 0) for r in rows]
                wedges, _, _ = ax.pie(values, autopct="%1.1f%%", startangle=90)
                ax.set_title(title or "Cost distribution")
                if len(labels_display) <= 6:
                    ax.legend(wedges, labels_display, loc="center left", bbox_to_anchor=(1, 0.5))
                else:
                    ax.legend(wedges, labels_display, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=min(4, len(labels_display)))

            elif graph_type in ("line", "area"):
                for yk in y_keys_list:
                    y_vals = [float(r.get(yk) or 0) for r in rows]
                    if graph_type == "line":
                        ax.plot(x_vals, y_vals, marker='o', label=yk)
                    else:
                        ax.fill_between(range(len(x_vals)), y_vals, alpha=0.5, label=yk)
                if len(y_keys_list) > 1:
                    ax.legend()
                ax.set_title(title or "Cost trend")
                ax.set_xlabel(xlabel or x_key)
                ax.set_ylabel(ylabel or (y_keys_list[0] if y_keys_list else "Value"))
                ax.grid(True, axis='y', alpha=0.3)

            elif graph_type == "column_grouped":
                n_groups = len(rows)
                n_bars = len(y_keys_list)
                index = np.arange(n_groups)
                bar_width = 0.8 / max(1, n_bars)
                for i, yk in enumerate(y_keys_list):
                    y_vals = [float(r.get(yk) or 0) for r in rows]
                    ax.bar(index + i * bar_width, y_vals, bar_width, label=yk)
                ax.set_xticks(index + bar_width * (n_bars - 1) / 2)
                ax.set_xticklabels([str(x) for x in x_vals], rotation=45, ha='right')
                ax.set_title(title or "Cost comparison")
                ax.set_xlabel(xlabel or x_key)
                ax.set_ylabel(ylabel or ("Values" if len(y_keys_list) > 1 else y_keys_list[0]))
                if len(y_keys_list) > 1:
                    ax.legend()

            elif graph_type == "column_stacked":
                x_vals_unique: List[Any] = []
                seen_x = set()
                for r in rows:
                    xval = r.get(x_key)
                    if xval not in seen_x:
                        seen_x.add(xval)
                        x_vals_unique.append(xval)

                y_keys_plot: List[Any]
                pivot = defaultdict(lambda: defaultdict(float))
                if stack_col:
                    for r in rows:
                        xval = r.get(x_key)
                        sval = r.get(stack_col)
                        yval = float(r.get(y_keys_list[0]) or 0)
                        pivot[xval][sval] += yval
                    y_keys_plot = sorted({key for row in pivot.values() for key in row.keys()})
                else:
                    for r in rows:
                        xval = r.get(x_key)
                        for yk in y_keys_list:
                            pivot[xval][yk] += float(r.get(yk) or 0)
                    y_keys_plot = y_keys_list

                data_matrix = [[pivot[x_val].get(yk, 0.0) for x_val in x_vals_unique] for yk in y_keys_plot]
                index = np.arange(len(x_vals_unique))
                bottoms = np.zeros(len(x_vals_unique))
                for i, yk in enumerate(y_keys_plot):
                    ax.bar(index, data_matrix[i], bottom=bottoms, label=str(yk))
                    bottoms += np.array(data_matrix[i])
                ax.set_xticks(index)
                ax.set_xticklabels([str(x) for x in x_vals_unique], rotation=45, ha='right')
                ax.set_title(title or "Cost breakdown")
                ax.set_xlabel(xlabel or x_key)
                ax.set_ylabel(ylabel or (y_keys_list[0] if y_keys_list else "Values"))
                if len(y_keys_plot) > 1:
                    legend_title = stack_col or "Segments"
                    ax.legend(title=legend_title)

            plt.tight_layout()
            img_b64 = self._fig_to_base64_dict(fig, filename=filename)
            payload = {
                "status": "ok",
                "type": "image_url",
                "image_url": {"url": str(img_b64.get("image_url", ""))},
                "metadata": {
                    "graph_type": graph_type,
                    "x_keys": x_keys_list,
                    "y_keys": y_keys_list,
                    "stack_key": stack_col,
                    "figure_size": scaled_figsize,
                    "recommendations": hints.get("recommended", {})
                }
            }

            if conversation_id:
                try:
                    self.upload_cosmos_message(conversation_id, str(img_b64.get("image_url", "")))
                except Exception:
                    logging.exception("Failed to upload chart image to Cosmos DB")
                    payload.setdefault("warnings", []).append("Chart rendered but storing to conversation failed.")
            else:
                payload.setdefault("warnings", []).append("Chart rendered but conversation_id was not provided; image not persisted.")

            return payload
        except Exception as ex:
            logging.exception("Error while generating chart")
            return {"status": "error", "error": f"Error while generating chart: {str(ex)}"}
        finally:
            if fig is not None:
                plt.close(fig)


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

    @kernel_function(description="Run an Azure Cost Management query and return rows, column metadata, and plotting hints for manual chart selection. Defaults to BillingMonthToDate timeframe.")
    @plugin_function_logger("AzureBillingPlugin")
    def run_data_query(self,
        conversation_id: str,
        subscription_id: str,
        resource_group_name: Optional[str] = None,
        query_type: str = "Usage",
        timeframe: str = "BillingMonthToDate",
        granularity: str = "Daily",
        aggregations: Optional[List[Dict[str, Any]]] = None,
        groupings: Optional[List[Dict[str, Any]]] = None,
        query_filter: Optional[Dict[str, Any]] = None,
        time_period: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Execute an Azure Cost Management query and return structured results.

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
        if not self._normalize_enum(timeframe, TIME_FRAME_TYPE):
            raise ValueError(f"Invalid timeframe: {timeframe}. Must be one of {TIME_FRAME_TYPE}.")
        if not self._normalize_enum(granularity, GRANULARITY_TYPE):
            raise ValueError(f"Invalid granularity: {granularity}. Must be one of {GRANULARITY_TYPE}.")
        query = {
            "type": query_type,
            "timeframe": timeframe,
            "dataset": {
                "granularity": granularity
            }
        }
        # If user did not provide aggregations/groupings or filter, construct sensible defaults
        if not aggregations and not groupings and not query_filter:
            logging.info("No aggregations/groupings/filter provided; applying default aggregation and grouping.")
            aggregations = [{
                "name": "totalCost",
                "function": "Sum",
                "column": "PreTaxCost"
            }]
            groupings = [{
                "type": "Dimension",
                "name": "ResourceType"
            }]
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
                if not gname or not self._normalize_enum(gname, GROUPING_DIMENSIONS):
                    return {"status": "error", "error": f"Grouping name '{gname}' is invalid. Must be one of: {GROUPING_DIMENSIONS}", "example": [{"type": "Dimension", "name": "ResourceType"}]}
                normalized_groupings.append({'type': gtype, 'name': gname})
            query["dataset"]["grouping"] = normalized_groupings
        if query_filter:
            query["dataset"]["filter"] = query_filter
        # Enforce presence and shape of time_period when timeframe is Custom
        if self._normalize_enum(timeframe, TIME_FRAME_TYPE) == "Custom":
            if not time_period or not isinstance(time_period, dict):
                example = {
                    "type": query_type,
                    "dataSet": {
                        "granularity": granularity,
                        "aggregation": {
                            "totalCost": {"name": "Cost", "function": "Sum"}
                        },
                        "grouping": [{"type": "Dimension", "name": "ResourceType"}]
                    },
                    "timeframe": "Custom",
                    "time_period": {"from": "2025-04-01T00:00:00+00:00", "to": "2025-09-30T23:59:59+00:00"}
                }
                return {
                    "status": "valueError",
                    "error": "timeframe is 'Custom' but no valid time_period provided. Provide a time_period dict with 'from' and 'to' ISO timestamps. Resubmit the query again with the time_period included.",
                    "example": example
                }
            # Validate that 'from' and 'to' exist
            if 'from' not in time_period or 'to' not in time_period:
                return {"status": "error", "error": "time_period must include 'from' and 'to' keys with ISO datetime strings."}
            query["timePeriod"] = time_period
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
            "status": "ok",
            "conversation_id": conversation_id,
            "scope": scope,
            "api_version": self.api_version,
            "query": query,
            "rows": result_rows,
            "row_count": len(result_rows),
            "columns": columns_meta,
            "csv": csv_output,
            "plot_hints": plot_hints
        }

    @kernel_function(description="Return available configuration options for Azure Billing report queries.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_query_configuration_options(self, subscription_id: str, resource_group_name: Optional[str] = None) -> Dict[str, Any]:
        get_dimension_results = self.get_grouping_dimensions(subscription_id, resource_group_name)
        if isinstance(get_dimension_results, dict) and ("error" in get_dimension_results or "consent_url" in get_dimension_results):
            return get_dimension_results
        if isinstance(get_dimension_results, list):
            global GROUPING_DIMENSIONS
            GROUPING_DIMENSIONS = get_dimension_results
        return {
            "TIME_FRAME_TYPE": TIME_FRAME_TYPE,
            "QUERY_TYPE": QUERY_TYPE,
            "GRANULARITY_TYPE": GRANULARITY_TYPE,
            "GROUPING_TYPE": GROUPING_TYPE,
            "GROUPING_DIMENSIONS": GROUPING_DIMENSIONS,
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
    def get_format_run_data_query(self) -> Dict[str, Any]:
        """
        Returns an example JSON object describing the expected parameters for run_data_query.
        Includes required/optional fields, types, valid values, and reflects the latest method signature.
        """
        return {
            "conversation_id": "<string, required - reuse this when calling plot_chart to persist images>",
            "subscription_id": "<string, required>",
            "resource_group_name": "<string, optional>",
            "query_type": f"<string, optional, one of {QUERY_TYPE}>",
            "timeframe": f"<string, optional, one of {TIME_FRAME_TYPE}>",
            "granularity": f"<string, optional, one of {GRANULARITY_TYPE}>",
            "aggregations": [
                {
                    "name": "totalCost",
                    "function": f"<string, one of {AGGREGATION_FUNCTIONS}>",
                    "column": f"<string, one of {AGGREGATION_COLUMNS}>"
                }
            ],
            "groupings": [
                {
                    "type": f"<string, one of {GROUPING_TYPE}>",
                    "name": f"<string, one of {GROUPING_DIMENSIONS}>"
                }
            ],
            "query_filter": "<object, optional – Cost Management filter definition>",
            "time_period": {
                "from": "2025-04-01T00:00:00+00:00",
                "to": "2025-09-30T23:59:59+00:00"
            },
            "example_request": {
                "conversation_id": "abc123",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "query_type": "Usage",
                "timeframe": "BillingMonthToDate",
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
                    {"ResourceType": "microsoft.compute/disks", "PreTaxCost": 4715.20}
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
                "Inspect plot_hints['recommended'] for suggested x_keys, y_keys, and chart types.",
                "Pass rows (or the csv string) plus the chosen keys into plot_chart to render and persist a graph."
            ]
        }

    # Returns the expected input data format for plot_custom_chart
    @kernel_function(description="Get the expected input data format for plot_custom_chart (graphing) as JSON.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_format_plot_chart() -> Dict[str, Any]:
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
            "filename": "chart.png",
            "figsize": [7.0, 5.0],
            "notes": [
                "Feed the list returned in run_data_query['rows'] directly, or supply the CSV from run_data_query['csv'].",
                "Pick x_keys/y_keys from run_data_query['plot_hints']['recommended'] to ensure compatible chart input.",
                "Pie charts require exactly one numeric y_key; stacked/grouped charts accept multiple."
            ]
        }

    def upload_cosmos_message(self, 
            conversation_id: str,
            content: str) -> Dict[str, Any]:
        """
        Upload a message to Azure Cosmos DB.
        """
        try:
            image_message_id = f"{conversation_id}_image_{int(time.time())}_{random.randint(1000,9999)}"    
            # Check if image data is too large for a single Cosmos document (2MB limit)
            # Account for JSON overhead by using 1.5MB as the safe limit for base64 content
            max_content_size = 1500000  # 1.5MB in bytes
            
            if len(content) > max_content_size:
                debug_print(f"Large image detected ({len(content)} bytes), splitting across multiple documents")
                
                # Split the data URL into manageable chunks
                if content.startswith('data:image/png;base64,'):
                    # Extract just the base64 part for splitting
                    data_url_prefix = 'data:image/png;base64,'
                    base64_content = content[len(data_url_prefix):]
                    debug_print(f"Extracted base64 content length: {len(base64_content)} bytes")
                else:
                    # For regular URLs, store as-is (shouldn't happen with large content)
                    data_url_prefix = ''
                    base64_content = content
                
                # Calculate chunk size and number of chunks
                chunk_size = max_content_size - len(data_url_prefix) - 200  # More room for JSON overhead
                chunks = [base64_content[i:i+chunk_size] for i in range(0, len(base64_content), chunk_size)]
                total_chunks = len(chunks)
                
                debug_print(f"Splitting into {total_chunks} chunks of max {chunk_size} bytes each")
                for i, chunk in enumerate(chunks):
                    debug_print(f"Chunk {i} length: {len(chunk)} bytes")
                
                # Verify we can reassemble before storing
                reassembled_test = data_url_prefix + ''.join(chunks)
                if len(reassembled_test) == len(content):
                    debug_print(f"✅ Chunking verification passed - can reassemble to original size")
                else:
                    debug_print(f"❌ Chunking verification failed - {len(reassembled_test)} vs {len(content)}")
                
                
                # Create main image document with metadata
                main_image_doc = {
                    'id': image_message_id,
                    'conversation_id': conversation_id,
                    'role': 'image',
                    'content': f"{data_url_prefix}{chunks[0]}",  # First chunk with data URL prefix
                    'prompt': '',
                    'created_at': datetime.datetime.utcnow().isoformat(),
                    'timestamp': datetime.datetime.utcnow().isoformat(),
                    'model_deployment_name': 'azurebillingplugin',
                    'metadata': {
                        'is_chunked': True,
                        'total_chunks': total_chunks,
                        'chunk_index': 0,
                        'original_size': len(content)
                    }
                }
                
                # Create additional chunk documents
                chunk_docs = []
                for i in range(1, total_chunks):
                    chunk_doc = {
                        'id': f"{image_message_id}_chunk_{i}",
                        'conversation_id': conversation_id,
                        'role': 'image_chunk',
                        'content': chunks[i],
                        'parent_message_id': image_message_id,
                        'created_at': datetime.datetime.utcnow().isoformat(),
                        'timestamp': datetime.datetime.utcnow().isoformat(),
                        'metadata': {
                            'is_chunk': True,
                            'chunk_index': i,
                            'total_chunks': total_chunks,
                            'parent_message_id': image_message_id
                        }
                    }
                    chunk_docs.append(chunk_doc)
                
                # Store all documents
                debug_print(f"Storing main document with content length: {len(main_image_doc['content'])} bytes")
                cosmos_messages_container.upsert_item(main_image_doc)
                
                for i, chunk_doc in enumerate(chunk_docs):
                    debug_print(f"Storing chunk {i+1} with content length: {len(chunk_doc['content'])} bytes")
                    cosmos_messages_container.upsert_item(chunk_doc)
                    
                debug_print(f"Successfully stored image in {total_chunks} documents")
                debug_print(f"Main doc content starts with: {main_image_doc['content'][:50]}...")
                debug_print(f"Main doc content ends with: ...{main_image_doc['content'][-50:]}")
                
                # Return the full image URL for immediate display
                response_image_url = content
                
            else:
                # Small image - store normally in single document
                debug_print(f"Small image ({len(content)} bytes), storing in single document")
                
                image_doc = {
                    'id': image_message_id,
                    'conversation_id': conversation_id,
                    'role': 'image',
                    'content': content,
                    'prompt': user_message,
                    'created_at': datetime.datetime.utcnow().isoformat(),
                    'timestamp': datetime.datetime.utcnow().isoformat(),
                    'model_deployment_name': image_gen_model,
                    'metadata': {
                        'is_chunked': False,
                        'original_size': len(content)
                    }
                }
                cosmos_messages_container.upsert_item(image_doc)
                response_image_url = content
            conversation_item = cosmos_conversations_container.read_item(item=conversation_id, partition_key=conversation_id)
            conversation_item['last_updated'] = datetime.datetime.utcnow().isoformat()
            cosmos_conversations_container.upsert_item(conversation_item)
        except Exception as e:
            print(f"[ABP] Error uploading image message to Cosmos DB: {str(e)}")
            logging.error(f"[ABP] Error uploading image message to Cosmos DB: {str(e)}")
