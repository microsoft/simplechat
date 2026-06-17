# route_backend_data_management.py
"""Admin API routes for SimpleChat Data Management."""

import logging

from flask import current_app, jsonify, request, session

from functions_activity_logging import log_general_admin_action
from functions_appinsights import log_event
from functions_authentication import admin_required, get_current_user_id, login_required
from functions_data_management import (
    DATA_MANAGEMENT_OPERATION_BACKUP,
    DATA_MANAGEMENT_OPERATION_DRY_RUN,
    DATA_MANAGEMENT_OPERATION_MIGRATION,
    DATA_MANAGEMENT_OPERATION_RESTORE,
    DataManagementSettingsValidationError,
    generate_data_management_encryption_key,
    get_data_management_backup_summary,
    get_data_management_job_detail,
    get_data_management_jobs,
    get_data_management_migration_catalog,
    get_data_management_settings,
    queue_data_management_job,
    sanitize_data_management_job_for_admin,
    sanitize_data_management_settings_for_admin,
    summarize_data_management_migration_plan,
    submit_data_management_job,
    test_backup_storage_connection,
    test_target_cosmos_connection,
    test_target_enhanced_citation_storage_connection,
    test_target_search_connection,
    update_data_management_settings,
)
from swagger_wrapper import get_auth_security, swagger_route


def _get_admin_context():
    admin_user = session.get("user", {}) if session else {}
    admin_email = admin_user.get("preferred_username") or admin_user.get("email") or "unknown"
    return get_current_user_id() or "unknown", admin_email


def _log_data_management_admin_action(action, description, additional_context=None):
    admin_user_id, admin_email = _get_admin_context()
    try:
        log_general_admin_action(
            admin_user_id,
            admin_email,
            action,
            description=description,
            additional_context=additional_context or {},
        )
    except Exception as exc:
        log_event(
            "[DataManagement] Failed to write admin activity record.",
            {"action": action, "error": str(exc)},
            level=logging.WARNING,
        )


