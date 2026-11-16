# route_backend_public_prompts_scoped.py
"""Immutable-target public prompt routes: the workspace is named in the path.

Version: 0.261.178
Implemented in: 0.261.178

These sit beside the legacy active-scoped ``/api/public_prompts`` routes, which
keep their own shape. An older server lacking this family 404s rather than
silently serving whatever public workspace the account has selected. Reads are
open to any authenticated caller of a browsable workspace (the established
public-read model), writes are narrowed to Owner/Admin/DocumentManager, and
every mutation is conditional on ``expected_etag`` so concurrent manager edits
cannot be lost to last-write-wins.

This mirrors ``route_backend_group_prompts_scoped.py`` line for line, including
the strict query, duplicate-key and body guards, so the two families reject the
same malformed requests identically. It shares the group's exact
``prompt_changed`` conflict text and code.
"""

import json
from functools import wraps

from flask import jsonify, request

from functions_authentication import login_required, user_required, get_current_user_id
from functions_settings import enabled_required
from functions_public_prompt_access import (
    PublicPromptError,
    create_public_prompt,
    delete_public_prompt,
    list_public_prompts,
    read_public_prompt,
    update_public_prompt,
    validate_public_prompt_create,
    validate_public_prompt_update,
)
from functions_prompts import PromptConflictError
from swagger_wrapper import swagger_route, get_auth_security


def _public_prompt_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except PublicPromptError as error:
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
        raise PublicPromptError("This request does not accept query parameters.", 400)


def _reject_request_body():
    if request.get_data():
        raise PublicPromptError("This read does not accept a request body.", 400)


def _read_json_body():
    """Parse a JSON object body, rejecting duplicate keys so a smuggled second
    value cannot shadow a validated one."""
    def unique_fields(pairs):
        payload = {}
        for key, value in pairs:
            if key in payload:
                raise PublicPromptError("Duplicate fields are not supported.", 400)
            payload[key] = value
        return payload

    if not request.is_json:
        raise PublicPromptError("A JSON object is required for this action.", 400)
    try:
        body = json.loads(request.get_data(), object_pairs_hook=unique_fields)
    except (ValueError, UnicodeDecodeError) as error:
        raise PublicPromptError("Provide valid JSON with no duplicate fields.", 400) from error
    if not isinstance(body, dict):
        raise PublicPromptError("A JSON object is required for this action.", 400)
    return body


def _list_query():
    """The list route accepts only the shared pagination and search controls, each at most once."""
    allowed = {"page", "page_size", "search"}
    if set(request.args) - allowed or any(len(values) != 1 for _key, values in request.args.lists()):
        raise PublicPromptError("Invalid query parameters for this request.", 400)
    if request.get_data():
        raise PublicPromptError("This read does not accept a request body.", 400)
    return request.args


def register_route_backend_public_prompts_scoped(bp):
    """Register the immutable-target public prompt routes.

    - GET    /api/public-workspaces/<workspace_id>/prompts
    - POST   /api/public-workspaces/<workspace_id>/prompts
    - GET    /api/public-workspaces/<workspace_id>/prompts/<prompt_id>
    - PATCH  /api/public-workspaces/<workspace_id>/prompts/<prompt_id>
    - DELETE /api/public-workspaces/<workspace_id>/prompts/<prompt_id>
    """

    @bp.route('/api/public-workspaces/<workspace_id>/prompts', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_prompt_boundary
    def api_scoped_public_prompts_list(workspace_id):
        return jsonify(list_public_prompts(get_current_user_id(), workspace_id, _list_query())), 200

    @bp.route('/api/public-workspaces/<workspace_id>/prompts', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_prompt_boundary
    def api_scoped_public_prompts_create(workspace_id):
        _reject_query_parameters()
        name, content, options, error = validate_public_prompt_create(_read_json_body())
        if error:
            raise PublicPromptError(error, 400)
        prompt = create_public_prompt(get_current_user_id(), workspace_id, name, content, options)
        return jsonify(prompt), 201

    @bp.route('/api/public-workspaces/<workspace_id>/prompts/<prompt_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_prompt_boundary
    def api_scoped_public_prompt_read(workspace_id, prompt_id):
        _reject_query_parameters()
        _reject_request_body()
        return jsonify(read_public_prompt(get_current_user_id(), workspace_id, prompt_id)), 200

    @bp.route('/api/public-workspaces/<workspace_id>/prompts/<prompt_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_prompt_boundary
    def api_scoped_public_prompt_update(workspace_id, prompt_id):
        _reject_query_parameters()
        updates, expected_etag, error = validate_public_prompt_update(_read_json_body())
        if error:
            raise PublicPromptError(error, 400)
        prompt = update_public_prompt(get_current_user_id(), workspace_id, prompt_id, updates, expected_etag)
        return jsonify(prompt), 200

    @bp.route('/api/public-workspaces/<workspace_id>/prompts/<prompt_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_prompt_boundary
    def api_scoped_public_prompt_delete(workspace_id, prompt_id):
        _reject_query_parameters()
        body = _read_json_body()
        unknown = set(body) - {"expected_etag"}
        if unknown:
            raise PublicPromptError(f"Unsupported field(s): {', '.join(sorted(unknown))}.", 400)
        expected_etag = body.get("expected_etag")
        if not isinstance(expected_etag, str) or not expected_etag.strip():
            raise PublicPromptError("A non-empty 'expected_etag' is required.", 400)
        delete_public_prompt(get_current_user_id(), workspace_id, prompt_id, expected_etag)
        return jsonify({"message": "Prompt deleted successfully."}), 200
