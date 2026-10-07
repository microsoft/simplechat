# functions_azure_files_search_runtime.py
"""Connect the Azure Files Search action to Azure AI Search, Azure Files, Graph, and ARM.

``functions_azure_files_search`` holds the search and permission logic with its I/O injected.
This module supplies the real clients, records each search for administrators, and runs the
admin connection test. The application identity reads the customer's search index (Search
Index Data Reader) and each file's security descriptor (Storage File Data Privileged Reader,
backup intent); the signed-in user's delegated Graph token resolves their group SIDs.
"""

import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizableTextQuery
from azure.storage.fileshare import ShareServiceClient

from config import AZURE_ENVIRONMENT, resource_manager, search_resource_manager
from functions_action_manifest import get_action_origin
from functions_appinsights import log_event
from functions_authentication import get_graph_base_url, get_valid_access_token
from functions_azure_files_access import (
    AzureFilesIdentityError,
    check_share_level_access,
    classify_foreign_sid,
    get_user_principals,
)
from functions_azure_files_acl import MEMBER, NOT_MEMBER, build_membership, evaluate_sddl_read_access
from functions_azure_files_search import (
    AZURE_FILES_SEARCH_UNVERIFIED_NOTIFICATION_TYPE,
    PERMISSION_MODE_NONE,
    SHARE_ACCESS_CHECK_RBAC,
    AzureFilePath,
    AzureFileNotFound,
    AzureFilesSearchConfig,
    AzureFilesSearchConfigError,
    AzureFilesSearchOutcome,
    SddlCache,
    SearchDependencies,
    StorageShareEntry,
    assert_not_internal_index,
    build_model_response,
    build_review_record,
    build_search_request,
    normalize_azure_files_search_config,
    notification_day,
    parse_azure_file_path,
    run_azure_files_search,
)

# The GA Search API cannot address index aliases, so a configured name always means one index.
AZURE_FILES_SEARCH_API_VERSION = "2024-07-01"
AZURE_FILES_TOKEN_INTENT = "backup"
SEARCH_CONNECTION_TIMEOUT_SECONDS = 10
SEARCH_READ_TIMEOUT_SECONDS = 30
FILE_REQUEST_TIMEOUT_SECONDS = 10
UNAVAILABLE_MESSAGE = "Azure Files Search is unavailable right now. Try again later."
MISCONFIGURED_MESSAGE = "This Azure Files Search action isn't configured correctly. Ask an administrator to check it."
SIGNED_OUT_MESSAGE = "Azure Files Search needs a signed-in user."

_credential_lock = threading.Lock()
_credential: Optional[DefaultAzureCredential] = None
_share_service_clients: Dict[str, ShareServiceClient] = {}
_share_service_lock = threading.Lock()
_sddl_cache = SddlCache()


class AzureFilesSearchUnavailable(RuntimeError):
    """A search request failed; ``public_message`` is a reviewed, actionable explanation."""

    def __init__(self, code: str, public_message: str):
        self.code = code
        self.public_message = public_message
        super().__init__(code)


def _app_credential() -> DefaultAzureCredential:
    global _credential
    with _credential_lock:
        if _credential is None:
            _credential = DefaultAzureCredential()
        return _credential


def _search_client(config: AzureFilesSearchConfig) -> SearchClient:
    options: Dict[str, Any] = {
        "api_version": AZURE_FILES_SEARCH_API_VERSION,
        "connection_timeout": SEARCH_CONNECTION_TIMEOUT_SECONDS,
        "read_timeout": SEARCH_READ_TIMEOUT_SECONDS,
    }
    if config.auth_type == "key":
        credential: Any = AzureKeyCredential(config.auth_key)
    else:
        credential = _app_credential()
        if AZURE_ENVIRONMENT in ("usgovernment", "custom"):
            options["audience"] = search_resource_manager
    return SearchClient(endpoint=config.endpoint, index_name=config.index_name, credential=credential, **options)


def classify_search_error(error: Exception, config: AzureFilesSearchConfig) -> AzureFilesSearchUnavailable:
    """Map an Azure AI Search failure to a reviewed message an administrator can act on."""
    status_code = getattr(error, "status_code", None)
    detail = str(getattr(error, "message", "") or "").lower()
    if status_code in (401, 403):
        if config.auth_type == "key":
            return AzureFilesSearchUnavailable(
                "search_access_denied", "Azure AI Search rejected the query key. Check the key stored for this action.",
            )
        return AzureFilesSearchUnavailable(
            "search_access_denied",
            "Azure AI Search denied the query. Give SimpleChat's managed identity the Search Index Data Reader role "
            "on the search service, and enable role-based access on the service.",
        )
    if status_code == 404 or isinstance(error, ResourceNotFoundError):
        return AzureFilesSearchUnavailable("search_index_not_found", "The search index wasn't found on the search service.")
    if status_code == 400 and "semantic" in detail:
        return AzureFilesSearchUnavailable(
            "search_semantic_unavailable",
            "The index has no usable semantic configuration. Enter its name, or use keyword or hybrid search.",
        )
    if status_code == 400 and ("vector" in detail or "vectorizer" in detail):
        return AzureFilesSearchUnavailable(
            "search_vector_unavailable",
            "The vector field has no vectorizer, so hybrid search can't run. Use keyword or semantic search.",
        )
    if status_code == 400:
        return AzureFilesSearchUnavailable(
            "search_request_invalid",
            "Azure AI Search rejected the request. Check that the configured field names exist and are retrievable.",
        )
    return AzureFilesSearchUnavailable("search_unavailable", UNAVAILABLE_MESSAGE)


