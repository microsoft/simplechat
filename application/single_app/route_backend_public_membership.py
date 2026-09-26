# route_backend_public_membership.py
"""The native public workspace membership routes.

- ``GET /api/public-workspaces/<workspace_id>/membership/members`` lists the members,
  paged, with each member's ``member_actions`` and the ``membership_management`` hint;
- ``POST /api/public-workspaces/<workspace_id>/membership/members`` adds a member;
- ``PATCH /api/public-workspaces/<workspace_id>/membership/members/<user_id>`` changes
  a role;
- ``DELETE /api/public-workspaces/<workspace_id>/membership/members/<user_id>`` removes
  a member. There is no "leave": self-removal is refused;
- ``GET /api/public-workspaces/<workspace_id>/membership/requests`` lists the pending
  document-manager requests;
- ``POST /api/public-workspaces/<workspace_id>/membership/requests/<user_id>/approve``
  and ``.../reject`` decide one;
- ``PUT /api/public-workspaces/<workspace_id>/membership/owner`` transfers ownership.

They sit beside the classic ``/api/public_workspaces/<ws_id>/members``, ``/requests``
and ``/transferOwnership`` routes, which are unchanged, and share no path pattern with
them (the classic family uses an underscore, ``public_workspaces``, and no
``/membership`` segment), so a server without these routes answers 404 or 405 rather
than running another handler against whatever workspace an account has selected. The
rules live in ``functions_public_membership`` and ``functions_public_membership_policy``.
"""

from functools import wraps

from flask import jsonify

from functions_authentication import get_current_user_id, get_current_user_info, login_required, user_required
from functions_public_membership import (
    add_public_member,
    approve_public_request,
    change_public_member_role,
    list_public_join_requests,
    list_public_members,
    public_membership_error_response,
    read_member_list_query,
    reject_public_request,
    reject_query_parameters,
    reject_request_body,
    remove_public_member,
    transfer_public_ownership,
)
from functions_settings import enabled_required
from swagger_wrapper import swagger_route, get_auth_security


def _public_membership_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - all mapped to stable HTTP responses
            return public_membership_error_response(error)
    return guarded


def _no_store(payload, status):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


def register_route_backend_public_membership(bp):
    """Register the native public workspace membership routes."""

    @bp.route('/api/public-workspaces/<workspace_id>/membership/members', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_membership_boundary
    def api_public_membership_list(workspace_id):
        """List the members: ``search``, ``role``, ``page`` and ``page_size``."""
        query = read_member_list_query()
        reject_request_body()
        return _no_store(*list_public_members(get_current_user_id(), workspace_id, **query))

    @bp.route('/api/public-workspaces/<workspace_id>/membership/members', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_membership_boundary
    def api_public_membership_add(workspace_id):
        """Add a member from ``{userId, displayName?, email?, role}``."""
        reject_query_parameters()
        return _no_store(*add_public_member(get_current_user_info(), workspace_id))

    @bp.route('/api/public-workspaces/<workspace_id>/membership/members/<user_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_membership_boundary
    def api_public_membership_role(workspace_id, user_id):
        """Change a member's role from ``{role}``."""
        reject_query_parameters()
        return _no_store(*change_public_member_role(get_current_user_info(), workspace_id, user_id))

    @bp.route('/api/public-workspaces/<workspace_id>/membership/members/<user_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_membership_boundary
    def api_public_membership_remove(workspace_id, user_id):
        """Remove a member. There is no "leave"."""
        reject_query_parameters()
        reject_request_body()
        return _no_store(*remove_public_member(get_current_user_info(), workspace_id, user_id))

    @bp.route('/api/public-workspaces/<workspace_id>/membership/requests', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_membership_boundary
    def api_public_membership_requests(workspace_id):
        """List the pending document-manager requests."""
        reject_query_parameters()
        reject_request_body()
        return _no_store(*list_public_join_requests(get_current_user_id(), workspace_id))

    @bp.route('/api/public-workspaces/<workspace_id>/membership/requests/<user_id>/approve', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_membership_boundary
    def api_public_membership_request_approve(workspace_id, user_id):
        """Approve a pending request."""
        reject_query_parameters()
        reject_request_body()
        return _no_store(*approve_public_request(get_current_user_info(), workspace_id, user_id))

    @bp.route('/api/public-workspaces/<workspace_id>/membership/requests/<user_id>/reject', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_membership_boundary
    def api_public_membership_request_reject(workspace_id, user_id):
        """Reject a pending request."""
        reject_query_parameters()
        reject_request_body()
        return _no_store(*reject_public_request(get_current_user_info(), workspace_id, user_id))

    @bp.route('/api/public-workspaces/<workspace_id>/membership/owner', methods=['PUT'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_membership_boundary
    def api_public_membership_owner(workspace_id):
        """Transfer ownership from ``{userId}``."""
        reject_query_parameters()
        return _no_store(*transfer_public_ownership(get_current_user_info(), workspace_id))
