# route_backend_group_settings.py
"""The native group settings and insights routes.

- ``GET /api/groups/<group_id>/settings`` reads the group's settings and the
  ``settings_management`` decision;
- ``PATCH /api/groups/<group_id>/settings/profile`` changes the name, description or
  hero color;
- ``PUT`` and ``DELETE /api/groups/<group_id>/settings/logo`` replace and remove the
  logo;
- ``PATCH /api/groups/<group_id>/settings/downloads`` sets the group's file download
  switch;
- ``PATCH /api/groups/<group_id>/settings/retention`` changes its retention policy;
- ``GET /api/groups/<group_id>/insights/activity``, ``/insights/stats`` and
  ``/insights/file-count`` read the activity feed, the statistics and the count of
  the group's current documents.

They sit beside the classic ``/api/groups/<group_id>`` routes, which are unchanged.
None of these paths matches any other route, so a server without them answers 404.
The rules live in ``functions_group_settings``, ``functions_group_insights`` and
``functions_group_settings_policy``.
"""

from functools import wraps

from functions_authentication import get_current_user_id, login_required, user_required
from functions_group_insights import read_group_activity, read_group_file_count, read_group_stats
from functions_group_directory import reject_request_body
from functions_group_settings import (
    group_settings_error_response,
    no_store,
    read_group_settings,
    remove_group_logo,
    replace_group_logo,
    update_group_downloads,
    update_group_profile,
    update_group_retention,
)
from functions_settings import enabled_required
from swagger_wrapper import swagger_route, get_auth_security


def _group_settings_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - all mapped to stable HTTP responses
            return group_settings_error_response(error)
    return guarded


def register_route_backend_group_settings(bp):
    """Register the native group settings and insights routes."""

    @bp.route('/api/groups/<group_id>/settings', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_settings_boundary
    def api_group_settings_read(group_id):
        """Read the group's settings, for the owner or an admin."""
        reject_request_body()
        return no_store(*read_group_settings(get_current_user_id(), group_id))

    @bp.route('/api/groups/<group_id>/settings/profile', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_settings_boundary
    def api_group_settings_profile_update(group_id):
        """Change ``{revision, name?, description?, hero_color?}``."""
        return no_store(*update_group_profile(get_current_user_id(), group_id))

    @bp.route('/api/groups/<group_id>/settings/logo', methods=['PUT'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_settings_boundary
    def api_group_settings_logo_replace(group_id):
        """Replace the logo from a multipart ``logo_file`` and ``revision``."""
        return no_store(*replace_group_logo(get_current_user_id(), group_id))

    @bp.route('/api/groups/<group_id>/settings/logo', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_settings_boundary
    def api_group_settings_logo_remove(group_id):
        """Remove the logo, given ``{revision}``."""
        return no_store(*remove_group_logo(get_current_user_id(), group_id))

    @bp.route('/api/groups/<group_id>/settings/downloads', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_settings_boundary
    def api_group_settings_downloads_update(group_id):
        """Set ``{revision, disable_file_downloads}``."""
        return no_store(*update_group_downloads(get_current_user_id(), group_id))

    @bp.route('/api/groups/<group_id>/settings/retention', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_settings_boundary
    def api_group_settings_retention_update(group_id):
        """Merge ``{revision, conversation_retention_days?, document_retention_days?}``."""
        return no_store(*update_group_retention(get_current_user_id(), group_id))

    @bp.route('/api/groups/<group_id>/insights/activity', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_settings_boundary
    def api_group_insights_activity(group_id):
        """Read the group's activity feed: ``limit`` is 10, 20 or 50."""
        reject_request_body()
        return no_store(*read_group_activity(get_current_user_id(), group_id))

    @bp.route('/api/groups/<group_id>/insights/stats', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_settings_boundary
    def api_group_insights_stats(group_id):
        """Read the group's statistics for ``days`` or ``start_date`` and ``end_date``."""
        reject_request_body()
        return no_store(*read_group_stats(get_current_user_id(), group_id))

    @bp.route('/api/groups/<group_id>/insights/file-count', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_settings_boundary
    def api_group_insights_file_count(group_id):
        """Count the group's current documents, for the owner."""
        reject_request_body()
        return no_store(*read_group_file_count(get_current_user_id(), group_id))
