# functions_support_latest_features.py
"""The Latest Features catalogues, shaped for the V2 admin surface.

``support_menu_config`` holds two release catalogues: one written for end users
and shown from the Support menu, and one written for administrators and shown on
the Admin Latest Features tab. The server-rendered page turns both into markup
with Jinja, resolving each shortcut with ``url_for`` and each screenshot with
``url_for('static', ...)``. The V2 surface can do neither, so this module does
that resolution once, on the server, and returns plain data.

It imports no Flask and no Azure client, so it can be exercised directly: the
route passes in the two resolvers it needs.

``admin``
    Administrator release groups. Each shortcut that targets an admin tab is
    resolved to a live tab id, following ``LEGACY_TAB_REDIRECTS``, so the V2 page
    can jump to the matching card, or fall back to the server-rendered tab when V2
    does not draw it.

``user``
    End-user release groups as users read them, with each announcement's default
    visibility. Shortcuts keep their ``requires_settings`` so the V2 preview can
    show or hide them as the draft changes; the documentation guide buttons
    depend on a switch in the same section.
"""

import re

from admin_settings_nav import resolve_admin_tab_id
from support_menu_config import (
    get_admin_latest_feature_release_groups_for_settings,
    get_default_support_latest_features_visibility,
    get_support_latest_feature_release_groups_for_preview,
)


ACTION_KIND_ADMIN = "admin"
ACTION_KIND_PAGE = "page"
ACTION_KIND_EXTERNAL = "external"

# Section ids are element ids on both admin surfaces. Anything else is dropped
# rather than passed to the browser as a jump target.
SECTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,120}$")

# Settings keys an action may depend on. They are compared against the draft in
# the browser, so only plain keys are passed through.
SETTING_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,120}$")


def _text(value):
    """Return a trimmed string for any catalogue value."""
    return str(value if value is not None else "").strip()


def _is_same_origin_path(href):
    """Whether a destination is a path on this application."""
    return href.startswith("/") and not href.startswith("//") and "\\" not in href


def _is_http_url(href):
    """Whether a destination is an absolute http(s) address."""
    return href.lower().startswith(("https://", "http://"))


def _serialize_image(image, resolve_static_url):
    """Return one screenshot with a browser-ready URL, or None when it has no path."""
    path = _text(image.get("path"))
    if not path:
        return None
    url = _text(resolve_static_url(path))
    if not _is_same_origin_path(url):
        return None
    return {
        "url": url,
        "alt": _text(image.get("alt")),
        "title": _text(image.get("title")),
        "caption": _text(image.get("caption")),
        "label": _text(image.get("label")),
    }


def _resolve_page_href(action, resolve_endpoint_url):
    """Return the destination of a non-admin shortcut, or '' when it has none."""
    href = _text(action.get("href"))
    if href:
        return href

    endpoint = _text(action.get("endpoint"))
    if not endpoint:
        return ""
    href = _text(resolve_endpoint_url(endpoint))
    fragment = _text(action.get("fragment"))
    if href and fragment:
        href = f"{href}#{fragment}"
    return href


def _serialize_action(action, resolve_endpoint_url):
    """Return one shortcut as the V2 page needs it, or None when it cannot be followed.

    ``kind`` says how the browser follows it:

    ``admin``
        A tab on the Admin Settings page, optionally narrowed to a section. ``href``
        is the server-rendered tab, used when V2 does not draw the target itself.
    ``page``
        Another page of this application.
    ``external``
        An absolute http(s) address, opened in a new tab.
    """
    label = _text(action.get("label"))
    if not label:
        return None

    serialized = {
        "label": label,
        "description": _text(action.get("description")),
        "icon": _text(action.get("icon")),
        "requires_settings": [
            key
            for key in (_text(item) for item in action.get("requires_settings") or [])
            if SETTING_KEY_PATTERN.match(key)
        ],
    }

    admin_tab = resolve_admin_tab_id(action.get("admin_tab"))
    if admin_tab:
        section = _text(action.get("admin_section"))
        serialized.update(
            {
                "kind": ACTION_KIND_ADMIN,
                "admin_tab": admin_tab,
                "admin_section": section if SECTION_ID_PATTERN.match(section) else None,
                "href": f"/admin/settings#{admin_tab}",
            }
        )
        return serialized

    href = _resolve_page_href(action, resolve_endpoint_url)
    if _is_http_url(href):
        serialized.update({"kind": ACTION_KIND_EXTERNAL, "href": href})
        return serialized
    if _is_same_origin_path(href):
        serialized.update({"kind": ACTION_KIND_PAGE, "href": href})
        return serialized
    return None


def _serialize_feature(feature, resolve_endpoint_url, resolve_static_url, default_visible=None):
    """Return one announcement with its screenshots and shortcuts resolved."""
    images = [
        image
        for image in (
            _serialize_image(item, resolve_static_url)
            for item in feature.get("images") or []
            if isinstance(item, dict)
        )
        if image
    ]
    actions = [
        action
        for action in (
            _serialize_action(item, resolve_endpoint_url)
            for item in feature.get("actions") or []
            if isinstance(item, dict)
        )
        if action
    ]
    serialized = {
        "id": _text(feature.get("id")),
        "title": _text(feature.get("title")),
        "icon": _text(feature.get("icon")),
        "summary": _text(feature.get("summary")),
        "details": _text(feature.get("details")),
        "why": _text(feature.get("why")),
        "guidance": [_text(item) for item in feature.get("guidance") or [] if _text(item)],
        "images": images,
        "actions": actions,
    }
    if default_visible is not None:
        serialized["default_visible"] = bool(default_visible)
    return serialized


def _serialize_group(group, resolve_endpoint_url, resolve_static_url, visibility_defaults=None):
    """Return one release group and its announcements."""
    features = []
    for feature in group.get("features") or []:
        if not isinstance(feature, dict) or not _text(feature.get("id")):
            continue
        default_visible = None
        if visibility_defaults is not None:
            default_visible = visibility_defaults.get(feature["id"], True)
        features.append(
            _serialize_feature(
                feature,
                resolve_endpoint_url,
                resolve_static_url,
                default_visible=default_visible,
            )
        )
    return {
        "id": _text(group.get("id")),
        "label": _text(group.get("label")),
        "description": _text(group.get("description")),
        "release_version": _text(group.get("release_version")),
        "default_expanded": bool(group.get("default_expanded")),
        "features": features,
    }


def build_latest_features_payload(settings, *, resolve_endpoint_url, resolve_static_url, version):
    """Return both Latest Features catalogues for the V2 admin surface.

    ``resolve_endpoint_url`` turns a Flask endpoint name into a path and returns
    '' when the endpoint does not exist; ``resolve_static_url`` turns a static file
    path into a URL. Both are supplied by the route so this stays free of Flask.
    """
    visibility_defaults = get_default_support_latest_features_visibility()
    return {
        "version": _text(version),
        "admin": [
            _serialize_group(group, resolve_endpoint_url, resolve_static_url)
            for group in get_admin_latest_feature_release_groups_for_settings(settings)
        ],
        "user": [
            _serialize_group(
                group,
                resolve_endpoint_url,
                resolve_static_url,
                visibility_defaults=visibility_defaults,
            )
            for group in get_support_latest_feature_release_groups_for_preview(settings)
        ],
    }
