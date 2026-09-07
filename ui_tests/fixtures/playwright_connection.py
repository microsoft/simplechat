# playwright_connection.py
"""
Shared local/Azure Playwright browser connection fixture.
Version: 0.261.096
Implemented in: 0.261.096

Reuse a configured Azure workspace without provisioning resources or storing tokens.
Without PLAYWRIGHT_SERVICE_URL, pytest-playwright uses its normal local browser.
"""

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import pytest
from azure.identity import DefaultAzureCredential
from azure.mgmt.playwright import PlaywrightMgmtClient


@pytest.fixture(scope="session")
def connect_options():
    """Connect only to the configured Azure workspace, or use a local browser."""
    service_url = os.getenv("PLAYWRIGHT_SERVICE_URL", "")
    if not service_url:
        return {}

    parts = os.getenv("PLAYWRIGHT_WORKSPACE_RESOURCE_ID", "").strip("/").split("/")
    if (
        len(parts) != 8
        or parts[0].lower() != "subscriptions"
        or parts[2].lower() != "resourcegroups"
        or parts[4].lower() != "providers"
        or parts[5].lower() != "microsoft.loadtestservice"
        or parts[6].lower() != "playwrightworkspaces"
    ):
        raise ValueError("Set PLAYWRIGHT_WORKSPACE_RESOURCE_ID to the workspace's ARM resource ID.")

    endpoint = urlsplit(service_url)
    with DefaultAzureCredential() as credential:
        with PlaywrightMgmtClient(credential, parts[1]) as client:
            workspace = client.playwright_workspaces.get(parts[3], parts[7])
        dataplane_uri = workspace.properties.dataplane_uri if workspace.properties else None
        if (
            endpoint.scheme != "wss"
            or not dataplane_uri
            or endpoint.hostname != urlsplit(dataplane_uri).hostname
        ):
            raise ValueError("PLAYWRIGHT_SERVICE_URL must target the configured Azure workspace.")
        token = credential.get_token("https://management.azure.com/.default").token

    query = dict(parse_qsl(endpoint.query))
    query.update({
        "os": "linux",
        "runId": os.getenv("PLAYWRIGHT_SERVICE_RUN_ID") or str(uuid4()),
        "api-version": "2025-09-01",
    })
    return {
        "ws_endpoint": urlunsplit(endpoint._replace(query=urlencode(query))),
        "headers": {"Authorization": f"Bearer {token}"},
        "timeout": 180000,
    }
