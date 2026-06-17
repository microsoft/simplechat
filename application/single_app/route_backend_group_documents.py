# route_backend_group_documents.py:

from datetime import datetime, timezone

from config import *
from functions_authentication import *
from functions_settings import *
from functions_group import *
from functions_documents import *
from functions_file_sync import (
    FILE_SYNC_SCOPE_GROUP,
    apply_synced_document_delete_action,
    build_synced_document_delete_guard,
)
from functions_notifications import create_notification, delete_notifications_by_metadata
from functions_simplechat_operations import download_blob_content, queue_generated_document_processing
from utils_cache import invalidate_group_search_cache
from functions_debug import *
from functions_activity_logging import log_document_upload
from flask import current_app
from swagger_wrapper import swagger_route, get_auth_security


PENDING_GENERATED_ARTIFACT_NOTIFICATION_TYPES = [
    'approval_request_pending',
    'approval_request_pending_submitter',
]
GROUP_DOCUMENT_SHARE_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
GROUP_DOCUMENT_DOWNLOAD_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
GROUP_DOCUMENT_SHARE_PENDING_NOTIFICATION_TYPES = ['group_document_share_pending']


def _cleanup_group_generated_artifact_notifications(document_id, group_id):
    delete_notifications_by_metadata(
        metadata_filters={
            'document_id': document_id,
            'group_id': group_id,
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


def _require_active_group_document_context(user_id, allowed_roles, permission_message='Access denied'):
    try:
        active_group_id = require_active_group(user_id, allowed_roles=allowed_roles)
    except ValueError:
        return None, None, None, (jsonify({'error': 'No active group selected'}), 400)
    except LookupError:
        return None, None, None, (jsonify({'error': 'Active group not found'}), 404)
    except PermissionError:
        return None, None, None, (jsonify({'error': permission_message}), 403)

    group_doc = find_group_by_id(active_group_id)
    if not group_doc:
        return None, None, None, (jsonify({'error': 'Active group not found'}), 404)

    return active_group_id, group_doc, get_user_role_in_group(group_doc, user_id), None


def _get_group_document_display_name(document_item):
    return str(
        (document_item or {}).get('title')
        or (document_item or {}).get('file_name')
        or 'Document'
    ).strip()


def _group_share_entry_matches(entry, group_id):
    normalized_entry = str(entry or '')
    return normalized_entry == group_id or normalized_entry.startswith(f"{group_id},")


def _get_group_share_status(entry):
    normalized_entry = str(entry or '')
    if ',' not in normalized_entry:
        return 'approved'
    return normalized_entry.split(',', 1)[1] or 'unknown'


def _find_group_share_entry(shared_group_ids, group_id):
    for entry in shared_group_ids or []:
        if _group_share_entry_matches(entry, group_id):
            return str(entry)
    return None


def _set_group_share_status(shared_group_ids, group_id, status):
    updated_entries = []
    found = False
    for entry in shared_group_ids or []:
        if _group_share_entry_matches(entry, group_id):
            if not found:
                updated_entries.append(f"{group_id},{status}")
                found = True
            continue
        updated_entries.append(entry)

    if not found:
        updated_entries.append(f"{group_id},{status}")

    return updated_entries


def _remove_group_share_entries(shared_group_ids, group_id):
    return [
        entry
        for entry in shared_group_ids or []
        if not _group_share_entry_matches(entry, group_id)
    ]


def _get_group_name(group_doc, fallback='Unknown Group'):
    return str((group_doc or {}).get('name') or fallback).strip()


def _get_group_share_reviewer_user_ids(group_doc):
    reviewer_ids = []

    owner_id = str((group_doc or {}).get('owner', {}).get('id') or '').strip()
    if owner_id:
        reviewer_ids.append(owner_id)

    for role_key in ('admins', 'documentManagers'):
        for user_id in (group_doc or {}).get(role_key, []) or []:
            normalized_user_id = str(user_id or '').strip()
            if normalized_user_id and normalized_user_id not in reviewer_ids:
                reviewer_ids.append(normalized_user_id)

    return reviewer_ids


def _get_group_share_details(document_item):
    details = document_item.get('document_share_details') if isinstance(document_item, dict) else None
    if not isinstance(details, dict):
        details = {}

    group_details = details.get('groups')
    if not isinstance(group_details, dict):
        group_details = {}

    details['groups'] = group_details
    return details, group_details


def _get_group_share_detail(document_item, target_group_id):
    _, group_details = _get_group_share_details(document_item)
    detail = group_details.get(target_group_id)
    return detail if isinstance(detail, dict) else {}


def _set_group_share_detail(document_item, target_group_id, updates):
    details, group_details = _get_group_share_details(document_item)
    existing_detail = group_details.get(target_group_id)
    if not isinstance(existing_detail, dict):
        existing_detail = {}

    existing_detail.update(updates)
    group_details[target_group_id] = existing_detail
    details['groups'] = group_details
    return details


def _clear_group_document_share_pending_notifications(document_id, target_group_id):
    delete_notifications_by_metadata(
        metadata_filters={
            'share_scope': 'group',
            'document_id': document_id,
            'target_group_id': target_group_id,
        },
        notification_types=GROUP_DOCUMENT_SHARE_PENDING_NOTIFICATION_TYPES,
    )


def _create_group_document_share_pending_notifications(
    document_item,
    source_group,
    target_group,
    shared_by_user_id,
):
    document_name = _get_group_document_display_name(document_item)
    source_group_id = (source_group or {}).get('id')
    target_group_id = (target_group or {}).get('id')
    source_group_name = _get_group_name(source_group, 'the owning group')
    target_group_name = _get_group_name(target_group, 'your group')
    created_notifications = []

    for reviewer_user_id in _get_group_share_reviewer_user_ids(target_group):
        notification = create_notification(
            user_id=reviewer_user_id,
            notification_type='group_document_share_pending',
            title='Group document share needs approval',
            message=(
                f'"{document_name}" was shared from {source_group_name} to '
                f'{target_group_name} and needs approval before it can be searched.'
            ),
            link_url='/group_workspaces',
            link_context={
                'workspace_type': 'group',
                'group_id': target_group_id,
                'document_id': document_item.get('id'),
            },
            metadata={
                'share_scope': 'group',
                'document_id': document_item.get('id'),
                'document_name': document_name,
                'source_group_id': source_group_id,
                'source_group_name': source_group_name,
                'target_group_id': target_group_id,
                'target_group_name': target_group_name,
                'shared_by_user_id': shared_by_user_id,
            },
        )
        if notification:
            created_notifications.append(notification)

    return created_notifications


def _create_group_document_share_decision_notification(
    document_item,
    target_group_id,
    decision,
    decided_by_user_id,
):
    share_detail = _get_group_share_detail(document_item, target_group_id)
    recipient_user_id = str(share_detail.get('shared_by_user_id') or '').strip()
    source_group = find_group_by_id(document_item.get('group_id'))
    target_group = find_group_by_id(target_group_id)

    if not recipient_user_id:
        recipient_user_id = str((source_group or {}).get('owner', {}).get('id') or '').strip()
    if not recipient_user_id:
        return None

    normalized_decision = 'approved' if decision == 'approved' else 'denied'
    document_name = _get_group_document_display_name(document_item)
    target_group_name = _get_group_name(target_group, 'the receiving group')

    return create_notification(
        user_id=recipient_user_id,
        notification_type=f'group_document_share_{normalized_decision}',
        title=f'Group document share {normalized_decision}',
        message=(
            f'{target_group_name} {normalized_decision} the shared document '
            f'"{document_name}".'
        ),
        link_url='/group_workspaces',
        link_context={
            'workspace_type': 'group',
            'group_id': document_item.get('group_id'),
            'document_id': document_item.get('id'),
        },
        metadata={
            'share_scope': 'group',
            'document_id': document_item.get('id'),
            'document_name': document_name,
            'source_group_id': document_item.get('group_id'),
            'target_group_id': target_group_id,
            'target_group_name': target_group_name,
            'decision': normalized_decision,
            'decided_by_user_id': decided_by_user_id,
        },
    )

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

        active_group_id, group_doc, _, error_response = _require_active_group_document_context(
            user_id,
            allowed_roles=("Owner", "Admin", "DocumentManager"),
            permission_message='You do not have permission to upload documents',
        )
        if error_response:
            return error_response

        # Check if group status allows uploads
        from functions_group import check_group_status_allows_operation
        allowed, reason = check_group_status_allows_operation(group_doc, 'upload')
        if not allowed:
            return jsonify({'error': reason}), 403

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
        validated_group_roles = {}

        if group_ids_param:
            # Multi-group mode: validate each group
            requested_ids = [gid.strip() for gid in group_ids_param.split(',') if gid.strip()]
            validated_group_ids = []
            for gid in requested_ids:
                try:
                    role = assert_group_role(
                        user_id,
                        gid,
                        allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
                    )
                except (LookupError, PermissionError):
                    continue
                validated_group_ids.append(gid)
                validated_group_roles[gid] = role

            if not validated_group_ids:
                return jsonify({
                    'documents': [],
                    'page': 1,
                    'page_size': 10,
                    'total_count': 0,
                    'file_downloads_enabled': False,
                    'file_download_enabled_group_ids': [],
                }), 200
        else:
            active_group_id, _, role, error_response = _require_active_group_document_context(
                user_id,
                allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
                permission_message='You are not a member of the active group',
            )
            if error_response:
                return error_response

            validated_group_ids = [active_group_id]
            validated_group_roles[active_group_id] = role

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
            group_condition = (
                "(c.group_id = @group_id_0 "
                "OR ARRAY_CONTAINS(c.shared_group_ids, @group_id_0) "
                "OR EXISTS(SELECT VALUE s FROM s IN c.shared_group_ids WHERE STARTSWITH(s, @group_id_0_prefix)))"
            )
            query_params = [
                {"name": "@group_id_0", "value": validated_group_ids[0]},
                {"name": "@group_id_0_prefix", "value": f"{validated_group_ids[0]},"},
            ]
        else:
            own_parts = []
            shared_parts = []
            query_params = []
            for i, gid in enumerate(validated_group_ids):
                param_name = f"@group_id_{i}"
                prefix_param_name = f"@group_id_{i}_prefix"
                own_parts.append(f"c.group_id = {param_name}")
                shared_parts.append(
                    f"ARRAY_CONTAINS(c.shared_group_ids, {param_name}) "
                    f"OR EXISTS(SELECT VALUE s FROM s IN c.shared_group_ids WHERE STARTSWITH(s, {prefix_param_name}))"
                )
                query_params.append({"name": param_name, "value": gid})
                query_params.append({"name": prefix_param_name, "value": f"{gid},"})
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
            from functions_documents import sanitize_tags_for_filter
            tags_list = sanitize_tags_for_filter(tags_filter)
            if tags_list:
                for idx, tag in enumerate(tags_list):
                    param_name = f"@tag_{param_count}_{idx}"
                    query_conditions.append(f"ARRAY_CONTAINS(c.tags, {param_name})")
                    query_params.append({"name": param_name, "value": tag})
                param_count += len(tags_list)

        where_clause = " AND ".join(query_conditions)

        # --- 3) Query matching documents, then collapse to current revisions before paginating ---
        try:
            offset = (page - 1) * page_size
            data_query_str = f"""
                SELECT *
                FROM c
                WHERE {where_clause}
            """
            matching_docs = list(cosmos_group_documents_container.query_items(
                query=data_query_str,
                parameters=query_params,
                enable_cross_partition_query=True
            ))
            current_docs = sort_documents(
                select_current_documents(matching_docs),
                sort_by=sort_by,
                sort_order=sort_order,
            )
            total_count = len(current_docs)
            docs = current_docs[offset:offset + page_size]

            group_name_cache = {}
            for doc in docs:
                owner_group_id = doc.get('group_id')
                doc['owner_group_id'] = owner_group_id
                if owner_group_id in validated_group_ids:
                    doc['shared_approval_status'] = 'owner'
                    continue

                matched_group_id = None
                matched_status = 'none'
                for group_id in validated_group_ids:
                    shared_entry = _find_group_share_entry(doc.get('shared_group_ids', []), group_id)
                    if shared_entry:
                        matched_group_id = group_id
                        matched_status = _get_group_share_status(shared_entry)
                        break

                doc['shared_group_active_id'] = matched_group_id
                doc['shared_approval_status'] = matched_status
                if owner_group_id:
                    if owner_group_id not in group_name_cache:
                        group_name_cache[owner_group_id] = _get_group_name(
                            find_group_by_id(owner_group_id),
                            'Unknown Group',
                        )
                    doc['owner_group_name'] = group_name_cache[owner_group_id]
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
        app_settings = get_settings()
        group_docs_for_policy = {
            group_id: find_group_by_id(group_id)
            for group_id in validated_group_ids
        }
        file_download_enabled_group_ids = [
            group_id for group_id, group_doc in group_docs_for_policy.items()
            if group_doc
            and validated_group_roles.get(group_id) in GROUP_DOCUMENT_DOWNLOAD_MANAGER_ROLES
            and is_group_workspace_file_download_enabled(app_settings, group_doc)
        ]
        return jsonify({
            "documents": docs,
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
            "file_downloads_enabled": len(file_download_enabled_group_ids) > 0,
            "file_download_enabled_group_ids": file_download_enabled_group_ids,
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

        try:
            active_group_id = require_active_group(
                user_id,
                allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
            )
        except ValueError:
            return jsonify({'error': 'No active group selected'}), 400
        except LookupError:
            return jsonify({'error': 'Active group not found'}), 404
        except PermissionError:
            return jsonify({'error': 'You are not a member of the active group'}), 403

        return get_document(user_id=user_id, document_id=document_id, group_id=active_group_id)

    @app.route('/api/group_documents/<document_id>/versions', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_get_group_document_versions(document_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        requested_group_id = str(request.args.get('group_id') or '').strip()
        if not requested_group_id:
            return jsonify({'error': 'group_id is required'}), 400

        try:
            assert_group_role(
                user_id,
                requested_group_id,
                allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
            )
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403

        versions = get_document_versions(
            user_id=user_id,
            document_id=document_id,
            group_id=requested_group_id,
        )
        if not versions:
            return jsonify({'error': 'Document versions not found'}), 404

        return jsonify({
            'document_id': document_id,
            'group_id': requested_group_id,
            'revision_family_id': versions[0].get('revision_family_id'),
            'versions': versions,
        }), 200

    def _authorize_group_document_download(user_id, document_id):
        try:
            active_group_id = require_active_group(
                user_id,
                allowed_roles=GROUP_DOCUMENT_DOWNLOAD_MANAGER_ROLES,
            )
        except ValueError:
            return None, None, (jsonify({'error': 'No active group selected'}), 400)
        except LookupError:
            return None, None, (jsonify({'error': 'Active group not found'}), 404)
        except PermissionError:
            return None, None, (jsonify({'error': 'You do not have permission to download files from this group workspace'}), 403)

        group_doc = find_group_by_id(active_group_id)
        if not group_doc:
            return None, None, (jsonify({'error': 'Active group not found'}), 404)
        if not is_group_workspace_file_download_enabled(get_settings(), group_doc):
            return None, None, (jsonify({'error': 'File downloads are disabled for this group workspace'}), 403)

        document_record = get_document_record(user_id=user_id, document_id=document_id, group_id=active_group_id)
        if not document_record:
            return None, None, (jsonify({'error': 'Document not found or access denied'}), 404)
        return active_group_id, document_record, None

    @app.route('/api/group_documents/<document_id>/download', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_download_group_document(document_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        active_group_id, document_record, error_response = _authorize_group_document_download(user_id, document_id)
        if error_response:
            return error_response

        try:
            return build_document_download_response(document_record, user_id=user_id, group_id=active_group_id)
        except FileNotFoundError as exc:
            return jsonify({'error': str(exc)}), 404
        except Exception as exc:
            log_event(
                '[DocumentDownload] Failed group document download',
                {'document_id': document_id, 'group_id': active_group_id, 'error': str(exc)},
                debug_only=True,
            )
            return jsonify({'error': 'Unable to download document'}), 500

    @app.route('/api/group_documents/download', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_download_group_documents():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json(silent=True) or {}
        document_ids = data.get('document_ids') or []
        if not isinstance(document_ids, list):
            return jsonify({'error': 'document_ids must be a list'}), 400

        active_group_id = None
        documents = []
        seen_ids = set()
        for document_id_value in document_ids:
            normalized_document_id = str(document_id_value or '').strip()
            if not normalized_document_id or normalized_document_id in seen_ids:
                continue
            seen_ids.add(normalized_document_id)
            authorized_group_id, document_record, error_response = _authorize_group_document_download(
                user_id,
                normalized_document_id,
            )
            if error_response:
                return error_response
            if active_group_id is None:
                active_group_id = authorized_group_id
            documents.append(document_record)

        if not documents:
            return jsonify({'error': 'No documents selected'}), 400
        if len(documents) == 1:
            try:
                return build_document_download_response(documents[0], user_id=user_id, group_id=active_group_id)
            except FileNotFoundError as exc:
                return jsonify({'error': str(exc)}), 404

        try:
            return build_documents_zip_download_response(
                documents,
                'group_documents.zip',
                user_id=user_id,
                group_id=active_group_id,
            )
        except FileNotFoundError as exc:
            return jsonify({'error': str(exc)}), 404
        except Exception as exc:
            log_event(
                '[DocumentDownload] Failed group document ZIP download',
                {'group_id': active_group_id, 'document_count': len(documents), 'error': str(exc)},
                debug_only=True,
            )
            return jsonify({'error': 'Unable to download selected documents'}), 500

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

        active_group_id, _, _, error_response = _require_active_group_document_context(
            user_id,
            allowed_roles=("Owner", "Admin", "DocumentManager"),
            permission_message='You do not have permission to update documents in this group',
        )
        if error_response:
            return error_response

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
                from functions_activity_logging import log_document_metadata_update_transaction
                doc_response = get_document(user_id, document_id, group_id=active_group_id)
                doc = None
                if isinstance(doc_response, tuple):
                    resp, status_code = doc_response
                    if status_code == 200 and hasattr(resp, 'get_json'):
                        doc = resp.get_json()
                elif hasattr(doc_response, 'get_json'):
                    doc = doc_response.get_json()
                else:
                    doc = doc_response

                if doc and isinstance(doc, dict):
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

        active_group_id, group_doc, _, error_response = _require_active_group_document_context(
            user_id,
            allowed_roles=("Owner", "Admin", "DocumentManager"),
            permission_message='You do not have permission to delete documents in this group',
        )
        if error_response:
            return error_response

        # Check if group status allows deletions
        from functions_group import check_group_status_allows_operation
        allowed, reason = check_group_status_allows_operation(group_doc, 'delete')
        if not allowed:
            return jsonify({'error': reason}), 403

        owned_document_matches = list(cosmos_group_documents_container.query_items(
            query=(
                'SELECT TOP 1 * FROM c '
                'WHERE c.id = @document_id AND c.group_id = @group_id '
                'ORDER BY c.version DESC'
            ),
            parameters=[
                {'name': '@document_id', 'value': document_id},
                {'name': '@group_id', 'value': active_group_id},
            ],
            enable_cross_partition_query=True,
        ))
        if not owned_document_matches:
            return jsonify({'error': 'Document not found or access denied'}), 404

        delete_mode = request.args.get('delete_mode', 'all_versions')
        if delete_mode not in {'all_versions', 'current_only'}:
            return jsonify({'error': 'Invalid delete mode'}), 400
        file_sync_delete_action = request.args.get('file_sync_delete_action')
        file_sync_guard = build_synced_document_delete_guard(
            FILE_SYNC_SCOPE_GROUP,
            document_id,
            user_id,
            group_id=active_group_id,
            requested_action=file_sync_delete_action,
        )
        if file_sync_guard:
            return jsonify(file_sync_guard), 409

        try:
            apply_synced_document_delete_action(
                FILE_SYNC_SCOPE_GROUP,
                document_id,
                user_id,
                file_sync_delete_action,
                group_id=active_group_id,
            )
            delete_result = delete_document_revision(
                user_id=user_id,
                document_id=document_id,
                delete_mode=delete_mode,
                group_id=active_group_id,
            )

            # Invalidate group search cache since document was deleted
            invalidate_group_search_cache(active_group_id)

            return jsonify({
                'message': 'Group document deleted successfully',
                **delete_result,
            }), 200
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

        active_group_id, _, _, error_response = _require_active_group_document_context(
            user_id,
            allowed_roles=("Owner", "Admin", "DocumentManager"),
            permission_message='You do not have permission to extract metadata for this group document',
        )
        if error_response:
            return error_response

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

    @app.route('/api/group_documents/reprocess_extraction', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_reprocess_group_document_extraction():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            active_group_id = require_active_group(
                user_id,
                allowed_roles=GROUP_DOCUMENT_SHARE_MANAGER_ROLES,
            )
        except ValueError:
            return jsonify({'error': 'No active group selected'}), 400
        except LookupError:
            return jsonify({'error': 'Active group not found'}), 404
        except PermissionError:
            return jsonify({'error': 'You do not have permission to change extraction for group documents'}), 403

        group_doc = find_group_by_id(active_group_id)
        if not group_doc:
            return jsonify({'error': 'Active group not found'}), 404

        allowed, reason = check_group_status_allows_operation(group_doc, 'delete')
        if not allowed:
            return jsonify({'error': reason}), 403

        payload = request.get_json(silent=True) or {}
        raw_mode = str(payload.get('extraction_mode') or payload.get('target_extraction_mode') or '').strip().lower()
        if raw_mode not in DOCUMENT_INTELLIGENCE_MANUAL_EXTRACTION_MODES:
            return jsonify({'error': 'Extraction mode must be Standard or Enhanced.'}), 400
        target_mode = normalize_document_intelligence_manual_extraction_mode(raw_mode)

        document_ids = payload.get('document_ids')
        if not isinstance(document_ids, list):
            document_id = payload.get('document_id')
            document_ids = [document_id] if document_id else []
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
                    group_id=active_group_id,
                )
                if not document_item:
                    errors.append({'document_id': document_id, 'error': 'Document not found.'})
                    continue
                if document_item.get('group_id') != active_group_id:
                    errors.append({'document_id': document_id, 'error': 'Only documents owned by the active group can have extraction changed.'})
                    continue

                is_valid, validation_message = validate_document_reprocess_source(
                    document_item,
                    user_id=user_id,
                    group_id=active_group_id,
                )
                if not is_valid:
                    errors.append({'document_id': document_id, 'error': validation_message})
                    continue

                current_app.extensions['executor'].submit_stored(
                    f"{document_id}_group_di_reprocess_{target_mode}",
                    process_document_reprocess_extraction_background,
                    document_id=document_id,
                    user_id=user_id,
                    target_extraction_mode=target_mode,
                    group_id=active_group_id,
                )
                queued.append({'document_id': document_id, 'extraction_mode': target_mode})
            except Exception as e:
                errors.append({'document_id': document_id, 'error': str(e)})

        if queued:
            invalidate_group_search_cache(active_group_id)

        status_code = 202 if queued and not errors else (207 if queued else 400)
        target_mode_label = "Enhanced" if target_mode == "layout" else "Standard"
        return jsonify({
            'message': f'Queued {len(queued)} document(s) to extract again with {target_mode_label}.',
            'queued': queued,
            'errors': errors,
        }), status_code

    @app.route('/api/group_documents/upgrade_legacy', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_upgrade_legacy_group_documents():
        user_id = get_current_user_id()
        active_group_id, _, _, error_response = _require_active_group_document_context(
            user_id,
            allowed_roles=("Owner", "Admin", "DocumentManager"),
            permission_message='Insufficient permissions',
        )
        if error_response:
            return error_response
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

        try:
            active_group_id = require_active_group(
                user_id,
                allowed_roles=GROUP_DOCUMENT_SHARE_MANAGER_ROLES,
            )
        except ValueError:
            return jsonify({'error': 'No active group selected'}), 400
        except LookupError:
            return jsonify({'error': 'Active group not found'}), 404
        except PermissionError:
            return jsonify({'error': 'Insufficient permissions'}), 403

        # Get the document
        try:
            document = get_document_metadata(document_id=document_id, user_id=user_id, group_id=active_group_id)
            if not document:
                return jsonify({'error': 'Document not found'}), 404

            if document.get('group_id') != active_group_id:
                return jsonify({'error': 'Only the owning group can view document sharing'}), 403

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

        try:
            active_group_id = require_active_group(
                user_id,
                allowed_roles=GROUP_DOCUMENT_SHARE_MANAGER_ROLES,
            )
        except ValueError:
            return jsonify({'error': 'No active group selected'}), 400
        except LookupError:
            return jsonify({'error': 'Active group not found'}), 404
        except PermissionError:
            return jsonify({'error': 'Insufficient permissions'}), 403

        try:
            # Get the document
            document_item = get_document_metadata(document_id=document_id, user_id=user_id, group_id=active_group_id)
            if not document_item:
                return jsonify({'error': 'Document not found or access denied'}), 404
            shared_group_ids = document_item.get('shared_group_ids', [])
            shared_entry = _find_group_share_entry(shared_group_ids, active_group_id)
            if not shared_entry or document_item.get('group_id') == active_group_id:
                return jsonify({'error': 'This document is not awaiting approval for the active group'}), 400

            updated = False
            new_shared_group_ids = shared_group_ids
            if _get_group_share_status(shared_entry) != 'approved':
                new_shared_group_ids = _set_group_share_status(
                    shared_group_ids,
                    active_group_id,
                    'approved',
                )
                updated = True

            if updated:
                document_share_details = _set_group_share_detail(
                    document_item,
                    active_group_id,
                    {
                        'status': 'approved',
                        'decided_by_user_id': user_id,
                        'decided_at': datetime.now(timezone.utc).isoformat(),
                    },
                )
                update_document(
                    document_id=document_id,
                    group_id=document_item.get('group_id'),
                    user_id=user_id,
                    shared_group_ids=new_shared_group_ids,
                    document_share_details=document_share_details,
                )
                _clear_group_document_share_pending_notifications(document_id, active_group_id)
                refreshed_document = get_document_metadata(
                    document_id=document_id,
                    user_id=user_id,
                    group_id=active_group_id,
                ) or document_item
                _create_group_document_share_decision_notification(
                    refreshed_document,
                    active_group_id,
                    'approved',
                    user_id,
                )
                # Invalidate cache for the group that approved
                invalidate_group_search_cache(active_group_id)

            return jsonify({'message': 'Share approved' if updated else 'Already approved'}), 200
        except Exception as e:
            return jsonify({'error': f'Error approving shared document: {str(e)}'}), 500

    @app.route('/api/group_documents/<document_id>/approve-generated-artifact', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_approve_group_generated_artifact(document_id):
        """Approve a generated chat artifact promotion into the active group workspace."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            active_group_id = require_active_group(
                user_id,
                allowed_roles=("Owner", "Admin", "DocumentManager"),
            )
            group_doc = find_group_by_id(group_id=active_group_id)
            if not group_doc:
                return jsonify({'error': 'Active group not found'}), 404

            allowed, reason = check_group_status_allows_operation(group_doc, 'upload')
            if not allowed:
                return jsonify({'error': reason}), 403

            document_item = get_document_metadata(
                document_id=document_id,
                user_id=user_id,
                group_id=active_group_id,
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
                    document_id=document_id,
                    user_id=owner_user_id,
                    group_id=active_group_id,
                    status='Queued for processing',
                    percentage_complete=0,
                    generated_artifact_promotion_status='approved',
                    generated_artifact_approved_at=datetime.now(timezone.utc).isoformat(),
                    generated_artifact_approved_by_user_id=user_id,
                    generated_artifact_approved_by_display_name=approver_name,
                )
                queue_generated_document_processing(
                    document_id=document_id,
                    owner_user_id=owner_user_id,
                    normalized_file_name=str(document_item.get('file_name') or 'generated-artifact.json').strip() or 'generated-artifact.json',
                    file_content_bytes=artifact_bytes,
                    group_id=active_group_id,
                )
            except Exception as exc:
                update_document(
                    document_id=document_id,
                    user_id=owner_user_id,
                    group_id=active_group_id,
                    status=f'Approval failed: {str(exc)}',
                    generated_artifact_promotion_status='approval_failed',
                )
                raise

            _cleanup_group_generated_artifact_notifications(document_id, active_group_id)
            invalidate_group_search_cache(active_group_id)

            group_name = str(group_doc.get('name') or 'this group').strip() or 'this group'
            create_notification(
                user_id=owner_user_id,
                notification_type='approval_request_approved',
                title='Generated artifact approved',
                message=f"{str(document_item.get('file_name') or 'Your generated artifact').strip()} was approved for {group_name} and is now processing.",
                link_url='/group_workspaces',
                link_context={
                    'workspace_type': 'group',
                    'group_id': active_group_id,
                    'document_id': document_id,
                },
                metadata={
                    'document_id': document_id,
                    'group_id': active_group_id,
                    'request_type': 'generated_artifact_promotion',
                },
            )

            return jsonify({
                'message': 'Generated artifact approved and queued for processing',
                'document_id': document_id,
            }), 200
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as e:
            return jsonify({'error': f'Error approving generated artifact: {str(e)}'}), 500

    @app.route('/api/group_documents/<document_id>/deny-generated-artifact', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_deny_group_generated_artifact(document_id):
        """Deny a pending generated chat artifact promotion in the active group workspace."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            active_group_id = require_active_group(
                user_id,
                allowed_roles=("Owner", "Admin", "DocumentManager"),
            )
            assert_group_role(
                user_id,
                active_group_id,
                allowed_roles=("Owner", "Admin", "DocumentManager"),
            )
            group_doc = find_group_by_id(group_id=active_group_id)
            if not group_doc:
                return jsonify({'error': 'Active group not found'}), 404

            document_item = get_document_metadata(
                document_id=document_id,
                user_id=user_id,
                group_id=active_group_id,
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
            group_name = str(group_doc.get('name') or 'this group').strip() or 'this group'
            denier_name = _get_generated_artifact_actor_name(get_current_user_info(), user_id)

            delete_document_revision(
                user_id=user_id,
                document_id=document_id,
                delete_mode='all_versions',
                group_id=active_group_id,
            )
            _cleanup_group_generated_artifact_notifications(document_id, active_group_id)
            invalidate_group_search_cache(active_group_id)

            if requester_user_id:
                create_notification(
                    user_id=requester_user_id,
                    notification_type='approval_request_denied',
                    title='Generated artifact denied',
                    message=f"{document_name} was denied for {group_name} by {denier_name}.",
                    link_url='/group_workspaces',
                    link_context={
                        'workspace_type': 'group',
                        'group_id': active_group_id,
                    },
                    metadata={
                        'document_id': document_id,
                        'group_id': active_group_id,
                        'request_type': 'generated_artifact_promotion',
                    },
                )

            return jsonify({'message': 'Generated artifact request denied and removed from the group workspace.'}), 200
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as e:
            return jsonify({'error': f'Error denying generated artifact: {str(e)}'}), 500

    @app.route('/api/group_documents/<document_id>/cancel-generated-artifact', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_cancel_group_generated_artifact(document_id):
        """Cancel a pending generated chat artifact promotion requested by the current user."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            active_group_id = require_active_group(
                user_id,
                allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
            )
            assert_group_role(
                user_id,
                active_group_id,
                allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
            )

            document_item = get_document_metadata(
                document_id=document_id,
                user_id=user_id,
                group_id=active_group_id,
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
                document_id=document_id,
                delete_mode='all_versions',
                group_id=active_group_id,
            )
            _cleanup_group_generated_artifact_notifications(document_id, active_group_id)
            invalidate_group_search_cache(active_group_id)

            return jsonify({'message': 'Generated artifact request canceled.'}), 200
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as e:
            return jsonify({'error': f'Error canceling generated artifact: {str(e)}'}), 500

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

        try:
            active_group_id = require_active_group(
                user_id,
                allowed_roles=GROUP_DOCUMENT_SHARE_MANAGER_ROLES,
            )
        except ValueError:
            return jsonify({'error': 'No active group selected'}), 400
        except LookupError:
            return jsonify({'error': 'Active group not found'}), 404
        except PermissionError:
            return jsonify({'error': 'You do not have permission to share documents in this group'}), 403

        group_doc = find_group_by_id(active_group_id)

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

            if target_group_id == active_group_id:
                return jsonify({'error': 'A group cannot share a document with itself'}), 400

            # Add target group to shared_group_ids if not already there
            shared_group_ids = document.get('shared_group_ids', [])
            already_shared = bool(_find_group_share_entry(shared_group_ids, target_group_id))
            if not already_shared:
                shared_group_ids = _set_group_share_status(
                    shared_group_ids,
                    target_group_id,
                    'not_approved',
                )
                shared_by_user_info = get_current_user_info() or {}
                document_share_details = _set_group_share_detail(
                    document,
                    target_group_id,
                    {
                        'status': 'not_approved',
                        'shared_by_user_id': user_id,
                        'shared_by_display_name': _get_generated_artifact_actor_name(
                            shared_by_user_info,
                            user_id,
                        ),
                        'shared_at': datetime.now(timezone.utc).isoformat(),
                        'source_group_id': active_group_id,
                        'target_group_id': target_group_id,
                    },
                )

                # Update the document
                update_document(
                    document_id=document_id,
                    group_id=active_group_id,
                    user_id=user_id,
                    shared_group_ids=shared_group_ids,
                    document_share_details=document_share_details,
                )

                refreshed_document = get_document_metadata(
                    document_id=document_id,
                    user_id=user_id,
                    group_id=active_group_id,
                ) or document
                _create_group_document_share_pending_notifications(
                    refreshed_document,
                    group_doc,
                    target_group,
                    user_id,
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

        try:
            active_group_id = require_active_group(
                user_id,
                allowed_roles=GROUP_DOCUMENT_SHARE_MANAGER_ROLES,
            )
        except ValueError:
            return jsonify({'error': 'No active group selected'}), 400
        except LookupError:
            return jsonify({'error': 'Active group not found'}), 404
        except PermissionError:
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
            if _find_group_share_entry(shared_group_ids, target_group_id):
                shared_group_ids = _remove_group_share_entries(shared_group_ids, target_group_id)

                # Update the document
                update_document(
                    document_id=document_id,
                    group_id=active_group_id,
                    user_id=user_id,
                    shared_group_ids=shared_group_ids
                )
                _clear_group_document_share_pending_notifications(document_id, target_group_id)

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

        try:
            active_group_id = require_active_group(
                user_id,
                allowed_roles=GROUP_DOCUMENT_SHARE_MANAGER_ROLES,
            )
        except ValueError:
            return jsonify({'error': 'No active group selected'}), 400
        except LookupError:
            return jsonify({'error': 'Active group not found'}), 404
        except PermissionError:
            return jsonify({'error': 'You do not have permission to remove shared documents in this group'}), 403

        # Get the document metadata
        try:
            document = get_document_metadata(document_id=document_id, user_id=user_id, group_id=active_group_id)
            if not document:
                return jsonify({'error': 'Document not found'}), 404

            # If the group is the owner, do not allow removal
            if document.get('group_id') == active_group_id:
                return jsonify({'error': 'Owning group cannot remove itself from its own document'}), 400

            shared_group_ids = document.get('shared_group_ids', [])
            shared_entry = _find_group_share_entry(shared_group_ids, active_group_id)
            if not shared_entry:
                return jsonify({'error': 'Group is not a shared group for this document'}), 400

            was_pending = _get_group_share_status(shared_entry) == 'not_approved'

            # Remove the group from shared_group_ids
            shared_group_ids = _remove_group_share_entries(shared_group_ids, active_group_id)
            document_share_details = _set_group_share_detail(
                document,
                active_group_id,
                {
                    'status': 'denied' if was_pending else 'removed',
                    'decided_by_user_id': user_id,
                    'decided_at': datetime.now(timezone.utc).isoformat(),
                },
            )
            update_document(
                document_id=document_id,
                group_id=document.get('group_id'),
                user_id=user_id,
                shared_group_ids=shared_group_ids,
                document_share_details=document_share_details,
            )
            _clear_group_document_share_pending_notifications(document_id, active_group_id)
            if was_pending:
                _create_group_document_share_decision_notification(
                    document,
                    active_group_id,
                    'denied',
                    user_id,
                )
            invalidate_group_search_cache(active_group_id)
            invalidate_group_search_cache(document.get('group_id'))
            return jsonify({
                'message': 'Share denied' if was_pending else 'Successfully removed group from shared document'
            }), 200
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
            try:
                group_ids = [require_active_group(user_id)]
            except (ValueError, LookupError, PermissionError):
                group_ids = []

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

        active_group_id, group_doc, _, error_response = _require_active_group_document_context(
            user_id,
            allowed_roles=("Owner", "Admin", "DocumentManager"),
            permission_message='You do not have permission to manage tags',
        )
        if error_response:
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

            tag_defs = group_doc.get('tag_definitions', {})

            if normalized_tag in tag_defs:
                return jsonify({'error': 'Tag already exists'}), 409

            tag_defs[normalized_tag] = {
                'color': normalized_color,
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            group_doc['tag_definitions'] = tag_defs
            cosmos_groups_container.upsert_item(group_doc)

            return jsonify({
                'message': f'Tag "{normalized_tag}" created successfully',
                'tag': {
                    'name': normalized_tag,
                    'color': normalized_color
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

        active_group_id, _, _, error_response = _require_active_group_document_context(
            user_id,
            allowed_roles=("Owner", "Admin", "DocumentManager"),
            permission_message='You do not have permission to manage tags',
        )
        if error_response:
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

        active_group_id, group_doc, _, error_response = _require_active_group_document_context(
            user_id,
            allowed_roles=("Owner", "Admin", "DocumentManager"),
            permission_message='You do not have permission to manage tags',
        )
        if error_response:
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
                is_valid_color, color_error, normalized_color = validate_tag_color(new_color, normalized_old_tag)
                if not is_valid_color:
                    return jsonify({'error': color_error}), 400

                tag_defs = group_doc.get('tag_definitions', {})

                if normalized_old_tag in tag_defs:
                    tag_defs[normalized_old_tag]['color'] = normalized_color
                else:
                    from datetime import datetime, timezone
                    tag_defs[normalized_old_tag] = {
                        'color': normalized_color,
                        'created_at': datetime.now(timezone.utc).isoformat()
                    }

                group_doc['tag_definitions'] = tag_defs
                cosmos_groups_container.upsert_item(group_doc)

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

        active_group_id, group_doc, _, error_response = _require_active_group_document_context(
            user_id,
            allowed_roles=("Owner", "Admin", "DocumentManager"),
            permission_message='You do not have permission to manage tags',
        )
        if error_response:
            return error_response

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
