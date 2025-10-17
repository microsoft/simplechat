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
import re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union
import json
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel.functions import kernel_function
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger
from functions_authentication import get_valid_access_token, get_valid_access_token_for_plugins
from azure.identity import DefaultAzureCredential
from functions_debug import debug_print
from azure.core.credentials import AccessToken, TokenCredential

RESOURCE_ID_REGEX = r"^/subscriptions/(?P<subscriptionId>[a-fA-F0-9-]+)/?(?:resourceGroups/(?P<resourceGroupName>[^/]+))?$"
TIME_FRAME_TYPE = ["MonthToDate", "BillingMonthToDate", "WeekToDate", "Custom"] # "TheLastMonth, TheLastBillingMonth" are not supported in MAG
QUERY_TYPE = ["Usage", "ActualCost", "AmortizedCost"]
GRANULARITY_TYPE = ["None", "Daily", "Monthly", "Accumulated"]
GROUPING_TYPE = ["Dimension", "TagKey"]
AGGREGATION_FUNCTIONS = ["Sum"]#, "Average", "Min", "Max", "Count", "None"]
GROUPING_CATEGORY = ["None", "BillingPeriod", "ChargeType", "Frequency", "MeterCategory", "MeterId", "MeterSubCategory", "Product", "ResourceGroupName", "ResourceLocation", "ResourceType", "ServiceFamily", "ServiceName", "SubscriptionId", "SubscriptionName", "Tag"]

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

    def _plot_graph(self, x, y, title: str = "", xlabel: str = "", ylabel: str = "") -> str:
        plt.figure(figsize=(8, 4))
        plt.plot(x, y, marker='o')
        plt.title(title)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close()
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode('utf-8')
        return img_b64

    def _fig_to_base64_dict(self, fig, filename: str = "chart.png") -> Dict[str, str]:
        """Convert a matplotlib Figure to a structured base64 dict.

        Returns: {"mime": "image/png", "filename": filename, "base64": <b64str>, "data_url": "data:image/png;base64,<b64>"}
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
            "data_url": f"data:image/png;base64,{img_b64}"
        }

    @kernel_function(description="Plot a custom chart from provided data. Supports pie, column_stacked, column_grouped, line, and area.")
    @plugin_function_logger("AzureBillingPlugin")
    def plot_custom_chart(self,
                          data: List[Dict[str, Any]],
                          x_key: Optional[str] = None,
                          y_keys: Optional[List[str]] = None,
                          chart_type: str = "line",
                          title: str = "",
                          xlabel: str = "",
                          ylabel: str = "",
                          filename: str = "chart.png",
                          figsize: tuple = (10, 6)) -> Dict[str, Any]:
        """
        General plotting function.

        - data: list of dict rows (e.g., [{'date': '2025-10-01', 'cost': 12.3, 'type': 'A'}, ...])
        - x_key: key to use for x axis (required for non-pie charts)
        - y_keys: list of keys to plot on y axis (if None and chart_type is not pie, autodetect numeric columns)
        - chart_type: one of ['pie', 'column_stacked', 'column_grouped', 'line', 'area']
        - returns structured dict with mime, filename, base64, data_url and metadata
        """
        chart_type = chart_type.lower() if isinstance(chart_type, str) else str(chart_type)
        supported = ["pie", "column_stacked", "column_grouped", "line", "area"]
        if chart_type not in supported:
            raise ValueError(f"Unsupported chart_type '{chart_type}'. Supported: {supported}")

        # Defensive copy
        rows = [r.copy() for r in (data or [])]

        # If no data, return an error-like dict
        if not rows:
            raise ValueError("No data provided for plotting")

        # Autodetect numeric columns if y_keys not provided
        if not y_keys and chart_type != "pie":
            sample = rows[0]
            y_keys = [k for k, v in sample.items() if isinstance(v, (int, float))]
            if not y_keys:
                raise ValueError("Could not autodetect numeric columns for y axis. Provide y_keys explicitly.")

        # Prepare x values
        x_vals = None
        if chart_type != "pie":
            if not x_key:
                # attempt to pick a sensible x_key (date-like or first non-numeric)
                for k, v in rows[0].items():
                    if not isinstance(v, (int, float)):
                        x_key = k
                        break
            if not x_key:
                raise ValueError("x_key is required for this chart type")
            x_vals = [r.get(x_key) for r in rows]

        # Build matplotlib figure
        fig, ax = plt.subplots(figsize=figsize)

        if chart_type == "pie":
            # For pie, expect y_keys to be a single key and aggregate values by label (x_key)
            if not x_key or (not y_keys or len(y_keys) != 1):
                raise ValueError("Pie chart requires an x_key (labels) and a single y_key for values")
            labels = [r.get(x_key) for r in rows]
            values = [r.get(y_keys[0]) or 0 for r in rows]
            ax.pie(values, labels=labels, autopct="%1.1f%%")
            ax.set_title(title)

        elif chart_type in ("line", "area"):
            for yk in y_keys:
                y_vals = [r.get(yk) or 0 for r in rows]
                if chart_type == "line":
                    ax.plot(x_vals, y_vals, marker='o', label=yk)
                else:
                    ax.fill_between(x_vals, y_vals, alpha=0.5, label=yk)
            if y_keys and len(y_keys) > 1:
                ax.legend()
            ax.set_title(title)
            ax.set_xlabel(xlabel or x_key)
            ax.set_ylabel(ylabel)

        elif chart_type == "column_grouped":
            # Grouped bar chart: for each x position, multiple bars side-by-side
            import numpy as np
            n_groups = len(rows)
            n_bars = len(y_keys)
            index = np.arange(n_groups)
            bar_width = 0.8 / max(1, n_bars)
            for i, yk in enumerate(y_keys):
                y_vals = [r.get(yk) or 0 for r in rows]
                ax.bar(index + i * bar_width, y_vals, bar_width, label=yk)
            ax.set_xticks(index + bar_width * (n_bars - 1) / 2)
            ax.set_xticklabels([str(x) for x in x_vals], rotation=45, ha='right')
            ax.set_title(title)
            ax.set_xlabel(xlabel or x_key)
            ax.set_ylabel(ylabel)
            if y_keys and len(y_keys) > 1:
                ax.legend()

        elif chart_type == "column_stacked":
            import numpy as np
            index = np.arange(len(rows))
            bottoms = [0] * len(rows)
            for yk in y_keys:
                y_vals = [r.get(yk) or 0 for r in rows]
                ax.bar(index, y_vals, bottom=bottoms, label=yk)
                bottoms = [b + y for b, y in zip(bottoms, y_vals)]
            ax.set_xticks(index)
            ax.set_xticklabels([str(x) for x in x_vals], rotation=45, ha='right')
            ax.set_title(title)
            ax.set_xlabel(xlabel or x_key)
            ax.set_ylabel(ylabel)
            if y_keys and len(y_keys) > 1:
                ax.legend()

        plt.tight_layout()
        result = self._fig_to_base64_dict(fig, filename=filename)
        return {"status": "ok", "chart": result, "metadata": {"type": chart_type, "x_key": x_key, "y_keys": y_keys}}

    @property
    def display_name(self) -> str:
        return "Azure Billing"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "name": self.metadata_dict.get("name", "azure_billing_plugin"),
            "type": "azure_billing",
            "description": "Azure Billing plugin for cost, budgets, alerts, forecasting, CSV export, and PNG graphing.",
            "methods": [
                {"name": "list_subscriptions", "description": "List all subscriptions accessible to the user/service principal. Returns CSV."},
                {"name": "list_resource_groups", "description": "List all resource groups in a subscription. Returns CSV."},
                {"name": "get_scope", "description": "Get the billing scope string for a subscription or resource group (e.g., /subscriptions/{id} or /subscriptions/{id}/resourceGroups/{rg})."},
                {"name": "get_current_charges", "description": "Get current charges for a subscription or resource group. Returns CSV."},
                {"name": "get_historical_charges", "description": "Get historical billing data. Returns CSV."},
                {"name": "get_forecast", "description": "Get cost forecast for a given period and granularity. Returns CSV."},
                {"name": "get_budgets", "description": "Get budgets for a subscription/resource group. Returns CSV."},
                {"name": "get_alerts", "description": "Get cost alerts. Returns CSV."},
                {"name": "get_actual_cost_data", "description": "Retrieve actual cost data as a list of dicts."},
                {"name": "get_forecast_cost_data", "description": "Retrieve forecast cost data as a list of dicts."},
                {"name": "plot_cost_trend", "description": "Return a PNG graph of actual cost trend (base64 PNG)."},
                {"name": "plot_actual_and_forecast_cost", "description": "Return a PNG graph of actual and forecasted cost trends (base64 PNG)."}
            ]
        }

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
        today = datetime.utcnow().date()
        start_date = today
        end_date = today + timedelta(days=forecast_period_months * 30)
        # If lookback_months is set, use that for historical data
        if lookback_months:
            hist_start = today - timedelta(days=lookback_months * 30)
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
    def get_specific_alert(self, subscription_id: str, resource_group_name: Optional[str] = None, alertId: str ) -> str:
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

    @kernel_function(description="Return a PNG graph of cost trend.")
    @plugin_function_logger("AzureBillingPlugin")
    def plot_cost_trend(self, subscription_id: str, resource_group_name: Optional[str] = None, timeframe: str = "MonthToDate") -> str:
        if resource_group_name:
            scope = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}"
        else:
            scope = f"/subscriptions/{subscription_id}"
        url = f"{self.endpoint.rstrip('/')}{scope}/providers/Microsoft.CostManagement/query?api-version={self.api_version}"
        query = {
            "type": "ActualCost",
            "timeframe": timeframe,
            "dataset": {"granularity": "Daily"}
        }
        data = self._post(url, query)
        if isinstance(data, dict) and ("error" in data or "consent_url" in data):
            return data
        rows = data.get('properties', {}).get('rows', [])
        columns = [c['name'] for c in data.get('properties', {}).get('columns', [])]
        result = [dict(zip(columns, row)) for row in rows]
        # Assume columns include 'UsageDate' and 'Cost' or similar
        x = [r.get('UsageDate') or r.get('date') for r in result]
        y = [r.get('Cost') or r.get('PreTaxCost') or r.get('cost') for r in result]
        img_b64 = self._plot_graph(x, y, title="Cost Trend", xlabel="Date", ylabel="Cost ($)")
        return f'<img src="data:image/png;base64,{img_b64}"/>'

    @kernel_function(description="Run a general Azure Cost Management query with flexible dataset and aggregation. Defaults to BillingMonthToDate. Supports up to two allowed query aggregations as per API spec.")
    @plugin_function_logger("AzureBillingPlugin")
    def run_data_query(self, subscription_id: str, resource_group_name: Optional[str] = None, query_type: str = "Usage", timeframe: str = "BillingMonthToDate", granularity: str = "Daily", aggregations: Optional[List[Dict[str, Any]]] = None, groupings: Optional[List[Dict[str, Any]]] = None, query_filter: Optional[Dict[str, Any]] = None, time_period: Optional[Dict[str, str]] = None) -> str:
        """
        Run a general Azure Cost Management query.
        - subscription_id: Azure subscription ID (required)
        - resource_group_name: Resource group name (optional)
        - query_type: "Usage", "ActualCost", or "Forecast" (default: "Usage")
        - timeframe: e.g., "BillingMonthToDate", "MonthToDate", "Custom" (default: "BillingMonthToDate")
        - granularity: "None", "Daily", "Monthly" (default: "Daily")
        - aggregations: list of aggregation dicts, e.g., [{"name": "totalCost", "function": "Sum", "column": "PreTaxCost"}]
        - groupings: list of grouping dicts, e.g., [{"type": "Dimension", "name": "ResourceGroupName"}]
        - query_filter: dict representing filter (optional)
        - time_period: dict with "from" and "to" ISO date strings (required if timeframe is "Custom")
        """
        if resource_group_name:
            scope = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}"
        else:
            scope = f"/subscriptions/{subscription_id}"
        url = f"{self.endpoint.rstrip('/')}{scope}/providers/Microsoft.CostManagement/query?api-version={self.api_version}"
        if query_type not in QUERY_TYPE:
            raise ValueError(f"Invalid query_type: {query_type}. Must be one of {QUERY_TYPE}.")
        if timeframe not in TIME_FRAME_TYPE:
            raise ValueError(f"Invalid timeframe: {timeframe}. Must be one of {TIME_FRAME_TYPE}.")
        if granularity not in GRANULARITY_TYPE:
            raise ValueError(f"Invalid granularity: {granularity}. Must be one of {GRANULARITY_TYPE}.")
        query = {
            "type": query_type,
            "timeframe": timeframe,
            "dataset": {
                "granularity": granularity
            }
        }
        if not aggregations and not groupings and not query_filter:
            return "Either aggregations and groupings or a query_filter must be provided."
        # Validate and normalize aggregations (if provided)
        if aggregations:
            if not isinstance(aggregations, list):
                raise ValueError("aggregations must be a list of aggregation definitions")
            if len(aggregations) > 2:
                logging.warning("More than 2 aggregations provided; only the first 2 will be used")
            agg_map: Dict[str, Any] = {}
            for agg in aggregations[:2]:
                if not isinstance(agg, dict):
                    raise ValueError("Each aggregation must be a dict")
                # Support shape: {"name":..., "function":..., ...} or {"type":..., "aggregation": {"name":..., "function":..., ...}}
                if 'aggregation' in agg and isinstance(agg['aggregation'], dict):
                    sub = agg['aggregation']
                    name = sub.get('name') or agg.get('name')
                    function = sub.get('function') or agg.get('function')
                    details = {k: v for k, v in sub.items() if k != 'name'}
                else:
                    name = agg.get('name')
                    function = agg.get('function')
                    details = {k: v for k, v in agg.items() if k != 'name'}
                if not name:
                    raise ValueError("Aggregation entry missing 'name'")
                if not function:
                    raise ValueError(f"Aggregation '{name}' missing 'function'")
                if function not in AGGREGATION_FUNCTIONS:
                    raise ValueError(f"Aggregation function '{function}' is invalid. Must be one of: {AGGREGATION_FUNCTIONS}")
                agg_map[name] = details
            query["dataset"]["aggregation"] = agg_map

        # Validate and normalize groupings (if provided)
        if groupings:
            if not isinstance(groupings, list):
                raise ValueError("groupings must be a list of grouping definitions")
            if len(groupings) > 2:
                logging.warning("More than 2 groupings provided; only the first 2 will be used")
            normalized_groupings: List[Dict[str, str]] = []
            for grp in groupings[:2]:
                if not isinstance(grp, dict):
                    raise ValueError("Each grouping must be a dict with 'type' and 'name'")
                gtype = grp.get('type')
                gname = grp.get('name')
                if not gtype or gtype not in GROUPING_TYPE:
                    raise ValueError(f"Grouping type '{gtype}' is invalid. Must be one of: {GROUPING_TYPE}")
                if not gname or gname not in GROUPING_CATEGORY:
                    raise ValueError(f"Grouping name '{gname}' is invalid. Must be one of: {GROUPING_CATEGORY}")
                normalized_groupings.append({'type': gtype, 'name': gname})
            query["dataset"]["grouping"] = normalized_groupings
        if query_filter:
            query["dataset"]["filter"] = query_filter
        if timeframe == "Custom" and time_period:
            query["timePeriod"] = time_period
        data = self._post(url, query)
        if isinstance(data, dict) and ("error" in data or "consent_url" in data):
            return data
        rows = data.get('properties', {}).get('rows', [])
        columns = [c['name'] for c in data.get('properties', {}).get('columns', [])]
        result = [dict(zip(columns, row)) for row in rows]
        return self._csv_from_table(result)

    @kernel_function(description="Return available configuration options for Azure Billing report queries.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_query_configuration_options(self, subscription_id: str, resource_group_name: Optional[str] = None) -> Dict[str, Any]:
        get_categories_result = self.get_grouping_categories(subscription_id, resource_group_name)
        if isinstance(get_categories_result, dict) and ("error" in get_categories_result or "consent_url" in get_categories_result):
            return get_categories_result
        if isinstance(get_categories_result, list):
            global GROUPING_CATEGORY
            GROUPING_CATEGORY = get_categories_result
        return {
            "TIME_FRAME_TYPE": TIME_FRAME_TYPE,
            "QUERY_TYPE": QUERY_TYPE,
            "GRANULARITY_TYPE": GRANULARITY_TYPE,
            "GROUPING_TYPE": GROUPING_TYPE,
            "GROUPING_CATEGORY": GROUPING_CATEGORY,
            "AGGREGATION_FUNCTIONS": AGGREGATION_FUNCTIONS,
            "NOTE": "Not all combinations are available for all queries."
        }

    @kernel_function(description="Get available cost categories (dimensions) for Azure Billing.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_grouping_categories(self, subscription_id: str, resource_group_name: Optional[str] = None) -> List[str]:
        if resource_group_name:
            scope = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}"
        else:
            scope = f"/subscriptions/{subscription_id}"
        # Use the Cost Management query endpoint to retrieve available dimensions/categories
        # Note: some Cost Management responses return a 'value' array where each item has a
        # 'properties' object containing a 'category' property. We handle that shape and
        # fall back to other common fields.
        url = f"{self.endpoint.rstrip('/')}{scope}/providers/Microsoft.CostManagement/query?api-version={self.api_version}"
        data = self._get(url)
        if isinstance(data, dict) and ("error" in data or "consent_url" in data):
            return data

        values = data.get('value', []) if isinstance(data, dict) else []
        cats = []
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
                cats.append(cat)

        # dedupe while preserving order
        seen = set()
        deduped = []
        for c in cats:
            if c not in seen:
                seen.add(c)
                deduped.append(c)
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


    