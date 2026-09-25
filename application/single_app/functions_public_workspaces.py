# functions_public_workspaces.py

from config import *
import functions_authentication
import functions_settings
from functions_group import *
from typing import Iterable

from functions_chat_bootstrap_cache import bump_chat_bootstrap_global_cache_version
from functions_workspace_branding import (
    DEFAULT_WORKSPACE_HERO_COLOR,
    get_workspace_logo_metadata,
    normalize_workspace_hero_color,
)


# How many times a conditional public-workspace write re-reads and re-applies its
# change after losing a race to another writer before it reports a conflict.
PUBLIC_DOCUMENT_WRITE_ATTEMPTS = 3


class PublicWorkspaceDocumentWriteConflict(RuntimeError):
    """The public workspace document kept changing while a write was being applied to it."""


# Every public route answers PublicWorkspaceDocumentWriteConflict the same way: 409
# with this code and this reviewed sentence. Other modules import these rather than
# copy them.
PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE = "public_workspace_write_conflict"
PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE = "The public workspace changed while your request was being saved. Try again."


def _stored_public_workspace_fields(document):
    """A public workspace document without the Cosmos system properties (``_etag``, ``_ts``, ...)."""
    return {key: value for key, value in (document or {}).items() if not key.startswith("_")}


def update_public_workspace_document_with_etag_guard(ws_id, apply_changes, *, cache_reason, attempts=PUBLIC_DOCUMENT_WRITE_ATTEMPTS):
    """Apply one change to the stored public workspace document and write it back conditionally.

    The public workspace document also carries membership, status and every other
    workspace-scoped setting, so a writer that changes one part of it must never
    restore the rest from an outdated copy. ``apply_changes`` receives a private copy
    of the document just read and returns the document to write; the replace is
    conditional on that read's ``_etag`` (``IfNotModified``). When another writer lands
    in between, the document is read again and ``apply_changes`` is re-applied to the
    newer copy, up to ``attempts`` writes, after which
    ``PublicWorkspaceDocumentWriteConflict`` is raised. Because it can run more than
    once, ``apply_changes`` must derive its result only from the copy it is given;
    raising from it abandons the write with nothing stored.

    A workspace that is missing at read time or at replace time is never recreated: the
    function returns ``None`` and writes nothing. When a re-read finds exactly the body
    this call sent, the earlier replace committed and only its response was lost (a
    transport retry of a committed write fails its own precondition), so that is
    reported as the committed write rather than as a conflict.

    A committed write returns the stored document and bumps the global chat bootstrap
    cache with ``cache_reason``. ``cache_reason`` is required, and ``None`` is the
    explicit choice for a change no bootstrap payload reads, such as a join request,
    which commits without a bump.
    """
    attempted = None
    for attempt in range(attempts + 1):
        try:
            current = cosmos_public_workspaces_container.read_item(item=ws_id, partition_key=ws_id)
        except exceptions.CosmosResourceNotFoundError:
            return None
        if attempted is not None and _stored_public_workspace_fields(current) == _stored_public_workspace_fields(attempted):
            if cache_reason is not None:
                bump_chat_bootstrap_global_cache_version(reason=cache_reason)
            return current
        if attempt == attempts:
            break
        attempted = apply_changes(copy.deepcopy(current))
        try:
            written = cosmos_public_workspaces_container.replace_item(
                item=ws_id,
                body=attempted,
                etag=current.get("_etag"),
                match_condition=MatchConditions.IfNotModified,
            )
        except exceptions.CosmosResourceNotFoundError:
            return None
        except exceptions.CosmosAccessConditionFailedError:
            continue
        if cache_reason is not None:
            bump_chat_bootstrap_global_cache_version(reason=cache_reason)
        return written
    raise PublicWorkspaceDocumentWriteConflict("The public workspace document kept changing while it was being saved.")

def create_public_workspace(name: str, description: str) -> dict:
    """
    Creates a new public workspace. The creator becomes the Owner by default.
    """
    user_info = functions_authentication.get_current_user_info()
    if not user_info:
        raise Exception("No user in session")

    new_id = str(uuid.uuid4())
    now_iso = datetime.utcnow().isoformat()

    ws_doc = {
        "id": new_id,
        "name": name,
        "description": description,
        "heroColor": DEFAULT_WORKSPACE_HERO_COLOR,
        "logoBase64": "",
        "logoVersion": 1,
        "owner": {
            "userId": user_info["userId"],
            "email": user_info["email"],
            "displayName": user_info["displayName"]
        },
        "admins": [],
        "documentManagers": [],
        "pendingDocumentManagers": [],
        "disable_file_downloads": False,
        "createdDate": now_iso,
        "modifiedDate": now_iso
    }
    cosmos_public_workspaces_container.create_item(ws_doc)
    bump_chat_bootstrap_global_cache_version(reason="public_workspace_created")
    return ws_doc


