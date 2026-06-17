# route_backend_public_documents.py

from datetime import datetime, timezone

from config import *

from functions_authentication import *
from functions_settings import *
from functions_public_workspaces import *
from functions_documents import *
from functions_file_sync import (
    FILE_SYNC_SCOPE_PUBLIC,
    apply_synced_document_delete_action,
    build_synced_document_delete_guard,
)
from functions_notifications import create_notification, delete_notifications_by_metadata
from functions_simplechat_operations import download_blob_content, queue_generated_document_processing
from utils_cache import invalidate_public_workspace_search_cache
from flask import current_app
from functions_debug import *
from swagger_wrapper import swagger_route, get_auth_security


PENDING_GENERATED_ARTIFACT_NOTIFICATION_TYPES = [
    'approval_request_pending',
    'approval_request_pending_submitter',
]


def _cleanup_public_generated_artifact_notifications(document_id, public_workspace_id):
    delete_notifications_by_metadata(
        metadata_filters={
            'document_id': document_id,
            'public_workspace_id': public_workspace_id,
            'request_type': 'generated_artifact_promotion',
        },
        notification_types=PENDING_GENERATED_ARTIFACT_NOTIFICATION_TYPES,
    )


def _get_generated_artifact_actor_name(user_info, fallback_user_id):
    return (
        str((user_info or {}).get('displayName') or '').strip()
        or str((user_info or {}).get('email') or '').strip()
        or fallback_user_id
    )


PUBLIC_WORKSPACE_READER_ROLES = ('Owner', 'Admin', 'DocumentManager', 'User')
PUBLIC_WORKSPACE_MANAGER_ROLES = ('Owner', 'Admin', 'DocumentManager')


