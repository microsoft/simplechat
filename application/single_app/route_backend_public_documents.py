# route_backend_public_documents.py

import uuid
import tempfile
import os
import math
from config import *
from functions_authentication import *
from functions_settings import *
from functions_public_workspace import *
from functions_documents import *
from werkzeug.utils import secure_filename

def register_route_backend_public_documents(app):
    @app.route('/api/public_documents', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_list_public_documents():
        """
        Return a list of documents for the active public workspace.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        # Get query parameters for pagination and search
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 10))
        search_term = request.args.get('q', '').strip()

        # Build query for public documents
        query = "SELECT * FROM c WHERE c.public_workspace_id = @workspace_id"
        parameters = [{"name": "@workspace_id", "value": active_public_workspace_id}]

        if search_term:
            query += " AND CONTAINS(c.file_name, @search)"
            parameters.append({"name": "@search", "value": search_term})

        query += " ORDER BY c._ts DESC"

        # Execute query
        try:
            all_documents = list(cosmos_public_documents_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))

            # Apply pagination
            total_count = len(all_documents)
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            paginated_documents = all_documents[start_index:end_index]

            return jsonify({
                'documents': paginated_documents,
                'page': page,
                'page_size': page_size,
                'total_count': total_count,
                'total_pages': math.ceil(total_count / page_size) if page_size > 0 else 0
            })

        except Exception as e:
            return jsonify({'error': f'Failed to fetch documents: {str(e)}'}), 500


    @app.route('/api/public_documents/<document_id>', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_get_public_document(document_id):
        """
        Return metadata for a specific public document.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        # Query the public documents container directly
        query = """
            SELECT TOP 1 * 
            FROM c
            WHERE c.id = @document_id 
                AND c.public_workspace_id = @public_workspace_id
            ORDER BY c.version DESC
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@public_workspace_id", "value": active_public_workspace_id}
        ]
        
        try:
            documents = list(cosmos_public_documents_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ))
            
            if not documents:
                return jsonify({'error': 'Document not found'}), 404
                
            return jsonify(documents[0]), 200
            
        except Exception as e:
            return jsonify({'error': f'Failed to fetch document: {str(e)}'}), 500


    @app.route('/api/public_documents/<document_id>/chunks', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_get_public_document_chunks(document_id):
        """
        Return chunks for a specific public document.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        return get_all_chunks(document_id, user_id, active_public_workspace_id)


    @app.route('/api/public_documents/<document_id>', methods=['PATCH'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_patch_public_document(document_id):
        """
        Update metadata fields for a public document.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        workspace_doc = find_public_workspace_by_id(active_public_workspace_id)
        if not workspace_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404

        role = get_user_role_in_public_workspace(workspace_doc, user_id)
        if role not in ['Owner', 'Admin', 'DocumentManager']:
            return jsonify({'error': 'You do not have permission to update documents in this public workspace'}), 403

        data = request.get_json()

        try:
            if 'title' in data:
                update_document(
                    document_id=document_id,
                    group_id=active_public_workspace_id,
                    user_id=user_id,
                    title=data['title']
                )
            if 'abstract' in data:
                update_document(
                    document_id=document_id,
                    group_id=active_public_workspace_id,
                    user_id=user_id,
                    abstract=data['abstract']
                )
            if 'keywords' in data:
                if isinstance(data['keywords'], list):
                    update_document(
                        document_id=document_id,
                        group_id=active_public_workspace_id,
                        user_id=user_id,
                        keywords=data['keywords']
                    )
            if 'authors' in data:
                if isinstance(data['authors'], list):
                    update_document(
                        document_id=document_id,
                        group_id=active_public_workspace_id,
                        user_id=user_id,
                        authors=data['authors']
                    )
            if 'document_classification' in data:
                update_document(
                    document_id=document_id,
                    group_id=active_public_workspace_id,
                    user_id=user_id,
                    document_classification=data['document_classification']
                )
            return jsonify({"updated": True}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500


    @app.route('/api/public_documents/<document_id>', methods=['DELETE'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_delete_public_document(document_id):
        """
        Delete a document from a public workspace.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        workspace_doc = find_public_workspace_by_id(active_public_workspace_id)
        if not workspace_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404

        role = get_user_role_in_public_workspace(workspace_doc, user_id)
        if role not in ['Owner', 'Admin', 'DocumentManager']:
            return jsonify({'error': 'You do not have permission to delete documents in this public workspace'}), 403

        try:
            delete_document(user_id, document_id, active_public_workspace_id)
            return jsonify({"deleted": True}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500


    @app.route('/api/public_documents/<document_id>/extract_metadata', methods=['POST'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_extract_public_metadata(document_id):
        """
        Extract metadata for a document in a public workspace.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        workspace_doc = find_public_workspace_by_id(active_public_workspace_id)
        if not workspace_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404

        role = get_user_role_in_public_workspace(workspace_doc, user_id)
        if role not in ['Owner', 'Admin', 'DocumentManager']:
            return jsonify({'error': 'You do not have permission to extract metadata in this public workspace'}), 403

        try:
            meta_data = extract_document_metadata(document_id, user_id, active_public_workspace_id)
            return jsonify(meta_data), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500


    @app.route('/api/public_documents/upload', methods=['POST'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_upload_public_document():
        """
        Upload one or more documents to the currently active public workspace.
        Mirrors logic from api_upload_group_document but scoped to public workspace context.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")
        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        workspace_doc = find_public_workspace_by_id(active_public_workspace_id)
        if not workspace_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404

        role = get_user_role_in_public_workspace(workspace_doc, user_id)
        if role not in ["Owner", "Admin", "DocumentManager"]:
            return jsonify({'error': 'You do not have permission to upload documents'}), 403

        if 'file' not in request.files:
            return jsonify({'error': 'No file part in the request'}), 400

        files = request.files.getlist('file')
        if not files or all(not f.filename for f in files):
            return jsonify({'error': 'No file selected or files have no name'}), 400

        processed_docs = []
        upload_errors = []

        for file in files:
            if not file.filename:
                upload_errors.append(f"Skipped a file with no name.")
                continue

            original_filename = file.filename
            safe_suffix_filename = secure_filename(original_filename)
            file_ext = os.path.splitext(safe_suffix_filename)[1].lower()

            if not allowed_file(original_filename):
                upload_errors.append(f"File type not allowed for: {original_filename}")
                continue

            if not os.path.splitext(original_filename)[1]:
                upload_errors.append(f"Could not determine file extension for: {original_filename}")
                continue

            parent_document_id = str(uuid.uuid4())
            temp_file_path = None

            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
                    file.save(tmp_file.name)
                    temp_file_path = tmp_file.name
            except Exception as e:
                upload_errors.append(f"Failed to save temporary file for {original_filename}: {e}")
                if temp_file_path and os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
                continue

            try:
                create_public_document(
                    file_name=original_filename,
                    public_workspace_id=active_public_workspace_id,
                    user_id=user_id,
                    document_id=parent_document_id,
                    num_file_chunks=0,
                    status="Queued for processing"
                )

                update_public_document(
                    document_id=parent_document_id,
                    user_id=user_id,
                    public_workspace_id=active_public_workspace_id,
                    percentage_complete=0
                )

                future = executor.submit(
                    process_document_upload_background,
                    document_id=parent_document_id,
                    user_id=user_id,
                    temp_file_path=temp_file_path,
                    original_filename=original_filename,
                    group_id=None,
                    public_workspace_id=active_public_workspace_id
                )
                executor.submit_stored(
                    parent_document_id, 
                    process_document_upload_background, 
                    document_id=parent_document_id, 
                    user_id=user_id, 
                    temp_file_path=temp_file_path, 
                    original_filename=original_filename,
                    group_id=None,
                    public_workspace_id=active_public_workspace_id
                )

                processed_docs.append({'document_id': parent_document_id, 'filename': original_filename})

            except Exception as e:
                upload_errors.append(f"Failed to queue processing for {original_filename}: {str(e)}")
                if temp_file_path and os.path.exists(temp_file_path):
                    os.remove(temp_file_path)

        response_status = 200 if processed_docs and not upload_errors else 207
        if not processed_docs and upload_errors:
            response_status = 400
        
        return jsonify({
            'message': f'Processed {len(processed_docs)} file(s). Check status periodically.',
            'document_ids': [doc['document_id'] for doc in processed_docs],
            'processed_filenames': [doc['filename'] for doc in processed_docs],
            'errors': upload_errors
        }), response_status