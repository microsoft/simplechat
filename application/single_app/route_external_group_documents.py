# route_external_group_documents.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_group import *
from functions_documents import *
from flask import current_app

def register_route_external_group_documents(app):
    """
    Provides backend routes for group-level document management:
    - POST /external/group_documents/upload
    - GET /external/group_documents      (list)
    - DELETE /external/group_documents/<doc_id>
    """
    @app.route('/external/group_documents/upload', methods=['POST'])
    @accesstoken_required
    @enabled_required("enable_group_workspaces")
    def external_upload_group_document():
        """
        Upload one or more documents to the currently active group workspace.
        Mirrors logic from api_user_upload_document but scoped to group context.
        """

        print("Entered external_upload_group_document")

        user_id = request.form.get('user_id')
        active_workspace_id = request.form.get('active_workspace_id')  # This is group_id
        classification = request.form.get('classification')

        if not user_id:
            return jsonify({'error': 'user_id is required'}), 400
        
        if not active_workspace_id:
            return jsonify({'error': 'active_workspace_id (group_id) is required'}), 400

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
                # Check if sc-temp-files directory exists, otherwise use system temp
                sc_temp_files_dir = "/sc-temp-files" if os.path.exists("/sc-temp-files") else ""
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext, dir=sc_temp_files_dir) as tmp_file:
                    file.save(tmp_file.name)
                    temp_file_path = tmp_file.name
            except Exception as e:
                upload_errors.append(f"Failed to save temporary file for {original_filename}: {e}")
                if temp_file_path and os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
                continue

            try:
                # Create document metadata in Cosmos DB
                create_document(
                    file_name=original_filename,
                    group_id=active_workspace_id,
                    user_id=user_id,
                    document_id=parent_document_id,
                    num_file_chunks=0,
                    status="Queued for processing",
                    document_classification=classification if classification else None
                )

                update_document(
                    document_id=parent_document_id,
                    user_id=user_id,
                    group_id=active_workspace_id,
                    percentage_complete=0
                )

                # Submit background processing task
                future = current_app.extensions['executor'].submit_stored(
                    parent_document_id, 
                    process_document_upload_background, 
                    document_id=parent_document_id, 
                    group_id=active_workspace_id, 
                    user_id=user_id, 
                    temp_file_path=temp_file_path, 
                    original_filename=original_filename
                )

                processed_docs.append({'document_id': parent_document_id, 'filename': original_filename})

            except Exception as e:
                upload_errors.append(f"Failed to queue processing for {original_filename}: {e}")
                print(f"Error processing {original_filename}: {e}")
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

        
    @app.route('/external/group_documents', methods=['GET'])
    @accesstoken_required
    @enabled_required("enable_group_workspaces")
    def external_get_group_documents():
        """
        Return a paginated, filtered list of documents for the user's *active* group.
        Mirrors logic of api_get_user_documents.
        """
        user_id = request.args.get('user_id')
        active_workspace_id = request.args.get('active_workspace_id')  # This is group_id

        # --- 1) Read pagination and filter parameters ---
        page = request.args.get('page', default=1, type=int)
        page_size = request.args.get('page_size', default=10, type=int)
        search_term = request.args.get('search', default=None, type=str)
        classification_filter = request.args.get('classification', default=None, type=str)
        author_filter = request.args.get('author', default=None, type=str)
        keywords_filter = request.args.get('keywords', default=None, type=str)
        abstract_filter = request.args.get('abstract', default=None, type=str)

        if page < 1: page = 1
        if page_size < 1: page_size = 10

        # --- 2) Build dynamic WHERE clause and parameters ---
        query_conditions = ["c.group_id = @group_id"]
        query_params = [{"name": "@group_id", "value": active_workspace_id}]
        param_count = 0

        if search_term:
            param_name = f"@search_term_{param_count}"
            query_conditions.append(f"(CONTAINS(LOWER(c.file_name ?? ''), LOWER({param_name})) OR CONTAINS(LOWER(c.title ?? ''), LOWER({param_name})))")
            query_params.append({"name": param_name, "value": search_term})
            param_count += 1

        if classification_filter:
            param_name = f"@classification_{param_count}"
            if classification_filter.lower() == 'none':
                query_conditions.append(f"(NOT IS_DEFINED(c.document_classification) OR c.document_classification = null OR c.document_classification = '')")
            else:
                query_conditions.append(f"c.document_classification = {param_name}")
                query_params.append({"name": param_name, "value": classification_filter})
                param_count += 1

        if author_filter:
            param_name = f"@author_{param_count}"
            query_conditions.append(f"ARRAY_CONTAINS(c.authors, {param_name}, true)")
            query_params.append({"name": param_name, "value": author_filter})
            param_count += 1

        if keywords_filter:
            param_name = f"@keywords_{param_count}"
            query_conditions.append(f"ARRAY_CONTAINS(c.keywords, {param_name}, true)")
            query_params.append({"name": param_name, "value": keywords_filter})
            param_count += 1

        if abstract_filter:
            param_name = f"@abstract_{param_count}"
            query_conditions.append(f"CONTAINS(LOWER(c.abstract ?? ''), LOWER({param_name}))")
            query_params.append({"name": param_name, "value": abstract_filter})
            param_count += 1

        where_clause = " AND ".join(query_conditions)

        # --- 3) Get total count ---
        try:
            count_query_str = f"SELECT VALUE COUNT(1) FROM c WHERE {where_clause}"
            count_items = list(cosmos_group_documents_container.query_items(
                query=count_query_str,
                parameters=query_params,
                enable_cross_partition_query=True
            ))
            total_count = count_items[0] if count_items else 0
        except Exception as e:
            print(f"Error executing count query for group: {e}")
            return jsonify({"error": f"Error counting documents: {str(e)}"}), 500

        # --- 4) Get paginated data ---
        try:
            offset = (page - 1) * page_size
            data_query_str = f"""
                SELECT *
                FROM c
                WHERE {where_clause}
                ORDER BY c._ts DESC
                OFFSET {offset} LIMIT {page_size}
            """
            documents = list(cosmos_group_documents_container.query_items(
                query=data_query_str,
                parameters=query_params,
                enable_cross_partition_query=True
            ))
        except Exception as e:
            print(f"Error executing data query for group: {e}")
            return jsonify({"error": f"Error fetching documents: {str(e)}"}), 500

        # --- 5) Return the response ---
        return jsonify({
            "documents": documents,
            "pagination": {
                "total_count": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": (total_count + page_size - 1) // page_size
            }
        }), 200


    @app.route('/external/group_documents/<document_id>', methods=['DELETE'])
    @accesstoken_required
    @enabled_required("enable_group_workspaces")
    def external_delete_group_document(document_id):
        """
        Delete a document from the group workspace.
        """
        user_id = request.args.get('user_id')
        active_workspace_id = request.args.get('active_workspace_id')  # group_id

        if not user_id or not active_workspace_id:
            return jsonify({'error': 'user_id and active_workspace_id required'}), 400

        try:
            # Retrieve document metadata
            doc = cosmos_group_documents_container.read_item(
                item=document_id,
                partition_key=active_workspace_id
            )

            # Delete from Cosmos DB
            cosmos_group_documents_container.delete_item(
                item=document_id,
                partition_key=active_workspace_id
            )

            # TODO: Delete from AI Search index if needed
            # delete_from_search_index(document_id, active_workspace_id)

            return jsonify({'message': f'Document {document_id} deleted successfully'}), 200

        except exceptions.CosmosResourceNotFoundError:
            return jsonify({'error': 'Document not found'}), 404
        except Exception as e:
            print(f"Error deleting group document {document_id}: {e}")
            return jsonify({'error': f'Failed to delete document: {str(e)}'}), 500
