# route_backend_model_ca_bundles.py
"""Admin-owned CA management and scope-authorized certificate choices."""

import logging
import re

from azure.core.exceptions import AzureError
from flask import jsonify, request

from functions_appinsights import log_event
from functions_authentication import admin_required, enabled_required, get_current_user_id, login_required, user_required
from functions_governance import ensure_governance_access
from functions_group import assert_group_role, require_active_group
from functions_settings import get_model_endpoint_ca_bundle_registry, get_settings
from model_endpoint_ca_bundles import CABundleError, MAX_CA_BYTES
from swagger_wrapper import get_auth_security, swagger_route


def _revision(value):
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,9}", value):
        return int(value)
    raise CABundleError("ca_bundle_invalid", "Reload the bundle and supply its current revision.")


def _certificate_file(*, required):
    upload = request.files.get("file")
    if upload is None:
        if required:
            raise CABundleError("ca_bundle_invalid", "Choose a PEM CA certificate file.")
        return None
    return upload.read(MAX_CA_BYTES + 1)


def register_route_backend_model_ca_bundles(bp):
    def execute(operation, *, status=200):
        try:
            registry = get_model_endpoint_ca_bundle_registry(get_settings())
            return jsonify(operation(registry)), status
        except CABundleError as error:
            log_event(
                "[MODEL_CA_BUNDLES] Certificate operation rejected.",
                extra={"code": error.code, "actor_id": get_current_user_id()},
                level=logging.WARNING if error.status < 500 else logging.ERROR,
            )
            return jsonify(error.payload), error.status
        except (AzureError, OSError) as error:
            log_event(
                "[MODEL_CA_BUNDLES] Certificate storage operation failed.",
                extra={"error_type": type(error).__name__, "actor_id": get_current_user_id()},
                level=logging.ERROR,
            )
            return jsonify({
                "error": "Unable to confirm the certificate operation. Refresh the manager and verify before retrying.",
                "error_code": "ca_bundle_storage",
            }), 503

    def options(scope):
        settings = get_settings()
        flag = {"user": "allow_user_custom_endpoints", "group": "allow_group_custom_endpoints"}.get(scope)
        if not settings.get("enable_multi_model_endpoints") or (flag and not settings.get(flag)):
            return jsonify({"error": "Model endpoint management is disabled for this scope."}), 403
        actor_id = get_current_user_id()
        try:
            ensure_governance_access(f"governance_{scope}_endpoints", actor_id)
            if scope == "group":
                group_id = require_active_group(actor_id)
                assert_group_role(actor_id, group_id, allowed_roles=("Owner", "Admin"))
        except (PermissionError, LookupError, ValueError):
            return jsonify({"error": "You do not have access to certificate choices for this endpoint scope."}), 403
        return execute(lambda registry: {"bundles": registry.list_bundles()})

    @bp.route("/api/model-ca-bundles", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @admin_required
    def list_model_ca_bundles():
        def list_details(registry):
            bundles = registry.list_bundles(details=True)
            for bundle in bundles:
                bundle["references"] = registry.references(bundle["id"])
            return {"bundles": bundles}
        return execute(list_details)

    @bp.route("/api/model-ca-bundles", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @admin_required
    def create_model_ca_bundle():
        return execute(
            lambda registry: {
                "bundle": registry.create(request.form.get("name"), _certificate_file(required=True), get_current_user_id()),
                "success": True,
            },
            status=201,
        )

    @bp.route("/api/model-ca-bundles/<bundle_id>", methods=["PUT"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @admin_required
    def replace_model_ca_bundle(bundle_id):
        return execute(lambda registry: {
            "bundle": registry.replace(
                bundle_id, request.form.get("name"), _certificate_file(required=False),
                _revision(request.form.get("expected_revision")), get_current_user_id(),
            ),
            "success": True,
        })

    @bp.route("/api/model-ca-bundles/<bundle_id>", methods=["DELETE"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @admin_required
    def delete_model_ca_bundle(bundle_id):
        def delete(registry):
            payload = request.get_json()
            if not isinstance(payload, dict):
                raise CABundleError("ca_bundle_invalid", "Supply the current CA bundle revision.")
            registry.delete(bundle_id, _revision(payload.get("expected_revision")), get_current_user_id())
            return {"success": True}
        return execute(delete)

    @bp.route("/api/models/ca-bundle-options", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @admin_required
    def global_model_ca_bundle_options():
        return options("global")

    @bp.route("/api/user/models/ca-bundle-options", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("allow_user_custom_endpoints")
    def user_model_ca_bundle_options():
        return options("user")

    @bp.route("/api/group/models/ca-bundle-options", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("allow_group_custom_endpoints")
    def group_model_ca_bundle_options():
        return options("group")
