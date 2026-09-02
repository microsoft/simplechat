# route_backend_v2.py

"""JSON APIs that back the V2 React interface.

The V2 SPA cannot read Jinja template context, so this module exposes the same data the
server-rendered chat page receives as a single bootstrap payload. It deliberately reuses
the catalog builders from ``route_frontend_chats`` rather than reimplementing them, so the
two interfaces cannot drift apart in which models, agents or prompts a user may see.

Two blueprints are registered from here:

``backend_v2``
    login_required + user_required. Serves the bootstrap payload. Settings returned to the
    browser go through ``sanitize_settings_for_user`` first.

``backend_v2_admin``
    login_required + admin_required. Serves and updates the raw settings document for the
    admin surface. Admin settings are intentionally *not* sanitized, because sanitization
    strips the very fields an administrator needs to manage.
"""

import logging

from flask import jsonify, request, session

from admin_settings_nav import ADMIN_NAV
from functions_appinsights import log_event
from functions_authentication import (
    admin_required,
    get_current_user_id,
    get_current_user_info,
    login_required,
    user_required,
)
from functions_conversation_contents import is_conversation_contents_drawer_enabled
from functions_group import find_group_by_id, get_user_groups
from functions_public_workspaces import (
    find_public_workspace_by_id,
    get_user_visible_public_workspace_ids_from_settings,
)
from functions_settings import (
    WEB_SEARCH_USER_NOTICE_DEFAULT_TEXT,
    get_settings,
    get_user_settings,
    is_chat_file_upload_enabled_for_user,
    is_user_workflows_enabled_for_user,
    sanitize_settings_for_user,
    update_settings,
)
from functions_source_review import (
    is_source_review_enabled_for_user,
    is_url_access_enabled_for_user,
)
from route_frontend_chats import (
    _build_chat_model_catalog,
    _build_chat_prompt_catalog,
    _build_initial_chat_model_selection,
    _is_chat_agent_allowed_by_governance,
)
from functions_agent_catalog import build_accessible_agent_catalog
from functions_ai_notice import get_ai_notice_config, is_ai_notice_dismissed
from config import VERSION
from swagger_wrapper import get_auth_security, swagger_route

logger = logging.getLogger(__name__)


def _build_branding(raw_settings, public_settings):
    """Describe branding for the SPA without leaking the encoded logo payloads.

    ``sanitize_settings_for_user`` strips any key containing "base64", which removes the
    logo blobs from public settings. The blobs are not what the browser needs anyway: the
    images are already served as static files, so the URLs are derived here from the raw
    settings and only the URLs are returned.
    """
    show_logo = bool(raw_settings.get("show_logo", False))
    logo_version = raw_settings.get("logo_version") or 1
    logo_dark_version = raw_settings.get("logo_dark_version") or 1

    logo_url = None
    logo_dark_url = None
    if raw_settings.get("custom_logo_base64"):
        logo_url = f"/static/images/custom_logo.png?v={logo_version}"
    if raw_settings.get("custom_logo_dark_base64"):
        logo_dark_url = f"/static/images/custom_logo_dark.png?v={logo_dark_version}"
    elif logo_url:
        # Matches the server-rendered template, which reuses the light logo in dark mode
        # when no dedicated dark variant has been uploaded.
        logo_dark_url = logo_url

    classification_banner = None
    if raw_settings.get("classification_banner_enabled") and raw_settings.get(
        "classification_banner_text"
    ):
        classification_banner = {
            "enabled": True,
            "text": raw_settings.get("classification_banner_text"),
            "color": raw_settings.get("classification_banner_color") or "#ffc107",
            "text_color": raw_settings.get("classification_banner_text_color") or "#ffffff",
        }

    return {
        "app_title": public_settings.get("app_title") or "SimpleChat",
        "hide_app_title": bool(raw_settings.get("hide_app_title", False)),
        "show_logo": show_logo,
        "logo_url": logo_url if show_logo else None,
        "logo_dark_url": logo_dark_url if show_logo else None,
        "classification_banner": classification_banner,
    }


def _build_feature_flags(public_settings, per_user_overrides):
    """Collapse the settings document into the boolean flags the SPA branches on.

    Every ``enable_*`` key is forwarded so a newly added capability shows up in the SPA
    without a change here, and the per-user computed values are layered on top because
    they depend on the caller's roles rather than on global configuration alone.
    """
    features = {
        key: bool(value)
        for key, value in public_settings.items()
        if key.startswith("enable_") and isinstance(value, bool)
    }
    features.update(per_user_overrides)
    return features


