# functions_azure_files_access.py
"""Resolve who a signed-in user is to Azure Files, and whether a share admits them.

The Azure Files Search action evaluates each candidate file's NTFS DACL itself, because
Azure Files OAuth reads use backup intent and bypass file permissions. This module supplies
the identity side of that evaluation:

* the Windows security identifiers (SIDs) the user and their groups carry, from Microsoft
  Graph (``securityIdentifier`` and ``onPremisesSecurityIdentifier``, plus the SID derived
  from each Entra object ID);
* whether another principal named in an ACL is a different directory object, so its entries
  can be ignored rather than treated as unknown;
* whether the user has share-level access, from the storage account's default share-level
  permission and the user's Azure role assignments on the share.

Every lookup failure resolves to "unknown", which callers treat as unverified.
"""

import logging
import re
import struct
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, Iterable, Optional, Tuple
from urllib.parse import quote

import requests

from functions_appinsights import log_event
from functions_azure_files_acl import MEMBER, NOT_MEMBER, UNKNOWN, normalize_sid

GRAPH_REQUEST_TIMEOUT_SECONDS = 10
ARM_REQUEST_TIMEOUT_SECONDS = 10
PRINCIPALS_CACHE_TTL_SECONDS = 600
SID_LOOKUP_CACHE_TTL_SECONDS = 3600
SHARE_ACCESS_CACHE_TTL_SECONDS = 600
ROLE_DEFINITION_CACHE_TTL_SECONDS = 3600
STORAGE_ACCOUNT_CACHE_TTL_SECONDS = 600
CACHE_MAX_ENTRIES = 5000
MAX_GROUP_PAGES = 25
MAX_ROLE_ASSIGNMENT_PAGES = 10

STORAGE_ACCOUNT_API_VERSION = "2023-05-01"
AUTHORIZATION_API_VERSION = "2022-04-01"
FILE_SHARE_READ_DATA_ACTION = "Microsoft.Storage/storageAccounts/fileServices/fileshares/files/read"
# Default share-level permissions that let every authenticated identity read a share.
READ_GRANTING_DEFAULT_SHARE_PERMISSIONS = frozenset({
    "storagefiledatasmbsharereader",
    "storagefiledatasmbsharecontributor",
    "storagefiledatasmbshareelevatedcontributor",
})

REASON_IDENTITY_UNAVAILABLE = "identity_unavailable"
REASON_SHARE_ACCESS_DENIED = "share_access_denied"
REASON_SHARE_ACCESS_UNKNOWN = "share_access_unknown"
REASON_SHARE_DEFAULT_PERMISSION = "share_default_permission"
REASON_SHARE_ROLE_ASSIGNMENT = "share_role_assignment"

_STORAGE_ACCOUNT_RESOURCE_ID_PATTERN = re.compile(
    r"^/subscriptions/([0-9a-fA-F-]{36})/resourceGroups/([-\w._()]{1,90})"
    r"/providers/Microsoft\.Storage/storageAccounts/([a-z0-9]{3,24})$",
    re.IGNORECASE,
)
_SHARE_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){2,62}$")
_ROLE_DEFINITION_ID_PATTERN = re.compile(
    r"^(/subscriptions/[0-9a-fA-F-]{36})?/providers/Microsoft\.Authorization/roleDefinitions/[0-9a-fA-F-]{36}$",
    re.IGNORECASE,
)

HttpGet = Callable[..., Any]


