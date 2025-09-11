# route_external_public_documents.py:

from config import *
from functions_authentication import *
from functions_settings import *
from functions_public_workspaces import *
from functions_documents import *
from flask import current_app

def register_route_external_public_documents(app):
    """
    Provides backend routes for public-level document management:
    - GET /external/public_documents      (list)
    - POST /external/public_documents/upload
    - DELETE /external/public_documents/<doc_id>
    """
    @app.route('/external/public_documents/upload', methods=['POST'])
    @accesstoken_required
    @enabled_required("enable_public_workspaces")
    def external_upload_public_document():
        """
        Upload one or more documents to the currently active public workspace.
        Mirrors logic from api_user_upload_document but scoped to public context.
        """

        print("Entered external_upload_public_document")

        user_id = request.form.get('user_id')
        active_workspace_id = request.form.get('active_workspace_id')
        classification = request.form.get('classification')

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
                create_document(
                    file_name=original_filename,
                    public_workspace_id=active_workspace_id,
                    user_id=user_id,
                    document_id=parent_document_id,
                    num_file_chunks=0,
                    status="Queued for processing"
                )

                update_document(
                    document_id=parent_document_id,
                    user_id=user_id,
                    public_workspace_id=active_workspace_id,
                    percentage_complete=0
                )

                future = current_app.extensions['executor'].submit_stored(
                    parent_document_id, 
                    process_document_upload_background, 
                    document_id=parent_document_id, 
                    public_workspace_id=active_workspace_id, 
                    user_id=user_id, 
                    temp_file_path=temp_file_path, 
                    original_filename=original_filename
                )

                processed_docs.append({'document_id': parent_document_id, 'filename': original_filename})

            except Exception as e:
                upload_errors.append(f"Failed to queue processing for {original_filename}: {e}")
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

        
    @app.route('/external/public_documents', methods=['GET'])
    @accesstoken_required
    @enabled_required("enable_public_workspaces")
    def external_get_public_documents():
        """
        Return a paginated, filtered list of documents for the user's *active* public.
        Mirrors logic of api_get_user_documents.
        """
        user_id = request.args.get('user_id')
        active_workspace_id = request.args.get('active_workspace_id')

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
        query_conditions = ["c.public_workspace_id = @public_workspace_id"]
        query_params = [{"name": "@public_workspace_id", "value": active_workspace_id}]
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
            count_items = list(cosmos_public_documents_container.query_items(
                query=count_query_str,
                parameters=query_params,
                enable_cross_partition_query=True
            ))
            total_count = count_items[0] if count_items else 0
        except Exception as e:
            print(f"Error executing count query for public: {e}")
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
            docs = list(cosmos_public_documents_container.query_items(
                query=data_query_str,
                parameters=query_params,
                enable_cross_partition_query=True
            ))
        except Exception as e:
            print(f"Error fetching public documents: {e}")
            return jsonify({"error": f"Error fetching documents: {str(e)}"}), 500

        
        # --- new: do we have any legacy documents? ---
        try:
            legacy_q = """
                SELECT VALUE COUNT(1)
                FROM c
                WHERE c.public_workspace_id = @public_workspace_id
                    AND NOT IS_DEFINED(c.percentage_complete)
            """
            legacy_docs = list(
                cosmos_public_documents_container.query_items(
                    query=legacy_q,
                    parameters=[{"name":"@public_workspace_id","value":active_workspace_id}],
                    enable_cross_partition_query=True
                )
            )
            legacy_count = legacy_docs[0] if legacy_docs else 0
        except Exception as e:
            print(f"Error executing legacy query: {e}")

        # --- 5) Return results ---
        return jsonify({
            "documents": docs,
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
            "needs_legacy_update_check": legacy_count > 0
        }), 200


    @app.route('/external/public_documents/<document_id>', methods=['GET'])
    @accesstoken_required
    @enabled_required("enable_public_workspaces")
    def external_get_public_document(document_id):
        """
        Return metadata for a specific public document, validating public workspace membership.
        Mirrors logic of api_get_user_document.
        """
        user_id = request.args.get('user_id')
        active_workspace_id = request.args.get('active_workspace_id')

        if not user_id:
            return jsonify({'error': 'user_id not defined'}), 401

        if not active_workspace_id:
            return jsonify({'error': 'active_workspace_id not defined'}), 401

        return get_document(user_id=user_id, document_id=document_id, public_workspace_id=active_workspace_id)

    @app.route('/external/public_documents/<document_id>', methods=['PATCH'])
    @accesstoken_required
    @enabled_required("enable_public_workspaces")
    def external_patch_public_document(document_id):
        """
        Update metadata fields for a public document. Mirrors logic from api_patch_user_document.
        """
        user_id = request.args.get('user_id')
        active_workspace_id = request.args.get('active_workspace_id')

        if not active_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        public_doc = find_public_workspace_by_id(active_workspace_id)
        if not public_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404

        data = request.get_json()

        try:
            if 'title' in data:
                update_document(
                    document_id=document_id,
                    public_workspace_id=active_workspace_id,
                    user_id=user_id,
                    title=data['title']
                )
            if 'abstract' in data:
                update_document(
                    document_id=document_id,
                    public_workspace_id=active_workspace_id,
                    user_id=user_id,
                    abstract=data['abstract']
                )
            if 'keywords' in data:
                if isinstance(data['keywords'], list):
                    update_document(
                        document_id=document_id,
                        public_workspace_id=active_workspace_id,
                        user_id=user_id,
                        keywords=data['keywords']
                    )
                else:
                    update_document(
                        document_id=document_id,
                        public_workspace_id=active_workspace_id,
                        user_id=user_id,
                        keywords=[kw.strip() for kw in data['keywords'].split(',')]
                    )
            if 'publication_date' in data:
                update_document(
                    document_id=document_id,
                    public_workspace_id=active_workspace_id,
                    user_id=user_id,
                    publication_date=data['publication_date']
                )
            if 'document_classification' in data:
                update_document(
                    document_id=document_id,
                    public_workspace_id=active_workspace_id,
                    user_id=user_id,
                    document_classification=data['document_classification']
                )
            if 'authors' in data:
                if isinstance(data['authors'], list):
                    update_document(
                        document_id=document_id,
                        public_workspace_id=active_workspace_id,
                        user_id=user_id,
                        authors=data['authors']
                    )
                else:
                    update_document(
                        document_id=document_id,
                        public_workspace_id=active_workspace_id,
                        user_id=user_id,
                        authors=[data['authors']]
                    )

            return jsonify({'message': 'Public document metadata updated successfully'}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
   


    @app.route('/external/public_documents/<document_id>', methods=['DELETE'])
    @enabled_required("enable_public_workspaces")
    def external_delete_public_document(document_id):
        """
        Delete a public document and its associated chunks.
        Mirrors api_delete_user_document with public context and permissions.
        """
        user_id = request.args.get('user_id')
        active_workspace_id = request.args.get('active_workspace_id')

        try:
            delete_document(user_id=user_id, document_id=document_id, public_workspace_id=active_workspace_id)
            delete_document_chunks(document_id=document_id, public_workspace_id=active_workspace_id)
            return jsonify({'message': 'Public document deleted successfully'}), 200
        except Exception as e:
            return jsonify({'error': f'Error deleting public document: {str(e)}'}), 500


    @app.route('/external/public_documents/<document_id>/extract_metadata', methods=['POST'])
    @accesstoken_required
    @enabled_required("enable_public_workspaces")
    def external_extract_public_metadata(document_id):
        """
        POST /external/public_documents/<document_id>/extract_metadata
        Queues a background job to extract metadata for a public document.
        """
        user_id = request.form.get('user_id')
        active_workspace_id = request.form.get('active_workspace_id')

        # Queue the public metadata extraction task
        future = current_app.extensions['executor'].submit_stored(
            f"{document_id}_public_metadata",
            process_metadata_extraction_background,
            document_id=document_id,
            user_id=user_id,
            public_workspace_id=active_workspace_id
        )

        return jsonify({
            'message': 'Public metadata extraction has been queued. Check document status periodically.',
            'document_id': document_id
        }), 200
        
    @app.route('/external/public_documents/upgrade_legacy', methods=['POST'])
    @accesstoken_required
    @enabled_required("enable_public_workspaces")
    def external_upgrade_legacy_public_documents():
        user_id = request.form.get('user_id')
        active_workspace_id = request.form.get('active_workspace_id')

        # returns how many docs were updated
        try:
            # your existing function, but pass public_workspace_id
            count = upgrade_legacy_documents(user_id=user_id, public_workspace_id=active_workspace_id)
            return jsonify({
                "message": f"Upgraded {count} public document(s) to the new format."
            }), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500