def _build_notices(public_settings, user_settings_dict):
    """Describe the administrator-configured notices the chat surface must render.

    Both notices exist in the server-rendered interface, where the AI notice arrives as
    template context and the web search notice as a Jinja condition over three settings
    keys. The SPA can read neither, so they are resolved here rather than in the browser:

    - The AI notice carries a SHA-256 of its message and frequency, and whether the caller
      has already dismissed it depends on a stored, server-timestamped record. Recomputing
      either client-side would let the two interfaces disagree about whether an
      administrator's edit should re-surface a notice somebody had dismissed.
    - The web search notice depends on ``web_search_consent_accepted``, which is not an
      ``enable_*`` key and so never reaches the feature flags the composer branches on.
    """
    ai_notice = get_ai_notice_config(public_settings)
    ai_notice["dismissed"] = is_ai_notice_dismissed(ai_notice, user_settings_dict)

    # All three are required, matching the condition in chats.html: the capability, the
    # administrator's acknowledgement that messages leave the tenant, and the notice itself.
    web_search_notice_enabled = bool(
        public_settings.get("enable_web_search")
        and public_settings.get("web_search_consent_accepted")
        and public_settings.get("enable_web_search_user_notice")
    )
    web_search_notice_text = str(
        public_settings.get("web_search_user_notice_text") or ""
    ).strip()

    return {
        "ai": ai_notice,
        "web_search": {
            "enabled": web_search_notice_enabled,
            "text": web_search_notice_text or WEB_SEARCH_USER_NOTICE_DEFAULT_TEXT,
        },
    }