class AzureFilesIdentityError(RuntimeError):
    """The user's directory identity could not be resolved; access stays unverified."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class _TtlCache:
    """A small thread-safe cache with per-entry expiry and a bounded size."""

    def __init__(self, ttl_seconds: int, max_entries: int = CACHE_MAX_ENTRIES):
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._entries: Dict[Any, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at < time.monotonic():
                self._entries.pop(key, None)
                return None
            return value

    def set(self, key: Any, value: Any, ttl_seconds: Optional[int] = None) -> None:
        with self._lock:
            if len(self._entries) >= self._max_entries:
                now = time.monotonic()
                for stale_key in [k for k, (expires_at, _) in self._entries.items() if expires_at < now]:
                    self._entries.pop(stale_key, None)
                if len(self._entries) >= self._max_entries:
                    self._entries.pop(next(iter(self._entries)))
            self._entries[key] = (time.monotonic() + (ttl_seconds or self._ttl_seconds), value)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_principals_cache = _TtlCache(PRINCIPALS_CACHE_TTL_SECONDS)
_sid_lookup_cache = _TtlCache(SID_LOOKUP_CACHE_TTL_SECONDS)
_share_access_cache = _TtlCache(SHARE_ACCESS_CACHE_TTL_SECONDS)
_role_definition_cache = _TtlCache(ROLE_DEFINITION_CACHE_TTL_SECONDS)
_storage_account_cache = _TtlCache(STORAGE_ACCOUNT_CACHE_TTL_SECONDS)


def clear_azure_files_access_caches() -> None:
    """Drop every cached identity, SID, and share decision."""
    for cache in (_principals_cache, _sid_lookup_cache, _share_access_cache, _role_definition_cache, _storage_account_cache):
        cache.clear()


@dataclass(frozen=True)
class UserPrincipals:
    user_id: str
    sids: FrozenSet[str]
    group_ids: FrozenSet[str]


@dataclass(frozen=True)
class StorageAccountReference:
    resource_id: str
    subscription_id: str
    resource_group: str
    account_name: str


def parse_storage_account_resource_id(value: Any) -> StorageAccountReference:
    """Validate an Azure Storage account resource ID and return its parts."""
    text = str(value or "").strip().rstrip("/")
    match = _STORAGE_ACCOUNT_RESOURCE_ID_PATTERN.match(text)
    if not match:
        raise ValueError(
            "Storage accounts must be Azure resource IDs such as "
            "/subscriptions/<id>/resourceGroups/<group>/providers/Microsoft.Storage/storageAccounts/<account>."
        )
    subscription_id, resource_group, account_name = match.groups()
    account_name = account_name.lower()
    canonical = (
        f"/subscriptions/{subscription_id.lower()}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Storage/storageAccounts/{account_name}"
    )
    return StorageAccountReference(canonical, subscription_id.lower(), resource_group, account_name)


def is_valid_share_name(value: Any) -> bool:
    return bool(_SHARE_NAME_PATTERN.match(str(value or "")))


def entra_object_id_to_sid(object_id: Any) -> str:
    """Return the ``S-1-12-1-...`` SID Microsoft Entra derives from an object ID."""
    try:
        object_uuid = uuid.UUID(str(object_id or ""))
    except ValueError:
        return ""
    parts = struct.unpack("<IIII", object_uuid.bytes_le)
    return "S-1-12-1-" + "-".join(str(part) for part in parts)


def entra_sid_to_object_id(sid: Any) -> str:
    """Return the Entra object ID behind an ``S-1-12-1-a-b-c-d`` SID, or ``""``."""
    match = re.match(r"^S-1-12-1-(\d+)-(\d+)-(\d+)-(\d+)$", normalize_sid(sid))
    if not match:
        return ""
    parts = [int(part) for part in match.groups()]
    if any(part > 0xFFFFFFFF for part in parts):
        return ""
    return str(uuid.UUID(bytes_le=struct.pack("<IIII", *parts)))


def _graph_get(url: str, access_token: str, http_get: HttpGet, consistency: bool = False) -> Any:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    if consistency:
        headers["ConsistencyLevel"] = "eventual"
    return http_get(url, headers=headers, timeout=GRAPH_REQUEST_TIMEOUT_SECONDS)


def _response_json(response: Any) -> Dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _principal_sids(directory_object: Dict[str, Any]) -> Iterable[str]:
    yield normalize_sid(directory_object.get("securityIdentifier"))
    yield normalize_sid(directory_object.get("onPremisesSecurityIdentifier"))
    yield entra_object_id_to_sid(directory_object.get("id"))


def get_user_principals(
    user_id: str,
    access_token: str,
    graph_base_url: str,
    http_get: HttpGet = requests.get,
) -> UserPrincipals:
    """Return the SIDs the signed-in user and every group they belong to carry.

    The delegated token must belong to ``user_id``; a token for anyone else is refused.
    Group membership is transitive. An incomplete membership list raises, because a
    missing group could hide an allow or a deny.
    """
    normalized_user_id = str(user_id or "").strip().lower()
    if not normalized_user_id or not access_token:
        raise AzureFilesIdentityError(REASON_IDENTITY_UNAVAILABLE)
    cached = _principals_cache.get(normalized_user_id)
    if cached is not None:
        return cached

    base_url = graph_base_url.rstrip("/")
    try:
        me_response = _graph_get(
            f"{base_url}/me?$select=id,securityIdentifier,onPremisesSecurityIdentifier",
            access_token,
            http_get,
        )
        if me_response.status_code != 200:
            raise AzureFilesIdentityError(REASON_IDENTITY_UNAVAILABLE)
        me = _response_json(me_response)
        if str(me.get("id") or "").lower() != normalized_user_id:
            raise AzureFilesIdentityError(REASON_IDENTITY_UNAVAILABLE)

        sids = set(_principal_sids(me))
        group_ids = set()
        next_url = (
            f"{base_url}/me/transitiveMemberOf/microsoft.graph.group"
            "?$select=id,securityIdentifier,onPremisesSecurityIdentifier&$top=999"
        )
        for _ in range(MAX_GROUP_PAGES):
            response = _graph_get(next_url, access_token, http_get)
            if response.status_code != 200:
                raise AzureFilesIdentityError(REASON_IDENTITY_UNAVAILABLE)
            payload = _response_json(response)
            for group in payload.get("value") or []:
                if isinstance(group, dict) and group.get("id"):
                    group_ids.add(str(group["id"]).lower())
                    sids.update(_principal_sids(group))
            next_url = payload.get("@odata.nextLink")
            if not next_url:
                break
        else:
            raise AzureFilesIdentityError(REASON_IDENTITY_UNAVAILABLE)
    except AzureFilesIdentityError:
        raise
    except Exception as error:
        log_event(
            "[AZURE_FILES_SEARCH] Could not resolve the user's directory principals.",
            level=logging.WARNING,
            extra={"exception_type": type(error).__name__},
        )
        raise AzureFilesIdentityError(REASON_IDENTITY_UNAVAILABLE) from error

    principals = UserPrincipals(
        user_id=normalized_user_id,
        sids=frozenset(sid for sid in sids if sid),
        group_ids=frozenset(group_ids),
    )
    _principals_cache.set(normalized_user_id, principals)
    return principals


def classify_foreign_sid(
    sid: str,
    access_token: str,
    graph_base_url: str,
    http_get: HttpGet = requests.get,
) -> str:
    """Return ``not_member`` when another directory object owns ``sid``, else ``unknown``.

    Called only for SIDs that are not the user's own or one of their groups'. A SID that
    belongs to another Entra user, or to a group whose membership is fully known, does not
    apply to the user. A SID the directory cannot place (an AD-only group, a local or
    deleted account, another tenant) stays unknown.
    """
    normalized = normalize_sid(sid)
    if not normalized or not access_token:
        return UNKNOWN
    cached = _sid_lookup_cache.get(normalized)
    if cached is not None:
        return cached

    base_url = graph_base_url.rstrip("/")
    state = UNKNOWN
    cacheable = True
    try:
        object_id = entra_sid_to_object_id(normalized)
        if object_id:
            for collection in ("groups", "users"):
                response = _graph_get(f"{base_url}/{collection}/{object_id}?$select=id", access_token, http_get)
                if response.status_code == 200:
                    state = NOT_MEMBER
                    break
                if response.status_code != 404:
                    cacheable = False
                    break
        else:
            for collection, attribute in (
                ("groups", "securityIdentifier"),
                ("groups", "onPremisesSecurityIdentifier"),
                ("users", "onPremisesSecurityIdentifier"),
            ):
                response = _graph_get(
                    f"{base_url}/{collection}?$filter={attribute}%20eq%20'{quote(normalized, safe='-')}'"
                    "&$select=id&$top=1&$count=true",
                    access_token,
                    http_get,
                    consistency=True,
                )
                if response.status_code != 200:
                    cacheable = False
                    continue
                if _response_json(response).get("value"):
                    state = NOT_MEMBER
                    break
    except Exception as error:
        log_event(
            "[AZURE_FILES_SEARCH] Could not look up a principal named in a file ACL.",
            level=logging.WARNING,
            extra={"exception_type": type(error).__name__},
        )
        return UNKNOWN

    if state == NOT_MEMBER or cacheable:
        _sid_lookup_cache.set(normalized, state)
    return state


def _action_matches(pattern: str, action: str) -> bool:
    regex = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
    return re.match(regex, action, re.IGNORECASE) is not None


def role_definition_grants_file_read(role_definition: Dict[str, Any]) -> bool:
    """Return whether a role definition's data actions include reading file share data."""
    for permission in (role_definition.get("properties") or {}).get("permissions") or []:
        data_actions = permission.get("dataActions") or []
        not_data_actions = permission.get("notDataActions") or []
        if any(_action_matches(pattern, FILE_SHARE_READ_DATA_ACTION) for pattern in data_actions) and not any(
            _action_matches(pattern, FILE_SHARE_READ_DATA_ACTION) for pattern in not_data_actions
        ):
            return True
    return False


