# test_model_ca_bundle_routes_integration.py
"""
Real cold application/Blueprint CA authorization and storage integration.
Version: 0.261.052
Implemented in: 0.261.052

Runs in fresh normal/optimized processes. Only external storage/config I/O is
substituted; application modules, auth decorators, Blueprint, and registry are real.
"""

from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def run_offline():
    from datetime import datetime, timedelta, timezone
    from unittest.mock import patch

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from test_support.offline_bootstrap import offline_app_imports
    from test_model_endpoint_ca_bundles import BlobContainer, Container

    with offline_app_imports() as offline:
        import app
        from flask import Blueprint, Flask
        import functions_authentication as authentication
        import functions_settings as settings
        import route_backend_model_ca_bundles as routes
        from model_endpoint_ca_bundles import CABundleRegistry
        from model_endpoint_clients import build_custom_endpoint_ssl_context
        from model_endpoint_ca_bundles import ManagedCABundle

        web = Flask("ca-route-integration")
        web.secret_key = "offline-ca-route"
        blueprint = Blueprint("ca_routes", __name__)
        blueprint.before_request(authentication.user_required_blueprint())
        routes.register_route_backend_model_ca_bundles(blueprint)
        web.register_blueprint(blueprint)
        client = web.test_client()
        metadata, blob = Container(), BlobContainer()
        sources = {kind: Container() for kind in ("settings", "user_settings", "groups")}
        registry = CABundleRegistry(
            metadata, lambda: blob, sources,
            global_source_fence=lambda etag: None, log=lambda *args, **kwargs: None,
        )
        configuration = {
            "enable_multi_model_endpoints": True, "allow_user_custom_endpoints": True,
            "allow_group_custom_endpoints": True, "enable_enhanced_citations": False,
        }
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Offline root")])
        now = datetime.now(timezone.utc)
        pem = (
            x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)
        )
        denied_store_calls = []

        def store_for_operation(config):
            denied_store_calls.append(True)
            return registry

        with (
            patch.object(routes, "get_settings", return_value=configuration),
            patch.object(routes, "get_model_endpoint_ca_bundle_registry", side_effect=store_for_operation),
            patch.object(routes, "ensure_governance_access"),
            patch.object(authentication, "check_user_access_status", return_value=(True, "")),
            patch.object(authentication, "get_settings", return_value=configuration),
            patch.object(settings, "get_settings", return_value=configuration),
            patch.object(routes, "log_event"),
        ):
            for method, path in (
                ("GET", "/api/model-ca-bundles"),
                ("POST", "/api/model-ca-bundles"),
                ("PUT", "/api/model-ca-bundles/ca-0123456789abcdef0123456789abcdef"),
                ("DELETE", "/api/model-ca-bundles/ca-0123456789abcdef0123456789abcdef"),
            ):
                response = client.open(path, method=method)
                require(response.status_code in (302, 401, 403), "Anonymous CA operation was allowed.")
            require(not denied_store_calls, "Anonymous request reached certificate storage.")
            with client.session_transaction() as session:
                session["user"] = {"oid": "user-one", "roles": ["User"]}
            response = client.get("/api/model-ca-bundles")
            require(response.status_code == 403, "Non-admin certificate management was allowed.")
            require(not denied_store_calls, "Non-admin request reached certificate storage.")
            with client.session_transaction() as session:
                session["user"] = {"oid": "admin-one", "roles": ["Admin"]}
            response = client.post("/api/model-ca-bundles", data={
                "name": "Offline root", "file": (BytesIO(pem), "root.pem"),
            })
            require(response.status_code == 201, "Admin certificate upload failed.")
            created = response.get_json()["bundle"]
            require("BEGIN CERTIFICATE" not in str(created), "Certificate bytes escaped the storage boundary.")
            body, revision, digest = registry.resolve(created["id"])
            context = build_custom_endpoint_ssl_context(ManagedCABundle(created["id"], revision, digest, body))
            require(context.check_hostname, "Managed CA trust disabled hostname verification.")
            require(context.cert_store_stats()["x509_ca"] == 1, "Managed CA unexpectedly appended public roots.")
            response = client.get("/api/user/models/ca-bundle-options")
            require(response.status_code == 200, f"Authorized certificate choices failed: {response.status_code}, {response.get_json()}.")
            options = response.get_json()["bundles"]
            require(options[0]["id"] == created["id"], "Stable bundle ID was not exposed.")
            require("certificates" not in options[0], "Workspace choices exposed admin certificate metadata.")
            configuration["allow_user_custom_endpoints"] = False
            calls_before = len(denied_store_calls)
            response = client.get("/api/user/models/ca-bundle-options")
            require(response.status_code == 400, "Disabled workspace did not use the standard disabled-feature response.")
            require(len(denied_store_calls) == calls_before, "Disabled workspace reached certificate storage.")
            configuration["allow_user_custom_endpoints"] = True
            import httpx
            import socket
            import functions_genai_mil as genai
            from test_genai_mil_profile import endpoint as genai_endpoint

            discovery_requests = []

            def discovery(request):
                discovery_requests.append(request)
                return httpx.Response(200, json={"data": [{"id": "Model-ID"}, {"id": "model-id"}]})

            with (
                patch.object(genai, "build_custom_openai_sync_http_client", side_effect=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(discovery))),
                patch.object(socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))]),
            ):
                discovered = genai.fetch_genai_mil_models(genai_endpoint(), configuration)
            require([model["modelName"] for model in discovered] == ["Model-ID", "model-id"], "Discovery changed exact scoped model identities.")
            require(str(discovery_requests[0].url) == "https://api.genai.mil/v1/models", "Discovery used the wrong protected API route.")
            require(discovery_requests[0].headers["Authorization"] == "Bearer synthetic-genai-key", "Discovery did not use scoped bearer-key authentication.")
            response = client.delete(f"/api/model-ca-bundles/{created['id']}", json={"expected_revision": 1})
            require(response.status_code == 200, "Unused certificate deletion failed.")
            require(not blob.items, "Certificate deletion did not clean shared storage.")
        require(not offline.network_attempts, "CA integration attempted external network access.")


@pytest.mark.parametrize("optimized", (False, True))
def test_ca_blueprint_and_real_storage_contract(optimized):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT), str(APP), str(TESTS)))
    env["PYTHONIOENCODING"] = "utf-8"
    command = [sys.executable, *(["-O"] if optimized else []), str(Path(__file__).resolve()), "--offline-probe"]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    require(result.returncode == 0, result.stdout + result.stderr)


if __name__ == "__main__" and "--offline-probe" in sys.argv:
    run_offline()
