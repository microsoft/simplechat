# route_backend_group_membership.py
"""The native group membership routes.

- ``GET /api/groups/<group_id>/membership/members`` lists the members, paged, with
  each member's ``member_actions`` and the ``membership_management`` hint;
- ``POST /api/groups/<group_id>/membership/members`` adds a member;
- ``PATCH /api/groups/<group_id>/membership/members/<user_id>`` changes a role;
- ``DELETE /api/groups/<group_id>/membership/members/<user_id>`` removes a member,
  or leaves the group when ``user_id`` is the caller;
- ``GET /api/groups/<group_id>/membership/requests`` lists the pending requests;
- ``POST /api/groups/<group_id>/membership/requests/<user_id>/approve`` and
  ``.../reject`` decide one;
- ``PUT /api/groups/<group_id>/membership/owner`` transfers ownership.

They sit beside the classic ``/api/groups/<group_id>/members``, ``/requests`` and
``/transferOwnership`` routes, which are unchanged, and share no path pattern with
them, so a server without these routes answers 404 or 405 rather than running
another handler. The rules live in ``functions_group_membership`` and
``functions_group_membership_policy``.
"""

from functools import wraps

from flask import jsonify

from functions_authentication import get_current_user_id, get_current_user_info, login_required, user_required
from functions_group_directory import reject_query_parameters, reject_request_body
from functions_group_membership import (
    add_group_member,
    approve_join_request,
    change_group_member_role,
    group_membership_error_response,
    list_group_join_requests,
    list_group_members,
    read_member_list_query,
    reject_join_request,
    remove_group_member,
    transfer_group_ownership,
)
from functions_settings import enabled_required
from swagger_wrapper import swagger_route, get_auth_security


def _group_membership_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - all mapped to stable HTTP responses
            return group_membership_error_response(error)
    return guarded


def _no_store(payload, status):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


def register_route_backend_group_membership(bp):
    """Register the native group membership routes."""

    @bp.route('/api/groups/<group_id>/membership/members', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_membership_boundary
    def api_group_membership_list(group_id):
        """List the members: ``search``, ``role``, ``page`` and ``page_size``."""
        query = read_member_list_query()
        reject_request_body()
        return _no_store(*list_group_members(get_current_user_id(), group_id, **query))

    @bp.route('/api/groups/<group_id>/membership/members', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_membership_boundary
    def api_group_membership_add(group_id):
        """Add a member from ``{userId, displayName?, email?, role}``."""
        reject_query_parameters()
        return _no_store(*add_group_member(get_current_user_info(), group_id))

    @bp.route('/api/groups/<group_id>/membership/members/<user_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_membership_boundary
    def api_group_membership_role(group_id, user_id):
        """Change a member's role from ``{role}``."""
        reject_query_parameters()
        return _no_store(*change_group_member_role(get_current_user_info(), group_id, user_id))

    @bp.route('/api/groups/<group_id>/membership/members/<user_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_membership_boundary
    def api_group_membership_remove(group_id, user_id):
        """Remove a member, or leave the group."""
        reject_query_parameters()
        reject_request_body()
        return _no_store(*remove_group_member(get_current_user_info(), group_id, user_id))

    @bp.route('/api/groups/<group_id>/membership/requests', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_membership_boundary
    def api_group_membership_requests(group_id):
        """List the pending requests to join."""
        reject_query_parameters()
        reject_request_body()
        return _no_store(*list_group_join_requests(get_current_user_id(), group_id))

    @bp.route('/api/groups/<group_id>/membership/requests/<user_id>/approve', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_membership_boundary
    def api_group_membership_request_approve(group_id, user_id):
        """Approve a pending request."""
        reject_query_parameters()
        reject_request_body()
        return _no_store(*approve_join_request(get_current_user_info(), group_id, user_id))

    @bp.route('/api/groups/<group_id>/membership/requests/<user_id>/reject', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_membership_boundary
    def api_group_membership_request_reject(group_id, user_id):
        """Reject a pending request."""
        reject_query_parameters()
        reject_request_body()
        return _no_store(*reject_join_request(get_current_user_info(), group_id, user_id))

    @bp.route('/api/groups/<group_id>/membership/owner', methods=['PUT'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_membership_boundary
    def api_group_membership_owner(group_id):
        """Transfer ownership from ``{userId}``."""
        reject_query_parameters()
        return _no_store(*transfer_group_ownership(get_current_user_info(), group_id))
