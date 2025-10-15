# azure_billing_plugin.py
"""
Azure Billing Plugin for Semantic Kernel
- Supports user (Entra ID) and service principal authentication
- Uses Azure Cost Management REST API for billing, budgets, alerts, forecasting
- Renders graphs server-side as PNG (base64 for web, downloadable)
- Returns tabular data as CSV for minimal token usage
"""

import io
import base64
import requests
import csv
import inspect
import matplotlib.pyplot as plt
from typing import Dict, Any, List, Optional, Union
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel.functions import kernel_function
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger
from functions_authentication import get_valid_access_token, get_valid_access_token_for_plugins
from azure.identity import DefaultAzureCredential

class AzureBillingPlugin(BasePlugin):
    def __init__(self, manifest: Dict[str, Any]):
        super().__init__(manifest)
        self.manifest = manifest
        self.additional_fields = manifest.get('additionalFields', {})
        self.auth = manifest.get('auth', {})
        self.endpoint = manifest.get('endpoint', 'https://management.azure.com')
        self.metadata_dict = manifest.get('metadata', {})
        self.api_version = additional_fields.get('apiVersion', '2023-03-01')

    def _get_token(self) -> Optional[str]:
        """Get an access token for Azure REST API calls."""
        auth_type = self.auth.get('type')
        if auth_type == 'servicePrincipal':
            # Service principal: use client credentials
            tenant_id = self.auth.get('tenantId')
            client_id = self.auth.get('identity')
            client_secret = self.auth.get('key')
            authority = self.endpoint.rstrip('/')
            token_url = f"{authority}/{tenant_id}/oauth2/v2.0/token"
            data = {
                'grant_type': 'client_credentials',
                'client_id': client_id,
                'client_secret': client_secret,
                'scope': 'https://{}/.default'.format(authority)
            }
            resp = requests.post(token_url, data=data)
            resp.raise_for_status()
            return resp.json().get('access_token')
        else:
            # User: use session token helper
            token = get_valid_access_token_for_plugins()
            return token

    def _get_headers(self) -> Dict[str, str]:
        token = self._get_token()
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

    def _get(self, url: str, params: Dict[str, Any] = None) -> Any:
        headers = self._get_headers()
        resp = requests.get(url, headers=headers, params=params)
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
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

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

    def get_functions(self) -> List[str]:
        """
        functions = []
        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            # Check for a custom attribute set by the decorator
            if getattr(method, "is_kernel_function", False):
                print(f"Registering function: {name} from AzureBillingPlugin")
                functions.append(name)
        return functions
        """
        return [
            "list_subscriptions",
            "list_resource_groups",
            "get_scope",
            "get_current_charges",
            "get_historical_charges",
            "get_forecast",
            "get_budgets",
            "get_alerts",
            "get_actual_cost_data",
            "get_forecast_cost_data",
            "plot_cost_trend",
            "plot_actual_and_forecast_cost"
        ]

    @kernel_function(description="List all subscriptions and resource groups acccessible to the user/service principal.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_scope(self) -> str:
        url = f"{self.endpoint}/subscriptions?api-version=2020-01-01"
        subs = self._get(url).get('value', [])
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

    @kernel_function(description="List all subscriptions accessible to the user/service principal.")
    @plugin_function_logger("AzureBillingPlugin")
    def list_subscriptions(self) -> str:
        url = f"{self.endpoint}/subscriptions?api-version=2020-01-01"
        data = self._get(url)
        subs = data.get('value', [])
        return self._csv_from_table(subs)

    @kernel_function(description="List all resource groups in a subscription.")
    @plugin_function_logger("AzureBillingPlugin")
    def list_resource_groups(self, subscription_id: str) -> str:
        url = f"{self.endpoint}/subscriptions/{subscription_id}/resourcegroups?api-version=2021-04-01"
        data = self._get(url)
        rgs = data.get('value', [])
        return self._csv_from_table(rgs)

    @kernel_function(description="Get current charges for a subscription or resource group.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_current_charges(self, scope: str) -> str:
        # scope: /subscriptions/{id} or /subscriptions/{id}/resourceGroups/{rg}
        url = f"{self.endpoint}{scope}/providers/Microsoft.CostManagement/query?api-version={self.api_version}"
        query = {
            "type": "ActualCost",
            "timeframe": "MonthToDate",
            "dataset": {"granularity": "Daily"}
        }
        data = self._post(url, query)
        rows = data.get('properties', {}).get('rows', [])
        columns = [c['name'] for c in data.get('properties', {}).get('columns', [])]
        result = [dict(zip(columns, row)) for row in rows]
        return self._csv_from_table(result)

    @kernel_function(description="Get historical billing data.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_historical_charges(self, scope: str, timeframe: str = "MonthToDate") -> str:
        url = f"{self.endpoint}{scope}/providers/Microsoft.CostManagement/query?api-version={self.api_version}"
        query = {
            "type": "ActualCost",
            "timeframe": timeframe,
            "dataset": {"granularity": "Daily"}
        }
        data = self._post(url, query)
        rows = data.get('properties', {}).get('rows', [])
        columns = [c['name'] for c in data.get('properties', {}).get('columns', [])]
        result = [dict(zip(columns, row)) for row in rows]
        return self._csv_from_table(result)

    @kernel_function(description="Get cost forecast.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_forecast(self, scope: str) -> str:
        url = f"{self.endpoint}{scope}/providers/Microsoft.CostManagement/query?api-version={self.api_version}"
        query = {
            "type": "Forecast",
            "timeframe": "MonthToDate",
            "dataset": {"granularity": "Daily"}
        }
        data = self._post(url, query)
        rows = data.get('properties', {}).get('rows', [])
        columns = [c['name'] for c in data.get('properties', {}).get('columns', [])]
        result = [dict(zip(columns, row)) for row in rows]
        return self._csv_from_table(result)

    @kernel_function(description="Get cost forecast with custom duration and granularity.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_forecast(self, scope: str, forecast_period_months: int = 12, granularity: str = "Monthly", lookback_months: Optional[int] = None) -> str:
        """
        Get cost forecast for a given period and granularity.
        scope: /subscriptions/{id} or /subscriptions/{id}/resourceGroups/{rg}
        forecast_period_months: Number of months to forecast (default 12)
        granularity: "Daily", "Monthly", "Weekly"
        lookback_months: If provided, use last N months as historical data for forecasting
        """
        url = f"{self.endpoint}{scope}/providers/Microsoft.CostManagement/query?api-version={self.api_version}"
        timeframe = "Custom"
        # Calculate start/end dates for forecast
        from datetime import datetime, timedelta
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
        rows = data.get('properties', {}).get('rows', [])
        columns = [c['name'] for c in data.get('properties', {}).get('columns', [])]
        result = [dict(zip(columns, row)) for row in rows]
        return self._csv_from_table(result)

    @kernel_function(description="Get budgets for a subscription/resource group.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_budgets(self, scope: str) -> str:
        url = f"{self.endpoint}{scope}/providers/Microsoft.CostManagement/budgets?api-version={self.api_version}"
        data = self._get(url)
        budgets = data.get('value', [])
        return self._csv_from_table(budgets)

    @kernel_function(description="Get cost alerts.")
    @plugin_function_logger("AzureBillingPlugin")
    def get_alerts(self, scope: str) -> str:
        url = f"{self.endpoint}{scope}/providers/Microsoft.CostManagement/alerts?api-version={self.api_version}"
        data = self._get(url)
        alerts = data.get('value', [])
        return self._csv_from_table(alerts)

    @kernel_function(description="Return a PNG graph of cost trend.")
    @plugin_function_logger("AzureBillingPlugin")
    def plot_cost_trend(self, scope: str, timeframe: str = "MonthToDate") -> str:
        url = f"{self.endpoint}{scope}/providers/Microsoft.CostManagement/query?api-version={self.api_version}"
        query = {
            "type": "ActualCost",
            "timeframe": timeframe,
            "dataset": {"granularity": "Daily"}
        }
        data = self._post(url, query)
        rows = data.get('properties', {}).get('rows', [])
        columns = [c['name'] for c in data.get('properties', {}).get('columns', [])]
        result = [dict(zip(columns, row)) for row in rows]
        # Assume columns include 'UsageDate' and 'Cost' or similar
        x = [r.get('UsageDate') or r.get('date') for r in result]
        y = [r.get('Cost') or r.get('PreTaxCost') or r.get('cost') for r in result]
        img_b64 = self._plot_graph(x, y, title="Cost Trend", xlabel="Date", ylabel="Cost ($)")
        return img_b64

    def get_historical_cost_data(self, scope: str, timeframe: str = "MonthToDate", granularity: str = "Daily") -> List[Dict[str, Any]]:
        """
        Retrieve actual cost data for a given scope and timeframe.
        Returns a list of dicts with date and cost.
        """
        url = f"{self.endpoint}{scope}/providers/Microsoft.CostManagement/query?api-version={self.api_version}"
        query = {
            "type": "ActualCost",
            "timeframe": timeframe,
            "dataset": {"granularity": granularity}
        }
        data = self._post(url, query)
        rows = data.get('properties', {}).get('rows', [])
        columns = [c['name'] for c in data.get('properties', {}).get('columns', [])]
        result = [dict(zip(columns, row)) for row in rows]
        return result

    def get_forecast_cost_data(self, scope: str, forecast_period_months: int = 12, granularity: str = "Monthly", lookback_months: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieve forecast cost data for a given scope and period.
        Returns a list of dicts with date and forecasted cost.
        """
        url = f"{self.endpoint}{scope}/providers/Microsoft.CostManagement/query?api-version={self.api_version}"
        timeframe = "Custom"
        from datetime import datetime, timedelta
        today = datetime.utcnow().date()
        start_date = today
        end_date = today + timedelta(days=forecast_period_months * 30)
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
        if hist_start and hist_end:
            query["historicalTimePeriod"] = {
                "from": hist_start.isoformat(),
                "to": hist_end.isoformat()
            }
        data = self._post(url, query)
        rows = data.get('properties', {}).get('rows', [])
        columns = [c['name'] for c in data.get('properties', {}).get('columns', [])]
        result = [dict(zip(columns, row)) for row in rows]
        return result

    @kernel_function(description="Return a PNG graph of actual and forecasted cost trend.")
    @plugin_function_logger("AzureBillingPlugin")
    def plot_actual_and_forecast_cost(self, scope: str, actual_timeframe: str = "MonthToDate", actual_granularity: str = "Daily", forecast_period_months: int = 12, forecast_granularity: str = "Monthly", lookback_months: Optional[int] = None) -> str:
        """
        Plot both actual and forecasted cost trends on a single PNG graph.
        Returns base64 PNG string.
        """
        actual_data = self.get_actual_cost_data(scope, actual_timeframe, actual_granularity)
        forecast_data = self.get_forecast_cost_data(scope, forecast_period_months, forecast_granularity, lookback_months)
        # Extract dates and costs
        actual_x = [r.get('UsageDate') or r.get('date') for r in actual_data]
        actual_y = [r.get('Cost') or r.get('PreTaxCost') or r.get('cost') for r in actual_data]
        forecast_x = [r.get('UsageDate') or r.get('date') for r in forecast_data]
        forecast_y = [r.get('Cost') or r.get('PreTaxCost') or r.get('cost') for r in forecast_data]
        plt.figure(figsize=(10, 5))
        plt.plot(actual_x, actual_y, marker='o', label='Actual Cost')
        plt.plot(forecast_x, forecast_y, marker='x', linestyle='--', label='Forecast Cost')
        plt.title("Actual vs Forecasted Cost Trend")
        plt.xlabel("Date")
        plt.ylabel("Cost ($)")
        plt.legend()
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close()
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode('utf-8')
        return img_b64