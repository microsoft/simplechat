# functions_public_workspace.py

from config import *
from functions_authentication import *
from functions_settings import *


def create_public_workspace(name, description):
    """Creates a new public workspace. The creator is the Owner by default."""
    user_info = get_current_user_info()
    if not user_info:
        raise Exception("No user in session")

    new_workspace_id = str(uuid.uuid4())
    now_str = datetime.utcnow().isoformat()

    workspace_doc = {
        "id": new_workspace_id,
        "name": name,
        "description": description,
        "owner":
            {
                "id": user_info["userId"],
                "email": user_info["email"],
                "displayName": user_info["displayName"]
            },
        "admins": [],
        "documentManagers": [],
        "createdDate": now_str,
        "modifiedDate": now_str
    }
    cosmos_public_workspaces_container.create_item(workspace_doc)
    return workspace_doc


def search_public_workspaces(search_query=None):
    """
    Return a list of all public workspaces, optionally filtered by search query.
    """
    query = "SELECT * FROM c"
    params = []
    
    if search_query:
        query += " WHERE CONTAINS(c.name, @search) "
        params.append({"name": "@search", "value": search_query})

    results = list(cosmos_public_workspaces_container.query_items(
        query=query,
        parameters=params,
        enable_cross_partition_query=True
    ))
    return results


def get_user_public_workspaces(user_id):
    """
    Fetch all public workspaces where this user has a role (owner, admin, document manager).
    """
    query = """
        SELECT * FROM c
        WHERE c.owner.id = @user_id
        OR ARRAY_CONTAINS(c.admins, @user_id)
        OR ARRAY_CONTAINS(c.documentManagers, @user_id)
    """

    params = [{ "name": "@user_id", "value": user_id }]
    results = list(cosmos_public_workspaces_container.query_items(
        query=query,
        parameters=params,
        enable_cross_partition_query=True
    ))
    return results


def find_public_workspace_by_id(workspace_id):
    """Retrieve a single public workspace doc by its ID."""
    try:
        workspace_doc = cosmos_public_workspaces_container.read_item(
            item=workspace_id,
            partition_key=workspace_id
        )
        return workspace_doc
    except exceptions.CosmosResourceNotFoundError:
        return None


def update_active_public_workspace_for_user(workspace_id):
    user_id = get_current_user_id()
    new_settings = {
        "activePublicWorkspaceOid": workspace_id
    }
    update_user_settings(user_id, new_settings)


def get_user_role_in_public_workspace(workspace_doc, user_id):
    """Determine the user's role in the given public workspace doc."""
    if not workspace_doc:
        return None

    if workspace_doc.get("owner", {}).get("id") == user_id:
        return "Owner"
    elif user_id in workspace_doc.get("admins", []):
        return "Admin"
    elif user_id in workspace_doc.get("documentManagers", []):
        return "DocumentManager"

    return None


def map_public_workspace_list_for_frontend(workspaces, current_user_id):
    """
    Utility to produce a simplified list of public workspace data
    for the front-end, including userRole and isActive.
    """
    user_settings = get_user_settings(current_user_id)
    active_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")
    response = []
    for w in workspaces:
        role = get_user_role_in_public_workspace(w, current_user_id)
        response.append({
            "id": w["id"],
            "name": w["name"],
            "description": w.get("description", ""),
            "userRole": role,
            "isActive": (w["id"] == active_workspace_id)
        })
    return response


def delete_public_workspace(workspace_id):
    """
    Deletes a public workspace from Cosmos DB. Typically only owner can do this.
    """
    cosmos_public_workspaces_container.delete_item(item=workspace_id, partition_key=workspace_id)


def is_user_manager_in_public_workspace(workspace_doc, user_id):
    """
    Helper to check if a user is an owner, admin or document manager in the workspace.
    """
    if workspace_doc.get("owner", {}).get("id") == user_id:
        return True
    elif user_id in workspace_doc.get("admins", []):
        return True
    elif user_id in workspace_doc.get("documentManagers", []):
        return True
        
    return False