# functions_public_workspaces.py

from config import *
from functions_authentication import *
from functions_group import *

def create_public_workspace(name: str, description: str) -> dict:
    """
    Creates a new public workspace. The creator becomes the Owner by default.
    """
    user_info = get_current_user_info()
    if not user_info:
        raise Exception("No user in session")

    new_id = str(uuid.uuid4())
    now_iso = datetime.utcnow().isoformat()

    ws_doc = {
        "id": new_id,
        "name": name,
        "description": description,
        "owner": {
            "userId": user_info["userId"],
            "email": user_info["email"],
            "displayName": user_info["displayName"]
        },
        "admins": [],
        "documentManagers": [],
        "pendingDocumentManagers": [],
        "createdDate": now_iso,
        "modifiedDate": now_iso
    }
    cosmos_public_workspaces_container.create_item(ws_doc)
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


def delete_public_workspace(ws_id: str) -> None:
    """
    Deletes a public workspace from Cosmos DB. Typically only the owner may call this.
    """
    cosmos_public_workspaces_container.delete_item(
        item=ws_id,
        partition_key=ws_id
    )


def get_user_role_in_public_workspace(ws_doc: dict, user_id: str) -> str | None:
    """
    Determine the user's role in the given workspace doc.
    """
    if not ws_doc:
        return None
    if ws_doc.get("owner", {}).get("userId") == user_id:
        return "Owner"
    if user_id in ws_doc.get("admins", []):
        return "Admin"
    if any(dm["userId"] == user_id for dm in ws_doc.get("documentManagers", [])):
        return "DocumentManager"
    return None


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


def add_document_manager(ws_id: str, user_id: str, email: str, display_name: str) -> None:
    """
    Add a user as a document manager.
    """
    ws = find_public_workspace_by_id(ws_id)
    if not ws:
        raise Exception("Workspace not found")

    ws.setdefault("documentManagers", []).append({
        "userId": user_id,
        "email": email,
        "displayName": display_name
    })
    ws["modifiedDate"] = datetime.utcnow().isoformat()
    cosmos_public_workspaces_container.upsert_item(ws)


def remove_document_manager(ws_id: str, user_id: str) -> None:
    """
    Remove a user from document managers.
    """
    ws = find_public_workspace_by_id(ws_id)
    if not ws:
        raise Exception("Workspace not found")

    ws["documentManagers"] = [
        dm for dm in ws.get("documentManagers", [])
        if dm["userId"] != user_id
    ]
    ws["modifiedDate"] = datetime.utcnow().isoformat()
    cosmos_public_workspaces_container.upsert_item(ws)


def approve_document_manager_request(ws_id: str, request_user_id: str) -> None:
    """
    Approve a pending document-manager request and add the user.
    """
    ws = find_public_workspace_by_id(ws_id)
    if not ws:
        raise Exception("Workspace not found")

    pend = ws.get("pendingDocumentManagers", [])
    new_pend = []
    for p in pend:
        if p["userId"] == request_user_id:
            add_document_manager(ws_id, p["userId"], p["email"], p["displayName"])
        else:
            new_pend.append(p)

    ws["pendingDocumentManagers"] = new_pend
    ws["modifiedDate"] = datetime.utcnow().isoformat()
    cosmos_public_workspaces_container.upsert_item(ws)


def reject_document_manager_request(ws_id: str, request_user_id: str) -> None:
    """
    Reject (remove) a pending document-manager request.
    """
    ws = find_public_workspace_by_id(ws_id)
    if not ws:
        raise Exception("Workspace not found")

    ws["pendingDocumentManagers"] = [
        p for p in ws.get("pendingDocumentManagers", [])
        if p["userId"] != request_user_id
    ]
    ws["modifiedDate"] = datetime.utcnow().isoformat()
    cosmos_public_workspaces_container.upsert_item(ws)


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
    Persist the user's activePublicWorkspaceOid in their settings.
    """
    update_user_settings(user_id, {"activePublicWorkspaceOid": ws_id})


def get_user_visible_public_workspaces(user_id: str) -> list:
    """
    Get the list of public workspace IDs that the user has marked as visible.
    Returns all accessible workspaces if no visibility settings exist yet.
    """
    from functions_settings import get_user_settings
    
    user_settings = get_user_settings(user_id)
    visible_workspace_ids = user_settings.get("settings", {}).get("visiblePublicWorkspaceIds")
    
    # If no visibility settings exist yet, return all accessible workspaces (backward compatibility)
    if visible_workspace_ids is None:
        accessible_workspaces = get_user_public_workspaces(user_id)
        return [ws["id"] for ws in accessible_workspaces]
    
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
    Get all public workspaces that the user has access to AND has marked as visible.
    This replaces get_user_public_workspaces for visibility-filtered results.
    """
    # Get all workspaces the user has access to
    accessible_workspaces = get_user_public_workspaces(user_id)
    
    # Get the user's visibility preferences
    visible_workspace_ids = get_user_visible_public_workspaces(user_id)
    
    # Filter to only include visible workspaces
    visible_workspaces = [
        ws for ws in accessible_workspaces
        if ws["id"] in visible_workspace_ids
    ]
    
    return visible_workspaces