# route_backend_public_document_management.py
"""Immutable-target public workspace document management routes.

The workspace is always taken from the path, never from a query parameter and
never from a stored active-workspace preference. An older server that lacks
these routes 404s rather than executing an upload, edit, or delete against the
account's currently selected workspace. These routes are not aliases for the
legacy public document routes.
"""

from functools import wraps

from flask import current_app, g, jsonify, request

from content_screening.access import (
    assert_current_request_sources_available,
    register_document_api_guards,
)
from functions_authentication import *
from functions_settings import *
from functions_public_document_access import require_public_document_management_context
from functions_public_document_management import (
    PublicDocumentOperationError,
    change_public_document_tag,
    create_public_document_tag,
    delete_public_document,
    delete_public_documents,
    download_public_documents,
    public_operation_error,
    queue_public_document_jobs,
    require_payload,
    tag_public_documents,
    update_public_document_metadata,
    upload_public_documents,
    validate_delete_options,
    validate_metadata_changes,
    validate_public_download_response,
)
from swagger_wrapper import swagger_route, get_auth_security


def _public_document_management_boundary(function):
    @wraps(function)
    def guarded(workspace_id, *args, **kwargs):
        try:
            return function(workspace_id, *args, **kwargs)
        except Exception as error:
            payload, status = public_operation_error(
                error, function.__name__, workspace_id=workspace_id, document_id=kwargs.get("document_id"),
            )
            return jsonify(payload), status
    return guarded


def _public_management_query(allowed=()):
    if set(request.args) - set(allowed) or any(len(values) != 1 for _key, values in request.args.lists()):
        raise PublicDocumentOperationError("Invalid query parameters for this public workspace operation.", 400)
    return request.args.to_dict()


def _public_management_body(allowed, required=()):
    return require_payload(request.get_json(silent=True), allowed, required)


def _validate_public_document_response_sources():
    binding = getattr(g, "public_document_download_binding", None)
    if binding:
        validate_public_download_response(binding["user_id"], binding["workspace_id"], binding["documents"])
    else:
        assert_current_request_sources_available()


