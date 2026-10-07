# functions_azure_files_search.py
"""Search an existing Azure AI Search index built from Azure Files, returning only files the user can open.

Customers often index Azure file shares with the Azure AI Search Azure Files indexer. The index
carries file content and paths but no permissions, and Azure AI Search cannot ingest Azure Files
ACLs. The Azure Files Search action therefore searches the customer's index, then, for every
candidate file, reads the file's security descriptor from Azure Files and evaluates it, together
with share-level permissions, against the signed-in user's directory identity. Only files the
user is proven to be able to open reach the model. Files that are denied or cannot be verified
are withheld silently and recorded for administrators.

The functions here take their I/O dependencies as arguments so the permission logic can be
tested without Azure; ``semantic_kernel_plugins.azure_files_index_plugin`` wires the real ones.
"""

import base64
import logging
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

from functions_appinsights import log_event
from functions_azure_endpoint_validation import (
    AZURE_FILE_ENDPOINT_ERROR,
    azure_storage_endpoint_suffix_for_hostname,
    validate_azure_search_endpoint,
)
from functions_azure_files_access import (
    StorageAccountReference,
    is_valid_share_name,
    parse_storage_account_resource_id,
)
from functions_azure_files_acl import (
    MEMBER,
    NOT_MEMBER,
    OUTCOME_ALLOWED,
    OUTCOME_DENIED,
    OUTCOME_UNVERIFIED,
    AccessDecision,
)

AZURE_FILES_INDEX_ACTION_TYPE = "azure_files_index"
AZURE_FILES_SEARCH_DISPLAY_NAME = "Azure Files Search"
AZURE_FILES_SEARCH_ACTIVITY_TYPE = "azure_files_search_access"
AZURE_FILES_SEARCH_UNVERIFIED_NOTIFICATION_TYPE = "azure_files_search_access_unverified"
INTERNAL_SEARCH_INDEX_NAMES = frozenset({
    "simplechat-user-index",
    "simplechat-group-index",
    "simplechat-public-index",
})

LAYOUT_DOCUMENT_PER_FILE = "document_per_file"
LAYOUT_CHUNKED = "chunked"
LAYOUT_CUSTOM = "custom"
INDEX_LAYOUTS = (LAYOUT_DOCUMENT_PER_FILE, LAYOUT_CHUNKED, LAYOUT_CUSTOM)
LAYOUT_FIELD_DEFAULTS = {
    LAYOUT_DOCUMENT_PER_FILE: {
        "content_field": "content",
        "title_field": "metadata_storage_name",
        "path_field": "metadata_storage_path",
        "name_field": "metadata_storage_name",
        "last_modified_field": "metadata_storage_last_modified",
        "vector_field": "",
        "select_content": False,
    },
    LAYOUT_CHUNKED: {
        "content_field": "chunk",
        "title_field": "title",
        "path_field": "metadata_storage_path",
        "name_field": "metadata_storage_name",
        "last_modified_field": "",
        "vector_field": "text_vector",
        "select_content": True,
    },
}
LAYOUT_FIELD_DEFAULTS[LAYOUT_CUSTOM] = dict(LAYOUT_FIELD_DEFAULTS[LAYOUT_DOCUMENT_PER_FILE])

QUERY_MODE_KEYWORD = "keyword"
QUERY_MODE_SEMANTIC = "semantic"
QUERY_MODE_HYBRID = "hybrid"
QUERY_MODES = (QUERY_MODE_KEYWORD, QUERY_MODE_SEMANTIC, QUERY_MODE_HYBRID)

PERMISSION_MODE_LIVE_ACL = "live_acl"
PERMISSION_MODE_NONE = "none"
PERMISSION_MODES = (PERMISSION_MODE_LIVE_ACL, PERMISSION_MODE_NONE)
SHARE_ACCESS_CHECK_RBAC = "rbac"
SHARE_ACCESS_CHECK_SKIP = "skip"
SHARE_ACCESS_CHECKS = (SHARE_ACCESS_CHECK_RBAC, SHARE_ACCESS_CHECK_SKIP)

