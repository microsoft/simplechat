# route_backend_group_file_sources_scoped.py
"""Immutable-target group file source routes: the group is named in the path.

These sit beside the legacy active-scoped ``/api/file-sync/group/sources`` routes,
which fall back to the account's selected group and are left exactly as they are.
An older server lacking this family 404s rather than silently editing whatever
group the account has selected.

Group file sources are manager-only for reads and writes. A PATCH and a DELETE are
conditional on ``expected_config_revision`` in the JSON body — a mismatch is a 409
``config_conflict`` with nothing written — and a DELETE refuses with 409
``source_busy`` while a run is queued or running. A test or browse of a saved
source uses stored identity credentials, so those routes are manager-only too.
"""

import json
from functools import wraps

from flask import jsonify, request, session

from functions_authentication import get_current_user_id, get_current_user_info, login_required, user_required
from functions_group_file_source_access import (
    GroupFileSourceError,
    browse_group_file_source,
    create_group_file_source,
    delete_group_file_source,
    get_group_file_source,
    get_group_file_source_options,
    group_file_source_error_response,
    ignore_group_file_source_path,
    list_group_file_sources,
    list_group_file_source_runs,
    sync_group_file_source,
    test_group_file_source_connection,
    update_group_file_source,
)
from functions_settings import enabled_required
from swagger_wrapper import get_auth_security, swagger_route


