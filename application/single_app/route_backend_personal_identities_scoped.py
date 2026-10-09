# route_backend_personal_identities_scoped.py
"""Strict native personal identity routes; classic APIs retain their existing contracts."""

import json
from functools import wraps

from flask import jsonify, request, session

from functions_authentication import get_current_user_id, get_current_user_info, login_required, user_required
from functions_personal_identity_access import (
    PersonalIdentityError,
    create_personal_identity,
    delete_personal_identity,
    get_personal_identity,
    list_personal_identities,
    personal_identity_error_response,
    update_personal_identity,
)
from swagger_wrapper import get_auth_security, swagger_route


def _personal_identity_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            if request.args:
                raise PersonalIdentityError("This request does not accept query parameters.", 400)
            result = function(*args, **kwargs)
            payload, status = result
            response = jsonify(payload)
            response.headers["Cache-Control"] = "no-store"
            return response, status
        except Exception as error:
            return personal_identity_error_response(error)
    return guarded


def _current_user_info():
    info = dict(get_current_user_info() or {})
    user = session.get("user")
    if isinstance(user, dict) and user.get("roles"):
        info["roles"] = user["roles"]
    return info


def _read_body():
    def unique_fields(pairs):
        payload = {}
        for key, value in pairs:
            if key in payload:
                raise PersonalIdentityError("Duplicate fields are not supported.", 400)
            payload[key] = value
        return payload

    if not request.is_json:
        raise PersonalIdentityError("A JSON object is required for this action.", 400)
    try:
        body = json.loads(request.get_data(), object_pairs_hook=unique_fields)
    except (ValueError, UnicodeDecodeError) as error:
        raise PersonalIdentityError("Provide valid JSON with no duplicate fields.", 400) from error
    if not isinstance(body, dict):
        raise PersonalIdentityError("A JSON object is required for this action.", 400)
    return body


def _reject_body():
    if request.get_data():
        raise PersonalIdentityError("This read does not accept a request body.", 400)


def register_route_backend_personal_identities_scoped(bp):
    @bp.route('/api/user/identities', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_personal_identity_boundary
    def api_personal_identities_list():
        _reject_body()
        return list_personal_identities(get_current_user_id(), user_info=_current_user_info())

    @bp.route('/api/user/identities/<identity_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_personal_identity_boundary
    def api_personal_identity_read(identity_id):
        _reject_body()
        return get_personal_identity(get_current_user_id(), identity_id, user_info=_current_user_info())

    @bp.route('/api/user/identities', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_personal_identity_boundary
    def api_personal_identity_create():
        return create_personal_identity(get_current_user_id(), _read_body(), user_info=_current_user_info())

    @bp.route('/api/user/identities/<identity_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_personal_identity_boundary
    def api_personal_identity_update(identity_id):
        return update_personal_identity(get_current_user_id(), identity_id, _read_body(), user_info=_current_user_info())

    @bp.route('/api/user/identities/<identity_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_personal_identity_boundary
    def api_personal_identity_delete(identity_id):
        return delete_personal_identity(get_current_user_id(), identity_id, _read_body(), user_info=_current_user_info())
