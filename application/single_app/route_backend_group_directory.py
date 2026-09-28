# route_backend_group_directory.py
"""The native group directory routes.

- ``GET /api/groups/directory`` lists every group the caller may discover, paged,
  with the caller's membership in each and the ``group_directory`` hint;
- ``POST /api/groups/directory`` creates a group owned by the caller;
- ``POST /api/groups/<group_id>/join-request`` asks to join a group;
- ``DELETE /api/groups/<group_id>/join-request`` cancels the caller's own request.

They sit beside the classic ``/api/groups/discover``, ``POST /api/groups`` and
``/api/groups/<group_id>/requests``, which are unchanged. ``/api/groups/directory``
shares its shape with the classic ``/api/groups/<group_id>`` routes: GET and POST
reach these routes because a static segment outranks a converter, and PATCH, PUT
and DELETE still reach the classic group routes. Those refuse the request, with 404
because no group can have the id ``directory`` (``create_group`` mints UUIDs), or
first with their ``CreateGroups`` 403. An older server without these routes answers
GET with that same 404 and POST with 405.

The rules live in ``functions_group_directory`` and
``functions_group_directory_policy``.
"""

from functools import wraps

from flask import jsonify

from functions_authentication import get_current_user_id, get_current_user_info, login_required, user_required
from functions_group_directory import (
    cancel_group_join_request,
    create_directory_group,
    group_directory_error_response,
    list_group_directory,
    read_group_directory_query,
    reject_query_parameters,
    reject_request_body,
    request_to_join_group,
)
from functions_settings import enabled_required
from swagger_wrapper import swagger_route, get_auth_security


def _group_directory_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - all mapped to stable HTTP responses
            return group_directory_error_response(error)
    return guarded


def _no_store(payload, status):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


def register_route_backend_group_directory(bp):
    """Register the native group directory routes."""

    @bp.route('/api/groups/directory', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_directory_boundary
    def api_group_directory_list():
        """List the group directory: ``search``, ``view``, ``page`` and ``page_size``."""
        query = read_group_directory_query()
        reject_request_body()
        return _no_store(*list_group_directory(get_current_user_id(), **query))

    @bp.route('/api/groups/directory', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_directory_boundary
    def api_group_directory_create():
        """Create a group from ``{name, description?}``."""
        reject_query_parameters()
        return _no_store(*create_directory_group(get_current_user_id()))

    @bp.route('/api/groups/<group_id>/join-request', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_directory_boundary
    def api_group_join_request_create(group_id):
        """Ask to join the named group."""
        reject_query_parameters()
        reject_request_body()
        return _no_store(*request_to_join_group(get_current_user_info(), group_id))

    @bp.route('/api/groups/<group_id>/join-request', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_directory_boundary
    def api_group_join_request_cancel(group_id):
        """Cancel the caller's own request to join the named group."""
        reject_query_parameters()
        reject_request_body()
        return _no_store(*cancel_group_join_request(get_current_user_id(), group_id))