def _arm_get(url: str, access_token: str, http_get: HttpGet) -> Any:
    return http_get(
        url,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=ARM_REQUEST_TIMEOUT_SECONDS,
    )


def _default_share_permission(account: StorageAccountReference, arm_base_url: str, arm_token: str, http_get: HttpGet) -> str:
    cached = _storage_account_cache.get(account.resource_id)
    if cached is not None:
        return cached
    response = _arm_get(f"{arm_base_url}{account.resource_id}?api-version={STORAGE_ACCOUNT_API_VERSION}", arm_token, http_get)
    if response.status_code != 200:
        raise RuntimeError("storage_account_unreadable")
    identity_auth = (_response_json(response).get("properties") or {}).get("azureFilesIdentityBasedAuthentication") or {}
    permission = str(identity_auth.get("defaultSharePermission") or "None").replace("_", "").lower()
    _storage_account_cache.set(account.resource_id, permission)
    return permission


def _role_definition(role_definition_id: str, arm_base_url: str, arm_token: str, http_get: HttpGet) -> Dict[str, Any]:
    cache_key = role_definition_id.lower()
    cached = _role_definition_cache.get(cache_key)
    if cached is not None:
        return cached
    if not _ROLE_DEFINITION_ID_PATTERN.match(role_definition_id):
        raise RuntimeError("role_definition_invalid")
    response = _arm_get(f"{arm_base_url}{role_definition_id}?api-version={AUTHORIZATION_API_VERSION}", arm_token, http_get)
    if response.status_code != 200:
        raise RuntimeError("role_definition_unreadable")
    definition = _response_json(response)
    _role_definition_cache.set(cache_key, definition)
    return definition


