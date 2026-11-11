# route_backend_support_exports.py
"""Separate administrator collection and subject-owner consent API surfaces."""

import io
import logging

from flask import jsonify, request, send_file, session

from functions_appinsights import log_event
from functions_authentication import admin_required, get_current_user_id, login_required, user_required
from support_export_contracts import SupportExportError, fail
from support_export_service import require_admin
from swagger_wrapper import get_auth_security, swagger_route


def _service(factory):
    if factory is not None:
        return factory()
    # Storage/settings wiring belongs to the operation, not route-module import.
    from functions_support_exports import get_support_export_service

    return get_support_export_service()


def _roles():
    user = session.get("user")
    roles = user.get("roles") if isinstance(user, dict) else None
    return roles if isinstance(roles, list) else []


def _body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        fail("invalid_request", "A JSON request object is required.")
    return body


def _respond(factory, operation):
    try:
        if request.path.startswith("/api/admin/support-exports"):
            require_admin(get_current_user_id(), _roles())
        service = _service(factory)
        try:
            result = operation(service)
        finally:
            service.close()
        response = result if hasattr(result, "headers") else jsonify(result)
    except SupportExportError as exc:
        response = jsonify({"error": exc.public_message, "code": exc.code})
        response.status_code = exc.status
    except Exception as exc:
        log_event("[SUPPORT_EXPORT] Support export request failed.", extra={"error_type": type(exc).__name__}, level=logging.ERROR)
        response = jsonify({"error": "Support export could not complete. Check configuration and application logs.", "code": "support_export_failed"})
        response.status_code = 503
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def register_route_backend_support_exports(bp, service_factory=None):
    @bp.route("/api/admin/support-exports/readiness", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def support_export_readiness():
        return _respond(service_factory, lambda service: service.readiness())

    @bp.route("/api/admin/support-exports/configuration", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def support_export_configuration():
        return _respond(service_factory, lambda service: service.configure(get_current_user_id(), _roles(), _body()))

    @bp.route("/api/admin/support-exports/initialize-storage", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def support_export_initialize():
        def initialize(service):
            if _body() != {"confirmed": True}:
                fail("confirmation_required", "Confirm initialization of the private support-export container.")
            return service.initialize_storage(get_current_user_id(), _roles())
        return _respond(service_factory, initialize)

    @bp.route("/api/admin/support-exports/test-sources", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def support_export_test_sources():
        return _respond(service_factory, lambda service: service.test_sources(get_current_user_id(), _roles()))

    @bp.route("/api/admin/support-exports/users", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def support_export_users():
        return _respond(service_factory, lambda service: service.sources.users(request.args.get("q", ""), request.args.get("after", "")))

    @bp.route("/api/admin/support-exports/conversations", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def support_export_conversations():
        return _respond(service_factory, lambda service: service.sources.conversations(
            request.args.get("user_id"), after=request.args.get("after", ""), term=request.args.get("q", ""),
        ))

    @bp.route("/api/admin/support-exports", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def support_export_list():
        return _respond(service_factory, lambda service: service.list_jobs(get_current_user_id(), _roles(), request.args.get("after", "")))

    @bp.route("/api/admin/support-exports/review", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def support_export_review():
        return _respond(service_factory, lambda service: service.prepare(get_current_user_id(), _roles(), _body()))

    @bp.route("/api/admin/support-exports", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def support_export_create():
        def create(service):
            body = _body()
            if set(body) != {"request", "retry_key", "review_id"}:
                fail("invalid_request", "An export request, current scope review, and retry key are required.")
            if not isinstance(body["review_id"], str) or not body["review_id"]:
                fail("review_required", "Review the export scope before generating.")
            return service.create(get_current_user_id(), _roles(), body["request"], body["retry_key"], body["review_id"])
        return _respond(service_factory, create)

    @bp.route("/api/admin/support-exports/<job_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def support_export_status(job_id):
        return _respond(service_factory, lambda service: service.status(get_current_user_id(), _roles(), job_id))

    @bp.route("/api/admin/support-exports/<job_id>/cancel", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def support_export_cancel(job_id):
        return _respond(service_factory, lambda service: service.cancel(get_current_user_id(), _roles(), job_id))

    @bp.route("/api/admin/support-exports/<job_id>/preview", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def support_export_preview(job_id):
        return _respond(service_factory, lambda service: service.preview(get_current_user_id(), _roles(), job_id))

    @bp.route("/api/admin/support-exports/<job_id>/download", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def support_export_download(job_id):
        def download(service):
            data = service.download(get_current_user_id(), _roles(), job_id)
            return send_file(io.BytesIO(data), mimetype="application/zip", as_attachment=True,
                             download_name=f"simplechat-support-{job_id}.zip", max_age=0)
        return _respond(service_factory, download)


def register_route_backend_support_export_consents(bp, service_factory=None):
    @bp.route("/api/support-export-consents", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def support_export_consent_list():
        return _respond(service_factory, lambda service: service.list_consents(get_current_user_id(), request.args.get("after", "")))

    @bp.route("/api/support-export-consents/<consent_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def support_export_consent_details(consent_id):
        return _respond(service_factory, lambda service: service.consent_details(get_current_user_id(), consent_id))

    @bp.route("/api/support-export-consents/<consent_id>/preview", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def support_export_consent_preview(consent_id):
        return _respond(service_factory, lambda service: service.consent_preview(get_current_user_id(), consent_id))

    @bp.route("/api/support-export-consents/<consent_id>/decision", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def support_export_consent_decision(consent_id):
        def decide(service):
            body = _body()
            if set(body) - {"action", "fingerprint"}:
                fail("invalid_request", "Unsupported consent decision.")
            return service.decide(get_current_user_id(), consent_id, body.get("action"), body.get("fingerprint"))
        return _respond(service_factory, decide)
