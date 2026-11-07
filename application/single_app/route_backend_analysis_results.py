# route_backend_analysis_results.py
"""Authorized, complete-record readers for saved Analyze results."""

import logging

from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from flask import jsonify, request

from functions_appinsights import log_event
from functions_authentication import get_current_user_id, login_required, user_required
from functions_saved_analysis import (
    MAX_ANALYSIS_DIAGNOSTIC_PAGE_BYTES, MAX_ANALYSIS_PAGE_RECORDS, read_saved_analysis_page,
)
from functions_workflow_result_store import WorkflowResultStorageUnavailableError
from swagger_wrapper import get_auth_security, swagger_route


def register_route_backend_analysis_results(bp):
    @bp.route("/api/analysis_results", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_saved_analysis_result():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated."}), 401
        context = {
            name: str(request.args.get(name) or "").strip()
            for name in ("conversation_id", "message_id", "result_sha256")
        }
        if not all(context.values()):
            return jsonify({"error": "A conversation, message, and saved result are required."}), 400
        representation = str(request.args.get("representation") or "records").strip()
        diagnostic_transport = representation == "diagnostics"
        default_limit = MAX_ANALYSIS_DIAGNOSTIC_PAGE_BYTES if diagnostic_transport else 25
        maximum_limit = MAX_ANALYSIS_DIAGNOSTIC_PAGE_BYTES if diagnostic_transport else MAX_ANALYSIS_PAGE_RECORDS
        try:
            offset = int(request.args.get("offset", "0"))
            limit = int(request.args.get("limit", str(default_limit)))
        except ValueError:
            return jsonify({"error": "Page bounds must be integers."}), 400
        if (
            offset < 0 or not 1 <= limit <= maximum_limit
            or representation not in {"records", "evidence", "diagnostics"}
        ):
            return jsonify({"error": "The requested result page is invalid."}), 400
        try:
            page = read_saved_analysis_page(
                user_id, context, offset=offset, limit=limit,
                representation=representation, record_id=request.args.get("record_id"),
            )
            response = jsonify(page)
            if diagnostic_transport:
                response.headers["Cache-Control"] = "no-store"
            return response
        except PermissionError:
            return jsonify({"error": "Access to this saved analysis could not be confirmed."}), 403
        except (CosmosResourceNotFoundError, LookupError):
            return jsonify({"error": "This saved analysis is no longer available."}), 404
        except ValueError:
            return jsonify({"error": "This result or representation is not ready or has changed. Reload its analysis."}), 409
        except (AzureError, WorkflowResultStorageUnavailableError) as exc:
            log_event(
                "[DOCUMENT_ANALYSIS] Saved result reader is unavailable.",
                extra={**context, "error_type": type(exc).__name__},
                level=logging.ERROR,
            )
            return jsonify({"error": "Saved analysis storage is temporarily unavailable."}), 503
