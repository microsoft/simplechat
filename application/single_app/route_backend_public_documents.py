# route_backend_public_documents.py

from config import *

from functions_authentication import *
from functions_settings import *
from functions_public_workspaces import *
from functions_documents import *
from utils_cache import invalidate_public_workspace_search_cache
from flask import current_app
from functions_debug import *
from swagger_wrapper import swagger_route, get_auth_security

def register_route_backend_public_documents(app):
    """
    Provides backend routes for public-workspace–scoped document management
    """

    @app.route('/api/public_documents/upload', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_upload_public_document():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        settings = get_user_settings(user_id)
        active_ws = settings['settings'].get('activePublicWorkspaceOid')
        if not active_ws:
            return jsonify({'error': 'No active public workspace selected'}), 400

        ws_doc = find_public_workspace_by_id(active_ws)
        if not ws_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404

        allowed, reason = check_public_workspace_status_allows_operation(ws_doc, 'upload')
        if not allowed:
            return jsonify({'error': reason}), 403

        role = get_user_role_in_public_workspace(ws_doc, user_id)
        if role not in ['Owner', 'Admin', 'DocumentManager']:
            return jsonify({'error': 'Insufficient permissions'}), 403

        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        files = request.files.getlist('file')
        processed, errors = [], []

        for f in files:
            if not f.filename:
                errors.append('Skipped empty filename')
                continue
            orig = f.filename
            safe_name = secure_filename(orig)
            ext = os.path.splitext(safe_name)[1].lower()
            if not allowed_file(orig):
                errors.append(f'Type not allowed: {orig}')
                continue
            doc_id = str(uuid.uuid4())
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                    f.save(tmp.name)
                    tmp_path = tmp.name
            except Exception as e:
                errors.append(f'Failed save tmp for {orig}: {e}')
                if tmp_path and os.path.exists(tmp_path): os.remove(tmp_path)
                continue

            try:
                create_document(
                    file_name=orig,
                    public_workspace_id=active_ws,
                    user_id=user_id,
                    document_id=doc_id,
                    num_file_chunks=0,
                    status='Queued'
                )
                update_document(
                    document_id=doc_id,
                    user_id=user_id,
                    public_workspace_id=active_ws,
                    percentage_complete=0
                )
                executor = current_app.extensions['executor']
                executor.submit(
                    process_document_upload_background,
                    document_id=doc_id,
                    public_workspace_id=active_ws,
                    user_id=user_id,
                    temp_file_path=tmp_path,
                    original_filename=orig
                )
                processed.append({'id': doc_id, 'filename': orig})
            except Exception as e:
                errors.append(f'Queue failed for {orig}: {e}')
                if tmp_path and os.path.exists(tmp_path): os.remove(tmp_path)

        status = 200 if processed and not errors else (207 if processed else 400)
        
        # Invalidate public workspace search cache since documents were added
        if processed:
            invalidate_public_workspace_search_cache(active_ws)
        
        return jsonify({
            'message': f'Processed {len(processed)} file(s)',
            'document_ids': [d['id'] for d in processed],
            'errors': errors
        }), status

    @app.route('/api/public_documents', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_list_public_documents():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        settings = get_user_settings(user_id)
        active_ws = settings['settings'].get('activePublicWorkspaceOid')
        if not active_ws:
            return jsonify({'error': 'No active public workspace selected'}), 400

        ws_doc = find_public_workspace_by_id(active_ws)
        if not ws_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404
        from functions_public_workspaces import get_user_role_in_public_workspace
        role = get_user_role_in_public_workspace(ws_doc, user_id)
        if not role:
            return jsonify({'error': 'Access denied'}), 403

        # pagination
        try:
            page = int(request.args.get('page', 1));
        except: page = 1
        try:
            page_size = int(request.args.get('page_size', 10));
        except: page_size = 10
        if page < 1: page = 1
        if page_size < 1: page_size = 10
        offset = (page - 1) * page_size

        # filters
        search = request.args.get('search', '').strip()
        classification_filter = request.args.get('classification', default=None, type=str)
        author_filter = request.args.get('author', default=None, type=str)
        keywords_filter = request.args.get('keywords', default=None, type=str)
        abstract_filter = request.args.get('abstract', default=None, type=str)
        tags_filter = request.args.get('tags', default=None, type=str)
        sort_by = request.args.get('sort_by', default='_ts', type=str)
        sort_order = request.args.get('sort_order', default='desc', type=str)

        allowed_sort_fields = {'_ts', 'file_name', 'title'}
        if sort_by not in allowed_sort_fields:
            sort_by = '_ts'
        sort_order = sort_order.upper() if sort_order.lower() in ('asc', 'desc') else 'DESC'

        # build WHERE
        conds = ['c.public_workspace_id = @ws']
        params = [{'name':'@ws','value':active_ws}]
        param_count = 0
        if search:
            conds.append('(CONTAINS(LOWER(c.file_name), LOWER(@search)) OR CONTAINS(LOWER(c.title), LOWER(@search)))')
            params.append({'name':'@search','value':search})
            param_count += 1

        if classification_filter:
            if classification_filter.lower() == 'none':
                conds.append("(NOT IS_DEFINED(c.document_classification) OR c.document_classification = null OR c.document_classification = '' OR LOWER(c.document_classification) = 'none')")
            else:
                param_name = f"@classification_{param_count}"
                conds.append(f"c.document_classification = {param_name}")
                params.append({'name': param_name, 'value': classification_filter})
                param_count += 1

        if author_filter:
            param_name = f"@author_{param_count}"
            conds.append(f"EXISTS(SELECT VALUE a FROM a IN c.authors WHERE CONTAINS(LOWER(a), LOWER({param_name})))")
            params.append({'name': param_name, 'value': author_filter})
            param_count += 1

        if keywords_filter:
            param_name = f"@keywords_{param_count}"
            conds.append(f"EXISTS(SELECT VALUE k FROM k IN c.keywords WHERE CONTAINS(LOWER(k), LOWER({param_name})))")
            params.append({'name': param_name, 'value': keywords_filter})
            param_count += 1

        if abstract_filter:
            param_name = f"@abstract_{param_count}"
            conds.append(f"CONTAINS(LOWER(c.abstract ?? ''), LOWER({param_name}))")
            params.append({'name': param_name, 'value': abstract_filter})
            param_count += 1

        if tags_filter:
            from functions_documents import normalize_tag
            tags_list = [normalize_tag(t.strip()) for t in tags_filter.split(',') if t.strip()]
            if tags_list:
                for idx, tag in enumerate(tags_list):
                    param_name = f"@tag_{param_count}_{idx}"
                    conds.append(f"ARRAY_CONTAINS(c.tags, {param_name})")
                    params.append({'name': param_name, 'value': tag})
                param_count += len(tags_list)

        where = ' AND '.join(conds)

        # count
        count_q = f'SELECT VALUE COUNT(1) FROM c WHERE {where}'
        total = list(cosmos_public_documents_container.query_items(
            query=count_q, parameters=params, enable_cross_partition_query=True
        ))
        total_count = total[0] if total else 0

        # data
        data_q = f'SELECT * FROM c WHERE {where} ORDER BY c.{sort_by} {sort_order} OFFSET {offset} LIMIT {page_size}'
        docs = list(cosmos_public_documents_container.query_items(
            query=data_q, parameters=params, enable_cross_partition_query=True
        ))

        # legacy
        legacy_q = 'SELECT VALUE COUNT(1) FROM c WHERE c.public_workspace_id = @ws AND NOT IS_DEFINED(c.percentage_complete)'
        legacy = list(cosmos_public_documents_container.query_items(
            query=legacy_q,
            parameters=[{'name':'@ws','value':active_ws}],
            enable_cross_partition_query=True
        ))
        legacy_count = legacy[0] if legacy else 0

        return jsonify({
            'documents': docs,
            'page': page,
            'page_size': page_size,
            'total_count': total_count,
            'needs_legacy_update': legacy_count > 0
        }), 200

    @app.route('/api/public_workspace_documents', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_list_public_workspace_documents():
        """
        Endpoint specifically for chat functionality to load public workspace documents
        Returns documents from ALL visible public workspaces for the chat interface
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        # Get user settings to access publicDirectorySettings
        settings = get_user_settings(user_id)
        public_directory_settings = settings.get('settings', {}).get('publicDirectorySettings', {})
        
        # Get IDs of workspaces marked as visible (value is true)
        workspace_ids = [ws_id for ws_id, is_visible in public_directory_settings.items() if is_visible]
        
        if not workspace_ids:
            return jsonify({
                'documents': [],
                'workspace_name': 'All Public Workspaces',
                'error': 'No visible public workspaces found'
            }), 200

        # Get page_size parameter for pagination
        try:
            page_size = int(request.args.get('page_size', 1000))
        except:
            page_size = 1000
        if page_size < 1:
            page_size = 1000

        # Query documents from all visible public workspaces
        workspace_conditions = " OR ".join([f"c.public_workspace_id = @ws_{i}" for i in range(len(workspace_ids))])
        query = f'SELECT * FROM c WHERE {workspace_conditions} ORDER BY c._ts DESC'
        params = [{'name': f'@ws_{i}', 'value': workspace_id} for i, workspace_id in enumerate(workspace_ids)]
        
        docs = list(cosmos_public_documents_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        ))

        # Limit results to page_size
        docs = docs[:page_size]

        return jsonify({
            'documents': docs,
            'workspace_name': 'All Public Workspaces'
        }), 200

    @app.route('/api/public_documents/<doc_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_get_public_document(doc_id):
        user_id = get_current_user_id()
        settings = get_user_settings(user_id)
        active_ws = settings['settings'].get('activePublicWorkspaceOid')
        if not active_ws:
            return jsonify({'error': 'No active public workspace selected'}), 400
        ws_doc = find_public_workspace_by_id(active_ws)
        if not ws_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404
        from functions_public_workspaces import get_user_role_in_public_workspace
        if not get_user_role_in_public_workspace(ws_doc, user_id):
            return jsonify({'error':'Access denied'}), 403
        return get_document(user_id=user_id, document_id=doc_id, public_workspace_id=active_ws)

    @app.route('/api/public_documents/<doc_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_patch_public_document(doc_id):
        user_id = get_current_user_id()
        settings = get_user_settings(user_id)
        active_ws = settings['settings'].get('activePublicWorkspaceOid')
        ws_doc = find_public_workspace_by_id(active_ws) if active_ws else None
        from functions_public_workspaces import get_user_role_in_public_workspace
        role = get_user_role_in_public_workspace(ws_doc, user_id) if ws_doc else None
        if role not in ['Owner','Admin','DocumentManager']:
            return jsonify({'error':'Access denied'}), 403
        data = request.get_json() or {}
        
        # Track which fields were updated
        updated_fields = {}
        
        try:
            if 'title' in data:
                update_document(document_id=doc_id, public_workspace_id=active_ws, user_id=user_id, title=data['title'])
                updated_fields['title'] = data['title']
            if 'abstract' in data:
                update_document(document_id=doc_id, public_workspace_id=active_ws, user_id=user_id, abstract=data['abstract'])
                updated_fields['abstract'] = data['abstract']
            if 'keywords' in data:
                kws = data['keywords'] if isinstance(data['keywords'],list) else [k.strip() for k in data['keywords'].split(',')]
                update_document(document_id=doc_id, public_workspace_id=active_ws, user_id=user_id, keywords=kws)
                updated_fields['keywords'] = kws
            if 'authors' in data:
                auths = data['authors'] if isinstance(data['authors'],list) else [data['authors']]
                update_document(document_id=doc_id, public_workspace_id=active_ws, user_id=user_id, authors=auths)
                updated_fields['authors'] = auths
            if 'publication_date' in data:
                update_document(document_id=doc_id, public_workspace_id=active_ws, user_id=user_id, publication_date=data['publication_date'])
                updated_fields['publication_date'] = data['publication_date']
            if 'document_classification' in data:
                update_document(document_id=doc_id, public_workspace_id=active_ws, user_id=user_id, document_classification=data['document_classification'])
                updated_fields['document_classification'] = data['document_classification']
            if 'tags' in data:
                from functions_documents import validate_tags, get_or_create_tag_definition
                tags_input = data['tags'] if isinstance(data['tags'], list) else []
                is_valid, error_msg, normalized_tags = validate_tags(tags_input)
                if not is_valid:
                    return jsonify({'error': error_msg}), 400
                for tag in normalized_tags:
                    get_or_create_tag_definition(user_id, tag, workspace_type='public', public_workspace_id=active_ws)
                update_document(document_id=doc_id, public_workspace_id=active_ws, user_id=user_id, tags=normalized_tags)
                updated_fields['tags'] = normalized_tags

            # Log the metadata update transaction if any fields were updated
            if updated_fields:
                from functions_documents import get_document
                from functions_activity_logging import log_document_metadata_update_transaction
                doc = get_document(user_id, doc_id, public_workspace_id=active_ws)
                if doc:
                    log_document_metadata_update_transaction(
                        user_id=user_id,
                        document_id=doc_id,
                        workspace_type='public',
                        file_name=doc.get('file_name', 'Unknown'),
                        updated_fields=updated_fields,
                        file_type=doc.get('file_type'),
                        public_workspace_id=active_ws
                    )
            
            return jsonify({'message':'Metadata updated'}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/public_documents/<doc_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_delete_public_document(doc_id):
        user_id = get_current_user_id()
        settings = get_user_settings(user_id)
        active_ws = settings['settings'].get('activePublicWorkspaceOid')
        ws_doc = find_public_workspace_by_id(active_ws) if active_ws else None
        
        # Check if workspace status allows deletions
        if ws_doc:
            from functions_public_workspaces import check_public_workspace_status_allows_operation
            allowed, reason = check_public_workspace_status_allows_operation(ws_doc, 'delete')
            if not allowed:
                return jsonify({'error': reason}), 403
        
        from functions_public_workspaces import get_user_role_in_public_workspace
        role = get_user_role_in_public_workspace(ws_doc, user_id) if ws_doc else None
        if role not in ['Owner','Admin','DocumentManager']:
            return jsonify({'error':'Access denied'}), 403
        try:
            delete_document(user_id=user_id, document_id=doc_id, public_workspace_id=active_ws)
            delete_document_chunks(document_id=doc_id, public_workspace_id=active_ws)
            
            # Invalidate public workspace search cache since document was deleted
            invalidate_public_workspace_search_cache(active_ws)
            
            return jsonify({'message':'Deleted'}), 200
        except Exception as e:
            return jsonify({'error':str(e)}), 500

    @app.route('/api/public_documents/<doc_id>/extract_metadata', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_extract_metadata_public_document(doc_id):
        user_id = get_current_user_id()
        settings = get_settings()
        if not settings.get('enable_extract_meta_data'):
            return jsonify({'error':'Not enabled'}), 403
        user_cfg = get_user_settings(user_id)
        active_ws = user_cfg['settings'].get('activePublicWorkspaceOid')
        ws_doc = find_public_workspace_by_id(active_ws) if active_ws else None
        from functions_public_workspaces import get_user_role_in_public_workspace
        role = get_user_role_in_public_workspace(ws_doc, user_id) if ws_doc else None
        if role not in ['Owner','Admin','DocumentManager']:
            return jsonify({'error':'Access denied'}), 403
        executor = current_app.extensions['executor']
        executor.submit(process_metadata_extraction_background, document_id=doc_id, user_id=user_id, public_workspace_id=active_ws)
        return jsonify({'message':'Extraction queued'}), 200

    @app.route('/api/public_documents/upgrade_legacy', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_upgrade_legacy_public_documents():
        user_id = get_current_user_id()
        user_cfg = get_user_settings(user_id)
        active_ws = user_cfg['settings'].get('activePublicWorkspaceOid')
        ws_doc = find_public_workspace_by_id(active_ws) if active_ws else None
        from functions_public_workspaces import get_user_role_in_public_workspace
        role = get_user_role_in_public_workspace(ws_doc, user_id) if ws_doc else None
        if role not in ['Owner','Admin','DocumentManager']:
            return jsonify({'error':'Access denied'}), 403
        try:
            count = upgrade_legacy_documents(user_id=user_id, public_workspace_id=active_ws)
            return jsonify({'message':f'Upgraded {count} docs'}), 200
        except Exception as e:
            return jsonify({'error':str(e)}), 500

    @app.route('/api/public_workspace_documents/tags', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_get_public_workspace_document_tags():
        """
        Get all unique tags used across one or more public workspaces with document counts.
        Accepts optional `workspace_ids` query param (comma-separated).
        Falls back to all visible public workspaces from user settings if not provided.
        Permission: only workspaces the user has visibility to are included.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        ws_ids_param = request.args.get('workspace_ids', '')

        if ws_ids_param:
            workspace_ids = [wid.strip() for wid in ws_ids_param.split(',') if wid.strip()]
        else:
            workspace_ids = get_user_visible_public_workspace_ids_from_settings(user_id)

        visible_ids = set(get_user_visible_public_workspace_ids_from_settings(user_id))
        validated_ids = [wid for wid in workspace_ids if wid in visible_ids]

        from functions_documents import get_workspace_tags

        all_tags = {}
        for wid in validated_ids:
            tags = get_workspace_tags(user_id, public_workspace_id=wid)
            for tag in tags:
                if tag['name'] in all_tags:
                    all_tags[tag['name']]['count'] += tag['count']
                else:
                    all_tags[tag['name']] = dict(tag)

        merged = sorted(all_tags.values(), key=lambda t: t['name'])
        return jsonify({'tags': merged}), 200

    @app.route('/api/public_workspace_documents/tags', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_create_public_workspace_tag():
        """
        Create a new tag in the public workspace.

        Request body:
        {
            "tag_name": "new-tag",
            "color": "#3b82f6"  // optional
        }
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_cfg = get_user_settings(user_id)
        active_ws = user_cfg['settings'].get('activePublicWorkspaceOid')
        if not active_ws:
            return jsonify({'error': 'No active public workspace selected'}), 400

        ws_doc = find_public_workspace_by_id(active_ws)
        if not ws_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404

        from functions_public_workspaces import get_user_role_in_public_workspace
        role = get_user_role_in_public_workspace(ws_doc, user_id)
        if role not in ['Owner', 'Admin', 'DocumentManager']:
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

            tag_defs = ws_doc.get('tag_definitions', {})

            if normalized_tag in tag_defs:
                return jsonify({'error': 'Tag already exists'}), 409

            tag_defs[normalized_tag] = {
                'color': color,
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            ws_doc['tag_definitions'] = tag_defs
            cosmos_public_workspaces_container.upsert_item(ws_doc)

            return jsonify({
                'message': f'Tag "{normalized_tag}" created successfully',
                'tag': {
                    'name': normalized_tag,
                    'color': color
                }
            }), 201

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/public_workspace_documents/bulk-tag', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_bulk_tag_public_documents():
        """
        Apply tag operations to multiple public workspace documents.

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

        user_cfg = get_user_settings(user_id)
        active_ws = user_cfg['settings'].get('activePublicWorkspaceOid')
        if not active_ws:
            return jsonify({'error': 'No active public workspace selected'}), 400

        ws_doc = find_public_workspace_by_id(active_ws)
        if not ws_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404

        from functions_public_workspaces import get_user_role_in_public_workspace
        role = get_user_role_in_public_workspace(ws_doc, user_id)
        if role not in ['Owner', 'Admin', 'DocumentManager']:
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
            get_or_create_tag_definition(user_id, tag, workspace_type='public', public_workspace_id=active_ws)

        results = {
            'success': [],
            'errors': []
        }

        try:
            for doc_id in document_ids:
                try:
                    query = "SELECT TOP 1 * FROM c WHERE c.id = @document_id AND c.public_workspace_id = @ws_id ORDER BY c.version DESC"
                    parameters = [
                        {"name": "@document_id", "value": doc_id},
                        {"name": "@ws_id", "value": active_ws}
                    ]

                    document_results = list(
                        cosmos_public_documents_container.query_items(
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
                        public_workspace_id=active_ws,
                        user_id=user_id,
                        tags=new_tags
                    )

                    try:
                        propagate_tags_to_chunks(doc_id, new_tags, user_id, public_workspace_id=active_ws)
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
                invalidate_public_workspace_search_cache(active_ws)

            status_code = 200 if not results['errors'] else 207
            return jsonify(results), status_code

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/public_workspace_documents/tags/<tag_name>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_update_public_workspace_tag(tag_name):
        """
        Update a public workspace tag (rename or change color).

        Request body:
        {
            "new_name": "new-tag-name",  // optional
            "color": "#3b82f6"           // optional
        }
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_cfg = get_user_settings(user_id)
        active_ws = user_cfg['settings'].get('activePublicWorkspaceOid')
        if not active_ws:
            return jsonify({'error': 'No active public workspace selected'}), 400

        ws_doc = find_public_workspace_by_id(active_ws)
        if not ws_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404

        from functions_public_workspaces import get_user_role_in_public_workspace
        role = get_user_role_in_public_workspace(ws_doc, user_id)
        if role not in ['Owner', 'Admin', 'DocumentManager']:
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

                query = "SELECT * FROM c WHERE c.public_workspace_id = @ws_id"
                parameters = [{"name": "@ws_id", "value": active_ws}]
                documents = list(cosmos_public_documents_container.query_items(
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
                            public_workspace_id=active_ws,
                            user_id=user_id,
                            tags=new_tags
                        )

                        try:
                            propagate_tags_to_chunks(doc['id'], new_tags, user_id, public_workspace_id=active_ws)
                        except Exception:
                            pass

                        updated_count += 1

                tag_defs = ws_doc.get('tag_definitions', {})
                if normalized_old_tag in tag_defs:
                    old_def = tag_defs.pop(normalized_old_tag)
                    tag_defs[normalized_new_tag] = old_def
                ws_doc['tag_definitions'] = tag_defs
                cosmos_public_workspaces_container.upsert_item(ws_doc)

                invalidate_public_workspace_search_cache(active_ws)

                return jsonify({
                    'message': f'Tag renamed from "{normalized_old_tag}" to "{normalized_new_tag}"',
                    'documents_updated': updated_count
                }), 200

            if new_color:
                tag_defs = ws_doc.get('tag_definitions', {})

                if normalized_old_tag in tag_defs:
                    tag_defs[normalized_old_tag]['color'] = new_color
                else:
                    from datetime import datetime, timezone
                    tag_defs[normalized_old_tag] = {
                        'color': new_color,
                        'created_at': datetime.now(timezone.utc).isoformat()
                    }

                ws_doc['tag_definitions'] = tag_defs
                cosmos_public_workspaces_container.upsert_item(ws_doc)

                return jsonify({
                    'message': f'Tag color updated for "{normalized_old_tag}"'
                }), 200

            return jsonify({'error': 'No updates specified'}), 400

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/public_workspace_documents/tags/<tag_name>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_delete_public_workspace_tag(tag_name):
        """Delete a tag from all documents in the public workspace."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_cfg = get_user_settings(user_id)
        active_ws = user_cfg['settings'].get('activePublicWorkspaceOid')
        if not active_ws:
            return jsonify({'error': 'No active public workspace selected'}), 400

        ws_doc = find_public_workspace_by_id(active_ws)
        if not ws_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404

        from functions_public_workspaces import get_user_role_in_public_workspace
        role = get_user_role_in_public_workspace(ws_doc, user_id)
        if role not in ['Owner', 'Admin', 'DocumentManager']:
            return jsonify({'error': 'You do not have permission to manage tags'}), 403

        from functions_documents import normalize_tag, update_document, propagate_tags_to_chunks

        try:
            normalized_tag = normalize_tag(tag_name)

            query = "SELECT * FROM c WHERE c.public_workspace_id = @ws_id"
            parameters = [{"name": "@ws_id", "value": active_ws}]
            documents = list(cosmos_public_documents_container.query_items(
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
                        public_workspace_id=active_ws,
                        user_id=user_id,
                        tags=new_tags
                    )

                    try:
                        propagate_tags_to_chunks(doc['id'], new_tags, user_id, public_workspace_id=active_ws)
                    except Exception:
                        pass

                    updated_count += 1

            tag_defs = ws_doc.get('tag_definitions', {})
            if normalized_tag in tag_defs:
                tag_defs.pop(normalized_tag)
                ws_doc['tag_definitions'] = tag_defs
                cosmos_public_workspaces_container.upsert_item(ws_doc)

            if updated_count > 0:
                invalidate_public_workspace_search_cache(active_ws)

            return jsonify({
                'message': f'Tag "{normalized_tag}" deleted from {updated_count} document(s)'
            }), 200

        except Exception as e:
            return jsonify({'error': str(e)}), 500
