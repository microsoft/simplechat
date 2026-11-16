# route_backend_group_endpoints_scoped.py
"""Immutable-target group model endpoint routes: the group is named in the path.

These sit beside the legacy active-scoped ``/api/group/model-endpoints`` routes,
which resolve the account's selected group and replace the whole collection; those
are left exactly as they are. An older server lacking this family 404s rather than
silently editing whatever group the account has selected.

Each route manages one endpoint, the same per-item shape as the personal and admin
model endpoint APIs. Reads are open to every member on a browsable status; writes
need Owner or Admin in an ``active`` group. PATCH and DELETE are conditional on the
endpoint's ``revision`` (``expected_revision``), so a stale editor cannot overwrite
a concurrent change: a mismatch is a 409 with nothing written. The named-group
discovery routes (``/api/groups/<group_id>/models/*``) live with the discovery
closures in ``route_backend_models.py``.
"""

from functools import wraps

from flask import jsonify

from functions_authentication import login_required, user_required, get_current_user_id
from functions_settings import enabled_required
from functions_group_endpoint_access import (
    create_group_model_endpoint,
    delete_group_model_endpoint,
    get_group_model_endpoint,
    group_endpoint_error_response,
    list_group_model_endpoints,
    read_strict_json_object,
    reject_query_parameters,
    reject_request_body,
    update_group_model_endpoint,
)
from swagger_wrapper import swagger_route, get_auth_security


def _group_endpoint_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - all mapped to stable HTTP responses
            return group_endpoint_error_response(error)
    return guarded


def _no_store(payload, status):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


def register_route_backend_group_endpoints_scoped(bp):
    """Register the immutable-target group model endpoint routes.

    - GET    /api/groups/<group_id>/model-endpoints
    - POST   /api/groups/<group_id>/model-endpoints
    - GET    /api/groups/<group_id>/model-endpoints/<endpoint_id>
    - PATCH  /api/groups/<group_id>/model-endpoints/<endpoint_id>
    - DELETE /api/groups/<group_id>/model-endpoints/<endpoint_id>
    """

    @bp.route('/api/groups/<group_id>/model-endpoints', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_endpoint_boundary
    def api_scoped_group_model_endpoints_list(group_id):
        reject_query_parameters()
        reject_request_body()
        return _no_store(*list_group_model_endpoints(get_current_user_id(), group_id))

    @bp.route('/api/groups/<group_id>/model-endpoints', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_endpoint_boundary
    def api_scoped_group_model_endpoints_create(group_id):
        reject_query_parameters()
        return _no_store(*create_group_model_endpoint(
            get_current_user_id(), group_id, read_strict_json_object(),
        ))

    @bp.route('/api/groups/<group_id>/model-endpoints/<endpoint_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_endpoint_boundary
    def api_scoped_group_model_endpoint_read(group_id, endpoint_id):
        reject_query_parameters()
        reject_request_body()
        return _no_store(*get_group_model_endpoint(get_current_user_id(), group_id, endpoint_id))

    @bp.route('/api/groups/<group_id>/model-endpoints/<endpoint_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_endpoint_boundary
    def api_scoped_group_model_endpoint_update(group_id, endpoint_id):
        reject_query_parameters()
        return _no_store(*update_group_model_endpoint(
            get_current_user_id(), group_id, endpoint_id, read_strict_json_object(),
        ))

    @bp.route('/api/groups/<group_id>/model-endpoints/<endpoint_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_endpoint_boundary
    def api_scoped_group_model_endpoint_delete(group_id, endpoint_id):
        # The DELETE body is exactly {"expected_revision": "..."}.
        reject_query_parameters()
        return _no_store(*delete_group_model_endpoint(
            get_current_user_id(), group_id, endpoint_id, read_strict_json_object(),
        ))
