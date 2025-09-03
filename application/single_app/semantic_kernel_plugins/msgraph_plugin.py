from typing import Dict, Any, List
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel.functions import kernel_function
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger
import requests
from flask import session
from functions_authentication import get_valid_access_token

class MSGraphPlugin(BasePlugin):
    def __init__(self, manifest: Dict[str, Any]):
        self.manifest = manifest
        self._metadata = manifest.get('metadata', {})
        # You can add more config here if needed

    @property
    def display_name(self) -> str:
        return "Microsoft Graph"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "name": self.manifest.get("name", "msgraph_plugin"),
            "type": "msgraph",
            "description": "Plugin for interacting with Microsoft Graph API. Supports calendar lookup, user profile, and security info.",
            "methods": [
                {
                    "name": "get_my_profile",
                    "description": "Get information about the signed-in user.",
                    "parameters": [],
                    "returns": {"type": "dict", "description": "User profile info from MS Graph."}
                },
                {
                    "name": "get_my_events",
                    "description": "Get upcoming calendar events for the signed-in user.",
                    "parameters": [
                        {"name": "top", "type": "int", "description": "Number of events to return.", "required": False}
                    ],
                    "returns": {"type": "dict", "description": "List of events from MS Graph."}
                },
                {
                    "name": "get_my_security_alerts",
                    "description": "Get recent security alerts for the signed-in user (requires SecurityEvents.Read.All).",
                    "parameters": [
                        {"name": "top", "type": "int", "description": "Number of alerts to return.", "required": False}
                    ],
                    "returns": {"type": "dict", "description": "List of security alerts from MS Graph."}
                }
            ]
        }

    def get_functions(self) -> List[str]:
        return ["get_my_profile", "get_my_events", "get_my_security_alerts"]

    def _get_token(self, scopes=None):
        # Use the existing authentication helper to get a valid token for Graph
        scopes = scopes or ["https://graph.microsoft.com/.default"]
        token = get_valid_access_token(scopes=scopes)
        if not token:
            raise Exception("Could not acquire MS Graph access token. User may need to re-authenticate.")
        return token

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Get information about the signed-in user.")
    def get_my_profile(self) -> dict:
        token = self._get_token(["User.Read"])
        headers = {"Authorization": f"Bearer {token}"}
        base = self.manifest.get("endpoint", "https://graph.microsoft.com").rstrip("/")
        url = base + "/v1.0/me"
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Get upcoming calendar events for the signed-in user.")
    def get_my_events(self, top: int = 5) -> dict:
        token = self._get_token(["Calendars.Read"])
        headers = {"Authorization": f"Bearer {token}"}
        params = {"$top": top}
        base = self.manifest.get("endpoint", "https://graph.microsoft.com").rstrip("/")
        url = base + "/v1.0/me/events"
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Get recent security alerts for the signed-in user.")
    def get_my_security_alerts(self, top: int = 5) -> dict:
        token = self._get_token(["SecurityEvents.Read.All"])
        headers = {"Authorization": f"Bearer {token}"}
        params = {"$top": top}
        base = self.manifest.get("endpoint", "https://graph.microsoft.com").rstrip("/")
        url = base + "/v1.0/security/alerts"
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()
