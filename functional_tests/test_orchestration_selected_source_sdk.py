# test_orchestration_selected_source_sdk.py
"""Selected-source reads use the real Azure Blob SDK's bounded download contract.

Version: 0.261.369
Implemented in: 0.261.369

The real bootstrap, screening boundary, parsers and SDK execute offline. Only
external metadata/directory I/O and the SDK's HTTP transport are substituted.
"""

from copy import deepcopy
import hashlib
import importlib
import io
import json
from types import SimpleNamespace

from azure.core.pipeline.transport import HttpResponse, HttpTransport
from azure.core.utils import case_insensitive_dict
from azure.storage.blob import BlobServiceClient
from openpyxl import Workbook
import pytest

from test_orchestration_harness_routes import login, modules, real_http_harness
from test_support.orchestration_harness_execution import render_step
from test_support.orchestration_revisions import AtomicMemoryContainer


__all__ = ["modules", "real_http_harness"]

ACTOR = "PRIVATE_ACTOR"
DOCUMENT_ID = "PRIVATE_DOCUMENT"
CONVERSATION = "PRIVATE_CONVERSATION"
ETAG = '"source-etag"'
CSV_CONTENT = b"Record,Program,Amount\n001,Grants,10\n002,Acquisitions,20\n003,Grants,30\n004,Acquisitions,40\n"


class BlobStream:
    def __init__(self, content):
        self.content = content
        self.content_length = len(content)

    def __iter__(self):
        yield self.content


class BlobResponse(HttpResponse):
    def __init__(self, request, status, headers, content=b""):
        super().__init__(request, None)
        self.status_code = status
        self.headers = case_insensitive_dict(headers)
        self.content_type = headers.get("content-type", "application/octet-stream")
        self.reason = "OK" if status < 400 else "Fixture failure"
        self.content = content

    def body(self):
        return self.content

    def read(self):
        return self.content

    def stream_download(self, pipeline, **kwargs):
        return BlobStream(self.content)


