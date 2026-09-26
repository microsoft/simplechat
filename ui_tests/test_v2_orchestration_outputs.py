# test_v2_orchestration_outputs.py
"""
Real-component coverage for independent orchestration file recovery.
Version: 0.261.141
Implemented in: 0.261.127
Simplified file cards covered in: 0.261.141
Refs: microsoft/simplechat#1509

Executes the production React thread/drawer, stores, SSE reader and HTTP clients
with the existing local/Azure Playwright fixture and production CSS. Responses
follow public_output, committed_artifact_card and the file-only retry API.
Only HTTP boundaries are mocked; no provider/model calls or Azure resources are
created. These checks do not claim backend admission or scheduler integration.
"""

import copy
import re
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

import test_v2_orchestration_dependency_plans as dependency_tests
import test_v2_orchestration_plan_editor as editor_tests
import test_v2_orchestration_recovery as recovery_tests
from test_v2_orchestration_plan_editor import (  # noqa: F401
    connect_options,
    editor_assets,
    editor_browser,
    editor_ui,
)


pytestmark = pytest.mark.ui
CONVERSATION = recovery_tests.CONVERSATION
TURN = recovery_tests.TURN
READY_ID = "orender_" + "a" * 64
RETRY_ID = "orender_" + "b" * 64
CATALOG_PATH = "/api/v2/orchestration/export-catalog"
DOWNLOAD_PATH = "/api/chat_artifacts/download"
CSV_CONTENT = "finding\n" + "saved\n" * 7
UNAVAILABLE_HISTORY = (
    "Generated file is unavailable because current access or publication could not be confirmed."
)


def public_output(output_id, state, file_name="findings.csv", step_id="file_a"):
    completed = state == "completed"
    return {
        "output_id": output_id,
        "step_id": step_id,
        "file_name": file_name,
        "output_format": "csv",
        "profile": "tabular_records_v1",
        "state": state,
        "attempt_count": 3 if state == "failed" else 1,
        "automatic_attempts": 3 if state == "failed" else 1,
        "max_automatic_attempts": 3,
        "next_retry_at": "2026-09-23T14:30:00Z" if state == "retry_scheduled" else None,
        "can_retry": state == "failed",
        "available": state != "cancelled",
        "error_code": "output_storage_unavailable" if state in ("failed", "retry_scheduled") else None,
        "message": {
            "waiting": "This file is waiting to be rendered.",
            "rendering": "This file is being prepared.",
            "retry_scheduled": "This file will be retried automatically.",
            "completed": "This file is ready.",
            "failed": "This file could not be created.",
            "cancelled": "This file was cancelled.",
        }[state],
        "artifact_message_id": "artifact-" + output_id if completed else None,
        "row_count": 7 if completed else None,
        "character_count": None,
        "size_bytes": len(CSV_CONTENT.encode("utf-8")) if completed else None,
    }


def committed_card(output):
    return {
        "capability": "render_file", "source_kind": "orchestration_retained_output",
        "output_id": output["output_id"], "artifact_message_id": output["artifact_message_id"],
        "conversation_id": CONVERSATION, "storage_scope": "chat",
        "file_name": output["file_name"], "output_format": output["output_format"],
        "profile": output["profile"], "summary": "The requested file is ready.",
        "row_count": output["row_count"], "character_count": output["character_count"],
    }