def find_public_workspace_by_id(ws_id: str) -> dict | None:
    """
    Retrieve a single public workspace document by its ID.
    """
    try:
        return cosmos_public_workspaces_container.read_item(
            item=ws_id,
            partition_key=ws_id
        )
    except exceptions.CosmosResourceNotFoundError:
        return None


def get_user_public_workspaces(user_id: str) -> list:
    """
    Fetch all public workspaces for which this user is Owner, Admin, or DocumentManager.
    """
    query = """
        SELECT * FROM c
        WHERE c.owner.userId = @uid
           OR ARRAY_CONTAINS(c.admins, @uid)
           OR EXISTS (
               SELECT VALUE dm
               FROM dm IN c.documentManagers
               WHERE dm.userId = @uid
           )
    """
    params = [{"name": "@uid", "value": user_id}]
    return list(cosmos_public_workspaces_container.query_items(
        query=query,
        parameters=params,
        enable_cross_partition_query=True
    ))


def get_all_public_workspaces() -> list:
    """
    Fetch all public workspaces visible to authenticated users.
    """
    return list(cosmos_public_workspaces_container.query_items(
        query="SELECT * FROM c",
        enable_cross_partition_query=True
    ))


def search_public_workspaces(search_query: str, user_id: str) -> list:
    """
    Return the user's public workspaces matching the search term in name or description.
    """
    base_query = """
        SELECT * FROM c
        WHERE (c.owner.userId = @uid
            OR ARRAY_CONTAINS(c.admins, @uid)
            OR EXISTS (
                SELECT VALUE dm
                FROM dm IN c.documentManagers
                WHERE dm.userId = @uid
            ))
    """
    params = [{"name": "@uid", "value": user_id}]

    if search_query:
        base_query += " AND (CONTAINS(LOWER(c.name), @search) OR CONTAINS(LOWER(c.description), @search))"
        params.append({"name": "@search", "value": search_query.lower()})

    return list(cosmos_public_workspaces_container.query_items(
        query=base_query,
        parameters=params,
        enable_cross_partition_query=True
    ))


def search_all_public_workspaces(search_query: str) -> list:
    """
    Return all public workspaces matching the search term in name or description.
    """
    base_query = "SELECT * FROM c"
    params = []

    if search_query:
        base_query += " WHERE CONTAINS(LOWER(c.name), @search) OR CONTAINS(LOWER(c.description), @search)"
        params.append({"name": "@search", "value": search_query.lower()})

    return list(cosmos_public_workspaces_container.query_items(
        query=base_query,
        parameters=params,
        enable_cross_partition_query=True
    ))


def delete_public_workspace(ws_id: str) -> None:
    """
    Deletes a public workspace from Cosmos DB. Typically only the owner may call this.
    """
    cosmos_public_workspaces_container.delete_item(
        item=ws_id,
        partition_key=ws_id
    )
    bump_chat_bootstrap_global_cache_version(reason="public_workspace_deleted")


def get_user_role_in_public_workspace(ws_doc: dict, user_id: str) -> str | None:
    """
    Determine the user's effective role in the given public workspace doc.
    """
    if not ws_doc or not user_id:
        return None
    if ws_doc.get("owner", {}).get("userId") == user_id:
        return "Owner"
    for admin in ws_doc.get("admins", []):
        if isinstance(admin, str) and admin == user_id:
            return "Admin"
        if isinstance(admin, dict) and admin.get("userId") == user_id:
            return "Admin"
    for manager in ws_doc.get("documentManagers", []):
        if isinstance(manager, str) and manager == user_id:
            return "DocumentManager"
        if isinstance(manager, dict) and manager.get("userId") == user_id:
            return "DocumentManager"
    return "User"


def build_public_workspace_public_summary(ws_doc: dict) -> dict:
    """Return the non-sensitive workspace fields safe for any authenticated caller."""
    owner = ws_doc.get("owner", {}) or {}
    logo_metadata = get_workspace_logo_metadata(ws_doc)
    return {
        "id": ws_doc.get("id", ""),
        "name": ws_doc.get("name", ""),
        "description": ws_doc.get("description", ""),
        "owner": {
            "displayName": owner.get("displayName", ""),
            "email": owner.get("email", ""),
        },
        "status": ws_doc.get("status", "active"),
        "heroColor": normalize_workspace_hero_color(ws_doc.get("heroColor")),
        **logo_metadata,
        "userRole": None,
        "isMember": False,
    }


