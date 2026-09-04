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

from flask import current_app, jsonify, request, session

from admin_settings_fields import (
    LANDING_PAGE_ALIGNMENTS,
    LOGO_SCALE_DEFAULT_PERCENT,
    LOGO_SCALE_MAX_PERCENT,
    LOGO_SCALE_MIN_PERCENT,
    get_admin_settings_fields,
    get_suppressed_capability_keys,
    is_safe_external_link_url,
    normalize_admin_settings_updates,
)
from admin_settings_nav import ADMIN_NAV
from config import (
    ensure_custom_favicon_file_exists,
    ensure_custom_logo_file_exists,
)
from functions_appinsights import log_event
from functions_branding_images import (
    ALLOWED_FAVICON_EXTENSIONS,
    ALLOWED_LOGO_EXTENSIONS,
    is_allowed_branding_image_filename,
    prepare_favicon_image_for_storage,
    prepare_logo_image_for_storage,
)
from functions_branding_urls import (
    FAVICON_STATIC_URL,
    LOGO_DARK_STATIC_URL,
    LOGO_STATIC_URL,
    build_custom_logo_urls,
    build_favicon_url,
)
from functions_authentication import (
    admin_required,
    get_current_user_id,
    get_current_user_info,
    login_required,
    user_required,
)
from functions_conversation_contents import is_conversation_contents_drawer_enabled
from functions_custom_pages import get_custom_pages_nav
from functions_group import find_group_by_id, get_user_groups
from functions_image_edit import resolve_image_edit_capability
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
    redact_admin_settings_secrets_for_form,
    sanitize_model_endpoints_for_frontend,
    sanitize_settings_for_user,
    update_settings,
)
from functions_source_review import (
    is_source_review_enabled_for_user,
    is_url_access_enabled_for_user,
)
from functions_workspace_sections import build_workspace_section_availability
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


# Describes each branding asset an administrator can replace: how to convert the
# upload, which settings keys hold it, and the static path it is written to. The
# paths come from ``functions_branding_urls``, which is also what the bootstrap
# payload and the SPA shell read, so a change there cannot leave one surface
# pointing at a file another no longer writes.
BRANDING_IMAGE_TARGETS = {
    "logo": {
        "settings_key": "custom_logo_base64",
        "version_key": "logo_version",
        "static_url": LOGO_STATIC_URL,
        "extensions": ALLOWED_LOGO_EXTENSIONS,
        "prepare": prepare_logo_image_for_storage,
    },
    "logo_dark": {
        "settings_key": "custom_logo_dark_base64",
        "version_key": "logo_dark_version",
        "static_url": LOGO_DARK_STATIC_URL,
        "extensions": ALLOWED_LOGO_EXTENSIONS,
        "prepare": prepare_logo_image_for_storage,
    },
    "favicon": {
        "settings_key": "custom_favicon_base64",
        "version_key": "favicon_version",
        "static_url": FAVICON_STATIC_URL,
        "extensions": ALLOWED_FAVICON_EXTENSIONS,
        "prepare": prepare_favicon_image_for_storage,
    },
}


def _build_branding_assets(settings):
    """Describe the stored branding images without returning the encoded blobs.

    The admin surface needs to show which assets exist and render a preview of
    each. The base64 payloads are large and already served as static files, so
    only presence, version and URL are returned.
    """
    assets = {}
    for target, spec in BRANDING_IMAGE_TARGETS.items():
        version = settings.get(spec["version_key"]) or 1
        has_asset = bool(settings.get(spec["settings_key"]))
        assets[target] = {
            "present": has_asset,
            "version": version,
            "url": f"{spec['static_url']}?v={version}" if has_asset else None,
        }
    return assets


def _refresh_branding_static_files():
    """Rewrite the logo and favicon static files from the stored settings.

    The files are generated from the settings document rather than uploaded to
    disk directly, so any save that could have changed them has to regenerate
    them or the browser keeps being served the previous image.
    """
    try:
        refreshed_settings = get_settings()
        if not refreshed_settings:
            return
        ensure_custom_logo_file_exists(current_app, refreshed_settings)
        ensure_custom_favicon_file_exists(current_app, refreshed_settings)
    except Exception as exc:
        # A stale static file is a cosmetic problem; it must not turn a saved
        # settings change into a failed request.
        log_event(
            f"[V2_ADMIN_SETTINGS] Could not refresh branding static files: {exc}",
            level=logging.WARNING,
            exceptionTraceback=True,
        )


