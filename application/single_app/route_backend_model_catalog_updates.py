# route_backend_model_catalog_updates.py
"""Administrative signed-catalog update API."""

import logging

from flask import jsonify, request

from app_settings_store import SettingsConflictError, SettingsUnavailableError
from functions_appinsights import log_event
from functions_authentication import admin_required, get_current_user_id, login_required
from functions_settings import get_model_catalog_update_service
from model_catalog_package import CatalogUpdateError, MAX_PACKAGE_BYTES
from swagger_wrapper import get_auth_security, swagger_route


def register_catalog_update_routes(bp):
    @bp.route("/api/admin/model-catalog/updates", methods=["GET", "POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def model_catalog_updates():
        try:
            service = get_model_catalog_update_service()
            if request.method == "GET":
                return jsonify(service.status())
            if request.content_length is None or request.content_length > MAX_PACKAGE_BYTES + 65536:
                return jsonify(error="The catalog request exceeds its size limit."), 413
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                raise CatalogUpdateError("Provide a catalog update request.")
            operation = payload.get("operation")
            fields = {
                "online": {"enabled", "etag"}, "check": set(),
                "upload": {"package"}, "preview": {"digest"},
                "apply": {"digest", "etag"}, "rollback-preview": set(),
                "rollback": {"digest", "etag"},
            }
            if not isinstance(operation, str) or operation not in fields or set(payload) != fields[operation] | {"operation"}:
                raise CatalogUpdateError("The catalog request contains unsupported fields.")
            actor = get_current_user_id()
            if operation in {"online", "apply", "rollback"}:
                if not isinstance(payload["etag"], str) or not payload["etag"]:
                    raise CatalogUpdateError("Reload the catalog before saving.")
            if operation == "online":
                result = service.set_online(payload["enabled"], payload["etag"], actor)
            elif operation == "check":
                result = service.check(actor)
            elif operation == "upload":
                raw = payload["package"]
                if not isinstance(raw, str):
                    raise CatalogUpdateError("Choose a signed catalog package.")
                result = service.preview(raw.encode("utf-8"), actor)
            elif operation == "preview":
                result = service.preview_staged(payload["digest"])
            elif operation == "rollback-preview":
                result = service.rollback_target()
            else:
                result = service.activate(
                    payload["digest"], payload["etag"], actor, rollback=operation == "rollback",
                )
            return jsonify(result)
        except CatalogUpdateError as exc:
            return jsonify(error=exc.public_message), 400
        except SettingsConflictError:
            return jsonify(error="The catalog changed. Reload and preview again."), 409
        except SettingsUnavailableError:
            return jsonify(error="Unable to confirm the catalog save. Reload before retrying."), 503
        except Exception as exc:
            log_event("[MODELS] Catalog update failed.", level=logging.ERROR, extra={
                "error_type": type(exc).__name__,
            })
            return jsonify(error="Unable to complete the catalog operation. Reload and retry."), 503