def build_public_workspace_member_payload(ws_doc: dict, user_id: str) -> dict:
    """Return the workspace fields required by member-facing workspace pages."""
    role = get_user_role_in_public_workspace(ws_doc, user_id)
    owner = ws_doc.get("owner", {}) or {}
    logo_metadata = get_workspace_logo_metadata(ws_doc)
    payload = {
        "id": ws_doc.get("id", ""),
        "name": ws_doc.get("name", ""),
        "description": ws_doc.get("description", ""),
        "owner": {
            "displayName": owner.get("displayName", ""),
            "email": owner.get("email", ""),
        },
        "status": ws_doc.get("status", "active"),
        "heroColor": normalize_workspace_hero_color(ws_doc.get("heroColor")),
        **logo_metadata,
        "userRole": role,
        "isMember": bool(role),
        "disable_file_downloads": bool(ws_doc.get("disable_file_downloads", False)),
    }

    if role in ("Owner", "Admin") and "retention_policy" in ws_doc:
        payload["retention_policy"] = ws_doc.get("retention_policy")

    return payload


def is_user_in_public_workspace(ws_doc: dict, user_id: str) -> bool:
    """
    Check if a user has any role in the workspace.
    """
    return get_user_role_in_public_workspace(ws_doc, user_id) is not None


def get_pending_document_manager_requests(ws_id: str) -> list:
    """
    Retrieve the list of pending document-manager requests.
    """
    ws = find_public_workspace_by_id(ws_id)
    if not ws:
        return []
    return ws.get("pendingDocumentManagers", [])


def count_public_workspace_documents(ws_id: str) -> int:
    """
    Return the number of documents in this public workspace.
    """
    query = "SELECT VALUE COUNT(1) FROM d WHERE d.public_workspace_id = @wsId"
    params = [{"name": "@wsId", "value": ws_id}]
    iter_ = cosmos_public_documents_container.query_items(
        query=query,
        parameters=params,
        enable_cross_partition_query=True
    )
    return next(iter_, 0)


def update_active_public_workspace_for_user(user_id: str, ws_id: str) -> None:
    """
    Persist the user's activePublicWorkspaceOid after validating the workspace.
    """
    normalized_workspace_id = str(ws_id or "").strip()
    if not normalized_workspace_id:
        functions_settings.update_user_settings(user_id, {"activePublicWorkspaceOid": ""})
        return

    workspace_doc = find_public_workspace_by_id(normalized_workspace_id)
    if not workspace_doc:
        raise LookupError("Workspace not found")

    functions_settings.update_user_settings(
        user_id,
        {"activePublicWorkspaceOid": normalized_workspace_id},
    )


def require_active_public_workspace(
    user_id: str,
    allowed_roles: Iterable[str] = ("Owner", "Admin", "DocumentManager"),
) -> tuple[str, dict, str]:
    """Return the active public workspace after validating it still exists and the user can access it."""
    settings = functions_settings.get_user_settings(user_id)
    active_workspace_id = str(settings.get("settings", {}).get("activePublicWorkspaceOid") or "").strip()
    if not active_workspace_id:
        raise ValueError("No active public workspace selected")

    workspace_doc = find_public_workspace_by_id(active_workspace_id)
    if not workspace_doc:
        raise LookupError("Active public workspace not found")

    role = get_user_role_in_public_workspace(workspace_doc, user_id)
    if not role:
        raise PermissionError("Access denied")

    allowed = {allowed_role.lower() for allowed_role in allowed_roles}
    if role.lower() not in allowed:
        raise PermissionError("Access denied")

    return active_workspace_id, workspace_doc, role


def get_user_visible_public_workspaces(user_id: str) -> list:
    """
    Get the list of public workspace IDs that the user has marked as visible.
    Returns all public workspaces if no visibility settings exist yet.
    """
    from functions_settings import get_user_settings
    
    user_settings = get_user_settings(user_id)
    visible_workspace_ids = user_settings.get("settings", {}).get("visiblePublicWorkspaceIds")
    
    # If no visibility settings exist yet, return all public workspaces (backward compatibility)
    if visible_workspace_ids is None:
        public_workspaces = get_all_public_workspaces()
        return [ws["id"] for ws in public_workspaces]
    
    return visible_workspace_ids

def get_user_visible_public_workspace_ids_from_settings(user_id: str) -> list:
    """
    Get the list of public workspace IDs that the user has marked as visible
    using the publicDirectorySettings in user settings.
    
    Returns a list of workspace IDs where the value is true in publicDirectorySettings.
    If publicDirectorySettings doesn't exist, falls back to the old method.
    """
    from functions_settings import get_user_settings
    
    user_settings = get_user_settings(user_id)
    public_directory_settings = user_settings.get("settings", {}).get("publicDirectorySettings", {})
    
    # If publicDirectorySettings exists, return IDs where value is True
    if public_directory_settings:
        return [ws_id for ws_id, is_visible in public_directory_settings.items() if is_visible]
    
    # Fall back to old method if publicDirectorySettings doesn't exist
    return get_user_visible_public_workspaces(user_id)


