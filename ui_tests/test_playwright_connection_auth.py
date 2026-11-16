# test_playwright_connection_auth.py
"""
Azure Playwright connection fixture authentication regression.
Version: 0.261.125
Implemented in: 0.261.125

The browser service requires the audience used by the official Azure Playwright
SDK, which differs from the management client audience. All credentials here are
synthetic and no Azure requests are made.
"""

from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

import playwright_connection as connection


@pytest.fixture
def azure_connection(monkeypatch):
    monkeypatch.setenv(
        "PLAYWRIGHT_WORKSPACE_RESOURCE_ID",
        "/subscriptions/test-subscription/resourceGroups/test-group/providers/"
        "Microsoft.LoadTestService/playwrightWorkspaces/test-workspace",
    )
    monkeypatch.setenv("PLAYWRIGHT_SERVICE_URL", "wss://browser.example.test/playwrightworkspaces/test/browsers")
    credential = MagicMock()
    credential.__enter__.return_value = credential
    credential.get_token.return_value = SimpleNamespace(token="synthetic-short-lived-token")
    management = MagicMock()
    management.__enter__.return_value = management
    management.playwright_workspaces.get.return_value = SimpleNamespace(
        properties=SimpleNamespace(dataplane_uri="https://browser.example.test/playwrightworkspaces/test"),
    )
    monkeypatch.setattr(connection, "DefaultAzureCredential", lambda: credential)
    monkeypatch.setattr(connection, "PlaywrightMgmtClient", lambda *args: management)
    return credential, management


def test_browser_connection_uses_the_sdk_entra_audience(azure_connection):
    credential, management = azure_connection
    options = connection.connect_options.__wrapped__()
    credential.get_token.assert_called_once_with("https://management.core.windows.net/.default")
    management.playwright_workspaces.get.assert_called_once_with("test-group", "test-workspace")
    assert options["headers"]["Authorization"] == "Bearer synthetic-short-lived-token"
    query = parse_qs(urlsplit(options["ws_endpoint"]).query)
    assert query["api-version"] == ["2025-09-01"]
    assert query["os"] == ["linux"]
    assert query["runId"]


def test_foreign_browser_host_never_receives_a_token(azure_connection, monkeypatch):
    credential, _ = azure_connection
    monkeypatch.setenv("PLAYWRIGHT_SERVICE_URL", "wss://unrelated.example.test/browsers")
    with pytest.raises(ValueError, match="configured Azure workspace"):
        connection.connect_options.__wrapped__()
    credential.get_token.assert_not_called()


def test_unconfigured_azure_service_uses_the_local_browser(azure_connection, monkeypatch):
    credential, management = azure_connection
    monkeypatch.delenv("PLAYWRIGHT_SERVICE_URL", raising=False)
    options = connection.connect_options.__wrapped__()
    assert options == {}
    credential.get_token.assert_not_called()
    management.playwright_workspaces.get.assert_not_called()
