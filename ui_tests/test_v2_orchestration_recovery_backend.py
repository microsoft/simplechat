# test_v2_orchestration_recovery_backend.py
"""
Browser-to-Flask checkpoint recovery regressions.
Version: 0.261.105
Implemented in: 0.261.105

Real orchestration routes, executor, durable checkpoint codec, conditional attempts,
and message persistence run in the shared backend fixture. Only Azure/model/service
boundaries are deterministic. The real React UI uses the local/Azure Playwright harness.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from azure.core.exceptions import AzureError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, expect

import test_v2_orchestration_plan_editor as editor_tests
import test_v2_orchestration_recovery as recovery_tests
from test_v2_orchestration_plan_editor import (  # noqa: F401
    connect_options,
    editor_assets,
    editor_browser,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

# The shared fixture lives outside the UI test import directory.
from test_support.orchestration_recovery import RecoveryFixture  # noqa: E402


pytestmark = pytest.mark.ui


@pytest.fixture
def integrated_recovery(editor_browser, editor_assets):
    with RecoveryFixture() as backend:
        plan = backend.plan_attempt()
        record = backend.detail(plan["run_id"])
        context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        requests = []
        errors = []
        options = {"lose_terminal": False, "hold_finalization": False, "pending_detail": None}

        def forward(route):
            request = route.request
            url = urlsplit(request.url)
            if f"{url.scheme}://{url.netloc}" != editor_tests.ORIGIN:
                errors.append(f"Unexpected browser origin: {url.netloc}")
                route.abort()
                return
            if request.method == "GET" and url.path in editor_assets:
                route.fulfill(path=str(editor_assets[url.path]))
                return
            if url.path == "/favicon.ico":
                route.fulfill(status=204)
                return
            if url.path == "/api/get_messages":
                route.fulfill(json={"messages": [
                    row for row in backend.messages.items.values() if row.get("role") in ("user", "assistant")
                ]})
                return
            if not url.path.startswith("/api/v2/orchestration/"):
                errors.append(f"Unexpected browser request: {request.method} {url.path}")
                route.abort()
                return
            response = backend.client.open(
                url.path + (f"?{url.query}" if url.query else ""),
                method=request.method, data=request.post_data,
                content_type=request.headers.get("content-type"), buffered=True,
            )
            requests.append({
                "path": url.path, "status": response.status_code,
                "body": request.post_data_json if request.post_data else None,
            })
            content = response.get_data(as_text=True)
            pending = options["pending_detail"]
            if (options["hold_finalization"] and pending and request.method == "GET"
                    and url.path == f"{editor_tests.RUNS}/{pending['run_id']}"):
                # Replay the actual projection captured before the message batch committed.
                content = json.dumps({"run": pending})
            assert "SECRET_SENTINEL" not in content
            assert "private.test" not in content
            if options["lose_terminal"] and url.path == editor_tests.RUN:
                content = 'data: {"type":"thought","content":"Execution started"}\n\n'
            route.fulfill(status=response.status_code, content_type=response.content_type, body=content)

        page.route("**/*", forward)
        page.on("pageerror", lambda error: errors.append(str(error)))
        mounted = SimpleNamespace(
            assets=editor_assets, plan=plan,
            messages=[{
                "id": record["user_message_id"], "conversation_id": "conv1", "role": "user",
                "content": record["user_message"], "metadata": {"orchestration_turn_id": record["turn_id"]},
            }],
        )
        try:
            recovery_tests.mount_recovery(page, mounted)
            yield page, backend, requests, mounted, options
        finally:
            context.close()
            assert not errors, errors


def test_real_failed_agent_resume_reuses_checkpoints_and_survives_reload(integrated_recovery):
    page, backend, requests, mounted, _options = integrated_recovery
    initial_user_count = sum(row.get("role") == "user" for row in backend.messages.items.values())
    page.get_by_role("button", name="Approve and run the plan").click()
    retry = page.get_by_role("button", name="Retry from failed step")
    expect(retry.first).to_be_enabled()
    record = backend.detail(mounted.plan["run_id"])
    assert backend.calls == ["a", "b"]
    assert record["outcome"] == "partial"
    expect(page.get_by_text(record["failure"]["message"], exact=True).first).to_be_visible()
    assert recovery_tests.main_state(page)["messages"][-1]["metadata"]["orchestration"]["outcome"] == "partial"
    page.get_by_role("button", name="Review saved attempt").first.click()
    drawer = page.get_by_role("complementary", name="Review drawer")
    expect(drawer.get_by_text(record["failure"]["message"], exact=True).first).to_be_visible()
    drawer.get_by_role("button", name="Retry from failed step").click()
    page.get_by_role("dialog").get_by_role("button", name="Cancel", exact=True).click()
    assert not any(request["path"].endswith("/retry") for request in requests)
    assert backend.calls == ["a", "b"]

    backend.fail_b = False
    drawer.get_by_role("button", name="Retry from failed step").click()
    page.get_by_role("dialog").get_by_role("button", name="Confirm retry").click()
    try:
        page.wait_for_function("""() => window.OrchHarness.stores.chat.useChatStore.getState().messages.some(
            message => message.metadata?.orchestration?.attempt_index === 2
                && message.metadata.orchestration.outcome === 'completed')""")
    except PlaywrightTimeoutError as error:
        raise AssertionError({
            "requests": requests, "calls": backend.calls, "visible": page.locator("body").inner_text(),
        }) from error
    expect(drawer.get_by_text("Reused saved result", exact=True).first).to_be_visible()
    assert backend.calls == ["a", "b", "b", "c"]
    assert sum(row.get("role") == "user" for row in backend.messages.items.values()) == initial_user_count
    assert len([request for request in requests if request["path"].endswith("/retry")]) == 1
    assert len([request for request in requests if request["path"] == editor_tests.RUN]) == 2
    assert "Saved findings a" in json.dumps(backend.model.calls[-1])
    attempts = [message for message in recovery_tests.main_state(page)["messages"]
                if message.get("metadata", {}).get("orchestration", {}).get("attempt_index")]
    assert len(attempts) == 2
    assert attempts[0]["id"] == record["assistant_message_id"]
    assert attempts[1]["metadata"]["orchestration"]["retry_of_run_id"] == record["run_id"]

    mounted.messages = [
        row for row in backend.messages.items.values() if row.get("role") in ("user", "assistant")
    ]
    recovery_tests.mount_recovery(page, mounted, saved=True)
    expect(page.get_by_role("button", name="View current attempt").first).to_be_visible()
    page.get_by_role("button", name="View current attempt").first.click()
    try:
        expect(page.get_by_role("complementary", name="Review drawer")
               .get_by_text("Reused saved result", exact=True).first).to_be_visible()
    except AssertionError as error:
        raise AssertionError({"requests": requests[-10:], "visible": page.locator("body").inner_text()}) from error
    assert backend.calls == ["a", "b", "b", "c"]
    assert len([request for request in requests if request["path"] == editor_tests.RUN]) == 2


def test_edited_plan_resumes_without_reusing_its_approval_version(integrated_recovery):
    page, backend, requests, mounted, _options = integrated_recovery
    run_id = mounted.plan["run_id"]
    response = backend.client.post(
        f"/api/v2/orchestration/runs/{run_id}/edit",
        json={"conversation_id": "conv1", "plan_id": mounted.plan["plan_id"]},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    edited = backend.detail(run_id)["plan"]
    assert edited["edit_version"]
    assert backend.run_attempt(edited).status_code == 200
    assert backend.calls == ["a", "b"]

    mounted.messages = [
        row for row in backend.messages.items.values() if row.get("role") in ("user", "assistant")
    ]
    recovery_tests.mount_recovery(page, mounted, saved=True)
    backend.fail_b = False
    page.get_by_role("button", name="Retry from failed step").first.click()
    page.get_by_role("dialog").get_by_role("button", name="Confirm retry").click()
    page.wait_for_function("""() => window.OrchHarness.stores.chat.useChatStore.getState().messages.some(
        message => message.metadata?.orchestration?.attempt_index === 2
            && message.metadata.orchestration.outcome === 'completed')""")
    assert backend.calls == ["a", "b", "b", "c"]
    retry_run_requests = [request for request in requests if request["path"] == editor_tests.RUN]
    assert len(retry_run_requests) == 1
    assert "edits" not in retry_run_requests[0]["body"]
    child = backend.detail(retry_run_requests[0]["body"]["run_id"])
    assert retry_run_requests[0]["body"]["expected_version"] == child["plan"]["edit_version"]
    assert retry_run_requests[0]["body"]["expected_version"] != edited["edit_version"]


@pytest.mark.parametrize("lose_terminal", [False, True])
def test_real_final_model_failure_stays_visible_even_when_transport_ends(integrated_recovery, lose_terminal):
    page, backend, requests, mounted, options = integrated_recovery
    backend.model.answer_error = RuntimeError("PRIVATE_MODEL_SENTINEL https://provider.internal/error")
    options["lose_terminal"] = lose_terminal
    page.get_by_role("button", name="Approve and run the plan").click()
    expect(page.get_by_role("button", name="Retry from failed step").first).to_be_enabled()
    record = backend.detail(mounted.plan["run_id"])
    expect(page.get_by_text(record["failure"]["message"], exact=True).first).to_be_visible()
    state = recovery_tests.main_state(page)
    assert state["history"]["conv1"][0]["status"] == "failed"
    assert state["messages"][-1]["id"] == record["assistant_message_id"]
    assert state["messages"][-1]["content"]
    assert "PRIVATE_MODEL_SENTINEL" not in page.locator("body").inner_text()
    assert not any("/cancel/" in request["path"] or request["path"].endswith("/retry") for request in requests)


@pytest.mark.parametrize("agent_fails", [True, False])
def test_real_terminal_projection_keeps_browser_polling_until_message_saved(integrated_recovery, agent_fails):
    page, backend, requests, mounted, options = integrated_recovery
    backend.fail_b = agent_fails
    options.update(lose_terminal=True, hold_finalization=True)
    run_id = mounted.plan["run_id"]

    def capture_pending_publication(*_args):
        options["pending_detail"] = backend.detail(run_id)

    backend.messages.before_batch = capture_pending_publication
    page.clock.install()
    page.get_by_role("button", name="Approve and run the plan").click()
    expect(page.get_by_text("The server is saving the final response.", exact=False).first).to_be_visible()
    pending = options["pending_detail"]
    assert pending["status"] == ("failed" if agent_fails else "completed")
    assert pending["finalization_status"] == "pending"
    assert not pending["assistant_message_id"]
    assert pending["recovery"]["reason_code"] == "execution_live"
    assert run_id in recovery_tests.main_state(page)["inFlight"]
    expect(page.get_by_text("message was not saved", exact=False)).to_have_count(0)
    expect(page.get_by_role("button", name="Retry from failed step")).to_have_count(0)

    options["hold_finalization"] = False
    page.clock.fast_forward(5001)
    saved = backend.detail(run_id)
    assert saved["finalization_status"] == "saved"
    page.wait_for_function("""(id) => window.OrchHarness.stores.chat.useChatStore
        .getState().messages.some(message => message.id === id)""", arg=saved["assistant_message_id"])
    assert not recovery_tests.main_state(page)["inFlight"]
    if agent_fails:
        expect(page.get_by_role("button", name="Retry from failed step").first).to_be_enabled()
    assert len([request for request in requests if request["path"] == editor_tests.RUN]) == 1
    assert not any("/cancel/" in request["path"] or request["path"].endswith("/retry") for request in requests)


def test_lost_message_ack_preserves_saved_failure_and_retry(integrated_recovery):
    page, backend, requests, mounted, _options = integrated_recovery

    def lose_acknowledgement(*_args):
        backend.messages.after_batch = None
        raise AzureError("LOST_PUBLICATION_ACK_SENTINEL")

    backend.messages.after_batch = lose_acknowledgement
    page.get_by_role("button", name="Approve and run the plan").click()
    expect(page.get_by_role("button", name="Retry from failed step").first).to_be_enabled()
    saved = backend.detail(mounted.plan["run_id"])
    assert saved["finalization_status"] == "saved"
    assert saved["message_saved"] is True
    assert recovery_tests.main_state(page)["messages"][-1]["id"] == saved["assistant_message_id"]
    assert "LOST_PUBLICATION_ACK_SENTINEL" not in page.locator("body").inner_text()
    backend.fail_b = False
    page.get_by_role("button", name="Retry from failed step").first.click()
    page.get_by_role("dialog").get_by_role("button", name="Confirm retry").click()
    page.wait_for_function("""() => window.OrchHarness.stores.chat.useChatStore.getState().messages.some(
        message => message.metadata?.orchestration?.attempt_index === 2
            && message.metadata.orchestration.outcome === 'completed')""")
    assert backend.calls == ["a", "b", "b", "c"]
    assert len([request for request in requests if request["path"].endswith("/retry")]) == 1


@pytest.mark.parametrize("agent_fails", [True, False])
def test_message_storage_outage_keeps_safe_terminal_explanation_in_browser(integrated_recovery, agent_fails):
    page, backend, requests, _mounted, _options = integrated_recovery
    backend.fail_b = agent_fails
    def fail_message_save(step, _context, _kwargs):
        if step["step_id"] == "b":
            backend.messages.fail_writes = True
    backend.before_adapter = fail_message_save
    page.get_by_role("button", name="Approve and run the plan").click()
    expect(page.get_by_text("This explanation could not be saved to the conversation.", exact=False).first).to_be_visible()
    state = recovery_tests.main_state(page)
    assert state["history"]["conv1"][0]["status"] == "failed"
    assert state["messages"][-1]["content"]
    assert state["messages"][-1]["metadata"]["orchestration"]["failure"]["code"] == (
        "step_timeout" if agent_fails else "message_not_saved"
    )
    assert not state["inFlight"]
    assert not any("/cancel/" in request["path"] for request in requests)
