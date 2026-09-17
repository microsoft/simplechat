# route_backend_action_auth.py
"""Private credential controls; never shared conversation messages or elicitation answers."""

import logging

from flask import jsonify, request

from functions_action_auth import ActionAuthConflict, ActionAuthStorageError, ActionCredentialsRequired
from functions_action_auth_state import (
    ActionAuthValidationError,
    cancel_action_auth_request,
    get_action_auth_request,
    preflight_action_auth,
    save_action_auth_credentials,
)
from functions_appinsights import log_event
from functions_authentication import get_current_user_id, login_required, user_required
from swagger_wrapper import get_auth_security, swagger_route


def register_route_backend_action_auth(bp):
    """Register under the application's user_required_blueprint security policy."""
    @bp.after_request
    def action_auth_no_store(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response

    def _payload():
        if not request.is_json or (request.content_length or 0) > 24576:
            raise ValueError("Invalid credential request.")
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ValueError("Invalid credential request.")
        return payload

    def _call(operation, *args):
        try:
            actor = get_current_user_id()
            if not actor:
                raise PermissionError()
            return jsonify(operation(actor, *args)), 200
        except ActionCredentialsRequired as error:
            return jsonify(error.to_payload()), 409
        except ActionAuthConflict as error:
            return jsonify({"error": error.safe_message, "error_code": error.code}), 409
        except ActionAuthValidationError as error:
            return jsonify({"error": error.safe_message, "error_code": error.code}), error.status_code
        except ActionAuthStorageError:
            return jsonify({
                "error": "Credential storage is unavailable. Please try again.",
                "error_code": "action_auth_storage_unavailable",
            }), 503
        except PermissionError:
            return jsonify({"error": "You are not permitted to use this authentication request."}), 403
        except LookupError:
            return jsonify({"error": "The action or authentication request is unavailable."}), 404
        except ValueError:
            return jsonify({"error": "Invalid action authentication request."}), 400
        except Exception as error:
            log_event(
                "[ACTION_AUTH] A private authentication operation failed.",
                level=logging.WARNING, extra={"error_type": type(error).__name__},
            )
            return jsonify({"error": "Action authentication is temporarily unavailable."}), 503

    @bp.route("/api/action-auth/preflight", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def action_auth_preflight():
        return _call(lambda actor: preflight_action_auth(actor, _payload()))

    @bp.route("/api/action-auth/requests/<request_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def action_auth_request_get(request_id):
        return _call(get_action_auth_request, request_id)

    @bp.route("/api/action-auth/requests/<request_id>/credentials", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def action_auth_credentials(request_id):
        return _call(lambda actor: save_action_auth_credentials(actor, request_id, _payload()))

    @bp.route("/api/action-auth/requests/<request_id>/cancel", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def action_auth_cancel(request_id):
        def cancel(actor):
            if request.content_length and _payload():
                raise ValueError("Cancellation does not accept credential values.")
            return cancel_action_auth_request(actor, request_id)

        return _call(cancel)
