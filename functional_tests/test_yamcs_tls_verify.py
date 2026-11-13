# test_yamcs_tls_verify.py
#!/usr/bin/env python3
"""
Functional tests for the Yamcs action's TLS verification setting.
Version: 0.261.062
Implemented in: 0.261.062

Runs real plugin and connection-test bodies with the pinned Yamcs/Requests
libraries and intercepted HTTP transport. Selected definitions avoid Azure
bootstrap; route_tests separately verifies the real route security policy.
This is request-behavior coverage, not an import-lifecycle test.
"""

import ast
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import itertools
import json
import logging
import os
from pathlib import Path
import re
import socket
import sys
from typing import Any, Callable, Dict, Iterable, List, Optional
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
import warnings

from flask import Flask, jsonify, request
import requests
from requests.adapters import HTTPAdapter
from yamcs.protobuf.instances import instances_service_pb2
from yamcs.protobuf.server import server_service_pb2


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
# Import the dependency-light app helpers with a temporary search path.
original_sys_path = list(sys.path)
sys.path.insert(0, str(APP_DIR))
try:
    import functions_yamcs_operations as operations
finally:
    sys.path[:] = original_sys_path

SERVER_URL = "https://yamcs.example.invalid/yamcs"
REQUESTS_BUNDLE = "example-requests-ca.pem"
CURL_BUNDLE = "example-curl-ca.pem"


class OfflineBasePlugin:
    def __init__(self, manifest=None):
        pass


def noop_decorator(*args, **kwargs):
    def decorate(function):
        return function

    return decorate