def check_share_level_access(
    user_id: str,
    account: StorageAccountReference,
    share_name: str,
    arm_base_url: str,
    get_arm_token: Callable[[], str],
    http_get: HttpGet = requests.get,
) -> Tuple[str, str]:
    """Return ``(state, reason)`` for whether share-level permissions admit the user.

    A default share-level permission that grants read admits every authenticated identity.
    Otherwise the user's role assignments at, above, or (through groups) for the share are
    checked for a role whose data actions include reading files. Role assignments carrying
    conditions are not evaluated and leave access unknown.
    """
    normalized_user_id = str(user_id or "").strip().lower()
    if not normalized_user_id or not is_valid_share_name(share_name):
        return UNKNOWN, REASON_SHARE_ACCESS_UNKNOWN
    cache_key = (normalized_user_id, account.resource_id, share_name)
    cached = _share_access_cache.get(cache_key)
    if cached is not None:
        return cached

    arm_base_url = arm_base_url.rstrip("/")
    try:
        arm_token = get_arm_token()
        if _default_share_permission(account, arm_base_url, arm_token, http_get) in READ_GRANTING_DEFAULT_SHARE_PERMISSIONS:
            decision = (MEMBER, REASON_SHARE_DEFAULT_PERMISSION)
            _share_access_cache.set(cache_key, decision)
            return decision

        share_scope = f"{account.resource_id}/fileServices/default/fileshares/{share_name}"
        next_url = (
            f"{arm_base_url}{share_scope}/providers/Microsoft.Authorization/roleAssignments"
            f"?api-version={AUTHORIZATION_API_VERSION}&$filter=assignedTo('{normalized_user_id}')"
        )
        conditional_grant = False
        for _ in range(MAX_ROLE_ASSIGNMENT_PAGES):
            response = _arm_get(next_url, arm_token, http_get)
            if response.status_code != 200:
                raise RuntimeError("role_assignments_unreadable")
            payload = _response_json(response)
            for assignment in payload.get("value") or []:
                properties = (assignment or {}).get("properties") or {}
                role_definition_id = str(properties.get("roleDefinitionId") or "")
                if not role_definition_id:
                    continue
                if not role_definition_grants_file_read(_role_definition(role_definition_id, arm_base_url, arm_token, http_get)):
                    continue
                if properties.get("condition"):
                    conditional_grant = True
                    continue
                decision = (MEMBER, REASON_SHARE_ROLE_ASSIGNMENT)
                _share_access_cache.set(cache_key, decision)
                return decision
            next_url = payload.get("nextLink")
            if not next_url:
                break
        else:
            raise RuntimeError("role_assignments_incomplete")
    except Exception as error:
        log_event(
            "[AZURE_FILES_SEARCH] Could not check share-level permissions.",
            level=logging.WARNING,
            extra={"exception_type": type(error).__name__, "storage_account": account.account_name, "share": share_name},
        )
        return UNKNOWN, REASON_SHARE_ACCESS_UNKNOWN

    decision = (UNKNOWN, REASON_SHARE_ACCESS_UNKNOWN) if conditional_grant else (NOT_MEMBER, REASON_SHARE_ACCESS_DENIED)
    _share_access_cache.set(cache_key, decision)
    return decision
