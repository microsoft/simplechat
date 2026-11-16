# test_key_vault_connection_permissions.py
"""
Behavioral coverage for the shared Key Vault permission test.
Version: 0.261.400
Implemented in: 0.261.125
SDK cleanup and partial-result regressions added in: 0.261.400

Read-only access must not pass; write/read-back/cleanup failures must be explicit.
The probe must never expose its value or modify an existing application secret.
"""

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from urllib.parse import urlsplit

import pytest
import requests
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError, ServiceRequestError
from azure.core.pipeline.transport import RequestsTransport
from azure.keyvault.secrets import SecretClient, __version__ as sdk_version

from test_support.app_stubs import import_app_module


probe = import_app_module("functions_keyvault_test")


def forbidden():
    error = HttpResponseError(message="private provider details and synthetic credential")
    error.status_code = 403
    return error


class ProbeClient:
    def __init__(self):
        self.items = {"existing-application-secret": "untouched"}
        self.calls = []
        self.failures = {}
        self.values = []
        self.options = []
        self.mismatch = False
        self.delete_done = True
        self.write_before_error = False
        self.closed = False
        self.written_names = []
        self.deleted_names = []
        self.poll_timeouts = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def _call(self, stage):
        self.calls.append(stage)
        if stage in self.failures:
            raise self.failures[stage]

    def list_properties_of_secrets(self, **kwargs):
        self._call("list")
        return iter([])

    def set_secret(self, name, value, **kwargs):
        self.written_names.append(name)
        self.values.append(value)
        self.options.append(kwargs)
        if self.write_before_error:
            self.items[name] = value
        self._call("write")
        self.items[name] = value

    def get_secret(self, name, **kwargs):
        self._call("read")
        return SimpleNamespace(value="wrong" if self.mismatch else self.items[name])

    def begin_delete_secret(self, name, *, connection_timeout, read_timeout, retry_total):
        self.deleted_names.append(name)
        self._call("cleanup")
        if name not in self.items:
            raise ResourceNotFoundError(message="No test secret exists")
        if self.delete_done:
            del self.items[name]

        def wait(*, timeout):
            self.poll_timeouts.append(timeout)
            if "poll" in self.failures:
                raise self.failures["poll"]

        return SimpleNamespace(wait=wait, done=lambda: self.delete_done)


@pytest.fixture
def world(monkeypatch):
    client = ProbeClient()
    constructor = Mock(return_value=client)
    credential = Mock()
    credential.__enter__ = Mock(return_value=credential)
    credential.__exit__ = Mock(return_value=False)
    factory = Mock(return_value=credential)
    monkeypatch.setattr(probe, "SecretClient", constructor)
    log = Mock()
    monkeypatch.setattr(probe, "log_event", log)

    def run(**updates):
        result = probe.run_key_vault_connection_test(
            {"vault_name": "test-vault", "client_id": "", **updates},
            vault_domain=".vault.azure.net",
            credential_factory=factory,
        )
        public = json.dumps(result)
        for value in client.values:
            assert value not in public
        assert "private provider details" not in public
        assert client.items["existing-application-secret"] == "untouched"
        return result

    return SimpleNamespace(client=client, constructor=constructor, factory=factory, run=run, log=log)


def test_success_requires_write_readback_and_cleanup(world):
    result, status = world.run()
    assert status == 200 and result["success"] is True
    assert world.client.calls == ["list", "write", "read", "cleanup"]
    assert all(value == "passed" for value in result["checks"].values())
    assert world.client.items == {"existing-application-secret": "untouched"}
    assert world.client.options[0]["expires_on"] > datetime.now(timezone.utc)
    assert world.client.closed
    assert world.client.deleted_names == world.client.written_names
    assert world.client.poll_timeouts == [probe.PROBE_CLEANUP_TIMEOUT]
    world.factory.assert_called_once_with(
        settings={"key_vault_identity": None}, **probe.PROBE_CREDENTIAL_OPTIONS,
    )