def load_definitions(path, definition_name, namespace):
    """Execute the real definition and its actual shared-operations imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    definitions = []
    found = False
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "functions_yamcs_operations":
            definitions.append(node)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name == definition_name:
            node.decorator_list = []
            definitions.append(node)
            found = True
    if not found:
        raise RuntimeError(f"Missing Yamcs definition: {definition_name}")
    module = ast.Module(body=definitions, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)


class OfflineTransport:
    def __init__(self, *, expire_login_token=False, reject_verified_requests=False):
        self.calls = []
        self.closed_sessions = []
        self.expire_login_token = expire_login_token
        self.reject_verified_requests = reject_verified_requests

    def send(self, prepared_request, **kwargs):
        path = urlsplit(prepared_request.url).path
        self.calls.append({
            "path": path,
            "verify": kwargs["verify"],
            "timeout": kwargs.get("timeout"),
            "proxies": kwargs.get("proxies"),
            "headers": dict(prepared_request.headers),
            "body": prepared_request.body,
        })
        if self.reject_verified_requests and kwargs["verify"] is not False:
            raise requests.exceptions.SSLError("Untrusted offline fixture certificate")

        response = requests.Response()
        response.status_code = 200
        response.url = prepared_request.url
        response.request = prepared_request
        if path == "/yamcs/auth/token":
            grant_type = parse_qs(prepared_request.body)["grant_type"][0]
            refreshed = grant_type == "refresh_token"
            response.headers["Content-Type"] = "application/json"
            response._content = json.dumps({
                "access_token": "refreshed-test-token" if refreshed else "login-test-token",
                "refresh_token": "example-refresh-token",
                "expires_in": 0 if self.expire_login_token and not refreshed else 3600,
            }).encode("utf-8")
        elif path == "/yamcs/api":
            response._content = server_service_pb2.GetServerInfoResponse().SerializeToString()
        elif path == "/yamcs/api/instances":
            message = instances_service_pb2.ListInstancesResponse()
            message.instances.add(name="simulator")
            response._content = message.SerializeToString()
        else:
            raise AssertionError(f"Unexpected offline Yamcs request: {path}")
        return response


@contextmanager
def offline_requests(environment, **transport_options):
    transport = OfflineTransport(**transport_options)
    original_close = requests.Session.close

    def send(adapter, prepared_request, **kwargs):
        return transport.send(prepared_request, **kwargs)

    def close(session):
        transport.closed_sessions.append(session)
        return original_close(session)

    with (
        warnings.catch_warnings(),
        patch.dict(os.environ, environment, clear=True),
        patch.object(HTTPAdapter, "send", send),
        patch.object(requests.Session, "close", close),
        patch("requests.sessions.get_netrc_auth", return_value=None),
        patch("yamcs.client.core.context.FixedDelay"),
        patch.object(socket.socket, "connect", side_effect=AssertionError("Unexpected network access")),
    ):
        yield transport


class YamcsTlsVerifyTests(unittest.TestCase):
    def setUp(self):
        plugin_namespace = {
            **globals(),
            "BasePlugin": OfflineBasePlugin,
            "kernel_function": noop_decorator,
            "plugin_function_logger": noop_decorator,
            "log_event": Mock(),
            "debug_print": Mock(),
        }
        load_definitions(
            APP_DIR / "semantic_kernel_plugins" / "yamcs_plugin.py",
            "YamcsPlugin",
            plugin_namespace,
        )
        self.plugin_class = plugin_namespace["YamcsPlugin"]
        route_namespace = {
            **globals(),
            "get_current_user_id": lambda: "offline-user",
            "_load_existing_plugin_for_test": Mock(return_value=None),
            "_resolve_plugin_secret_context": Mock(return_value=("offline-user", "user")),
            "_resolve_secret_value_for_action_test": lambda value, *args: value,
            "ACTION_AUTH_SECRET_SOURCES": {"action"},
            "ACTION_ADDITIONAL_SECRET_SOURCES": {"action-addset"},
            "ui_trigger_word": "Stored_In_KeyVault",
            "log_event": Mock(),
        }
        load_definitions(
            APP_DIR / "route_backend_plugins.py",
            "test_yamcs_connection",
            route_namespace,
        )
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.add_url_rule(
            "/test-yamcs",
            view_func=route_namespace["test_yamcs_connection"],
            methods=["POST"],
        )

    def build_plugin(self, tls_verify, auth_method="none", basic_auth=False):
        fields = {
            "server_url": SERVER_URL,
            "instance": "simulator",
            "auth_method": auth_method,
            "timeout": 17,
            "enable_basic_auth": basic_auth,
            "basic_auth_username": "example-proxy-user",
            "basic_auth_password": "example-proxy-password",
        }
        if tls_verify is not None:
            fields["tls_verify"] = tls_verify
        auth = {"type": "NoAuth"}
        if auth_method != "none":
            auth = {
                "type": "username_password" if auth_method == "username_password" else "key",
                "identity": "example-user",
                "key": "example-auth-secret",
            }
        return self.plugin_class({
            "name": "offline_yamcs",
            "type": "yamcs",
            "endpoint": SERVER_URL,
            "auth": auth,
            "additionalFields": fields,
        })

    def run_connection(self, path, tls_verify, auth_method="none", basic_auth=False):
        if path == "plugin":
            plugin = self.build_plugin(tls_verify, auth_method, basic_auth)
            return plugin.list_instances()
        payload = {
            "server_url": SERVER_URL,
            "instance": "simulator",
            "auth_method": auth_method,
            "username": "example-user",
            "auth_key": "example-auth-secret",
            "timeout": 17,
            "enable_basic_auth": basic_auth,
            "basic_auth_username": "example-proxy-user",
            "basic_auth_password": "example-proxy-password",
        }
        if tls_verify is not None:
            payload["tls_verify"] = tls_verify
        with self.app.test_client() as client:
            response = client.post("/test-yamcs", json=payload)
            result = response.get_json()
        return result

    def test_tls_choice_and_secure_default_survive_ca_environment_merge(self):
        environments = (
            {},
            {"REQUESTS_CA_BUNDLE": REQUESTS_BUNDLE},
            {"CURL_CA_BUNDLE": CURL_BUNDLE},
            {"REQUESTS_CA_BUNDLE": REQUESTS_BUNDLE, "CURL_CA_BUNDLE": CURL_BUNDLE},
            {"REQUESTS_CA_BUNDLE": "", "CURL_CA_BUNDLE": CURL_BUNDLE},
        )
        for environment in environments:
            for tls_verify in (False, True, None):
                expected = False if tls_verify is False else (
                    environment.get("REQUESTS_CA_BUNDLE")
                    or environment.get("CURL_CA_BUNDLE")
                    or True
                )
                for path in ("plugin", "route"):
                    with self.subTest(environment=environment, tls_verify=tls_verify, path=path):
                        with offline_requests(environment) as transport:
                            result = self.run_connection(path, tls_verify)
                        self.assertTrue(result["success"], result)
                        self.assertGreater(len(transport.calls), 0)
                        for call in transport.calls:
                            self.assertEqual(call["verify"], expected)
                            self.assertEqual(call["timeout"], 17)

    def test_constructor_login_and_token_renewal_use_the_same_tls_policy(self):
        for environment in (
            {"REQUESTS_CA_BUNDLE": REQUESTS_BUNDLE},
            {"CURL_CA_BUNDLE": CURL_BUNDLE},
        ):
            for tls_verify in (False, True):
                expected = False if tls_verify is False else next(iter(environment.values()))
                for path in ("plugin", "route"):
                    with self.subTest(environment=environment, tls_verify=tls_verify, path=path):
                        with offline_requests(environment, expire_login_token=True) as transport:
                            result = self.run_connection(path, tls_verify, "username_password")
                        self.assertTrue(result["success"], result)
                        token_calls = [
                            call for call in transport.calls if call["path"] == "/yamcs/auth/token"
                        ]
                        grants = [parse_qs(call["body"])["grant_type"][0] for call in token_calls]
                        self.assertEqual(grants, ["password", "refresh_token"])
                        for call in transport.calls:
                            self.assertEqual(call["verify"], expected)
                            self.assertEqual(call["timeout"], 17)
                            if call["path"].startswith("/yamcs/api"):
                                self.assertEqual(
                                    call["headers"]["Authorization"],
                                    "Bearer refreshed-test-token",
                                )

    def test_api_key_bearer_and_basic_auth_preserve_tls_selection(self):
        for auth_method, basic_auth in (
            ("api_key", False),
            ("bearer_token", False),
            ("none", True),
            ("api_key", True),
        ):
            for path in ("plugin", "route"):
                with self.subTest(auth_method=auth_method, basic_auth=basic_auth, path=path):
                    with offline_requests({"CURL_CA_BUNDLE": CURL_BUNDLE}) as transport:
                        result = self.run_connection(path, False, auth_method, basic_auth)
                    self.assertTrue(result["success"], result)
                    basic_header = operations.build_yamcs_basic_auth_header(
                        "example-proxy-user", "example-proxy-password"
                    )
                    for call in transport.calls:
                        self.assertIs(call["verify"], False)
                        if auth_method == "api_key":
                            self.assertEqual(call["headers"]["x-api-key"], "example-auth-secret")
                        if basic_auth:
                            self.assertEqual(call["headers"]["Authorization"], basic_header)
                        elif auth_method == "bearer_token":
                            self.assertEqual(
                                call["headers"]["Authorization"], "Bearer example-auth-secret"
                            )

    def test_explicit_request_verification_and_timeout_overrides_are_preserved(self):
        with offline_requests({"REQUESTS_CA_BUNDLE": REQUESTS_BUNDLE}) as transport:
            plugin = self.build_plugin(False)
            client = plugin._connect()
            try:
                for verify, expected in (
                    (False, False),
                    (True, REQUESTS_BUNDLE),
                    ("explicit-ca.pem", "explicit-ca.pem"),
                ):
                    response = client.ctx.session.get(
                        client.ctx.api_root, verify=verify, timeout=3
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(transport.calls[-1]["verify"], expected)
                    self.assertEqual(transport.calls[-1]["timeout"], 3)
            finally:
                client.close()

    def test_request_wrapper_keeps_environment_proxy_behavior(self):
        environment = {
            "REQUESTS_CA_BUNDLE": REQUESTS_BUNDLE,
            "HTTPS_PROXY": "http://proxy.example.invalid:8080",
        }
        with offline_requests(environment) as transport:
            plugin = self.build_plugin(False)
            with requests.Session() as session:
                wrapped_request = plugin._with_timeout(session.request)
                response = wrapped_request("get", SERVER_URL + "/api")
        self.assertEqual(response.status_code, 200)
        self.assertIs(transport.calls[-1]["verify"], False)
        self.assertEqual(
            transport.calls[-1]["proxies"]["https"], "http://proxy.example.invalid:8080"
        )

    def test_failed_login_closes_session_without_an_insecure_retry(self):
        for path in ("plugin", "route"):
            with self.subTest(path=path):
                with offline_requests(
                    {"REQUESTS_CA_BUNDLE": REQUESTS_BUNDLE},
                    reject_verified_requests=True,
                ) as transport:
                    result = self.run_connection(path, True, "username_password")
                self.assertFalse(result["success"])
                self.assertEqual(len(transport.calls), 1)
                self.assertEqual(transport.calls[0]["verify"], REQUESTS_BUNDLE)
                self.assertEqual(len(transport.closed_sessions), 1)
                if path == "route":
                    self.assertNotIn("Untrusted offline fixture certificate", result["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