def _build_branding(raw_settings, public_settings):
    """Describe branding for the SPA without leaking the encoded logo payloads.

    ``sanitize_settings_for_user`` strips any key containing "base64", which removes the
    logo blobs from public settings. The blobs are not what the browser needs anyway: the
    images are already served as static files, so the URLs are derived here from the raw
    settings and only the URLs are returned.

    The landing page fields ride along because the SPA renders its own home page and would
    otherwise need a second request for three values it needs on first paint.
    """
    show_logo = bool(raw_settings.get("show_logo", False))
    logo_url, logo_dark_url = build_custom_logo_urls(raw_settings)

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

    landing_alignment = raw_settings.get("landing_page_alignment") or "left"
    if landing_alignment not in LANDING_PAGE_ALIGNMENTS:
        landing_alignment = "left"

    return {
        "app_title": public_settings.get("app_title") or "SimpleChat",
        "hide_app_title": bool(raw_settings.get("hide_app_title", False)),
        "show_logo": show_logo,
        "logo_url": logo_url if show_logo else None,
        "logo_dark_url": logo_dark_url if show_logo else None,
        "favicon_url": build_favicon_url(raw_settings),
        "classification_banner": classification_banner,
        # Passed through as stored apart from trimming, including when that leaves it
        # empty. ``get_settings`` merges the seeded default into every document, so a
        # blank value is an administrator's deletion, and substituting default copy would
        # put wording they removed -- including an acceptable-use statement -- back on
        # the page.
        "landing_page_text": str(raw_settings.get("landing_page_text") or "").strip(),
        "landing_page_alignment": landing_alignment,
        "landing_page_logo_scale_percent": _coerce_logo_scale(
            raw_settings.get("landing_page_logo_scale_percent")
        ),
    }


def _coerce_logo_scale(value):
    """Clamp the stored home page logo scale into the range the slider offers."""
    try:
        scale = int(float(value))
    except (TypeError, ValueError):
        return LOGO_SCALE_DEFAULT_PERCENT
    return max(LOGO_SCALE_MIN_PERCENT, min(LOGO_SCALE_MAX_PERCENT, scale))


def _menu_name(value, fallback):
    """Return a navigation group's heading, falling back when it is blank.

    ``fallback_when_empty`` in the field schema already restores the default on save, but
    a settings document written before that rule existed can still hold an empty string,
    and an unlabelled group in the rail is worse than a defaulted one.
    """
    return str(value or "").strip() or fallback


