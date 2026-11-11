# test_admin_support_export_sources.py
"""
Pinned SDK transport and source-isolation tests for support exports.
Version: 0.261.426
Implemented in: 0.261.426
"""

import json
import sys
import time
from pathlib import Path

import pytest
from azure.core.credentials import AccessToken
from azure.core.pipeline.transport import HttpResponse, HttpTransport

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from support_export_contracts import SupportExportError, iso, normalize_request, utc_now
from support_export_sources import build_support_monitor_client
from test_support.support_exports import build_service


RESOURCE = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg/providers/Microsoft.Insights/components/simplechat"
COLUMNS = [
    ("TimeGenerated", "datetime"), ("ContextScope", "string"), ("Message", "string"),
    ("Severity", "string"), ("Table", "string"), ("Operation", "string"), ("Properties", "dynamic"),
    ("Details", "dynamic"), ("Success", "bool"), ("Duration", "real"), ("ResultCode", "string"),
    ("Target", "string"), ("ExceptionType", "string"), ("RequestId", "string"), ("ParentId", "string"),
    ("Instance", "string"),
]


class Credential:
    def __init__(self):
        self.scopes = []

    def get_token(self, *scopes, **kwargs):
        self.scopes.append(scopes)
        return AccessToken("synthetic-test-token", int(time.time()) + 3600)


class Reply(HttpResponse):
    def __init__(self, request, payload):
        super().__init__(request, None)
        self.status_code = 200
        self.headers = {"content-type": "application/json"}
        self.payload = json.dumps(payload).encode()
        self.content = self.payload
        self.reason = "OK"

    def body(self):
        return self.payload

    def json(self):
        return json.loads(self.payload)


class Transport(HttpTransport):
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def open(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def send(self, request, **kwargs):
        self.requests.append((request.url, json.loads(request.body)))
        return Reply(request, self.payload)


def payload(*, partial=False):
    result = {"tables": [{
        "name": "PrimaryResult",
        "columns": [{"name": name, "type": kind} for name, kind in COLUMNS],
        "rows": [[iso(utc_now()), "correlated", "Synthetic failure", "3", "AppTraces", "operation",
                  {"sc_user_id_hash": "a" * 64}, None, False, 5.0, "403", "service", "TestError",
                  "request-one", "parent-one", "instance-one"]],
    }]}
    if partial:
        result["error"] = {"code": "PartialError", "message": "Synthetic partial response"}
    return result


@pytest.mark.parametrize("cloud,origin", [
    ("public", "https://api.loganalytics.io"),
    ("usgovernment", "https://api.loganalytics.us"),
])
def test_pinned_sdk_resource_url_and_token_audience(cloud, origin):
    service = build_service()[0]
    credential = Credential()
    transport = Transport(payload())
    configuration = {"cloud": cloud, "app_resource_id": RESOURCE, "site_resource_id": ""}
    client = build_support_monitor_client(configuration, credential, transport=transport)
    service.sources.monitor = client
    plan = normalize_request({"user_id": "owner", "sources": ["telemetry"], "conversation_ids": ["conversation-1"]})
    try:
        rows = service.sources.collect_monitor(
            "telemetry", configuration, plan, [[plan["start"], plan["end"]]], lambda: None,
        )
    finally:
        client.close()
    assert len(rows) == 1 and rows[0]["properties"]["result_code"] == "403"
    url, body = transport.requests[0]
    assert url.startswith(origin + "/v1" + RESOURCE + "/query")
    assert credential.scopes == [(origin + "/.default",)]
    assert "tolower(_ResourceId)" in body["query"] and RESOURCE in body["query"]
    assert "p.sc_user_id_hash" in body["query"] and "let ops=" in body["query"]
    assert "system_context" in body["query"]


def test_partial_sdk_response_is_not_a_complete_export():
    service = build_service()[0]
    configuration = {"cloud": "public", "app_resource_id": RESOURCE, "site_resource_id": ""}
    client = build_support_monitor_client(configuration, Credential(), transport=Transport(payload(partial=True)))
    service.sources.monitor = client
    plan = normalize_request({"all_users": True, "sources": ["telemetry"]})
    try:
        with pytest.raises(SupportExportError, match="incomplete"):
            service.sources.collect_monitor("telemetry", configuration, plan, [[plan["start"], plan["end"]]], lambda: None)
    finally:
        client.close()


def test_removed_shared_entries_do_not_hide_later_conversation_pages():
    service, containers, *_ = build_service()
    for index in range(52):
        conversation_id = f"a{index:03d}" if index < 51 else "z-valid"
        containers["collaboration_states"].create_item({
            "id": conversation_id, "user_id": "owner", "conversation_id": conversation_id, "membership_status": "accepted",
        })
        containers["collaboration"].create_item({"id": conversation_id, "created_at": iso(utc_now())})

    def authorize(owner, document):
        if document["id"] != "z-valid":
            raise PermissionError("removed")

    service.sources.authorize_shared = authorize
    first = service.sources.conversations("owner")
    assert first["next"] == "a050"
    second = service.sources.conversations("owner", after=first["next"])
    assert {row["id"] for row in second["items"]} == {"conversation-1", "z-valid"}
    assert second["next"] is None


def test_transcripts_keep_authority_metadata_until_filtering_and_omit_binary():
    service, containers, *_ = build_service()
    message = containers["messages"].read_item("message-1", "conversation-1")
    message["metadata"] = {"settings": {"availability_check": True}}
    message["content"] = "Text ![image](data:image/png;base64,QUJDREVGRw==) after."
    containers["messages"].upsert_item(message)
    seen = []

    def visible(messages, owner):
        seen.append(messages[0]["metadata"]["settings"]["availability_check"])
        return messages

    service.sources.filter_messages = visible
    result = service.sources.snapshot("owner", ["conversation-1"], iso(utc_now()))
    assert seen == [True]
    assert "QUJDREVGRw==" not in result[0]["messages"][0]["content"]
    assert "[Binary data omitted]" in result[0]["messages"][0]["content"]
