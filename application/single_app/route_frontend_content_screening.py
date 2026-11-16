# route_frontend_content_screening.py
"""Authenticated classic content review entry; disabled scanning never hides holds."""

from flask import make_response, render_template

from functions_authentication import login_required, user_required, user_required_blueprint
from functions_settings import get_settings, sanitize_settings_for_user
from swagger_wrapper import swagger_route, get_auth_security


def register_route_frontend_content_screening(bp):
    bp.before_request(user_required_blueprint())

    @bp.route("/content-review", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_review():
        settings = sanitize_settings_for_user(get_settings() or {})
        response = make_response(render_template(
            "content_review.html", app_settings=settings, settings=settings,
        ))
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