def _run_search_for(config: AzureFilesSearchConfig) -> Callable[[Dict[str, Any]], List[Dict[str, Any]]]:
    def run(request: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            hits = []
            for hit in _search_client(config).search(**request):
                hits.append(dict(hit))
                if len(hits) >= config.max_candidates:
                    break
            return hits
        except HttpResponseError as error:
            raise classify_search_error(error, config) from error

    return run


def _share_service_client(file_endpoint: str) -> ShareServiceClient:
    with _share_service_lock:
        client = _share_service_clients.get(file_endpoint)
        if client is None:
            client = ShareServiceClient(
                account_url=file_endpoint,
                credential=_app_credential(),
                token_intent=AZURE_FILES_TOKEN_INTENT,
                connection_timeout=FILE_REQUEST_TIMEOUT_SECONDS,
                read_timeout=FILE_REQUEST_TIMEOUT_SECONDS,
            )
            _share_service_clients[file_endpoint] = client
        return client


def read_file_sddl(path: AzureFilePath) -> str:
    """Read a file's security descriptor; files with identical ACLs share one cached lookup."""
    share_client = _share_service_client(path.file_endpoint).get_share_client(path.share_name)
    try:
        properties = share_client.get_file_client(path.relative_path).get_file_properties(
            timeout=FILE_REQUEST_TIMEOUT_SECONDS,
        )
    except ResourceNotFoundError as error:
        raise AzureFileNotFound("file_not_found") from error
    permission_key = str(getattr(properties, "permission_key", "") or "")
    if not permission_key:
        raise RuntimeError("permission_key_missing")
    return _sddl_cache.get_or_load(
        (path.account_name, path.share_name, permission_key),
        lambda: share_client.get_permission_for_share(permission_key, timeout=FILE_REQUEST_TIMEOUT_SECONDS),
    )


def _arm_token() -> str:
    return _app_credential().get_token(f"{resource_manager.rstrip('/')}/.default").token


def _check_share_access_for(user_id: str) -> Callable[[StorageShareEntry], Tuple[str, str]]:
    def check(share: StorageShareEntry) -> Tuple[str, str]:
        return check_share_level_access(user_id, share.account, share.share_name, resource_manager, _arm_token)

    return check


def build_user_membership(config: AzureFilesSearchConfig, user_id: str) -> Tuple[Optional[Callable[[str], str]], str]:
    """Resolve the signed-in user's SIDs; ``(None, reason)`` when they cannot be resolved."""
    access_token = get_valid_access_token()
    if not access_token:
        return None, "identity_unavailable"
    graph_base_url = get_graph_base_url()
    try:
        principals = get_user_principals(user_id, access_token, graph_base_url)
    except AzureFilesIdentityError as error:
        return None, error.reason
    membership = build_membership(
        principals.sids,
        treat_builtin_users_as_member=config.treat_builtin_users_as_member,
        resolve_unknown_sid=lambda sid: classify_foreign_sid(sid, access_token, graph_base_url),
    )
    return membership, ""


def record_azure_files_search_review(
    config: AzureFilesSearchConfig,
    user_id: str,
    outcome: AzureFilesSearchOutcome,
) -> None:
    """Record a search for administrators: always in telemetry, in activity logs when files were withheld."""
    review = build_review_record(config, outcome)
    log_event(
        "[AZURE_FILES_SEARCH] Search completed.",
        extra={"user_id": user_id, **{key: value for key, value in review.items() if key != "withheld_files"}},
        level=logging.INFO,
    )
    if not outcome.withheld_count:
        return
    try:
        # Imported at use: plugin discovery imports this module, and activity logging and
        # notifications pull in workspace and workflow modules that discovery doesn't need.
        from functions_activity_logging import log_azure_files_search_access

        log_azure_files_search_access(user_id=user_id, review=review)
    except Exception as error:
        log_event(
            "[AZURE_FILES_SEARCH] Failed to record the access review.",
            level=logging.WARNING,
            extra={"exception_type": type(error).__name__, "action_id": config.action_id},
        )
    if outcome.unverified_files:
        _notify_admins_of_unverified_results(config, review)


def _notify_admins_of_unverified_results(config: AzureFilesSearchConfig, review: Dict[str, Any]) -> None:
    try:
        # Imported at use for the same reason as the activity-logging hook above.
        from functions_notifications import create_notification

        create_notification(
            notification_type=AZURE_FILES_SEARCH_UNVERIFIED_NOTIFICATION_TYPE,
            title=f"Azure Files Search could not verify file permissions: {config.display_name}",
            message=(
                "Some results were withheld because their file permissions could not be verified. "
                "Review the Azure Files Search access entries in the Control Center activity logs."
            ),
            link_url="/admin/control-center",
            link_context={"activity_type": "azure_files_search_access", "action_id": config.action_id},
            metadata={
                "action_id": config.action_id,
                "index_name": config.index_name,
                "reasons": review.get("reasons", {}),
            },
            assignment={"roles": ["Admin"]},
            idempotency_key=f"azure-files-search-unverified:{config.action_id or config.index_name}:{notification_day()}",
        )
    except Exception as error:
        log_event(
            "[AZURE_FILES_SEARCH] Failed to notify administrators about unverified results.",
            level=logging.WARNING,
            extra={"exception_type": type(error).__name__, "action_id": config.action_id},
        )


def execute_azure_files_search(
    manifest: Dict[str, Any],
    query: str,
    top_n: Optional[int],
    user_id: str,
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    """Run one Azure Files Search for the signed-in user and return the model-facing response."""
    if not user_id:
        return {"results": [], "result_count": 0, "error": SIGNED_OUT_MESSAGE}
    origin = get_action_origin(manifest)
    # Like MCP, require the origin bound by the authorized global-action lookup; a copied or
    # rebuilt manifest without one can't prove it is an administrator-managed global action.
    if origin is None or origin.scope_type != "global":
        log_event(
            "[AZURE_FILES_SEARCH] Refused an action that is not a bound global action.",
            level=logging.WARNING,
            extra={
                "action_id": str((manifest or {}).get("id") or ""),
                "scope_type": origin.scope_type if origin is not None else "unbound",
            },
        )
        return {"results": [], "result_count": 0, "error": MISCONFIGURED_MESSAGE}
    try:
        config = normalize_azure_files_search_config(manifest)
        assert_not_internal_index(config, settings)
    except AzureFilesSearchConfigError as error:
        log_event(
            "[AZURE_FILES_SEARCH] Action configuration rejected at run time.",
            level=logging.WARNING,
            extra={"action_id": str((manifest or {}).get("id") or ""), "reason": error.public_message},
        )
        return {"results": [], "result_count": 0, "error": MISCONFIGURED_MESSAGE}

    membership, identity_reason = (None, "")
    if config.permission_mode != PERMISSION_MODE_NONE:
        membership, identity_reason = build_user_membership(config, user_id)
    dependencies = SearchDependencies(
        run_search=_run_search_for(config),
        read_file_sddl=read_file_sddl,
        check_share_access=_check_share_access_for(user_id),
        membership=membership,
        evaluate_sddl=evaluate_sddl_read_access,
        identity_error_reason=identity_reason,
    )
    try:
        outcome = run_azure_files_search(config, query, top_n, dependencies, vector_query_factory=VectorizableTextQuery)
    except AzureFilesSearchUnavailable as error:
        log_event(
            "[AZURE_FILES_SEARCH] Search request failed.",
            level=logging.WARNING,
            extra={"action_id": config.action_id, "index_name": config.index_name, "error_code": error.code},
        )
        return {"results": [], "result_count": 0, "error": UNAVAILABLE_MESSAGE}
    except Exception as error:
        log_event(
            "[AZURE_FILES_SEARCH] Search failed unexpectedly.",
            level=logging.ERROR,
            extra={"action_id": config.action_id, "exception_type": type(error).__name__},
            exceptionTraceback=True,
        )
        return {"results": [], "result_count": 0, "error": UNAVAILABLE_MESSAGE}

    record_azure_files_search_review(config, user_id, outcome)
    return build_model_response(config, outcome)


def _check(name: str, status: str, message: str) -> Dict[str, str]:
    return {"name": name, "status": status, "message": message}


def check_azure_files_search_connection(
    manifest: Dict[str, Any],
    user_id: str,
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    """Check an Azure Files Search configuration end to end for the administrator running the test."""
    checks: List[Dict[str, str]] = []
    try:
        config = normalize_azure_files_search_config(manifest)
        assert_not_internal_index(config, settings)
    except AzureFilesSearchConfigError as error:
        return {"success": False, "checks": [_check("configuration", "fail", error.public_message)]}
    checks.append(_check("configuration", "pass", "The configuration is valid."))

    sample_hits: List[Dict[str, Any]] = []
    try:
        request = {"search_text": "*", "select": [config.path_field, config.name_field], "top": 25}
        sample_hits = _run_search_for(config)(request)
        checks.append(_check("search_access", "pass", f"SimpleChat queried the index and read {len(sample_hits)} sample documents."))
    except AzureFilesSearchUnavailable as error:
        checks.append(_check("search_access", "fail", error.public_message))
        return {"success": False, "checks": checks}

    sample_paths = [parse_azure_file_path(hit.get(config.path_field)) for hit in sample_hits]
    parsed_paths = [path for path in sample_paths if path is not None]
    if not sample_hits:
        checks.append(_check("file_paths", "warn", "The index returned no documents, so file paths couldn't be checked."))
    elif not parsed_paths:
        checks.append(_check(
            "file_paths", "fail",
            f"The {config.path_field} field doesn't contain Azure Files URLs, so file permissions can't be checked.",
        ))
    else:
        checks.append(_check("file_paths", "pass", f"{len(parsed_paths)} sample documents have Azure Files paths."))

    if config.query_mode != "keyword":
        try:
            _run_search_for(config)(
                {**_mode_probe_request(config), "top": 1}
            )
            checks.append(_check("query_mode", "pass", f"{config.query_mode.capitalize()} search works on this index."))
        except AzureFilesSearchUnavailable as error:
            checks.append(_check("query_mode", "fail", error.public_message))

    if config.permission_mode == PERMISSION_MODE_NONE:
        checks.append(_check(
            "permissions", "warn",
            "File permission checks are off. Everyone who can use this action can search every file in the index.",
        ))
        return {"success": all(check["status"] != "fail" for check in checks), "checks": checks}

    membership, identity_reason = build_user_membership(config, user_id)
    if membership is None:
        checks.append(_check(
            "identity", "fail",
            "SimpleChat couldn't read your group memberships from Microsoft Graph, so file permissions can't be checked. "
            "Sign out and back in, and confirm the app registration has Group.Read.All consent.",
        ))
    else:
        checks.append(_check("identity", "pass", "SimpleChat resolved your directory groups."))

    for share in config.storage_shares:
        label = f"{share.account.account_name}/{share.share_name}"
        if config.share_access_check == SHARE_ACCESS_CHECK_RBAC:
            state, _reason = _check_share_access_for(user_id)(share)
            if state in (MEMBER, NOT_MEMBER):
                checks.append(_check(f"share_access:{label}", "pass", f"SimpleChat read share-level permissions for {label}."))
            else:
                checks.append(_check(
                    f"share_access:{label}", "fail",
                    f"SimpleChat couldn't read share-level permissions for {label}. Give its managed identity the Reader "
                    "role on the storage account, or turn off the share-level check.",
                ))
        share_path = next(
            (path for path in parsed_paths if path.account_name == share.account.account_name and path.share_name == share.share_name),
            None,
        )
        if share_path is None:
            checks.append(_check(f"file_permissions:{label}", "warn", f"No sample document came from {label}, so file permissions weren't read."))
            continue
        try:
            read_file_sddl(share_path)
            checks.append(_check(f"file_permissions:{label}", "pass", f"SimpleChat read file permissions in {label}."))
        except AzureFileNotFound:
            checks.append(_check(f"file_permissions:{label}", "warn", f"A sample file in {label} no longer exists. The index may be stale."))
        except Exception as error:
            log_event(
                "[AZURE_FILES_SEARCH] Connection test could not read file permissions.",
                level=logging.WARNING,
                extra={"exception_type": type(error).__name__, "storage_account": share.account.account_name},
            )
            checks.append(_check(
                f"file_permissions:{label}", "fail",
                f"SimpleChat couldn't read file permissions in {label}. Give its managed identity the Storage File Data "
                "Privileged Reader role on the storage account or share, and allow it through the storage firewall.",
            ))

    unlisted = sorted({
        f"{path.account_name}/{path.share_name}" for path in parsed_paths
        if config.find_share(path.account_name, path.share_name) is None
    })
    if unlisted:
        checks.append(_check(
            "storage_allowlist", "warn",
            "The index contains files from shares that aren't listed, and those results will be withheld: " + ", ".join(unlisted[:5]),
        ))
    return {"success": all(check["status"] != "fail" for check in checks), "checks": checks}


def _mode_probe_request(config: AzureFilesSearchConfig) -> Dict[str, Any]:
    request = build_search_request(config, "test", VectorizableTextQuery)
    request["select"] = [config.path_field]
    request.pop("highlight_fields", None)
    request.pop("highlight_pre_tag", None)
    request.pop("highlight_post_tag", None)
    return request