@pytest.mark.parametrize("stage", ["list", "write", "read", "cleanup"])
def test_each_permission_failure_is_explicit(world, stage):
    world.client.failures[stage] = forbidden()
    result, status = world.run()
    assert status == 400 and result["success"] is False
    assert result["failed_stage"] == stage
    assert "Key Vault Secrets Officer" in result["error"]
    assert result["checks"][stage] == "failed"
    if stage in ("write", "read"):
        assert "cleanup" in world.client.calls
    world.log.assert_called()


def test_readback_mismatch_fails_and_cleans_up(world):
    world.client.mismatch = True
    result, status = world.run()
    assert status == 400 and result["failed_stage"] == "read"
    assert result["checks"]["cleanup"] == "passed"
    assert len(world.client.items) == 1


def test_uncertain_write_still_cleans_up_its_secret(world):
    world.client.write_before_error = True
    world.client.failures["write"] = ServiceRequestError("private provider details")
    result, status = world.run()
    assert status == 400 and result["failed_stage"] == "write"
    assert result["checks"]["cleanup"] == "passed"
    assert len(world.client.items) == 1


def test_cleanup_timeout_is_not_success(world):
    world.client.delete_done = False
    result, status = world.run()
    assert status == 400 and result["failed_stage"] == "cleanup"
    assert result["cleanup_secret_name"].startswith("simplechat-connection-test-")
    assert "could not be confirmed" in result["error"]


def test_primary_failure_is_preserved_when_cleanup_also_fails(world):
    world.client.failures.update({"read": forbidden(), "cleanup": forbidden()})
    result, status = world.run()
    assert status == 400 and result["failed_stage"] == "read"
    assert result["code"] == "key_vault_read_forbidden"
    assert result["checks"]["cleanup"] == "failed"
    assert result["cleanup_secret_name"] in result["error"]


@pytest.mark.parametrize("error", [
    ServiceRequestError("private provider details"),
    ResourceNotFoundError("private provider details"),
    TypeError("private provider details"),
])
def test_polling_errors_are_cleanup_failures_with_complete_results(world, error):
    world.client.failures["poll"] = error
    result, status = world.run()
    assert status == 400 and result["success"] is False
    assert result["failed_stage"] == "cleanup"
    assert result["checks"] == {
        "list": "passed", "write": "passed", "read": "passed", "cleanup": "failed",
    }
    assert result["details"] == [
        "List secrets: passed", "Write test secret: passed",
        "Read-back test secret: passed", "Clean up test secret: failed",
    ]
    assert result["cleanup_secret_name"] == world.client.written_names[0]
    assert world.client.closed


@pytest.mark.parametrize("stage", ["write", "read", "cleanup"])
def test_sdk_type_errors_return_safe_partial_results(world, stage):
    world.client.failures[stage] = TypeError("private provider details")
    result, status = world.run()
    assert status == 400 and result["success"] is False
    assert result["failed_stage"] == stage
    assert result["checks"][stage] == "failed"
    assert len(result["details"]) == 4
    assert world.client.deleted_names == world.client.written_names
    if stage == "cleanup":
        assert result["cleanup_secret_name"] == world.client.written_names[0]
    else:
        assert result["checks"]["cleanup"] == "passed"
        assert "cleanup_secret_name" not in result


