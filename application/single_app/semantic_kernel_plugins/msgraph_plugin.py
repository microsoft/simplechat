# msgraph_plugin.py

from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
from requests import RequestException

from functions_authentication import get_valid_access_token_for_plugins
from functions_debug import debug_print
from semantic_kernel.functions import kernel_function
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


class MSGraphPlugin(BasePlugin):
    DEFAULT_ENDPOINT = "https://graph.microsoft.com"
    DEFAULT_TIMEOUT_SECONDS = 30
    MAX_ITEMS_PER_RESULT = 25
    MAX_PAGES_PER_REQUEST = 5

    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        super().__init__(manifest)
        self.manifest = manifest or {}
        self._metadata = self.manifest.get("metadata", {})
        self._endpoint = self.manifest.get("endpoint", self.DEFAULT_ENDPOINT).rstrip("/")
        scope_overrides = self.manifest.get("scopes") or self._metadata.get("scopes") or {}
        self._scope_overrides = scope_overrides if isinstance(scope_overrides, dict) else {}

    @property
    def display_name(self) -> str:
        return "Microsoft Graph"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "name": self.manifest.get("name", "msgraph_plugin"),
            "type": "msgraph",
            "description": (
                "Plugin for interacting with Microsoft Graph API. Supports user profile, "
                "calendar, mailbox timezone settings, mail, directory, drive, and security alert operations."
            ),
            "methods": [
                {
                    "name": "get_my_profile",
                    "description": "Get the signed-in user's profile details.",
                    "parameters": [
                        {
                            "name": "select_fields",
                            "type": "str",
                            "description": "Optional comma-separated Graph fields to include.",
                            "required": False,
                        }
                    ],
                    "returns": {"type": "dict", "description": "User profile information from Microsoft Graph."},
                },
                {
                    "name": "get_my_timezone",
                    "description": "Get the signed-in user's Microsoft 365 mailbox time zone and related formatting settings. Use this before answering timezone-sensitive questions.",
                    "parameters": [],
                    "returns": {"type": "dict", "description": "Mailbox timezone, date format, and time format settings from Microsoft Graph."},
                },
                {
                    "name": "get_my_events",
                    "description": "Get upcoming calendar events for the signed-in user.",
                    "parameters": [
                        {"name": "top", "type": "int", "description": "Maximum number of events to return.", "required": False},
                        {
                            "name": "start_datetime",
                            "type": "str",
                            "description": "Optional ISO datetime. If provided with end_datetime, uses calendarView.",
                            "required": False,
                        },
                        {
                            "name": "end_datetime",
                            "type": "str",
                            "description": "Optional ISO datetime. If provided with start_datetime, uses calendarView.",
                            "required": False,
                        },
                        {
                            "name": "select_fields",
                            "type": "str",
                            "description": "Optional comma-separated Graph fields to include.",
                            "required": False,
                        },
                    ],
                    "returns": {"type": "dict", "description": "Calendar event results from Microsoft Graph."},
                },
                {
                    "name": "get_my_messages",
                    "description": "Get recent mail messages for the signed-in user.",
                    "parameters": [
                        {"name": "top", "type": "int", "description": "Maximum number of messages to return.", "required": False},
                        {"name": "folder", "type": "str", "description": "Optional mail folder name, such as inbox.", "required": False},
                        {"name": "unread_only", "type": "bool", "description": "If true, only unread messages are returned.", "required": False},
                        {
                            "name": "select_fields",
                            "type": "str",
                            "description": "Optional comma-separated Graph fields to include.",
                            "required": False,
                        },
                    ],
                    "returns": {"type": "dict", "description": "Mail message results from Microsoft Graph."},
                },
                {
                    "name": "search_users",
                    "description": "Search directory users by name or email prefix.",
                    "parameters": [
                        {"name": "query", "type": "str", "description": "Search text for display name or email.", "required": True},
                        {"name": "top", "type": "int", "description": "Maximum number of users to return.", "required": False},
                        {
                            "name": "select_fields",
                            "type": "str",
                            "description": "Optional comma-separated Graph fields to include.",
                            "required": False,
                        },
                    ],
                    "returns": {"type": "dict", "description": "Matching users from Microsoft Graph."},
                },
                {
                    "name": "get_user_by_email",
                    "description": "Get a directory user by exact email address or UPN.",
                    "parameters": [
                        {"name": "email", "type": "str", "description": "Exact email address or user principal name.", "required": True},
                        {
                            "name": "select_fields",
                            "type": "str",
                            "description": "Optional comma-separated Graph fields to include.",
                            "required": False,
                        },
                    ],
                    "returns": {"type": "dict", "description": "User match information from Microsoft Graph."},
                },
                {
                    "name": "list_drive_items",
                    "description": "List OneDrive items from the root or a child path for the signed-in user.",
                    "parameters": [
                        {"name": "path", "type": "str", "description": "Optional path below the drive root.", "required": False},
                        {"name": "top", "type": "int", "description": "Maximum number of items to return.", "required": False},
                        {
                            "name": "select_fields",
                            "type": "str",
                            "description": "Optional comma-separated Graph fields to include.",
                            "required": False,
                        },
                    ],
                    "returns": {"type": "dict", "description": "Drive item results from Microsoft Graph."},
                },
                {
                    "name": "get_my_security_alerts",
                    "description": "Get recent security alerts for the signed-in user. Requires elevated Graph permissions.",
                    "parameters": [
                        {"name": "top", "type": "int", "description": "Maximum number of alerts to return.", "required": False}
                    ],
                    "returns": {"type": "dict", "description": "Security alert results from Microsoft Graph."},
                },
            ],
        }

    def get_functions(self) -> List[str]:
        return [
            "get_my_profile",
            "get_my_timezone",
            "get_my_events",
            "get_my_messages",
            "search_users",
            "get_user_by_email",
            "list_drive_items",
            "get_my_security_alerts",
        ]

    def _get_scopes(self, operation_name: str, default_scopes: List[str]) -> List[str]:
        configured_scopes = self._scope_overrides.get(operation_name)
        if isinstance(configured_scopes, str) and configured_scopes.strip():
            return [configured_scopes.strip()]
        if isinstance(configured_scopes, list):
            normalized_scopes = [scope.strip() for scope in configured_scopes if isinstance(scope, str) and scope.strip()]
            if normalized_scopes:
                return normalized_scopes
        return default_scopes

    def _get_token(self, operation_name: str, default_scopes: List[str]) -> Tuple[Optional[str], List[str], Optional[Dict[str, Any]]]:
        scopes = self._get_scopes(operation_name, default_scopes)
        token_result = get_valid_access_token_for_plugins(scopes=scopes)
        if isinstance(token_result, dict) and token_result.get("access_token"):
            return token_result["access_token"], scopes, None

        error_payload = token_result if isinstance(token_result, dict) else {
            "error": "token_acquisition_failed",
            "message": "Failed to acquire Microsoft Graph access token.",
        }
        error_payload.setdefault("operation", operation_name)
        error_payload.setdefault("scopes", scopes)
        return None, scopes, error_payload

    def _normalize_top(self, top: int) -> int:
        try:
            normalized_top = int(top)
        except (TypeError, ValueError):
            return 5
        return max(1, min(normalized_top, self.MAX_ITEMS_PER_RESULT))

    def _sanitize_select_fields(self, select_fields: str) -> Optional[str]:
        if not select_fields:
            return None

        allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./")
        fields = []
        for raw_field in select_fields.split(","):
            field = raw_field.strip()
            if field and all(char in allowed_chars for char in field):
                fields.append(field)

        return ",".join(fields) if fields else None

    def _sanitize_filter_value(self, value: str) -> str:
        return value.replace("'", "''").strip()

    def _build_odata_params(
        self,
        top: int = 5,
        select_fields: str = "",
        filter_query: str = "",
        order_by: str = "",
        search_query: str = "",
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        params: Dict[str, Any] = {"$top": self._normalize_top(top)}
        headers: Dict[str, str] = {}

        normalized_select = self._sanitize_select_fields(select_fields)
        if normalized_select:
            params["$select"] = normalized_select

        if filter_query.strip():
            params["$filter"] = filter_query.strip()

        if order_by.strip():
            params["$orderby"] = order_by.strip()

        if search_query.strip():
            params["$search"] = search_query.strip()
            headers["ConsistencyLevel"] = "eventual"

        if extra_params:
            for key, value in extra_params.items():
                if value is not None and value != "":
                    params[key] = value

        return params, headers

    def _build_graph_error(
        self,
        operation_name: str,
        scopes: List[str],
        response: Optional[requests.Response] = None,
        exception: Optional[Exception] = None,
        fallback_message: str = "Microsoft Graph request failed.",
    ) -> Dict[str, Any]:
        error_payload: Dict[str, Any] = {
            "error": "graph_request_failed",
            "message": fallback_message,
            "operation": operation_name,
            "scopes": scopes,
        }

        if response is not None:
            error_payload["status_code"] = response.status_code
            try:
                graph_body = response.json()
            except ValueError:
                graph_body = None

            graph_error = graph_body.get("error", {}) if isinstance(graph_body, dict) else {}
            graph_message = graph_error.get("message") or response.text.strip() or fallback_message
            graph_code = graph_error.get("code") or error_payload["error"]

            error_payload["error"] = graph_code
            error_payload["message"] = graph_message

            if response.status_code == 429:
                error_payload["error"] = "throttled"
                error_payload["retry_after_seconds"] = response.headers.get("Retry-After")
            elif response.status_code == 401:
                error_payload["error"] = "unauthorized"
            elif response.status_code == 403:
                error_payload["error"] = "forbidden"
            elif response.status_code == 404:
                error_payload["error"] = "not_found"

        if exception is not None:
            error_payload["details"] = str(exception)

        debug_print(f"[MSGraphPlugin] {operation_name} failed: {error_payload}")
        return error_payload

    def _shape_graph_result(self, operation_name: str, payload: Any, max_items: int) -> Dict[str, Any]:
        if isinstance(payload, dict) and isinstance(payload.get("value"), list):
            items = payload.get("value", [])
            next_link = payload.get("@odata.nextLink")
            limited_items = items[:max_items]
            return {
                "operation": operation_name,
                "count": len(limited_items),
                "value": limited_items,
                "next_link": next_link,
                "truncated": len(items) > max_items,
            }

        if isinstance(payload, dict):
            shaped_payload = dict(payload)
            shaped_payload.setdefault("operation", operation_name)
            return shaped_payload

        return {
            "operation": operation_name,
            "value": payload,
        }

    def _perform_graph_request(
        self,
        operation_name: str,
        method: str,
        path: str,
        default_scopes: List[str],
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        paginate: bool = False,
        max_items: int = 5,
        additional_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        token, scopes, token_error = self._get_token(operation_name, default_scopes)
        if token_error:
            debug_print(f"[MSGraphPlugin] {operation_name} token acquisition failed: {token_error}")
            return token_error

        url = path if path.startswith("http") else f"{self._endpoint}{path}"
        normalized_max_items = self._normalize_top(max_items)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        if additional_headers:
            headers.update(additional_headers)

        collected_items: List[Any] = []
        next_url = url
        next_params = dict(params or {})
        pages_fetched = 0
        last_next_link = None

        while next_url and pages_fetched < self.MAX_PAGES_PER_REQUEST:
            request_params = next_params if next_url == url else None
            try:
                debug_print(f"[MSGraphPlugin] {operation_name} requesting {next_url} params={request_params}")
                response = requests.request(
                    method.upper(),
                    next_url,
                    headers=headers,
                    params=request_params,
                    json=json_body,
                    timeout=self.DEFAULT_TIMEOUT_SECONDS,
                )
            except requests.Timeout as ex:
                return self._build_graph_error(
                    operation_name,
                    scopes,
                    exception=ex,
                    fallback_message="Microsoft Graph request timed out.",
                )
            except RequestException as ex:
                return self._build_graph_error(
                    operation_name,
                    scopes,
                    exception=ex,
                    fallback_message="Microsoft Graph request could not be completed.",
                )

            pages_fetched += 1
            if response.status_code >= 400:
                return self._build_graph_error(operation_name, scopes, response=response)

            try:
                payload = response.json()
            except ValueError as ex:
                return self._build_graph_error(
                    operation_name,
                    scopes,
                    response=response,
                    exception=ex,
                    fallback_message="Microsoft Graph returned a non-JSON response.",
                )

            if paginate and isinstance(payload, dict) and isinstance(payload.get("value"), list):
                remaining_capacity = max(0, normalized_max_items - len(collected_items))
                page_items = payload.get("value", [])
                collected_items.extend(page_items[:remaining_capacity])
                last_next_link = payload.get("@odata.nextLink")
                if len(collected_items) >= normalized_max_items or not last_next_link:
                    return {
                        "operation": operation_name,
                        "count": len(collected_items),
                        "value": collected_items,
                        "next_link": last_next_link,
                        "truncated": bool(last_next_link) or len(page_items) > remaining_capacity,
                    }
                next_url = last_next_link
                next_params = {}
                continue

            return self._shape_graph_result(operation_name, payload, normalized_max_items)

        return {
            "operation": operation_name,
            "count": len(collected_items),
            "value": collected_items,
            "next_link": last_next_link,
            "truncated": bool(last_next_link),
        }

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Get information about the signed-in user.")
    def get_my_profile(self, select_fields: str = "") -> dict:
        params, headers = self._build_odata_params(
            top=1,
            select_fields=select_fields or "id,displayName,givenName,surname,mail,userPrincipalName,jobTitle,department,officeLocation,mobilePhone,businessPhones",
        )
        params.pop("$top", None)
        return self._perform_graph_request(
            "get_my_profile",
            "GET",
            "/v1.0/me",
            ["User.Read"],
            params=params,
            additional_headers=headers,
        )

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Get the signed-in user's Microsoft 365 mailbox timezone settings. Use this before answering timezone-sensitive date and time questions.")
    def get_my_timezone(self) -> dict:
        result = self._perform_graph_request(
            "get_my_timezone",
            "GET",
            "/v1.0/me/mailboxSettings",
            ["MailboxSettings.Read"],
        )
        if not isinstance(result, dict) or result.get("error"):
            return result

        working_hours = result.get("workingHours") if isinstance(result.get("workingHours"), dict) else {}
        return {
            "operation": "get_my_timezone",
            "time_zone": result.get("timeZone") or "",
            "date_format": result.get("dateFormat") or "",
            "time_format": result.get("timeFormat") or "",
            "language": result.get("language") or {},
            "working_hours_time_zone": working_hours.get("timeZone") or {},
            "message": (
                "Use the user's mailbox time_zone instead of assuming UTC when answering "
                "user-facing date and time questions."
            ),
        }

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Get upcoming calendar events for the signed-in user.")
    def get_my_events(
        self,
        top: int = 5,
        start_datetime: str = "",
        end_datetime: str = "",
        select_fields: str = "",
    ) -> dict:
        use_calendar_view = bool(start_datetime.strip() or end_datetime.strip())
        if use_calendar_view and not (start_datetime.strip() and end_datetime.strip()):
            return {
                "error": "invalid_parameters",
                "message": "Both start_datetime and end_datetime are required when filtering calendar events by time range.",
                "operation": "get_my_events",
            }

        params, headers = self._build_odata_params(
            top=top,
            select_fields=select_fields or "id,subject,start,end,location,organizer,isAllDay,webLink",
            order_by="start/dateTime",
            extra_params={
                "startDateTime": start_datetime.strip() or None,
                "endDateTime": end_datetime.strip() or None,
            },
        )
        path = "/v1.0/me/calendarView" if use_calendar_view else "/v1.0/me/events"
        return self._perform_graph_request(
            "get_my_events",
            "GET",
            path,
            ["Calendars.Read"],
            params=params,
            paginate=True,
            max_items=top,
            additional_headers=headers,
        )

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Get recent mail messages for the signed-in user.")
    def get_my_messages(
        self,
        top: int = 5,
        folder: str = "inbox",
        unread_only: bool = False,
        select_fields: str = "",
    ) -> dict:
        filter_query = "isRead eq false" if unread_only else ""
        params, headers = self._build_odata_params(
            top=top,
            select_fields=select_fields or "id,subject,from,receivedDateTime,isRead,importance,webLink",
            filter_query=filter_query,
            order_by="receivedDateTime desc",
        )
        normalized_folder = (folder or "").strip().strip("/")
        if normalized_folder:
            path = f"/v1.0/me/mailFolders/{quote(normalized_folder, safe='')}/messages"
        else:
            path = "/v1.0/me/messages"
        return self._perform_graph_request(
            "get_my_messages",
            "GET",
            path,
            ["Mail.Read"],
            params=params,
            paginate=True,
            max_items=top,
            additional_headers=headers,
        )

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Search directory users by name or email prefix.")
    def search_users(self, query: str, top: int = 5, select_fields: str = "") -> dict:
        normalized_query = (query or "").strip()
        if not normalized_query:
            return {
                "error": "invalid_parameters",
                "message": "query is required to search users.",
                "operation": "search_users",
            }

        safe_query = self._sanitize_filter_value(normalized_query)
        filter_query = (
            f"startswith(displayName,'{safe_query}') or "
            f"startswith(givenName,'{safe_query}') or "
            f"startswith(surname,'{safe_query}') or "
            f"startswith(mail,'{safe_query}') or "
            f"startswith(userPrincipalName,'{safe_query}')"
        )
        params, headers = self._build_odata_params(
            top=top,
            select_fields=select_fields or "id,displayName,mail,userPrincipalName,jobTitle,department,officeLocation",
            filter_query=filter_query,
            order_by="displayName",
        )
        return self._perform_graph_request(
            "search_users",
            "GET",
            "/v1.0/users",
            ["User.ReadBasic.All"],
            params=params,
            paginate=True,
            max_items=top,
            additional_headers=headers,
        )

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Get a directory user by exact email address or user principal name.")
    def get_user_by_email(self, email: str, select_fields: str = "") -> dict:
        normalized_email = (email or "").strip()
        if not normalized_email:
            return {
                "error": "invalid_parameters",
                "message": "email is required to look up a user.",
                "operation": "get_user_by_email",
            }

        safe_email = self._sanitize_filter_value(normalized_email)
        filter_query = f"mail eq '{safe_email}' or userPrincipalName eq '{safe_email}'"
        params, headers = self._build_odata_params(
            top=1,
            select_fields=select_fields or "id,displayName,mail,userPrincipalName,jobTitle,department,officeLocation",
            filter_query=filter_query,
        )
        result = self._perform_graph_request(
            "get_user_by_email",
            "GET",
            "/v1.0/users",
            ["User.ReadBasic.All"],
            params=params,
            paginate=False,
            max_items=1,
            additional_headers=headers,
        )
        if isinstance(result, dict) and isinstance(result.get("value"), list):
            result["value"] = result.get("value", [])[:1]
            result["count"] = len(result["value"])
        return result

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="List OneDrive items from the drive root or a child path for the signed-in user.")
    def list_drive_items(self, path: str = "", top: int = 10, select_fields: str = "") -> dict:
        normalized_path = (path or "").strip().strip("/")
        params, headers = self._build_odata_params(
            top=top,
            select_fields=select_fields or "id,name,webUrl,lastModifiedDateTime,size,folder,file,parentReference",
            order_by="name",
        )
        if normalized_path:
            graph_path = f"/v1.0/me/drive/root:/{quote(normalized_path, safe='/')}:/children"
        else:
            graph_path = "/v1.0/me/drive/root/children"
        return self._perform_graph_request(
            "list_drive_items",
            "GET",
            graph_path,
            ["Files.Read"],
            params=params,
            paginate=True,
            max_items=top,
            additional_headers=headers,
        )

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Get recent security alerts for the signed-in user.")
    def get_my_security_alerts(self, top: int = 5) -> dict:
        params, headers = self._build_odata_params(
            top=top,
            order_by="createdDateTime desc",
        )
        return self._perform_graph_request(
            "get_my_security_alerts",
            "GET",
            "/v1.0/security/alerts",
            ["SecurityEvents.Read.All"],
            params=params,
            paginate=True,
            max_items=top,
            additional_headers=headers,
        )