def set_user_visible_public_workspaces(user_id: str, workspace_ids: list) -> None:
    """
    Set the list of public workspace IDs that the user wants to be visible.
    """
    from functions_settings import update_user_settings
    
    update_user_settings(user_id, {"visiblePublicWorkspaceIds": workspace_ids})


def add_visible_public_workspace(user_id: str, ws_id: str) -> None:
    """
    Add a workspace to the user's visible list using publicDirectorySettings.
    """
    from functions_settings import get_user_settings, update_user_settings
    
    user_settings = get_user_settings(user_id)
    settings_dict = user_settings.get("settings", {})
    
    # Initialize publicDirectorySettings if it doesn't exist
    if "publicDirectorySettings" not in settings_dict:
        settings_dict["publicDirectorySettings"] = {}
    
    # Set the workspace as visible
    settings_dict["publicDirectorySettings"][ws_id] = True
    
    # Update user settings
    update_user_settings(user_id, {"publicDirectorySettings": settings_dict["publicDirectorySettings"]})


def remove_visible_public_workspace(user_id: str, ws_id: str) -> None:
    """
    Remove a workspace from the user's visible list using publicDirectorySettings.
    """
    from functions_settings import get_user_settings, update_user_settings
    
    user_settings = get_user_settings(user_id)
    settings_dict = user_settings.get("settings", {})
    
    # Initialize publicDirectorySettings if it doesn't exist
    if "publicDirectorySettings" not in settings_dict:
        settings_dict["publicDirectorySettings"] = {}
    
    # Set the workspace as hidden
    settings_dict["publicDirectorySettings"][ws_id] = False
    
    # Update user settings
    update_user_settings(user_id, {"publicDirectorySettings": settings_dict["publicDirectorySettings"]})


def get_user_visible_public_workspace_docs(user_id: str) -> list:
    """
    Get all public workspaces that the user has marked as visible.
    This replaces get_user_public_workspaces for visibility-filtered results.
    """
    public_workspaces = get_all_public_workspaces()
    
    # Get the user's visibility preferences
    visible_workspace_ids = get_user_visible_public_workspaces(user_id)
    
    # Filter to only include visible workspaces
    visible_workspaces = [
        ws for ws in public_workspaces
        if ws["id"] in visible_workspace_ids
    ]
    
    return visible_workspaces


def check_public_workspace_status_allows_operation(workspace_doc, operation_type):
    """
    Check if the public workspace's status allows the specified operation.
    
    Args:
        workspace_doc: The public workspace document from Cosmos DB
        operation_type: One of 'upload', 'delete', 'chat', 'view'
    
    Returns:
        tuple: (allowed: bool, reason: str)
    
    Status definitions:
        - active: All operations allowed
        - locked: Read-only mode (view and chat only, no modifications)
        - upload_disabled: No new uploads, but deletions and chat allowed
        - inactive: No operations allowed except admin viewing
    """
    if not workspace_doc:
        return False, "Public workspace not found"
    
    status = workspace_doc.get('status', 'active')  # Default to 'active' if not set
    
    # Define what each status allows
    status_permissions = {
        'active': {
            'upload': True,
            'delete': True,
            'chat': True,
            'view': True
        },
        'locked': {
            'upload': False,
            'delete': False,
            'chat': True,
            'view': True
        },
        'upload_disabled': {
            'upload': False,
            'delete': True,
            'chat': True,
            'view': True
        },
        'inactive': {
            'upload': False,
            'delete': False,
            'chat': False,
            'view': False
        }
    }
    
    # An unrecognized status is treated as inactive rather than active: a status the
    # code does not know must never be given active's full permissions. Its reason is
    # the public context's own words for an unknown status.
    known_status = status in status_permissions
    permissions = status_permissions.get(status, status_permissions['inactive'])
    
    # Check if operation is allowed
    allowed = permissions.get(operation_type, False)
    
    # Generate helpful reason message if not allowed
    if not allowed:
        if not known_status:
            return False, "This workspace's status is not recognized. Contact an administrator."
        reasons = {
            'locked': {
                'upload': 'This public workspace is locked (read-only mode). Document uploads are disabled.',
                'delete': 'This public workspace is locked (read-only mode). Document deletions are disabled.'
            },
            'upload_disabled': {
                'upload': 'Document uploads are disabled for this public workspace.'
            },
            'inactive': {
                'upload': 'This public workspace is inactive. All operations are disabled.',
                'delete': 'This public workspace is inactive. All operations are disabled.',
                'chat': 'This public workspace is inactive. All operations are disabled.',
                'view': 'This public workspace is inactive. Access is restricted to administrators.'
            }
        }
        
        reason = reasons.get(status, {}).get(operation_type, 
                                             f'This operation is not allowed when public workspace status is "{status}".')
        return False, reason
    
    return True, ""