DEFAULT_TOP_N = 5
MAX_TOP_N = 20
DEFAULT_MAX_CANDIDATES = 50
MAX_CANDIDATES = 200
MIN_CANDIDATES = 5
DEFAULT_MAX_SNIPPET_CHARS = 1200
MIN_SNIPPET_CHARS = 200
MAX_SNIPPET_CHARS = 4000
DEFAULT_TIME_BUDGET_SECONDS = 25
MIN_TIME_BUDGET_SECONDS = 5
MAX_TIME_BUDGET_SECONDS = 60
MAX_RESULTS_PER_FILE = 3
MAX_STORAGE_SHARES = 50
MAX_LOGGED_WITHHELD_FILES = 25
MAX_LOGGED_UNRESOLVED_SIDS = 5
MAX_QUERY_LENGTH = 1000
ACL_EVALUATION_WORKERS = 8

REASON_PATH_MISSING = "path_missing"
REASON_STORAGE_NOT_ALLOWLISTED = "storage_not_allowlisted"
REASON_FILE_NOT_FOUND = "file_not_found"
REASON_ACL_READ_FAILED = "acl_read_failed"
REASON_TIME_BUDGET_EXCEEDED = "time_budget_exceeded"
REASON_PERMISSION_CHECKS_DISABLED = "permission_checks_disabled"

_INDEX_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){1,127}$")
_FIELD_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
_SEMANTIC_CONFIGURATION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_WHITESPACE_PATTERN = re.compile(r"\s+")


class AzureFilesSearchConfigError(ValueError):
    """An Azure Files Search configuration is invalid; the message is safe to show admins."""

    def __init__(self, public_message: str):
        self.public_message = public_message
        super().__init__(public_message)


class AzureFileNotFound(RuntimeError):
    """The indexed file no longer exists in the share."""


@dataclass(frozen=True)
class StorageShareEntry:
    account: StorageAccountReference
    share_name: str


@dataclass(frozen=True)
class AzureFilesSearchConfig:
    action_id: str
    action_name: str
    display_name: str
    endpoint: str
    index_name: str
    auth_type: str
    auth_key: str = field(repr=False)
    layout: str
    content_field: str
    title_field: str
    path_field: str
    name_field: str
    last_modified_field: str
    vector_field: str
    select_content: bool
    query_mode: str
    semantic_configuration: str
    default_top_n: int
    max_candidates: int
    max_snippet_chars: int
    time_budget_seconds: int
    permission_mode: str
    share_access_check: str
    treat_builtin_users_as_member: bool
    storage_shares: Tuple[StorageShareEntry, ...]

    def find_share(self, account_name: str, share_name: str) -> Optional[StorageShareEntry]:
        for entry in self.storage_shares:
            if entry.account.account_name == account_name and entry.share_name == share_name:
                return entry
        return None


@dataclass(frozen=True)
class AzureFilePath:
    url: str
    file_endpoint: str
    account_name: str
    endpoint_suffix: str
    share_name: str
    relative_path: str
    file_name: str
    unc_path: str
    folder: str


@dataclass
class AzureFilesSearchOutcome:
    results: List[Dict[str, Any]]
    candidate_count: int = 0
    files_evaluated: int = 0
    allowed_files: int = 0
    denied_files: int = 0
    unverified_files: int = 0
    reasons: Dict[str, int] = field(default_factory=dict)
    withheld_files: List[Dict[str, Any]] = field(default_factory=list)
    withheld_files_truncated: bool = False
    duration_ms: int = 0
    error: str = ""

    @property
    def withheld_count(self) -> int:
        return self.denied_files + self.unverified_files


def _text(value: Any, limit: int = 256) -> str:
    return str(value or "").strip()[:limit]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _field_name(value: Any, default: str, label: str, required: bool = False) -> str:
    name = _text(value, 128) if value is not None else default
    if not name:
        if required:
            raise AzureFilesSearchConfigError(f"Enter the {label} field name.")
        return ""
    if not _FIELD_NAME_PATTERN.match(name):
        raise AzureFilesSearchConfigError(f"The {label} field name is invalid.")
    return name


