# route_backend_group_identities_scoped.py
"""Immutable-target group identity routes: the group is named in the path.

These sit beside the legacy active-scoped
``/api/workspace-identities/group/identities`` routes, which fall back to the
account's selected group and are left exactly as they are. An older server lacking
this family 404s rather than silently editing whatever group the account has
selected.

Group identities are manager-only for reads and writes. Every mutation is
conditional on ``expected_etag`` in the JSON body so a stale editor cannot
overwrite a concurrent manager edit — a mismatch is a 409 with nothing written —
and a delete refuses with 409 ``identity_in_use`` while a File Sync source or
action in the group still references the identity.
"""

import json
from functools import wraps

from flask import jsonify, request, session

from functions_authentication import get_current_user_id, get_current_user_info, login_required, user_required
from functions_group_identity_access import (
    GroupIdentityError,
    create_group_identity,
    delete_group_identity,
    get_group_identity,
    group_identity_error_response,
    list_group_identities,
    update_group_identity,
)
from functions_settings import enabled_required
from swagger_wrapper import get_auth_security, swagger_route


def _group_identity_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - all mapped to stable HTTP responses
            return group_identity_error_response(error)
    return guarded


def _current_user_info():
    """The caller's identity, with session roles overriding the stored roles.

    Mirrors the V2 context bootstrap so the shared availability predicate evaluates
    the File Sync ``file_sync_group_admin_only`` toggle against the live session,
    not a stale stored copy.
    """
    user_info = dict(get_current_user_info() or {})
    session_user = session.get("user")
    if isinstance(session_user, dict) and session_user.get("roles"):
        user_info["roles"] = session_user["roles"]
    return user_info


def _reject_query_parameters():
    """These immutable-target routes take no query parameters; a stray one is a 400
    rather than being silently ignored (e.g. ``?expected_etag=`` on DELETE)."""
    if request.args:
        raise GroupIdentityError("This request does not accept query parameters.", 400)


def _reject_request_body():
    if request.get_data():
        raise GroupIdentityError("This read does not accept a request body.", 400)


def _read_json_body():
    """Parse a JSON object body, rejecting duplicate keys so a smuggled second value
    cannot shadow a validated one."""
    def unique_fields(pairs):
        payload = {}
        for key, value in pairs:
            if key in payload:
                raise GroupIdentityError("Duplicate fields are not supported.", 400)
            payload[key] = value
        return payload

    if not request.is_json:
        raise GroupIdentityError("A JSON object is required for this action.", 400)
    try:
        body = json.loads(request.get_data(), object_pairs_hook=unique_fields)
    except (ValueError, UnicodeDecodeError) as error:
        raise GroupIdentityError("Provide valid JSON with no duplicate fields.", 400) from error
    if not isinstance(body, dict):
        raise GroupIdentityError("A JSON object is required for this action.", 400)
    return body


def register_route_backend_group_identities_scoped(bp):
    """Register the immutable-target group identity routes.

    - GET    /api/groups/<group_id>/identities
    - POST   /api/groups/<group_id>/identities
    - GET    /api/groups/<group_id>/identities/<identity_id>
    - PATCH  /api/groups/<group_id>/identities/<identity_id>
    - DELETE /api/groups/<group_id>/identities/<identity_id>
    """

    @bp.route('/api/groups/<group_id>/identities', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_identity_boundary
    def api_scoped_group_identities_list(group_id):
        _reject_query_parameters()
        _reject_request_body()
        payload, status = list_group_identities(
            get_current_user_id(), group_id, user_info=_current_user_info(),
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/identities', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_identity_boundary
    def api_scoped_group_identity_create(group_id):
        _reject_query_parameters()
        payload, status = create_group_identity(
            get_current_user_id(), group_id, _read_json_body(), user_info=_current_user_info(),
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/identities/<identity_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_identity_boundary
    def api_scoped_group_identity_read(group_id, identity_id):
        _reject_query_parameters()
        _reject_request_body()
        payload, status = get_group_identity(
            get_current_user_id(), group_id, identity_id, user_info=_current_user_info(),
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/identities/<identity_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_identity_boundary
    def api_scoped_group_identity_update(group_id, identity_id):
        _reject_query_parameters()
        payload, status = update_group_identity(
            get_current_user_id(), group_id, identity_id, _read_json_body(), user_info=_current_user_info(),
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/identities/<identity_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_identity_boundary
    def api_scoped_group_identity_delete(group_id, identity_id):
        # Unlike a read, DELETE carries the JSON body that supplies expected_etag,
        # so a stale editor cannot delete an identity a concurrent manager changed.
        _reject_query_parameters()
        payload, status = delete_group_identity(
            get_current_user_id(), group_id, identity_id, _read_json_body(), user_info=_current_user_info(),
        )
        return jsonify(payload), status
