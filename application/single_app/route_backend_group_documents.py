# route_backend_group_documents.py:

from config import *
from functions_authentication import *
from functions_settings import *
from functions_group import *
from functions_documents import *
from utils_cache import invalidate_group_search_cache
from functions_debug import *
from functions_activity_logging import log_document_upload
from flask import current_app
from swagger_wrapper import swagger_route, get_auth_security

def register_route_backend_group_documents(app):
    """
    Provides backend routes for group-level document management:
    - GET /api/group_documents      (list)
    - POST /api/group_documents/upload
    - DELETE /api/group_documents/<doc_id>
    """

    @app.route('/api/group_documents/upload', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_upload_group_document():
        """
        Upload one or more documents to the currently active group.
        Mirrors logic from api_user_upload_document but scoped to group context.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_group_id = user_settings["settings"].get("activeGroupOid")
        if not active_group_id:
            return jsonify({'error': 'No active group selected'}), 400

        group_doc = find_group_by_id(group_id=active_group_id)
        if not group_doc:
            return jsonify({'error': 'Active group not found'}), 404

        # Check if group status allows uploads
        from functions_group import check_group_status_allows_operation
        allowed, reason = check_group_status_allows_operation(group_doc, 'upload')
        if not allowed:
            return jsonify({'error': reason}), 403

        role = get_user_role_in_group(group_doc, user_id)
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
                create_document(
                    file_name=original_filename,
                    group_id=active_group_id,
                    user_id=user_id,
                    document_id=parent_document_id,
                    num_file_chunks=0,
                    status="Queued for processing"
                )

                update_document(
                    document_id=parent_document_id,
                    user_id=user_id,
                    group_id=active_group_id,
                    percentage_complete=0
                )

                future = current_app.extensions['executor'].submit_stored(
                    parent_document_id, 
                    process_document_upload_background, 
                    document_id=parent_document_id, 
                    group_id=active_group_id, 
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

        # Invalidate group search cache since documents were added
        if processed_docs:
            invalidate_group_search_cache(active_group_id)

        return jsonify({
            'message': f'Processed {len(processed_docs)} file(s). Check status periodically.',
            'document_ids': [doc['document_id'] for doc in processed_docs],
            'processed_filenames': [doc['filename'] for doc in processed_docs],
            'errors': upload_errors
        }), response_status

        
    @app.route('/api/group_documents', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_get_group_documents():
        """
        Return a paginated, filtered list of documents for the user's groups.
        Accepts optional `group_ids` query param (comma-separated) to load from
        multiple groups at once. Falls back to single active group from user settings.
        Permission: user must be a member of each group (non-members silently excluded).
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        group_ids_param = request.args.get('group_ids', '')

        if group_ids_param:
            # Multi-group mode: validate each group
            requested_ids = [gid.strip() for gid in group_ids_param.split(',') if gid.strip()]
            validated_group_ids = []
            for gid in requested_ids:
                group_doc = find_group_by_id(gid)
                if not group_doc:
                    continue
                role = get_user_role_in_group(group_doc, user_id)
                if not role:
                    continue
                validated_group_ids.append(gid)

            if not validated_group_ids:
                return jsonify({'documents': [], 'page': 1, 'page_size': 10, 'total_count': 0}), 200
        else:
            # Fallback: single active group from user settings
            user_settings = get_user_settings(user_id)
            active_group_id = user_settings["settings"].get("activeGroupOid")

            if not active_group_id:
                return jsonify({'error': 'No active group selected'}), 400

            group_doc = find_group_by_id(group_id=active_group_id)
            if not group_doc:
                return jsonify({'error': 'Active group not found'}), 404

            role = get_user_role_in_group(group_doc, user_id)
            if not role:
                return jsonify({'error': 'You are not a member of the active group'}), 403

            validated_group_ids = [active_group_id]

        # --- 1) Read pagination and filter parameters ---
        page = request.args.get('page', default=1, type=int)
        page_size = request.args.get('page_size', default=10, type=int)
        search_term = request.args.get('search', default=None, type=str)
        classification_filter = request.args.get('classification', default=None, type=str)
        author_filter = request.args.get('author', default=None, type=str)
        keywords_filter = request.args.get('keywords', default=None, type=str)
        abstract_filter = request.args.get('abstract', default=None, type=str)
        tags_filter = request.args.get('tags', default=None, type=str)
        sort_by = request.args.get('sort_by', default='_ts', type=str)
        sort_order = request.args.get('sort_order', default='desc', type=str)

        if page < 1: page = 1
        if page_size < 1: page_size = 10

        allowed_sort_fields = {'_ts', 'file_name', 'title'}
        if sort_by not in allowed_sort_fields:
            sort_by = '_ts'
        sort_order = sort_order.upper() if sort_order.lower() in ('asc', 'desc') else 'DESC'

        # --- 2) Build dynamic WHERE clause and parameters ---
        # Include documents owned by any validated group OR shared with any validated group
        if len(validated_group_ids) == 1:
            group_condition = "(c.group_id = @group_id_0 OR ARRAY_CONTAINS(c.shared_group_ids, @group_id_0))"
            query_params = [{"name": "@group_id_0", "value": validated_group_ids[0]}]
        else:
            own_parts = []
            shared_parts = []
            query_params = []
            for i, gid in enumerate(validated_group_ids):
                param_name = f"@group_id_{i}"
                own_parts.append(f"c.group_id = {param_name}")
                shared_parts.append(f"ARRAY_CONTAINS(c.shared_group_ids, {param_name})")
                query_params.append({"name": param_name, "value": gid})
            group_condition = f"(({' OR '.join(own_parts)}) OR ({' OR '.join(shared_parts)}))"

        query_conditions = [group_condition]
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
            query_conditions.append(f"EXISTS(SELECT VALUE a FROM a IN c.authors WHERE CONTAINS(LOWER(a), LOWER({param_name})))")
            query_params.append({"name": param_name, "value": author_filter})
            param_count += 1

        if keywords_filter:
            param_name = f"@keywords_{param_count}"
            query_conditions.append(f"EXISTS(SELECT VALUE k FROM k IN c.keywords WHERE CONTAINS(LOWER(k), LOWER({param_name})))")
            query_params.append({"name": param_name, "value": keywords_filter})
            param_count += 1

        if abstract_filter:
            param_name = f"@abstract_{param_count}"
            query_conditions.append(f"CONTAINS(LOWER(c.abstract ?? ''), LOWER({param_name}))")
            query_params.append({"name": param_name, "value": abstract_filter})
            param_count += 1

        if tags_filter:
            from functions_documents import normalize_tag
            tags_list = [normalize_tag(t.strip()) for t in tags_filter.split(',') if t.strip()]
            if tags_list:
                for idx, tag in enumerate(tags_list):
                    param_name = f"@tag_{param_count}_{idx}"
                    query_conditions.append(f"ARRAY_CONTAINS(c.tags, {param_name})")
                    query_params.append({"name": param_name, "value": tag})
                param_count += len(tags_list)

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
                ORDER BY c.{sort_by} {sort_order}
                OFFSET {offset} LIMIT {page_size}
            """
            docs = list(cosmos_group_documents_container.query_items(
                query=data_query_str,
                parameters=query_params,
                enable_cross_partition_query=True
            ))
        except Exception as e:
            print(f"Error fetching group documents: {e}")
            return jsonify({"error": f"Error fetching documents: {str(e)}"}), 500

        
        # --- new: do we have any legacy documents? ---
        legacy_count = 0
        try:
            if len(validated_group_ids) == 1:
                legacy_q = """
                    SELECT VALUE COUNT(1)
                    FROM c
                    WHERE c.group_id = @group_id
                        AND NOT IS_DEFINED(c.percentage_complete)
                """
                legacy_docs = list(
                    cosmos_group_documents_container.query_items(
                        query=legacy_q,
                        parameters=[{"name":"@group_id","value":validated_group_ids[0]}],
                        enable_cross_partition_query=True
                    )
                )
                legacy_count = legacy_docs[0] if legacy_docs else 0
            else:
                # For multi-group, check each group
                for gid in validated_group_ids:
                    legacy_q = """
                        SELECT VALUE COUNT(1)
                        FROM c
                        WHERE c.group_id = @group_id
                            AND NOT IS_DEFINED(c.percentage_complete)
                    """
                    legacy_docs = list(
                        cosmos_group_documents_container.query_items(
                            query=legacy_q,
                            parameters=[{"name":"@group_id","value":gid}],
                            enable_cross_partition_query=True
                        )
                    )
                    legacy_count += legacy_docs[0] if legacy_docs else 0
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

    @app.route('/api/group_documents/<document_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_get_group_document(document_id):
        """
        Return metadata for a specific group document, validating group membership.
        Mirrors logic of api_get_user_document.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_group_id = user_settings["settings"].get("activeGroupOid")

        if not active_group_id:
            return jsonify({'error': 'No active group selected'}), 400

        group_doc = find_group_by_id(active_group_id)
        if not group_doc:
            return jsonify({'error': 'Active group not found'}), 404

        role = get_user_role_in_group(group_doc, user_id)
        if not role:
            return jsonify({'error': 'You are not a member of the active group'}), 403

        return get_document(user_id=user_id, document_id=document_id, group_id=active_group_id)

    @app.route('/api/group_documents/<document_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_patch_group_document(document_id):
        """
        Update metadata fields for a group document. Mirrors logic from api_patch_user_document.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_group_id = user_settings["settings"].get("activeGroupOid")

        if not active_group_id:
            return jsonify({'error': 'No active group selected'}), 400

        group_doc = find_group_by_id(active_group_id)
        if not group_doc:
            return jsonify({'error': 'Active group not found'}), 404

        role = get_user_role_in_group(group_doc, user_id)
        if role not in ["Owner", "Admin", "DocumentManager"]:
            return jsonify({'error': 'You do not have permission to update documents in this group'}), 403

        data = request.get_json()
        
        # Track which fields were updated
        updated_fields = {}

        try:
            if 'title' in data:
                update_document(
                    document_id=document_id,
                    group_id=active_group_id,
                    user_id=user_id,
                    title=data['title']
                )
                updated_fields['title'] = data['title']
            if 'abstract' in data:
                update_document(
                    document_id=document_id,
                    group_id=active_group_id,
                    user_id=user_id,
                    abstract=data['abstract']
                )
                updated_fields['abstract'] = data['abstract']
            if 'keywords' in data:
                if isinstance(data['keywords'], list):
                    update_document(
                        document_id=document_id,
                        group_id=active_group_id,
                        user_id=user_id,
                        keywords=data['keywords']
                    )
                    updated_fields['keywords'] = data['keywords']
                else:
                    keywords_list = [kw.strip() for kw in data['keywords'].split(',')]
                    update_document(
                        document_id=document_id,
                        group_id=active_group_id,
                        user_id=user_id,
                        keywords=keywords_list
                    )
                    updated_fields['keywords'] = keywords_list
            if 'publication_date' in data:
                update_document(
                    document_id=document_id,
                    group_id=active_group_id,
                    user_id=user_id,
                    publication_date=data['publication_date']
                )
                updated_fields['publication_date'] = data['publication_date']
            if 'document_classification' in data:
                update_document(
                    document_id=document_id,
                    group_id=active_group_id,
                    user_id=user_id,
                    document_classification=data['document_classification']
                )
                updated_fields['document_classification'] = data['document_classification']
            if 'authors' in data:
                if isinstance(data['authors'], list):
                    update_document(
                        document_id=document_id,
                        group_id=active_group_id,
                        user_id=user_id,
                        authors=data['authors']
                    )
                    updated_fields['authors'] = data['authors']
                else:
                    authors_list = [data['authors']]
                    update_document(
                        document_id=document_id,
                        group_id=active_group_id,
                        user_id=user_id,
                        authors=authors_list
                    )
                    updated_fields['authors'] = authors_list

            if 'tags' in data:
                from functions_documents import validate_tags, get_or_create_tag_definition
                tags_input = data['tags'] if isinstance(data['tags'], list) else []
                is_valid, error_msg, normalized_tags = validate_tags(tags_input)
                if not is_valid:
                    return jsonify({'error': error_msg}), 400
                for tag in normalized_tags:
                    get_or_create_tag_definition(user_id, tag, workspace_type='group', group_id=active_group_id)
                update_document(
                    document_id=document_id,
                    group_id=active_group_id,
                    user_id=user_id,
                    tags=normalized_tags
                )
                updated_fields['tags'] = normalized_tags

            # Log the metadata update transaction if any fields were updated
            if updated_fields:
                # Get document details for logging
                from functions_documents import get_document
                doc = get_document(user_id, document_id, group_id=active_group_id)
                if doc:
                    from functions_activity_logging import log_document_metadata_update_transaction
                    log_document_metadata_update_transaction(
                        user_id=user_id,
                        document_id=document_id,
                        workspace_type='group',
                        file_name=doc.get('file_name', 'Unknown'),
                        updated_fields=updated_fields,
                        file_type=doc.get('file_type'),
                        group_id=active_group_id
                    )

            return jsonify({'message': 'Group document metadata updated successfully'}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
   
    @app.route('/api/group_documents/<document_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_delete_group_document(document_id):
        """
        Delete a group document and its associated chunks.
        Mirrors api_delete_user_document with group context and permissions.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_group_id = user_settings["settings"].get("activeGroupOid")

        if not active_group_id:
            return jsonify({'error': 'No active group selected'}), 400

        group_doc = find_group_by_id(active_group_id)
        if not group_doc:
            return jsonify({'error': 'Active group not found'}), 404

        # Check if group status allows deletions
        from functions_group import check_group_status_allows_operation
        allowed, reason = check_group_status_allows_operation(group_doc, 'delete')
        if not allowed:
            return jsonify({'error': reason}), 403

        role = get_user_role_in_group(group_doc, user_id)
        if role not in ["Owner", "Admin", "DocumentManager"]:
            return jsonify({'error': 'You do not have permission to delete documents in this group'}), 403

        try:
            delete_document(user_id=user_id, document_id=document_id, group_id=active_group_id)
            delete_document_chunks(document_id=document_id, group_id=active_group_id)
            
            # Invalidate group search cache since document was deleted
            invalidate_group_search_cache(active_group_id)
            
            return jsonify({'message': 'Group document deleted successfully'}), 200
        except Exception as e:
            return jsonify({'error': f'Error deleting group document: {str(e)}'}), 500

    @app.route('/api/group_documents/<document_id>/extract_metadata', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_extract_group_metadata(document_id):
        """
        POST /api/group_documents/<document_id>/extract_metadata
        Queues a background job to extract metadata for a group document.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        settings = get_settings()
        if not settings.get('enable_extract_meta_data'):
            return jsonify({'error': 'Metadata extraction not enabled'}), 403

        user_settings = get_user_settings(user_id)
        active_group_id = user_settings["settings"].get("activeGroupOid")

        if not active_group_id:
            return jsonify({'error': 'No active group selected'}), 400

        group_doc = find_group_by_id(active_group_id)
        if not group_doc:
            return jsonify({'error': 'Active group not found'}), 404

        role = get_user_role_in_group(group_doc, user_id)
        if role not in ["Owner", "Admin", "DocumentManager"]:
            return jsonify({'error': 'You do not have permission to extract metadata for this group document'}), 403

        # Queue the group metadata extraction task
        future = current_app.extensions['executor'].submit_stored(
            f"{document_id}_group_metadata",
            process_metadata_extraction_background,
            document_id=document_id,
            user_id=user_id,
            group_id=active_group_id
        )

        return jsonify({
            'message': 'Group metadata extraction has been queued. Check document status periodically.',
            'document_id': document_id
        }), 200
        
    @app.route('/api/group_documents/upgrade_legacy', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_upgrade_legacy_group_documents():
        user_id = get_current_user_id()
        settings = get_user_settings(user_id)
        active_group_id = settings["settings"].get("activeGroupOid")
        if not active_group_id:
            return jsonify({'error':'No active group selected'}), 400

        group_doc = find_group_by_id(active_group_id)
        if not group_doc:
            return jsonify({'error':'Active group not found'}), 404

        role = get_user_role_in_group(group_doc, user_id)
        if role not in ["Owner","Admin","DocumentManager"]:
            return jsonify({'error':'Insufficient permissions'}), 403
        # returns how many docs were updated
        try:
            # your existing function, but pass group_id
            count = upgrade_legacy_documents(user_id=user_id, group_id=active_group_id)
            return jsonify({
                "message": f"Upgraded {count} group document(s) to the new format."
            }), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
            
    @app.route('/api/group_documents/<document_id>/shared-groups', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_get_document_shared_groups(document_id):
        """
        GET /api/group_documents/<document_id>/shared-groups
        Returns a list of groups that the document is shared with.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_group_id = user_settings["settings"].get("activeGroupOid")

        if not active_group_id:
            return jsonify({'error': 'No active group selected'}), 400

        group_doc = find_group_by_id(active_group_id)
        if not group_doc:
            return jsonify({'error': 'Active group not found'}), 404

        role = get_user_role_in_group(group_doc, user_id)
        if not role:
            return jsonify({'error': 'You are not a member of the active group'}), 403

        # Get the document
        try:
            document = get_document_metadata(document_id=document_id, user_id=user_id, group_id=active_group_id)
            if not document:
                return jsonify({'error': 'Document not found'}), 404
                
            # Check if user has permission to view shared groups
            if document.get('group_id') != active_group_id and active_group_id not in document.get('shared_group_ids', []):
                return jsonify({'error': 'You do not have access to this document'}), 403
                
            # Get the list of shared group IDs
            shared_group_ids = document.get('shared_group_ids', [])
            
            # Get details for each shared group
            shared_groups = []
            for entry in shared_group_ids:
                if ',' in entry:
                    group_oid, status = entry.split(',', 1)
                else:
                    group_oid, status = entry, 'unknown'
                group = find_group_by_id(group_oid)
                if group:
                    shared_groups.append({
                        'id': group['id'],
                        'name': group.get('name', 'Unknown Group'),
                        'description': group.get('description', ''),
                        'approval_status': status
                    })
                else:
                    shared_groups.append({
                        'id': group_oid,
                        'name': 'Unknown Group',
                        'description': '',
                        'approval_status': status
                    })
            
            return jsonify({'shared_groups': shared_groups}), 200
        except Exception as e:
            return jsonify({'error': f'Error retrieving shared groups: {str(e)}'}), 500
        
    @app.route('/api/group_documents/<document_id>/approve-share-with-group', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_approve_shared_group_document(document_id):
        """
        Approve a document that was shared with the current group.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_group_id = user_settings["settings"].get("activeGroupOid")
        if not active_group_id:
            return jsonify({'error': 'No active group selected'}), 400

        try:
            # Get the document
            document_item = get_document_metadata(document_id=document_id, user_id=user_id, group_id=active_group_id)
            if not document_item:
                return jsonify({'error': 'Document not found or access denied'}), 404
            shared_group_ids = document_item.get('shared_group_ids', [])
            updated = False
            new_shared_group_ids = []
            for entry in shared_group_ids:
                if entry.startswith(f"{active_group_id},"):
                    if entry != f"{active_group_id},approved":
                        new_shared_group_ids.append(f"{active_group_id},approved")
                        updated = True
                    else:
                        new_shared_group_ids.append(entry)
                else:
                    new_shared_group_ids.append(entry)
            if updated:
                update_document(
                    document_id=document_id,
                    group_id=document_item.get('group_id'),
                    user_id=user_id,
                    shared_group_ids=new_shared_group_ids
                )
                # Invalidate cache for the group that approved
                invalidate_group_search_cache(active_group_id)
            
            return jsonify({'message': 'Share approved' if updated else 'Already approved'}), 200
        except Exception as e:
            return jsonify({'error': f'Error approving shared document: {str(e)}'}), 500

    @app.route('/api/group_documents/<document_id>/share-with-group', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_share_document_with_group(document_id):
        """
        POST /api/group_documents/<document_id>/share-with-group
        Shares a document with a group.
        Expects JSON: { "group_id": "<group_id>" }
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_group_id = user_settings["settings"].get("activeGroupOid")

        if not active_group_id:
            return jsonify({'error': 'No active group selected'}), 400

        group_doc = find_group_by_id(active_group_id)
        if not group_doc:
            return jsonify({'error': 'Active group not found'}), 404

        role = get_user_role_in_group(group_doc, user_id)
        if role not in ["Owner", "Admin", "DocumentManager"]:
            return jsonify({'error': 'You do not have permission to share documents in this group'}), 403

        data = request.get_json()
        if not data or 'group_id' not in data:
            return jsonify({'error': 'Missing group_id in request'}), 400
            
        target_group_id = data['group_id']
        
        # Verify target group exists
        target_group = find_group_by_id(target_group_id)
        if not target_group:
            return jsonify({'error': 'Target group not found'}), 404
            
        # Get the document
        try:
            document = get_document_metadata(document_id=document_id, user_id=user_id, group_id=active_group_id)
            if not document:
                return jsonify({'error': 'Document not found'}), 404
                
            # Check if document belongs to active group
            if document.get('group_id') != active_group_id:
                return jsonify({'error': 'You can only share documents owned by your active group'}), 403
                
            # Add target group to shared_group_ids if not already there
            shared_group_ids = document.get('shared_group_ids', [])
            if target_group_id not in shared_group_ids:
                shared_group_ids.append(target_group_id)
                
                # Update the document
                update_document(
                    document_id=document_id,
                    group_id=active_group_id,
                    user_id=user_id,
                    shared_group_ids=shared_group_ids
                )
                
                # Invalidate cache for both groups
                invalidate_group_search_cache(active_group_id)
                invalidate_group_search_cache(target_group_id)
                
            return jsonify({
                'message': 'Document shared successfully',
                'document_id': document_id,
                'shared_with_group': target_group_id
            }), 200
        except Exception as e:
            return jsonify({'error': f'Error sharing document: {str(e)}'}), 500
            
    @app.route('/api/group_documents/<document_id>/unshare-with-group', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_unshare_document_with_group(document_id):
        """
        DELETE /api/group_documents/<document_id>/unshare-with-group
        Removes sharing of a document with a group.
        Expects JSON: { "group_id": "<group_id>" }
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_group_id = user_settings["settings"].get("activeGroupOid")

        if not active_group_id:
            return jsonify({'error': 'No active group selected'}), 400

        group_doc = find_group_by_id(active_group_id)
        if not group_doc:
            return jsonify({'error': 'Active group not found'}), 404

        role = get_user_role_in_group(group_doc, user_id)
        if role not in ["Owner", "Admin", "DocumentManager"]:
            return jsonify({'error': 'You do not have permission to manage document sharing in this group'}), 403

        data = request.get_json()
        if not data or 'group_id' not in data:
            return jsonify({'error': 'Missing group_id in request'}), 400
            
        target_group_id = data['group_id']
        
        # Get the document
        try:
            document = get_document_metadata(document_id=document_id, user_id=user_id, group_id=active_group_id)
            if not document:
                return jsonify({'error': 'Document not found'}), 404
                
            # Check if document belongs to active group
            if document.get('group_id') != active_group_id:
                return jsonify({'error': 'You can only manage sharing for documents owned by your active group'}), 403
                
            # Remove target group from shared_group_ids if present
            shared_group_ids = document.get('shared_group_ids', [])
            if target_group_id in shared_group_ids:
                shared_group_ids.remove(target_group_id)
                
                # Update the document
                update_document(
                    document_id=document_id,
                    group_id=active_group_id,
                    user_id=user_id,
                    shared_group_ids=shared_group_ids
                )
                
                # Invalidate cache for both groups
                invalidate_group_search_cache(active_group_id)
                invalidate_group_search_cache(target_group_id)
                
            return jsonify({
                'message': 'Document sharing removed successfully',
                'document_id': document_id,
                'unshared_with_group': target_group_id
            }), 200
        except Exception as e:
            return jsonify({'error': f'Error unsharing document: {str(e)}'}), 500

    @app.route('/api/group_documents/<document_id>/remove-self', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_remove_self_from_group_document(document_id):
        """
        Remove the current group from a document's shared_group_ids.
        Allows a group to remove itself from a document it does not own but is shared with.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_group_id = user_settings["settings"].get("activeGroupOid")
        if not active_group_id:
            return jsonify({'error': 'No active group selected'}), 400

        # Get the document metadata
        try:
            document = get_document_metadata(document_id=document_id, user_id=user_id, group_id=active_group_id)
            if not document:
                return jsonify({'error': 'Document not found'}), 404

            # If the group is the owner, do not allow removal
            if document.get('group_id') == active_group_id:
                return jsonify({'error': 'Owning group cannot remove itself from its own document'}), 400

            shared_group_ids = document.get('shared_group_ids', [])
            if active_group_id not in shared_group_ids:
                return jsonify({'error': 'Group is not a shared group for this document'}), 400

            # Remove the group from shared_group_ids
            shared_group_ids = [gid for gid in shared_group_ids if gid != active_group_id]
            update_document(
                document_id=document_id,
                group_id=document.get('group_id'),
                user_id=user_id,
                shared_group_ids=shared_group_ids
            )
            return jsonify({'message': 'Successfully removed group from shared document'}), 200
        except Exception as e:
            return jsonify({'error': f'Error removing group from shared document: {str(e)}'}), 500

    @app.route('/api/group_documents/tags', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_get_group_document_tags():
        """
        Get all unique tags used across one or more group workspaces with document counts.
        Accepts optional `group_ids` query param (comma-separated).
        Falls back to single active group from user settings if not provided.
        Permission: user must be a member of each group (non-members silently excluded).
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        group_ids_param = request.args.get('group_ids', '')

        if group_ids_param:
            group_ids = [gid.strip() for gid in group_ids_param.split(',') if gid.strip()]
        else:
            user_settings = get_user_settings(user_id)
            active_group_id = user_settings["settings"].get("activeGroupOid")
            group_ids = [active_group_id] if active_group_id else []

        from functions_documents import get_workspace_tags

        all_tags = {}
        for gid in group_ids:
            group_doc = find_group_by_id(gid)
            if not group_doc:
                continue
            role = get_user_role_in_group(group_doc, user_id)
            if not role:
                continue

            tags = get_workspace_tags(user_id, group_id=gid)
            for tag in tags:
                if tag['name'] in all_tags:
                    all_tags[tag['name']]['count'] += tag['count']
                else:
                    all_tags[tag['name']] = dict(tag)

        merged = sorted(all_tags.values(), key=lambda t: t['name'])
        return jsonify({'tags': merged}), 200

    @app.route('/api/group_documents/tags', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_create_group_tag():
        """
        Create a new tag in the group workspace.

        Request body:
        {
            "tag_name": "new-tag",
            "color": "#3b82f6"  // optional
        }
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_group_id = user_settings["settings"].get("activeGroupOid")
        if not active_group_id:
            return jsonify({'error': 'No active group selected'}), 400

        group_doc = find_group_by_id(group_id=active_group_id)
        if not group_doc:
            return jsonify({'error': 'Active group not found'}), 404

        role = get_user_role_in_group(group_doc, user_id)
        if role not in ["Owner", "Admin", "DocumentManager"]:
            return jsonify({'error': 'You do not have permission to manage tags'}), 403

        data = request.get_json()
        tag_name = data.get('tag_name')
        color = data.get('color', '#0d6efd')

        if not tag_name:
            return jsonify({'error': 'tag_name is required'}), 400

        from functions_documents import normalize_tag, validate_tags
        from datetime import datetime, timezone

        try:
            is_valid, error_msg, normalized_tags = validate_tags([tag_name])
            if not is_valid:
                return jsonify({'error': error_msg}), 400

            normalized_tag = normalized_tags[0]

            tag_defs = group_doc.get('tag_definitions', {})

            if normalized_tag in tag_defs:
                return jsonify({'error': 'Tag already exists'}), 409

            tag_defs[normalized_tag] = {
                'color': color,
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            group_doc['tag_definitions'] = tag_defs
            cosmos_groups_container.upsert_item(group_doc)

            return jsonify({
                'message': f'Tag "{normalized_tag}" created successfully',
                'tag': {
                    'name': normalized_tag,
                    'color': color
                }
            }), 201

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/group_documents/bulk-tag', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_bulk_tag_group_documents():
        """
        Apply tag operations to multiple group documents.

        Request body:
        {
            "document_ids": ["doc1", "doc2", ...],
            "action": "add_tags" | "remove_tags" | "set_tags",
            "tags": ["tag1", "tag2", ...]
        }
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_group_id = user_settings["settings"].get("activeGroupOid")
        if not active_group_id:
            return jsonify({'error': 'No active group selected'}), 400

        group_doc = find_group_by_id(group_id=active_group_id)
        if not group_doc:
            return jsonify({'error': 'Active group not found'}), 404

        role = get_user_role_in_group(group_doc, user_id)
        if role not in ["Owner", "Admin", "DocumentManager"]:
            return jsonify({'error': 'You do not have permission to manage tags'}), 403

        data = request.get_json()
        document_ids = data.get('document_ids', [])
        action = data.get('action')
        tags_input = data.get('tags', [])

        if not document_ids or not isinstance(document_ids, list):
            return jsonify({'error': 'document_ids must be a non-empty array'}), 400

        if action not in ['add_tags', 'remove_tags', 'set_tags']:
            return jsonify({'error': 'action must be add_tags, remove_tags, or set_tags'}), 400

        from functions_documents import (
            validate_tags, update_document,
            propagate_tags_to_chunks, get_or_create_tag_definition
        )

        is_valid, error_msg, normalized_tags = validate_tags(tags_input)
        if not is_valid:
            return jsonify({'error': error_msg}), 400

        for tag in normalized_tags:
            get_or_create_tag_definition(user_id, tag, workspace_type='group', group_id=active_group_id)

        results = {
            'success': [],
            'errors': []
        }

        try:
            for doc_id in document_ids:
                try:
                    query = "SELECT TOP 1 * FROM c WHERE c.id = @document_id AND c.group_id = @group_id ORDER BY c.version DESC"
                    parameters = [
                        {"name": "@document_id", "value": doc_id},
                        {"name": "@group_id", "value": active_group_id}
                    ]

                    document_results = list(
                        cosmos_group_documents_container.query_items(
                            query=query,
                            parameters=parameters,
                            enable_cross_partition_query=True
                        )
                    )

                    if not document_results:
                        results['errors'].append({
                            'document_id': doc_id,
                            'error': 'Document not found or access denied'
                        })
                        continue

                    doc = document_results[0]
                    current_tags = doc.get('tags', [])
                    new_tags = []

                    if action == 'add_tags':
                        new_tags = list(set(current_tags + normalized_tags))
                    elif action == 'remove_tags':
                        new_tags = [t for t in current_tags if t not in normalized_tags]
                    elif action == 'set_tags':
                        new_tags = normalized_tags

                    update_document(
                        document_id=doc_id,
                        group_id=active_group_id,
                        user_id=user_id,
                        tags=new_tags
                    )

                    try:
                        propagate_tags_to_chunks(doc_id, new_tags, user_id, group_id=active_group_id)
                    except Exception:
                        pass

                    results['success'].append({
                        'document_id': doc_id,
                        'tags': new_tags
                    })

                except Exception as doc_error:
                    results['errors'].append({
                        'document_id': doc_id,
                        'error': str(doc_error)
                    })

            if results['success']:
                invalidate_group_search_cache(active_group_id)

            status_code = 200 if not results['errors'] else 207
            return jsonify(results), status_code

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/group_documents/tags/<tag_name>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_update_group_tag(tag_name):
        """
        Update a group tag (rename or change color).

        Request body:
        {
            "new_name": "new-tag-name",  // optional
            "color": "#3b82f6"           // optional
        }
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_group_id = user_settings["settings"].get("activeGroupOid")
        if not active_group_id:
            return jsonify({'error': 'No active group selected'}), 400

        group_doc = find_group_by_id(group_id=active_group_id)
        if not group_doc:
            return jsonify({'error': 'Active group not found'}), 404

        role = get_user_role_in_group(group_doc, user_id)
        if role not in ["Owner", "Admin", "DocumentManager"]:
            return jsonify({'error': 'You do not have permission to manage tags'}), 403

        data = request.get_json()
        new_name = data.get('new_name')
        new_color = data.get('color')

        from functions_documents import normalize_tag, validate_tags, update_document, propagate_tags_to_chunks

        try:
            normalized_old_tag = normalize_tag(tag_name)

            if new_name:
                is_valid, error_msg, normalized_new = validate_tags([new_name])
                if not is_valid:
                    return jsonify({'error': error_msg}), 400

                normalized_new_tag = normalized_new[0]

                query = "SELECT * FROM c WHERE c.group_id = @group_id"
                parameters = [{"name": "@group_id", "value": active_group_id}]
                documents = list(cosmos_group_documents_container.query_items(
                    query=query, parameters=parameters, enable_cross_partition_query=True
                ))

                latest_documents = {}
                for doc in documents:
                    file_name = doc['file_name']
                    if file_name not in latest_documents or doc['version'] > latest_documents[file_name]['version']:
                        latest_documents[file_name] = doc

                all_docs = list(latest_documents.values())
                updated_count = 0

                for doc in all_docs:
                    if normalized_old_tag in doc.get('tags', []):
                        current_tags = doc['tags']
                        new_tags = [normalized_new_tag if t == normalized_old_tag else t for t in current_tags]

                        update_document(
                            document_id=doc['id'],
                            group_id=active_group_id,
                            user_id=user_id,
                            tags=new_tags
                        )

                        try:
                            propagate_tags_to_chunks(doc['id'], new_tags, user_id, group_id=active_group_id)
                        except Exception:
                            pass

                        updated_count += 1

                tag_defs = group_doc.get('tag_definitions', {})
                if normalized_old_tag in tag_defs:
                    old_def = tag_defs.pop(normalized_old_tag)
                    tag_defs[normalized_new_tag] = old_def
                group_doc['tag_definitions'] = tag_defs
                cosmos_groups_container.upsert_item(group_doc)

                invalidate_group_search_cache(active_group_id)

                return jsonify({
                    'message': f'Tag renamed from "{normalized_old_tag}" to "{normalized_new_tag}"',
                    'documents_updated': updated_count
                }), 200

            if new_color:
                tag_defs = group_doc.get('tag_definitions', {})

                if normalized_old_tag in tag_defs:
                    tag_defs[normalized_old_tag]['color'] = new_color
                else:
                    from datetime import datetime, timezone
                    tag_defs[normalized_old_tag] = {
                        'color': new_color,
                        'created_at': datetime.now(timezone.utc).isoformat()
                    }

                group_doc['tag_definitions'] = tag_defs
                cosmos_groups_container.upsert_item(group_doc)

                return jsonify({
                    'message': f'Tag color updated for "{normalized_old_tag}"'
                }), 200

            return jsonify({'error': 'No updates specified'}), 400

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/group_documents/tags/<tag_name>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_delete_group_tag(tag_name):
        """Delete a tag from all documents in the group workspace."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_group_id = user_settings["settings"].get("activeGroupOid")
        if not active_group_id:
            return jsonify({'error': 'No active group selected'}), 400

        group_doc = find_group_by_id(group_id=active_group_id)
        if not group_doc:
            return jsonify({'error': 'Active group not found'}), 404

        role = get_user_role_in_group(group_doc, user_id)
        if role not in ["Owner", "Admin", "DocumentManager"]:
            return jsonify({'error': 'You do not have permission to manage tags'}), 403

        from functions_documents import normalize_tag, update_document, propagate_tags_to_chunks

        try:
            normalized_tag = normalize_tag(tag_name)

            query = "SELECT * FROM c WHERE c.group_id = @group_id"
            parameters = [{"name": "@group_id", "value": active_group_id}]
            documents = list(cosmos_group_documents_container.query_items(
                query=query, parameters=parameters, enable_cross_partition_query=True
            ))

            latest_documents = {}
            for doc in documents:
                file_name = doc['file_name']
                if file_name not in latest_documents or doc['version'] > latest_documents[file_name]['version']:
                    latest_documents[file_name] = doc

            all_docs = list(latest_documents.values())
            updated_count = 0

            for doc in all_docs:
                if normalized_tag in doc.get('tags', []):
                    new_tags = [t for t in doc['tags'] if t != normalized_tag]

                    update_document(
                        document_id=doc['id'],
                        group_id=active_group_id,
                        user_id=user_id,
                        tags=new_tags
                    )

                    try:
                        propagate_tags_to_chunks(doc['id'], new_tags, user_id, group_id=active_group_id)
                    except Exception:
                        pass

                    updated_count += 1

            tag_defs = group_doc.get('tag_definitions', {})
            if normalized_tag in tag_defs:
                tag_defs.pop(normalized_tag)
                group_doc['tag_definitions'] = tag_defs
                cosmos_groups_container.upsert_item(group_doc)

            if updated_count > 0:
                invalidate_group_search_cache(active_group_id)

            return jsonify({
                'message': f'Tag "{normalized_tag}" deleted from {updated_count} document(s)'
            }), 200

        except Exception as e:
            return jsonify({'error': str(e)}), 500
