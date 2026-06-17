# route_custom_pages.py
"""Routes for trusted deployment-time custom pages."""

import mimetypes
import os
import logging

from flask import Response, jsonify, render_template, request, send_file, session

from functions_appinsights import log_event
from functions_authentication import admin_required, login_required
from functions_custom_pages import (
    build_custom_page_context,
    delete_custom_page,
    get_custom_page,
    is_custom_page_authorized,
    is_custom_pages_enabled,
    list_custom_pages,
    resolve_custom_page_file,
    save_custom_page,
    validate_custom_page_metadata,
)
from functions_settings import get_settings, sanitize_settings_for_user, update_settings
from swagger_wrapper import get_auth_security, swagger_route


def _custom_pages_disabled_response():
    return "Not Found", 404


def _load_enabled_custom_page_or_404(slug):
    settings = get_settings()
    if not is_custom_pages_enabled(settings):
        return None, settings, _custom_pages_disabled_response()

    page = get_custom_page(slug, include_python=True)
    if not page or not page.get("enabled", True):
        return None, settings, ("Not Found", 404)

    if not is_custom_page_authorized(page):
        return None, settings, ("Forbidden", 403)

    return page, settings, None


def _current_admin_user_id():
    user = session.get("user", {}) if session else {}
    if not isinstance(user, dict):
        return "admin"
    return str(user.get("oid") or user.get("preferred_username") or user.get("email") or "admin")


def _get_custom_pages_developer_guide_path():
    """Return the path for the canonical in-app Custom Pages developer guide."""
    app_root = os.path.dirname(__file__)
    guide_path = os.path.abspath(os.path.join(app_root, "docs", "how-to", "custom_pages.md"))
    return guide_path if os.path.isfile(guide_path) else None


def _strip_markdown_front_matter(markdown_text):
    """Remove Jekyll front matter before rendering markdown inside the app."""
    if not markdown_text.startswith("---"):
        return markdown_text
    parts = markdown_text.split("---", 2)
    if len(parts) == 3:
        return parts[2].lstrip()
    return markdown_text


def _render_custom_page_response(slug):
    """Render a custom page response for canonical and compatibility routes."""
    page, settings, error_response = _load_enabled_custom_page_or_404(slug)
    if error_response:
        return error_response

    if page.get("entry_type") == "python":
        extension = page.get("extension")
        if not extension or not hasattr(extension, "render"):
            return "Not Found", 404
        return extension.render(build_custom_page_context(page, sanitize_settings_for_user(settings)))

    html_file = page.get("html_file")
    html_path, error = resolve_custom_page_file(page, "html", html_file)
    if error:
        log_event(
            "[CustomPages] Unable to resolve custom page HTML.",
            extra={"slug": slug, "error": error},
            level=logging.WARNING,
        )
        return "Not Found", 404

    with open(html_path, "r", encoding="utf-8") as html_handle:
        trusted_html = html_handle.read()

    return render_template(
        "custom_page_shell.html",
        custom_page=page,
        custom_page_html=trusted_html,
        settings=sanitize_settings_for_user(settings),
    )


