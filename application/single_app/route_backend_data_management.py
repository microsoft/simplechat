# route_backend_data_management.py
"""Admin API routes for SimpleChat Data Management."""

import hmac
import logging

from flask import Response, current_app, jsonify, request, session

from functions_activity_logging import log_general_admin_action
from functions_appinsights import log_event
from functions_authentication import admin_required, get_current_user_id, login_required
from functions_data_management import (
    DATA_MANAGEMENT_OPERATION_BACKUP,
    DATA_MANAGEMENT_OPERATION_DRY_RUN,
    DATA_MANAGEMENT_OPERATION_MIGRATION,
    DATA_MANAGEMENT_OPERATION_RESTORE,
    DataManagementCosmosEditorError,
    DataManagementHistoryPaginationError,
    DataManagementSettingsValidationError,
    cleanup_expired_data_management_backups,
    create_data_management_migration_review_authorization,
    delete_data_management_backup,
    create_data_management_restore_review_authorization,
    export_data_management_migration_manifest,
    generate_data_management_encryption_key,
    get_data_management_cosmos_editor_containers,
    get_data_management_cosmos_editor_document,
    get_data_management_backup_summary,
    get_data_management_job_detail,
    get_data_management_job_progress,
    get_data_management_jobs_page,
    get_data_management_migration_catalog,
    get_data_management_migration_review_fingerprint,
    get_data_management_restore_review_fingerprint,
    get_data_management_settings,
    log_data_management_cosmos_editor_activity,
    preview_data_management_migration_plan,
    queue_data_management_job,
    query_data_management_cosmos_editor_documents,
    request_data_management_job_cancellation,
    release_data_management_migration_review_reservation,
    release_data_management_restore_review_reservation,
    reserve_data_management_migration_review_authorization,
    reserve_data_management_restore_review_authorization,
    review_data_management_migration,
    review_data_management_restore,
    retry_data_management_backup_job,
    resolve_data_management_migration_manifest_item,
    retry_data_management_migration_job,
    retry_data_management_restore_job,
    sanitize_data_management_job_for_admin,
    sanitize_data_management_settings_for_admin,
    save_data_management_cosmos_editor_document,
    summarize_data_management_migration_plan,
    submit_data_management_job,
    test_backup_storage_connection,
    test_target_cosmos_capacity_management,
    test_target_cosmos_connection,
    test_target_enhanced_citation_storage_connection,
    test_target_search_connection,
    update_data_management_settings,
)
from swagger_wrapper import get_auth_security, swagger_route


DATA_MANAGEMENT_HISTORY_VALIDATION_ERROR = (
    "Data Management history filters or continuation token are invalid."
)


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


def _get_cosmos_editor_payload():
    payload = request.get_json(silent=True) or {}
    return payload if isinstance(payload, dict) else {}


def _get_history_filters(list_kind):
    filters = {
        "status": request.args.get("status"),
        "scheduled": request.args.get("scheduled"),
        "created_from": request.args.get("created_from"),
        "created_to": request.args.get("created_to"),
    }
    if list_kind == "jobs":
        filters["operation"] = request.args.get("operation")
    else:
        filters["backup_type"] = request.args.get("backup_type")
    return filters


def _cosmos_editor_error_status(exc, default_status=400):
    status_code = getattr(exc, "status_code", None)
    if status_code == 404:
        return 404
    if status_code == 412:
        return 409
    return default_status


def _log_cosmos_editor_failure(action, message, details=None):
    admin_user_id, admin_email = _get_admin_context()
    log_data_management_cosmos_editor_activity(
        admin_user_id,
        admin_email,
        action,
        "failed",
        message,
        details=details or {},
    )


