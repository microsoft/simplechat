# functions_m365_retrieval.py
"""Delegated file discovery, retrieval, and conversation-scoped evidence operations."""

import hashlib
import html
import json
import re
import time
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from functools import wraps
from inspect import isawaitable
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote, unquote, urlsplit

from semantic_kernel.functions import kernel_function
from semantic_kernel.functions.kernel_plugin import KernelPlugin

from functions_conversation_memory import (
    ConversationMemoryError,
    ConversationMemoryStore,
    EvidenceChunk,
    EvidenceLocation,
    EvidenceSource,
    MemoryConflictError,
    MemoryContext,
    MemoryAuthorizationError,
    MemoryLimitError,
    MemoryStateError,
    MemoryUnavailableError,
)
from functions_m365_approvals import M365ApprovalRequired, M365PolicyError
from functions_m365_extraction import (
    M365_EVIDENCE_CHUNK_CHARS,
    M365_FILE_MIME_TYPES,
    extract_m365_file,
    iter_m365_evidence_chunks,
    m365_file_format,
)
from functions_m365_operations import (
    M365_FILE_SOURCES,
    get_m365_action_definition,
    get_m365_enabled_function_names,
    get_m365_function_definitions,
    normalize_m365_action_config,
)
from functions_m365_transport import (
    M365_FILE_HARD_MAX_BYTES,
    M365ProviderError,
    M365Transport,
    authorize_m365_capability,
    authorize_m365_publication,
    authorize_m365_source,
    get_m365_context,
    log_m365_failure,
)
from semantic_kernel_plugins.base_plugin import BasePlugin


M365_FAST_DOWNLOADS = 3
M365_FAST_FILE_BYTES = 25 * 1024 * 1024
M365_FAST_CONTEXT_TOKENS = 12000
M365_SEARCH_PAGE_SIZE = 25
M365_SEARCH_MAX_OFFSET = 1000
M365_HARD_DOWNLOADS_PER_REQUEST = 100
M365_MAX_REQUEST_OPERATIONS = 100
M365_COPILOT_SKU_ID = "639dec6b-bb19-468b-871c-c5c441c4b0cb"
M365_COPILOT_SEARCH_PLAN_ID = "931e4a88-a67f-48b5-814f-16a5f1e6028d"
_ITEM_SELECT = "id,name,webUrl,size,file,folder,remoteItem,parentReference,eTag,cTag,lastModifiedDateTime,sharepointIds"
_SEARCH_FIELDS = [
    "id", "name", "webUrl", "size", "file", "folder", "parentReference",
    "eTag", "cTag", "lastModifiedDateTime", "sharepointIds",
]
_memory_resolver = None
_analysis_callback = None
_request_run_resolver = None
_model_budget_resolver = None
_token_counter = None
_UNSET_CALLBACK = object()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _graph_id(value: Any, name: str) -> str:
    if (
        not isinstance(value, str) or len(value) > 512
        or not re.fullmatch(r"[A-Za-z0-9_!.-]+", value)
        or value in (".", "..")
    ):
        raise M365ProviderError("invalid_file_identity", f"A valid canonical Microsoft Graph {name} is required.")
    return value