def register_route_backend_public_document_management(bp):
    """Register the immutable-target public workspace document management routes.

    - POST   /api/public-workspaces/<workspace_id>/documents/upload
    - PATCH  /api/public-workspaces/<workspace_id>/documents/<document_id>
    - DELETE /api/public-workspaces/<workspace_id>/documents/<document_id>
    - POST   /api/public-workspaces/<workspace_id>/documents/bulk-delete
    - GET    /api/public-workspaces/<workspace_id>/documents/<document_id>/download
    - POST   /api/public-workspaces/<workspace_id>/documents/download
    - POST   /api/public-workspaces/<workspace_id>/documents/extract_metadata
    - POST   /api/public-workspaces/<workspace_id>/documents/reprocess_extraction
    - POST   /api/public-workspaces/<workspace_id>/documents/tags
    - PATCH  /api/public-workspaces/<workspace_id>/documents/tags/<tag_name>
    - DELETE /api/public-workspaces/<workspace_id>/documents/tags/<tag_name>
    - POST   /api/public-workspaces/<workspace_id>/documents/bulk-tag
    """
    register_document_api_guards(bp, source_validator=_validate_public_document_response_sources)

    @bp.route('/api/public-workspaces/<workspace_id>/documents/upload', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_management_boundary
    def api_scoped_public_document_upload(workspace_id):
        _public_management_query()
        if request.form or set(request.files) - {"file"}:
            raise PublicDocumentOperationError("Only file upload fields are accepted.", 400)
        payload, status = upload_public_documents(
            get_current_user_id(), workspace_id, request.files.getlist("file"), current_app.extensions["executor"],
        )
        return jsonify(payload), status

    @bp.route('/api/public-workspaces/<workspace_id>/documents/<document_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_management_boundary
    def api_scoped_public_document_metadata(workspace_id, document_id):
        _public_management_query()
        changes = validate_metadata_changes(request.get_json(silent=True))
        receipt = update_public_document_metadata(get_current_user_id(), workspace_id, document_id, changes)
        return jsonify(receipt), 202 if receipt["status"] == "queued" else 200

    @bp.route('/api/public-workspaces/<workspace_id>/documents/<document_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_management_boundary
    def api_scoped_public_document_delete(workspace_id, document_id):
        options = validate_delete_options(_public_management_query({
            "delete_mode", "conversation_linked_delete_confirmed", "file_sync_delete_action",
        }), query=True)
        if request.get_data():
            raise PublicDocumentOperationError("Deletion options must be supplied in the query.", 400)
        return jsonify(delete_public_document(get_current_user_id(), workspace_id, document_id, options)), 200

    @bp.route('/api/public-workspaces/<workspace_id>/documents/bulk-delete', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_management_boundary
    def api_scoped_public_documents_delete(workspace_id):
        _public_management_query()
        payload, status = delete_public_documents(get_current_user_id(), workspace_id, request.get_json(silent=True))
        return jsonify(payload), status

    @bp.route('/api/public-workspaces/<workspace_id>/documents/<document_id>/download', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_management_boundary
    def api_scoped_public_document_download(workspace_id, document_id):
        _public_management_query()
        user_id = get_current_user_id()
        response, documents = download_public_documents(user_id, workspace_id, [document_id])
        g.public_document_download_binding = {"user_id": user_id, "workspace_id": workspace_id, "documents": documents}
        return response

    @bp.route('/api/public-workspaces/<workspace_id>/documents/download', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_management_boundary
    def api_scoped_public_documents_download(workspace_id):
        _public_management_query()
        payload = _public_management_body({"document_ids"}, {"document_ids"})
        user_id = get_current_user_id()
        response, documents = download_public_documents(user_id, workspace_id, payload["document_ids"])
        g.public_document_download_binding = {"user_id": user_id, "workspace_id": workspace_id, "documents": documents}
        return response

    @bp.route('/api/public-workspaces/<workspace_id>/documents/extract_metadata', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_management_boundary
    def api_scoped_public_documents_extract(workspace_id):
        _public_management_query()
        payload, status = queue_public_document_jobs(
            get_current_user_id(), workspace_id, request.get_json(silent=True),
            "extract_metadata", current_app.extensions["executor"],
        )
        return jsonify(payload), status

    @bp.route('/api/public-workspaces/<workspace_id>/documents/reprocess_extraction', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_management_boundary
    def api_scoped_public_documents_reprocess(workspace_id):
        _public_management_query()
        payload, status = queue_public_document_jobs(
            get_current_user_id(), workspace_id, request.get_json(silent=True),
            "reprocess", current_app.extensions["executor"],
        )
        return jsonify(payload), status

    @bp.route('/api/public-workspaces/<workspace_id>/documents/tags', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_management_boundary
    def api_scoped_public_tag_create(workspace_id):
        _public_management_query()
        payload, status = create_public_document_tag(get_current_user_id(), workspace_id, request.get_json(silent=True))
        return jsonify(payload), status

    @bp.route('/api/public-workspaces/<workspace_id>/documents/tags/<path:tag_name>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_management_boundary
    def api_scoped_public_tag_update(workspace_id, tag_name):
        _public_management_query()
        payload, status = change_public_document_tag(
            get_current_user_id(), workspace_id, tag_name, request.get_json(silent=True),
        )
        return jsonify(payload), status

    @bp.route('/api/public-workspaces/<workspace_id>/documents/tags/<path:tag_name>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_management_boundary
    def api_scoped_public_tag_delete(workspace_id, tag_name):
        _public_management_query()
        if request.get_data():
            raise PublicDocumentOperationError("A tag deletion does not accept a request body.", 400)
        payload, status = change_public_document_tag(get_current_user_id(), workspace_id, tag_name, delete=True)
        return jsonify(payload), status

    @bp.route('/api/public-workspaces/<workspace_id>/documents/bulk-tag', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_management_boundary
    def api_scoped_public_documents_tag(workspace_id):
        _public_management_query()
        payload, status = tag_public_documents(get_current_user_id(), workspace_id, request.get_json(silent=True))
        return jsonify(payload), status