def register_route_backend_data_management(app):
    @app.route("/api/admin/data-management/settings", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def get_admin_data_management_settings():
        settings = get_data_management_settings()
        return jsonify({
            "success": True,
            "settings": sanitize_data_management_settings_for_admin(settings),
        }), 200

    @app.route("/api/admin/data-management/settings", methods=["PUT"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def update_admin_data_management_settings():
        payload = request.get_json(silent=True) or {}
        try:
            settings = update_data_management_settings(payload)
        except DataManagementSettingsValidationError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except Exception as exc:
            log_event(
                "[DataManagement] Settings update failed.",
                {"error": str(exc)},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"success": False, "error": "Data Management settings could not be saved."}), 400

        _log_data_management_admin_action(
            "data_management_settings_updated",
            "Updated Data Management backup and migration settings.",
            {"enabled": bool(settings.get("enabled")), "scheduled_time_utc": settings.get("scheduled_time_utc")},
        )
        return jsonify({
            "success": True,
            "settings": sanitize_data_management_settings_for_admin(settings),
        }), 200

    @app.route("/api/admin/data-management/encryption-key", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def generate_admin_data_management_encryption_key():
        try:
            settings = generate_data_management_encryption_key()
        except Exception as exc:
            log_event(
                "[DataManagement] Encryption key generation failed.",
                {"error": str(exc)},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"success": False, "error": "Backup encryption key could not be generated."}), 400

        _log_data_management_admin_action(
            "data_management_encryption_key_generated",
            "Generated a Data Management backup encryption key.",
            {"encryption_key_storage": settings.get("encryption_key_storage")},
        )
        return jsonify({"success": True, "settings": settings}), 200

    @app.route("/api/admin/data-management/storage/test", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def test_admin_data_management_storage():
        payload = request.get_json(silent=True) or {}
        create_container = bool(payload.get("create_container", False))
        settings_payload = payload.get("settings") if isinstance(payload.get("settings"), dict) else None
        try:
            result = test_backup_storage_connection(settings=settings_payload, create_container=create_container)
        except DataManagementSettingsValidationError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except Exception as exc:
            log_event(
                "[DataManagement] Backup storage connection test failed.",
                {"error": str(exc)},
                level=logging.WARNING,
            )
            return jsonify({"success": False, "error": "Backup storage connection test failed."}), 400
        return jsonify(result), 200

    @app.route("/api/admin/data-management/target/cosmos/test", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def test_admin_data_management_target_cosmos():
        payload = request.get_json(silent=True) or {}
        settings_payload = payload.get("settings") if isinstance(payload.get("settings"), dict) else None
        try:
            result = test_target_cosmos_connection(settings=settings_payload)
        except Exception as exc:
            log_event(
                "[DataManagement] Target Cosmos connection test failed.",
                {"error": str(exc)},
                level=logging.WARNING,
            )
            return jsonify({"success": False, "error": "Target Cosmos connection test failed."}), 400
        return jsonify(result), 200

    @app.route("/api/admin/data-management/target/search/test", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def test_admin_data_management_target_search():
        payload = request.get_json(silent=True) or {}
        settings_payload = payload.get("settings") if isinstance(payload.get("settings"), dict) else None
        try:
            result = test_target_search_connection(settings=settings_payload)
        except Exception as exc:
            log_event(
                "[DataManagement] Target Search connection test failed.",
                {"error": str(exc)},
                level=logging.WARNING,
            )
            return jsonify({"success": False, "error": "Target Search connection test failed."}), 400
        return jsonify(result), 200

    @app.route("/api/admin/data-management/target/enhanced-citation-storage/test", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def test_admin_data_management_target_enhanced_citation_storage():
        payload = request.get_json(silent=True) or {}
        settings_payload = payload.get("settings") if isinstance(payload.get("settings"), dict) else None
        create_containers = bool(payload.get("create_containers", False))
        try:
            result = test_target_enhanced_citation_storage_connection(
                settings=settings_payload,
                create_containers=create_containers,
            )
        except Exception as exc:
            log_event(
                "[DataManagement] Target Enhanced Citation Storage connection test failed.",
                {"error": str(exc)},
                level=logging.WARNING,
            )
            return jsonify({"success": False, "error": "Target Enhanced Citation Storage connection test failed."}), 400
        return jsonify(result), 200

    @app.route("/api/admin/data-management/jobs", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def list_admin_data_management_jobs():
        limit = request.args.get("limit", 25)
        jobs = [sanitize_data_management_job_for_admin(job) for job in get_data_management_jobs(limit=limit)]
        return jsonify({"success": True, "jobs": jobs}), 200

    @app.route("/api/admin/data-management/jobs/<job_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def get_admin_data_management_job_detail(job_id):
        detail = get_data_management_job_detail(job_id)
        if not detail:
            return jsonify({"success": False, "error": "Data Management job was not found."}), 404
        return jsonify({"success": True, **detail}), 200

    @app.route("/api/admin/data-management/backups", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def list_admin_data_management_backups():
        limit = request.args.get("limit", 100)
        backup_summary = get_data_management_backup_summary(limit=limit)
        return jsonify({"success": True, **backup_summary}), 200

    @app.route("/api/admin/data-management/migration/catalog/<target_type>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def get_admin_data_management_migration_catalog(target_type):
        search = request.args.get("search", "")
        limit = request.args.get("limit", 50)
        try:
            catalog = get_data_management_migration_catalog(target_type, search_text=search, limit=limit)
        except DataManagementSettingsValidationError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        return jsonify({"success": True, **catalog}), 200

    @app.route("/api/admin/data-management/migration/summary", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def summarize_admin_data_management_migration():
        payload = request.get_json(silent=True) or {}
        try:
            summary = summarize_data_management_migration_plan(payload)
        except DataManagementSettingsValidationError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        return jsonify({"success": True, "summary": summary}), 200

    @app.route("/api/admin/data-management/jobs", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def create_admin_data_management_job():
        payload = request.get_json(silent=True) or {}
        operation = str(payload.get("operation") or DATA_MANAGEMENT_OPERATION_DRY_RUN).strip()
        backup_type = payload.get("backup_type")
        if operation not in {
            DATA_MANAGEMENT_OPERATION_BACKUP,
            DATA_MANAGEMENT_OPERATION_RESTORE,
            DATA_MANAGEMENT_OPERATION_MIGRATION,
            DATA_MANAGEMENT_OPERATION_DRY_RUN,
        }:
            return jsonify({"success": False, "error": "Unsupported data management operation."}), 400

        admin_user_id, admin_email = _get_admin_context()
        try:
            job = queue_data_management_job(
                operation,
                backup_type=backup_type,
                requested_by=admin_user_id,
                requested_by_email=admin_email,
                options=payload.get("options") if isinstance(payload.get("options"), dict) else {},
            )
            submitted = submit_data_management_job(current_app._get_current_object(), job.get("id"))
        except Exception as exc:
            log_event(
                "[DataManagement] Failed to queue data management job.",
                {"operation": operation, "error": str(exc)},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"success": False, "error": "Data Management job could not be queued."}), 400

        _log_data_management_admin_action(
            "data_management_job_queued",
            "Queued a Data Management job.",
            {"operation": operation, "backup_type": backup_type, "job_id": job.get("id"), "submitted": submitted},
        )
        public_job = sanitize_data_management_job_for_admin(job)
        public_job["submitted_to_executor"] = submitted
        return jsonify({"success": True, "job": public_job}), 202