def _build_navigation(raw_settings, user_roles):
    """Describe the administrator-configured navigation entries for the SPA.

    Both groups exist in the server-rendered interface, where custom pages arrive as
    template context built in ``app.py`` and external links are read straight off
    ``app_settings`` in ``_sidebar_nav.html``. Neither is reachable from the SPA, and
    neither can be derived from the feature flags: custom pages are filtered per page
    against the caller's roles, and the external link list is not an ``enable_*`` key.

    ``menu_name`` and ``force_menu`` travel with each group so the browser can apply the
    same "inline below three, menu at three or more" rule the templates use.
    """
    custom_pages = []
    if raw_settings.get("enable_custom_pages"):
        try:
            for page in get_custom_pages_nav(raw_settings):
                url = page.get("url") or page.get("href")
                if not page.get("slug") or not url:
                    continue
                custom_pages.append(
                    {
                        "slug": page["slug"],
                        "label": page.get("label") or page["slug"],
                        "icon": page.get("icon") or "bi-file-earmark-text",
                        "url": url,
                        "open_in_new_tab": bool(page.get("open_in_new_tab", False)),
                    }
                )
        except Exception as exc:
            # A missing navigation group is a degraded rail, not a broken app, so it
            # must not take the whole bootstrap payload down with it.
            log_event(
                f"[V2_BOOTSTRAP] Could not resolve custom page navigation: {exc}",
                level=logging.WARNING,
                exceptionTraceback=True,
            )
            custom_pages = []

    # Matches the role gate in _sidebar_nav.html: external links are shown to signed-in
    # users holding a real application role, not to anyone who merely has a session.
    may_see_external_links = any(role in ("Admin", "User") for role in user_roles or [])
    external_links = []
    if raw_settings.get("enable_external_links") and may_see_external_links:
        for link in raw_settings.get("external_links") or []:
            if not isinstance(link, dict):
                continue
            url = str(link.get("url") or "").strip()
            label = str(link.get("label") or "").strip()
            if not url or not label:
                continue
            # Re-checked on the way out, not just on the way in. The V2 settings PATCH
            # is the only write path that applies the scheme rule, so a link stored
            # through the server-rendered admin form, or already in the document, could
            # otherwise put a javascript: URL into every user's navigation.
            if not is_safe_external_link_url(url):
                log_event(
                    "[V2_BOOTSTRAP] Dropped an external link with an unsupported URL "
                    f"scheme: {label}",
                    level=logging.WARNING,
                )
                continue
            external_links.append({"label": label, "url": url})

    return {
        "custom_pages": {
            "enabled": bool(raw_settings.get("enable_custom_pages")),
            "menu_name": _menu_name(
                raw_settings.get("custom_pages_menu_name"), "Custom Pages"
            ),
            "force_menu": bool(raw_settings.get("custom_pages_force_menu")),
            "items": custom_pages,
        },
        "external_links": {
            "enabled": bool(raw_settings.get("enable_external_links")),
            "menu_name": _menu_name(
                raw_settings.get("external_links_menu_name"), "External Links"
            ),
            "force_menu": bool(raw_settings.get("external_links_force_menu")),
            "items": external_links,
        },
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


def _build_capabilities(settings):
    """Describe what the deployment can do, where the answer is not a settings flag.

    ``features`` above forwards every ``enable_*`` boolean, which is the right shape for a
    capability an administrator switches on. Some capabilities are not switches: whether an
    image can have part of it changed depends on which model the selected deployment runs and
    which API version is configured, and neither is a boolean anyone set.

    Naming one of these ``enable_something`` to smuggle it into ``features`` would make it look
    like a settings key to everything that reads the application's surface, including the
    documentation inventory. It is reported separately instead.

    Computed from the raw settings and reduced to an enum, so no deployment detail beyond the
    model's name reaches the browser.
    """
    capability = resolve_image_edit_capability(settings)
    return {
        "image_edit": {
            "mode": capability["mode"],
            "model_name": capability["model_name"],
            "reason": capability["reason"],
        },
    }


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

            # Which workspace sections this user may see. Computed server-side because the
            # answer combines settings, app-role checks and governance policy, and only
            # `enable_*` keys reach `features` above -- `allow_user_agents`,
            # `allow_user_plugins`, `per_user_semantic_kernel` and the file sync and
            # governance checks would all be invisible to the SPA otherwise.
            workspace = {"enabled": False, "sections": {}}
            try:
                workspace = build_workspace_section_availability(
                    settings,
                    user_id,
                    user_info=current_user_info,
                    user_roles=current_user_roles,
                )
            except Exception as exc:
                logger.warning(f"[V2_BOOTSTRAP] Failed to resolve workspace sections: {exc}")

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
                "navigation": _build_navigation(settings, current_user_roles),
                "features": _build_feature_flags(public_settings, per_user_overrides),
                "capabilities": _build_capabilities(settings),
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
                "workspace": workspace,
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
        """Return the settings document, the admin navigation and the field schema.

        Admin settings are not run through ``sanitize_settings_for_user``. That removes
        keys and endpoint configuration outright, which are exactly the values an
        administrator is here to manage. Access is restricted to the Admin role by the
        blueprint guard and the decorator.

        Stored secrets are masked all the same, using the same helpers the
        server-rendered form uses. An administrator needs to know a credential is
        configured and be able to replace it, not to read it back, and the settings
        PATCH resolves the mask to the stored value so an untouched field round-trips
        intact. Model endpoint credentials are nested inside the ``model_endpoints``
        list rather than at a fixed key, so they are stripped by
        ``sanitize_model_endpoints_for_frontend`` first, matching what the
        server-rendered page passes to its template.

        ``field_schema`` describes the concrete controls each section owns. Sections with
        no entry are rendered by the SPA's ``enable_*`` fallback scan, so groups that have
        not been described yet keep working. ``suppressed_capabilities`` names the keys
        that scan must skip because they are derived or are staged rollout flags with no
        administrator control.
        """
        try:
            settings = get_settings()
            safe_settings = redact_admin_settings_secrets_for_form(settings)
            safe_settings["model_endpoints"] = sanitize_model_endpoints_for_frontend(
                settings.get("model_endpoints")
            )
            return (
                jsonify(
                    {
                        "settings": safe_settings,
                        "admin_nav": ADMIN_NAV,
                        "field_schema": get_admin_settings_fields(),
                        "branding_assets": _build_branding_assets(settings),
                        "suppressed_capabilities": get_suppressed_capability_keys(),
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

        The V2 admin surface edits a section at a time rather than posting the whole
        settings form, so only the supplied keys are forwarded to ``update_settings``.

        Values are normalized against the field schema first, which is what keeps the two
        admin interfaces agreeing on what a valid value is. The update is applied only if
        every supplied key validates, so a save never lands half-applied.
        """
        payload = request.get_json(silent=True) or {}
        updates = payload.get("settings")

        if not isinstance(updates, dict) or not updates:
            return jsonify({"error": "No settings supplied"}), 400

        try:
            current_settings = get_settings()
            normalized, errors, warnings = normalize_admin_settings_updates(
                updates, current_settings
            )

            if errors:
                log_event(
                    f"[V2_ADMIN_SETTINGS] Rejected update for "
                    f"{', '.join(sorted(errors.keys()))}",
                    level=logging.WARNING,
                )
                return (
                    jsonify(
                        {
                            "error": "Some settings could not be saved.",
                            "field_errors": errors,
                        }
                    ),
                    400,
                )

            if not normalized:
                return jsonify({"error": "No settings supplied"}), 400

            update_settings(normalized)
            log_event(
                f"[V2_ADMIN_SETTINGS] Updated {len(normalized)} setting(s): "
                f"{', '.join(sorted(normalized.keys()))}",
                level=logging.INFO,
            )

            # Logo scale and title changes are read from the settings document on the
            # next request, but the favicon and logo static files are written from it, so
            # a branding change has to refresh them.
            _refresh_branding_static_files()

            return (
                jsonify(
                    {
                        "success": True,
                        "updated_keys": sorted(normalized.keys()),
                        # Re-mask before echoing. A secret field resolves the mask back to
                        # the stored credential, so returning `normalized` unchanged would
                        # hand the browser the very value the GET withholds.
                        "settings": redact_admin_settings_secrets_for_form(normalized),
                        "warnings": warnings,
                    }
                ),
                200,
            )
        except Exception as exc:
            log_event(
                f"[V2_ADMIN_SETTINGS] Failed to update settings: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"error": "Failed to update settings"}), 500

    @bp.route("/api/v2/admin/settings/branding-image", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def v2_admin_upload_branding_image():
        """Store an uploaded logo or favicon and return its new static URL.

        Branding images cannot travel through the JSON settings PATCH, so they get their
        own multipart endpoint. The conversion is the shared one in
        ``functions_branding_images``, so an asset uploaded here is byte-for-byte what the
        server-rendered form would have stored.

        The version counter is bumped on every successful upload because the static file
        keeps a stable name; without the counter, browsers would keep serving the previous
        image from cache.
        """
        target = str(request.form.get("target") or "").strip().lower()
        spec = BRANDING_IMAGE_TARGETS.get(target)
        if not spec:
            return (
                jsonify(
                    {
                        "error": "Unsupported branding image target. Expected one of: "
                        f"{', '.join(sorted(BRANDING_IMAGE_TARGETS))}."
                    }
                ),
                400,
            )

        upload = request.files.get("file")
        if not upload or not upload.filename:
            return jsonify({"error": "No file was supplied."}), 400

        if not is_allowed_branding_image_filename(upload.filename, spec["extensions"]):
            return (
                jsonify(
                    {
                        "error": "Unsupported file type. Allowed extensions: "
                        f"{', '.join(sorted(spec['extensions']))}."
                    }
                ),
                400,
            )

        try:
            file_bytes = upload.read()
            processed = spec["prepare"](file_bytes, upload.filename)
        except Exception as exc:
            # A decode failure is administrator error, not a server fault, and the
            # existing asset must survive it.
            log_event(
                f"[V2_ADMIN_SETTINGS] Rejected {target} upload: {exc}",
                level=logging.WARNING,
            )
            return (
                jsonify({"error": f"That image could not be processed: {exc}"}),
                400,
            )

        try:
            settings = get_settings()
            next_version = int(settings.get(spec["version_key"], 1) or 1) + 1

            update_settings(
                {
                    spec["settings_key"]: processed["base64_str"],
                    spec["version_key"]: next_version,
                }
            )
            _refresh_branding_static_files()

            log_event(
                f"[V2_ADMIN_SETTINGS] Stored {target} image "
                f"({processed['detected_format']}, {processed['original_size']} -> "
                f"{processed['stored_size']}, version {next_version})",
                level=logging.INFO,
            )

            return (
                jsonify(
                    {
                        "success": True,
                        "target": target,
                        "url": f"{spec['static_url']}?v={next_version}",
                        "version": next_version,
                        "stored_size": list(processed["stored_size"]),
                    }
                ),
                200,
            )
        except Exception as exc:
            log_event(
                f"[V2_ADMIN_SETTINGS] Failed to store {target} image: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"error": "Failed to store the uploaded image"}), 500
