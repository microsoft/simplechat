# route_backend_group_prompts_scoped.py
"""Immutable-target group prompt routes: the group is named in the path.

These sit beside the legacy active-scoped ``/api/group_prompts`` routes, which
are left exactly as they are. An older server lacking this family 404s rather
than silently serving whatever group the account has selected. Writes are
narrowed to Owner/Admin/DocumentManager (the legacy routes' User-write behaviour
is a separate, pre-existing policy question and is not changed here), and every
mutation is conditional on ``expected_etag`` so concurrent manager edits cannot
be lost to last-write-wins.
"""

import json
from functools import wraps

from flask import jsonify, request

from functions_authentication import login_required, user_required, get_current_user_id
from functions_settings import enabled_required
from functions_group_prompt_access import (
    GroupPromptError,
    create_group_prompt,
    delete_group_prompt,
    list_group_prompts,
    read_group_prompt,
    update_group_prompt,
    validate_group_prompt_create,
    validate_group_prompt_update,
)
from functions_prompts import PromptConflictError
from swagger_wrapper import swagger_route, get_auth_security


def _group_prompt_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except GroupPromptError as error:
            return jsonify({"error": error.description}), error.code
        except PromptConflictError:
            return jsonify({
                "error": "The prompt was changed by someone else. Refresh and try again.",
                "error_code": "prompt_changed",
            }), 409
    return guarded


def _reject_query_parameters():
    """Immutable-target prompt routes take no query parameters except the reader's page controls."""
    if request.args:
        raise GroupPromptError("This request does not accept query parameters.", 400)


def _reject_request_body():
    if request.get_data():
        raise GroupPromptError("This read does not accept a request body.", 400)


def _read_json_body():
    """Parse a JSON object body, rejecting duplicate keys so a smuggled second
    value cannot shadow a validated one."""
    def unique_fields(pairs):
        payload = {}
        for key, value in pairs:
            if key in payload:
                raise GroupPromptError("Duplicate fields are not supported.", 400)
            payload[key] = value
        return payload

    if not request.is_json:
        raise GroupPromptError("A JSON object is required for this action.", 400)
    try:
        body = json.loads(request.get_data(), object_pairs_hook=unique_fields)
    except (ValueError, UnicodeDecodeError) as error:
        raise GroupPromptError("Provide valid JSON with no duplicate fields.", 400) from error
    if not isinstance(body, dict):
        raise GroupPromptError("A JSON object is required for this action.", 400)
    return body


def _list_query():
    """The list route accepts only the shared pagination and search controls, each at most once."""
    allowed = {"page", "page_size", "search"}
    if set(request.args) - allowed or any(len(values) != 1 for _key, values in request.args.lists()):
        raise GroupPromptError("Invalid query parameters for this request.", 400)
    if request.get_data():
        raise GroupPromptError("This read does not accept a request body.", 400)
    return request.args


def register_route_backend_group_prompts_scoped(bp):
    """Register the immutable-target group prompt routes.

    - GET    /api/groups/<group_id>/prompts
    - POST   /api/groups/<group_id>/prompts
    - GET    /api/groups/<group_id>/prompts/<prompt_id>
    - PATCH  /api/groups/<group_id>/prompts/<prompt_id>
    - DELETE /api/groups/<group_id>/prompts/<prompt_id>
    """

    @bp.route('/api/groups/<group_id>/prompts', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_prompt_boundary
    def api_scoped_group_prompts_list(group_id):
        return jsonify(list_group_prompts(get_current_user_id(), group_id, _list_query())), 200

    @bp.route('/api/groups/<group_id>/prompts', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_prompt_boundary
    def api_scoped_group_prompts_create(group_id):
        _reject_query_parameters()
        name, content, options, error = validate_group_prompt_create(_read_json_body())
        if error:
            raise GroupPromptError(error, 400)
        prompt = create_group_prompt(get_current_user_id(), group_id, name, content, options)
        return jsonify(prompt), 201

    @bp.route('/api/groups/<group_id>/prompts/<prompt_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_prompt_boundary
    def api_scoped_group_prompt_read(group_id, prompt_id):
        _reject_query_parameters()
        _reject_request_body()
        return jsonify(read_group_prompt(get_current_user_id(), group_id, prompt_id)), 200

    @bp.route('/api/groups/<group_id>/prompts/<prompt_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_prompt_boundary
    def api_scoped_group_prompt_update(group_id, prompt_id):
        _reject_query_parameters()
        updates, expected_etag, error = validate_group_prompt_update(_read_json_body())
        if error:
            raise GroupPromptError(error, 400)
        prompt = update_group_prompt(get_current_user_id(), group_id, prompt_id, updates, expected_etag)
        return jsonify(prompt), 200

    @bp.route('/api/groups/<group_id>/prompts/<prompt_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_prompt_boundary
    def api_scoped_group_prompt_delete(group_id, prompt_id):
        _reject_query_parameters()
        body = _read_json_body()
        unknown = set(body) - {"expected_etag"}
        if unknown:
            raise GroupPromptError(f"Unsupported field(s): {', '.join(sorted(unknown))}.", 400)
        expected_etag = body.get("expected_etag")
        if not isinstance(expected_etag, str) or not expected_etag.strip():
            raise GroupPromptError("A non-empty 'expected_etag' is required.", 400)
        delete_group_prompt(get_current_user_id(), group_id, prompt_id, expected_etag)
        return jsonify({"message": "Prompt deleted successfully."}), 200
