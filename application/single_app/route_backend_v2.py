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
import uuid

from flask import current_app, jsonify, request, session

from admin_app_roles import get_app_role_requirements
from admin_settings_fields import (
    LANDING_PAGE_ALIGNMENTS,
    LOGO_SCALE_DEFAULT_PERCENT,
    LOGO_SCALE_MAX_PERCENT,
    LOGO_SCALE_MIN_PERCENT,
    SECRET_REDACTED_VALUE,
    get_admin_section_status,
    get_admin_settings_fields,
    get_secret_field_keys,
    get_secret_storage_paths,
    get_suppressed_capability_keys,
    is_safe_external_link_url,
    normalize_admin_settings_updates,
    read_nested_setting,
    write_nested_setting,
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
from functions_group import (
    GROUP_DIRECTORY_DEFAULT_LIMIT,
    GROUP_DIRECTORY_MAX_LIMIT,
    find_group_by_id,
    find_groups_by_ids,
    get_user_groups,
    list_groups_for_admin_directory,
)
from functions_group_assignment_ids import normalize_group_workflow_allowed_group_ids
from functions_image_edit import resolve_image_edit_capability
from functions_public_workspaces import (
    find_public_workspace_by_id,
    get_user_visible_public_workspace_ids_from_settings,
)
from functions_settings import (
    ADMIN_SETTINGS_SECRET_REDACTED_VALUE,
    WEB_SEARCH_USER_NOTICE_DEFAULT_TEXT,
    build_migrated_model_endpoints_from_legacy,
    get_admin_settings_api_secret_fields,
    get_settings,
    get_user_settings,
    is_chat_file_upload_enabled_for_user,
    is_user_workflows_enabled_for_user,
    merge_model_endpoint_payload,
    normalize_model_endpoints,
    redact_admin_settings_secrets_for_api,
    redact_admin_settings_secrets_for_form,
    resolve_admin_settings_secret_value,
    resolve_default_model_selection,
    resolve_metadata_extraction_model_selection,
    sanitize_settings_for_user,
    sanitize_model_endpoints_for_frontend,
    update_settings,
)
from functions_keyvault import (
    keyvault_model_endpoint_cleanup_helper,
    keyvault_model_endpoint_delete_helper,
    keyvault_model_endpoint_save_helper,
)
from functions_source_review import (
    get_source_review_runtime_capabilities,
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
# Shared with the server-rendered admin page so both interfaces run the same
# connection tests rather than maintaining two lists of what can be tested.
from route_backend_settings import run_admin_settings_connection_test
from functions_agent_catalog import build_accessible_agent_catalog
from functions_ai_notice import get_ai_notice_config, is_ai_notice_dismissed
from functions_model_capabilities import resolve_model_vision_support
from functions_documents import get_audio_runtime_capabilities
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


def _load_global_model_endpoints(settings=None):
    """Read the stored global model endpoints as a list."""
    source = settings if isinstance(settings, dict) else get_settings()
    endpoints = source.get("model_endpoints", [])
    return endpoints if isinstance(endpoints, list) else []


def _find_model_endpoint(endpoints, endpoint_id):
    """Return the endpoint with the given id, or None."""
    reference = str(endpoint_id or "")
    for endpoint in endpoints:
        if isinstance(endpoint, dict) and str(endpoint.get("id") or "") == reference:
            return endpoint
    return None


def _model_endpoint_response(saved_endpoints, endpoint_id, status):
    """Return one saved endpoint, sanitized, as the response to a write."""
    saved = _find_model_endpoint(saved_endpoints, endpoint_id)
    sanitized = sanitize_model_endpoints_for_frontend([saved]) if saved else []
    return jsonify({"endpoint": sanitized[0] if sanitized else {}}), status


def _persist_global_model_endpoints(normalized, existing):
    """Save the global endpoint list, moving Key Vault secrets to match.

    Secrets need three passes because every endpoint can carry them: endpoints being
    saved write theirs, endpoints whose auth changed have the superseded secret cleaned
    up, and endpoints that are gone have theirs deleted. Without the last pass a delete
    would leave an orphaned secret in the vault forever.

    This mirrors what the classic admin form does on submit, so an endpoint saved from
    either interface ends up stored identically.
    """
    existing_by_id = {
        endpoint.get("id"): endpoint
        for endpoint in existing
        if isinstance(endpoint, dict) and endpoint.get("id")
    }

    saved_endpoints = [
        keyvault_model_endpoint_save_helper(
            endpoint,
            endpoint.get("id"),
            scope="global",
            existing_endpoint=existing_by_id.get(endpoint.get("id")),
        )
        for endpoint in normalized
    ]

    for endpoint in saved_endpoints:
        if not isinstance(endpoint, dict):
            continue
        endpoint_id = endpoint.get("id")
        if not endpoint_id:
            continue
        keyvault_model_endpoint_cleanup_helper(
            existing_by_id.get(endpoint_id),
            endpoint,
            endpoint_id,
            scope="global",
        )

    saved_endpoint_ids = {
        endpoint.get("id")
        for endpoint in saved_endpoints
        if isinstance(endpoint, dict) and endpoint.get("id")
    }
    for endpoint in existing:
        if not isinstance(endpoint, dict):
            continue
        endpoint_id = endpoint.get("id")
        if endpoint_id and endpoint_id not in saved_endpoint_ids:
            keyvault_model_endpoint_delete_helper(endpoint, endpoint_id, scope="global")

    settings = get_settings()
    updates = {"model_endpoints": saved_endpoints}
    multi_endpoint_enabled = bool(settings.get("enable_multi_model_endpoints", False))

    # Both stored selections name an endpoint and a model by id, so deleting or disabling
    # either leaves them pointing at nothing. A dangling default makes chat fall back
    # quietly; a dangling metadata extraction selection makes document ingestion raise,
    # and its caller only logs that. Neither is acceptable, so both are re-resolved against
    # what was actually saved.
    resolved_default, _ = resolve_default_model_selection(
        settings.get("default_model_selection"),
        saved_endpoints,
        multi_endpoint_enabled=multi_endpoint_enabled,
    )
    if resolved_default != settings.get("default_model_selection"):
        updates["default_model_selection"] = resolved_default

    resolved_metadata, _ = resolve_metadata_extraction_model_selection(
        settings.get("metadata_extraction_model_selection"),
        saved_endpoints,
        multi_endpoint_enabled=multi_endpoint_enabled,
    )
    if resolved_metadata != settings.get("metadata_extraction_model_selection"):
        updates["metadata_extraction_model_selection"] = resolved_metadata

    # ``update_settings`` swallows its own exceptions and answers False. The Key Vault
    # passes above have already run and cannot be undone, so reporting success on a failed
    # write would leave an endpoint referencing a secret that no longer exists.
    if not update_settings(updates):
        raise RuntimeError("The settings document could not be updated.")

    return saved_endpoints


def _seed_connections_on_first_enable(updates, current_settings):
    """Carry the classic chat endpoint into the connection list when connections go on.

    Enabling connections is one-way. A deployment that already had a working classic
    endpoint, and enables connections without carrying it over, is left with an empty model
    catalog and no way to switch back -- so chat stops working outright.

    The classic form has always migrated on this transition. Mirroring it here, through the
    same shared builder, is what stops the V2 surface from being the one path that strands
    a deployment.
    """
    if not updates.get("enable_multi_model_endpoints"):
        return
    if current_settings.get("enable_multi_model_endpoints", False):
        return
    if _load_global_model_endpoints(current_settings):
        return

    migrated = build_migrated_model_endpoints_from_legacy(current_settings)
    if not migrated:
        return

    normalized, _ = normalize_model_endpoints(migrated)
    updates["model_endpoints"] = [
        keyvault_model_endpoint_save_helper(
            endpoint, endpoint.get("id"), scope="global", existing_endpoint=None
        )
        for endpoint in normalized
    ]
    log_event(
        f"[V2_ADMIN_ENDPOINTS] Migrated the classic chat endpoint into "
        f"{len(updates['model_endpoints'])} connection(s) on first enable",
        level=logging.INFO,
    )


def register_route_backend_v2_admin(bp):
    def _build_model_catalog(settings):
        """Return the models an administrator can pick, with resolved capabilities.

        A picker that offered every model would let an administrator choose one that
        cannot read images for Multi-Modal Vision Analysis, which fails at upload time
        rather than at configuration time. Resolving here keeps the decision on the
        server, where ``functions_model_capabilities`` is the single implementation, so
        the browser does not need a second copy of the rules.

        ``vision_source`` says whether the answer is known or guessed, which is what
        lets the picker mark an inferred model rather than presenting a guess as fact.
        """
        catalog = []
        seen = set()

        for endpoint in settings.get("model_endpoints") or []:
            if not isinstance(endpoint, dict):
                continue
            endpoint_label = endpoint.get("name") or endpoint.get("id") or ""

            for model in endpoint.get("models") or []:
                if not isinstance(model, dict) or not model.get("enabled", True):
                    continue

                deployment = str(
                    model.get("deploymentName") or model.get("deployment") or ""
                ).strip()
                if not deployment or deployment in seen:
                    continue
                seen.add(deployment)

                supports_vision, vision_source = resolve_model_vision_support(model)
                catalog.append(
                    {
                        "deployment": deployment,
                        "label": model.get("displayName")
                        or model.get("modelName")
                        or deployment,
                        "endpoint": endpoint_label,
                        "endpoint_id": endpoint.get("id"),
                        "model_name": model.get("modelName") or "",
                        "supports_vision": supports_vision,
                        "vision_source": vision_source,
                    }
                )

        catalog.sort(key=lambda entry: entry["label"].lower())
        return catalog

    def _build_status_readouts():
        """Return the server-computed readouts declared `status` fields render.

        Some of what an administrator needs is not a setting: whether the Playwright
        runtime can render JavaScript, which endpoint a cloud selection resolves to,
        whether audio transcoding is available. The server-rendered panes pass these
        into the template as loose context and print them as stray markup. Naming them
        here lets the schema declare a readout, which keeps the reason a control is
        unavailable next to the control and makes it findable by search.

        Each entry is ``{ok, message}``: the renderer needs the tone as well as the
        text, and inferring it from wording would be guesswork.
        """
        readouts = {}

        try:
            capabilities = get_source_review_runtime_capabilities()
            readouts["source_review_js_runtime"] = {
                "ok": bool(capabilities.get("js_rendering_available")),
                "message": capabilities.get("message")
                or "Runtime support has not been checked yet.",
            }
            if capabilities.get("sandbox_disabled"):
                readouts["source_review_js_runtime"]["message"] += (
                    " The Chromium sandbox is disabled by environment configuration."
                )
        except Exception as exc:
            # A probe that launches a browser can fail for reasons that have nothing
            # to do with the settings page, and it must not take the page down.
            log_event(
                f"[V2_ADMIN_SETTINGS] Source review runtime probe failed: {exc}",
                level=logging.WARNING,
            )
            readouts["source_review_js_runtime"] = {
                "ok": False,
                "message": "Runtime support could not be checked.",
            }

        try:
            audio = get_audio_runtime_capabilities()
            broad = bool(audio.get("broad_transcoding_available"))
            supported = ", ".join(audio.get("supported_extensions") or []) or "none"
            message = audio.get("message") or "Audio runtime support has not been checked."
            readouts["audio_runtime"] = {
                "ok": broad,
                "message": f"{message} Accepted uploads: {supported}.",
            }
        except Exception as exc:
            log_event(
                f"[V2_ADMIN_SETTINGS] Audio runtime probe failed: {exc}",
                level=logging.WARNING,
            )
            readouts["audio_runtime"] = {
                "ok": False,
                "message": "Audio runtime support could not be checked.",
            }

        return readouts

    def _build_endpoint_readouts(settings):
        """Readouts derived from the settings document rather than from the host."""
        endpoint = str(settings.get("video_indexer_endpoint") or "").strip()
        return {
            "video_indexer_endpoint": {
                "ok": bool(endpoint),
                "message": endpoint or "No endpoint resolved yet.",
            }
        }

    def _redact_admin_settings_for_v2(settings):
        """Replace stored credentials with the redaction placeholder.

        Three lists feed this, and all three are needed:

        ``redact_admin_settings_secrets_for_api`` covers what the server-rendered form
        protects plus the keys only this endpoint returns, because it hands back the
        whole settings document rather than the subset a template draws.

        ``get_secret_storage_paths`` adds anything the V2 schema declares as a secret,
        so declaring a new credential field protects it without a second edit here. It
        reports storage paths rather than field keys, because a credential is not always
        stored under the name of its control -- the Web Search client secret lives inside
        ``web_search_agent``, and redacting the field key would leave the real value in
        place under its actual path.

        Model endpoint credentials are reached by none of the above, because they sit
        inside a list rather than at a fixed key. ``sanitize_model_endpoints_for_frontend``
        strips those, and it runs here rather than at the call site so the PATCH echo is
        covered by the same guarantee as the GET.
        """
        redacted = redact_admin_settings_secrets_for_api(settings)
        for path in get_secret_storage_paths():
            if "." in path:
                if read_nested_setting(redacted, path):
                    write_nested_setting(redacted, path, SECRET_REDACTED_VALUE)
            elif redacted.get(path):
                redacted[path] = SECRET_REDACTED_VALUE
        # Only when it is present: the PATCH echo carries just the submitted keys, and
        # adding one the caller never sent would write it into the page's stored copy.
        if "model_endpoints" in redacted:
            redacted["model_endpoints"] = sanitize_model_endpoints_for_frontend(
                redacted.get("model_endpoints")
            )
        return redacted

    @bp.route("/api/v2/admin/settings", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def v2_admin_get_settings():
        """Return the settings document, the admin navigation and the field schema.

        Admin settings are not passed through ``sanitize_settings_for_user``: that
        removes endpoint and integration configuration, which is exactly what an
        administrator is here to manage. Access is restricted to the Admin role by the
        blueprint guard and the decorator.

        Secrets are a separate question from sanitization and *are* withheld. Every known
        secret is replaced with a placeholder, matching what the server-rendered form
        does, so a stored key never reaches the browser merely because someone opened the
        page. The list used here is wider than the form's, because this endpoint returns
        the whole settings document rather than the subset a template draws, and it also
        covers credentials the schema declares at a nested path rather than under a
        top-level key of their own.

        Submitting a placeholder back means "unchanged". The normalizer drops it, and the
        PATCH below resolves anything that reaches it against the stored document, so an
        untouched secret survives a save either way.

        Model endpoint credentials sit inside the ``model_endpoints`` list rather than at
        a fixed key, so no key-based list reaches them. They are stripped separately by
        ``sanitize_model_endpoints_for_frontend``, which is what the server-rendered page
        passes to its template.

        ``field_schema`` describes the concrete controls each section owns. Sections with
        no entry are rendered by the SPA's ``enable_*`` fallback scan, so groups that have
        not been described yet keep working. ``suppressed_capabilities`` names the keys
        that scan must skip because they are derived or are staged rollout flags with no
        administrator control.
        """
        try:
            settings = get_settings()
            return (
                jsonify(
                    {
                        "settings": _redact_admin_settings_for_v2(settings),
                        "admin_nav": ADMIN_NAV,
                        "field_schema": get_admin_settings_fields(),
                        "section_status": get_admin_section_status(),
                        "app_role_requirements": get_app_role_requirements(),
                        "branding_assets": _build_branding_assets(settings),
                        "status_readouts": {
                            **_build_status_readouts(),
                            **_build_endpoint_readouts(settings),
                        },
                        "model_catalog": _build_model_catalog(settings),
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

        Secrets need one step beyond normalization. The browser was handed a placeholder
        rather than the stored value, so a save that did not touch a secret sends the
        placeholder straight back; storing it verbatim would overwrite a working
        credential with the literal string. Every key redacted on the way out is
        therefore resolved against the current document on the way in, exactly as the
        server-rendered form does -- not just the ones the schema declares, so a redacted
        key reaching the payload some other way cannot land as the placeholder either.
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
                # Every supplied key normalized away. In practice that means the payload
                # held nothing but untouched credentials, which is a no-op rather than a
                # mistake, so it succeeds with an empty result instead of a 400.
                return (
                    jsonify(
                        {
                            "success": True,
                            "updated_keys": [],
                            "settings": {},
                            "warnings": warnings,
                        }
                    ),
                    200,
                )

            secret_keys = set(get_admin_settings_api_secret_fields()) | get_secret_field_keys()
            for key in secret_keys & set(normalized):
                normalized[key] = resolve_admin_settings_secret_value(
                    key, normalized[key], current_settings
                )

            # After the secret pass, so the derived endpoints this adds -- whose own
            # secrets are already stored through Key Vault -- are not run through it.
            _seed_connections_on_first_enable(normalized, current_settings)

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

            # The response reflects the draft back into the page's stored state, so a
            # resolved secret has to be re-redacted on the way out, which
            # _redact_admin_settings_for_v2 does below.
            return (
                jsonify(
                    {
                        "success": True,
                        "updated_keys": sorted(normalized.keys()),
                        # The browser merges this into its copy of the document, so a
                        # credential that was just set has to come back redacted rather
                        # than echoing the value straight out again. This follows nested
                        # storage paths too, which a flat key check over `normalized`
                        # would miss for the Foundry client secret.
                        "settings": _redact_admin_settings_for_v2(normalized),
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

    @bp.route("/api/v2/admin/settings/test-connection", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def v2_admin_test_connection():
        """Run one connection test against the values currently on screen.

        Endpoints and credentials are worth nothing if they are wrong, and the only
        way to find out is to try them. The server-rendered page has always offered
        this; without it here, configuring a connection in the V2 surface would mean
        saving blind and waiting for a user to hit the failure.

        Testing before saving is the point, so the payload carries the draft values
        rather than the stored ones. The one thing the browser cannot supply is a
        credential it was never sent: a stored secret arrives as the redaction
        placeholder and is resolved server-side by the shared dispatcher.

        The dispatcher is shared with ``/api/admin/settings/test_connection`` so both
        interfaces support exactly the same set of tests.
        """
        payload = request.get_json(silent=True) or {}

        test_type = str(payload.get("test_type") or "").strip()
        if not test_type:
            return jsonify({"error": "No test_type supplied"}), 400

        _prepare_v2_test_payload(payload, test_type)

        log_event(
            f"[V2_ADMIN_SETTINGS] Running '{test_type}' connection test",
            level=logging.INFO,
        )
        return run_admin_settings_connection_test(payload)

    def _prepare_v2_test_payload(payload, test_type):
        """Fill in what the V2 picker knows but the schema cannot express.

        A ``test_payload`` maps settings keys to request fields, which covers a
        connection assembled from settings. The vision test is different: it needs the
        endpoint that hosts the chosen model, and that is a property of the selection
        rather than a setting of its own.

        Resolving it here rather than sending it from the browser also keeps the
        endpoint's credentials out of the request. The handler looks the endpoint up in
        the stored settings from the id alone.
        """
        if test_type != "multimodal_vision":
            return

        if isinstance(payload.get("multi_endpoint"), dict):
            return

        deployment = str(payload.get("vision_model") or "").strip()
        if not deployment:
            return

        settings = get_settings()
        for endpoint in settings.get("model_endpoints") or []:
            if not isinstance(endpoint, dict):
                continue
            for model in endpoint.get("models") or []:
                if not isinstance(model, dict):
                    continue
                candidate = str(
                    model.get("deploymentName") or model.get("deployment") or ""
                ).strip()
                if candidate != deployment:
                    continue

                payload["multi_endpoint"] = {
                    "endpoint_id": endpoint.get("id"),
                    "model_id": model.get("id"),
                    "provider": endpoint.get("provider"),
                    "deployment_name": candidate,
                }
                return

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

    # ---------------------------------------------------------------------
    # Global model endpoints
    # ---------------------------------------------------------------------
    #
    # Personal and group scopes have had per-endpoint REST routes for a while; global
    # scope never did. It was written through a hidden ``model_endpoints_json`` field on
    # the classic admin form, which means adding or editing an endpoint there stores
    # nothing until the whole settings page is submitted. These routes give global scope
    # the same per-resource handling the other two scopes already have, so a save is a
    # save.
    #
    # Secrets never travel outward: responses go through
    # ``sanitize_model_endpoints_for_frontend``, which strips ``auth.api_key`` and
    # ``auth.client_secret`` and leaves ``has_api_key`` / ``has_client_secret`` behind. An
    # omitted secret on the way back in therefore means "keep what is stored" rather than
    # "clear it", which is what ``merge_model_endpoint_payload`` implements.

    @bp.route("/api/v2/admin/model-endpoints", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def v2_admin_list_model_endpoints():
        """Return every global model endpoint, with secrets stripped."""
        try:
            endpoints = _load_global_model_endpoints()
            return (
                jsonify(
                    {
                        "endpoints": sanitize_model_endpoints_for_frontend(endpoints),
                        "multi_endpoint_enabled": bool(
                            get_settings().get("enable_multi_model_endpoints", False)
                        ),
                    }
                ),
                200,
            )
        except Exception as exc:
            log_event(
                f"[V2_ADMIN_ENDPOINTS] Failed to list model endpoints: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"error": "Failed to load model endpoints"}), 500

    @bp.route("/api/v2/admin/model-endpoints", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def v2_admin_create_model_endpoint():
        """Add one global model endpoint."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not payload:
            return jsonify({"error": "Model endpoint payload must be an object."}), 400

        try:
            existing = _load_global_model_endpoints()
            candidate = dict(payload)

            endpoint_id = str(candidate.get("id") or "").strip()
            if not endpoint_id:
                endpoint_id = str(uuid.uuid4())
            elif _find_model_endpoint(existing, endpoint_id):
                return (
                    jsonify({"error": "A model endpoint with that id already exists."}),
                    409,
                )
            candidate["id"] = endpoint_id

            normalized, _ = normalize_model_endpoints(list(existing) + [candidate])
            saved = _persist_global_model_endpoints(normalized, existing)
            log_event(
                f"[V2_ADMIN_ENDPOINTS] Created model endpoint {endpoint_id}",
                level=logging.INFO,
            )
            return _model_endpoint_response(saved, endpoint_id, 201)
        except Exception as exc:
            log_event(
                f"[V2_ADMIN_ENDPOINTS] Failed to create model endpoint: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"error": "Failed to create the model endpoint"}), 500

    @bp.route("/api/v2/admin/model-endpoints/<endpoint_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def v2_admin_get_model_endpoint(endpoint_id):
        """Return one global model endpoint, with its secrets stripped."""
        try:
            endpoint = _find_model_endpoint(_load_global_model_endpoints(), endpoint_id)
            if not endpoint:
                return jsonify({"error": "Model endpoint not found."}), 404

            sanitized = sanitize_model_endpoints_for_frontend([endpoint])
            return jsonify({"endpoint": sanitized[0] if sanitized else {}}), 200
        except Exception as exc:
            log_event(
                f"[V2_ADMIN_ENDPOINTS] Failed to read model endpoint: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"error": "Failed to load the model endpoint"}), 500

    @bp.route("/api/v2/admin/model-endpoints/<endpoint_id>", methods=["PATCH"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def v2_admin_update_model_endpoint(endpoint_id):
        """Apply a partial update to one global model endpoint.

        The stored endpoint is merged with the supplied keys server-side. A client only
        ever holds a copy with the secrets stripped out, so sending that copy back must
        not blank them -- and because the merge skips empty values, it does not.
        """
        updates = request.get_json(silent=True)
        if not isinstance(updates, dict):
            return jsonify({"error": "Model endpoint payload must be an object."}), 400

        try:
            existing = _load_global_model_endpoints()
            current = _find_model_endpoint(existing, endpoint_id)
            if not current:
                return jsonify({"error": "Model endpoint not found."}), 404

            merged = merge_model_endpoint_payload(
                current, {**updates, "id": current.get("id")}
            )
            replaced = [
                merged
                if isinstance(endpoint, dict)
                and str(endpoint.get("id") or "") == str(endpoint_id)
                else endpoint
                for endpoint in existing
            ]

            normalized, _ = normalize_model_endpoints(replaced)
            saved = _persist_global_model_endpoints(normalized, existing)
            log_event(
                f"[V2_ADMIN_ENDPOINTS] Updated model endpoint {endpoint_id}",
                level=logging.INFO,
            )
            return _model_endpoint_response(saved, current.get("id"), 200)
        except Exception as exc:
            log_event(
                f"[V2_ADMIN_ENDPOINTS] Failed to update model endpoint: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"error": "Failed to update the model endpoint"}), 500

    @bp.route("/api/v2/admin/model-endpoints/<endpoint_id>", methods=["DELETE"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def v2_admin_delete_model_endpoint(endpoint_id):
        """Remove one global model endpoint and the secrets it owned.

        The stored list is read server-side rather than taken from the request, so a
        stale copy in one browser tab cannot drop endpoints it never knew about.
        """
        try:
            existing = _load_global_model_endpoints()
            if not _find_model_endpoint(existing, endpoint_id):
                return jsonify({"error": "Model endpoint not found."}), 404

            remaining = [
                endpoint
                for endpoint in existing
                if not (
                    isinstance(endpoint, dict)
                    and str(endpoint.get("id") or "") == str(endpoint_id)
                )
            ]

            normalized, _ = normalize_model_endpoints(remaining)
            _persist_global_model_endpoints(normalized, existing)
            log_event(
                f"[V2_ADMIN_ENDPOINTS] Deleted model endpoint {endpoint_id}",
                level=logging.INFO,
            )
            return jsonify({"success": True}), 200
        except Exception as exc:
            log_event(
                f"[V2_ADMIN_ENDPOINTS] Failed to delete model endpoint: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"error": "Failed to delete the model endpoint"}), 500

    @bp.route("/api/v2/admin/groups", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def v2_admin_list_groups():
        """Return group directory rows for an administrator's assignment picker.

        Settings such as ``group_workflow_allowed_group_ids`` store group ids. An
        id is not something an administrator can recognise, so the picker needs to
        resolve one to a name, and needs to search the directory to add another.

        This exists rather than reusing ``/api/groups/discover`` because that
        endpoint answers a different question: it is a member-facing directory,
        gated on the User role and on group workspaces being enabled, it returns
        every group in one unbounded response, and it cannot resolve a specific
        set of ids. An administrator managing an assignment may hold neither the
        User role nor a membership in the groups being assigned.

        ``ids`` resolves an existing assignment; ids that no longer exist are
        absent from the response, which is how the caller detects a stale entry.
        Otherwise ``search`` matches on name, description or id.
        """
        raw_ids = str(request.args.get("ids") or "").strip()
        if raw_ids:
            requested_ids = normalize_group_workflow_allowed_group_ids(raw_ids)
            if not requested_ids:
                return jsonify({"groups": [], "truncated": False}), 200
            if len(requested_ids) > GROUP_DIRECTORY_MAX_LIMIT:
                return (
                    jsonify(
                        {
                            "error": "Too many group ids requested. Limit is "
                            f"{GROUP_DIRECTORY_MAX_LIMIT}."
                        }
                    ),
                    400,
                )

            try:
                return (
                    jsonify({"groups": find_groups_by_ids(requested_ids), "truncated": False}),
                    200,
                )
            except Exception as exc:
                log_event(
                    f"[V2_ADMIN_GROUPS] Failed to resolve {len(requested_ids)} group id(s): {exc}",
                    level=logging.ERROR,
                    exceptionTraceback=True,
                )
                return jsonify({"error": "Failed to load groups"}), 500

        try:
            limit = int(request.args.get("limit") or GROUP_DIRECTORY_DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = GROUP_DIRECTORY_DEFAULT_LIMIT

        try:
            groups, truncated = list_groups_for_admin_directory(
                search_query=request.args.get("search", ""),
                limit=limit,
            )
            return jsonify({"groups": groups, "truncated": truncated}), 200
        except Exception as exc:
            log_event(
                f"[V2_ADMIN_GROUPS] Failed to list groups: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"error": "Failed to load groups"}), 500
