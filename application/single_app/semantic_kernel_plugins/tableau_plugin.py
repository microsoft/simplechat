# tableau_plugin.py
"""Semantic Kernel plugin for read-only Tableau Server and Tableau Cloud actions."""

import logging
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from semantic_kernel.functions import kernel_function

from functions_appinsights import log_event
from functions_debug import debug_print
from functions_tableau_operations import (
    TABLEAU_AUTH_METHOD_PAT,
    TABLEAU_AUTH_METHOD_USERNAME_PASSWORD,
    TABLEAU_PLUGIN_TYPE,
    normalize_tableau_additional_fields,
    normalize_tableau_server_url,
)
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger

try:
    import tableauserverclient as TSC
except ImportError:
    TSC = None


class TableauPlugin(BasePlugin):
    """Read-only Tableau action plugin built on Tableau Server Client."""

    _SUPPORTED_COLLECTIONS = {
        "projects": "project",
        "workbooks": "workbook",
        "views": "view",
        "datasources": "datasource",
    }

    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        super().__init__(manifest)
        self.manifest = manifest or {}
        self._metadata = self.manifest.get("metadata", {}) or {}
        self._auth = self.manifest.get("auth", {}) if isinstance(self.manifest.get("auth"), dict) else {}
        self.auth_type = str(self._auth.get("type") or "key").strip() or "key"
        self._additional_fields = normalize_tableau_additional_fields(
            self.manifest.get("additionalFields", {}),
            auth_type=self.auth_type,
        )
        self.endpoint = normalize_tableau_server_url(
            self.manifest.get("endpoint")
            or self._additional_fields.get("server_url")
            or self._additional_fields.get("serverUrl")
            or ""
        )
        self.site_content_url = str(self._additional_fields.get("site_content_url") or "").strip().strip("/")
        self.auth_method = self._additional_fields.get("auth_method") or TABLEAU_AUTH_METHOD_PAT
        self.pat_name = str(self._additional_fields.get("pat_name") or self._auth.get("identity") or "").strip()
        self.page_size = int(self._additional_fields.get("page_size") or 100)
        self.max_results = int(self._additional_fields.get("max_results") or 100)
        self.timeout = int(self._additional_fields.get("timeout") or 30)
        self.use_server_version = bool(self._additional_fields.get("use_server_version", True))
        self._validate_configuration()

    @property
    def display_name(self) -> str:
        return "Tableau"

    @property
    def metadata(self) -> Dict[str, Any]:
        user_description = self._metadata.get(
            "description",
            "Read-only Tableau Server and Tableau Cloud content discovery action.",
        )
        description = (
            f"{user_description}\n\n"
            "This action uses Tableau Server Client to list and search Tableau projects, "
            "workbooks, views, and datasources. It does not publish, update, or delete Tableau content."
        )
        return {
            "name": self.manifest.get("name", "tableau"),
            "type": TABLEAU_PLUGIN_TYPE,
            "description": description,
            "methods": [
                {
                    "name": "search_tableau_content",
                    "description": "Search Tableau projects, workbooks, views, or datasources by name.",
                    "parameters": [
                        {"name": "content_type", "type": "str", "description": "projects, workbooks, views, or datasources.", "required": True},
                        {"name": "query", "type": "str", "description": "Optional search text.", "required": False},
                        {"name": "max_results", "type": "int", "description": "Optional result limit.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Matching Tableau content items."},
                },
                {
                    "name": "list_projects",
                    "description": "List Tableau projects visible to the configured credentials.",
                    "parameters": [
                        {"name": "query", "type": "str", "description": "Optional project name search text.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Tableau project results."},
                },
                {
                    "name": "list_workbooks",
                    "description": "List Tableau workbooks visible to the configured credentials.",
                    "parameters": [
                        {"name": "query", "type": "str", "description": "Optional workbook name search text.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Tableau workbook results."},
                },
                {
                    "name": "list_views",
                    "description": "List Tableau views visible to the configured credentials.",
                    "parameters": [
                        {"name": "query", "type": "str", "description": "Optional view name search text.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Tableau view results."},
                },
                {
                    "name": "list_datasources",
                    "description": "List Tableau datasources visible to the configured credentials.",
                    "parameters": [
                        {"name": "query", "type": "str", "description": "Optional datasource name search text.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Tableau datasource results."},
                },
                {
                    "name": "get_workbook_details",
                    "description": "Get a Tableau workbook and its views by workbook ID.",
                    "parameters": [
                        {"name": "workbook_id", "type": "str", "description": "Tableau workbook ID.", "required": True},
                    ],
                    "returns": {"type": "dict", "description": "Workbook metadata and view list."},
                },
            ],
        }

    def get_functions(self) -> List[str]:
        return [
            "search_tableau_content",
            "list_projects",
            "list_workbooks",
            "list_views",
            "list_datasources",
            "get_workbook_details",
        ]

    def _validate_configuration(self) -> None:
        parsed_endpoint = urlparse(self.endpoint)
        if parsed_endpoint.scheme != "https" or not parsed_endpoint.netloc:
            raise ValueError("Tableau action requires an HTTPS Tableau Server or Tableau Cloud URL.")

        if self.auth_type not in {"key", "username_password", "identity"}:
            raise ValueError("Tableau action supports auth.type values 'key', 'username_password', and 'identity'.")

        if self.auth_method == TABLEAU_AUTH_METHOD_PAT:
            if self.auth_type == "key" and not self._auth.get("key"):
                raise ValueError("Tableau personal access token authentication requires auth.key.")
            if self.auth_type == "key" and not self.pat_name:
                raise ValueError("Tableau personal access token authentication requires auth.identity or additionalFields.pat_name.")
        elif self.auth_method == TABLEAU_AUTH_METHOD_USERNAME_PASSWORD:
            if self.auth_type == "username_password" and (not self._auth.get("identity") or not self._auth.get("key")):
                raise ValueError("Tableau username/password authentication requires auth.identity and auth.key.")
        else:
            raise ValueError("Tableau action supports personal access token or username/password authentication.")

    def _require_tsc(self):
        if TSC is None:
            raise RuntimeError("The tableauserverclient package is not installed.")
        return TSC

    def _get_tableau_auth(self):
        tsc = self._require_tsc()
        if self.auth_method == TABLEAU_AUTH_METHOD_USERNAME_PASSWORD:
            return tsc.TableauAuth(
                str(self._auth.get("identity") or ""),
                str(self._auth.get("key") or ""),
                site_id=self.site_content_url,
            )
        return tsc.PersonalAccessTokenAuth(
            self.pat_name,
            str(self._auth.get("key") or ""),
            site_id=self.site_content_url,
        )

    def _create_server(self):
        tsc = self._require_tsc()
        debug_print(
            f"[TableauPlugin] Creating Tableau server client endpoint={self.endpoint} "
            f"site_content_url={self.site_content_url or '<default>'} "
            f"auth_method={self.auth_method} timeout={self.timeout} "
            f"use_server_version={self.use_server_version}"
        )
        server = tsc.Server(self.endpoint, use_server_version=self.use_server_version)
        if hasattr(server, "add_http_options"):
            try:
                server.add_http_options({"timeout": self.timeout})
            except Exception:
                log_event(
                    "[TableauPlugin] Unable to apply Tableau HTTP timeout option.",
                    extra={"endpoint": self.endpoint, "plugin_name": self.manifest.get("name")},
                    level=logging.DEBUG,
                    debug_only=True,
                )
        return server

    def _build_request_options(self):
        tsc = self._require_tsc()
        try:
            return tsc.RequestOptions(pagesize=self.page_size)
        except TypeError:
            request_options = tsc.RequestOptions()
            if hasattr(request_options, "pagesize"):
                request_options.pagesize = self.page_size
            elif hasattr(request_options, "page_size"):
                request_options.page_size = self.page_size
            return request_options

    def _iter_collection(self, collection: Any) -> Iterable[Any]:
        tsc = self._require_tsc()
        request_options = self._build_request_options()
        if hasattr(tsc, "Pager"):
            return tsc.Pager(collection, request_options)
        items, _pagination = collection.get(request_options)
        return items

    def _item_to_dict(self, item: Any, content_type: str) -> Dict[str, Any]:
        field_names = [
            "id",
            "name",
            "content_url",
            "webpage_url",
            "project_id",
            "project_name",
            "owner_id",
            "created_at",
            "updated_at",
            "description",
            "size",
            "view_count",
            "sheet_type",
            "workbook_id",
        ]
        payload = {"content_type": content_type}
        for field_name in field_names:
            value = getattr(item, field_name, None)
            if value not in [None, ""]:
                payload[field_name] = str(value) if field_name.endswith("_at") else value
        return payload

    def _matches_query(self, item: Any, query: str) -> bool:
        normalized_query = str(query or "").strip().lower()
        if not normalized_query:
            return True
        searchable_values = [
            getattr(item, "name", ""),
            getattr(item, "content_url", ""),
            getattr(item, "project_name", ""),
            getattr(item, "description", ""),
        ]
        return any(normalized_query in str(value or "").lower() for value in searchable_values)

    def _effective_max_results(self, max_results: int = 0) -> int:
        try:
            requested_limit = int(max_results or 0)
        except (TypeError, ValueError):
            requested_limit = 0
        if requested_limit > 0:
            return min(requested_limit, self.max_results)
        return self.max_results

    def _error_response(self, message: str, error_type: str = "validation", **extra: Any) -> Dict[str, Any]:
        payload = {
            "success": False,
            "error": message,
            "error_type": error_type,
        }
        payload.update(extra)
        return payload

    def _list_content(self, collection_name: str, query: str = "", max_results: int = 0) -> Dict[str, Any]:
        if collection_name not in self._SUPPORTED_COLLECTIONS:
            return self._error_response(
                "Unsupported Tableau content type. Use projects, workbooks, views, or datasources.",
                error_type="validation",
                content_type=collection_name,
            )

        limit = self._effective_max_results(max_results)
        items: List[Dict[str, Any]] = []
        try:
            debug_print(
                f"[TableauPlugin] Listing Tableau content content_type={collection_name} "
                f"query_present={bool(str(query or '').strip())} limit={limit} "
                f"plugin_name={self.manifest.get('name')}"
            )
            server = self._create_server()
            tableau_auth = self._get_tableau_auth()
            debug_print(
                f"[TableauPlugin] Signing in to Tableau endpoint={self.endpoint} "
                f"site_content_url={self.site_content_url or '<default>'} auth_method={self.auth_method}"
            )
            with server.auth.sign_in(tableau_auth):
                debug_print(f"[TableauPlugin] Tableau sign-in succeeded; reading {collection_name}.")
                collection = getattr(server, collection_name)
                for item in self._iter_collection(collection):
                    if not self._matches_query(item, query):
                        continue
                    items.append(self._item_to_dict(item, self._SUPPORTED_COLLECTIONS[collection_name]))
                    if len(items) >= limit:
                        break
            debug_print(
                f"[TableauPlugin] Tableau content listing succeeded content_type={collection_name} "
                f"count={len(items)} has_query={bool(str(query or '').strip())}"
            )
            return {
                "success": True,
                "content_type": collection_name,
                "query": str(query or ""),
                "items": items,
                "count": len(items),
                "max_results": limit,
            }
        except Exception as exc:
            debug_print(
                f"[TableauPlugin] Tableau content listing failed content_type={collection_name} "
                f"endpoint={self.endpoint} site_content_url={self.site_content_url or '<default>'} "
                f"exception_type={type(exc).__name__} message={exc}"
            )
            log_event(
                f"[TableauPlugin] Tableau content listing failed: {exc}",
                extra={
                    "endpoint": self.endpoint,
                    "content_type": collection_name,
                    "plugin_name": self.manifest.get("name"),
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return self._error_response("Tableau content listing failed.", error_type="tableau", content_type=collection_name)

    @plugin_function_logger("TableauPlugin")
    @kernel_function(description="Search Tableau projects, workbooks, views, or datasources by name.", name="search_tableau_content")
    def search_tableau_content(self, content_type: str, query: str = "", max_results: int = 0) -> Dict[str, Any]:
        normalized_type = str(content_type or "").strip().lower()
        aliases = {
            "project": "projects",
            "workbook": "workbooks",
            "view": "views",
            "datasource": "datasources",
            "data_source": "datasources",
            "data_sources": "datasources",
        }
        return self._list_content(aliases.get(normalized_type, normalized_type), query=query, max_results=max_results)

    @plugin_function_logger("TableauPlugin")
    @kernel_function(description="List Tableau projects visible to the configured credentials.", name="list_projects")
    def list_projects(self, query: str = "") -> Dict[str, Any]:
        return self._list_content("projects", query=query)

    @plugin_function_logger("TableauPlugin")
    @kernel_function(description="List Tableau workbooks visible to the configured credentials.", name="list_workbooks")
    def list_workbooks(self, query: str = "") -> Dict[str, Any]:
        return self._list_content("workbooks", query=query)

    @plugin_function_logger("TableauPlugin")
    @kernel_function(description="List Tableau views visible to the configured credentials.", name="list_views")
    def list_views(self, query: str = "") -> Dict[str, Any]:
        return self._list_content("views", query=query)

    @plugin_function_logger("TableauPlugin")
    @kernel_function(description="List Tableau datasources visible to the configured credentials.", name="list_datasources")
    def list_datasources(self, query: str = "") -> Dict[str, Any]:
        return self._list_content("datasources", query=query)

    @plugin_function_logger("TableauPlugin")
    @kernel_function(description="Get a Tableau workbook and its views by workbook ID.", name="get_workbook_details")
    def get_workbook_details(self, workbook_id: str) -> Dict[str, Any]:
        normalized_workbook_id = str(workbook_id or "").strip()
        if not normalized_workbook_id:
            return self._error_response("Workbook ID is required.", error_type="validation")

        try:
            debug_print(
                f"[TableauPlugin] Getting workbook details workbook_id_present={bool(normalized_workbook_id)} "
                f"endpoint={self.endpoint} site_content_url={self.site_content_url or '<default>'}"
            )
            server = self._create_server()
            tableau_auth = self._get_tableau_auth()
            debug_print(f"[TableauPlugin] Signing in to Tableau for workbook details endpoint={self.endpoint}.")
            with server.auth.sign_in(tableau_auth):
                debug_print("[TableauPlugin] Tableau sign-in succeeded; loading workbook details.")
                workbook = server.workbooks.get_by_id(normalized_workbook_id)
                if hasattr(server.workbooks, "populate_views"):
                    server.workbooks.populate_views(workbook)
                views = [self._item_to_dict(view, "view") for view in getattr(workbook, "views", []) or []]
            debug_print(
                f"[TableauPlugin] Workbook details lookup succeeded workbook_id={normalized_workbook_id} "
                f"view_count={len(views)}"
            )
            return {
                "success": True,
                "workbook": self._item_to_dict(workbook, "workbook"),
                "views": views,
                "view_count": len(views),
            }
        except Exception as exc:
            debug_print(
                f"[TableauPlugin] Workbook details lookup failed workbook_id={normalized_workbook_id} "
                f"endpoint={self.endpoint} exception_type={type(exc).__name__} message={exc}"
            )
            log_event(
                f"[TableauPlugin] Tableau workbook details lookup failed: {exc}",
                extra={
                    "endpoint": self.endpoint,
                    "workbook_id": normalized_workbook_id,
                    "plugin_name": self.manifest.get("name"),
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return self._error_response("Tableau workbook details lookup failed.", error_type="tableau", workbook_id=normalized_workbook_id)