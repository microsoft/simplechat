# route_backend_documents.py

from config import *
from functions_authentication import *
from functions_documents import *
from functions_settings import *
import os
import requests
from flask import current_app
from swagger_wrapper import swagger_route, get_auth_security

def register_route_backend_documents(app):
    @app.route('/api/get_file_content', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def get_file_content():
        data = request.get_json()
        user_id = get_current_user_id()
        conversation_id = data.get('conversation_id')
        file_id = data.get('file_id')

        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        if not conversation_id or not file_id:
            return jsonify({'error': 'Missing conversation_id or id'}), 400

        try:
            _ = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation not found'}), 404
        except Exception as e:
            return jsonify({'error': f'Error reading conversation: {str(e)}'}), 500
        
        add_file_task_to_file_processing_log(document_id=file_id, user_id=user_id, content="Conversation exists, retrieving file content")
        try:
            query_str = """
                SELECT * FROM c
                WHERE c.conversation_id = @conversation_id
                AND c.id = @file_id
            """
            items = list(cosmos_messages_container.query_items(
                query=query_str,
                parameters=[
                    {'name': '@conversation_id', 'value': conversation_id},
                    {'name': '@file_id', 'value': file_id}
                ],
                partition_key=conversation_id
            ))

            if not items:
                add_file_task_to_file_processing_log(document_id=file_id, user_id=user_id, content="File not found in conversation")
                return jsonify({'error': 'File not found in conversation'}), 404

            add_file_task_to_file_processing_log(document_id=file_id, user_id=user_id, content="File found, processing content: " + str(items))
            items_sorted = sorted(items, key=lambda x: x.get('chunk_index', 0))

            filename = items_sorted[0].get('filename', 'Untitled')
            is_table = items_sorted[0].get('is_table', False)

            add_file_task_to_file_processing_log(document_id=file_id, user_id=user_id, content="Combining file content from chunks, filename: " + filename + ", is_table: " + str(is_table))
            combined_parts = []
            for it in items_sorted:
                fc = it.get('file_content', '')

                if isinstance(fc, list):
                    # If file_content is a list of dicts, join their 'content' fields
                    text_chunks = []
                    for chunk in fc:
                        text_chunks.append(chunk.get('content', ''))
                    combined_parts.append("\n".join(text_chunks))
                elif isinstance(fc, str):
                    # If it's already a string, just append
                    combined_parts.append(fc)
                else:
                    # If it's neither a list nor a string, handle as needed (e.g., skip or log)
                    pass

            combined_content = "\n".join(combined_parts)

            if not combined_content:
                add_file_task_to_file_processing_log(document_id=file_id, user_id=user_id, content="Combined file content is empty")
                return jsonify({'error': 'File content not found'}), 404

            return jsonify({
                'file_content': combined_content,
                'filename': filename,
                'is_table': is_table
            }), 200

        except Exception as e:
            add_file_task_to_file_processing_log(document_id=file_id, user_id=user_id, content="Error retrieving file content: " + str(e))
            return jsonify({'error': f'Error retrieving file content: {str(e)}'}), 500
    
    @app.route('/api/documents/upload', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def api_user_upload_document():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        if 'file' not in request.files:
            return jsonify({'error': 'No file part in the request'}), 400 # Changed error message slightly

        files = request.files.getlist('file') # Handle multiple files potentially
        if not files or all(not f.filename for f in files):
             return jsonify({'error': 'No file selected or files have no name'}), 400

        processed_docs = []
        upload_errors = []

        for file in files:
            if not file.filename:
                upload_errors.append(f"Skipped a file with no name.")
                continue

            # --- CHANGE: Use original filename directly ---
            original_filename = file.filename
            # Keep secure_filename ONLY for creating the temporary file path suffix
            # to avoid issues with OS path characters, BUT DO NOT use its output elsewhere.
            safe_suffix_filename = secure_filename(original_filename)
            file_ext = os.path.splitext(safe_suffix_filename)[1].lower() # Get extension from safely-suffixed name for temp file

            # --- CHANGE: Validate using the original filename ---
            if not allowed_file(original_filename):
                upload_errors.append(f"File type not allowed for: {original_filename}")
                continue

            # --- Check extension existence from original filename ---
            if not os.path.splitext(original_filename)[1]:
                 upload_errors.append(f"Could not determine file extension for: {original_filename}")
                 continue

            # 1) Save the file temporarily
            parent_document_id = str(uuid.uuid4())
            temp_file_path = None # Initialize
            try:
                # The user can configure the app service to use azure storage for temp files,
                # Check if the 'sc-temp-files' folder exists, and if so, use it.
                # Otherwise, use the default system temp directory.
                sc_temp_files_dir = "/sc-temp-files" if os.path.exists("/sc-temp-files") else ""

                # Use NamedTemporaryFile for automatic cleanup, generate safe suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext, dir=sc_temp_files_dir) as tmp_file:
                    file.save(tmp_file.name)
                    temp_file_path = tmp_file.name
            except Exception as e:
                 upload_errors.append(f"Failed to save temporary file for {original_filename}: {e}")
                 if temp_file_path and os.path.exists(temp_file_path):
                     os.remove(temp_file_path) # Clean up if partially created
                 continue # Skip this file

            try:
                # 2) Create the Cosmos metadata with status="Queued"
                # --- CHANGE: Use original_filename for file_name ---
                create_document(
                    file_name=original_filename,
                    user_id=user_id,
                    document_id=parent_document_id,
                    num_file_chunks=0, # This likely gets updated later
                    status="Queued for processing"
                )

                # (Optional) set initial percentage
                update_document(
                    document_id=parent_document_id,
                    user_id=user_id,
                    percentage_complete=0
                )

                # 3) Now run heavy-lifting in a background thread
                # --- CHANGE: Pass original_filename ---
                future = current_app.extensions['executor'].submit_stored(
                    parent_document_id, 
                    process_document_upload_background, 
                    document_id=parent_document_id, 
                    user_id=user_id, 
                    temp_file_path=temp_file_path, 
                    original_filename=original_filename
                )

                processed_docs.append({'document_id': parent_document_id, 'filename': original_filename})

            except Exception as e:
                upload_errors.append(f"Failed to queue processing for {original_filename}: {e}")
                # Clean up temp file if queuing failed after saving
                if temp_file_path and os.path.exists(temp_file_path):
                    os.remove(temp_file_path)

        # 4) Return immediately to the user with doc IDs and any errors
        response_status = 200 if processed_docs and not upload_errors else 207 # Multi-Status if partial success/errors
        if not processed_docs and upload_errors: response_status = 400 # Bad Request if all failed

        # NOTE: For workspace uploads, we do NOT create conversations or chat messages.
        # Files uploaded to workspaces are for document storage/management, not for immediate chat interaction.
        # Users can later search these documents in chat if needed.

        return jsonify({
            'message': f'Processed {len(processed_docs)} file(s). Check status periodically.',
            'document_ids': [doc['document_id'] for doc in processed_docs],
            'processed_filenames': [doc['filename'] for doc in processed_docs],
            'errors': upload_errors
        }), response_status


    @app.route('/api/documents', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def api_get_user_documents():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        # --- 1) Read pagination and filter parameters ---
        page = request.args.get('page', default=1, type=int)
        page_size = request.args.get('page_size', default=10, type=int)
        search_term = request.args.get('search', default=None, type=str)
        classification_filter = request.args.get('classification', default=None, type=str)
        author_filter = request.args.get('author', default=None, type=str)
        keywords_filter = request.args.get('keywords', default=None, type=str)
        abstract_filter = request.args.get('abstract', default=None, type=str)

        # Ensure page and page_size are positive
        if page < 1: page = 1
        if page_size < 1: page_size = 10
        # Limit page size to prevent abuse? (Optional)
        # page_size = min(page_size, 100)

        # --- 2) Build dynamic WHERE clause and parameters ---
        # Include documents owned by user OR shared with user via shared_user_ids
        query_conditions = ["(c.user_id = @user_id OR ARRAY_CONTAINS(c.shared_user_ids, @user_id))"]
        query_params = [{"name": "@user_id", "value": user_id}]
        param_count = 0 # To generate unique parameter names

        # Add user_id prefix for shared_user_ids with status
        user_id_prefix = f"{user_id},"
        query_params.append({"name": "@user_id_prefix", "value": user_id_prefix})

        # Replace the main ownership/shared condition
        query_conditions[0] = (
            "(c.user_id = @user_id "
            "OR ARRAY_CONTAINS(c.shared_user_ids, @user_id) "
            "OR EXISTS(SELECT VALUE s FROM s IN c.shared_user_ids WHERE STARTSWITH(s, @user_id_prefix)))"
        )
        # General Search (File Name / Title)
        if search_term:
            param_name = f"@search_term_{param_count}"
            # Case-insensitive search using LOWER and CONTAINS
            query_conditions.append(f"(CONTAINS(LOWER(c.file_name ?? ''), LOWER({param_name})) OR CONTAINS(LOWER(c.title ?? ''), LOWER({param_name})))")
            query_params.append({"name": param_name, "value": search_term})
            param_count += 1

        # Classification Filter
        if classification_filter:
            param_name = f"@classification_{param_count}"
            if classification_filter.lower() == 'none':
                # Filter for documents where classification is null, undefined, or empty string
                query_conditions.append(f"(NOT IS_DEFINED(c.document_classification) OR c.document_classification = null OR c.document_classification = '')")
                # No parameter needed for this specific condition
            else:
                query_conditions.append(f"c.document_classification = {param_name}")
                query_params.append({"name": param_name, "value": classification_filter})
                param_count += 1

        # Author Filter (Assuming 'authors' is an array of strings)
        if author_filter:
            param_name = f"@author_{param_count}"
            # Use ARRAY_CONTAINS for searching within the authors array (case-insensitive)
            # Note: This checks if the array *contains* the exact author string.
            # Case-insensitive substring match for any author
            query_conditions.append(f"EXISTS(SELECT VALUE a FROM a IN c.authors WHERE CONTAINS(LOWER(a), LOWER({param_name})))")
            query_params.append({"name": param_name, "value": author_filter})
            param_count += 1

        # Keywords Filter (Assuming 'keywords' is an array of strings)
        if keywords_filter:
            param_name = f"@keywords_{param_count}"
            # Case-insensitive substring match for any keyword
            query_conditions.append(f"EXISTS(SELECT VALUE k FROM k IN c.keywords WHERE CONTAINS(LOWER(k), LOWER({param_name})))")
            query_params.append({"name": param_name, "value": keywords_filter})
            param_count += 1

        # Abstract Filter
        if abstract_filter:
            param_name = f"@abstract_{param_count}"
            # Case-insensitive search using LOWER and CONTAINS
            query_conditions.append(f"CONTAINS(LOWER(c.abstract ?? ''), LOWER({param_name}))")
            query_params.append({"name": param_name, "value": abstract_filter})
            param_count += 1

        # Combine conditions into the WHERE clause
        where_clause = " AND ".join(query_conditions)

        # --- 3) First query: get total count based on filters ---
        try:
            count_query_str = f"SELECT VALUE COUNT(1) FROM c WHERE {where_clause}"
            # print(f"DEBUG Count Query: {count_query_str}") # Optional Debugging
            # print(f"DEBUG Count Params: {query_params}")    # Optional Debugging
            count_items = list(cosmos_user_documents_container.query_items(
                query=count_query_str,
                parameters=query_params,
                enable_cross_partition_query=True # May be needed if user_id is not partition key
            ))
            total_count = count_items[0] if count_items else 0

        except Exception as e:
            print(f"Error executing count query: {e}") # Log the error
            return jsonify({"error": f"Error counting documents: {str(e)}"}), 500


        # --- 4) Second query: fetch the page of data based on filters ---
        try:
            offset = (page - 1) * page_size
            # Note: ORDER BY c._ts DESC to show newest first
            data_query_str = f"""
                SELECT *
                FROM c
                WHERE {where_clause}
                ORDER BY c._ts DESC
                OFFSET {offset} LIMIT {page_size}
            """
            # print(f"DEBUG Data Query: {data_query_str}") # Optional Debugging
            # print(f"DEBUG Data Params: {query_params}")    # Optional Debugging
            docs = list(cosmos_user_documents_container.query_items(
                query=data_query_str,
                parameters=query_params,
                enable_cross_partition_query=True # May be needed if user_id is not partition key
            ))

            # Add shared_approval_status and owner_id for each doc
            for doc in docs:
                doc["owner_id"] = doc.get("user_id")  # Always set owner_id to the original user_id
                if doc.get("user_id") == user_id:
                    doc["shared_approval_status"] = "owner"
                else:
                    # Find entry for this user in shared_user_ids
                    status = None
                    for entry in doc.get("shared_user_ids", []):
                        if entry.startswith(f"{user_id},"):
                            status = entry.split(",", 1)[1]
                            break
                    doc["shared_approval_status"] = status or "none"
        except Exception as e:
            print(f"Error executing data query: {e}") # Log the error
            return jsonify({"error": f"Error fetching documents: {str(e)}"}), 500

        
        # --- new: do we have any legacy documents? ---
        try:
            legacy_q = """
                SELECT VALUE COUNT(1)
                FROM c
                WHERE c.user_id = @user_id
                    AND NOT IS_DEFINED(c.percentage_complete)
            """
            legacy_docs = list(
                cosmos_user_documents_container.query_items(
                    query=legacy_q,
                    parameters=[{"name":"@user_id","value":user_id}],
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

    @app.route('/api/documents/<document_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def api_get_user_document(document_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        return get_document(user_id, document_id)

    @app.route('/api/documents/<document_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def api_patch_user_document(document_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json()  # new metadata values from the client

        # Update allowed fields
        # You can decide which fields can be updated from the client
        if 'title' in data:
            update_document(
                document_id=document_id,
                user_id=user_id,
                title=data['title']
            )
        if 'abstract' in data:
            update_document(
                document_id=document_id,
                user_id=user_id,
                abstract=data['abstract']
            )
        if 'keywords' in data:
            # Expect a list or a comma-delimited string
            if isinstance(data['keywords'], list):
                update_document(
                    document_id=document_id,
                    user_id=user_id,
                    keywords=data['keywords']
                )
            else:
                # if client sends a comma-separated string of keywords
                update_document(
                    document_id=document_id,
                    user_id=user_id,
                    keywords=[kw.strip() for kw in data['keywords'].split(',')]
                )
        if 'publication_date' in data:
            update_document(
                document_id=document_id,
                user_id=user_id,
                publication_date=data['publication_date']
            )
        if 'document_classification' in data:
            update_document(
                document_id=document_id,
                user_id=user_id,
                document_classification=data['document_classification']
            )
        # Add authors if you want to allow editing that
        if 'authors' in data:
            # if you want a list, or just store a string
            # here is one approach:
            if isinstance(data['authors'], list):
                update_document(
                    document_id=document_id,
                    user_id=user_id,
                    authors=data['authors']
                )
            else:
                update_document(
                    document_id=document_id,
                    user_id=user_id,
                    authors=[data['authors']]
                )

        # Save updates back to Cosmos
        try:
            return jsonify({'message': 'Document metadata updated successfully'}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/documents/<document_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def api_delete_user_document(document_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            delete_document(user_id, document_id)
            delete_document_chunks(document_id)
            return jsonify({'message': 'Document deleted successfully'}), 200
        except Exception as e:
            return jsonify({'error': f'Error deleting document: {str(e)}'}), 500
    
    @app.route('/api/documents/<document_id>/extract_metadata', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def api_extract_user_metadata(document_id):
        """
        POST /api/documents/<document_id>/extract_metadata
        Queues a background job that calls extract_document_metadata() 
        and updates the document in Cosmos DB with the new metadata.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        settings = get_settings()
        if not settings.get('enable_extract_meta_data'):
            return jsonify({'error': 'Metadata extraction not enabled'}), 403

        # Queue the background task and store with tracking key
        future = current_app.extensions['executor'].submit_stored(
            f"{document_id}_metadata", 
            process_metadata_extraction_background, 
            document_id=document_id, 
            user_id=user_id
        )

        # Return an immediate response to the user
        return jsonify({
            'message': 'Metadata extraction has been queued. Check document status periodically.',
            'document_id': document_id
        }), 200

    @app.route("/api/get_citation", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_citation():
        data = request.get_json()
        user_id = get_current_user_id()
        citation_id = data.get("citation_id")

        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401
                
        if not citation_id:
            return jsonify({"error": "Missing citation_id"}), 400

        try:
            search_client_user = CLIENTS['search_client_user']
            chunk = search_client_user.get_document(key=citation_id)
            
            # Check if user owns the document or if document is shared with user
            chunk_user_id = chunk.get("user_id")
            chunk_shared_user_ids = chunk.get("shared_user_ids", [])
            
            # Allow access if user is owner or in shared_user_ids (prefix match)
            is_shared = any(
                entry == user_id or entry.startswith(f"{user_id},")
                for entry in chunk_shared_user_ids
            )
            if chunk_user_id != user_id and not is_shared:
                return jsonify({"error": "Unauthorized access to citation"}), 403

            return jsonify({
                "cited_text": chunk.get("chunk_text", ""),
                "file_name": chunk.get("file_name", ""),
                "page_number": chunk.get("chunk_sequence", 0)
            }), 200

        except ResourceNotFoundError:
            pass

        try:
            search_client_group = CLIENTS['search_client_group']
            group_chunk = search_client_group.get_document(key=citation_id)

            return jsonify({
                "cited_text": group_chunk.get("chunk_text", ""),
                "file_name": group_chunk.get("file_name", ""),
                "page_number": group_chunk.get("chunk_sequence", 0)
            }), 200

        except ResourceNotFoundError:
            pass
        
        try:
            search_client_public = CLIENTS['search_client_public']
            public_chunk = search_client_public.get_document(key=citation_id)

            return jsonify({
                "cited_text": public_chunk.get("chunk_text", ""),
                "file_name": public_chunk.get("file_name", ""),
                "page_number": public_chunk.get("chunk_sequence", 0)
            }), 200
        
        except ResourceNotFoundError:
            return jsonify({"error": "Citation not found in user, group, or public docs"}), 404

        except Exception as e:
            return jsonify({"error": f"Unexpected error: {str(e)}"}), 500
        
    @app.route('/api/documents/upgrade_legacy', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def api_upgrade_legacy_user_documents():
        user_id = get_current_user_id()
        # returns how many docs were updated
        count = upgrade_legacy_documents(user_id)
        return jsonify({
            "message": f"Upgraded {count} document(s) to the new format."
        }), 200

    # Document Sharing API Endpoints
    @app.route('/api/documents/<document_id>/share', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def api_share_document(document_id):
        """Share a document with a user"""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        data = request.get_json()
        target_user_id = data.get('user_id')
        
        if not target_user_id:
            return jsonify({'error': 'user_id is required'}), 400
        
        try:
            # Check if user owns the document
            doc = get_document(user_id, document_id)
            if not doc:
                return jsonify({'error': 'Document not found or access denied'}), 404
            
            # Share the document
            success = share_document_with_user(document_id, user_id, target_user_id)
            if success:
                return jsonify({'message': 'Document shared successfully'}), 200
            else:
                return jsonify({'error': 'Failed to share document'}), 500
                
        except Exception as e:
            return jsonify({'error': f'Error sharing document: {str(e)}'}), 500

    @app.route('/api/documents/<document_id>/unshare', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def api_unshare_document(document_id):
        """Remove sharing of a document from a user"""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        data = request.get_json()
        target_user_id = data.get('user_id')
        
        if not target_user_id:
            return jsonify({'error': 'user_id is required'}), 400
        
        try:
            # Check if user owns the document
            doc = get_document(user_id, document_id)
            if not doc:
                return jsonify({'error': 'Document not found or access denied'}), 404
            
            # Unshare the document
            success = unshare_document_from_user(document_id, user_id, target_user_id)
            if success:
                return jsonify({'message': 'Document unshared successfully'}), 200
            else:
                return jsonify({'error': 'Failed to unshare document'}), 500
                
        except Exception as e:
            return jsonify({'error': f'Error unsharing document: {str(e)}'}), 500

    @app.route('/api/documents/<document_id>/shared-users', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def api_get_shared_users(document_id):
        """Get list of users a document is shared with, including approval status"""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            # Check if user owns the document
            doc = get_document(user_id, document_id)
            if not doc:
                return jsonify({'error': 'Document not found or access denied'}), 404
            
            # Get shared users (now returns [{'id': oid, 'approval_status': status}, ...])
            shared_user_objs = get_shared_users_for_document(document_id, user_id)
            
            # Get user details from Microsoft Graph
            shared_users = []
            if shared_user_objs:
                access_token = get_valid_access_token()
                
                if access_token:
                    headers = {
                        'Authorization': f'Bearer {access_token}',
                        'Content-Type': 'application/json'
                    }
                    
                    for entry in shared_user_objs:
                        oid = entry['id']
                        approval_status = entry.get('approval_status', 'unknown')
                        try:
                            # Get user details from Microsoft Graph
                            graph_url = f"https://graph.microsoft.com/v1.0/users/{oid}"
                            response = requests.get(graph_url, headers=headers)
                            
                            if response.status_code == 200:
                                user_data = response.json()
                                shared_users.append({
                                    'id': oid,
                                    'approval_status': approval_status,
                                    'displayName': user_data.get('displayName', 'Unknown User'),
                                    'email': user_data.get('mail') or user_data.get('userPrincipalName', '')
                                })
                            else:
                                # If we can't get user details, still include the ID
                                shared_users.append({
                                    'id': oid,
                                    'approval_status': approval_status,
                                    'displayName': 'Unknown User',
                                    'email': ''
                                })
                        except Exception as e:
                            print(f"Error fetching user details for {oid}: {e}")
                            shared_users.append({
                                'id': oid,
                                'approval_status': approval_status,
                                'displayName': 'Unknown User',
                                'email': ''
                            })
            
            return jsonify({'shared_users': shared_users}), 200
                
        except Exception as e:
            return jsonify({'error': f'Error getting shared users: {str(e)}'}), 500

    @app.route('/api/documents/<document_id>/remove-self', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def api_remove_self_from_document(document_id):
        """Remove current user from shared document"""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
    
        try:
            # Always get the document and extract the dict robustly
            doc_response = get_document(user_id, document_id)
            doc = None
            status_code = None
    
            # Handle (response, status) tuple
            if isinstance(doc_response, tuple):
                resp, status_code = doc_response
                if hasattr(resp, "get_json"):
                    doc = resp.get_json()
                else:
                    doc = resp
            elif hasattr(doc_response, "status_code") and hasattr(doc_response, "get_json"):
                status_code = doc_response.status_code
                doc = doc_response.get_json()
            else:
                doc = doc_response
    
            if status_code is not None and status_code != 200:
                return jsonify({'error': 'Document not found or access denied'}), 404
            if not doc or not isinstance(doc, dict):
                return jsonify({'error': 'Document not found or access denied'}), 404
    
            # Check if user is the owner - owners cannot remove themselves
            if doc.get('user_id') == user_id:
                return jsonify({'error': 'Document owners cannot remove themselves from their own documents'}), 400
    
            # Remove user from shared_user_ids (pass user_id as both requester and target for self-removal)
            success = unshare_document_from_user(document_id, user_id, user_id)
            if success:
                return jsonify({'message': 'Successfully removed from shared document'}), 200
            else:
                return jsonify({'error': 'Failed to remove from shared document'}), 500
    
        except Exception as e:
            print(f"[ERROR] /api/documents/{document_id}/remove-self: {e}", flush=True)
            return jsonify({'error': f'Error removing from shared document: {str(e)}'}), 500

    @app.route('/api/documents/<document_id>/approve-share', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def api_approve_shared_document(document_id):
        """Approve a document that was shared with the current user."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            # Get the document
            document_item = cosmos_user_documents_container.read_item(
                item=document_id,
                partition_key=document_id
            )
            shared_user_ids = document_item.get('shared_user_ids', [])
            updated = False
            new_shared_user_ids = []
            for entry in shared_user_ids:
                if entry.startswith(f"{user_id},"):
                    if entry != f"{user_id},approved":
                        new_shared_user_ids.append(f"{user_id},approved")
                        updated = True
                    else:
                        new_shared_user_ids.append(entry)
                else:
                    new_shared_user_ids.append(entry)
            if updated:
                document_item['shared_user_ids'] = new_shared_user_ids
                document_item['last_updated'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                cosmos_user_documents_container.upsert_item(document_item)
                # Update all chunks with the new shared_user_ids
                try:
                    chunks = get_all_chunks(document_id, document_item.get('user_id'))
                    for chunk in chunks:
                        chunk_id = chunk.get('id')
                        if chunk_id:
                            try:
                                update_chunk_metadata(
                                    chunk_id=chunk_id,
                                    user_id=document_item.get('user_id'),
                                    group_id=None,
                                    public_workspace_id=None,
                                    document_id=document_id,
                                    shared_user_ids=new_shared_user_ids
                                )
                            except Exception as chunk_e:
                                print(f"Warning: Failed to update chunk {chunk_id}: {chunk_e}")
                except Exception as e:
                    print(f"Warning: Failed to update chunks for document {document_id}: {e}")
            return jsonify({'message': 'Share approved' if updated else 'Already approved'}), 200
        except Exception as e:
            return jsonify({'error': f'Error approving shared document: {str(e)}'}), 500