def _require_active_public_workspace_response(user_id, allowed_roles=PUBLIC_WORKSPACE_MANAGER_ROLES):
    try:
        active_ws, ws_doc, role = require_active_public_workspace(
            user_id,
            allowed_roles=allowed_roles,
        )
    except ValueError:
        return None, None, None, (jsonify({'error': 'No active public workspace selected'}), 400)
    except LookupError:
        return None, None, None, (jsonify({'error': 'Active public workspace not found'}), 404)
    except PermissionError:
        return None, None, None, (jsonify({'error': 'Access denied'}), 403)

    return active_ws, ws_doc, role, None

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

        active_ws, ws_doc, _role, error_response = _require_active_public_workspace_response(
            user_id,
            PUBLIC_WORKSPACE_MANAGER_ROLES,
        )
        if error_response:
            return error_response

        allowed, reason = check_public_workspace_status_allows_operation(ws_doc, 'upload')
        if not allowed:
            return jsonify({'error': reason}), 403

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

        active_ws, ws_doc, _role, error_response = _require_active_public_workspace_response(
            user_id,
            PUBLIC_WORKSPACE_READER_ROLES,
        )
        if error_response:
            return error_response

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
            from functions_documents import sanitize_tags_for_filter
            tags_list = sanitize_tags_for_filter(tags_filter)
            if tags_list:
                for idx, tag in enumerate(tags_list):
                    param_name = f"@tag_{param_count}_{idx}"
                    conds.append(f"ARRAY_CONTAINS(c.tags, {param_name})")
                    params.append({'name': param_name, 'value': tag})
                param_count += len(tags_list)

        where = ' AND '.join(conds)

        data_q = f'SELECT * FROM c WHERE {where}'
        matching_docs = list(cosmos_public_documents_container.query_items(
            query=data_q, parameters=params, enable_cross_partition_query=True
        ))
        current_docs = sort_documents(
            select_current_documents(matching_docs),
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total_count = len(current_docs)
        docs = current_docs[offset:offset + page_size]

        # legacy
        legacy_q = 'SELECT VALUE COUNT(1) FROM c WHERE c.public_workspace_id = @ws AND NOT IS_DEFINED(c.percentage_complete)'
        legacy = list(cosmos_public_documents_container.query_items(
            query=legacy_q,
            parameters=[{'name':'@ws','value':active_ws}],
            enable_cross_partition_query=True
        ))
        legacy_count = legacy[0] if legacy else 0

        file_downloads_enabled = is_public_workspace_file_download_enabled(get_settings(), ws_doc)
        return jsonify({
            'documents': docs,
            'page': page,
            'page_size': page_size,
            'total_count': total_count,
            'file_downloads_enabled': file_downloads_enabled,
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

        docs = sort_documents(select_current_documents(docs))[:page_size]

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
        active_ws, _ws_doc, _role, error_response = _require_active_public_workspace_response(
            user_id,
            PUBLIC_WORKSPACE_READER_ROLES,
        )
        if error_response:
            return error_response
        return get_document(user_id=user_id, document_id=doc_id, public_workspace_id=active_ws)

    @app.route('/api/public_workspace_documents/<document_id>/versions', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_get_public_workspace_document_versions(document_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        workspace_id = str(request.args.get('workspace_id') or '').strip()
        if not workspace_id:
            return jsonify({'error': 'workspace_id is required'}), 400

        ws_doc = find_public_workspace_by_id(workspace_id)
        if not ws_doc:
            return jsonify({'error': 'Public workspace not found'}), 404

        from functions_public_workspaces import get_user_role_in_public_workspace
        if not get_user_role_in_public_workspace(ws_doc, user_id):
            return jsonify({'error': 'Access denied'}), 403

        versions = get_document_versions(
            user_id=user_id,
            document_id=document_id,
            public_workspace_id=workspace_id,
        )
        if not versions:
            return jsonify({'error': 'Document versions not found'}), 404

        return jsonify({
            'document_id': document_id,
            'public_workspace_id': workspace_id,
            'revision_family_id': versions[0].get('revision_family_id'),
            'versions': versions,
        }), 200

    def _authorize_public_document_download(user_id, document_id):
        try:
            active_ws, ws_doc, _ = require_active_public_workspace(
                user_id,
                allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
            )
        except ValueError:
            return None, None, (jsonify({'error': 'No active public workspace selected'}), 400)
        except LookupError:
            return None, None, (jsonify({'error': 'Active public workspace not found'}), 404)
        except PermissionError:
            return None, None, (jsonify({'error': 'Access denied'}), 403)

        if not is_public_workspace_file_download_enabled(get_settings(), ws_doc):
            return None, None, (jsonify({'error': 'File downloads are disabled for this public workspace'}), 403)

        document_record = get_document_record(
            user_id=user_id,
            document_id=document_id,
            public_workspace_id=active_ws,
        )
        if not document_record:
            return None, None, (jsonify({'error': 'Document not found or access denied'}), 404)
        return active_ws, document_record, None

    @app.route('/api/public_documents/<doc_id>/download', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_download_public_document(doc_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        active_ws, document_record, error_response = _authorize_public_document_download(user_id, doc_id)
        if error_response:
            return error_response

        try:
            return build_document_download_response(document_record, user_id=user_id, public_workspace_id=active_ws)
        except FileNotFoundError as exc:
            return jsonify({'error': str(exc)}), 404
        except Exception as exc:
            log_event(
                '[DocumentDownload] Failed public document download',
                {'document_id': doc_id, 'public_workspace_id': active_ws, 'error': str(exc)},
                debug_only=True,
            )
            return jsonify({'error': 'Unable to download document'}), 500

    @app.route('/api/public_documents/download', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_download_public_documents():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json(silent=True) or {}
        document_ids = data.get('document_ids') or []
        if not isinstance(document_ids, list):
            return jsonify({'error': 'document_ids must be a list'}), 400

        active_ws = None
        documents = []
        seen_ids = set()
        for document_id_value in document_ids:
            normalized_document_id = str(document_id_value or '').strip()
            if not normalized_document_id or normalized_document_id in seen_ids:
                continue
            seen_ids.add(normalized_document_id)
            authorized_ws, document_record, error_response = _authorize_public_document_download(
                user_id,
                normalized_document_id,
            )
            if error_response:
                return error_response
            if active_ws is None:
                active_ws = authorized_ws
            documents.append(document_record)

        if not documents:
            return jsonify({'error': 'No documents selected'}), 400
        if len(documents) == 1:
            try:
                return build_document_download_response(documents[0], user_id=user_id, public_workspace_id=active_ws)
            except FileNotFoundError as exc:
                return jsonify({'error': str(exc)}), 404

        try:
            return build_documents_zip_download_response(
                documents,
                'public_workspace_documents.zip',
                user_id=user_id,
                public_workspace_id=active_ws,
            )
        except FileNotFoundError as exc:
            return jsonify({'error': str(exc)}), 404
        except Exception as exc:
            log_event(
                '[DocumentDownload] Failed public document ZIP download',
                {'public_workspace_id': active_ws, 'document_count': len(documents), 'error': str(exc)},
                debug_only=True,
            )
            return jsonify({'error': 'Unable to download selected documents'}), 500

    @app.route('/api/public_documents/<doc_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_patch_public_document(doc_id):
        user_id = get_current_user_id()
        active_ws, _ws_doc, _role, error_response = _require_active_public_workspace_response(
            user_id,
            PUBLIC_WORKSPACE_MANAGER_ROLES,
        )
        if error_response:
            return error_response
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
        active_ws, ws_doc, _role, error_response = _require_active_public_workspace_response(
            user_id,
            PUBLIC_WORKSPACE_MANAGER_ROLES,
        )
        if error_response:
            return error_response
        
        # Check if workspace status allows deletions
        allowed, reason = check_public_workspace_status_allows_operation(ws_doc, 'delete')
        if not allowed:
            return jsonify({'error': reason}), 403

        delete_mode = request.args.get('delete_mode', 'all_versions')
        if delete_mode not in {'all_versions', 'current_only'}:
            return jsonify({'error': 'Invalid delete mode'}), 400
        file_sync_delete_action = request.args.get('file_sync_delete_action')
        file_sync_guard = build_synced_document_delete_guard(
            FILE_SYNC_SCOPE_PUBLIC,
            doc_id,
            user_id,
            public_workspace_id=active_ws,
            requested_action=file_sync_delete_action,
        )
        if file_sync_guard:
            return jsonify(file_sync_guard), 409
        try:
            apply_synced_document_delete_action(
                FILE_SYNC_SCOPE_PUBLIC,
                doc_id,
                user_id,
                file_sync_delete_action,
                public_workspace_id=active_ws,
            )
            delete_result = delete_document_revision(
                user_id=user_id,
                document_id=doc_id,
                delete_mode=delete_mode,
                public_workspace_id=active_ws,
            )
            
            # Invalidate public workspace search cache since document was deleted
            invalidate_public_workspace_search_cache(active_ws)
            
            return jsonify({'message':'Deleted', **delete_result}), 200
        except Exception as e:
            return jsonify({'error':str(e)}), 500

    @app.route('/api/public_documents/<doc_id>/approve-generated-artifact', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_approve_public_generated_artifact(doc_id):
        """Approve a generated chat artifact promotion into the active public workspace."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            active_ws, ws_doc, _ = require_active_public_workspace(user_id)

            allowed, reason = check_public_workspace_status_allows_operation(ws_doc, 'upload')
            if not allowed:
                return jsonify({'error': reason}), 403

            document_item = get_document_metadata(
                document_id=doc_id,
                user_id=user_id,
                public_workspace_id=active_ws,
            )
            if not document_item:
                return jsonify({'error': 'Document not found or access denied'}), 404

            promotion_status = str(document_item.get('generated_artifact_promotion_status') or '').strip().lower()
            if promotion_status != 'pending_approval':
                return jsonify({'error': 'Document is not awaiting generated artifact approval'}), 400

            owner_user_id = str(document_item.get('user_id') or '').strip()
            source_blob_container = str(document_item.get('generated_artifact_source_blob_container') or '').strip()
            source_blob_path = str(document_item.get('generated_artifact_source_blob_path') or '').strip()
            if not owner_user_id or not source_blob_container or not source_blob_path:
                return jsonify({'error': 'Generated artifact source is incomplete'}), 400

            artifact_bytes = download_blob_content(source_blob_container, source_blob_path)
            approver_info = get_current_user_info() or {}
            approver_name = (
                str(approver_info.get('displayName') or '').strip()
                or str(approver_info.get('email') or '').strip()
                or user_id
            )

            try:
                update_document(
                    document_id=doc_id,
                    user_id=owner_user_id,
                    public_workspace_id=active_ws,
                    status='Queued for processing',
                    percentage_complete=0,
                    generated_artifact_promotion_status='approved',
                    generated_artifact_approved_at=datetime.now(timezone.utc).isoformat(),
                    generated_artifact_approved_by_user_id=user_id,
                    generated_artifact_approved_by_display_name=approver_name,
                )
                queue_generated_document_processing(
                    document_id=doc_id,
                    owner_user_id=owner_user_id,
                    normalized_file_name=str(document_item.get('file_name') or 'generated-artifact.json').strip() or 'generated-artifact.json',
                    file_content_bytes=artifact_bytes,
                    public_workspace_id=active_ws,
                )
            except Exception as exc:
                update_document(
                    document_id=doc_id,
                    user_id=owner_user_id,
                    public_workspace_id=active_ws,
                    status=f'Approval failed: {str(exc)}',
                    generated_artifact_promotion_status='approval_failed',
                )
                raise

            _cleanup_public_generated_artifact_notifications(doc_id, active_ws)
            invalidate_public_workspace_search_cache(active_ws)

            workspace_name = str(ws_doc.get('name') or 'this public workspace').strip() or 'this public workspace'
            create_notification(
                user_id=owner_user_id,
                notification_type='approval_request_approved',
                title='Generated artifact approved',
                message=f"{str(document_item.get('file_name') or 'Your generated artifact').strip()} was approved for {workspace_name} and is now processing.",
                link_url='/public_workspaces',
                link_context={
                    'workspace_type': 'public',
                    'public_workspace_id': active_ws,
                    'document_id': doc_id,
                },
                metadata={
                    'document_id': doc_id,
                    'public_workspace_id': active_ws,
                    'request_type': 'generated_artifact_promotion',
                },
            )

            return jsonify({
                'message': 'Generated artifact approved and queued for processing',
                'document_id': doc_id,
            }), 200
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as e:
            return jsonify({'error': f'Error approving generated artifact: {str(e)}'}), 500

    @app.route('/api/public_documents/<doc_id>/deny-generated-artifact', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_deny_public_generated_artifact(doc_id):
        """Deny a pending generated chat artifact promotion in the active public workspace."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            active_ws, ws_doc, role = require_active_public_workspace(user_id)
            if role not in ['Owner', 'Admin', 'DocumentManager']:
                return jsonify({'error': 'Access denied'}), 403

            document_item = get_document_metadata(
                document_id=doc_id,
                user_id=user_id,
                public_workspace_id=active_ws,
            )
            if not document_item:
                return jsonify({'error': 'Document not found or access denied'}), 404

            promotion_status = str(document_item.get('generated_artifact_promotion_status') or '').strip().lower()
            if promotion_status != 'pending_approval':
                return jsonify({'error': 'Document is not awaiting generated artifact approval'}), 400

            requester_user_id = (
                str(document_item.get('generated_artifact_requested_by_user_id') or '').strip()
                or str(document_item.get('user_id') or '').strip()
            )
            document_name = str(document_item.get('file_name') or 'This generated artifact').strip() or 'This generated artifact'
            workspace_name = str(ws_doc.get('name') or 'this public workspace').strip() or 'this public workspace'
            denier_name = _get_generated_artifact_actor_name(get_current_user_info(), user_id)

            delete_document_revision(
                user_id=user_id,
                document_id=doc_id,
                delete_mode='all_versions',
                public_workspace_id=active_ws,
            )
            _cleanup_public_generated_artifact_notifications(doc_id, active_ws)
            invalidate_public_workspace_search_cache(active_ws)

            if requester_user_id:
                create_notification(
                    user_id=requester_user_id,
                    notification_type='approval_request_denied',
                    title='Generated artifact denied',
                    message=f"{document_name} was denied for {workspace_name} by {denier_name}.",
                    link_url='/public_workspaces',
                    link_context={
                        'workspace_type': 'public',
                        'public_workspace_id': active_ws,
                    },
                    metadata={
                        'document_id': doc_id,
                        'public_workspace_id': active_ws,
                        'request_type': 'generated_artifact_promotion',
                    },
                )

            return jsonify({'message': 'Generated artifact request denied and removed from the public workspace.'}), 200
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as e:
            return jsonify({'error': f'Error denying generated artifact: {str(e)}'}), 500

    @app.route('/api/public_documents/<doc_id>/cancel-generated-artifact', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_cancel_public_generated_artifact(doc_id):
        """Cancel a pending generated chat artifact promotion requested by the current user."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            active_ws, _, _ = require_active_public_workspace(user_id)

            document_item = get_document_metadata(
                document_id=doc_id,
                user_id=user_id,
                public_workspace_id=active_ws,
            )
            if not document_item:
                return jsonify({'error': 'Document not found or access denied'}), 404

            promotion_status = str(document_item.get('generated_artifact_promotion_status') or '').strip().lower()
            if promotion_status != 'pending_approval':
                return jsonify({'error': 'Document is not awaiting generated artifact approval'}), 400

            requester_user_id = (
                str(document_item.get('generated_artifact_requested_by_user_id') or '').strip()
                or str(document_item.get('user_id') or '').strip()
            )
            if requester_user_id != user_id:
                return jsonify({'error': 'Only the requester can cancel this generated artifact request'}), 403

            delete_document_revision(
                user_id=user_id,
                document_id=doc_id,
                delete_mode='all_versions',
                public_workspace_id=active_ws,
            )
            _cleanup_public_generated_artifact_notifications(doc_id, active_ws)
            invalidate_public_workspace_search_cache(active_ws)

            return jsonify({'message': 'Generated artifact request canceled.'}), 200
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as e:
            return jsonify({'error': f'Error canceling generated artifact: {str(e)}'}), 500

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
        active_ws, _ws_doc, _role, error_response = _require_active_public_workspace_response(
            user_id,
            PUBLIC_WORKSPACE_MANAGER_ROLES,
        )
        if error_response:
            return error_response
        executor = current_app.extensions['executor']
        executor.submit(process_metadata_extraction_background, document_id=doc_id, user_id=user_id, public_workspace_id=active_ws)
        return jsonify({'message':'Extraction queued'}), 200

    @app.route('/api/public_documents/reprocess_extraction', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_reprocess_public_document_extraction():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            active_ws, ws_doc, _ = require_active_public_workspace(
                user_id,
                allowed_roles=('Owner', 'Admin', 'DocumentManager'),
            )
        except ValueError:
            return jsonify({'error': 'No active public workspace selected'}), 400
        except LookupError:
            return jsonify({'error': 'Active public workspace not found'}), 404
        except PermissionError:
            return jsonify({'error': 'Access denied'}), 403

        allowed, reason = check_public_workspace_status_allows_operation(ws_doc, 'delete')
        if not allowed:
            return jsonify({'error': reason}), 403

        payload = request.get_json(silent=True) or {}
        raw_mode = str(payload.get('extraction_mode') or payload.get('target_extraction_mode') or '').strip().lower()
        if raw_mode not in DOCUMENT_INTELLIGENCE_MANUAL_EXTRACTION_MODES:
            return jsonify({'error': 'Extraction mode must be Standard or Enhanced.'}), 400
        target_mode = normalize_document_intelligence_manual_extraction_mode(raw_mode)

        document_ids = payload.get('document_ids')
        if not isinstance(document_ids, list):
            doc_id = payload.get('document_id')
            document_ids = [doc_id] if doc_id else []
        document_ids = [str(document_id).strip() for document_id in document_ids if str(document_id or '').strip()]
        if not document_ids:
            return jsonify({'error': 'At least one document ID is required.'}), 400

        queued = []
        errors = []
        for document_id in document_ids:
            try:
                document_item = get_document_metadata(
                    document_id=document_id,
                    user_id=user_id,
                    public_workspace_id=active_ws,
                )
                if not document_item:
                    errors.append({'document_id': document_id, 'error': 'Document not found.'})
                    continue
                if document_item.get('public_workspace_id') != active_ws:
                    errors.append({'document_id': document_id, 'error': 'Only documents in the active public workspace can have extraction changed.'})
                    continue

                is_valid, validation_message = validate_document_reprocess_source(
                    document_item,
                    user_id=user_id,
                    public_workspace_id=active_ws,
                )
                if not is_valid:
                    errors.append({'document_id': document_id, 'error': validation_message})
                    continue

                current_app.extensions['executor'].submit_stored(
                    f"{document_id}_public_di_reprocess_{target_mode}",
                    process_document_reprocess_extraction_background,
                    document_id=document_id,
                    user_id=user_id,
                    target_extraction_mode=target_mode,
                    public_workspace_id=active_ws,
                )
                queued.append({'document_id': document_id, 'extraction_mode': target_mode})
            except Exception as e:
                errors.append({'document_id': document_id, 'error': str(e)})

        if queued:
            invalidate_public_workspace_search_cache(active_ws)

        status_code = 202 if queued and not errors else (207 if queued else 400)
        target_mode_label = "Enhanced" if target_mode == "layout" else "Standard"
        return jsonify({
            'message': f'Queued {len(queued)} document(s) to extract again with {target_mode_label}.',
            'queued': queued,
            'errors': errors,
        }), status_code

    @app.route('/api/public_documents/upgrade_legacy', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_upgrade_legacy_public_documents():
        user_id = get_current_user_id()
        active_ws, _ws_doc, _role, error_response = _require_active_public_workspace_response(
            user_id,
            PUBLIC_WORKSPACE_MANAGER_ROLES,
        )
        if error_response:
            return error_response
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

        active_ws, ws_doc, _role, error_response = _require_active_public_workspace_response(
            user_id,
            PUBLIC_WORKSPACE_MANAGER_ROLES,
        )
        if error_response:
            if error_response[1] == 403:
                return jsonify({'error': 'You do not have permission to manage tags'}), 403
            return error_response

        data = request.get_json()
        tag_name = data.get('tag_name')
        color = data.get('color')

        if not tag_name:
            return jsonify({'error': 'tag_name is required'}), 400

        from functions_documents import normalize_tag, validate_tag_color, validate_tags
        from datetime import datetime, timezone

        try:
            is_valid, error_msg, normalized_tags = validate_tags([tag_name])
            if not is_valid:
                return jsonify({'error': error_msg}), 400

            normalized_tag = normalized_tags[0]
            is_valid_color, color_error, normalized_color = validate_tag_color(color, normalized_tag)
            if not is_valid_color:
                return jsonify({'error': color_error}), 400

            tag_defs = ws_doc.get('tag_definitions', {})

            if normalized_tag in tag_defs:
                return jsonify({'error': 'Tag already exists'}), 409

            tag_defs[normalized_tag] = {
                'color': normalized_color,
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            ws_doc['tag_definitions'] = tag_defs
            cosmos_public_workspaces_container.upsert_item(ws_doc)

            return jsonify({
                'message': f'Tag "{normalized_tag}" created successfully',
                'tag': {
                    'name': normalized_tag,
                    'color': normalized_color
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

        active_ws, _ws_doc, _role, error_response = _require_active_public_workspace_response(
            user_id,
            PUBLIC_WORKSPACE_MANAGER_ROLES,
        )
        if error_response:
            if error_response[1] == 403:
                return jsonify({'error': 'You do not have permission to manage tags'}), 403
            return error_response

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

        active_ws, ws_doc, _role, error_response = _require_active_public_workspace_response(
            user_id,
            PUBLIC_WORKSPACE_MANAGER_ROLES,
        )
        if error_response:
            if error_response[1] == 403:
                return jsonify({'error': 'You do not have permission to manage tags'}), 403
            return error_response

        data = request.get_json()
        new_name = data.get('new_name')
        new_color = data.get('color')

        from functions_documents import normalize_tag, validate_tag_color, validate_tags, update_document, propagate_tags_to_chunks

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
                is_valid_color, color_error, normalized_color = validate_tag_color(new_color, normalized_old_tag)
                if not is_valid_color:
                    return jsonify({'error': color_error}), 400

                tag_defs = ws_doc.get('tag_definitions', {})

                if normalized_old_tag in tag_defs:
                    tag_defs[normalized_old_tag]['color'] = normalized_color
                else:
                    from datetime import datetime, timezone
                    tag_defs[normalized_old_tag] = {
                        'color': normalized_color,
                        'created_at': datetime.now(timezone.utc).isoformat()
                    }

                ws_doc['tag_definitions'] = tag_defs
                cosmos_public_workspaces_container.upsert_item(ws_doc)

                return jsonify({
                    'message': f'Tag color updated for "{normalized_old_tag}"',
                    'tag': {
                        'name': normalized_old_tag,
                        'color': normalized_color
                    }
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

        active_ws, ws_doc, _role, error_response = _require_active_public_workspace_response(
            user_id,
            PUBLIC_WORKSPACE_MANAGER_ROLES,
        )
        if error_response:
            if error_response[1] == 403:
                return jsonify({'error': 'You do not have permission to manage tags'}), 403
            return error_response

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
