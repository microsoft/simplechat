# route_backend_public_documents.py

from config import *

from functions_authentication import *
from functions_settings import *
from functions_public_workspaces import *
from functions_documents import *
from flask import current_app

def register_route_backend_public_documents(app):
    """
    Provides backend routes for public-workspace–scoped document management
    """

    @app.route('/api/public_documents/upload', methods=['POST'])
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

        # check role
        from functions_public_workspaces import get_user_role_in_public_workspace
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
        return jsonify({
            'message': f'Processed {len(processed)} file(s)',
            'document_ids': [d['id'] for d in processed],
            'errors': errors
        }), status

    @app.route('/api/public_documents', methods=['GET'])
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
        # build WHERE
        conds = ['c.public_workspace_id = @ws']
        params = [{'name':'@ws','value':active_ws}]
        if search:
            conds.append('(CONTAINS(LOWER(c.file_name), LOWER(@search)) OR CONTAINS(LOWER(c.title), LOWER(@search)))')
            params.append({'name':'@search','value':search})
        where = ' AND '.join(conds)

        # count
        count_q = f'SELECT VALUE COUNT(1) FROM c WHERE {where}'
        total = list(cosmos_public_documents_container.query_items(
            query=count_q, parameters=params, enable_cross_partition_query=True
        ))
        total_count = total[0] if total else 0

        # data
        data_q = f'SELECT * FROM c WHERE {where} ORDER BY c._ts DESC OFFSET {offset} LIMIT {page_size}'
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
        try:
            if 'title' in data:
                update_document(document_id=doc_id, public_workspace_id=active_ws, user_id=user_id, title=data['title'])
            if 'abstract' in data:
                update_document(document_id=doc_id, public_workspace_id=active_ws, user_id=user_id, abstract=data['abstract'])
            if 'keywords' in data:
                kws = data['keywords'] if isinstance(data['keywords'],list) else [k.strip() for k in data['keywords'].split(',')]
                update_document(document_id=doc_id, public_workspace_id=active_ws, user_id=user_id, keywords=kws)
            if 'authors' in data:
                auths = data['authors'] if isinstance(data['authors'],list) else [data['authors']]
                update_document(document_id=doc_id, public_workspace_id=active_ws, user_id=user_id, authors=auths)
            if 'publication_date' in data:
                update_document(document_id=doc_id, public_workspace_id=active_ws, user_id=user_id, publication_date=data['publication_date'])
            if 'document_classification' in data:
                update_document(document_id=doc_id, public_workspace_id=active_ws, user_id=user_id, document_classification=data['document_classification'])
            return jsonify({'message':'Metadata updated'}), 200
        except Exception as e:
            return jsonify({'error':str(e)}), 500

    @app.route('/api/public_documents/<doc_id>', methods=['DELETE'])
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_delete_public_document(doc_id):
        user_id = get_current_user_id()
        settings = get_user_settings(user_id)
        active_ws = settings['settings'].get('activePublicWorkspaceOid')
        ws_doc = find_public_workspace_by_id(active_ws) if active_ws else None
        from functions_public_workspaces import get_user_role_in_public_workspace
        role = get_user_role_in_public_workspace(ws_doc, user_id) if ws_doc else None
        if role not in ['Owner','Admin','DocumentManager']:
            return jsonify({'error':'Access denied'}), 403
        try:
            delete_document(user_id=user_id, document_id=doc_id, public_workspace_id=active_ws)
            delete_document_chunks(document_id=doc_id, public_workspace_id=active_ws)
            return jsonify({'message':'Deleted'}), 200
        except Exception as e:
            return jsonify({'error':str(e)}), 500

    @app.route('/api/public_documents/<doc_id>/extract_metadata', methods=['POST'])
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