class SourceTransport(HttpTransport):
    """A Blob HTTP boundary, not a replacement for SDK argument/range validation."""

    def __init__(self, content):
        self.content = content
        self.etag = ETAG
        self.requests = []
        self.bytes_sent = 0
        self.before_download = None
        self.after_download = None
        self.download_status = None

    def open(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def send(self, request, **kwargs):
        self.requests.append({
            "method": request.method, "headers": dict(request.headers), "options": kwargs,
        })
        headers = {
            "etag": self.etag, "content-length": str(len(self.content)),
            "content-type": "application/octet-stream", "x-ms-blob-type": "BlockBlob",
            "last-modified": "Wed, 21 Oct 2026 10:00:00 GMT",
        }
        if request.method == "HEAD":
            return BlobResponse(request, 200, headers)
        if request.method != "GET":
            raise AssertionError("Selected-source preparation must be read-only.")
        if self.before_download:
            self.before_download()
        status = self.download_status
        if request.headers.get("If-Match") != self.etag:
            status = 412
        if status:
            code = "ConditionNotMet" if status == 412 else "ServerBusy"
            return BlobResponse(request, status, {
                "content-type": "application/xml", "x-ms-error-code": code,
            }, f"<Error><Code>{code}</Code><Message>PRIVATE_PROVIDER_DETAIL</Message></Error>".encode())
        value = request.headers.get("x-ms-range", "")
        if not value.startswith("bytes="):
            raise AssertionError("A source download must have an explicit byte range.")
        start, end = (int(part) for part in value.removeprefix("bytes=").split("-"))
        data = self.content[start:end + 1]
        headers.update({
            "content-length": str(len(data)),
            "content-range": f"bytes {start}-{start + len(data) - 1}/{len(self.content)}",
        })
        self.bytes_sent += len(data)
        if self.after_download:
            self.after_download()
        return BlobResponse(request, 206, headers, data)


@pytest.fixture
def sdk_source(real_http_harness, monkeypatch):
    harness = real_http_harness.harness
    access = importlib.import_module("content_screening.access")
    contracts = importlib.import_module("content_screening.contracts")
    source_access = importlib.import_module("functions_orchestration_source_access")
    transport = SourceTransport(CSV_CONTENT)
    service = BlobServiceClient("https://selected-source.invalid", transport=transport, retry_total=0)
    monkeypatch.setitem(harness.config.CLIENTS, "storage_account_office_docs_client", service)
    containers = {}
    for scope, name in (
        ("personal", "cosmos_user_documents_container"),
        ("group", "cosmos_group_documents_container"),
        ("public", "cosmos_public_documents_container"),
        ("scans", "cosmos_content_screening_container"),
    ):
        containers[scope] = AtomicMemoryContainer("id")
        monkeypatch.setattr(harness.config, name, containers[scope])
    membership_reads = []

    def group_role(user_id, group_id, *, allowed_roles):
        membership_reads.append((user_id, group_id, allowed_roles))
        if user_id != ACTOR or group_id != "PRIVATE_GROUP":
            raise PermissionError("Not a member.")
        return "User"

    monkeypatch.setattr(importlib.import_module("functions_group"), "assert_group_role", group_role)
    monkeypatch.setattr(
        importlib.import_module("functions_public_workspaces"), "find_public_workspace_by_id",
        lambda identifier: {"id": identifier} if identifier == "PRIVATE_PUBLIC" else None,
    )
    state = SimpleNamespace(
        harness=harness, access=access, contracts=contracts, transport=transport,
        runtime=real_http_harness, containers=containers, membership_reads=membership_reads, document=None,
    )

    def select(*, content=CSV_CONTENT, file_name="PRIVATE_LEDGER.csv", scope="personal", screened=False):
        transport.content = content
        document = {
            "id": DOCUMENT_ID, "user_id": ACTOR, "version": 1, "status": "completed",
            "percentage_complete": 100, "file_name": file_name,
            "blob_container": "private-documents", "blob_path": "PRIVATE_PATH/original",
        }
        scope_id = ACTOR
        if scope != "personal":
            scope_id = "PRIVATE_GROUP" if scope == "group" else "PRIVATE_PUBLIC"
            document["group_id" if scope == "group" else "public_workspace_id"] = scope_id
        if screened:
            units = [contracts.ContentUnit("unit-1", "Approved fixture", {})]
            policy = {"fixture": "approved"}
            marker = {
                "state": "cleared", "source_revision": "1", "scan_id": "scan-1",
                "content_fingerprint": contracts.content_fingerprint(units),
                "canonical_ref": {"name": "canonical-1"}, "policy_fingerprint": contracts.hash_payload(policy),
                "active_blob": {
                    "container": "private-documents", "path": "PRIVATE_PATH/released",
                    "etag": ETAG, "content_hash": hashlib.sha256(content).hexdigest(),
                },
            }
            document["content_screening"] = marker
            containers["scans"].create_item({
                "id": "scan-1", "kind": "scan", "subject": contracts.subject_from_document(document).to_dict(),
                "state": "cleared", "coverage_complete": True, "result_status": "pass",
                "policy": policy, "policy_fingerprint": marker["policy_fingerprint"],
                "content_fingerprint": marker["content_fingerprint"], "units_ref": marker["canonical_ref"],
                "publication": {
                    "active_blob": deepcopy(marker["active_blob"]),
                    "content_fingerprint": marker["content_fingerprint"],
                },
            })
        state.document = containers[scope].create_item(document)
        state.container = containers[scope]
        context = {"scope": scope, "document": state.document}
        if scope != "personal":
            context["group_id" if scope == "group" else "public_workspace_id"] = scope_id
        return source_access.resolve_orchestration_source_manifest(
            [DOCUMENT_ID], ACTOR, conversation_id=CONVERSATION,
            context_resolver=lambda **kwargs: context,
        )

    state.select = select
    state.read = lambda sources: harness.bootstrap.build_selected_source_reader(
        ACTOR, conversation_id=CONVERSATION,
    )(sources)
    yield state
    service.close()


def workbook_content():
    book = Workbook()
    book.active.title = "Awards"
    for row in (["Record", "Program", "Amount"], ["001", "Grants", 10], ["002", "Acquisitions", 20]):
        book.active.append(row)
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
@pytest.mark.parametrize("scope", ["personal", "group", "public"])
def test_real_sdk_reads_selected_source_with_bounded_conditional_range(sdk_source, monkeypatch, extension, scope):
    state = sdk_source
    content = CSV_CONTENT if extension == "csv" else workbook_content()
    selected = state.select(content=content, file_name=f"PRIVATE_LEDGER.{extension}", scope=scope)
    read = state.access.read_available_document_bytes
    observed = []

    def capture(*args, **kwargs):
        result = read(*args, **kwargs)
        observed.append((args, result[1]))
        return result

    monkeypatch.setattr(state.access, "read_available_document_bytes", capture)
    projected = state.read(selected)
    table = projected[0]["inspection"]["tables"][0]
    assert table["columns"] == ["Record", "Program", "Amount"]
    assert table["sample_rows"][0] == ["001", "Grants", "10"]
    assert table["content_complete"] is False
    assert observed[0][1] == content
    assert observed[0][0][1:] == (
        ACTOR, "PRIVATE_GROUP" if scope == "group" else None, "PRIVATE_PUBLIC" if scope == "public" else None,
    )
    assert [request["method"] for request in state.transport.requests] == ["HEAD", "GET"]
    download = state.transport.requests[-1]
    assert download["headers"]["x-ms-range"] == "bytes=0-8388608"
    assert download["headers"]["If-Match"] == ETAG
    assert download["options"]["connection_timeout"] == 5
    assert download["options"]["read_timeout"] == 5
    assert state.transport.bytes_sent == len(content)
    assert not state.harness.model_calls
    if scope == "group":
        assert state.membership_reads
        assert all(call[:2] == (ACTOR, "PRIVATE_GROUP") for call in state.membership_reads)


@pytest.mark.parametrize("extra_bytes", [0, 1])
def test_real_sdk_enforces_source_size_limit_before_downloading(sdk_source, extra_bytes):
    state = sdk_source
    maximum = 8 * 1024 * 1024
    content = CSV_CONTENT + b"\n" * (maximum + extra_bytes - len(CSV_CONTENT))
    selected = state.select(content=content)
    result = state.read(selected)
    inspection = result[0]["inspection"]
    if extra_bytes:
        assert inspection["status"] == "limited"
        assert inspection["reason"] == "source_too_large"
        assert [request["method"] for request in state.transport.requests] == ["HEAD"]
        assert state.transport.bytes_sent == 0
    else:
        assert inspection["status"] == "inspected"
        assert state.transport.bytes_sent == maximum
        assert state.transport.requests[-1]["headers"]["x-ms-range"] == f"bytes=0-{maximum}"


@pytest.mark.parametrize("failure", ["etag", "storage"])
def test_real_sdk_download_failures_remain_screened_failures(sdk_source, failure):
    state = sdk_source
    selected = state.select()
    if failure == "etag":
        state.transport.before_download = lambda: setattr(state.transport, "etag", '"replaced"')
    else:
        state.transport.download_status = 503
    with pytest.raises(state.contracts.DocumentHeldError) as raised:
        state.read(selected)
    expected = "ResourceModifiedError" if failure == "etag" else "HttpResponseError"
    assert type(raised.value.__cause__).__name__ == expected
    assert state.transport.bytes_sent == 0
    assert len(state.transport.requests) == 2
    assert not state.harness.model_calls
    assert not state.harness.runs.items


@pytest.mark.parametrize("changed", [False, True])
def test_real_sdk_screened_source_keeps_hash_validation(sdk_source, changed):
    state = sdk_source
    selected = state.select(screened=True)
    if changed:
        state.transport.content = CSV_CONTENT.replace(b"Grants", b"SECRET")
        with pytest.raises(state.contracts.ScreeningConflictError):
            state.read(selected)
    else:
        result = state.read(selected)
        assert result[0]["inspection"]["status"] == "inspected"
    assert state.transport.requests[-1]["headers"]["If-Match"] == ETAG
    assert state.transport.bytes_sent == len(CSV_CONTENT)


@pytest.mark.parametrize("change", ["hold", "version", "metadata"])
@pytest.mark.parametrize("during_download", [False, True])
def test_source_changes_are_rejected_around_real_sdk_read(sdk_source, change, during_download):
    state = sdk_source
    selected = state.select(screened=change == "hold")

    def mutate():
        current = dict(state.container.items[(DOCUMENT_ID, DOCUMENT_ID)])
        if change == "hold":
            current["content_screening"] = {
                **current["content_screening"], "state": "pending_review",
            }
        elif change == "version":
            current["version"] += 1
        state.container.upsert_item(current)

    if during_download:
        state.transport.after_download = mutate
    else:
        mutate()
    source_context = importlib.import_module("functions_orchestration_source_context")
    with pytest.raises((state.contracts.ScreeningError, source_context.SourceContextError)):
        state.read(selected)
    assert len(state.transport.requests) == (2 if during_download else 0)
    assert not state.harness.model_calls


def test_source_free_and_narrative_context_do_not_use_blob_sdk(sdk_source):
    state = sdk_source
    selected = state.select(file_name="PRIVATE_POLICY.pdf")
    empty = state.read([])
    narrative = state.read(selected)
    assert empty == []
    assert narrative[0]["inspection"]["status"] == "not_applicable"
    assert state.transport.requests == []


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_unauthorized_actor_cannot_reach_blob_sdk(sdk_source, scope):
    state = sdk_source
    selected = state.select(scope=scope)
    reader = state.harness.bootstrap.build_selected_source_reader("different-actor")
    with pytest.raises(PermissionError):
        reader(selected)
    assert state.transport.requests == []


def test_source_service_artifact_query_keeps_sdk_owner_and_plain_rows(sdk_source):
    state = sdk_source
    harness = state.harness
    conversation = harness.conversations.create_item({"id": CONVERSATION, "user_id": ACTOR})
    harness.messages.create_item({
        "id": "prior-file", "conversation_id": CONVERSATION, "role": "file",
        "metadata": {"is_generated_chat_artifact": True}, "timestamp": "2026-10-21T10:00:00Z",
    })
    sources = harness.bootstrap.build_document_transform_sources(ACTOR, CONVERSATION)
    owner = sources.read_conversation(CONVERSATION)
    rows = list(sources.list_artifacts(CONVERSATION))
    assert type(conversation) is not dict
    assert type(owner) is dict and owner["_etag"] == conversation["_etag"]
    assert len(rows) == 1 and type(rows[0]) is dict
    assert rows[0]["id"] == "prior-file"
    assert state.transport.requests == []


@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("outcome", ["success", "storage", "hash"])
def test_source_read_diagnostics_are_debug_gated_and_content_free(sdk_source, monkeypatch, capsys, debug, outcome):
    state = sdk_source
    selected = state.select(screened=outcome == "hash")
    telemetry = importlib.import_module("functions_appinsights")
    monkeypatch.setattr(telemetry, "_load_logging_settings", lambda: {"enable_debug_logging": debug})
    recorded = []

    def log(message, **kwargs):
        recorded.append({"message": message, **kwargs})
        telemetry.log_event(message, **kwargs)

    monkeypatch.setattr(state.harness.bootstrap, "log_event", log)
    if outcome == "storage":
        state.transport.download_status = 503
    elif outcome == "hash":
        state.transport.content = CSV_CONTENT.replace(b"Grants", b"SECRET")
    capsys.readouterr()
    if outcome == "success":
        result = state.read(selected)
        assert result[0]["inspection"]["status"] == "inspected"
    else:
        with pytest.raises(state.contracts.ScreeningError):
            state.read(selected)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert ("Selected source read diagnostic." in output) is debug
    assert all(entry["debug_only"] is True for entry in recorded)
    details = [entry["extra"] for entry in recorded]
    assert details[0]["stage"] == "source_metadata"
    assert details[-1]["status"] == ("completed" if outcome == "success" else "failed")
    assert all(item["conversation_id_hash"] == hashlib.sha256(CONVERSATION.encode()).hexdigest() for item in details)
    if outcome == "storage":
        assert details[-1]["stage"] == "blob_download"
        assert details[-1]["error_type"] == "DocumentHeldError"
        assert details[-1]["reason"] == "HttpResponseError"
    elif outcome == "hash":
        assert details[-1]["stage"] == "source_integrity"
        assert details[-1]["error_type"] == "ScreeningConflictError"
    else:
        assert details[-1]["stage"] == "source_revision"
        assert details[-1]["content_bytes"] == len(CSV_CONTENT)
    assert "PRIVATE_" not in output + json.dumps(recorded)
    assert "SECRET" not in output + json.dumps(recorded)
    assert "Record,Program" not in output + json.dumps(recorded)
    assert "https://" not in output + json.dumps(recorded)


@pytest.mark.parametrize("output_format", ["csv", "xlsx"])
def test_http_review_plan_prepares_selected_file_through_real_sdk(sdk_source, monkeypatch, output_format):
    state = sdk_source
    selected = state.select()
    harness = state.harness
    harness.conversations.create_item({"id": CONVERSATION, "user_id": ACTOR})
    login(state.runtime, user_id=ACTOR)
    mixed = importlib.import_module("functions_mixed_source_orchestration")
    monkeypatch.setattr(mixed, "_default_document_context_batch_resolver", lambda **kwargs: [
        {"scope": "personal", "document": state.container.read_item(identifier, identifier)}
        for identifier in kwargs["document_ids"]
    ])

    def propose():
        payload = json.loads(harness.model_calls[-1]["messages"][1]["content"])
        source = payload["selected_sources"][0]
        columns = source["inspection"]["tables"][0]["columns"]
        export = render_step(
            "export", output_format, source="originals", output="records",
            profile="tabular_records_v1" if output_format == "csv" else "tabular_workbook_v1",
        )
        export["arguments"]["options"] = {"columns": columns}
        if output_format == "xlsx":
            export["arguments"]["options"]["sheet_name"] = "Original records"
        return json.dumps({
            "kind": "plan", "steps": [{
                "step_id": "originals", "capability_id": "tabular_analyze", "arguments": {
                    "question": "Read every original row.", "document_ids": [source["document_id"]],
                    "native_operation": "query", "columns": columns, "query_expression": "index == index",
                },
            }, export],
        })

    harness.replies = [propose]
    response = state.runtime.client.post("/api/v2/orchestration/plan", json={
        "conversation_id": CONVERSATION, "turn_id": "sdk-review",
        "message": f"Export every original row from my selected file as {output_format}.",
        "selected_document_ids": [selected[0]["document_id"]], "approval_mode": "manual",
    }, buffered=True)
    events = [
        json.loads(frame.partition("data:")[2])
        for frame in response.get_data(as_text=True).split("\n\n") if frame.startswith("data:")
    ]
    assert response.status_code == 200
    assert not any(event.get("error") for event in events), events
    plan = events[-1]["plan"]
    assert plan["steps"][0]["arguments"]["columns"] == ["Record", "Program", "Amount"]
    assert len(harness.model_calls) == 1
    assert state.transport.bytes_sent == len(CSV_CONTENT)
    assert [request["method"] for request in state.transport.requests] == ["HEAD", "GET"]
    assert harness.blobs.file_uploads == 0
    assert harness.assistant_messages() == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
