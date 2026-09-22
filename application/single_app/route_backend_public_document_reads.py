# route_backend_public_document_reads.py
"""Immutable-target, read-only public workspace document routes.

The workspace is always taken from the path, never from a query parameter and
never from a stored active-workspace preference. An older server that lacks
these routes 404s rather than silently serving the account's currently selected
workspace. These routes are not aliases for the legacy public document routes.
"""

from functools import wraps
import logging

from flask import g, jsonify, request

from content_screening.access import (
    public_documents_payload,
    register_document_api_guards,
)
from content_screening.contracts import ScreeningError
from functions_authentication import *
from functions_settings import *
from functions_appinsights import log_event
from functions_public_document_access import (
    PublicDocumentReadError,
    require_public_document_read_context,
)
from functions_public_document_reads import (
    PUBLIC_DOCUMENT_LIST_QUERY_PARAMS,
    PUBLIC_DOCUMENT_NO_QUERY_PARAMS,
    get_public_document_facets,
    get_public_document_read_metadata,
    get_public_document_read_tags,
    get_public_document_read_versions,
    load_public_document_browser_documents,
    query_public_document_list,
    refresh_public_document_read_payloads,
    validate_public_read_query,
)
from swagger_wrapper import swagger_route, get_auth_security


def _public_document_read_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except PublicDocumentReadError as error:
            return jsonify({"error": error.description}), error.code
        except ScreeningError as error:
            return jsonify({"error": error.public_message, "error_code": error.code}), error.status_code
        except Exception as error:
            log_event(
                "[DOCUMENTS] Public document read failed.",
                extra={"operation": function.__name__, "exception_type": type(error).__name__},
                level=logging.ERROR,
            )
            return jsonify({"error": "Unable to retrieve public documents."}), 500
    return guarded


def _reject_public_read_body():
    if request.content_length or request.get_data(cache=True):
        raise PublicDocumentReadError("This endpoint does not accept a request body.", 400)


def _project_public_document_read_response(documents, user_id):
    workspace_ids = getattr(g, "public_document_read_ids", None)
    if not workspace_ids or request.method not in {"GET", "HEAD"}:
        return public_documents_payload(documents, user_id)
    try:
        # Public workspaces have no cross-workspace share relationship in M3A, so
        # every read is scoped to exactly one explicit workspace target.
        workspace_id = workspace_ids[0]
        refreshed = {
            document["id"]: document
            for document in refresh_public_document_read_payloads(documents, user_id, workspace_id)
        }
        return [refreshed[document["id"]] for document in documents]
    except (PublicDocumentReadError, ScreeningError):
        raise
    except Exception as error:
        log_event(
            "[DOCUMENTS] Public document response revalidation failed.",
            extra={"exception_type": type(error).__name__},
            level=logging.ERROR,
        )
        raise PublicDocumentReadError("Unable to retrieve public documents.", 500) from error


def register_route_backend_public_document_reads(bp):
    """Register the immutable-target read-only public workspace document routes.

    - GET /api/public-workspaces/<workspace_id>/documents           (list)
    - GET /api/public-workspaces/<workspace_id>/documents/facets    (facets)
    - GET /api/public-workspaces/<workspace_id>/documents/tags      (tags)
    - GET /api/public-workspaces/<workspace_id>/documents/<document_id>          (metadata)
    - GET /api/public-workspaces/<workspace_id>/documents/<document_id>/versions (versions)
    """
    register_document_api_guards(bp, document_projector=_project_public_document_read_response)

    @bp.route('/api/public-workspaces/<workspace_id>/documents', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_read_boundary
    def api_get_public_workspace_documents(workspace_id):
        """List the safe current-revision document set for an explicit public workspace."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        _reject_public_read_body()
        validate_public_read_query(request.args, PUBLIC_DOCUMENT_LIST_QUERY_PARAMS)
        require_public_document_read_context(user_id, workspace_id)
        g.public_document_read_ids = [workspace_id]
        documents = load_public_document_browser_documents(user_id, workspace_id)
        payload = query_public_document_list(documents, workspace_id, request.args)
        payload["file_downloads_enabled"] = False
        return jsonify(payload), 200

    @bp.route('/api/public-workspaces/<workspace_id>/documents/facets', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_read_boundary
    def api_get_public_workspace_document_facets(workspace_id):
        """Count the complete safe current-revision set of an explicit public workspace."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        _reject_public_read_body()
        validate_public_read_query(request.args, PUBLIC_DOCUMENT_NO_QUERY_PARAMS)
        return jsonify(get_public_document_facets(user_id, workspace_id)), 200

    @bp.route('/api/public-workspaces/<workspace_id>/documents/tags', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_read_boundary
    def api_get_public_workspace_document_tags(workspace_id):
        """Return the workspace tag definitions with current-set counts and safe colors."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        _reject_public_read_body()
        validate_public_read_query(request.args, PUBLIC_DOCUMENT_NO_QUERY_PARAMS)
        return jsonify({"tags": get_public_document_read_tags(user_id, workspace_id)}), 200

    @bp.route('/api/public-workspaces/<workspace_id>/documents/<document_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_read_boundary
    def api_get_public_workspace_document(workspace_id, document_id):
        """Read metadata and processing progress for one document in an explicit workspace."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        _reject_public_read_body()
        validate_public_read_query(request.args, PUBLIC_DOCUMENT_NO_QUERY_PARAMS)
        g.public_document_read_ids = [workspace_id]
        return jsonify(get_public_document_read_metadata(user_id, workspace_id, document_id)), 200

    @bp.route('/api/public-workspaces/<workspace_id>/documents/<document_id>/versions', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_read_boundary
    def api_get_public_workspace_document_versions(workspace_id, document_id):
        """Return only the revisions individually authorized in the explicit workspace scope."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        _reject_public_read_body()
        validate_public_read_query(request.args, PUBLIC_DOCUMENT_NO_QUERY_PARAMS)
        g.public_document_read_ids = [workspace_id]
        return jsonify(get_public_document_read_versions(user_id, workspace_id, document_id)), 200
