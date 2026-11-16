# route_backend_public_document_collaboration.py
"""Immutable-target public workspace document collaboration routes.

The workspace is always taken from the path, never from a query parameter and
never from a stored active-workspace preference. An older server that lacks
these routes 404s rather than deciding a generated-artifact publication against
the account's currently selected workspace. These routes are not aliases for the
legacy public document routes.

Public workspaces have no cross-workspace share relationship yet (that arrives
with M3D), so the only collaboration surface here is the owner-side
generated-artifact decision: inspect, approve, reject, and cancel.
"""

from functools import wraps
import json

from flask import jsonify, request

from content_screening.access import register_document_api_guards
from functions_authentication import *
from functions_settings import *
from functions_public_document_collaboration import (
    collaboration_error_response,
    public_document_publication_state,
)
from functions_public_document_management import PublicDocumentOperationError
from functions_public_document_publication import decide_public_document_publication
from swagger_wrapper import swagger_route, get_auth_security


def _public_document_collaboration_boundary(function):
    @wraps(function)
    def guarded(workspace_id, document_id, *args, **kwargs):
        try:
            return function(workspace_id, document_id, *args, **kwargs)
        except Exception as error:
            payload, status = collaboration_error_response(
                error, public_workspace_id=workspace_id, document_id=document_id,
            )
            return jsonify(payload), status
    return guarded


def _public_document_collaboration_body():
    def unique_fields(pairs):
        payload = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError("Duplicate collaboration fields are not supported.")
            payload[key] = value
        return payload

    if not request.is_json:
        raise PublicDocumentOperationError("A JSON object is required for this action.", 400)
    try:
        return json.loads(request.get_data(), object_pairs_hook=unique_fields)
    except (ValueError, UnicodeDecodeError) as error:
        raise PublicDocumentOperationError("Provide valid JSON with no duplicate fields.", 400) from error


def register_route_backend_public_document_collaboration(bp):
    """Register the immutable-target public workspace collaboration routes.

    - GET  /api/public-workspaces/<workspace_id>/documents/<document_id>/publication
    - POST /api/public-workspaces/<workspace_id>/documents/<document_id>/artifact/approve
    - POST /api/public-workspaces/<workspace_id>/documents/<document_id>/artifact/reject
    - POST /api/public-workspaces/<workspace_id>/documents/<document_id>/artifact/cancel
    """
    register_document_api_guards(bp)

    @bp.route('/api/public-workspaces/<workspace_id>/documents/<document_id>/publication', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_collaboration_boundary
    def api_scoped_public_document_publication(workspace_id, document_id):
        """Read the generated-artifact publication state for one document in an explicit workspace."""
        if request.args:
            raise PublicDocumentOperationError("This read does not accept query parameters.", 400)
        if request.get_data():
            raise PublicDocumentOperationError("This read does not accept a request body.", 400)
        return jsonify(public_document_publication_state(get_current_user_id(), workspace_id, document_id)), 200

    @bp.route('/api/public-workspaces/<workspace_id>/documents/<document_id>/artifact/approve', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_collaboration_boundary
    def api_scoped_public_document_approve_artifact(workspace_id, document_id):
        """Approve a bound generated-artifact publication in an explicit public workspace."""
        if request.args:
            raise PublicDocumentOperationError("This action does not accept query parameters.", 400)
        payload, status = decide_public_document_publication(
            get_current_user_id(), workspace_id, document_id, "approve_artifact", _public_document_collaboration_body(),
        )
        return jsonify(payload), status

    @bp.route('/api/public-workspaces/<workspace_id>/documents/<document_id>/artifact/reject', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_collaboration_boundary
    def api_scoped_public_document_reject_artifact(workspace_id, document_id):
        """Reject a bound generated-artifact publication in an explicit public workspace."""
        if request.args:
            raise PublicDocumentOperationError("This action does not accept query parameters.", 400)
        payload, status = decide_public_document_publication(
            get_current_user_id(), workspace_id, document_id, "reject_artifact", _public_document_collaboration_body(),
        )
        return jsonify(payload), status

    @bp.route('/api/public-workspaces/<workspace_id>/documents/<document_id>/artifact/cancel', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_document_collaboration_boundary
    def api_scoped_public_document_cancel_artifact(workspace_id, document_id):
        """Cancel the requester's own bound generated-artifact publication in an explicit workspace."""
        if request.args:
            raise PublicDocumentOperationError("This action does not accept query parameters.", 400)
        payload, status = decide_public_document_publication(
            get_current_user_id(), workspace_id, document_id, "cancel_artifact", _public_document_collaboration_body(),
        )
        return jsonify(payload), status