def normalize_azure_files_search_config(manifest: Dict[str, Any]) -> AzureFilesSearchConfig:
    """Validate an Azure Files Search action manifest and return its normalized configuration."""
    if not isinstance(manifest, dict):
        raise AzureFilesSearchConfigError("The Azure Files Search configuration is invalid.")
    fields = manifest.get("additionalFields") if isinstance(manifest.get("additionalFields"), dict) else {}
    auth = manifest.get("auth") if isinstance(manifest.get("auth"), dict) else {}

    try:
        endpoint = validate_azure_search_endpoint(manifest.get("endpoint"))
    except ValueError as error:
        raise AzureFilesSearchConfigError(str(error)) from error

    index_name = _text(fields.get("index_name"), 128).lower()
    if not _INDEX_NAME_PATTERN.match(index_name):
        raise AzureFilesSearchConfigError(
            "Enter the search index name: 2-128 lowercase letters, numbers, or single dashes."
        )

    auth_type = _text(auth.get("type") or "identity", 32).lower()
    if auth_type not in {"identity", "key"}:
        raise AzureFilesSearchConfigError("Azure Files Search supports managed identity or a query key.")
    auth_key = str(auth.get("key") or "").strip() if auth_type == "key" else ""
    if auth_type == "key" and not auth_key:
        raise AzureFilesSearchConfigError("Enter the search query key, or use managed identity.")

    layout = _text(fields.get("index_layout") or LAYOUT_DOCUMENT_PER_FILE, 32)
    if layout not in INDEX_LAYOUTS:
        raise AzureFilesSearchConfigError("Choose a supported index layout.")
    defaults = LAYOUT_FIELD_DEFAULTS[layout]
    use_defaults = layout != LAYOUT_CUSTOM

    def configured(name: str) -> Any:
        return None if use_defaults and not fields.get(name) else fields.get(name, defaults[name])

    content_field = _field_name(configured("content_field"), defaults["content_field"], "content", required=True)
    path_field = _field_name(configured("path_field"), defaults["path_field"], "file path", required=True)
    name_field = _field_name(configured("name_field"), defaults["name_field"], "file name", required=True)
    title_field = _field_name(configured("title_field"), defaults["title_field"], "title")
    last_modified_field = _field_name(configured("last_modified_field"), defaults["last_modified_field"], "last modified")
    vector_field = _field_name(configured("vector_field"), defaults["vector_field"], "vector")
    select_content = (
        _as_bool(fields["select_content"]) if "select_content" in fields else defaults["select_content"]
    )

    query_mode = _text(fields.get("query_mode") or QUERY_MODE_KEYWORD, 32)
    if query_mode not in QUERY_MODES:
        raise AzureFilesSearchConfigError("Choose keyword, semantic, or hybrid search.")
    semantic_configuration = _text(fields.get("semantic_configuration"), 128)
    if semantic_configuration and not _SEMANTIC_CONFIGURATION_PATTERN.match(semantic_configuration):
        raise AzureFilesSearchConfigError("The semantic configuration name is invalid.")
    if query_mode == QUERY_MODE_HYBRID and not vector_field:
        raise AzureFilesSearchConfigError("Hybrid search needs the index's vector field.")

    permission_mode = _text(fields.get("permission_mode") or PERMISSION_MODE_LIVE_ACL, 32)
    if permission_mode not in PERMISSION_MODES:
        raise AzureFilesSearchConfigError("Choose how file permissions are checked.")
    if permission_mode == PERMISSION_MODE_NONE and not _as_bool(fields.get("permission_mode_none_acknowledged")):
        raise AzureFilesSearchConfigError(
            "Turning off file permission checks lets everyone who can use this action search every file in the index. "
            "Confirm the acknowledgment to continue."
        )
    share_access_check = _text(fields.get("share_access_check") or SHARE_ACCESS_CHECK_RBAC, 32)
    if share_access_check not in SHARE_ACCESS_CHECKS:
        raise AzureFilesSearchConfigError("Choose how share-level permissions are checked.")

    storage_shares = []
    raw_shares = fields.get("storage_shares") if isinstance(fields.get("storage_shares"), list) else []
    if len(raw_shares) > MAX_STORAGE_SHARES:
        raise AzureFilesSearchConfigError(f"List at most {MAX_STORAGE_SHARES} file shares.")
    seen = set()
    for raw_share in raw_shares:
        raw_share = raw_share if isinstance(raw_share, dict) else {}
        try:
            account = parse_storage_account_resource_id(raw_share.get("storage_account_resource_id"))
        except ValueError as error:
            raise AzureFilesSearchConfigError(str(error)) from error
        share_name = _text(raw_share.get("share_name"), 63).lower()
        if not is_valid_share_name(share_name):
            raise AzureFilesSearchConfigError("Each file share needs a valid share name.")
        key = (account.account_name, share_name)
        if key in seen:
            continue
        seen.add(key)
        storage_shares.append(StorageShareEntry(account=account, share_name=share_name))
    if permission_mode == PERMISSION_MODE_LIVE_ACL and not storage_shares:
        raise AzureFilesSearchConfigError("Add the storage account and file share that this index was built from.")

    return AzureFilesSearchConfig(
        action_id=_text(manifest.get("id"), 128),
        action_name=_text(manifest.get("name"), 128),
        display_name=_text(manifest.get("displayName") or manifest.get("name") or AZURE_FILES_SEARCH_DISPLAY_NAME, 128),
        endpoint=endpoint,
        index_name=index_name,
        auth_type=auth_type,
        auth_key=auth_key,
        layout=layout,
        content_field=content_field,
        title_field=title_field,
        path_field=path_field,
        name_field=name_field,
        last_modified_field=last_modified_field,
        vector_field=vector_field,
        select_content=select_content,
        query_mode=query_mode,
        semantic_configuration=semantic_configuration,
        default_top_n=_bounded_int(fields.get("default_top_n"), DEFAULT_TOP_N, 1, MAX_TOP_N),
        max_candidates=_bounded_int(fields.get("max_candidates"), DEFAULT_MAX_CANDIDATES, MIN_CANDIDATES, MAX_CANDIDATES),
        max_snippet_chars=_bounded_int(
            fields.get("max_snippet_chars"), DEFAULT_MAX_SNIPPET_CHARS, MIN_SNIPPET_CHARS, MAX_SNIPPET_CHARS,
        ),
        time_budget_seconds=_bounded_int(
            fields.get("time_budget_seconds"), DEFAULT_TIME_BUDGET_SECONDS, MIN_TIME_BUDGET_SECONDS, MAX_TIME_BUDGET_SECONDS,
        ),
        permission_mode=permission_mode,
        share_access_check=share_access_check,
        treat_builtin_users_as_member=_as_bool(fields.get("treat_builtin_users_as_member")),
        storage_shares=tuple(storage_shares),
    )