def register_route_custom_pages(app):
    @app.route("/custom/<slug>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    def custom_page(slug):
        """Render a trusted custom page."""
        return _render_custom_page_response(slug)

    @app.route("/custom/<slug>.html", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    def custom_page_html_alias(slug):
        """Render a trusted custom page from a familiar .html URL alias."""
        return _render_custom_page_response(slug)

    @app.route("/custom/assets/<slug>/<folder>/<path:filename>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    def custom_page_asset(slug, folder, filename):
        """Serve a declared custom page asset."""
        page, _, error_response = _load_enabled_custom_page_or_404(slug)
        if error_response:
            return error_response

        file_path, error = resolve_custom_page_file(page, folder, filename)
        if error:
            log_event(
                "[CustomPages] Blocked custom page asset request.",
                extra={"slug": slug, "folder": folder, "filename": filename, "error": error},
                level=logging.WARNING,
            )
            return "Not Found", 404

        mimetype = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        response = send_file(file_path, mimetype=mimetype, conditional=True)
        if os.path.splitext(file_path)[1].lower() == ".mjs":
            response.headers["Content-Type"] = "application/javascript"
        return response

    @app.route("/api/custom/<slug>/<path:operation>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    @swagger_route(security=get_auth_security())
    @login_required
    def custom_page_api(slug, operation):
        """Dispatch a trusted Python-backed custom page API operation."""
        page, settings, error_response = _load_enabled_custom_page_or_404(slug)
        if error_response:
            return error_response
        if page.get("entry_type") != "python" or not page.get("extension"):
            return jsonify({"error": "Custom page API not found"}), 404
        try:
            return page["extension"].handle_api(
                operation,
                build_custom_page_context(page, sanitize_settings_for_user(settings)),
            )
        except NotImplementedError:
            return jsonify({"error": "Custom page API not found"}), 404

    @app.route("/api/admin/custom-pages", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def admin_list_custom_pages():
        """List custom page metadata for the Admin Settings designer."""
        settings = get_settings()
        include_python = is_custom_pages_enabled(settings)
        pages = list_custom_pages(include_python=include_python)
        safe_pages = [{key: value for key, value in page.items() if key != "extension"} for page in pages]
        return jsonify({"pages": safe_pages})

    @app.route("/api/admin/custom-pages/developer-guide", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def admin_custom_pages_developer_guide():
        """Return the canonical Custom Pages developer guide markdown for the in-app modal."""
        guide_path = _get_custom_pages_developer_guide_path()
        if not guide_path:
            return jsonify({"error": "Custom Pages developer guide was not found."}), 404

        try:
            with open(guide_path, "r", encoding="utf-8") as guide_handle:
                markdown_text = _strip_markdown_front_matter(guide_handle.read())
            return jsonify({"markdown": markdown_text})
        except Exception as ex:
            log_event(
                "[CustomPages] Failed to load developer guide.",
                extra={"error": str(ex)},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"error": "Custom Pages developer guide could not be loaded."}), 500

    @app.route("/api/admin/custom-pages", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def admin_create_custom_page():
        """Create static custom page metadata."""
        payload = request.get_json(silent=True) or {}
        errors = validate_custom_page_metadata(payload, require_static_html=True)
        if errors:
            return jsonify({"error": "; ".join(errors)}), 400
        slug = str(payload.get("slug") or payload.get("id") or "").strip().lower()
        if get_custom_page(slug, include_python=True):
            return jsonify({"error": "A custom page with this slug already exists."}), 409
        saved = save_custom_page(payload, user_id=_current_admin_user_id())
        return jsonify(saved), 201

    @app.route("/api/admin/custom-pages/request-access-example", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def admin_create_request_access_custom_page():
        """Create or update the optional Request Access custom page metadata."""
        request_access_page = {
            "slug": "request-access",
            "title": "Request SimpleChat Access",
            "description": "A signed-in access request page for users who need the base User role.",
            "entry_type": "static",
            "access_level": "authenticated",
            "nav_label": "Request Access",
            "nav_icon": "bi-person-plus",
            "nav_order": 5,
            "roles": [],
            "show_in_nav": False,
            "open_in_new_tab": False,
            "html_file": "request-access.html",
            "css_files": ["request-access.css"],
            "js_files": [],
            "asset_files": [],
            "json_files": [],
            "enabled": True,
        }
        errors = validate_custom_page_metadata(request_access_page, require_static_html=True)
        if errors:
            return jsonify({"error": "; ".join(errors)}), 400

        saved = save_custom_page(request_access_page, user_id=_current_admin_user_id())
        update_settings({
            "access_request_button_enabled": True,
            "access_request_button_text": "Request Access",
            "access_request_page_url": "/custom/request-access",
        })
        return jsonify({"page": saved, "access_request_button_enabled": True}), 201

    @app.route("/api/admin/custom-pages/<slug>", methods=["PUT"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def admin_update_custom_page(slug):
        """Update static custom page metadata."""
        payload = request.get_json(silent=True) or {}
        payload["slug"] = slug
        errors = validate_custom_page_metadata(payload, require_static_html=True)
        if errors:
            return jsonify({"error": "; ".join(errors)}), 400
        saved = save_custom_page(payload, user_id=_current_admin_user_id())
        return jsonify(saved), 200

    @app.route("/api/admin/custom-pages/<slug>", methods=["DELETE"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def admin_delete_custom_page(slug):
        """Delete static custom page metadata."""
        page = get_custom_page(slug, include_python=True)
        if page and page.get("source") == "python":
            return jsonify({"error": "Python-backed custom pages are managed in code."}), 400
        if not delete_custom_page(slug):
            return jsonify({"error": "Custom page not found."}), 404
        return Response(status=204)