def _sanitize_backup_cleanup_result_for_response(cleanup_result):
    if not isinstance(cleanup_result, dict):
        return {}

    sanitized = dict(cleanup_result)
    errors = sanitized.get("errors")
    if isinstance(errors, list):
        sanitized_errors = []
        for error_item in errors:
            if isinstance(error_item, dict):
                sanitized_errors.append({
                    "job_id": error_item.get("job_id"),
                    "error": "Backup cleanup failed for this item.",
                })
            else:
                sanitized_errors.append({
                    "error": "Backup cleanup failed for this item.",
                })
        sanitized["errors"] = sanitized_errors
    return sanitized


def register_route_backend_data_management(bp):
    @bp.route("/api/admin/data-management/settings", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def get_admin_data_management_settings():
        settings = get_data_management_settings()
        return jsonify({
            "success": True,
            "settings": sanitize_data_management_settings_for_admin(settings),
        }), 200

    @bp.route("/api/admin/data-management/settings", methods=["PUT"])
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

    @bp.route("/api/admin/data-management/encryption-key", methods=["POST"])
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

    @bp.route("/api/admin/data-management/storage/test", methods=["POST"])
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

    @bp.route("/api/admin/data-management/target/cosmos/test", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def test_admin_data_management_target_cosmos():
        payload = request.get_json(silent=True) or {}
        settings_payload = payload.get("settings") if isinstance(payload.get("settings"), dict) else None
        migration_plan = payload.get("migration_plan") if isinstance(payload.get("migration_plan"), dict) else None
        try:
            result = test_target_cosmos_connection(
                settings=settings_payload,
                migration_plan=migration_plan,
            )
        except Exception as exc:
            log_event(
                "[DataManagement] Target Cosmos connection test failed.",
                {"error": str(exc)},
                level=logging.WARNING,
            )
            return jsonify({"success": False, "error": "Target Cosmos connection test failed."}), 400
        return jsonify(result), 200

    @bp.route("/api/admin/data-management/target/cosmos/ru-boost/test", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def test_admin_data_management_target_cosmos_ru_boost():
        payload = request.get_json(silent=True) or {}
        settings_payload = payload.get("settings") if isinstance(payload.get("settings"), dict) else None
        migration_plan = payload.get("migration_plan") if isinstance(payload.get("migration_plan"), dict) else None
        try:
            result = test_target_cosmos_capacity_management(
                settings=settings_payload,
                migration_plan=migration_plan,
            )
        except DataManagementSettingsValidationError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except Exception as exc:
            log_event(
                "[DataManagement] Target Cosmos RU Boost permission test failed.",
                {"error": str(exc)},
                level=logging.WARNING,
            )
            return jsonify({"success": False, "error": "Target Cosmos RU Boost permission test failed."}), 400
        return jsonify(result), 200

    @bp.route("/api/admin/data-management/target/search/test", methods=["POST"])
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

    @bp.route("/api/admin/data-management/target/enhanced-citation-storage/test", methods=["POST"])
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

    @bp.route("/api/admin/data-management/cosmos-editor/containers", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def list_admin_data_management_cosmos_editor_containers():
        return jsonify({
            "success": True,
            "containers": get_data_management_cosmos_editor_containers(),
        }), 200

    @bp.route("/api/admin/data-management/cosmos-editor/danger-acknowledgement", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def acknowledge_admin_data_management_cosmos_editor_danger():
        admin_user_id, admin_email = _get_admin_context()
        log_data_management_cosmos_editor_activity(
            admin_user_id,
            admin_email,
            "cosmos_editor_danger_acknowledged",
            "success",
            "Acknowledged the Cosmos DB editor danger prompt.",
            {"prompt": "interface_entry"},
        )
        return jsonify({"success": True}), 200

    @bp.route("/api/admin/data-management/cosmos-editor/query", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def query_admin_data_management_cosmos_editor_documents():
        payload = _get_cosmos_editor_payload()
        admin_user_id, admin_email = _get_admin_context()
        try:
            result = query_data_management_cosmos_editor_documents(
                payload.get("container"),
                query_text=payload.get("query"),
                page_size=payload.get("page_size"),
                continuation_token=payload.get("continuation_token"),
                admin_user_id=admin_user_id,
                admin_email=admin_email,
            )
        except DataManagementCosmosEditorError as exc:
            _log_cosmos_editor_failure(
                "cosmos_editor_query_rejected",
                "Rejected a Cosmos DB editor query.",
                {"container": payload.get("container"), "error": str(exc)},
            )
            return jsonify({"success": False, "error": "Cosmos DB editor query was rejected."}), 400
        except Exception as exc:
            log_event(
                "[DataManagement] Cosmos editor query failed.",
                {"container": payload.get("container"), "error": str(exc)},
                level=logging.WARNING,
            )
            _log_cosmos_editor_failure(
                "cosmos_editor_query_failed",
                "Cosmos DB editor query failed.",
                {"container": payload.get("container"), "status_code": getattr(exc, "status_code", None), "error": str(exc)},
            )
            return jsonify({"success": False, "error": "Cosmos DB editor query failed."}), _cosmos_editor_error_status(exc)
        return jsonify({"success": True, **result}), 200

    @bp.route("/api/admin/data-management/cosmos-editor/document", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def get_admin_data_management_cosmos_editor_document():
        payload = _get_cosmos_editor_payload()
        admin_user_id, admin_email = _get_admin_context()
        try:
            result = get_data_management_cosmos_editor_document(
                payload.get("container"),
                payload.get("id"),
                payload.get("partition_key"),
                admin_user_id=admin_user_id,
                admin_email=admin_email,
            )
        except DataManagementCosmosEditorError as exc:
            log_event(
                "[DataManagement] Cosmos editor document open rejected.",
                {"container": payload.get("container"), "document_id": payload.get("id"), "error": str(exc)},
                level=logging.WARNING,
            )
            _log_cosmos_editor_failure(
                "cosmos_editor_document_rejected",
                "Rejected a Cosmos DB editor document open request.",
                {"container": payload.get("container"), "document_id": payload.get("id"), "error": str(exc)},
            )
            return jsonify({"success": False, "error": "Cosmos DB document request was invalid."}), 400
        except Exception as exc:
            status_code = _cosmos_editor_error_status(exc, default_status=400)
            log_event(
                "[DataManagement] Cosmos editor document open failed.",
                {"container": payload.get("container"), "document_id": payload.get("id"), "error": str(exc)},
                level=logging.WARNING,
            )
            _log_cosmos_editor_failure(
                "cosmos_editor_document_failed",
                "Cosmos DB editor document open failed.",
                {"container": payload.get("container"), "document_id": payload.get("id"), "status_code": getattr(exc, "status_code", None), "error": str(exc)},
            )
            error_message = "Cosmos DB document was not found." if status_code == 404 else "Cosmos DB document could not be opened."
            return jsonify({"success": False, "error": error_message}), status_code
        return jsonify({"success": True, **result}), 200

    @bp.route("/api/admin/data-management/cosmos-editor/document", methods=["PUT"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def save_admin_data_management_cosmos_editor_document():
        payload = _get_cosmos_editor_payload()
        admin_user_id, admin_email = _get_admin_context()
        try:
            result = save_data_management_cosmos_editor_document(
                payload.get("container"),
                payload.get("id"),
                payload.get("partition_key"),
                payload.get("etag"),
                payload.get("document"),
                confirmation_accepted=payload.get("confirmation_accepted") is True,
                confirmation_phrase=payload.get("confirmation_phrase"),
                admin_user_id=admin_user_id,
                admin_email=admin_email,
            )
        except DataManagementCosmosEditorError as exc:
            _log_cosmos_editor_failure(
                "cosmos_editor_save_rejected",
                "Rejected a Cosmos DB editor save request.",
                {"container": payload.get("container"), "document_id": payload.get("id"), "error": str(exc)},
            )
            return jsonify({"success": False, "error": "Cosmos DB document save request was rejected."}), 400
        except Exception as exc:
            status_code = _cosmos_editor_error_status(exc, default_status=400)
            log_event(
                "[DataManagement] Cosmos editor save failed.",
                {"container": payload.get("container"), "document_id": payload.get("id"), "error": str(exc)},
                level=logging.WARNING,
                exceptionTraceback=True,
            )
            _log_cosmos_editor_failure(
                "cosmos_editor_save_failed",
                "Cosmos DB editor save failed.",
                {"container": payload.get("container"), "document_id": payload.get("id"), "status_code": getattr(exc, "status_code", None), "error": str(exc)},
            )
            if status_code == 409:
                error_message = "Cosmos DB document changed after it was opened. Refresh before saving again."
            elif status_code == 404:
                error_message = "Cosmos DB document was not found."
            else:
                error_message = "Cosmos DB document could not be saved."
            return jsonify({"success": False, "error": error_message}), status_code
        return jsonify({"success": True, **result}), 200

    @bp.route("/api/admin/data-management/jobs", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def list_admin_data_management_jobs():
        page_size = request.args.get("page_size", request.args.get("limit", 25))
        try:
            page = get_data_management_jobs_page(
                page_size=page_size,
                continuation_token=request.args.get("continuation_token"),
                filters=_get_history_filters("jobs"),
            )
        except DataManagementHistoryPaginationError:
            return jsonify({
                "success": False,
                "error": DATA_MANAGEMENT_HISTORY_VALIDATION_ERROR,
            }), 400
        return jsonify({
            "success": True,
            "jobs": page["items"],
            "pagination": page["pagination"],
            "filters": page["filters"],
        }), 200

    @bp.route("/api/admin/data-management/jobs/<job_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def get_admin_data_management_job_detail(job_id):
        detail = get_data_management_job_detail(job_id)
        if not detail:
            return jsonify({"success": False, "error": "Data Management job was not found."}), 404
        return jsonify({"success": True, **detail}), 200

    @bp.route("/api/admin/data-management/jobs/<job_id>/progress", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def get_admin_data_management_job_progress(job_id):
        progress = get_data_management_job_progress(job_id)
        if not progress:
            return jsonify({"success": False, "error": "Data Management job was not found."}), 404
        return jsonify({"success": True, "job": progress}), 200

    @bp.route("/api/admin/data-management/jobs/<job_id>/migration-manifest", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def download_admin_data_management_migration_manifest(job_id):
        statuses = {
            status.strip().lower()
            for status in str(request.args.get("statuses") or "").split(",")
            if status.strip()
        }
        try:
            export = export_data_management_migration_manifest(job_id, statuses=statuses)
        except DataManagementSettingsValidationError as exc:
            return jsonify({"success": False, "error": str(exc)}), 404
        response = Response(
            export["content"],
            status=200,
            content_type="application/x-ndjson; charset=utf-8",
        )
        suffix = "-failures" if statuses else ""
        response.headers["Content-Disposition"] = (
            f'attachment; filename="migration-{job_id}{suffix}.jsonl"'
        )
        response.headers["X-Migration-Manifest-Entries"] = str(export["entry_count"])
        return response

    @bp.route(
        "/api/admin/data-management/jobs/<job_id>/migration-manifest/items/<item_ref>",
        methods=["GET"],
    )
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def resolve_admin_data_management_migration_manifest_item(job_id, item_ref):
        try:
            item = resolve_data_management_migration_manifest_item(job_id, item_ref)
        except DataManagementSettingsValidationError as exc:
            return jsonify({"success": False, "error": str(exc)}), 404
        return jsonify({"success": True, "item": item}), 200

    @bp.route("/api/admin/data-management/jobs/<job_id>/retry", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def retry_admin_data_management_migration_job(job_id):
        try:
            existing_job = get_data_management_job_detail(job_id)
            operation = (
                (existing_job.get("job") or {}).get("operation")
                if isinstance(existing_job, dict) else
                ""
            )
            if operation == DATA_MANAGEMENT_OPERATION_BACKUP:
                job = retry_data_management_backup_job(job_id)
            elif operation == DATA_MANAGEMENT_OPERATION_RESTORE:
                job = retry_data_management_restore_job(job_id)
            else:
                job = retry_data_management_migration_job(job_id)
            submitted = submit_data_management_job(current_app._get_current_object(), job.get("id"))
        except DataManagementSettingsValidationError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except Exception as exc:
            log_event(
                "[DataManagement] Failed to retry durable job.",
                {"job_id": job_id, "error": str(exc)},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"success": False, "error": "Data Management job retry could not be queued."}), 400

        _log_data_management_admin_action(
            "data_management_job_retry_queued",
            "Queued a Data Management job retry from durable checkpoints.",
            {"job_id": job.get("id"), "operation": job.get("operation"), "submitted": submitted},
        )
        public_job = sanitize_data_management_job_for_admin(job)
        public_job["submitted_to_executor"] = submitted
        return jsonify({"success": True, "job": public_job}), 202

    @bp.route("/api/admin/data-management/jobs/<job_id>/cancel", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def cancel_admin_data_management_migration_job(job_id):
        payload = request.get_json(silent=True) or {}
        admin_user_id, admin_email = _get_admin_context()
        try:
            job = request_data_management_job_cancellation(
                job_id,
                requested_by=admin_user_id,
                requested_by_email=admin_email,
                reason=payload.get("reason"),
            )
        except DataManagementSettingsValidationError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except Exception as exc:
            log_event(
                "[DataManagement] Failed to request Data Management job cancellation.",
                {"job_id": job_id, "error": str(exc)},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"success": False, "error": "Data Management job cancellation could not be requested."}), 400

        _log_data_management_admin_action(
            "data_management_job_cancel_requested",
            "Requested cancellation of a Data Management job.",
            {"job_id": job.get("id"), "operation": job.get("operation"), "status": job.get("status")},
        )
        return jsonify({"success": True, "job": sanitize_data_management_job_for_admin(job)}), 202

    @bp.route("/api/admin/data-management/backups", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def list_admin_data_management_backups():
        page_size = request.args.get("page_size", request.args.get("limit", 25))
        try:
            backup_summary = get_data_management_backup_summary(
                limit=page_size,
                continuation_token=request.args.get("continuation_token"),
                filters=_get_history_filters("backups"),
            )
        except DataManagementHistoryPaginationError:
            return jsonify({
                "success": False,
                "error": DATA_MANAGEMENT_HISTORY_VALIDATION_ERROR,
            }), 400
        return jsonify({"success": True, **backup_summary}), 200

    @bp.route("/api/admin/data-management/backups/retention/cleanup", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def cleanup_admin_data_management_backups():
        admin_user_id, admin_email = _get_admin_context()
        try:
            cleanup_result = cleanup_expired_data_management_backups(
                requested_by=admin_user_id,
                requested_by_email=admin_email,
                manual_execution=True,
            )
        except DataManagementSettingsValidationError as exc:
            log_event(
                "[DataManagement] Manual backup retention cleanup validation failed.",
                {"error": str(exc)},
                level=logging.WARNING,
            )
            return jsonify({"success": False, "error": "Backup retention cleanup request is invalid."}), 400
        except Exception as exc:
            log_event(
                "[DataManagement] Manual backup retention cleanup failed.",
                {"error": str(exc)},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"success": False, "error": "Backup retention cleanup could not be completed."}), 400

        _log_data_management_admin_action(
            "data_management_backup_retention_cleanup",
            "Ran Data Management backup retention cleanup.",
            {
                "deleted_count": cleanup_result.get("deleted_count", 0),
                "candidate_count": cleanup_result.get("candidate_count", 0),
                "error_count": len(cleanup_result.get("errors") or []),
            },
        )
        public_cleanup_result = _sanitize_backup_cleanup_result_for_response(cleanup_result)
        if cleanup_result.get("success") is False:
            return jsonify({
                "success": False,
                "error": "Backup retention cleanup completed with errors.",
                "cleanup": public_cleanup_result,
            }), 400
        return jsonify({"success": True, "cleanup": public_cleanup_result}), 200

    @bp.route("/api/admin/data-management/backups/<backup_id>", methods=["DELETE"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def delete_admin_data_management_backup(backup_id):
        payload = request.get_json(silent=True) or {}
        admin_user_id, admin_email = _get_admin_context()
        try:
            cleanup_result = delete_data_management_backup(
                backup_id,
                requested_by=admin_user_id,
                requested_by_email=admin_email,
                reason=payload.get("reason") if isinstance(payload, dict) else "manual",
            )
        except DataManagementSettingsValidationError as exc:
            log_event(
                "[DataManagement] Backup deletion validation failed.",
                {"backup_id": backup_id, "error": str(exc)},
                level=logging.WARNING,
            )
            return jsonify({"success": False, "error": "Backup deletion request is invalid."}), 400
        except Exception as exc:
            log_event(
                "[DataManagement] Backup deletion failed.",
                {"backup_id": backup_id, "error": str(exc)},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"success": False, "error": "Backup could not be deleted."}), 400

        _log_data_management_admin_action(
            "data_management_backup_deleted",
            "Deleted a Data Management backup.",
            {
                "job_id": cleanup_result.get("job_id"),
                "backup_type": cleanup_result.get("backup_type"),
                "deleted_blob_count": cleanup_result.get("deleted_blob_count", 0),
                "job_item_deleted_count": cleanup_result.get("job_item_deleted_count", 0),
                "latest_item_state_deleted_count": cleanup_result.get("latest_item_state_deleted_count", 0),
            },
        )
        return jsonify({"success": True, "cleanup": cleanup_result}), 200

    @bp.route("/api/admin/data-management/migration/catalog/<target_type>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def get_admin_data_management_migration_catalog(target_type):
        search = request.args.get("search", "")
        limit = request.args.get("page_size", request.args.get("limit", 25))
        continuation_token = request.args.get("continuation_token", "")
        try:
            catalog = get_data_management_migration_catalog(
                target_type,
                search_text=search,
                limit=limit,
                continuation_token=continuation_token,
            )
        except DataManagementSettingsValidationError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        return jsonify({"success": True, **catalog}), 200

    @bp.route("/api/admin/data-management/restore/review", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def review_admin_data_management_restore():
        payload = request.get_json(silent=True) or {}
        restore_plan = payload.get("restore_plan") if isinstance(payload.get("restore_plan"), dict) else {}
        try:
            review = review_data_management_restore(restore_plan)
        except Exception as exc:
            log_event(
                "[DataManagement] Restore review failed.",
                {"error": str(exc)},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({"success": False, "error": "Restore review could not be completed."}), 400
        return jsonify({"success": True, "review": review}), 200

    @bp.route("/api/admin/data-management/migration/summary", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def summarize_admin_data_management_migration():
        payload = request.get_json(silent=True) or {}
        try:
            summary = summarize_data_management_migration_plan(payload)
            preview = None
            if payload.get("include_inventory") is True:
                preview = preview_data_management_migration_plan(
                    get_data_management_settings(),
                    payload,
                )
        except DataManagementSettingsValidationError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except Exception as exc:
            log_event(
                "[DataManagement] Migration inventory preview failed.",
                {"error": str(exc)},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({
                "success": False,
                "error": "Migration inventory preview could not be completed.",
            }), 400
        return jsonify({"success": True, "summary": summary, "preview": preview}), 200

    @bp.route("/api/admin/data-management/migration/review", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def review_admin_data_management_migration():
        payload = request.get_json(silent=True) or {}
        try:
            review = review_data_management_migration(
                settings=(
                    payload.get("settings")
                    if isinstance(payload.get("settings"), dict)
                    else None
                ),
                migration_plan=(
                    payload.get("migration_plan")
                    if isinstance(payload.get("migration_plan"), dict)
                    else None
                ),
            )
            if review.get("ready") is True:
                admin_user_id, _admin_email = _get_admin_context()
                review.update(
                    create_data_management_migration_review_authorization(
                        admin_user_id,
                        review.get("review_fingerprint"),
                    )
                )
        except DataManagementSettingsValidationError as exc:
            log_event(
                "[DataManagement] Migration review validation failed.",
                {"error_type": type(exc).__name__},
                level=logging.WARNING,
                exceptionTraceback=True,
            )
            return jsonify({
                "success": False,
                "error": "Migration review input is invalid.",
                "workflow_step": "review",
            }), 400
        except Exception as exc:
            log_event(
                "[DataManagement] Migration review failed.",
                {"error_type": type(exc).__name__},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({
                "success": False,
                "error": "Migration review could not be completed.",
                "workflow_step": "review",
            }), 400
        return jsonify({"success": True, "review": review}), 200

    @bp.route("/api/admin/data-management/restore/review", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def review_admin_data_management_restore():
        payload = request.get_json(silent=True) or {}
        try:
            review = review_data_management_restore(
                settings=(
                    payload.get("settings")
                    if isinstance(payload.get("settings"), dict)
                    else None
                ),
                restore_plan=(
                    payload.get("restore_plan")
                    if isinstance(payload.get("restore_plan"), dict)
                    else None
                ),
            )
            if review.get("ready") is True:
                admin_user_id, _admin_email = _get_admin_context()
                review.update(
                    create_data_management_restore_review_authorization(
                        admin_user_id,
                        review.get("review_fingerprint"),
                    )
                )
        except DataManagementSettingsValidationError as exc:
            log_event(
                "[DataManagement] Restore review validation failed.",
                {"error_type": type(exc).__name__},
                level=logging.WARNING,
                exceptionTraceback=True,
            )
            return jsonify({
                "success": False,
                "error": "Restore review input is invalid.",
                "workflow_step": "review",
            }), 400
        except Exception as exc:
            log_event(
                "[DataManagement] Restore review failed.",
                {"error_type": type(exc).__name__},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({
                "success": False,
                "error": "Restore review could not be completed.",
                "workflow_step": "review",
            }), 400
        return jsonify({"success": True, "review": review}), 200

    @bp.route("/api/admin/data-management/jobs", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def create_admin_data_management_job():
        payload = request.get_json(silent=True) or {}
        operation = str(payload.get("operation") or DATA_MANAGEMENT_OPERATION_DRY_RUN).strip()
        backup_type = payload.get("backup_type")
        review_reservation = None
        review_authorization_token = ""
        review_reservation_release = None
        if operation not in {
            DATA_MANAGEMENT_OPERATION_BACKUP,
            DATA_MANAGEMENT_OPERATION_RESTORE,
            DATA_MANAGEMENT_OPERATION_MIGRATION,
            DATA_MANAGEMENT_OPERATION_DRY_RUN,
        }:
            return jsonify({"success": False, "error": "Unsupported data management operation."}), 400

        admin_user_id, admin_email = _get_admin_context()
        try:
            job_options = (
                dict(payload.get("options"))
                if isinstance(payload.get("options"), dict)
                else {}
            )
            if operation == DATA_MANAGEMENT_OPERATION_MIGRATION:
                provided_review_fingerprint = str(
                    job_options.get("review_fingerprint") or ""
                ).strip()
                review_authorization_token = str(
                    job_options.get("review_authorization_token") or ""
                ).strip()
                expected_review_fingerprint = (
                    get_data_management_migration_review_fingerprint(
                        migration_plan=(
                            job_options.get("migration_plan")
                            if isinstance(
                                job_options.get("migration_plan"),
                                dict,
                            )
                            else None
                        ),
                    )
                )
                if (
                    not provided_review_fingerprint or
                    not hmac.compare_digest(
                        provided_review_fingerprint,
                        expected_review_fingerprint,
                    )
                ):
                    return jsonify({
                        "success": False,
                        "error": (
                            "Migration inputs changed after preflight review. "
                            "Run review again before execution."
                        ),
                        "workflow_step": "review",
                    }), 409
                try:
                    review_reservation = (
                        reserve_data_management_migration_review_authorization(
                            review_authorization_token,
                            admin_user_id,
                            expected_review_fingerprint,
                        )
                    )
                    job_options["review_reservation_token"] = (
                        review_reservation["reservation_token"]
                    )
                    review_reservation_release = release_data_management_migration_review_reservation
                except DataManagementSettingsValidationError as exc:
                    log_event(
                        "[DataManagement] Migration review reservation validation failed.",
                        {"operation": operation, "error": str(exc)},
                        level=logging.WARNING,
                    )
                    return jsonify({
                        "success": False,
                        "error": "Migration review authorization is invalid or expired. Run review again before execution.",
                        "workflow_step": "review",
                    }), 409
            elif operation == DATA_MANAGEMENT_OPERATION_RESTORE:
                provided_review_fingerprint = str(
                    job_options.get("review_fingerprint") or ""
                ).strip()
                review_authorization_token = str(
                    job_options.get("review_authorization_token") or ""
                ).strip()
                restore_plan = (
                    job_options.get("restore_plan")
                    if isinstance(job_options.get("restore_plan"), dict)
                    else None
                )
                expected_review_fingerprint = (
                    get_data_management_restore_review_fingerprint(
                        restore_plan=restore_plan,
                    )
                )
                if (
                    not provided_review_fingerprint or
                    not hmac.compare_digest(
                        provided_review_fingerprint,
                        expected_review_fingerprint,
                    )
                ):
                    return jsonify({
                        "success": False,
                        "error": (
                            "Restore inputs changed after preflight review. "
                            "Run review again before execution."
                        ),
                        "workflow_step": "review",
                    }), 409
                try:
                    review_reservation = (
                        reserve_data_management_restore_review_authorization(
                            review_authorization_token,
                            admin_user_id,
                            expected_review_fingerprint,
                        )
                    )
                    job_options["review_reservation_token"] = (
                        review_reservation["reservation_token"]
                    )
                    review_reservation_release = release_data_management_restore_review_reservation
                except DataManagementSettingsValidationError as exc:
                    log_event(
                        "[DataManagement] Restore review reservation validation failed.",
                        {"operation": operation, "error": str(exc)},
                        level=logging.WARNING,
                    )
                    return jsonify({
                        "success": False,
                        "error": "Restore review authorization is invalid or expired. Run review again before execution.",
                        "workflow_step": "review",
                    }), 409
            try:
                job = queue_data_management_job(
                    operation,
                    backup_type=backup_type,
                    requested_by=admin_user_id,
                    requested_by_email=admin_email,
                    options=job_options,
                    occurrence_id=(
                        review_reservation.get("job_id")
                        if review_reservation
                        else None
                    ),
                )
            except Exception:
                if review_reservation and review_reservation_release:
                    review_reservation_release(
                        review_authorization_token,
                        review_reservation["reservation_token"],
                    )
                raise
            submitted = submit_data_management_job(current_app._get_current_object(), job.get("id"))
        except DataManagementSettingsValidationError as exc:
            log_event(
                "[DataManagement] Validation error while queuing data management job.",
                {"operation": operation, "error": str(exc)},
                level=logging.WARNING,
            )
            response = {
                "success": False,
                "error": "Data Management job request is invalid.",
            }
            if operation in {DATA_MANAGEMENT_OPERATION_MIGRATION, DATA_MANAGEMENT_OPERATION_RESTORE}:
                response["workflow_step"] = "confirm"
            return jsonify(response), 400
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