def internal_search_endpoints(settings: Dict[str, Any]) -> Tuple[str, ...]:
    """Return SimpleChat's own Azure AI Search service origins from settings."""
    endpoints = []
    for key in ("azure_ai_search_endpoint", "target_ai_search_endpoint"):
        try:
            endpoints.append(validate_azure_search_endpoint((settings or {}).get(key)))
        except ValueError:
            continue
    return tuple(dict.fromkeys(endpoints))


def assert_not_internal_index(
    config: AzureFilesSearchConfig,
    settings: Dict[str, Any],
    alias_exists: Optional[Callable[[str], Optional[bool]]] = None,
) -> None:
    """Refuse SimpleChat's own indexes, which hold every workspace's documents.

    On SimpleChat's own search service an index alias could point at an internal index, so
    aliases are refused there too. When the alias lookup fails the index is refused, because
    it cannot be proven safe.
    """
    if config.endpoint not in internal_search_endpoints(settings):
        return
    if config.index_name in INTERNAL_SEARCH_INDEX_NAMES:
        raise AzureFilesSearchConfigError("SimpleChat's own workspace indexes can't be used with Azure Files Search.")
    if alias_exists is None:
        return
    exists = alias_exists(config.index_name)
    if exists is None or exists:
        raise AzureFilesSearchConfigError(
            "Index aliases on SimpleChat's own search service can't be used with Azure Files Search. Use the index name."
        )


