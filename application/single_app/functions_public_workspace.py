# functions_public_workspace.py

from config import *
from functions_authentication import *
from functions_settings import *
from functools import wraps


def create_public_workspace_role_required(f):
    """Decorator that checks if user has 'CreatePublicWorkspaces' app role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get('user')
        if not user:
            return redirect(url_for('login'))
            
        # Check if user has the required role
        roles = user.get('roles', [])
        if 'CreatePublicWorkspaces' not in roles:
            flash('You do not have permission to create or manage public workspaces.', 'danger')
            return redirect(url_for('index'))
            
        return f(*args, **kwargs)
    return decorated_function


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


def get_all_public_workspaces():
    """Fetch all public workspaces."""
    query = "SELECT * FROM c"
    results = list(cosmos_public_workspaces_container.query_items(
        query=query,
        enable_cross_partition_query=True
    ))
    return results


def get_user_public_workspaces(user_id):
    """
    Fetch all public workspaces where this user has a role (owner, admin, or document manager).
    """
    query = """
        SELECT *
        FROM c
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
    active_workspace_id = session.get("active_public_workspace")
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
    Also deletes all associated documents, blobs, and search index entries.
    """
    try:
        # First delete all documents associated with the workspace
        query = "SELECT * FROM c WHERE c.public_workspace_id = @workspace_id"
        parameters = [{"name": "@workspace_id", "value": workspace_id}]
        
        # Delete documents
        documents = list(cosmos_public_documents_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        for doc in documents:
            try:
                # Delete document metadata from Cosmos
                cosmos_public_documents_container.delete_item(item=doc["id"], partition_key=doc["id"])
                
                # Delete document from blob storage
                try:
                    blob_client = blob_service_client.get_blob_client(
                        container=storage_account_public_documents_container_name, 
                        blob=doc["id"]
                    )
                    blob_client.delete_blob()
                except Exception as e:
                    print(f"Warning: Could not delete blob for document {doc['id']}: {str(e)}")
                
                # Delete document chunks from search index
                try:
                    delete_document_chunks_from_search(doc["id"], client_key="search_client_public")
                except Exception as e:
                    print(f"Warning: Could not delete search chunks for document {doc['id']}: {str(e)}")
                    
            except Exception as e:
                print(f"Error deleting document {doc['id']}: {str(e)}")
        
        # Delete prompts
        prompts = list(cosmos_public_prompts_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        for prompt in prompts:
            try:
                cosmos_public_prompts_container.delete_item(item=prompt["id"], partition_key=prompt["id"])
            except Exception as e:
                print(f"Error deleting prompt {prompt['id']}: {str(e)}")
        
        # Finally delete the workspace itself
        cosmos_public_workspaces_container.delete_item(item=workspace_id, partition_key=workspace_id)
        
        return True
    except Exception as e:
        print(f"Error deleting public workspace: {str(e)}")
        raise


def delete_document_chunks_from_search(document_id, client_key="search_client_user"):
    """Delete all search chunks for a document."""
    try:
        search_client = CLIENTS[client_key]
        filter_expr = f"document_id eq '{document_id}'"
        
        # Get all chunks for this document
        results = search_client.search(
            search_text="*",
            filter=filter_expr,
            select="id"
        )
        
        chunk_ids = [result["id"] for result in results]
        if not chunk_ids:
            print(f"No chunks found for document {document_id}")
            return 0
            
        # Delete chunks in batches of 100
        batch_size = 100
        for i in range(0, len(chunk_ids), batch_size):
            batch = chunk_ids[i:i + batch_size]
            actions = [{"@search.action": "delete", "id": chunk_id} for chunk_id in batch]
            search_client.upload_documents(documents=actions)
            
        return len(chunk_ids)
        
    except Exception as e:
        print(f"Error deleting document chunks from search: {str(e)}")
        raise


def is_user_manager_in_public_workspace(workspace_doc, user_id):
    """
    Helper to check if a user has a management role in the public workspace (owner, admin, or document manager).
    """
    if workspace_doc.get("owner", {}).get("id") == user_id:
        return True
    
    if user_id in workspace_doc.get("admins", []):
        return True
        
    if user_id in workspace_doc.get("documentManagers", []):
        return True
        
    return False