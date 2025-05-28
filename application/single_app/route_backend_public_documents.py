# route_backend_public_documents.py

from config import *
from functions_documents import *
from functions_public_workspace import *
from functions_authentication import *

def register_route_backend_public_documents(app):
    @app.route('/api/public_workspaces/<workspace_id>/documents', methods=['POST'])
    @login_required
    def api_upload_public_document(workspace_id):
        try:
            # Check if the workspace exists and the user has permission
            workspace_doc = find_public_workspace_by_id(workspace_id)
            if not workspace_doc:
                return jsonify({"error": "Public workspace not found"}), 404
            
            # Only owners, admins, and document managers can upload documents
            user_id = get_current_user_id()
            role = get_user_role_in_public_workspace(workspace_doc, user_id)
            if not role or role not in ["Owner", "Admin", "DocumentManager"]:
                return jsonify({"error": "Insufficient permissions to upload documents to this workspace"}), 403

            # Check if file is included in the request
            if 'file' not in request.files:
                return jsonify({"error": "No file provided"}), 400
            
            file = request.files['file']
            
            if file.filename == '':
                return jsonify({"error": "No file selected"}), 400
                
            # Process the file upload
            document_id = process_document_upload(
                file=file,
                user_id=user_id,
                container_name=storage_account_public_documents_container_name,
                metadata_container=cosmos_public_documents_container,
                additional_metadata={
                    "public_workspace_id": workspace_id,
                    "type": "document_metadata"
                }
            )
            
            return jsonify({"message": "Document upload initiated", "document_id": document_id}), 202
            
        except Exception as e:
            print(f"Error uploading public document: {str(e)}")
            return jsonify({"error": f"Failed to upload document: {str(e)}"}), 500


    @app.route('/api/public_workspaces/<workspace_id>/documents', methods=['GET'])
    @login_required
    def api_get_public_documents(workspace_id):
        try:
            # Check if the workspace exists
            workspace_doc = find_public_workspace_by_id(workspace_id)
            if not workspace_doc:
                return jsonify({"error": "Public workspace not found"}), 404
            
            # Anyone can view public workspace documents, no permissions check needed
            
            query = "SELECT * FROM c WHERE c.public_workspace_id = @workspace_id AND c.type = 'document_metadata'"
            params = [{"name": "@workspace_id", "value": workspace_id}]
            
            documents = list(cosmos_public_documents_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            
            return jsonify({"documents": documents}), 200
            
        except Exception as e:
            print(f"Error retrieving public documents: {str(e)}")
            return jsonify({"error": f"Failed to retrieve documents: {str(e)}"}), 500


    @app.route('/api/public_workspaces/<workspace_id>/documents/<document_id>', methods=['DELETE'])
    @login_required
    def api_delete_public_document(workspace_id, document_id):
        try:
            # Check if the workspace exists
            workspace_doc = find_public_workspace_by_id(workspace_id)
            if not workspace_doc:
                return jsonify({"error": "Public workspace not found"}), 404
                
            # Only owners, admins, and document managers can delete documents
            user_id = get_current_user_id()
            role = get_user_role_in_public_workspace(workspace_doc, user_id)
            if not role or role not in ["Owner", "Admin", "DocumentManager"]:
                return jsonify({"error": "Insufficient permissions to delete documents from this workspace"}), 403
                
            # Try to retrieve the document
            try:
                document = cosmos_public_documents_container.read_item(
                    item=document_id,
                    partition_key=document_id
                )
            except exceptions.CosmosResourceNotFoundError:
                return jsonify({"error": "Document not found"}), 404
                
            # Verify the document belongs to the specified workspace
            if document.get("public_workspace_id") != workspace_id:
                return jsonify({"error": "Document does not belong to this workspace"}), 403
                
            # Delete the document from cosmos container
            cosmos_public_documents_container.delete_item(item=document_id, partition_key=document_id)
            
            # Delete the document from blob storage
            try:
                blob_client = blob_service_client.get_blob_client(
                    container=storage_account_public_documents_container_name, 
                    blob=document_id
                )
                blob_client.delete_blob()
            except Exception as e:
                print(f"Warning: Could not delete blob for document {document_id}: {str(e)}")
            
            # Delete document chunks from search index
            try:
                delete_document_chunks_from_search(document_id, client_key="search_client_public")
            except Exception as e:
                print(f"Warning: Could not delete document chunks from search for {document_id}: {str(e)}")
                
            return jsonify({"message": "Document deleted successfully"}), 200
            
        except Exception as e:
            print(f"Error deleting public document: {str(e)}")
            return jsonify({"error": f"Failed to delete document: {str(e)}"}), 500


    @app.route('/api/public_workspaces/<workspace_id>/documents/<document_id>', methods=['GET'])
    @login_required
    def api_get_public_document_details(workspace_id, document_id):
        try:
            # Check if the workspace exists
            workspace_doc = find_public_workspace_by_id(workspace_id)
            if not workspace_doc:
                return jsonify({"error": "Public workspace not found"}), 404
                
            # Anyone can view public workspace document details
            
            # Try to retrieve the document
            try:
                document = cosmos_public_documents_container.read_item(
                    item=document_id,
                    partition_key=document_id
                )
            except exceptions.CosmosResourceNotFoundError:
                return jsonify({"error": "Document not found"}), 404
                
            # Verify the document belongs to the specified workspace
            if document.get("public_workspace_id") != workspace_id:
                return jsonify({"error": "Document does not belong to this workspace"}), 403
                
            return jsonify({"document": document}), 200
            
        except Exception as e:
            print(f"Error retrieving public document details: {str(e)}")
            return jsonify({"error": f"Failed to retrieve document details: {str(e)}"}), 500


    @app.route('/api/public_documents', methods=['GET'])
    @login_required
    def api_get_all_public_documents():
        try:
            # Get page parameters with defaults for pagination
            page = request.args.get('page', 1, type=int)
            page_size = request.args.get('page_size', 10, type=int)
            
            # Calculate offset based on page and page_size
            offset = (page - 1) * page_size
            
            # Query to get all public documents across all workspaces
            query = "SELECT * FROM c WHERE c.type = 'document_metadata' OFFSET @offset LIMIT @limit"
            params = [{"name": "@offset", "value": offset}, {"name": "@limit", "value": page_size}]
            
            # Query to count total documents (for pagination metadata)
            count_query = "SELECT VALUE COUNT(1) FROM c WHERE c.type = 'document_metadata'"
            
            # Execute queries
            documents = list(cosmos_public_documents_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            
            total_count = list(cosmos_public_documents_container.query_items(
                query=count_query,
                enable_cross_partition_query=True
            ))[0]
            
            # Calculate total pages
            total_pages = (total_count + page_size - 1) // page_size
            
            return jsonify({
                "documents": documents,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_count": total_count,
                    "total_pages": total_pages
                }
            }), 200
            
        except Exception as e:
            print(f"Error retrieving all public documents: {str(e)}")
            return jsonify({"error": f"Failed to retrieve public documents: {str(e)}"}), 500