def _group_file_source_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - all mapped to stable HTTP responses
            return group_file_source_error_response(error)
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
    rather than being silently ignored."""
    if request.args:
        raise GroupFileSourceError("This request does not accept query parameters.", 400)


def _reject_request_body():
    if request.get_data():
        raise GroupFileSourceError("This request does not accept a request body.", 400)


def _unique_fields(pairs):
    payload = {}
    for key, value in pairs:
        if key in payload:
            raise GroupFileSourceError("Duplicate fields are not supported.", 400)
        payload[key] = value
    return payload


def _read_json_body():
    """Parse a required JSON object body, rejecting duplicate keys so a smuggled
    second value cannot shadow a validated one."""
    if not request.is_json:
        raise GroupFileSourceError("A JSON object is required for this action.", 400)
    try:
        body = json.loads(request.get_data(), object_pairs_hook=_unique_fields)
    except (ValueError, UnicodeDecodeError) as error:
        raise GroupFileSourceError("Provide valid JSON with no duplicate fields.", 400) from error
    if not isinstance(body, dict):
        raise GroupFileSourceError("A JSON object is required for this action.", 400)
    return body


def _read_optional_json_body():
    """Parse an optional JSON object body for a saved test or browse, which may run
    entirely against the stored source. An empty body is an empty object; any body
    present must be a JSON object with no duplicate keys."""
    if not request.get_data():
        return {}
    return _read_json_body()


def register_route_backend_group_file_sources_scoped(bp):
    """Register the immutable-target group file source routes.

    - GET    /api/groups/<group_id>/file-sources
    - POST   /api/groups/<group_id>/file-sources
    - GET    /api/groups/<group_id>/file-sources/<source_id>
    - PATCH  /api/groups/<group_id>/file-sources/<source_id>
    - DELETE /api/groups/<group_id>/file-sources/<source_id>
    - POST   /api/groups/<group_id>/file-sources/test-connection
    - POST   /api/groups/<group_id>/file-sources/<source_id>/test-connection
    - POST   /api/groups/<group_id>/file-sources/browse
    - POST   /api/groups/<group_id>/file-sources/<source_id>/browse
    - POST   /api/groups/<group_id>/file-sources/<source_id>/sync
    - GET    /api/groups/<group_id>/file-sources/<source_id>/runs
    - POST   /api/groups/<group_id>/file-sources/<source_id>/ignore-path
    - GET    /api/groups/<group_id>/file-source-options
    """

    @bp.route('/api/groups/<group_id>/file-sources', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_file_source_boundary
    def api_scoped_group_file_sources_list(group_id):
        _reject_query_parameters()
        _reject_request_body()
        payload, status = list_group_file_sources(
            get_current_user_id(), group_id, user_info=_current_user_info(),
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/file-sources', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_file_source_boundary
    def api_scoped_group_file_source_create(group_id):
        _reject_query_parameters()
        payload, status = create_group_file_source(
            get_current_user_id(), group_id, _read_json_body(), user_info=_current_user_info(),
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/file-sources/<source_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_file_source_boundary
    def api_scoped_group_file_source_read(group_id, source_id):
        _reject_query_parameters()
        _reject_request_body()
        payload, status = get_group_file_source(
            get_current_user_id(), group_id, source_id, user_info=_current_user_info(),
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/file-sources/<source_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_file_source_boundary
    def api_scoped_group_file_source_update(group_id, source_id):
        _reject_query_parameters()
        payload, status = update_group_file_source(
            get_current_user_id(), group_id, source_id, _read_json_body(), user_info=_current_user_info(),
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/file-sources/<source_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_file_source_boundary
    def api_scoped_group_file_source_delete(group_id, source_id):
        # DELETE carries the JSON body that supplies expected_config_revision and the
        # explicit delete_associated_files choice, so a stale editor cannot delete a
        # source a concurrent manager changed and the associated-file choice is never
        # defaulted.
        _reject_query_parameters()
        payload, status = delete_group_file_source(
            get_current_user_id(), group_id, source_id, _read_json_body(), user_info=_current_user_info(),
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/file-sources/test-connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_file_source_boundary
    def api_scoped_group_file_source_test_new(group_id):
        _reject_query_parameters()
        payload, status = test_group_file_source_connection(
            get_current_user_id(), group_id, _read_json_body(), user_info=_current_user_info(),
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/file-sources/<source_id>/test-connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_file_source_boundary
    def api_scoped_group_file_source_test_saved(group_id, source_id):
        _reject_query_parameters()
        payload, status = test_group_file_source_connection(
            get_current_user_id(), group_id, _read_optional_json_body(), source_id=source_id, user_info=_current_user_info(),
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/file-sources/browse', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_file_source_boundary
    def api_scoped_group_file_source_browse_new(group_id):
        _reject_query_parameters()
        payload, status = browse_group_file_source(
            get_current_user_id(), group_id, _read_json_body(), user_info=_current_user_info(),
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/file-sources/<source_id>/browse', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_file_source_boundary
    def api_scoped_group_file_source_browse_saved(group_id, source_id):
        _reject_query_parameters()
        payload, status = browse_group_file_source(
            get_current_user_id(), group_id, _read_optional_json_body(), source_id=source_id, user_info=_current_user_info(),
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/file-sources/<source_id>/sync', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_file_source_boundary
    def api_scoped_group_file_source_sync(group_id, source_id):
        _reject_query_parameters()
        _reject_request_body()
        payload, status = sync_group_file_source(
            get_current_user_id(), group_id, source_id, user_info=_current_user_info(),
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/file-sources/<source_id>/runs', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_file_source_boundary
    def api_scoped_group_file_source_runs(group_id, source_id):
        _reject_query_parameters()
        _reject_request_body()
        payload, status = list_group_file_source_runs(
            get_current_user_id(), group_id, source_id, user_info=_current_user_info(),
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/file-sources/<source_id>/ignore-path', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_file_source_boundary
    def api_scoped_group_file_source_ignore_path(group_id, source_id):
        _reject_query_parameters()
        payload, status = ignore_group_file_source_path(
            get_current_user_id(), group_id, source_id, _read_json_body(), user_info=_current_user_info(),
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/file-source-options', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_file_source_boundary
    def api_scoped_group_file_source_options(group_id):
        _reject_query_parameters()
        _reject_request_body()
        payload, status = get_group_file_source_options(
            get_current_user_id(), group_id, user_info=_current_user_info(),
        )
        return jsonify(payload), status