def catalog():
    return [{
        "format_id": "csv", "aliases": ["csv"], "file_extension": "csv",
        "media_type": "text/csv; charset=utf-8", "renderer_version": 1,
        "profiles": [{
            "profile": "tabular_records_v1", "source_kinds": ["records"],
            "required_options": ["columns"], "supported_options": ["columns"],
            "requires_complete": True,
            "options_schema": {"type": "object", "properties": {"columns": {
                "type": "array", "minItems": 1, "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            }}, "required": ["columns"], "additionalProperties": False},
            "input_schema": {"type": "array", "items": {"type": "object"}},
        }],
        "streaming": True, "rich_media": False, "dependencies": ["jsonschema"],
        "default_limits": {"max_records": 1000000}, "max_output_bytes_required": True,
        "failure_codes": [], "validation_failures_retryable": False, "retryable_failure_codes": [],
    }]


class OutputApi(recovery_tests.RecoveryApi):
    def __init__(self, assets):
        super().__init__(assets)
        self.plan = dependency_tests.dependency_plan(CONVERSATION, TURN)
        for step_id, name in (("file_a", "findings.csv"), ("file_b", "summary.csv")):
            self.plan["steps"].append({
                "step_id": step_id, "capability_id": "render_file", "role": "render",
                "title": f"Prepare {name}", "rationale": "", "depends_on": ["prepare_findings"],
                "arguments": {
                    "file_name": name, "output_format": "csv", "profile": "tabular_records_v1",
                    "options": {"columns": ["finding"]},
                },
                "inputs": {"source": {
                    "binding": dependency_tests.binding("prepare_findings", "findings"), "allow_partial": False,
                }},
                "outputs": [], "enabled": True, "optional": False, "estimated_cost": "low", "status": "pending",
            })
        self.records = {}
        self.steps = {}
        record = self.add_record(self.plan)
        record.update(
            status="failed", outcome="partial", finalization_status="saved", message_saved=True,
            assistant_message_id="output-answer",
            outputs=[
                public_output(READY_ID, "completed"),
                public_output(RETRY_ID, "failed", "summary.csv", "file_b"),
            ],
        )
        record["plan"]["status"] = "failed"
        record["plan_summary"].update(status="failed", step_count=len(self.plan["steps"]))
        record["recovery"] = {
            **self.recovery(record["run_id"]),
            "retry_step_ids": ["file_b"], "reused_step_ids": ["prepare_findings", "file_a"],
            "requires_confirmation": False,
        }
        self.steps[record["run_id"]] = [
            {"step_id": step["step_id"], "step_index": index, "title": step["title"],
             "status": "failed" if step["step_id"] == "file_b" else "completed", "summary": ""}
            for index, step in enumerate(self.plan["steps"])
        ]
        self.retry_mode = "success"
        self.retry_status = 403
        self.accepted = {}
        self.expected_console_errors = set()
        self.detail_override = None
        self.hold_next_detail = False
        self.catalog_status = 200
        self.catalog_formats = catalog()
        self.download_status = 200
        self.download_content = CSV_CONTENT
        self.download_file_name = "findings.csv"
        self.download_media_type = "text/csv"
        self.output_stream = "terminal"
        self.publish()

    @property
    def record(self):
        return self.records[self.plan["run_id"]]

    @property
    def output(self):
        return next(output for output in self.record["outputs"] if output["output_id"] == RETRY_ID)

    def publish(self):
        record = self.record
        record["generated_artifacts"] = [
            committed_card(output) for output in record.get("outputs", [])
            if output["state"] == "completed" and output.get("available") is not False
        ]
        fields = ("run_id", "turn_id", "attempt_index", "outcome", "recovery",
                  "finalization_status", "message_saved", "outputs")
        metadata = {"orchestration": {key: copy.deepcopy(record[key]) for key in fields if key in record}}
        self.messages = self.messages[:1] + [{
            "id": "output-answer", "conversation_id": CONVERSATION, "role": "assistant",
            "content": "The prepared findings are retained; review each requested file.",
            "metadata": metadata, "generated_artifacts": copy.deepcopy(record["generated_artifacts"]),
        }]

    def fail_request(self, route, status, code):
        self.expected_console_errors.add((urlsplit(route.request.url).path, str(status)))
        route.fulfill(status=status, json={
            "code": code, "error": "This file retry could not be accepted.",
            "details": "PRIVATE PROVIDER DETAIL MUST NOT BE SHOWN",
        })

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        retry_match = re.fullmatch(re.escape(editor_tests.RUNS) + r"/([^/]+)/outputs/([^/]+)/retry", path)
        special = retry_match or path in (CATALOG_PATH, DOWNLOAD_PATH, editor_tests.RUN)
        detail = path == editor_tests.RUNS + "/" + self.plan["run_id"]
        if not special and not detail:
            return super().handle(route)
        body = request.post_data_json if request.post_data else None
        self.requests.append({"path": path, "method": request.method, "body": body, "query": parsed.query})
        if detail:
            snapshot = copy.deepcopy(self.detail_override or self.record)
            if self.hold_next_detail:
                self.hold_next_detail = False
                self.waiting.append(lambda: route.fulfill(json={"run": snapshot}))
            else:
                route.fulfill(json={"run": snapshot})
            return
        if retry_match:
            run_id, output_id = retry_match.groups()
            assert run_id == self.plan["run_id"]
            assert set(body) == {"conversation_id", "submission_id"}
            assert body["conversation_id"] == CONVERSATION
            parsed_id = uuid.UUID(body["submission_id"])
            assert str(parsed_id) == body["submission_id"]
            if self.retry_mode == "denied":
                self.fail_request(route, self.retry_status, "output_unavailable")
                return
            if self.retry_mode == "server_error":
                self.fail_request(route, 503, "output_storage_unavailable")
                return
            if self.retry_mode == "network":
                self.expected_console_errors.add((path, "net::ERR_FAILED"))
                route.abort()
                return
            if body["submission_id"] not in self.accepted:
                output = next(item for item in self.record["outputs"] if item["output_id"] == output_id)
                assert output["can_retry"]
                old = copy.deepcopy(self.record)
                output.update(
                    state="waiting", attempt_count=output["attempt_count"] + 1, can_retry=False,
                    message="This file is waiting to be rendered.", next_retry_at=None,
                    error_code=None, artifact_message_id=None,
                )
                self.accepted[body["submission_id"]] = copy.deepcopy(body)
                if self.retry_mode == "lost_stale":
                    self.detail_override = old
            if self.retry_mode in ("lost", "lost_stale"):
                self.expected_console_errors.add((path, "net::ERR_FAILED"))
                route.abort()
                return
            self.detail_override = None
            receipt = {"output": copy.deepcopy(self.output), "run": copy.deepcopy(self.record)}
            if self.retry_mode == "delayed":
                self.waiting.append(lambda: route.fulfill(status=202, json=receipt))
            else:
                route.fulfill(status=202, json=receipt)
            return
        if path == CATALOG_PATH:
            assert parse_qs(parsed.query) == {
                "conversation_id": [CONVERSATION], "run_id": [self.plan["run_id"]],
            }
            if self.catalog_status == 200:
                route.fulfill(json={"formats": self.catalog_formats})
            elif self.catalog_status == 403:
                self.expected_console_errors.add((path, "403"))
                route.fulfill(status=403, json={
                    "error": "File rendering is not available for this conversation.",
                    "code": "rendering_unavailable",
                })
            else:
                self.fail_request(route, self.catalog_status, "unavailable")
            return
        if path == DOWNLOAD_PATH:
            assert parse_qs(parsed.query) == {
                "conversation_id": [CONVERSATION], "message_id": ["artifact-" + READY_ID],
            }
            if self.download_status != 200:
                self.fail_request(route, self.download_status, "output_unavailable")
                return
            route.fulfill(
                content_type=self.download_media_type, body=self.download_content,
                headers={"Content-Disposition": f'attachment; filename="{self.download_file_name}"'},
            )
            return
        if path == editor_tests.RUN:
            if self.output_stream in ("transport", "bare_done"):
                self.output.update(
                    state="retry_scheduled", can_retry=False,
                    message="This file will be retried automatically.",
                    next_retry_at="2026-09-23T14:30:00Z",
                )
                self.publish()
            events = [
                {"type": "orchestration_step", "step_id": output["step_id"],
                 "status": "running" if self.output_stream == "bare_done" else "partial",
                 "outputs": [copy.deepcopy(output)]}
                for output in self.record["outputs"]
            ]
            if self.output_stream == "bare_done":
                events.append({"done": True})
            elif self.output_stream != "transport":
                terminal = {
                    "type": "orchestration_done", "done": True, "status": "failed", "outcome": "partial",
                    "message_id": "output-answer", "full_content": self.messages[-1]["content"],
                    "run_id": self.plan["run_id"], "turn_id": TURN,
                    "finalization_status": "saved", "message_saved": True,
                    "generated_artifacts": self.record["generated_artifacts"],
                }
                if self.output_stream != "terminal_without_outputs":
                    terminal["outputs"] = copy.deepcopy(self.record["outputs"])
                events.append(terminal)
            self.stream(route, events)


@pytest.fixture
def outputs_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = OutputApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))

    def console_error(message):
        if message.type != "error":
            return
        path = urlsplit(message.location.get("url", "")).path
        if not any(path == expected and status in message.text
                   for expected, status in api.expected_console_errors):
            api.errors.append(message.text)

    page.on("console", console_error)
    try:
        yield page, api
    finally:
        api.release()
        context.close()
        assert not api.errors, api.errors


def mount_outputs(page, api, saved=True):
    recovery_tests.mount_recovery(page, api, saved=saved)
    files = page.get_by_role("region", name="Files from this plan").first
    expect(files).to_be_visible()
    expect(files.get_by_role("button", name="Check saved file status", exact=True)).to_be_enabled()
    return files


def file_card(files, name="summary.csv"):
    return files.get_by_role("article", name=f"File {name}", exact=True)


def retry_button(files):
    return file_card(files).get_by_role("button", name="Retry file summary.csv", exact=True)


def write_calls(api):
    return [request for request in api.requests if request["method"] == "POST"]


def saved_outputs(page, run_id):
    return page.evaluate("""(runId) => window.OrchHarness.stores.orchestration
        .useOrchestrationStore.getState().runRecovery[runId].outputs""", run_id)


def enable_uploaded_file_preview(page):
    page.evaluate("""() => {
        const B = window.OrchHarness.stores.bootstrap.useBootstrapStore;
        const data = B.getState().data;
        B.setState({ data: { ...data,
            features: { ...data.features, enable_user_workspace: true } } });
    }""")


@pytest.mark.parametrize("width", [1440, 390])
def test_ready_sibling_download_and_keyboard_file_retry_are_independent(outputs_ui, width):
    page, api = outputs_ui
    page.set_viewport_size({"width": width, "height": 900})
    files = mount_outputs(page, api)
    expect(file_card(files, "findings.csv").get_by_role("button", name="Download CSV")).to_be_enabled()
    expect(file_card(files, "findings.csv")).to_contain_text("CSV file · 7 rows")
    expect(file_card(files)).to_contain_text("This file could not be created.")
    # Attempt counters and failure codes are server bookkeeping, not something to act on.
    expect(file_card(files)).not_to_contain_text("Automatic attempts")
    expect(file_card(files)).not_to_contain_text("output_storage_unavailable")
    expect(page.get_by_role("button", name="Retry from failed step", exact=True)).to_have_count(0)
    retry = retry_button(files)
    expect(retry).to_have_accessible_description("This file could not be created.")
    retry.focus()
    retry.press("Enter")
    expect(file_card(files).get_by_role("status")).to_have_text("Waiting")
    expect(file_card(files)).not_to_contain_text("This file could not be created.")
    retried = next(output for output in saved_outputs(page, api.plan["run_id"]) if output["output_id"] == RETRY_ID)
    assert retried["attempt_count"] == 4
    expect(retry_button(files)).to_have_count(0)
    expect(file_card(files)).to_be_focused()
    with page.expect_download() as downloading:
        file_card(files, "findings.csv").get_by_role("button", name="Download CSV").click()
    download = downloading.value
    failure = download.failure()
    assert failure is None
    assert download.suggested_filename == "findings.csv"
    requests = write_calls(api)
    assert len(requests) == 1
    assert requests[0]["path"].endswith(f"/outputs/{RETRY_ID}/retry")
    assert len(api.accepted) == 1
    assert api.record["outputs"][0]["attempt_count"] == 1
    overflow = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
    assert not overflow


@pytest.mark.parametrize("output_format,media_type", [
    ("txt", "text/plain; charset=utf-8"),
    ("md", "text/markdown; charset=utf-8"),
])
def test_empty_text_files_preserve_zero_counts_and_download_empty_bytes(outputs_ui, tmp_path, output_format, media_type):
    page, api = outputs_ui
    file_name = f"empty.{output_format}"
    api.record["outputs"][0].update(
        file_name=file_name, output_format=output_format, profile="prepared_text_v1",
        row_count=0, character_count=0, size_bytes=0,
    )
    api.download_content = ""
    api.download_file_name = file_name
    api.download_media_type = media_type
    api.publish()
    files = mount_outputs(page, api)
    empty_file = file_card(files, file_name)
    expect(empty_file.get_by_role("status")).to_have_text("Completed")
    label = "Text file" if output_format == "txt" else "Markdown file"
    # Zero is a real count and a real size, never dropped as if it were missing.
    expect(empty_file).to_contain_text(f"{label} · 0 rows · 0 B")
    expect(empty_file.get_by_role("button", name=re.compile("^Retry file "))).to_have_count(0)
    with page.expect_download() as downloading:
        empty_file.get_by_role("button", name=f"Download {output_format.upper()}", exact=True).click()
    download = downloading.value
    destination = tmp_path / file_name
    download.save_as(destination)
    failure = download.failure()
    downloaded = destination.read_bytes()
    assert failure is None
    assert download.suggested_filename == file_name
    assert downloaded == b""
    assert not write_calls(api)


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("unavailable", [False, True])
def test_orchestration_history_markers_are_inert_and_do_not_hide_ready_siblings(outputs_ui, width, unavailable):
    page, api = outputs_ui
    page.set_viewport_size({"width": width, "height": 900})
    message = {
        "id": "generated-history", "conversation_id": CONVERSATION, "role": "file",
        "content": "A generated file was recorded.",
        "metadata": {"generated_artifact_origin": "orchestration_retained_output"},
    }
    if unavailable:
        message.update(content=UNAVAILABLE_HISTORY, content_unavailable=True, file_content="", extracted_text="")
    else:
        message["filename"] = "history.txt"
    api.messages.append(message)
    files = mount_outputs(page, api)
    enable_uploaded_file_preview(page)
    entry = page.locator("#message-generated-history")
    expect(entry).to_be_visible()
    expect(entry.get_by_role("button")).to_have_count(0)
    expect(entry.get_by_role("link")).to_have_count(0)
    if unavailable:
        expect(entry.get_by_role("status")).to_have_text(UNAVAILABLE_HISTORY)
        expect(entry).to_contain_text("Generated file unavailable")
    else:
        expect(entry).to_contain_text("history.txt")
        expect(entry).to_contain_text("committed output card")
    expect(file_card(files, "findings.csv").get_by_role("button", name="Download CSV")).to_be_enabled()
    assert not write_calls(api)


@pytest.mark.parametrize("width", [1440, 390])
def test_unavailable_history_hydration_closes_cached_preview_and_keeps_uploads_working(outputs_ui, width):
    page, api = outputs_ui
    page.set_viewport_size({"width": width, "height": 900})
    api.messages.append({
        "id": "cached-file", "conversation_id": CONVERSATION, "role": "file",
        "filename": "uploaded.txt", "content": "",
    })
    previews = []

    def preview_response(route):
        previews.append(route.request.post_data_json)
        route.fulfill(json={
            "filename": "uploaded.txt", "file_content": "Cached preview before access changed.",
            "file_content_source": "blob",
        })

    page.route("**/api/get_file_content", preview_response)
    mount_outputs(page, api)
    enable_uploaded_file_preview(page)
    entry = page.locator("#message-cached-file")
    upload = entry.get_by_role("button", name="uploaded.txt", exact=True)
    upload.focus()
    upload.press("Enter")
    dialog = page.get_by_role("dialog", name="Uploaded file: uploaded.txt")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("Cached preview before access changed.")
    # Strict Mode may read twice; replacing the history entry must not add a read.
    initial_previews = list(previews)
    assert initial_previews
    assert all(request == {"conversation_id": CONVERSATION, "file_id": "cached-file"}
               for request in initial_previews)
    page.evaluate("""(content) => {
        const C = window.OrchHarness.stores.chat.useChatStore;
        C.setState({ messages: C.getState().messages.map(message => message.id === 'cached-file'
            ? { ...message, content, content_unavailable: true, file_content: '', extracted_text: '',
                metadata: { generated_artifact_origin: 'orchestration_retained_output' } }
            : message) });
    }""", UNAVAILABLE_HISTORY)
    expect(dialog).to_have_count(0)
    expect(entry.get_by_role("status")).to_have_text(UNAVAILABLE_HISTORY)
    expect(entry).not_to_contain_text("uploaded.txt")
    expect(entry.get_by_role("button")).to_have_count(0)
    expect(page.get_by_text("Cached preview before access changed.", exact=True)).to_have_count(0)
    assert previews == initial_previews
    assert not write_calls(api)


def test_all_file_states_show_server_status_and_scheduled_time_without_early_retry(outputs_ui):
    page, api = outputs_ui
    api.record["outputs"] = [
        public_output("orender_" + f"{index:064x}", state, f"{state}.csv", f"file_{index}")
        for index, state in enumerate(("waiting", "rendering", "retry_scheduled", "completed", "failed", "cancelled"), 1)
    ]
    api.publish()
    files = mount_outputs(page, api)
    labels = files.get_by_role("status").all_text_contents()
    assert labels == ["Waiting", "Rendering", "Automatic retry scheduled", "Completed", "Failed", "Cancelled"]
    expect(files.locator("time")).to_have_attribute("datetime", "2026-09-23T14:30:00Z")
    expect(file_card(files, "retry_scheduled.csv")).to_contain_text("Retrying automatically at")
    # A badge that already says Waiting or Rendering is not repeated as a sentence.
    for state in ("waiting", "rendering", "completed"):
        expect(file_card(files, f"{state}.csv")).not_to_contain_text(public_output(READY_ID, state)["message"])
    expect(file_card(files, "failed.csv")).to_contain_text("This file could not be created.")
    expect(file_card(files, "cancelled.csv")).to_contain_text("This file was cancelled.")
    expect(files.get_by_role("button", name=re.compile("^Retry file "))).to_have_count(1)
    expect(files.get_by_role("button", name="Download CSV")).to_have_count(1)
    assert not write_calls(api)


def test_duplicate_activation_sends_one_file_action(outputs_ui):
    page, api = outputs_ui
    api.retry_mode = "delayed"
    files = mount_outputs(page, api)
    retry_button(files).evaluate("(button) => { button.click(); button.click(); }")
    expect(retry_button(files)).to_be_disabled()
    page.wait_for_function(
        """(runId) => Object.values(window.OrchHarness.stores.orchestration.useOrchestrationStore
            .getState().runRecovery[runId].outputRetries || {}).some(action => action.submissionId)""",
        arg=api.plan["run_id"],
    )
    expect(file_card(files, "findings.csv").get_by_role("button", name="Download CSV")).to_be_enabled()
    page.wait_for_function("() => document.body.textContent.includes('Requesting file retry...')")
    api.release()
    expect(file_card(files).get_by_role("status")).to_have_text("Waiting")
    assert len(write_calls(api)) == 1
    assert len(api.accepted) == 1


@pytest.mark.parametrize("mode", ["network", "server_error"])
def test_uncertain_retry_reuses_its_uuid_and_hides_transport_details(outputs_ui, mode):
    page, api = outputs_ui
    api.retry_mode = mode
    files = mount_outputs(page, api)
    retry_button(files).click()
    expect(file_card(files).get_by_role("alert")).to_contain_text("could not be confirmed")
    expect(retry_button(files)).to_be_enabled()
    expect(retry_button(files)).to_have_text("Retry same request")
    expect(page.get_by_text("PRIVATE PROVIDER DETAIL MUST NOT BE SHOWN")).to_have_count(0)
    first_id = write_calls(api)[0]["body"]["submission_id"]
    api.retry_mode = "success"
    retry_button(files).click()
    expect(file_card(files).get_by_role("status")).to_have_text("Waiting")
    assert [request["body"]["submission_id"] for request in write_calls(api)] == [first_id, first_id]
    assert len(api.accepted) == 1


def test_lost_accepted_retry_is_reconciled_without_another_post(outputs_ui):
    page, api = outputs_ui
    api.retry_mode = "lost"
    files = mount_outputs(page, api)
    retry_button(files).click()
    expect(file_card(files).get_by_role("status")).to_have_text("Waiting")
    expect(file_card(files).get_by_role("alert")).to_have_count(0)
    expect(retry_button(files)).to_have_count(0)
    assert len(write_calls(api)) == 1
    assert len(api.accepted) == 1
    state = recovery_tests.main_state(page)
    assert not state["inFlight"]


def test_unconfirmed_action_survives_reload_and_duplicate_receipt_does_not_advance_attempt(outputs_ui):
    page, api = outputs_ui
    api.retry_mode = "lost_stale"
    files = mount_outputs(page, api)
    retry_button(files).click()
    expect(file_card(files).get_by_role("alert")).to_contain_text("could not be confirmed")
    expect(retry_button(files)).to_be_enabled()
    first_id = write_calls(api)[0]["body"]["submission_id"]
    page.reload()
    files = mount_outputs(page, api)
    expect(file_card(files).get_by_role("alert")).to_contain_text("previous file retry")
    assert len(write_calls(api)) == 1
    api.retry_mode = "success"
    retry_button(files).focus()
    retry_button(files).press("Space")
    expect(file_card(files).get_by_role("status")).to_have_text("Waiting")
    assert [request["body"]["submission_id"] for request in write_calls(api)] == [first_id, first_id]
    assert api.output["attempt_count"] == 4
    assert len(api.accepted) == 1


@pytest.mark.parametrize("aggregate", ["failed", "completed"])
def test_pending_files_poll_after_terminal_aggregate_without_reexecution(outputs_ui, aggregate):
    page, api = outputs_ui
    api.record.update(status=aggregate, outcome="partial")
    api.record["plan"]["status"] = aggregate
    api.record["outputs"][1] = public_output(RETRY_ID, "retry_scheduled", "summary.csv", "file_b")
    api.publish()
    page.clock.install()
    files = mount_outputs(page, api)
    expect(file_card(files).get_by_role("status")).to_have_text("Automatic retry scheduled")
    api.record["outputs"][1] = public_output(RETRY_ID, "completed", "summary.csv", "file_b")
    api.publish()
    page.clock.fast_forward(5100)
    expect(file_card(files).get_by_role("status")).to_have_text("Completed")
    expect(files.get_by_role("button", name="Download CSV")).to_have_count(2)
    assert api.record["outcome"] == "partial"
    assert not write_calls(api)


# The server records a run's outcome on the run alone, so a real stored plan still reads running.
@pytest.mark.parametrize("stored_plan_status", ["completed", "running"])
def test_pending_outputs_restore_without_a_saved_assistant_message(outputs_ui, stored_plan_status):
    page, api = outputs_ui
    api.record.update(status="completed", outcome="partial", assistant_message_id=None, message_saved=False)
    api.record["plan"]["status"] = stored_plan_status
    api.record["outputs"][1] = public_output(RETRY_ID, "rendering", "summary.csv", "file_b")
    api.publish()
    api.messages = api.messages[:1]
    files = mount_outputs(page, api)
    expect(file_card(files).get_by_role("status")).to_have_text("Rendering")
    expect(page.get_by_role("button", name="Approve and run the plan")).to_have_count(0)
    expect(page.get_by_role("button", name="Cancel this plan")).to_have_count(0)
    assert not write_calls(api)


@pytest.mark.parametrize("hydration_path", ["direct-resume", "map-first"])
@pytest.mark.parametrize("width", [1440, 390])
def test_lean_list_output_hydration_recovers_terminal_run_and_polls_files(outputs_ui, hydration_path, width):
    """Only live outputs on the lean list may discover this otherwise terminal run."""
    page, api = outputs_ui
    page.set_viewport_size({"width": width, "height": 900})
    api.record.update(status="completed", outcome="partial", finalization_status="saved", message_saved=True)
    api.record["plan"]["status"] = "completed"
    api.record["plan_summary"]["status"] = "completed"
    api.record["outputs"][1] = public_output(RETRY_ID, "retry_scheduled", "summary.csv", "file_b")
    api.publish()
    api.record["artifact_count"] = len(api.record["generated_artifacts"])
    api.messages = api.messages[:1]
    initial_messages = copy.deepcopy(api.messages)
    list_responses = []
    detail_path = editor_tests.RUNS + "/" + api.plan["run_id"]

    def lean_list_response(route):
        request = route.request
        query = urlsplit(request.url).query
        parameters = parse_qs(query)
        assert request.method == "GET"
        assert parameters["conversation_id"] == [CONVERSATION]
        assert "include_plan" not in parameters
        fields = (
            "run_id", "conversation_id", "turn_id", "status", "plan_summary",
            "user_message_id", "assistant_message_id", "created_at", "completed_at",
            "attempt_index", "outcome", "finalization_status", "message_saved", "recovery", "outputs",
        )
        row = {key: copy.deepcopy(api.record[key]) for key in fields if key in api.record}
        row["artifact_count"] = sum(
            output["state"] == "completed" and output["available"] for output in row["outputs"]
        )
        list_responses.append(row)
        api.requests.append({"path": editor_tests.RUNS, "method": request.method, "body": None, "query": query})
        route.fulfill(json={"runs": [row]})

    page.route("**" + editor_tests.RUNS + "?*", lean_list_response)
    page.clock.install()
    recovery_tests.mount_recovery(page, api, saved=True, resume_saved=False)
    before = recovery_tests.main_state(page)
    assert before["messages"] == initial_messages
    assert not before["inFlight"]
    assert not api.calls(editor_tests.RUNS)
    assert not api.calls(detail_path)

    if hydration_path == "map-first":
        page.evaluate("""(conversationId) => {
            const H = window.OrchHarness;
            H.unmount('mount-a');
            H.mount('mount-a', 'OrchestrationMapView', {
                conversationId, shownTurnId: null,
                onSelectRun: () => { throw new Error('Lean hydration must not select an archived run.'); },
            }, { strictMode: true });
        }""", CONVERSATION)
        page.wait_for_function("""(conversationId) => window.OrchHarness.stores.orchestration
            .useOrchestrationStore.getState().hydration[conversationId] === 'loaded'""", arg=CONVERSATION)
        cached = page.evaluate("""(conversationId) => {
            const H = window.OrchHarness;
            const state = H.stores.orchestration.useOrchestrationStore.getState();
            const newest = state.hydratedHistory[conversationId][0];
            return { planCount: Object.keys(state.plans).length, status: newest.planStatus,
                outputs: newest.attempt.outputs,
                aggregatePending: H.orchestration.isOrchestrationRunPending({
                    ...newest.attempt, status: newest.planStatus,
                }) };
        }""", CONVERSATION)
        assert cached["planCount"] == 0
        assert cached["status"] == "completed"
        assert cached["aggregatePending"] is False
        assert cached["outputs"][1]["state"] == "retry_scheduled"
        assert len(api.calls(editor_tests.RUNS)) == 1
        assert not api.calls(detail_path)
        page.evaluate("""() => {
            const H = window.OrchHarness;
            H.unmount('mount-a');
            H.mount('mount-a', 'PlanEditorExperience', {}, { strictMode: true });
        }""")

    page.evaluate("""(conversationId) => window.OrchHarness.resume
        .resumeOrchestrationForConversation(conversationId)""", CONVERSATION)
    files = page.get_by_role("region", name="Files from this plan").first
    expect(files).to_be_visible()
    expect(files.get_by_role("button", name="Check saved file status", exact=True)).to_be_enabled()
    expect(file_card(files).get_by_role("status")).to_have_text("Automatic retry scheduled")
    expect(file_card(files, "findings.csv").get_by_role("button", name="Download CSV")).to_be_enabled()
    adopted = page.evaluate("""(conversationId) => {
        const state = window.OrchHarness.stores.orchestration.useOrchestrationStore.getState();
        const turnId = state.activeTurns[conversationId];
        return { turnId, runId: state.plans[`${conversationId}\\u0000${turnId}`]?.run_id };
    }""", CONVERSATION)
    initial_detail_reads = len(api.calls(detail_path))
    assert adopted == {"turnId": TURN, "runId": api.plan["run_id"]}
    assert initial_detail_reads > 0
    assert len(api.calls(editor_tests.RUNS)) == 1
    assert len(list_responses) == 1
    assert list_responses[0]["status"] == "completed"
    assert list_responses[0]["outputs"][1]["state"] == "retry_scheduled"
    assert list_responses[0]["artifact_count"] == 1
    assert "plan" not in list_responses[0]
    assert "generated_artifacts" not in list_responses[0]
    assert "artifacts" not in list_responses[0]

    api.record["outputs"][1] = public_output(RETRY_ID, "completed", "summary.csv", "file_b")
    api.publish()
    api.record["artifact_count"] = len(api.record["generated_artifacts"])
    page.clock.fast_forward(5100)
    expect(file_card(files).get_by_role("status")).to_have_text("Completed")
    expect(files.get_by_role("button", name="Download CSV")).to_have_count(2)
    restored = recovery_tests.main_state(page)
    assert len(api.calls(detail_path)) > initial_detail_reads
    assert len(api.calls(editor_tests.RUNS)) == 1
    assert restored["messages"] == initial_messages
    assert not restored["inFlight"]
    assert api.record["status"] == "completed"
    assert api.record["outcome"] == "partial"
    assert not write_calls(api)


@pytest.mark.parametrize("mode", ["transport", "bare_done", "terminal_without_outputs"])
def test_incremental_step_outputs_keep_siblings_and_stream_loss_reads_saved_files(outputs_ui, mode):
    page, api = outputs_ui
    api.output_stream = mode
    api.messages = api.messages[:1]
    recovery_tests.mount_recovery(page, api)
    page.get_by_role("button", name="Approve and run the plan").click()
    files = page.get_by_role("region", name="Files from this plan").first
    expect(files.get_by_role("article")).to_have_count(2)
    expect(file_card(files, "findings.csv").get_by_role("button", name="Download CSV")).to_be_visible()
    expect(file_card(files).get_by_role("status")).to_have_text(
        "Automatic retry scheduled" if mode in ("transport", "bare_done") else "Failed"
    )
    expect(files.get_by_role("button", name="Check saved file status", exact=True)).to_be_enabled()
    assert [request["path"] for request in write_calls(api)] == [editor_tests.RUN]
    state = recovery_tests.main_state(page)
    assert state["history"][CONVERSATION][0]["status"] == "failed"


def test_older_recovery_read_cannot_erase_new_retry_receipt(outputs_ui):
    page, api = outputs_ui
    files = mount_outputs(page, api)
    api.hold_next_detail = True
    page.evaluate("""(spec) => { window.OrchHarness.controller.loadOrchestrationRecovery(
        spec.conversation, spec.runId); }""", {"conversation": CONVERSATION, "runId": api.plan["run_id"]})
    retry_button(files).click()
    expect(file_card(files).get_by_role("status")).to_have_text("Waiting")
    api.release()
    expect(file_card(files).get_by_role("status")).to_have_text("Waiting")
    retried = next(output for output in saved_outputs(page, api.plan["run_id"]) if output["output_id"] == RETRY_ID)
    assert retried["attempt_count"] == 4
    assert len(write_calls(api)) == 1


def test_delayed_retry_receipt_cannot_undo_newer_completed_projection(outputs_ui):
    page, api = outputs_ui
    api.retry_mode = "delayed"
    page.clock.install()
    files = mount_outputs(page, api)
    retry_button(files).click()
    page.wait_for_function(
        """(runId) => Object.values(window.OrchHarness.stores.orchestration.useOrchestrationStore
            .getState().runRecovery[runId].outputRetries || {}).some(action => action.submissionId)""",
        arg=api.plan["run_id"],
    )
    page.clock.fast_forward(5100)
    expect(file_card(files).get_by_role("status")).to_have_text("Waiting")
    api.output.update(
        state="completed", artifact_message_id="artifact-" + RETRY_ID,
        message="This file is ready.", row_count=7, size_bytes=len(CSV_CONTENT.encode("utf-8")),
    )
    api.publish()
    page.clock.fast_forward(5100)
    expect(file_card(files).get_by_role("status")).to_have_text("Completed")
    page.evaluate("""(spec) => {
        const S = window.OrchHarness.stores.orchestration.useOrchestrationStore;
        window.outputObservedStates = [];
        window.stopOutputObservation = S.subscribe(state => {
            window.outputObservedStates.push(state.runRecovery[spec.runId]?.outputs
                ?.find(output => output.output_id === spec.outputId)?.state);
        });
    }""", {"runId": api.plan["run_id"], "outputId": RETRY_ID})
    try:
        api.release()
        page.wait_for_function(
            """(runId) => !Object.values(window.OrchHarness.stores.orchestration.useOrchestrationStore
                .getState().runRecovery[runId].outputRetries || {}).some(action => action.submitting)""",
            arg=api.plan["run_id"],
        )
        observed = page.evaluate("() => window.outputObservedStates")
        assert observed
        assert set(observed) == {"completed"}
        expect(files.get_by_role("button", name="Download CSV")).to_have_count(2)
    finally:
        page.evaluate("""() => {
            window.stopOutputObservation();
            delete window.stopOutputObservation;
            delete window.outputObservedStates;
        }""")


@pytest.mark.parametrize("status", [401, 403, 404, 409])
def test_auth_or_conflict_rejection_is_safe_and_does_not_hide_ready_sibling(outputs_ui, status):
    page, api = outputs_ui
    api.retry_mode = "denied"
    api.retry_status = status
    files = mount_outputs(page, api)
    retry_button(files).click()
    expect(file_card(files).get_by_role("alert")).to_be_visible()
    expect(retry_button(files)).to_be_disabled()
    expect(file_card(files, "findings.csv").get_by_role("button", name="Download CSV")).to_be_enabled()
    expect(page.get_by_text("PRIVATE PROVIDER DETAIL MUST NOT BE SHOWN")).to_have_count(0)
    assert not api.accepted
    assert len(write_calls(api)) == 1
    api.retry_mode = "success"
    files.get_by_role("button", name="Check saved file status", exact=True).click()
    expect(retry_button(files)).to_be_enabled()


@pytest.mark.parametrize("reason,message", [
    ("output_access_denied", "This file is unavailable because current source access could not be confirmed."),
    ("output_screening_hold", "This file is unavailable while its source is under review."),
    ("output_deleted", "This file was deleted."),
])
@pytest.mark.parametrize("width", [1440, 390])
def test_authoritative_unavailability_withholds_stale_card_but_preserves_ready_sibling(outputs_ui, reason, message, width):
    page, api = outputs_ui
    page.set_viewport_size({"width": width, "height": 900})
    api.record["outputs"][1] = public_output(RETRY_ID, "completed", "summary.csv", "file_b")
    api.publish()
    stale_messages = copy.deepcopy(api.messages)
    stale_record = copy.deepcopy(api.record)
    files = mount_outputs(page, api)
    expect(files.get_by_role("button", name="Download CSV")).to_have_count(2)
    initial_outputs = saved_outputs(page, api.plan["run_id"])
    api.output.update(
        available=False, artifact_message_id=None, can_retry=False, next_retry_at=None,
        row_count=None, character_count=None, size_bytes=None, error_code=reason, message=message,
    )
    api.publish()
    files.get_by_role("button", name="Check saved file status", exact=True).click()
    expect(file_card(files).get_by_role("status")).to_have_text("Unavailable")
    expect(files.get_by_role("button", name="Download CSV")).to_have_count(1)
    page.evaluate("""(messages) => window.OrchHarness.stores.chat.useChatStore.setState({messages})""", stale_messages)
    page.evaluate("""(spec) => window.OrchHarness.stores.orchestration.useOrchestrationStore.getState()
        .hydrateConversationRuns(spec.conversation, [spec.run])""", {
            "conversation": CONVERSATION, "run": stale_record,
        })
    expect(file_card(files).get_by_role("button", name="Download CSV")).to_have_count(0)
    expect(file_card(files)).to_contain_text(message)
    expect(file_card(files)).not_to_contain_text(reason)
    expect(file_card(files, "findings.csv").get_by_role("button", name="Download CSV")).to_be_enabled()
    unavailable_outputs = saved_outputs(page, api.plan["run_id"])
    assert unavailable_outputs[0] == initial_outputs[0]
    for field in ("output_id", "step_id", "file_name", "output_format", "profile", "state",
                  "attempt_count", "automatic_attempts", "max_automatic_attempts"):
        assert unavailable_outputs[1][field] == initial_outputs[1][field]
    for field in ("artifact_message_id", "next_retry_at", "row_count", "character_count", "size_bytes"):
        assert unavailable_outputs[1][field] is None
    assert unavailable_outputs[1]["available"] is False
    assert unavailable_outputs[1]["can_retry"] is False
    if reason != "output_deleted":
        api.record["outputs"][1] = copy.deepcopy(stale_record["outputs"][1])
        api.publish()
        check = files.get_by_role("button", name="Check saved file status", exact=True)
        check.focus()
        check.press("Enter")
        expect(file_card(files).get_by_role("status")).to_have_text("Completed")
        expect(files.get_by_role("button", name="Download CSV")).to_have_count(2)
        restored_outputs = saved_outputs(page, api.plan["run_id"])
        assert restored_outputs == initial_outputs
        assert not api.accepted
    assert not write_calls(api)


@pytest.mark.parametrize("mode", ["server_error", "network"])
@pytest.mark.parametrize("width", [1440, 390])
def test_status_read_failure_preserves_progress_without_inventing_source_denial(outputs_ui, mode, width):
    page, api = outputs_ui
    page.set_viewport_size({"width": width, "height": 900})
    files = mount_outputs(page, api)
    initial_outputs = saved_outputs(page, api.plan["run_id"])
    detail_path = editor_tests.RUNS + "/" + api.plan["run_id"]
    route_pattern = "**" + detail_path + "*"

    def fail_status_read(route):
        if mode == "network":
            api.expected_console_errors.add((detail_path, "net::ERR_FAILED"))
            route.abort("failed")
        else:
            api.fail_request(route, 503, "output_storage_unavailable")

    page.route(route_pattern, fail_status_read)
    check = files.get_by_role("button", name="Check saved file status", exact=True)
    check.click()
    expect(files.get_by_role("alert")).to_contain_text("Previous progress is shown; no work was restarted.")
    expect(file_card(files, "findings.csv").get_by_role("status")).to_have_text("Completed")
    expect(file_card(files).get_by_role("status")).to_have_text("Failed")
    expect(file_card(files, "findings.csv").get_by_role("button", name="Download CSV")).to_be_enabled()
    expect(files.get_by_text("output_access_denied", exact=True)).to_have_count(0)
    expect(page.get_by_text("PRIVATE PROVIDER DETAIL MUST NOT BE SHOWN")).to_have_count(0)
    after_failure = saved_outputs(page, api.plan["run_id"])
    assert after_failure == initial_outputs
    page.unroute(route_pattern, fail_status_read)
    check.click()
    expect(files.get_by_role("alert")).to_have_count(0)
    after_recovery = saved_outputs(page, api.plan["run_id"])
    assert after_recovery == initial_outputs
    assert not write_calls(api)


@pytest.mark.parametrize("mismatch", [
    "missing", "conversation_id", "source_conversation_id", "artifact_message_id", "output_id", "source_kind",
    "file_name", "output_format", "profile",
])
def test_completed_state_never_manufactures_a_download_descriptor(outputs_ui, mismatch):
    page, api = outputs_ui
    if mismatch == "missing":
        api.record["generated_artifacts"] = []
    elif mismatch in ("file_name", "output_format", "profile"):
        api.record["generated_artifacts"][0][mismatch] = None
    else:
        api.record["generated_artifacts"][0][mismatch] = "wrong-identity"
    api.messages[-1]["generated_artifacts"] = copy.deepcopy(api.record["generated_artifacts"])
    files = mount_outputs(page, api)
    expect(file_card(files, "findings.csv").get_by_role("status")).to_have_text("Completed")
    expect(files.get_by_role("button", name="Download CSV")).to_have_count(0)
    expect(files.get_by_role("link")).to_have_count(0)
    expect(file_card(files, "findings.csv")).to_contain_text("Download details are not available")
    assert not write_calls(api)


def test_output_names_are_inert_text_on_mobile(outputs_ui):
    page, api = outputs_ui
    page.set_viewport_size({"width": 390, "height": 844})
    unsafe = "<img src=https://invalid.example/x onerror=window.outputNameExecuted=true>.csv"
    api.output["file_name"] = unsafe
    api.publish()
    files = mount_outputs(page, api)
    card = file_card(files, unsafe)
    expect(card.get_by_role("heading", name=unsafe, exact=True)).to_be_visible()
    expect(card.get_by_role("button", name=f"Retry file {unsafe}", exact=True)).to_be_enabled()
    expect(files.locator("img, script, iframe")).to_have_count(0)
    executed = page.evaluate("() => Boolean(window.outputNameExecuted)")
    overflow = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
    assert not executed
    assert not overflow


def test_file_retry_rechecks_server_eligibility_before_posting(outputs_ui):
    page, api = outputs_ui
    files = mount_outputs(page, api)
    api.output.update(state="cancelled", can_retry=False, message="This file was cancelled.")
    retry_button(files).click()
    expect(file_card(files).get_by_role("status")).to_have_text("Cancelled")
    expect(retry_button(files)).to_have_count(0)
    assert not write_calls(api)


def test_exhaustion_does_not_override_server_retry_policy_or_enable_whole_run_replay(outputs_ui):
    page, api = outputs_ui
    api.output["can_retry"] = False
    api.publish()
    files = mount_outputs(page, api)
    expect(file_card(files).get_by_role("status")).to_have_text("Failed")
    expect(file_card(files)).to_contain_text("This file could not be created.")
    expect(file_card(files)).not_to_contain_text("Automatic attempts")
    expect(retry_button(files)).to_have_count(0)
    page.evaluate("""(spec) => window.OrchHarness.controller.retryOrchestrationRun(
        spec.conversation, spec.runId)""", {"conversation": CONVERSATION, "runId": api.plan["run_id"]})
    expect(page.get_by_role("alert")).to_contain_text("individual file retry controls")
    assert not write_calls(api)


def test_retry_requires_durable_tab_identity_and_supports_uuid_fallback(outputs_ui):
    page, api = outputs_ui
    files = mount_outputs(page, api)
    page.evaluate("""() => {
        window.savedSessionStorageDescriptor = Object.getOwnPropertyDescriptor(window, 'sessionStorage');
        Object.defineProperty(window, 'sessionStorage', {
            configurable: true, get() { throw new DOMException('Storage disabled'); },
        });
    }""")
    try:
        retry_button(files).click()
        expect(file_card(files).get_by_role("alert")).to_contain_text("retry identity could not be saved")
        assert not write_calls(api)
    finally:
        page.evaluate("""() => {
            Object.defineProperty(window, 'sessionStorage', window.savedSessionStorageDescriptor);
            delete window.savedSessionStorageDescriptor;
        }""")
    page.evaluate("""() => {
        window.savedRandomUuid = crypto.randomUUID;
        crypto.randomUUID = undefined;
    }""")
    try:
        retry_button(files).click()
        expect(file_card(files).get_by_role("status")).to_have_text("Waiting")
        submitted = uuid.UUID(write_calls(api)[0]["body"]["submission_id"])
        assert submitted.version == 4
    finally:
        page.evaluate("""() => {
            crypto.randomUUID = window.savedRandomUuid;
            delete window.savedRandomUuid;
        }""")


def test_download_access_error_uses_existing_safe_card_and_does_not_navigate(outputs_ui):
    page, api = outputs_ui
    api.download_status = 403
    files = mount_outputs(page, api)
    page.evaluate("() => window.OrchHarness.mount('mount-b', 'Toaster')")
    original_url = page.url
    file_card(files, "findings.csv").get_by_role("button", name="Download CSV").click()
    expect(page.get_by_text("The artifact could not be downloaded. Refresh the conversation and try again.")).to_be_visible()
    expect(page.get_by_text("PRIVATE PROVIDER DETAIL MUST NOT BE SHOWN")).to_have_count(0)
    assert page.url == original_url
    assert len(api.calls(DOWNLOAD_PATH)) == 1
    assert not write_calls(api)


@pytest.mark.parametrize("mask", [{"masked": True}, {"masked_ranges": [{"start": 0, "end": 5}]}])
def test_masked_message_does_not_expose_new_output_cards(outputs_ui, mask):
    page, api = outputs_ui
    api.messages[-1]["metadata"].update(mask)
    recovery_tests.mount_recovery(page, api, saved=True)
    expect(page.get_by_role("region", name="Files from this plan")).to_have_count(0)
    expect(page.get_by_role("button", name="Download CSV")).to_have_count(0)
    assert not write_calls(api)


def test_artifact_aliases_still_deduplicate_without_file_recovery(outputs_ui):
    page, api = outputs_ui
    api.record.pop("outputs")
    api.record.update(status="completed", outcome="completed")
    api.publish()
    legacy = {
        "capability": "tabular", "artifact_message_id": "legacy-file", "conversation_id": CONVERSATION,
        "file_name": "legacy.csv", "output_format": "csv", "storage_scope": "chat", "row_count": 2,
    }
    api.messages[-1]["generated_artifacts"] = [
        {**legacy, "artifact_message_id": "", "background_export": True, "export_run_id": "old-native-export"},
        legacy,
    ]
    api.messages[-1]["metadata"].update(
        generated_analysis_artifacts=[legacy], generated_tabular_outputs=[legacy],
    )
    recovery_tests.mount_recovery(page, api, saved=True)
    expect(page.get_by_role("button", name="Download CSV")).to_have_count(1)
    expect(page.get_by_role("region", name="Files from this plan")).to_have_count(0)
    assert not api.calls(CATALOG_PATH)
    assert not write_calls(api)


def test_catalog_is_fetched_only_on_request_with_owned_run_context(outputs_ui):
    page, api = outputs_ui
    mount_outputs(page, api)
    page.get_by_role("button", name="Review saved attempt").first.click()
    drawer = page.get_by_role("complementary", name="Review drawer")
    load = drawer.get_by_role("button", name="Load server file format reference", exact=True)
    expect(load).to_be_visible()
    assert not api.calls(CATALOG_PATH)
    load.focus()
    load.press("Enter")
    reference = drawer.get_by_text("Server file format reference", exact=True)
    expect(reference).to_be_visible()
    reference.click()
    expect(drawer.get_by_text("csv (.csv)", exact=True)).to_be_visible()
    expect(drawer.get_by_text("Profile: tabular_records_v1", exact=True)).to_be_visible()
    expect(drawer.get_by_text("xlsx (.xlsx)", exact=True)).to_have_count(0)
    assert len(api.calls(CATALOG_PATH)) == 1
    assert not write_calls(api)


def test_catalog_rendering_unavailable_keeps_saved_file_intent_without_guessed_formats(outputs_ui):
    page, api = outputs_ui
    api.catalog_status = 403
    mount_outputs(page, api)
    page.get_by_role("button", name="Review saved attempt").first.click()
    drawer = page.get_by_role("complementary", name="Review drawer")
    planned_file = drawer.get_by_role("region", name="Planned file for Prepare summary.csv")
    expect(planned_file).to_be_visible()
    drawer.get_by_role("button", name="Load server file format reference", exact=True).click()
    expect(drawer.get_by_role("alert")).to_contain_text("file format reference could not be loaded")
    expect(drawer.get_by_text("csv (.csv)", exact=True)).to_have_count(0)
    expect(planned_file).to_be_visible()
    expect(planned_file.get_by_text("summary.csv", exact=True)).to_be_visible()
    expect(planned_file.get_by_text("tabular_records_v1", exact=True)).to_be_visible()
    expect(planned_file).to_contain_text("source: Output findings from Prepare findings (records-v1)")
    expect(planned_file).to_contain_text("Requested output, not a completed download.")
    assert not write_calls(api)


def test_empty_catalog_reports_absence_instead_of_guessing_formats(outputs_ui):
    page, api = outputs_ui
    api.catalog_formats = []
    mount_outputs(page, api)
    page.get_by_role("button", name="Review saved attempt").first.click()
    drawer = page.get_by_role("complementary", name="Review drawer")
    drawer.get_by_role("button", name="Load server file format reference", exact=True).click()
    expect(drawer.get_by_text("The server did not advertise file formats for this plan.", exact=True)).to_be_visible()
    expect(drawer.get_by_text("csv (.csv)", exact=True)).to_have_count(0)
    assert not write_calls(api)


def test_editor_consumes_only_advertised_catalog_and_preserves_revision_behavior(editor_ui):
    page, api = editor_ui
    plan = dependency_tests.dependency_plan()
    original_projection = api.projection
    api.projection = lambda editor, before=None: {
        **original_projection(editor, before), "export_catalog": catalog(),
    }
    dependency_tests.mount_editor(page, api, plan)
    dialog = editor_tests.open_editor(page)
    reference = dialog.get_by_text("Server file format reference", exact=True)
    reference.click()
    expect(dialog.get_by_text("csv (.csv)", exact=True)).to_be_visible()
    editor_tests.ask(page, "Retain the same named source and improve the explanation")
    editor_tests.wait_revision(page, 1, dependency_tests.CONVERSATION, dependency_tests.TURN)
    state = dependency_tests.plan_state(page)
    assert state["plan"]["steps"][3]["inputs"] == plan["steps"][3]["inputs"]
    assert state["plan"]["edit_version"] == api.editors[dependency_tests.CONVERSATION]["version"]
    assert not api.calls(CATALOG_PATH)


@pytest.mark.parametrize("width", [1440, 390])
def test_file_free_editor_accepts_revisions_with_empty_server_catalog(editor_ui, monkeypatch, width):
    page, api = editor_ui
    page.set_viewport_size({"width": width, "height": 900})
    plan = dependency_tests.dependency_plan()
    original_stream = api.stream
    monkeypatch.setattr(api, "stream", lambda route, event: original_stream(
        route, {**event, "export_catalog": []},
    ))
    dependency_tests.mount_editor(page, api, plan)
    dialog = editor_tests.open_editor(page)
    editor_tests.ask(page, "Clarify the evidence review without creating files.")
    editor_tests.wait_revision(page, 1, dependency_tests.CONVERSATION, dependency_tests.TURN)
    empty_catalog = dialog.get_by_text("The server did not advertise file formats for this plan.", exact=True)
    expect(empty_catalog).to_be_visible()
    expect(dialog.get_by_role("button", name="Run saved revision", exact=True)).to_be_enabled()
    expect(dialog.get_by_role("button", name="Load server file format reference", exact=True)).to_have_count(0)
    editor_tests.ask(page, "Refine the final answer while retaining the same named inputs.")
    editor_tests.wait_revision(page, 2, dependency_tests.CONVERSATION, dependency_tests.TURN)
    expect(empty_catalog).to_be_visible()
    expect(dialog.get_by_role("button", name="Run saved revision", exact=True)).to_be_enabled()
    expect(dialog.get_by_text("csv (.csv)", exact=True)).to_have_count(0)
    state = dependency_tests.plan_state(page)
    assert state["plan"]["planner_contract_version"] == 2
    assert state["plan"]["edit_version"] == api.editors[dependency_tests.CONVERSATION]["version"]
    assert state["plan"]["final_response"] == plan["final_response"]
    assert [step["capability_id"] for step in state["plan"]["steps"]] == [
        step["capability_id"] for step in plan["steps"]
    ]
    assert [step["inputs"] for step in state["plan"]["steps"]] == [step["inputs"] for step in plan["steps"]]
    assert [step["outputs"] for step in state["plan"]["steps"]] == [step["outputs"] for step in plan["steps"]]
    assert not api.calls(CATALOG_PATH)
    assert not api.calls("/run")
    assert not api.calls("/retry")
    assert not api.successful_runs


def test_new_plan_event_catalog_is_adopted_without_a_second_format_request(editor_ui):
    page, api = editor_ui
    dependency_tests.mount_editor(page, api)

    def plan_response(route):
        body = route.request.post_data_json
        plan = dependency_tests.dependency_plan(body["conversation_id"], body["turn_id"])
        plan.update(run_id="catalog-plan-run", plan_id="catalog-plan")
        dependency_tests.seed_editor(api, plan)
        editor_tests.EditorApi.stream(route, {
            "type": "orchestration_plan", "done": True, "plan": plan, "export_catalog": catalog(),
        })

    page.route("**/api/v2/orchestration/plan", plan_response)
    page.evaluate("""async (conversationId) => {
        const H = window.OrchHarness;
        await H.controller.startOrchestrationPlan({
            conversationId, message: 'Prepare findings using the shared catalog.', approvalMode: 'manual',
        });
        H.stores.chat.useChatStore.getState().setDrawerMode('plan');
    }""", dependency_tests.CONVERSATION)
    drawer = page.get_by_role("complementary", name="Review drawer")
    reference = drawer.get_by_text("Server file format reference", exact=True)
    expect(reference).to_be_visible()
    reference.click()
    expect(drawer.get_by_text("csv (.csv)", exact=True)).to_be_visible()
    assert not api.calls(CATALOG_PATH)
    assert not api.successful_runs


def test_editor_question_keeps_catalog_from_actual_event_envelope(editor_ui):
    page, api = editor_ui
    dependency_tests.mount_editor(page, api)
    dialog = editor_tests.open_editor(page)
    expect(dialog.get_by_text("Server file format reference", exact=True)).to_have_count(0)
    original_stream = api.stream
    api.stream = lambda route, event: original_stream(route, {**event, "export_catalog": catalog()})
    api.next_revision = "question"
    editor_tests.ask(page, "Which format should this file use?")
    expect(dialog.get_by_role("group", name="Plan focus")).to_be_visible()
    reference = dialog.get_by_text("Server file format reference", exact=True)
    reference.click()
    expect(dialog.get_by_text("csv (.csv)", exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_disabled()
    assert not api.calls(CATALOG_PATH)
    assert not api.successful_runs
