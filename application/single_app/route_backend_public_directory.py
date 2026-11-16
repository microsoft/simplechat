# route_backend_public_directory.py
"""The native public workspace directory route.

- ``GET /api/public_workspaces/directory`` lists every public workspace the caller
  may discover, paged and searched, with the caller's role in each and the
  ``public_directory`` hint.

It sits beside the classic ``GET /api/public_workspaces`` and
``GET /api/public_workspaces/discover``, which are unchanged. The directory shares
its shape with the classic ``GET /api/public_workspaces/<ws_id>``: GET reaches this
route because a static segment outranks a converter, and PATCH, PUT and DELETE still
reach the classic workspace routes with the id ``directory``. Those refuse the
request, with 404 because no workspace has the id ``directory`` (``create_public_workspace``
mints UUIDs). An older server without this route answers GET with that same classic
details route, which is a 404 for that id.

The rules live in ``functions_public_directory``.
"""

from functools import wraps

from flask import jsonify

from functions_authentication import get_current_user_id, login_required, user_required
from functions_public_directory import (
    list_public_directory,
    public_directory_error_response,
    read_public_directory_query,
    reject_request_body,
)
from functions_settings import enabled_required
from swagger_wrapper import swagger_route, get_auth_security


def _public_directory_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - all mapped to stable HTTP responses
            return public_directory_error_response(error)
    return guarded


def _no_store(payload, status):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


def register_route_backend_public_directory(bp):
    """Register the native public workspace directory route."""

    @bp.route('/api/public_workspaces/directory', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_directory_boundary
    def api_public_directory_list():
        """List the public workspace directory: ``search``, ``view``, ``page`` and ``page_size``."""
        query = read_public_directory_query()
        reject_request_body()
        return _no_store(*list_public_directory(get_current_user_id(), **query))