def register_route_backend_v2(bp):
    @bp.route("/api/v2/bootstrap", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def v2_bootstrap():
        """Return everything the V2 SPA needs for its first paint.

        Mirrors the template context that ``route_frontend_chats.chats`` passes to
        chats.html, so the two front ends agree on catalogs, scope and feature flags.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        try:
            settings = get_settings()
            public_settings = sanitize_settings_for_user(settings)

            user_settings = get_user_settings(user_id)
            user_settings_dict = (
                user_settings.get("settings", {}) if isinstance(user_settings, dict) else {}
            )
            current_user_info = get_current_user_info() or {}
            session_user = session.get("user") or {}
            current_user_roles = session_user.get("roles", []) or []

            per_user_overrides = {
                "enable_chat_file_uploads": is_chat_file_upload_enabled_for_user(
                    settings, current_user_roles
                ),
                "allow_user_workflows": is_user_workflows_enabled_for_user(
                    settings, user_roles=current_user_roles
                ),
                "enable_source_review": is_source_review_enabled_for_user(
                    settings,
                    user_id,
                    user_email=current_user_info.get("email"),
                    user_roles=current_user_roles,
                ),
                "enable_url_access": is_url_access_enabled_for_user(
                    settings, user_roles=current_user_roles
                ),
                "enable_conversation_contents_drawer": is_conversation_contents_drawer_enabled(
                    public_settings, user_settings_dict
                ),
            }

            user_groups_raw = []
            groups = []
            try:
                user_groups_raw = get_user_groups(user_id) or []
                groups = [
                    {"id": group["id"], "name": group.get("name", "Unnamed")}
                    for group in user_groups_raw
                ]
            except Exception as exc:
                logger.warning(f"[V2_BOOTSTRAP] Failed to load user groups: {exc}")

            public_workspaces = []
            try:
                for workspace_id in get_user_visible_public_workspace_ids_from_settings(user_id):
                    workspace_doc = find_public_workspace_by_id(workspace_id)
                    if workspace_doc:
                        public_workspaces.append(
                            {"id": workspace_id, "name": workspace_doc.get("name", "Unknown")}
                        )
            except Exception as exc:
                logger.warning(f"[V2_BOOTSTRAP] Failed to load public workspaces: {exc}")

            agents = []
            try:
                agents = [
                    agent
                    for agent in build_accessible_agent_catalog(
                        user_id, settings=settings, user_groups=user_groups_raw
                    )
                    if _is_chat_agent_allowed_by_governance(
                        user_id,
                        agent,
                        str(agent.get("scope_type") or "").strip().lower() or "personal",
                    )
                ]
            except Exception as exc:
                logger.warning(f"[V2_BOOTSTRAP] Failed to load agent catalog: {exc}")

            models = []
            try:
                models = _build_chat_model_catalog(
                    user_id=user_id,
                    settings=settings,
                    user_settings_dict=user_settings_dict,
                    user_groups_raw=user_groups_raw,
                )
            except Exception as exc:
                logger.warning(f"[V2_BOOTSTRAP] Failed to load model catalog: {exc}")

            prompts = []
            try:
                prompts = _build_chat_prompt_catalog(
                    user_id=user_id,
                    settings=settings,
                    user_groups_raw=user_groups_raw,
                    user_visible_public_workspaces=public_workspaces,
                )
            except Exception as exc:
                logger.warning(f"[V2_BOOTSTRAP] Failed to load prompt catalog: {exc}")

            initial_model_selection = None
            try:
                initial_model_selection = _build_initial_chat_model_selection(
                    chat_model_options=models,
                    preferred_model_id=user_settings_dict.get("preferredModelId"),
                    preferred_model_deployment=user_settings_dict.get(
                        "preferredModelDeployment"
                    ),
                )
            except Exception as exc:
                logger.warning(f"[V2_BOOTSTRAP] Failed to resolve initial model: {exc}")

            # The stored active scope is only a UI preference, so it is reported back
            # rather than used to authorize anything here: the chat endpoints re-derive and
            # authorize scope on every request via _get_authorized_chat_scope_context.
            #
            # It is still validated against the caller's own authorized lists, because a
            # group or workspace can be revoked after the preference was saved and echoing
            # a stale id would show the user a scope badge they no longer have access to.
            # bac-check: ignore - preference read, filtered against the caller's authorized
            # group and workspace lists below; not used for an authorization decision.
            stored_group_id = user_settings_dict.get("activeGroupOid", "") or None
            # bac-check: ignore - preference read, filtered against the caller's visible
            # public workspace list below; not used for an authorization decision.
            stored_workspace_id = user_settings_dict.get("activePublicWorkspaceOid", "") or None

            authorized_group_ids = {group["id"] for group in groups}
            active_group_id = stored_group_id if stored_group_id in authorized_group_ids else None
            active_group_name = None
            if active_group_id:
                group_doc = find_group_by_id(active_group_id)
                if group_doc:
                    active_group_name = group_doc.get("name", "")

            visible_workspace_ids = {workspace["id"] for workspace in public_workspaces}
            active_public_workspace_id = (
                stored_workspace_id if stored_workspace_id in visible_workspace_ids else None
            )

            payload = {
                "version": VERSION,
                "user": {
                    "id": user_id,
                    "display_name": (
                        (user_settings or {}).get("display_name")
                        or current_user_info.get("displayName")
                        or ""
                    ),
                    "email": current_user_info.get("email"),
                    "is_admin": "Admin" in current_user_roles,
                    "roles": list(current_user_roles),
                },
                "branding": _build_branding(settings, public_settings),
                "features": _build_feature_flags(public_settings, per_user_overrides),
                "catalogs": {
                    "models": models,
                    "agents": agents,
                    "prompts": prompts,
                    "initial_model_selection": initial_model_selection,
                },
                "scope": {
                    "active_group_id": active_group_id,
                    "active_group_name": active_group_name,
                    "active_public_workspace_id": active_public_workspace_id,
                    "groups": groups,
                    "public_workspaces": public_workspaces,
                },
                "admin_nav": ADMIN_NAV if "Admin" in current_user_roles else [],
                "notices": _build_notices(public_settings, user_settings_dict),
                "settings": public_settings,
            }

            return jsonify(payload), 200
        except Exception as exc:
            log_event(
                f"[V2_BOOTSTRAP] Failed to build bootstrap payload: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"error": "Failed to load application bootstrap"}), 500


def register_route_backend_v2_admin(bp):
    @bp.route("/api/v2/admin/settings", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def v2_admin_get_settings():
        """Return the raw settings document plus the admin navigation structure.

        Admin settings are not sanitized. Sanitization removes keys, secrets and endpoint
        configuration, which are exactly the values an administrator is here to manage.
        Access is restricted to the Admin role by the blueprint guard and the decorator.
        """
        try:
            return (
                jsonify(
                    {
                        "settings": get_settings(),
                        "admin_nav": ADMIN_NAV,
                        "version": VERSION,
                    }
                ),
                200,
            )
        except Exception as exc:
            log_event(
                f"[V2_ADMIN_SETTINGS] Failed to load settings: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"error": "Failed to load settings"}), 500

    @bp.route("/api/v2/admin/settings", methods=["PATCH"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def v2_admin_patch_settings():
        """Apply a partial settings update.

        The V2 admin surface edits individual capabilities rather than posting the whole
        settings form, so only the supplied keys are forwarded to ``update_settings``.
        """
        payload = request.get_json(silent=True) or {}
        updates = payload.get("settings")

        if not isinstance(updates, dict) or not updates:
            return jsonify({"error": "No settings supplied"}), 400

        try:
            update_settings(updates)
            log_event(
                f"[V2_ADMIN_SETTINGS] Updated {len(updates)} setting(s): "
                f"{', '.join(sorted(updates.keys()))}",
                level=logging.INFO,
            )
            return jsonify({"success": True, "updated_keys": sorted(updates.keys())}), 200
        except Exception as exc:
            log_event(
                f"[V2_ADMIN_SETTINGS] Failed to update settings: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"error": "Failed to update settings"}), 500
