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

    # Debug logging to understand role detection issues
    owner_id = workspace_doc.get("owner", {}).get("id")
    admins = workspace_doc.get("admins", [])
    doc_managers = workspace_doc.get("documentManagers", [])
    
    print(f"DEBUG: Role check for user {user_id} (type: {type(user_id)})")
    print(f"DEBUG: Owner ID: {owner_id} (type: {type(owner_id)})")
    print(f"DEBUG: Admins: {admins}")
    print(f"DEBUG: Document Managers: {doc_managers}")
    print(f"DEBUG: Owner comparison: {user_id} == {owner_id} -> {user_id == owner_id}")
    print(f"DEBUG: Admin check: {user_id} in {admins} -> {user_id in admins}")
    print(f"DEBUG: DocManager check: {user_id} in {doc_managers} -> {user_id in doc_managers}")

    if owner_id == user_id:
        print(f"DEBUG: User {user_id} is Owner")
        return "Owner"
    elif user_id in admins:
        print(f"DEBUG: User {user_id} is Admin")
        return "Admin"
    elif user_id in doc_managers:
        print(f"DEBUG: User {user_id} is DocumentManager")
        return "DocumentManager"

    print(f"DEBUG: User {user_id} has no role (returning None)")
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


def create_public_document(file_name, user_id, document_id, num_file_chunks, status, public_workspace_id):
    """
    Create a document record in the public documents container.
    Similar to create_document but for public workspaces.
    """
    from datetime import datetime, timezone
    from functions_logging import add_file_task_to_file_processing_log
    
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # Check for existing documents with same name in this public workspace
    query = """
        SELECT * 
        FROM c
        WHERE c.file_name = @file_name 
            AND c.public_workspace_id = @public_workspace_id
    """
    parameters = [
        {"name": "@file_name", "value": file_name},
        {"name": "@public_workspace_id", "value": public_workspace_id}
    ]

    try:
        existing_document = list(
            cosmos_public_documents_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            )
        )
        version = existing_document[0]['version'] + 1 if existing_document else 1
        
        document_metadata = {
            "id": document_id,
            "file_name": file_name,
            "num_chunks": 0,
            "number_of_pages": 0,
            "current_file_chunk": 0,
            "num_file_chunks": num_file_chunks,
            "upload_date": current_time,
            "last_updated": current_time,
            "version": version,
            "status": status,
            "percentage_complete": 0,
            "document_classification": "Pending",
            "type": "document_metadata",
            "public_workspace_id": public_workspace_id
        }

        cosmos_public_documents_container.upsert_item(document_metadata)

        add_file_task_to_file_processing_log(
            document_id,
            user_id,
            f"Public document {file_name} created in workspace {public_workspace_id}."
        )

    except Exception as e:
        print(f"Error creating public document: {e}")
        raise


def update_public_document(**kwargs):
    """
    Update a document record in the public documents container.
    Similar to update_document but for public workspaces.
    """
    from datetime import datetime, timezone
    from functions_logging import add_file_task_to_file_processing_log
    from azure.cosmos.exceptions import CosmosResourceNotFoundError
    import json
    
    document_id = kwargs.get('document_id')
    user_id = kwargs.get('user_id')
    public_workspace_id = kwargs.get('public_workspace_id')
    num_chunks_increment = kwargs.pop('num_chunks_increment', 0)

    if not document_id or not user_id or not public_workspace_id:
        print("Error: document_id, user_id and public_workspace_id are required for update_public_document")
        raise ValueError("document_id, user_id and public_workspace_id are required")

    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    query = """
        SELECT * 
        FROM c
        WHERE c.id = @document_id 
            AND c.public_workspace_id = @public_workspace_id
    """
    parameters = [
        {"name": "@document_id", "value": document_id},
        {"name": "@public_workspace_id", "value": public_workspace_id}
    ]
    
    add_file_task_to_file_processing_log(
        document_id=document_id, 
        user_id=user_id, 
        content=f"Query is {query}, parameters are {parameters}."
    )

    try:
        existing_documents = list(
            cosmos_public_documents_container.query_items(
                query=query, 
                parameters=parameters, 
                enable_cross_partition_query=True
            )
        )

        status = kwargs.get('status', '')

        if status:
            add_file_task_to_file_processing_log(
                document_id=document_id,
                user_id=user_id,
                content=f"Status: {status}"
            )

        if not existing_documents:
            log_msg = f"Public document {document_id} not found for workspace {public_workspace_id} during update."
            print(log_msg)
            add_file_task_to_file_processing_log(
                document_id=document_id, 
                user_id=user_id, 
                content=log_msg
            )
            raise CosmosResourceNotFoundError(
                message=f"Public document {document_id} not found",
                status=404
            )

        existing_document = existing_documents[0]
        original_percentage = existing_document.get('percentage_complete', 0)

        # Apply updates from kwargs
        update_occurred = False

        if num_chunks_increment > 0:
            current_num_chunks = existing_document.get('num_chunks', 0)
            existing_document['num_chunks'] = current_num_chunks + num_chunks_increment
            update_occurred = True
            add_file_task_to_file_processing_log(
                document_id=document_id, 
                user_id=user_id,  
                content=f"Incrementing num_chunks by {num_chunks_increment} to {existing_document['num_chunks']}"
            )

        for key, value in kwargs.items():
            if value is not None and existing_document.get(key) != value:
                if key == 'num_chunks' and num_chunks_increment > 0:
                    continue
                existing_document[key] = value
                update_occurred = True

        # Handle timestamps and percentage if update occurred
        if update_occurred:
            existing_document['last_updated'] = current_time

            # Handle percentage completion based on status
            status_lower = existing_document.get('status', '')
            if isinstance(status_lower, str):
                status_lower = status_lower.lower()
            elif isinstance(status_lower, bytes):
                status_lower = status_lower.decode('utf-8').lower()
            elif isinstance(status_lower, dict):
                status_lower = json.dumps(status_lower).lower()

            if "processing complete" in status_lower:
                existing_document['percentage_complete'] = 100
            elif "error" in status_lower or "failed" in status_lower:
                existing_document['percentage_complete'] = 0

            # Update the document in Cosmos
            cosmos_public_documents_container.upsert_item(existing_document)

            add_file_task_to_file_processing_log(
                document_id=document_id, 
                user_id=user_id,
                content=f"Public document updated successfully."
            )

    except Exception as e:
        print(f"Error updating public document: {e}")
        raise