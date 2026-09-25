# route_backend_public_settings.py
"""The native public workspace settings routes.

- ``GET /api/public-workspaces/<workspace_id>/settings`` reads the workspace's settings
  and the ``settings_management`` decision;
- ``PATCH /api/public-workspaces/<workspace_id>/settings/profile`` changes the name,
  description or hero color;
- ``PUT`` and ``DELETE /api/public-workspaces/<workspace_id>/settings/logo`` replace and
  remove the logo;
- ``PATCH /api/public-workspaces/<workspace_id>/settings/downloads`` sets the workspace's
  file download switch;
- ``PATCH /api/public-workspaces/<workspace_id>/settings/retention`` changes its retention
  policy;
- ``GET /api/public-workspaces/<workspace_id>/insights/activity`` and ``/insights/stats``
  read the activity feed and the statistics.

They sit beside the classic ``/api/public_workspaces/<ws_id>`` routes, which are
unchanged. None of these paths matches any other route, so a server without them
answers 404. The rules live in ``functions_public_settings``,
``functions_public_insights`` and ``functions_public_settings_policy``.
"""

from functools import wraps

from functions_authentication import get_current_user_id, login_required, user_required
from functions_public_directory import reject_request_body
from functions_public_insights import read_public_activity, read_public_stats
from functions_public_settings import (
    no_store,
    public_settings_error_response,
    read_public_settings,
    remove_public_logo,
    replace_public_logo,
    update_public_downloads,
    update_public_profile,
    update_public_retention,
)
from functions_settings import enabled_required
from swagger_wrapper import swagger_route, get_auth_security


def _public_settings_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - all mapped to stable HTTP responses
            return public_settings_error_response(error)
    return guarded


def register_route_backend_public_settings(bp):
    """Register the native public workspace settings routes."""

    @bp.route('/api/public-workspaces/<workspace_id>/settings', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_settings_boundary
    def api_public_settings_read(workspace_id):
        """Read the workspace's settings, for the owner or an admin."""
        reject_request_body()
        return no_store(*read_public_settings(get_current_user_id(), workspace_id))

    @bp.route('/api/public-workspaces/<workspace_id>/settings/profile', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_settings_boundary
    def api_public_settings_profile_update(workspace_id):
        """Change ``{revision, name?, description?, hero_color?}``."""
        return no_store(*update_public_profile(get_current_user_id(), workspace_id))

    @bp.route('/api/public-workspaces/<workspace_id>/settings/logo', methods=['PUT'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_settings_boundary
    def api_public_settings_logo_replace(workspace_id):
        """Replace the logo from a multipart ``logo_file`` and ``revision``."""
        return no_store(*replace_public_logo(get_current_user_id(), workspace_id))

    @bp.route('/api/public-workspaces/<workspace_id>/settings/logo', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_settings_boundary
    def api_public_settings_logo_remove(workspace_id):
        """Remove the logo, given ``{revision}``."""
        return no_store(*remove_public_logo(get_current_user_id(), workspace_id))

    @bp.route('/api/public-workspaces/<workspace_id>/settings/downloads', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_settings_boundary
    def api_public_settings_downloads_update(workspace_id):
        """Set ``{revision, disable_file_downloads}``."""
        return no_store(*update_public_downloads(get_current_user_id(), workspace_id))

    @bp.route('/api/public-workspaces/<workspace_id>/settings/retention', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_settings_boundary
    def api_public_settings_retention_update(workspace_id):
        """Merge ``{revision, conversation_retention_days?, document_retention_days?}``."""
        return no_store(*update_public_retention(get_current_user_id(), workspace_id))

    @bp.route('/api/public-workspaces/<workspace_id>/insights/activity', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_settings_boundary
    def api_public_insights_activity(workspace_id):
        """Read the workspace's activity feed: ``limit`` is 10, 20 or 50."""
        reject_request_body()
        return no_store(*read_public_activity(get_current_user_id(), workspace_id))

    @bp.route('/api/public-workspaces/<workspace_id>/insights/stats', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @_public_settings_boundary
    def api_public_insights_stats(workspace_id):
        """Read the workspace's statistics for ``days`` or ``start_date`` and ``end_date``."""
        reject_request_body()
        return no_store(*read_public_stats(get_current_user_id(), workspace_id))