@pytest.mark.parametrize("poll_status", [200, 500])
def test_pinned_sdk_cleanup_uses_only_supported_request_arguments(world, monkeypatch, poll_status):
    """Run the pinned client and poller over a signature-checked, network-free session."""
    requirements = Path(__file__).resolve().parents[1] / "application" / "single_app" / "requirements.txt"
    requirement = next(
        line.split("==", 1)[1] for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.startswith("azure-keyvault-secrets==")
    )
    assert sdk_version == requirement
    session = create_autospec(requests.Session, instance=True)
    world.factory.return_value.__enter__.return_value = SimpleNamespace(
        get_token=lambda *_args, **_kwargs: AccessToken("offline-test-token", 4102444800),
    )
    calls = []
    items = {"existing-application-secret": "untouched"}
    written = {}

    def request(method, url, **kwargs):
        parts = urlsplit(url).path.strip("/").split("/")
        status = 200
        headers = {"Content-Type": "application/json"}
        if not kwargs["headers"].get("Authorization"):
            status = 401
            headers["WWW-Authenticate"] = (
                'Bearer authorization="https://login.microsoftonline.com/offline-tenant", '
                'resource="https://vault.azure.net"'
            )
            body = {}
        elif method == "GET" and parts == ["secrets"]:
            body = {"value": []}
        elif method == "PUT" and parts[0] == "secrets":
            value = json.loads(kwargs["data"])["value"]
            items[parts[1]] = value
            written[parts[1]] = value
            body = {"id": f"https://test-vault.vault.azure.net/secrets/{parts[1]}/version", "value": value}
        elif method == "GET" and parts[0] == "secrets":
            body = {"value": items[parts[1]]}
        elif method == "DELETE" and parts[0] == "secrets":
            del items[parts[1]]
            body = {
                "id": f"https://test-vault.vault.azure.net/secrets/{parts[1]}/version",
                "recoveryId": f"https://test-vault.vault.azure.net/deletedsecrets/{parts[1]}",
            }
        elif method == "GET" and parts[0] == "deletedsecrets":
            status = poll_status
            body = {} if status == 200 else {
                "error": {"code": "InternalError", "message": "private provider details"},
            }
        else:
            raise AssertionError(f"Unexpected SDK operation: {method} {parts}")
        if status != 401:
            calls.append((method, tuple(parts)))
        response = requests.Response()
        response.status_code = status
        response.headers.update(headers)
        response._content = json.dumps(body).encode("utf-8")
        response.raw = BytesIO(response._content)
        return response

    session.request.side_effect = request

    def build_client(**kwargs):
        return SecretClient(**kwargs, transport=RequestsTransport(session=session, session_owner=False))

    monkeypatch.setattr(probe, "SecretClient", build_client)
    result, status = world.run()
    assert status == (200 if poll_status == 200 else 400)
    assert result["success"] is (poll_status == 200)
    assert result["checks"]["cleanup"] == ("passed" if poll_status == 200 else "failed")
    assert len(written) == 1
    name = next(iter(written))
    assert name.startswith("simplechat-connection-test-")
    assert calls == [
        ("GET", ("secrets",)), ("PUT", ("secrets", name)),
        ("GET", ("secrets", name)), ("DELETE", ("secrets", name)),
        ("GET", ("deletedsecrets", name)),
    ]
    assert items == {"existing-application-secret": "untouched"}
    assert written[name] not in json.dumps(result)
    if poll_status != 200:
        assert result["cleanup_secret_name"] == name


def test_draft_user_identity_is_used(world):
    client_id = "11111111-2222-3333-4444-555555555555"
    result, status = world.run(client_id=client_id)
    assert status == 200
    world.factory.assert_called_once_with(
        settings={"key_vault_identity": client_id}, **probe.PROBE_CREDENTIAL_OPTIONS,
    )


@pytest.mark.parametrize("payload", [
    {"vault_name": ""},
    {"vault_name": "https://wrong-host"},
    {"vault_name": "test--vault"},
    {"vault_name": ["test-vault"]},
    {"client_id": "not-an-identity"},
    {"client_id": ["invalid"]},
    {"client_id": []},
    {"client_id": {}},
    {"client_id": False},
    {"client_id": 0},
])
def test_invalid_configuration_never_contacts_key_vault(world, payload):
    result, status = world.run(**payload)
    assert status == 400 and result["success"] is False
    world.constructor.assert_not_called()
    world.factory.assert_not_called()
    world.log.assert_called()
