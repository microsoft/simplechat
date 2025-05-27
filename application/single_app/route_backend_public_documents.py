# route_backend_public_documents.py

from config import *
from functions_authentication import *
from functions_settings import *

def register_route_backend_public_documents(app):
    @app.route('/api/public_documents', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def get_public_documents():
        """Get a list of available public documents."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        # Get query parameters for pagination
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 10, type=int)
        search_term = request.args.get('search_term', '', type=str)

        # Limit page size to prevent large queries
        if page_size > 50:
            page_size = 50

        # Calculate offsets
        skip = (page - 1) * page_size
        
        # Build the query
        if search_term:
            query = """
                SELECT * FROM c 
                WHERE NOT IS_DEFINED(c.percentage_complete)
                AND (
                    CONTAINS(LOWER(c.filename), LOWER(@search_term))
                    OR CONTAINS(LOWER(c.description), LOWER(@search_term))
                )
                ORDER BY c._ts DESC
                OFFSET @skip LIMIT @page_size
            """
            count_query = """
                SELECT VALUE COUNT(1) FROM c 
                WHERE NOT IS_DEFINED(c.percentage_complete)
                AND (
                    CONTAINS(LOWER(c.filename), LOWER(@search_term))
                    OR CONTAINS(LOWER(c.description), LOWER(@search_term))
                )
            """
            parameters = [
                {"name": "@search_term", "value": search_term},
                {"name": "@skip", "value": skip},
                {"name": "@page_size", "value": page_size}
            ]
        else:
            query = """
                SELECT * FROM c 
                WHERE NOT IS_DEFINED(c.percentage_complete)
                ORDER BY c._ts DESC
                OFFSET @skip LIMIT @page_size
            """
            count_query = """
                SELECT VALUE COUNT(1) FROM c 
                WHERE NOT IS_DEFINED(c.percentage_complete)
            """
            parameters = [
                {"name": "@skip", "value": skip},
                {"name": "@page_size", "value": page_size}
            ]
        
        # Get documents
        try:
            documents = list(cosmos_public_documents_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            total_count = list(cosmos_public_documents_container.query_items(
                query=count_query,
                parameters=parameters[:-2] if search_term else [],
                enable_cross_partition_query=True
            ))
            
            # Get user-specific visibility settings
            user_settings_id = f"public_workspaces_{user_id}"
            user_visibility_settings = {}
            
            try:
                user_settings = cosmos_user_settings_container.read_item(
                    item=user_visibility_settings_id,
                    partition_key=user_visibility_settings_id
                )
                user_visibility_settings = user_settings.get("visible_workspaces", {})
            except CosmosResourceNotFoundError:
                # No settings found, create default with all visible
                workspace_ids = [doc['id'] for doc in documents]
                user_visibility_settings = {workspace_id: True for workspace_id in workspace_ids}
                cosmos_user_settings_container.upsert_item({
                    "id": user_visibility_settings_id,
                    "user_id": user_id,
                    "visible_workspaces": user_visibility_settings
                })
            
            # Add visibility information to each document
            for doc in documents:
                doc["is_visible_to_user"] = user_visibility_settings.get(doc["id"], True)
            
            return jsonify({
                "documents": documents,
                "total_count": total_count[0] if total_count else 0,
                "page": page,
                "page_size": page_size
            })
        
        except Exception as e:
            print(f"Error retrieving public documents: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/public_documents/toggle_visibility', methods=['POST'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def toggle_public_document_visibility():
        """Toggle visibility of a public document for the current user."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401
        
        data = request.get_json()
        document_id = data.get("document_id")
        visibility = data.get("visibility", True)
        
        if not document_id:
            return jsonify({"error": "Document ID is required"}), 400
        
        user_settings_id = f"public_workspaces_{user_id}"
        
        try:
            # Check if document exists
            try:
                document = cosmos_public_documents_container.read_item(
                    item=document_id,
                    partition_key=document_id
                )
            except CosmosResourceNotFoundError:
                return jsonify({"error": "Public document not found"}), 404
            
            # Get or create user visibility settings
            try:
                user_settings = cosmos_user_settings_container.read_item(
                    item=user_settings_id,
                    partition_key=user_settings_id
                )
            except CosmosResourceNotFoundError:
                user_settings = {
                    "id": user_settings_id,
                    "user_id": user_id,
                    "visible_workspaces": {}
                }
            
            # Update visibility
            visible_workspaces = user_settings.get("visible_workspaces", {})
            visible_workspaces[document_id] = visibility
            user_settings["visible_workspaces"] = visible_workspaces
            
            # Save settings
            cosmos_user_settings_container.upsert_item(user_settings)
            
            return jsonify({
                "success": True,
                "document_id": document_id,
                "visibility": visibility
            })
        
        except Exception as e:
            print(f"Error toggling document visibility: {str(e)}")
            return jsonify({"error": str(e)}), 500