def _positive_integer(value: Any, name: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise M365ProviderError("invalid_parameters", f"{name} must be an integer from 1 to {maximum}.")
    return value


def _object(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise M365ProviderError("invalid_response", "Microsoft 365 returned malformed resource metadata.")
    return value


def _query_text(query: Any) -> str:
    if not isinstance(query, str) or not query.strip() or len(query) > 1500 or re.search(r"[\x00-\x1f\x7f]", query):
        raise M365ProviderError("invalid_query", "Use a natural-language query between 1 and 1,500 characters.")
    return query.strip()


def _literal_kql_query(query: str) -> str:
    # Tool arguments are natural language, never executable KQL or a filterExpression.
    words = re.findall(r"\w+(?:[-.@]\w+)*", _query_text(query), flags=re.UNICODE)
    if not words:
        raise M365ProviderError("invalid_query", "The search needs at least one word.")
    return " ".join(f'"{word}"' for word in words)


def _snippet_text(value: Any) -> str:
    return html.unescape(re.sub(r"<[^>]*>", "", value)) if isinstance(value, str) else ""


def _source_label(source: str) -> str:
    return "SPO" if source == "spo" else "OneDrive"


def _search_result(source: str, provider: str, *, fallback_reason: Optional[str] = None) -> Dict[str, Any]:
    return {
        "status": "ok",
        "source": source,
        "source_label": _source_label(source),
        "provider": provider,
        "fallback_reason": fallback_reason,
        "results": [],
        "errors": [],
        "coverage": {
            "complete": False,
            "kind": "search_excerpts",
            "files_returned": 0,
            "files_inspected": 0,
            "excluded_other_source": 0,
            "discovery_complete": False,
            "full_file_reads": 0,
        },
        "trust": "untrusted_source_data",
    }


def _capture_excerpt_version(file_info):
    # An index excerpt can lag the live file's ETag; its retained text is the verifiable snapshot.
    observed_metadata = file_info["captured_version"]
    encoded = json.dumps(file_info["excerpts"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    file_info["captured_version"] = {
        "kind": "index_excerpts",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "source_version_verified": False,
        "observed_metadata": observed_metadata,
    }


def get_m365_license_eligibility(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Recognize the documented Copilot SKU and enabled Intelligent Search service plan."""
    licenses, plans = profile.get("assignedLicenses"), profile.get("assignedPlans")
    if not isinstance(licenses, list) or not isinstance(plans, list):
        return {"verified": False, "reason": "license_unknown"}
    matching = [
        license_info for license_info in licenses
        if isinstance(license_info, dict) and str(license_info.get("skuId", "")).lower() == M365_COPILOT_SKU_ID
    ]
    if not matching:
        return {"verified": False, "reason": "copilot_license_not_assigned"}
    if not any(
        M365_COPILOT_SEARCH_PLAN_ID not in [
            str(plan).lower() for plan in license_info.get("disabledPlans", [])
        ]
        for license_info in matching
        if isinstance(license_info.get("disabledPlans", []), list)
    ):
        return {"verified": False, "reason": "copilot_search_disabled"}
    enabled = any(
        isinstance(plan, dict)
        and str(plan.get("servicePlanId", "")).lower() == M365_COPILOT_SEARCH_PLAN_ID
        and plan.get("capabilityStatus") == "Enabled"
        for plan in plans
    )
    return {"verified": enabled, "reason": None if enabled else "copilot_search_not_verified"}


def select_m365_retrieval_provider(transport: M365Transport):
    if transport.cloud.retrieval_provider == "graph":
        return "graph", "configured_graph"
    if not transport.cloud.supports_copilot_retrieval:
        return "graph", "copilot_retrieval_unsupported_in_cloud"
    profile = transport.request_json(
        "GET", "/me", ["User.Read"],
        params={"$select": "id,assignedLicenses,assignedPlans"},
    )
    context = get_m365_context()
    if profile.get("id") != context.data_user_id:
        raise M365ProviderError("principal_mismatch", "Microsoft 365 license information did not match the authorized data user.")
    eligibility = get_m365_license_eligibility(profile)
    if eligibility["verified"]:
        return "copilot_retrieval", None
    return "graph", eligibility["reason"]


class M365FileProvider:
    """A per-operation provider. Metadata is never cached across principals or conversations."""

    def __init__(self, transport: M365Transport):
        if transport.source not in M365_FILE_SOURCES:
            raise M365ProviderError("invalid_source", "File retrieval requires a OneDrive or SPO action.")
        self.transport = transport
        self.source = transport.source
        self._drives = {}

    def _raw_search(self, query: str, *, offset: int = 0, top: int = M365_SEARCH_PAGE_SIZE):
        payload = self.transport.request_json(
            "POST", "/search/query", ["Files.Read.All"],
            json_body={
                "requests": [{
                    "entityTypes": ["driveItem"],
                    "query": {"queryString": query},
                    "from": offset,
                    "size": top,
                    "fields": _SEARCH_FIELDS,
                }],
            },
        )
        values = payload.get("value")
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
            raise M365ProviderError("invalid_search_response", "Microsoft Graph returned an invalid search response.")
        containers = values[0].get("hitsContainers")
        if not isinstance(containers, list):
            raise M365ProviderError("invalid_search_response", "Microsoft Graph returned an invalid search response.")
        hits, more, total = [], False, 0
        for container in containers:
            if not isinstance(container, dict) or not isinstance(container.get("hits", []), list):
                raise M365ProviderError("invalid_search_response", "Microsoft Graph returned an invalid search result page.")
            hits.extend(container.get("hits", []))
            more = more or bool(container.get("moreResultsAvailable"))
            count = container.get("total", 0)
            if type(count) is int and count >= 0:
                total += count
        if len(hits) > top or (more and not hits):
            raise M365ProviderError("invalid_search_response", "Microsoft Graph returned inconsistent search pagination.")
        return hits, more, total

    def _drive(self, drive_id: str):
        drive_id = _graph_id(drive_id, "drive ID")
        if drive_id not in self._drives:
            result = self.transport.request_json(
                "GET", f"/drives/{quote(drive_id, safe='')}", ["Files.Read.All"],
                params={"$select": "id,driveType,webUrl"},
            )
            if result.get("id") != drive_id:
                raise M365ProviderError("invalid_file_identity", "Microsoft Graph returned a different drive.")
            self._drives[drive_id] = result
        return self._drives[drive_id]

    def _classify_item(self, item: Dict[str, Any]):
        parent = item.get("parentReference")
        if not isinstance(parent, dict):
            raise M365ProviderError("invalid_file_identity", "Microsoft Graph did not return the file's canonical drive.")
        drive_id = _graph_id(parent.get("driveId"), "drive ID")
        drive = self._drive(drive_id)
        drive_type = drive.get("driveType")
        if drive_type == "business":
            return "onedrive"
        if drive_type == "documentLibrary":
            return "spo"
        raise M365ProviderError("unsupported_drive_type", "Only organizational OneDrive and SPO document libraries are supported.")

    def _load_item(self, drive_id: str, item_id: str, *, remote_depth: int = 0):
        drive_id = _graph_id(drive_id, "drive ID")
        item_id = _graph_id(item_id, "item ID")
        item = self.transport.request_json(
            "GET", f"/drives/{quote(drive_id, safe='')}/items/{quote(item_id, safe='')}",
            ["Files.Read.All"], params={"$select": _ITEM_SELECT},
        )
        if item.get("id") != item_id:
            raise M365ProviderError("invalid_file_identity", "Microsoft Graph returned a different file.")
        parent = item.get("parentReference")
        if not isinstance(parent, dict) or parent.get("driveId") != drive_id:
            raise M365ProviderError("invalid_file_identity", "The returned file does not belong to the requested drive.")
        remote = item.get("remoteItem")
        if isinstance(remote, dict):
            if remote_depth:
                raise M365ProviderError("unsupported_shortcut", "This file shortcut cannot be resolved safely.")
            remote_parent = _object(remote.get("parentReference"))
            return self._load_item(remote_parent.get("driveId"), remote.get("id"), remote_depth=remote_depth + 1)
        return item

    def _item_from_search_hit(self, hit: Dict[str, Any]):
        if not isinstance(hit, dict) or not isinstance(hit.get("resource"), dict):
            raise M365ProviderError("invalid_search_hit", "Microsoft Graph returned an invalid file search hit.")
        resource = hit["resource"]
        if resource.get("@odata.type", "#microsoft.graph.driveItem") not in ("#microsoft.graph.driveItem", "microsoft.graph.driveItem"):
            raise M365ProviderError("unsupported_resource", "This search result is not a document-library file.")
        parent = _object(resource.get("parentReference"))
        if resource.get("id") and parent.get("driveId"):
            return self._load_item(parent["driveId"], resource["id"])
        ids = _object(resource.get("sharepointIds") or parent.get("sharepointIds"))
        site_id = parent.get("siteId")
        if site_id and ids.get("listId") and ids.get("listItemId"):
            path = (
                f"/sites/{quote(str(site_id), safe='')}/lists/{quote(str(ids['listId']), safe='')}"
                f"/items/{quote(str(ids['listItemId']), safe='')}/driveItem"
            )
            return self.transport.request_json(
                "GET", path, ["Files.Read.All"], params={"$select": _ITEM_SELECT},
            )
        raise M365ProviderError("file_identity_unavailable", "The file search result did not include a resolvable canonical identity.")

    def _canonical_item_url(self, item):
        try:
            return self.transport.cloud.canonical_web_url(item.get("webUrl", ""))
        except M365ProviderError as exc:
            if exc.code != "invalid_source_url":
                raise
        parent = _object(item.get("parentReference"))
        drive_id = _graph_id(parent.get("driveId"), "drive ID")
        parent_path = parent.get("path")
        name = item.get("name")
        if not isinstance(parent_path, str) or not isinstance(name, str) or "/" in name or "\\" in name:
            raise M365ProviderError("canonical_url_unavailable", "The file's canonical path could not be resolved from Microsoft Graph metadata.")
        prefixes = (f"/drives/{drive_id}/root:", "/drive/root:", "/me/drive/root:")
        prefix = next((value for value in prefixes if parent_path == value or parent_path.startswith(f"{value}/")), None)
        if prefix is None:
            raise M365ProviderError("canonical_url_unavailable", "The file's canonical path did not match its Graph drive.")
        drive_root = self.transport.cloud.canonical_web_url(self._drive(drive_id).get("webUrl", "")).rstrip("/")
        relative_parent = unquote(parent_path[len(prefix):]).strip("/")
        relative_path = f"{relative_parent}/{name}" if relative_parent else name
        return self.transport.cloud.canonical_web_url(f"{drive_root}/{quote(relative_path, safe='/')}")

    def _find_by_url(self, web_url: str, *, folder: bool = False):
        canonical = self.transport.cloud.canonical_web_url(web_url).rstrip("/")
        hits, more, _ = self._raw_search(
            f'Path:"{canonical}" AND IsDocument:{0 if folder else 1}',
        )
        matches = {}
        for hit in hits:
            resource = hit.get("resource") if isinstance(hit, dict) else None
            if not isinstance(resource, dict):
                raise M365ProviderError("invalid_search_hit", "Microsoft Graph returned an invalid scoped search hit.")
            item = None
            try:
                url = self.transport.cloud.canonical_web_url(resource.get("webUrl", "")).rstrip("/")
            except M365ProviderError as exc:
                if exc.code != "invalid_source_url":
                    raise
                item = self._item_from_search_hit(hit)
                url = self._canonical_item_url(item).rstrip("/")
            if url != canonical:
                continue
            if item is None:
                item = self._item_from_search_hit(hit)
            item_url = self._canonical_item_url(item).rstrip("/")
            if item_url == canonical:
                identity = (item.get("parentReference", {}).get("driveId"), item.get("id"))
                matches[identity] = item
        if more or len(matches) > 1:
            raise M365ProviderError("ambiguous_file_scope", "Use a specific canonical file or folder identity; this scope was ambiguous.")
        if not matches:
            raise M365ProviderError("scope_not_found", "The requested file or folder was not found in the data user's accessible search results.")
        item = next(iter(matches.values()))
        if folder and not isinstance(item.get("folder"), dict):
            raise M365ProviderError("invalid_folder", "The requested scope is not a folder.")
        return item

    def resolve_folder(self, folder: str = "") -> Optional[str]:
        if not isinstance(folder, str) or len(folder) > 4096:
            raise M365ProviderError("invalid_folder", "Use a specific canonical folder URL or OneDrive path.")
        if not folder:
            return None
        if folder.startswith("https://"):
            item = self._find_by_url(folder, folder=True)
        elif self.source == "onedrive":
            path = folder.strip().strip("/")
            decoded = unquote(unquote(path))
            if (
                not path or "://" in path or "\\" in decoded
                or any(segment in (".", "..") for segment in decoded.split("/"))
                or re.search(r'[\x00-\x1f\x7f?#"]', decoded)
            ):
                raise M365ProviderError("invalid_folder", "Use an exact path inside your OneDrive.")
            item = self.transport.request_json(
                "GET", f"/me/drive/root:/{quote(decoded, safe='/')}",
                ["Files.Read.All"], params={"$select": _ITEM_SELECT},
            )
            if not isinstance(item.get("folder"), dict):
                raise M365ProviderError("invalid_folder", "The requested OneDrive path is not a folder.")
        else:
            raise M365ProviderError("folder_clarification_required", "Specify the exact SPO folder URL; a folder name alone can be ambiguous.")
        if self._classify_item(item) != self.source:
            raise M365ProviderError("source_not_allowed", "This folder belongs to a different Microsoft 365 source.")
        return self._canonical_item_url(item).rstrip("/")

    def _normalized_file(self, item: Dict[str, Any], provider: str, *, folder_url: Optional[str] = None):
        if self._classify_item(item) != self.source:
            return None
        if not isinstance(item.get("file"), dict) or isinstance(item.get("folder"), dict):
            raise M365ProviderError("unsupported_resource", "Only files in document libraries are supported, not pages, lists, or folders.")
        web_url = self._canonical_item_url(item)
        if folder_url:
            parent = urlsplit(folder_url)
            current = urlsplit(web_url)
            if parent.netloc != current.netloc or not unquote(current.path).startswith(f"{unquote(parent.path).rstrip('/')}/"):
                raise M365ProviderError("scope_mismatch", "Microsoft 365 returned a file outside the requested folder.")
        name = item.get("name")
        if not isinstance(name, str) or not name or len(name) > 512:
            raise M365ProviderError("invalid_file_metadata", "Microsoft Graph returned invalid file metadata.")
        if Path(name).suffix.lower() == ".aspx":
            raise M365ProviderError("unsupported_resource", "SharePoint pages are not supported by this file action.")
        m365_file_format(name, item["file"].get("mimeType") or "")
        parent = item["parentReference"]
        drive_id, item_id = _graph_id(parent["driveId"], "drive ID"), _graph_id(item.get("id"), "item ID")
        ids = _object(item.get("sharepointIds") or parent.get("sharepointIds"))
        size = item.get("size")
        if size is not None and (type(size) is not int or size < 0):
            raise M365ProviderError("invalid_file_metadata", "Microsoft Graph returned an invalid file size.")
        return {
            "source": self.source,
            "source_label": _source_label(self.source),
            "provider": provider,
            "source_id": f"{drive_id}:{item_id}",
            "canonical_id": {
                "drive_id": drive_id, "item_id": item_id,
                "site_id": parent.get("siteId"),
                "list_id": ids.get("listId"),
                "list_item_id": ids.get("listItemId"),
            },
            "drive_id": drive_id,
            "item_id": item_id,
            "web_url": web_url,
            "url": web_url,
            "display_name": name,
            "mime_type": item["file"].get("mimeType") or "",
            "size_bytes": size,
            "captured_version": {
                "etag": item.get("eTag"),
                "ctag": item.get("cTag"),
                "last_modified": item.get("lastModifiedDateTime"),
            },
            "captured_at": _utc_now_iso(),
            "excerpts": [],
            "coverage": {"complete": False, "kind": "metadata"},
        }

    def resolve_file(self, drive_id: str = "", item_id: str = "", web_url: str = ""):
        if not all(isinstance(value, str) for value in (drive_id, item_id, web_url)):
            raise M365ProviderError("invalid_file_identity", "Canonical file IDs and URLs must be strings.")
        if bool(drive_id) != bool(item_id) or (not drive_id and not web_url):
            raise M365ProviderError("invalid_file_identity", "Provide both canonical drive/item IDs, or a canonical file URL.")
        item = self._load_item(drive_id, item_id) if drive_id else self._find_by_url(web_url)
        result = self._normalized_file(item, "graph")
        if result is None:
            raise M365ProviderError("source_not_allowed", "This file belongs to a different Microsoft 365 source.")
        if web_url and self.transport.cloud.canonical_web_url(web_url) != result["web_url"]:
            raise M365ProviderError("file_identity_mismatch", "The canonical file URL does not match the requested file IDs.")
        return result

    def discover_page(self, query: str, *, folder_url: Optional[str] = None, offset: int = 0, top: int = M365_SEARCH_PAGE_SIZE):
        _positive_integer(top, "top", M365_SEARCH_PAGE_SIZE)
        if type(offset) is not int or not 0 <= offset <= M365_SEARCH_MAX_OFFSET:
            raise M365ProviderError("search_limit", "The requested discovery offset exceeds the bounded search window.")
        kql = f"({_literal_kql_query(query)}) AND IsDocument:1"
        if folder_url:
            canonical_folder = self.transport.cloud.canonical_web_url(folder_url).rstrip("/")
            kql += f' AND Path:"{canonical_folder}"'
        hits, more, total = self._raw_search(kql, offset=offset, top=top)
        result = _search_result(self.source, "graph")
        for hit in hits:
            result["coverage"]["files_inspected"] += 1
            try:
                item = self._item_from_search_hit(hit)
                normalized = self._normalized_file(item, "graph", folder_url=folder_url)
                if normalized is None:
                    result["coverage"]["excluded_other_source"] += 1
                    continue
                snippet = _snippet_text(hit.get("summary"))
                if snippet:
                    normalized["excerpts"] = [{"text": snippet, "location": {}, "kind": "search_snippet"}]
                    normalized["coverage"]["kind"] = "search_snippet"
                    _capture_excerpt_version(normalized)
                result["results"].append(normalized)
            except M365ProviderError as exc:
                if exc.status_code == 401:
                    raise
                result["errors"].append(exc.as_dict())
        result["status"] = "partial" if result["errors"] else "ok"
        result["coverage"].update({
            "files_returned": len(result["results"]),
            "discovery_complete": not more and not result["errors"],
            "provider_candidate_total": total,
        })
        result["next_offset"] = offset + len(hits) if more else None
        if result["next_offset"] is not None and result["next_offset"] > M365_SEARCH_MAX_OFFSET:
            result["status"] = "partial"
            result["coverage"]["hard_limit"] = "search_window"
            result["coverage"]["continuation_unavailable"] = True
            result["next_offset"] = None
        result["ranking"] = "ranked_search"
        return result

    def _copilot_search(self, query: str, folder_url: Optional[str], top: int):
        extensions = sorted(suffix.lstrip(".") for suffix in M365_FILE_MIME_TYPES)
        filters = [f"({' OR '.join(f'FileExtension:{extension}' for extension in extensions)})"]
        if folder_url:
            filters.append(f'Path:"{folder_url}"')
        try:
            payload = self.transport.request_json(
                "POST", "/copilot/retrieval", ["Files.Read.All", "Sites.Read.All"],
                json_body={
                    "queryString": query,
                    "dataSource": "oneDriveBusiness" if self.source == "onedrive" else "sharePoint",
                    "filterExpression": " AND ".join(filters),
                    "resourceMetadata": ["title", "author"],
                    "maximumNumberOfResults": top,
                },
            )
        except M365ProviderError as exc:
            exc.details["provider"] = "copilot_retrieval"
            raise
        hits = payload.get("retrievalHits")
        if not isinstance(hits, list) or len(hits) > top:
            raise M365ProviderError("invalid_retrieval_response", "Copilot Retrieval returned an invalid response.")
        result = _search_result(self.source, "copilot_retrieval")
        for hit in hits:
            result["coverage"]["files_inspected"] += 1
            try:
                if not isinstance(hit, dict) or hit.get("resourceType") not in ("listItem", "driveItem"):
                    raise M365ProviderError("unsupported_resource", "Copilot Retrieval returned an unsupported resource.")
                item = self._find_by_url(hit.get("webUrl", ""))
                normalized = self._normalized_file(item, "copilot_retrieval", folder_url=folder_url)
                if normalized is None:
                    result["coverage"]["excluded_other_source"] += 1
                    continue
                m365_file_format(normalized["display_name"], normalized["mime_type"])
                extracts = hit.get("extracts")
                if not isinstance(extracts, list):
                    raise M365ProviderError("invalid_retrieval_response", "Copilot Retrieval returned invalid file excerpts.")
                for extract in extracts:
                    if not isinstance(extract, dict) or not isinstance(extract.get("text"), str):
                        raise M365ProviderError("invalid_retrieval_response", "Copilot Retrieval returned an invalid text excerpt.")
                    location = {}
                    if type(extract.get("pageNumber")) is int and extract["pageNumber"] > 0:
                        location["pages"] = [extract["pageNumber"]]
                    normalized["excerpts"].append({
                        "text": extract["text"],
                        "location": location,
                        "kind": "retrieval_excerpt",
                    })
                label = hit.get("sensitivityLabel")
                if isinstance(label, dict):
                    normalized["sensitivity"] = {
                        key: label[key] for key in ("sensitivityLabelId", "displayName")
                        if isinstance(label.get(key), str)
                    }
                normalized["coverage"].update({
                    "kind": "retrieval_excerpts", "excerpt_count": len(normalized["excerpts"]),
                })
                _capture_excerpt_version(normalized)
                result["results"].append(normalized)
            except M365ProviderError as exc:
                if exc.status_code == 401:
                    raise
                result["errors"].append(exc.as_dict())
        result["status"] = "partial" if result["errors"] else "ok"
        result["ranking"] = "unordered_retrieval_hits"
        result["coverage"].update({
            "files_returned": len(result["results"]),
            "discovery_complete": False,
            "exhaustive_search": False,
            "result_limit_reached": len(hits) == top,
        })
        return result

    def search(self, query: str, folder: str = "", top: int = 10):
        query = _query_text(query)
        _positive_integer(top, "top", M365_SEARCH_PAGE_SIZE)
        folder_url = self.resolve_folder(folder)
        provider, reason = select_m365_retrieval_provider(self.transport)
        if provider == "copilot_retrieval":
            try:
                return self._copilot_search(query, folder_url, top)
            except M365ProviderError as exc:
                if exc.details.get("api_unsupported") is not True:
                    raise
                reason = "copilot_retrieval_api_unsupported"
        result = self.discover_page(query, folder_url=folder_url, top=top)
        result["fallback_reason"] = reason
        return result


def configure_m365_retrieval(
    *, memory_resolver=_UNSET_CALLBACK, request_run_resolver=_UNSET_CALLBACK,
    model_budget_resolver=_UNSET_CALLBACK, token_counter=_UNSET_CALLBACK,
    analysis_callback=_UNSET_CALLBACK,
):
    """Update supplied callbacks only; omission preserves registration and explicit None clears it."""
    global _memory_resolver, _request_run_resolver, _model_budget_resolver, _token_counter
    global _analysis_callback
    for callback in (memory_resolver, request_run_resolver, model_budget_resolver, token_counter, analysis_callback):
        if callback is not _UNSET_CALLBACK and callback is not None and not callable(callback):
            raise TypeError("Microsoft 365 retrieval dependencies must be callbacks.")
    if memory_resolver is not _UNSET_CALLBACK:
        _memory_resolver = memory_resolver
    if request_run_resolver is not _UNSET_CALLBACK:
        _request_run_resolver = request_run_resolver
    if model_budget_resolver is not _UNSET_CALLBACK:
        _model_budget_resolver = model_budget_resolver
    if token_counter is not _UNSET_CALLBACK:
        _token_counter = token_counter
    if analysis_callback is not _UNSET_CALLBACK:
        _analysis_callback = analysis_callback


def _operation_key(*values) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def create_m365_request_budget(store: ConversationMemoryStore, memory_context: MemoryContext, context) -> str:
    """Resolve one crash-safe budget manifest per authorized principal and logical request."""
    _check_memory_binding(store, memory_context, context)
    memory_context = replace(memory_context, request_id=context.request_id)
    run = store.get_or_create_manifest(
        memory_context, kind="m365_request_budget", key=context.request_id,
    )
    if run.get("latest_checkpoint") is None or run.get("pending_operation"):
        if run["status"] in ("waiting", "failed"):
            store.resume(memory_context, run["run_id"])
        claim = store.claim(memory_context, run["run_id"], lease_seconds=600)
        try:
            checkpoint = _read_claimed_budget_checkpoint(store, memory_context, run["run_id"], claim)
            if checkpoint is None:
                store.append_checkpoint(
                    memory_context, run["run_id"],
                    checkpoint={
                        "kind": "m365_request_budget", "download_count": 0, "context_tokens": 0,
                        "operations": {}, "source_refusals": {},
                    },
                    claim=claim,
                )
        finally:
            current = store.read_manifest(memory_context, run["run_id"])
            store.release_claim(
                memory_context, claim,
                status="failed" if current.get("pending_operation") else "queued",
            )
    return run["run_id"]


def _read_claimed_budget_checkpoint(store, memory_context, run_id, claim):
    manifest = store.read_manifest(memory_context, run_id)
    if manifest.get("pending_operation"):
        if manifest["pending_operation"] != "checkpoint":
            raise M365ProviderError("invalid_request_memory", "The request budget contains an unexpected pending operation.")
        store.recover_pending(memory_context, run_id, claim=claim)
    return store.read_checkpoint(memory_context, run_id)


def _check_memory_binding(store, memory_context, context):
    if not isinstance(store, ConversationMemoryStore) or not isinstance(memory_context, MemoryContext):
        raise M365ProviderError("memory_unavailable", "Authorized conversation working memory is not configured.")
    if (
        memory_context.tenant_id != context.tenant_id
        or memory_context.principal_id != context.data_user_id
        or memory_context.conversation_id != context.conversation_id
        or memory_context.request_id is not None and memory_context.request_id != context.request_id
    ):
        raise M365ProviderError("memory_context_mismatch", "Working memory does not match this authorized conversation and data user.")


def _memory_binding(context):
    if _memory_resolver is None:
        raise M365ProviderError(
            "memory_unavailable", "Conversation working memory is required for retained Microsoft 365 file evidence.",
        )
    binding = _memory_resolver(context)
    if not isinstance(binding, tuple) or len(binding) != 2:
        raise M365ProviderError("memory_unavailable", "The conversation memory binding is unavailable.")
    store, memory_context = binding
    _check_memory_binding(store, memory_context, context)
    return store, replace(memory_context, request_id=context.request_id)


def _model_room(context) -> int:
    if _model_budget_resolver is None:
        raise M365ProviderError("model_context_unavailable", "The selected model's available file-context budget has not been supplied.")
    room = _model_budget_resolver(context)
    if type(room) is not int or room <= 0:
        raise M365ProviderError("model_context_full", "The model needs another bounded analysis step before more file text can be read.")
    return room


def _text_tokens(text: str, context) -> int:
    tokens = _token_counter(text, context) if _token_counter else len(text.encode("utf-8"))
    if type(tokens) is not int or tokens < 0 or (text and tokens == 0):
        raise M365ProviderError("invalid_model_budget", "The model token counter returned an invalid file-context count.")
    return tokens


def _fit_text(text: str, room: int, context):
    if room <= 0:
        return "", 0
    tokens = _text_tokens(text, context)
    if tokens <= room:
        return text, tokens
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if _text_tokens(text[:middle], context) <= room:
            low = middle
        else:
            high = middle - 1
    value = text[:low]
    return value, _text_tokens(value, context)


def _analysis_choice(source, action_id, context, proposal, *, snapshot=False):
    if snapshot:
        # A published copy uses conversation authorization; it must not reconnect the source.
        from functions_m365_approvals import get_m365_approval_service

        return get_m365_approval_service().authorize_extended_analysis(context, source, proposal)
    from functions_m365_execution import authorize_m365_extended_analysis

    return authorize_m365_extended_analysis(source, proposal, action_id=action_id, context=context)


class _RequestBudget:
    def __init__(self, store, memory_context, context, run_id, claim, checkpoint):
        self.store = store
        self.memory_context = memory_context
        self.context = context
        self.run_id = run_id
        self.claim = claim
        self.state = deepcopy(checkpoint)
        self.last_progress_check = time.monotonic()

    def check_active(self):
        self.claim = self.store.renew_claim(self.memory_context, self.claim, lease_seconds=600)
        self.last_progress_check = time.monotonic()

    def check_progress(self):
        if time.monotonic() - self.last_progress_check >= 5:
            self.check_active()

    def save(self):
        self.check_active()
        self.store.append_checkpoint(
            self.memory_context, self.run_id, checkpoint=self.state,
            completed_units=self.state["download_count"], claim=self.claim,
        )

    def remember(self, key, value):
        operations = self.state["operations"]
        if key not in operations and len(operations) >= M365_MAX_REQUEST_OPERATIONS:
            raise M365ProviderError("request_operation_limit", "This request reached its bounded file-operation limit; start a new logical request.")
        operations[key] = value
        self.save()

    def check_source_policy(self, source):
        refusal = self.state.get("source_refusals", {}).get(source)
        if refusal:
            raise M365ProviderError(
                "source_policy_blocked",
                "An explicit Copilot policy or access denial cannot be bypassed with raw Graph file reads in this request.",
                status_code=403, details={"provider": refusal["provider"], "policy_refusal": True},
            )

    def record_source_refusal(self, source, error):
        self.state.setdefault("source_refusals", {})[source] = {
            "provider": error.details["provider"], "code": error.code,
        }
        self.save()

    def reserve_download(self, source, action_id, size_bytes):
        projected = self.state["download_count"] + 1
        if projected > M365_HARD_DOWNLOADS_PER_REQUEST:
            raise M365ProviderError(
                "download_hard_limit", "This request reached the hard service limit for content downloads.",
                details={"download_count": self.state["download_count"], "hard_limit": M365_HARD_DOWNLOADS_PER_REQUEST},
            )
        max_bytes = M365_FAST_FILE_BYTES
        if projected > M365_FAST_DOWNLOADS or size_bytes is not None and size_bytes > M365_FAST_FILE_BYTES:
            choice = _analysis_choice(source, action_id, self.context, {
                "file_count": projected, "download_count": projected,
                "total_bytes": size_bytes or 0, "context_tokens": self.state["context_tokens"],
            })
            if choice.get("mode") != "extended":
                raise M365ProviderError(
                    "fast_analysis_limit", "The faster-answer choice leaves additional file content unread.",
                    details={"fast_answer_allowed": True, "download_count": self.state["download_count"]},
                )
            max_bytes = M365_FILE_HARD_MAX_BYTES
        self.state["download_count"] = projected
        self.save()
        return max_bytes

    def context_window(self, source, action_id, requested_tokens, *, snapshot=False):
        room = _model_room(self.context)
        fast_remaining = max(0, M365_FAST_CONTEXT_TOKENS - self.state["context_tokens"])
        choice = None
        if requested_tokens > fast_remaining or requested_tokens > room:
            choice = _analysis_choice(source, action_id, self.context, {
                "file_count": self.state["download_count"],
                "download_count": self.state["download_count"],
                "total_bytes": 0,
                "context_tokens": self.state["context_tokens"] + requested_tokens,
            }, snapshot=snapshot)
            if choice.get("mode") != "extended":
                room = min(room, fast_remaining)
        return room, choice

    def record_context(self, count):
        self.state["context_tokens"] += count
        self.save()


@contextmanager
def _request_budget(context, transport=None):
    store, memory_context = _memory_binding(context)
    run_id = (
        _request_run_resolver(context) if _request_run_resolver
        else create_m365_request_budget(store, memory_context, context)
    )
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise M365ProviderError("request_memory_binding_required", "This logical request has no valid persisted Microsoft 365 budget binding.")
    run = store.read_manifest(memory_context, run_id)
    if (
        run.get("purpose") != "m365_request_budget"
        or run.get("principal_id") != context.data_user_id
        or run.get("request_id") != context.request_id
    ):
        raise M365ProviderError("request_memory_mismatch", "The file budget belongs to a different request or data user.")
    if run.get("status") in ("waiting", "failed"):
        store.resume(memory_context, run_id)
    claim = store.claim(memory_context, run_id, lease_seconds=600)
    succeeded = False
    try:
        checkpoint = _read_claimed_budget_checkpoint(store, memory_context, run_id, claim)
        state = checkpoint.get("checkpoint") if isinstance(checkpoint, dict) else None
        if (
            not isinstance(state, dict) or state.get("kind") != "m365_request_budget"
            or type(state.get("download_count")) is not int or state["download_count"] < 0
            or type(state.get("context_tokens")) is not int or state["context_tokens"] < 0
            or not isinstance(state.get("operations"), dict)
            or not isinstance(state.get("source_refusals", {}), dict)
        ):
            raise M365ProviderError("invalid_request_memory", "The persisted file budget is incomplete or invalid.")
        budget = _RequestBudget(store, memory_context, context, run_id, claim, state)
        callbacks = (
            transport.callback_context(budget.check_active, budget.check_progress)
            if transport is not None else nullcontext()
        )
        with callbacks:
            yield budget
        claim = budget.claim
        succeeded = True
    finally:
        try:
            current = store.read_manifest(memory_context, run_id)
            store.release_claim(
                memory_context, claim,
                status="failed" if current.get("pending_operation") else "queued",
            )
        except (MemoryConflictError, MemoryStateError):
            if succeeded:
                raise
            log_m365_failure("request_claim_lost")


def _resume_writable_run(store, memory_context, run_id):
    run = store.read_manifest(memory_context, run_id)
    if run["status"] in ("waiting", "failed"):
        run = store.resume(memory_context, run_id)
    if run.get("pending_operation"):
        raise M365ProviderError(
            "memory_recovery_required",
            "This capture has uncommitted evidence. Recover or discard that exact pending memory operation before retrying.",
            details={"memory_id": run_id, "resume_required": True},
        )
    return run


def _source_version(file_info):
    version = file_info["captured_version"]
    if version.get("kind") == "index_excerpts":
        return f"excerpt-sha256:{version['sha256']}"
    return str(version.get("etag") or version.get("ctag") or version.get("sha256") or version.get("last_modified") or "unversioned-search")


def _publication_context(context, source, action_id, decision, operation_name):
    return {
        "execution_context": context, "source": source,
        "action_id": action_id, "sharing_decision": decision,
        "operation_name": operation_name,
    }


def _file_operation_context(function):
    @wraps(function)
    def execute(self, *args, **kwargs):
        with self.transport.operation_context(function.__name__):
            return function(self, *args, **kwargs)
    return execute


class M365FileOperations:
    def __init__(self, action_type: str, manifest=None):
        self.action_type = action_type
        self.manifest = normalize_m365_action_config(action_type, manifest)
        self.source = get_m365_action_definition(action_type)["source"]
        if self.source not in M365_FILE_SOURCES:
            raise ValueError("File operations require a file action type.")
        self.action_id = self.manifest.get("id") or self.manifest.get("name") or ""
        self.policy = {"maximum_sharing_acknowledgement": self.manifest["maximum_sharing_acknowledgement"]}
        self.transport = M365Transport(
            self.source, self.action_id, self.policy, action_type=self.action_type,
        )

    def authorize(self, operation, *, snapshot=False):
        enabled = get_m365_enabled_function_names(self.action_type, self.manifest)
        if operation not in enabled:
            raise M365ProviderError("function_not_enabled", "This function is not enabled for this Microsoft 365 action.")
        if snapshot:
            context = authorize_m365_capability(
                self.action_id, operation, self.action_type,
                context=get_m365_context(require_remote=False),
            )
            return context, None
        return authorize_m365_source(
            self.source, self.action_id, self.policy,
            operation_name=operation, action_type=self.action_type,
        )

    def _publish(self, store, memory_context, run_id, context, decision):
        manifest = store.read_manifest(memory_context, run_id)
        if context.shared and manifest.get("publication") is None:
            context, decision = authorize_m365_publication(
                self.source, self.action_id, self.policy,
                operation_name=self.transport.current_operation,
            )
            manifest = store.publish(
                memory_context, run_id,
                grant_context=_publication_context(
                    context, self.source, self.action_id, decision, self.transport.current_operation,
                ),
            )
        return manifest

    def _create_run(self, store, memory_context, context, purpose, decision=None, *, key=None):
        refs = [decision["approval_id"]] if decision and decision.get("approval_id") else []
        if key is not None:
            return store.get_or_create_manifest(
                memory_context, kind=purpose, key=key, approval_ids=refs,
            )["run_id"]
        return store.create_run(
            memory_context, request_id=context.request_id, purpose=purpose, approval_ids=refs,
        )["run_id"]

    def _file_source(self, file_info, *, complete=False, original_sha256=None):
        return EvidenceSource(
            source_type=self.source,
            source_id=file_info["source_id"],
            version=_source_version(file_info),
            display_name=file_info["display_name"],
            canonical_url=file_info["web_url"],
            original_sha256=original_sha256,
            coverage_complete=complete,
        )

    def _saved_search(self, store, memory_context, run_id):
        manifest = store.read_manifest(memory_context, run_id)
        checkpoint = store.read_checkpoint(memory_context, run_id)
        if (
            manifest.get("purpose") != f"m365_search_{self.source}"
            or not checkpoint or checkpoint["checkpoint"].get("phase") != "ready"
        ):
            raise M365ProviderError("memory_recovery_required", "The saved file search must be recovered before it can be reused.")
        result = deepcopy(checkpoint["output"])
        for file_info in result["results"]:
            file_info["excerpts"] = []
            if not file_info.get("evidence_id"):
                continue
            offset = 0
            while offset is not None:
                page = store.read_evidence_range(
                    memory_context, run_id, file_info["evidence_id"], start=offset,
                )
                for chunk in page["chunks"]:
                    file_info["excerpts"].append({
                        "text": chunk["text"], "location": chunk["locator"],
                        "kind": "retrieval_excerpt" if result["provider"] == "copilot_retrieval" else "search_snippet",
                    })
                offset = page["next_start"]
        return result

    def _stage_search(self, budget, result, key, decision):
        store, memory_context, context = budget.store, budget.memory_context, budget.context
        run_id = self._create_run(store, memory_context, context, f"m365_search_{self.source}", decision)
        budget.remember(key, {"kind": "search", "memory_id": run_id, "state": "capturing"})
        staged = deepcopy(result)
        for file_info in staged["results"]:
            excerpts = file_info.pop("excerpts")
            if not any(excerpt["text"] for excerpt in excerpts):
                continue
            chunks = []
            for excerpt in excerpts:
                locator = dict(excerpt["location"])
                for name in ("pages", "slides"):
                    if name in locator:
                        locator[name] = tuple(locator[name])
                for offset in range(0, len(excerpt["text"]), M365_EVIDENCE_CHUNK_CHARS):
                    text = excerpt["text"][offset:offset + M365_EVIDENCE_CHUNK_CHARS]
                    chunks.append(EvidenceChunk(text, EvidenceLocation(**{
                        **locator, "char_start": offset, "char_end": offset + len(text),
                    })))
            source = store.add_evidence(
                memory_context, run_id, source=self._file_source(file_info), chunks=chunks,
            )
            file_info.update({
                "memory_id": f"{run_id}:{source['evidence_id']}",
                "evidence_id": source["evidence_id"], "total_chunks": source["chunk_count"],
            })
        store.append_checkpoint(
            memory_context, run_id,
            checkpoint={"kind": "m365_search", "source": self.source, "phase": "ready", "operation_key": key},
            output=staged,
        )
        store.complete_run(memory_context, run_id)
        self._publish(store, memory_context, run_id, context, decision)
        budget.remember(key, {"kind": "search", "memory_id": run_id, "state": "ready"})
        return self._saved_search(store, memory_context, run_id)

    def _fit_search(self, result, budget):
        result = deepcopy(result)
        tokens = sum(
            _text_tokens(excerpt["text"], budget.context)
            for file_info in result["results"] for excerpt in file_info.get("excerpts", [])
        )
        room, choice = budget.context_window(self.source, self.action_id, tokens)
        used, omitted_chars = 0, 0
        for file_info in result["results"]:
            visible = []
            file_omitted = 0
            for excerpt in file_info.get("excerpts", []):
                text, count = _fit_text(excerpt["text"], max(0, room - used), budget.context)
                used += count
                file_omitted += len(excerpt["text"]) - len(text)
                if text:
                    visible.append({**excerpt, "text": text, "window_complete": len(text) == len(excerpt["text"])})
            file_info["excerpts"] = visible
            file_info["coverage"]["omitted_excerpt_characters"] = file_omitted
            omitted_chars += file_omitted
        budget.record_context(used)
        result["coverage"].update({
            "context_tokens": used,
            "logical_request_context_tokens": budget.state["context_tokens"],
            "token_count_method": "model_tokenizer" if _token_counter else "conservative_utf8_upper_bound",
            "omitted_excerpt_characters": omitted_chars,
            "retained_evidence_available": any(file_info.get("evidence_id") for file_info in result["results"]),
        })
        if choice:
            result["analysis_decision"] = choice
        if omitted_chars:
            result["status"] = "partial"
            result["coverage"]["limitation"] = "Additional retained evidence needs a later bounded model window."
        return result

    @_file_operation_context
    def search_files(self, query, folder="", top=10):
        context, decision = self.authorize("search_files")
        _query_text(query)
        _positive_integer(top, "top", M365_SEARCH_PAGE_SIZE)
        if not isinstance(folder, str) or len(folder) > 4096:
            raise M365ProviderError("invalid_folder", "Use a specific canonical folder URL or OneDrive path.")
        _model_room(context)
        key = _operation_key("search", self.source, query, folder, top)
        with _request_budget(context, self.transport) as budget:
            budget.check_source_policy(self.source)
            saved = budget.state["operations"].get(key)
            if saved:
                result = self._saved_search(budget.store, budget.memory_context, saved["memory_id"])
            else:
                try:
                    result = M365FileProvider(self.transport).search(query, folder, top)
                except M365ProviderError as exc:
                    if exc.details.get("provider") == "copilot_retrieval" and exc.details.get("policy_refusal"):
                        budget.record_source_refusal(self.source, exc)
                    raise
                result = self._stage_search(budget, result, key, decision)
            return self._fit_search(result, budget)

    @_file_operation_context
    def discover_files(self, query, folder="", memory_id=""):
        context, decision = self.authorize("discover_files")
        with _request_budget(context, self.transport) as budget:
            budget.check_source_policy(self.source)
            return self._discover_files(query, folder, memory_id, context, decision, budget)

    def _discover_files(self, query, folder, memory_id, context, decision, budget):
        query = _query_text(query)
        if not isinstance(memory_id, str) or not isinstance(folder, str) or len(folder) > 4096:
            raise M365ProviderError("invalid_parameters", "Discovery folder and checkpoint IDs must be valid strings.")
        store, memory_context = budget.store, budget.memory_context
        key = _operation_key("discovery", self.source, query, folder)
        provider = M365FileProvider(self.transport)
        if memory_id:
            run_id = memory_id
            run = _resume_writable_run(store, memory_context, run_id)
            checkpoint = store.read_checkpoint(memory_context, run_id)
            if (
                run.get("purpose") != f"m365_discovery_{self.source}"
                or run.get("principal_id") != context.data_user_id
                or not checkpoint or checkpoint["checkpoint"].get("operation_key") != key
            ):
                raise M365ProviderError("discovery_context_mismatch", "The discovery checkpoint belongs to another source, query, or data user.")
            state = checkpoint["checkpoint"]
            if state.get("next_offset") is None:
                return {**checkpoint["output"], "memory_id": run_id, "reused_checkpoint": True}
            offset, folder_url = state["next_offset"], state["folder_url"]
            inspected = checkpoint["completed_units"]
        else:
            folder_url = provider.resolve_folder(folder)
            run_id = self._create_run(store, memory_context, context, f"m365_discovery_{self.source}", decision)
            offset, inspected = 0, 0
        claim = store.claim(memory_context, run_id, lease_seconds=600)
        finished = False
        try:
            result = provider.discover_page(query, folder_url=folder_url, offset=offset)
            for file_info in result["results"]:
                file_info.pop("excerpts", None)
                version = file_info["captured_version"]
                if version.get("kind") == "index_excerpts":
                    file_info["captured_version"] = {
                        **version["observed_metadata"], "kind": "metadata_observation",
                        "source_version_verified": False,
                    }
                file_info["coverage"]["kind"] = "metadata"
            result["coverage"]["kind"] = "file_discovery"
            inspected += result["coverage"]["files_inspected"]
            state = {
                "kind": "m365_discovery", "source": self.source, "operation_key": key,
                "query": query, "folder_url": folder_url,
                "next_offset": result["next_offset"],
            }
            store.append_checkpoint(
                memory_context, run_id, checkpoint=state, output=result,
                completed_units=inspected, claim=claim,
            )
            if result["next_offset"] is None:
                store.complete_run(memory_context, run_id, claim=claim)
                finished = True
                self._publish(store, memory_context, run_id, context, decision)
            result["memory_id"] = run_id
            result["coverage"]["logical_discovery_candidates_inspected"] = inspected
            return result
        finally:
            if not finished:
                current = store.read_manifest(memory_context, run_id)
                store.release_claim(
                    memory_context, claim,
                    status="failed" if current.get("pending_operation") else "queued",
                )

    def _prepared_result(self, store, memory_context, run_id):
        run = store.read_manifest(memory_context, run_id)
        checkpoint = store.read_checkpoint(memory_context, run_id)
        if (
            run.get("purpose") == f"m365_file_{self.source}"
            and run.get("principal_id") == memory_context.principal_id
            and run.get("evidence_count") == 1 and not run.get("pending_operation")
            and checkpoint and checkpoint["checkpoint"].get("phase") == "extracted"
        ):
            if run["source_slots"] > M365_HARD_DOWNLOADS_PER_REQUEST:
                raise M365ProviderError("memory_recovery_required", "This capture exceeds bounded automatic recovery.")
            sources, start = [], 0
            while start is not None:
                page = store.list_sources(memory_context, run_id, start=start)
                sources.extend(page["sources"])
                start = page["next_start"]
            file_info = checkpoint["output"]["file"]
            coverage = checkpoint["output"]["coverage"]
            if (
                len(sources) != 1
                or sources[0]["source"]["source_type"] != self.source
                or sources[0]["source"]["source_id"] != file_info["source_id"]
                or sources[0]["source"]["version"] != _source_version(file_info)
                or sources[0]["source"]["original_sha256"] != file_info["captured_version"]["sha256"]
                or sources[0]["source"]["coverage_complete"] != coverage["complete"]
            ):
                raise M365ProviderError("memory_recovery_required", "The captured evidence does not match its extraction checkpoint.")
            _resume_writable_run(store, memory_context, run_id)
            self._commit_prepared_file(store, memory_context, run_id, file_info, coverage, sources[0])
            run = store.read_manifest(memory_context, run_id)
            checkpoint = store.read_checkpoint(memory_context, run_id)
        if (
            run.get("purpose") != f"m365_file_{self.source}"
            or not checkpoint or checkpoint["checkpoint"].get("phase") != "prepared"
        ):
            raise M365ProviderError(
                "memory_recovery_required", "This file capture is not complete; resume its retained checkpoint before reading.",
                details={"memory_id": run_id, "resume_required": True},
            )
        result = deepcopy(checkpoint["output"])
        result["memory_id"] = run_id
        result["memory_run_id"] = run_id
        result["evidence_reference"] = f"{run_id}:{result['evidence_id']}"
        result["snapshot_state"] = "published_snapshot" if run.get("publication") else "private_snapshot"
        return result

    def _commit_prepared_file(self, store, memory_context, run_id, file_info, coverage, source):
        result = {
            "status": "ok" if coverage["complete"] else "partial",
            "source": self.source, "source_label": _source_label(self.source),
            "provider": "graph", "file": file_info,
            "evidence_id": source["evidence_id"], "total_chunks": source["chunk_count"],
            "captured_at": source["capture"]["captured_at"],
            "captured_version": file_info["captured_version"],
            "coverage": coverage,
            "trust": "untrusted_source_data",
        }
        store.append_checkpoint(
            memory_context, run_id,
            checkpoint={"kind": "m365_file", "source": self.source, "phase": "prepared"}, output=result,
            completed_units=coverage["units_read"], total_units=coverage["units_total"],
        )
        store.complete_run(memory_context, run_id)

    @_file_operation_context
    def prepare_file(self, drive_id="", item_id="", web_url=""):
        context, decision = self.authorize("prepare_file")
        return self._capture_file(drive_id, item_id, web_url, context, decision)

    def _capture_file(self, drive_id, item_id, web_url, context, decision):
        with _request_budget(context, self.transport) as budget:
            budget.check_source_policy(self.source)
            provider = M365FileProvider(self.transport)
            file_info = provider.resolve_file(drive_id, item_id, web_url)
            suffix, allowed_mime_types = m365_file_format(file_info["display_name"], file_info["mime_type"])
            size = file_info["size_bytes"]
            if size is not None and size > M365_FILE_HARD_MAX_BYTES:
                raise M365ProviderError(
                    "file_hard_limit", "The file exceeds the hard service download limit.",
                    details={"size_bytes": size, "limit_bytes": M365_FILE_HARD_MAX_BYTES},
                )
            key = _operation_key("file", self.source, file_info["source_id"], file_info["captured_version"])
            saved = budget.state["operations"].get(key)
            if saved:
                run_id = saved["memory_id"]
            else:
                run_id = self._create_run(
                    budget.store, budget.memory_context, context,
                    f"m365_file_{self.source}", decision, key=key,
                )
                budget.remember(key, {"kind": "file", "memory_id": run_id, "state": "capturing"})
            manifest = budget.store.read_manifest(budget.memory_context, run_id)
            if manifest["status"] == "completed" or manifest["evidence_count"] == 1:
                self._prepared_result(budget.store, budget.memory_context, run_id)
                self._publish(budget.store, budget.memory_context, run_id, context, decision)
                budget.remember(key, {"kind": "file", "memory_id": run_id, "state": "ready"})
                return self._prepared_result(budget.store, budget.memory_context, run_id)
            _resume_writable_run(budget.store, budget.memory_context, run_id)
            observed_size = saved.get("minimum_size_bytes", 0) if saved else 0
            effective_size = max(size or 0, observed_size) or None
            max_bytes = budget.reserve_download(self.source, self.action_id, effective_size)
            store, memory_context = budget.store, budget.memory_context
            store.append_checkpoint(
                memory_context, run_id,
                checkpoint={"kind": "m365_file", "source": self.source, "phase": "downloading"},
                output={"file": file_info, "download_count": budget.state["download_count"]},
            )
            try:
                with self.transport.download_file(
                    file_info["drive_id"], file_info["item_id"],
                    suffix=suffix, allowed_mime_types=allowed_mime_types,
                    max_bytes=max_bytes, etag=file_info["captured_version"]["etag"] or "",
                ) as downloaded:
                    if size is not None and downloaded.size_bytes != size:
                        raise M365ProviderError("source_size_mismatch", "The download does not match the source file's declared size.")
                    extracted = extract_m365_file(downloaded.path, file_info["display_name"], file_info["mime_type"])
                    current = provider.resolve_file(file_info["drive_id"], file_info["item_id"])
                    if current["captured_version"] != file_info["captured_version"]:
                        raise M365ProviderError("source_changed", "The source changed during capture. Request a new source version.")
                    if current["size_bytes"] is not None and downloaded.size_bytes != current["size_bytes"]:
                        raise M365ProviderError("source_size_mismatch", "The download does not match the revalidated source file size.")
                    file_info["captured_version"]["sha256"] = downloaded.sha256
                    file_info["captured_version"]["kind"] = "file_capture"
                    file_info["captured_version"]["source_version_verified"] = bool(
                        file_info["captured_version"]["etag"] or file_info["captured_version"]["ctag"]
                    )
                    file_info["size_bytes"] = downloaded.size_bytes
                    store.append_checkpoint(
                        memory_context, run_id,
                        checkpoint={"kind": "m365_file", "source": self.source, "phase": "extracted"},
                        output={"file": file_info, "coverage": extracted.coverage},
                    )
                    source = store.add_evidence(
                        memory_context, run_id,
                        source=self._file_source(
                            file_info, complete=extracted.coverage["complete"], original_sha256=downloaded.sha256,
                        ),
                        chunks=iter_m365_evidence_chunks(extracted),
                    )
            except M365ProviderError as exc:
                store.append_checkpoint(
                    memory_context, run_id,
                    checkpoint={"kind": "m365_file", "source": self.source, "phase": "capture_error"},
                    output={"file": file_info, "error": exc.as_dict(), "coverage": {"complete": False}},
                )
                if exc.code == "file_size_limit" and max_bytes == M365_FAST_FILE_BYTES:
                    observed_size = max(0, exc.details.get("observed_bytes") or 0)
                    budget.remember(key, {
                        "kind": "file", "memory_id": run_id, "state": "requires_extended_size",
                        "minimum_size_bytes": observed_size,
                    })
                    choice = _analysis_choice(self.source, self.action_id, context, {
                        "file_count": budget.state["download_count"],
                        "download_count": budget.state["download_count"],
                        "total_bytes": observed_size,
                        "context_tokens": budget.state["context_tokens"],
                    })
                    exc.details["analysis_decision"] = choice
                    exc.details["resume_required"] = choice.get("mode") == "extended"
                exc.details["memory_id"] = run_id
                raise
            self._commit_prepared_file(store, memory_context, run_id, file_info, extracted.coverage, source)
            self._publish(store, memory_context, run_id, context, decision)
            budget.remember(key, {"kind": "file", "memory_id": run_id, "state": "ready"})
            return self._prepared_result(store, memory_context, run_id)

    def _read_chunk(self, memory_id, chunk_index, char_offset, context, budget):
        match = re.fullmatch(r"([0-9a-f]{32})(?::(s[0-9a-f]{16}))?", str(memory_id))
        if not match or type(chunk_index) is not int or chunk_index < 0 or type(char_offset) is not int or char_offset < 0:
            raise M365ProviderError("invalid_memory_range", "Use an authorized evidence ID and nonnegative chunk/character offsets.")
        run_id, evidence_id = match.groups()
        store, memory_context = budget.store, budget.memory_context
        manifest = store.read_manifest(memory_context, run_id)
        if manifest.get("purpose") not in (f"m365_file_{self.source}", f"m365_search_{self.source}"):
            raise M365ProviderError("source_not_allowed", "This retained evidence belongs to a different source or operation.")
        if manifest.get("purpose") == f"m365_file_{self.source}" and manifest["evidence_count"] == 1:
            self._prepared_result(store, memory_context, run_id)
            manifest = store.read_manifest(memory_context, run_id)
        if context.shared and manifest.get("publication") is None:
            if manifest.get("status") != "completed":
                raise M365ProviderError(
                    "memory_unpublished", "Complete and approve this private capture before bringing it into a shared conversation.",
                    details={"memory_id": memory_id},
                )
            manifest = self._publish(store, memory_context, run_id, context, None)
        if evidence_id is None:
            prepared = self._prepared_result(store, memory_context, run_id)
            evidence_id = prepared["evidence_id"]
        page = store.read_evidence_range(memory_context, run_id, evidence_id, start=chunk_index, count=1)
        if page["source"]["source"].get("source_type") != self.source:
            raise M365ProviderError("source_not_allowed", "This retained evidence belongs to a different Microsoft 365 source.")
        if not page["chunks"] or char_offset >= len(page["chunks"][0]["text"]) and page["chunks"][0]["text"]:
            raise M365ProviderError("invalid_memory_range", "The requested evidence range is outside the captured text.")
        chunk = page["chunks"][0]
        remaining = chunk["text"][char_offset:]
        requested = _text_tokens(remaining, context)
        room, choice = budget.context_window(self.source, self.action_id, requested, snapshot=True)
        if remaining and room <= 0:
            raise M365ProviderError(
                "fast_analysis_limit", "The faster-answer choice leaves this retained evidence for a later request.",
                details={"memory_id": memory_id, "fast_answer_allowed": True},
            )
        visible, used = _fit_text(remaining, room, context)
        budget.record_context(used)
        complete = len(visible) == len(remaining)
        next_character = None if complete else char_offset + len(visible)
        result = {
            "status": "ok" if complete else "partial",
            "source": self.source, "source_label": _source_label(self.source),
            "provider": "conversation_memory",
            "memory_id": memory_id, "evidence_id": evidence_id,
            "memory_run_id": run_id, "evidence_reference": f"{run_id}:{evidence_id}",
            "text": visible, "location": chunk["locator"], "chunk_index": chunk_index,
            "char_start": char_offset, "char_end": char_offset + len(visible),
            "next_chunk_index": page["next_start"] if complete else chunk_index,
            "next_char_offset": next_character,
            "canonical_id": page["source"]["source"]["source_id"],
            "web_url": page["source"]["source"]["canonical_url"],
            "captured_version": page["source"]["source"]["version"],
            "capture": page["source"]["capture"],
            "snapshot_state": "published_snapshot" if manifest.get("publication") else "private_snapshot",
            "coverage": {
                "complete": (
                    complete and page["next_start"] is None and chunk_index == 0 and char_offset == 0
                    and page["source"]["source"]["coverage_complete"] is True
                ),
                "window_complete": complete, "total_chunks": page["total_chunks"],
                "context_tokens": used, "logical_request_context_tokens": budget.state["context_tokens"],
                "token_count_method": "model_tokenizer" if _token_counter else "conservative_utf8_upper_bound",
            },
            "trust": "untrusted_source_data",
        }
        if choice:
            result["analysis_decision"] = choice
        return result

    @_file_operation_context
    def read_file_chunk(self, memory_id, chunk_index=0, char_offset=0):
        context, _ = self.authorize("read_file_chunk", snapshot=True)
        with _request_budget(context) as budget:
            return self._read_chunk(memory_id, chunk_index, char_offset, context, budget)

    @_file_operation_context
    def read_file(self, drive_id="", item_id="", web_url=""):
        context, decision = self.authorize("read_file")
        _model_room(context)
        prepared = self._capture_file(drive_id, item_id, web_url, context, decision)
        with _request_budget(context) as budget:
            window = self._read_chunk(prepared["evidence_reference"], 0, 0, context, budget)
        return {
            **prepared, "window": window,
            "status": "partial" if prepared["status"] == "partial" or window["next_chunk_index"] is not None else window["status"],
        }

    async def analyze_file(self, memory_id: str, question: str, analysis_id: str = "") -> dict:
        context, _ = self.authorize("analyze_file", snapshot=True)
        callback = _analysis_callback
        if callback is None:
            raise M365ProviderError(
                "m365_analysis_unavailable",
                "Retained-file analysis is not supported until a bounded analysis callback is configured.",
            )
        _memory_binding(context)
        pending = callback(context, self.source, self.action_id, memory_id, question, analysis_id)
        if not isawaitable(pending):
            raise M365ProviderError("invalid_analysis_callback", "Retained-file analysis requires an asynchronous callback.")
        result = await pending
        if not isinstance(result, dict) or not result:
            raise M365ProviderError("invalid_analysis_result", "The analysis callback did not return a bounded progress result.")
        return result


class M365FilePlugin(BasePlugin):
    """Internal shared facade; this module is outside auto-discovered plugin modules."""

    ACTION_TYPE = None

    def __init__(self, manifest=None):
        super().__init__(manifest)
        self._operations = M365FileOperations(self.ACTION_TYPE, manifest)
        self.manifest = self._operations.manifest

    @property
    def display_name(self):
        return get_m365_action_definition(self.ACTION_TYPE)["display_name"]

    @property
    def metadata(self):
        definition = get_m365_action_definition(self.ACTION_TYPE)
        enabled = set(self.get_functions())
        return {
            "name": self.manifest.get("name") or self.ACTION_TYPE,
            "type": self.ACTION_TYPE,
            "source": definition["source"],
            "description": definition["description"],
            "methods": [
                method for method in get_m365_function_definitions(self.ACTION_TYPE)
                if method["name"] in enabled
            ],
        }

    def get_functions(self):
        return get_m365_enabled_function_names(self.ACTION_TYPE, self.manifest)

    def get_kernel_plugin(self, plugin_name=None):
        return KernelPlugin.from_object(
            plugin_name or self.manifest.get("name") or self.ACTION_TYPE,
            {name: getattr(self, name) for name in self.get_functions()},
            description=self.metadata["description"],
        )

    def _invoke(self, operation, *args):
        try:
            return getattr(self._operations, operation)(*args)
        except M365ApprovalRequired:
            raise
        except (M365PolicyError, M365ProviderError, ConversationMemoryError) as exc:
            return self._invocation_error(operation, exc)

    def _invocation_error(self, operation, exc, *, provider="graph"):
        if isinstance(exc, M365PolicyError):
            log_m365_failure(exc.code, source=self._operations.source, operation=operation)
            return {
                "status": "error", "source": self._operations.source,
                "provider": provider, "operation": operation,
                "error": {"code": exc.code, "message": exc.payload["message"]},
                "policy": exc.payload, "coverage": {"complete": False},
            }
        if isinstance(exc, M365ProviderError):
            log_m365_failure(exc.code, source=self._operations.source, operation=operation)
            return exc.as_result(self._operations.source, provider=provider, operation=operation)
        if isinstance(exc, ConversationMemoryError):
            if isinstance(exc, MemoryAuthorizationError):
                code = "memory_access_denied"
            elif isinstance(exc, MemoryConflictError):
                code = "memory_busy"
            elif isinstance(exc, MemoryLimitError):
                code = "memory_hard_limit"
            elif isinstance(exc, MemoryUnavailableError):
                code = "memory_unavailable"
            else:
                code = "memory_recovery_required"
            log_m365_failure(code, source=self._operations.source, operation=operation)
            return M365ProviderError(
                code, "Conversation evidence could not be accessed or updated safely.",
                details={"resume_required": code in ("memory_busy", "memory_recovery_required")},
            ).as_result(self._operations.source, provider=provider, operation=operation)
        raise exc

    @kernel_function(description="Find accessible source-specific files and bounded grounding excerpts using delegated Microsoft 365 access.")
    def search_files(self, query: str, folder: str = "", top: int = 10) -> dict:
        return self._invoke("search_files", query, folder, top)

    @kernel_function(description="Discover and checkpoint one bounded page of accessible files; pass the returned memory_id to continue.")
    def discover_files(self, query: str, folder: str = "", memory_id: str = "") -> dict:
        return self._invoke("discover_files", query, folder, memory_id)

    @kernel_function(description="Capture one accessible file into durable conversation evidence. Extended work requires the data user's approval.")
    def prepare_file(self, drive_id: str = "", item_id: str = "", web_url: str = "") -> dict:
        return self._invoke("prepare_file", drive_id, item_id, web_url)

    @kernel_function(description="Read one accessible file and return a bounded first evidence window, with explicit references to remaining content.")
    def read_file(self, drive_id: str = "", item_id: str = "", web_url: str = "") -> dict:
        return self._invoke("read_file", drive_id, item_id, web_url)

    @kernel_function(description="Read a captured evidence chunk by authorized memory ID. Published snapshots do not require fresh Microsoft 365 access.")
    def read_file_chunk(self, memory_id: str, chunk_index: int = 0, char_offset: int = 0) -> dict:
        return self._invoke("read_file_chunk", memory_id, chunk_index, char_offset)

    @kernel_function(description="Analyze one retained file evidence batch, with user-approved deeper processing. Continue with the returned analysis_id until complete.")
    async def analyze_file(self, memory_id: str, question: str, analysis_id: str = "") -> dict:
        try:
            return await self._operations.analyze_file(memory_id, question, analysis_id)
        except M365ApprovalRequired:
            raise
        except (M365PolicyError, M365ProviderError, ConversationMemoryError) as exc:
            return self._invocation_error("analyze_file", exc, provider="conversation_memory")