def _decode_path_value(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower().startswith("https://"):
        return text
    # Indexers often store the document key as base64 of the path, with a trailing padding digit.
    candidate = text[:-1] if text[-1:].isdigit() else text
    try:
        padded = candidate + "=" * (-len(candidate) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeError):
        return ""
    return decoded if decoded.lower().startswith("https://") else ""


def parse_azure_file_path(value: Any) -> Optional[AzureFilePath]:
    """Parse an indexed Azure Files URL into its account, share, and file path."""
    url = _decode_path_value(value)
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment or parsed.port not in (None, 443):
        return None
    try:
        account_name, endpoint_suffix = azure_storage_endpoint_suffix_for_hostname(
            parsed.hostname.lower(), "file", AZURE_FILE_ENDPOINT_ERROR,
        )
    except ValueError:
        return None
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    if len(segments) < 2:
        return None
    share_name = segments[0].lower()
    file_segments = segments[1:]
    if not is_valid_share_name(share_name) or any(
        segment in {".", ".."} or "\\" in segment or "\x00" in segment for segment in file_segments
    ):
        return None
    host = f"{account_name}.file.{endpoint_suffix}"
    return AzureFilePath(
        url=url,
        file_endpoint=f"https://{host}",
        account_name=account_name,
        endpoint_suffix=endpoint_suffix,
        share_name=share_name,
        relative_path="/".join(file_segments),
        file_name=file_segments[-1],
        unc_path="\\\\" + "\\".join([host, share_name, *file_segments]),
        folder="\\".join(file_segments[:-1]),
    )


def _clip(text: Any, limit: int) -> str:
    normalized = _WHITESPACE_PATTERN.sub(" ", str(text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "\u2026"


def _caption_texts(hit: Dict[str, Any]) -> List[str]:
    texts = []
    for caption in hit.get("@search.captions") or []:
        text = getattr(caption, "text", None)
        if text is None and isinstance(caption, dict):
            text = caption.get("text")
        if text:
            texts.append(str(text))
    return texts


def build_snippet(hit: Dict[str, Any], config: AzureFilesSearchConfig) -> str:
    """Prefer semantic captions, then highlights, then the selected content, clipped."""
    captions = _caption_texts(hit)
    if captions:
        return _clip(" ".join(captions), config.max_snippet_chars)
    highlights = (hit.get("@search.highlights") or {}).get(config.content_field) or []
    if highlights:
        return _clip(" \u2026 ".join(str(item) for item in highlights), config.max_snippet_chars)
    if config.select_content:
        return _clip(hit.get(config.content_field), config.max_snippet_chars)
    return ""


def build_search_request(config: AzureFilesSearchConfig, query: str, vector_query_factory: Optional[Callable[..., Any]]) -> Dict[str, Any]:
    """Build keyword arguments for ``SearchClient.search``; the model controls only the query text."""
    select = [config.path_field, config.name_field]
    for optional_field in (config.title_field, config.last_modified_field):
        if optional_field and optional_field not in select:
            select.append(optional_field)
    if config.select_content and config.content_field not in select:
        select.append(config.content_field)
    request: Dict[str, Any] = {
        "search_text": query,
        "select": select,
        "top": config.max_candidates,
    }
    if not config.select_content:
        request["highlight_fields"] = config.content_field
        request["highlight_pre_tag"] = ""
        request["highlight_post_tag"] = ""
    if config.query_mode in (QUERY_MODE_SEMANTIC, QUERY_MODE_HYBRID) and (
        config.query_mode == QUERY_MODE_SEMANTIC or config.semantic_configuration
    ):
        request["query_type"] = "semantic"
        if config.semantic_configuration:
            request["semantic_configuration_name"] = config.semantic_configuration
        request["query_caption"] = "extractive"
    if config.query_mode == QUERY_MODE_HYBRID and vector_query_factory is not None:
        request["vector_queries"] = [
            vector_query_factory(text=query, k_nearest_neighbors=config.max_candidates, fields=config.vector_field)
        ]
    return request


@dataclass(frozen=True)
class SearchDependencies:
    """I/O used by one search: search hits, file security descriptors, share access, identity."""

    run_search: Callable[[Dict[str, Any]], Sequence[Dict[str, Any]]]
    read_file_sddl: Callable[[AzureFilePath], str]
    check_share_access: Callable[[StorageShareEntry], Tuple[str, str]]
    membership: Optional[Callable[[str], str]]
    evaluate_sddl: Callable[[str, Callable[[str], str]], AccessDecision]
    identity_error_reason: str = ""


def _withheld_entry(path: Optional[AzureFilePath], raw_path: str, decision: AccessDecision) -> Dict[str, Any]:
    entry = {
        "file": path.unc_path if path else _text(raw_path, 512),
        "outcome": decision.outcome,
        "reason": decision.reason,
    }
    if decision.unresolved_sids:
        entry["unresolved_sids"] = list(decision.unresolved_sids[:MAX_LOGGED_UNRESOLVED_SIDS])
    if decision.unsupported_aces:
        entry["unsupported"] = list(decision.unsupported_aces[:MAX_LOGGED_UNRESOLVED_SIDS])
    return entry


def _decide_file(config: AzureFilesSearchConfig, path: Optional[AzureFilePath], dependencies: SearchDependencies) -> AccessDecision:
    if config.permission_mode == PERMISSION_MODE_NONE:
        return AccessDecision(OUTCOME_ALLOWED, REASON_PERMISSION_CHECKS_DISABLED)
    if path is None:
        return AccessDecision(OUTCOME_UNVERIFIED, REASON_PATH_MISSING)
    share = config.find_share(path.account_name, path.share_name)
    if share is None:
        return AccessDecision(OUTCOME_UNVERIFIED, REASON_STORAGE_NOT_ALLOWLISTED)
    if dependencies.membership is None:
        return AccessDecision(OUTCOME_UNVERIFIED, dependencies.identity_error_reason or "identity_unavailable")
    if config.share_access_check == SHARE_ACCESS_CHECK_RBAC:
        share_state, share_reason = dependencies.check_share_access(share)
        if share_state == NOT_MEMBER:
            return AccessDecision(OUTCOME_DENIED, share_reason)
        if share_state != MEMBER:
            return AccessDecision(OUTCOME_UNVERIFIED, share_reason)
    try:
        sddl = dependencies.read_file_sddl(path)
    except AzureFileNotFound:
        return AccessDecision(OUTCOME_UNVERIFIED, REASON_FILE_NOT_FOUND)
    except Exception as error:
        log_event(
            "[AZURE_FILES_SEARCH] Could not read a file's permissions.",
            level=logging.WARNING,
            extra={
                "exception_type": type(error).__name__,
                "storage_account": path.account_name,
                "share": path.share_name,
                "action_id": config.action_id,
            },
        )
        return AccessDecision(OUTCOME_UNVERIFIED, REASON_ACL_READ_FAILED)
    return dependencies.evaluate_sddl(sddl, dependencies.membership)


def _hit_score(hit: Dict[str, Any]) -> Optional[float]:
    for key in ("@search.reranker_score", "@search.rerankerScore", "@search.score"):
        value = hit.get(key)
        if isinstance(value, (int, float)):
            return round(float(value), 4)
    return None


def run_azure_files_search(
    config: AzureFilesSearchConfig,
    query: str,
    top_n: Optional[int],
    dependencies: SearchDependencies,
    vector_query_factory: Optional[Callable[..., Any]] = None,
    clock: Callable[[], float] = time.monotonic,
) -> AzureFilesSearchOutcome:
    """Search the index and keep only results whose files the user is proven able to open."""
    started_at = clock()
    deadline = started_at + config.time_budget_seconds
    limit = _bounded_int(top_n, config.default_top_n, 1, MAX_TOP_N) if top_n else config.default_top_n
    query_text = _text(query, MAX_QUERY_LENGTH)
    outcome = AzureFilesSearchOutcome(results=[])
    if not query_text:
        outcome.error = "Enter what to search for."
        return outcome

    hits = list(dependencies.run_search(build_search_request(config, query_text, vector_query_factory)) or [])
    outcome.candidate_count = len(hits)

    file_order: List[str] = []
    paths: Dict[str, Optional[AzureFilePath]] = {}
    for hit in hits:
        raw_path = str(hit.get(config.path_field) or "")
        key = raw_path or f"missing:{len(file_order)}"
        if key not in paths:
            paths[key] = parse_azure_file_path(raw_path)
            file_order.append(key)
        hit["_simplechat_file_key"] = key

    decisions: Dict[str, AccessDecision] = {}
    executor = ThreadPoolExecutor(max_workers=ACL_EVALUATION_WORKERS, thread_name_prefix="azure-files-acl")
    try:
        futures = {executor.submit(_decide_file, config, paths[key], dependencies): key for key in file_order}
        done, not_done = wait(futures, timeout=max(0.0, deadline - clock()))
        for future in done:
            key = futures[future]
            try:
                decisions[key] = future.result()
            except Exception:
                decisions[key] = AccessDecision(OUTCOME_UNVERIFIED, REASON_ACL_READ_FAILED)
        for future in not_done:
            future.cancel()
            decisions[futures[future]] = AccessDecision(OUTCOME_UNVERIFIED, REASON_TIME_BUDGET_EXCEEDED)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    reasons: Counter = Counter()
    for key in file_order:
        decision = decisions[key]
        outcome.files_evaluated += 1
        if decision.outcome == OUTCOME_ALLOWED:
            outcome.allowed_files += 1
            continue
        reasons[decision.reason] += 1
        if decision.outcome == OUTCOME_DENIED:
            outcome.denied_files += 1
        else:
            outcome.unverified_files += 1
        if len(outcome.withheld_files) < MAX_LOGGED_WITHHELD_FILES:
            outcome.withheld_files.append(_withheld_entry(paths[key], key, decision))
        else:
            outcome.withheld_files_truncated = True
    outcome.reasons = dict(reasons)

    per_file_counts: Counter = Counter()
    for hit in hits:
        key = hit["_simplechat_file_key"]
        if decisions[key].outcome != OUTCOME_ALLOWED or per_file_counts[key] >= MAX_RESULTS_PER_FILE:
            continue
        per_file_counts[key] += 1
        path = paths[key]
        result = {
            "file_name": path.file_name if path else _text(hit.get(config.name_field), 256),
            "unc_path": path.unc_path if path else "",
            "folder": path.folder if path else "",
            "share": path.share_name if path else "",
            "title": _text(hit.get(config.title_field), 512) if config.title_field else "",
            "last_modified": _text(hit.get(config.last_modified_field), 64) if config.last_modified_field else "",
            "snippet": build_snippet(hit, config),
            "score": _hit_score(hit),
        }
        outcome.results.append({name: value for name, value in result.items() if value not in ("", None)})
        if len(outcome.results) >= limit:
            break

    outcome.duration_ms = int((clock() - started_at) * 1000)
    return outcome


def build_model_response(config: AzureFilesSearchConfig, outcome: AzureFilesSearchOutcome) -> Dict[str, Any]:
    """Return what the model sees: only allowed results, never counts of withheld files."""
    if outcome.error:
        return {"results": [], "result_count": 0, "error": outcome.error}
    return {
        "source": config.display_name,
        "results": outcome.results,
        "result_count": len(outcome.results),
        "citation_guidance": "Cite each file by its file name and network path (unc_path).",
    }


def build_review_record(config: AzureFilesSearchConfig, outcome: AzureFilesSearchOutcome) -> Dict[str, Any]:
    """Summarize one search for the admin-only activity log; contains no file content or query text."""
    return {
        "action_id": config.action_id,
        "action_name": config.action_name,
        "display_name": config.display_name,
        "search_service": urlparse(config.endpoint).hostname or "",
        "index_name": config.index_name,
        "permission_mode": config.permission_mode,
        "share_access_check": config.share_access_check,
        "status": "unverified" if outcome.unverified_files else ("denied" if outcome.denied_files else "allowed"),
        "counts": {
            "candidates": outcome.candidate_count,
            "files_evaluated": outcome.files_evaluated,
            "allowed_files": outcome.allowed_files,
            "denied_files": outcome.denied_files,
            "unverified_files": outcome.unverified_files,
            "results_returned": len(outcome.results),
        },
        "reasons": dict(outcome.reasons),
        "withheld_files": list(outcome.withheld_files),
        "withheld_files_truncated": outcome.withheld_files_truncated,
        "duration_ms": outcome.duration_ms,
    }


class SddlCache:
    """Cache security descriptors by permission key; files with identical ACLs share one key."""

    def __init__(self, ttl_seconds: int = 300, max_entries: int = 5000):
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._entries: Dict[Tuple[str, str, str], Tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get_or_load(self, key: Tuple[str, str, str], loader: Callable[[], str]) -> str:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry and entry[0] > now:
                return entry[1]
        value = loader()
        with self._lock:
            if len(self._entries) >= self._max_entries:
                self._entries.clear()
            self._entries[key] = (now + self._ttl_seconds, value)
        return value


def notification_day(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def validate_azure_files_index_action(manifest: Dict[str, Any], settings: Dict[str, Any]) -> AzureFilesSearchConfig:
    """Validate an Azure Files Search action for saving, refusing SimpleChat's own indexes."""
    config = normalize_azure_files_search_config(manifest)
    assert_not_internal_index(config, settings)
    return config
