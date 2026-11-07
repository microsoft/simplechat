# test_chat_action_recovery_rendering.py
"""
Regression coverage for recovery diagnostics and the exception-derived link sink.
Version: 0.261.420
Implemented in: 0.261.420

Exercises production recovery and streaming code with a real browser DOM.
Reuses the Azure Playwright/DefaultAzureCredential connection or local fallback.
Every request is intercepted, so no model, provider, or external write runs.
"""

import json
from pathlib import Path
import sys

import pytest
from playwright.sync_api import expect

# Existing browser fixture modules import their siblings by name.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from action_recovery import ORIGIN, RecoveryFixture
from playwright_connection import connect_options  # noqa: F401


pytestmark = pytest.mark.ui


@pytest.fixture
def recovery(page):
    fixture = RecoveryFixture(page, "classic")
    yield fixture
    fixture.assert_clean()


@pytest.mark.parametrize(
    ("edit_url", "expected_url"),
    [
        ("/v2/workspace/actions/action-1", "/v2/workspace/actions/action-1"),
        ("/v2/admin/actions/action-1", "/v2/admin/actions/action-1"),
        ("/v2/groups/group-1/actions/action-1", "/v2/groups/group-1/actions/action-1"),
        ("/v2/workspace/actions/quoted\" & <id>", "/v2/workspace/actions/quoted%22%20%26%20%3Cid%3E"),
        ("/v2/groups/space%20group/actions/space%20id%2F%25%22%23%3F",
         "/v2/groups/space%20group/actions/space%20id%2F%25%22%23%3F"),
        ("/v2/groups/owner%27s%20group/actions/action%28id%29%21%2A",
         "/v2/groups/owner%27s%20group/actions/action%28id%29%21%2A"),
    ],
    ids=["personal", "global", "group", "quoted-personal", "encoded-group", "encoded-symbols"],
)
def test_editor_links_keep_the_authorized_route_and_encoded_identifiers(recovery, edit_url, expected_url):
    recovery.incident["actions"][0]["edit_url"] = edit_url
    recovery.open()
    page = recovery.page
    page.get_by_role("button", name="Send fixture", exact=True).click()
    dialog = page.get_by_role("dialog", name="This agent has unavailable actions")
    expect(dialog).to_be_visible()
    link = dialog.get_by_role("link", name="Open action in a new tab")
    expect(link).to_have_attribute("href", expected_url)
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("rel", "noopener noreferrer")
    dialog.get_by_role("button", name="Cancel / choose another agent", exact=True).click()
    expect(dialog).to_be_hidden()
    notice = page.get_by_role("region", name="Unavailable actions")
    expect(notice.get_by_role("link")).to_have_attribute("href", expected_url)
    expect(notice.get_by_role("button", name="Recheck and send preserved request")).to_be_visible()
    sends = recovery.sends
    assert sends == []


@pytest.mark.parametrize(
    "edit_url",
    [
        "javascript:window.__injected=true",
        "https://untrusted.invalid/action",
        "/v2/workspace/actions/..",
        "/v2/groups/%2e%2e/actions/action-1",
        "/v2/workspace/actions/bad%ZZ",
        "/v2/admin/actions/action-1\n",
    ],
    ids=["script-url", "external-host", "dot-action", "dot-group", "invalid-percent", "raw-newline"],
)
def test_invalid_editor_urls_do_not_remove_diagnostics_or_recovery_controls(recovery, edit_url):
    recovery.incident["actions"][0]["edit_url"] = edit_url
    recovery.open()
    page = recovery.page
    page.get_by_role("button", name="Send fixture", exact=True).click()
    dialog = page.get_by_role("dialog", name="This agent has unavailable actions")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("link")).to_have_count(0)
    expect(dialog.get_by_text("This action could not be loaded.", exact=True)).to_be_visible()
    expect(dialog.get_by_text(
        "Contact the action's owner or administrator to review its configuration.", exact=True
    )).to_be_visible()
    expect(dialog.get_by_role("button", name="Notify owner/admin")).to_be_visible()
    expect(dialog.get_by_role("button", name="Recheck", exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="Continue without these actions", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Cancel / choose another agent", exact=True).click()
    sends = recovery.sends
    assert sends == []


def test_exception_recovery_payload_stays_literal_and_reports_and_rechecks_still_work(recovery):
    payload = '<img src=x onerror="window.__injected=true"><svg onload="window.__injected=true">&\''
    recovery.incident["agent_name"] = "Agent: " + payload
    action = recovery.incident["actions"][0]
    action.update({
        "name": "Action: " + payload,
        "scope": "Scope: " + payload,
        "reason": "Diagnostic: " + payload,
        "capabilities": ["Operation: " + payload],
        "edit_url": '/v2/workspace/actions/quoted" & <id>',
    })
    recovery.health = "ready"
    recovery.open()
    page = recovery.page
    preserved_message = "Unsent: " + payload
    page.evaluate("message => { window.__request.message = message; }", preserved_message)
    stream_bodies = []

    def respond_to_stream(route):
        stream_bodies.append(json.loads(route.request.post_data))
        if len(stream_bodies) == 1:
            # Production streaming catches this Error, then forwards its payload to recovery.
            recovery._json(route, {**recovery.incident, "error": "PRIVATE-provider " + payload}, 409)
        else:
            route.fulfill(
                content_type="text/event-stream",
                body='data: {"done":true,"full_content":"Synthetic response","message_id":"answer"}\n\n',
            )

    page.route(f"{ORIGIN}/api/chat/stream", respond_to_stream)
    page.get_by_role("button", name="Send fixture", exact=True).click()
    notice = page.get_by_role("region", name="Unavailable actions")
    expect(notice).to_be_visible()
    expect(notice.get_by_role("heading", level=3)).to_have_text(action["name"])
    expect(notice.get_by_text(action["reason"], exact=True)).to_be_visible()
    expect(notice.get_by_text(action["scope"] + " action", exact=True)).to_be_visible()
    expect(notice.get_by_text("Unavailable: " + action["capabilities"][0], exact=True)).to_be_visible()
    expect(notice.get_by_text(
        recovery.incident["agent_name"] + ": no model or action has run.", exact=True
    )).to_be_visible()
    notice.get_by_text("Preserved unsent message", exact=True).click()
    expect(notice.get_by_text(preserved_message, exact=True)).to_be_visible()
    expect(notice.get_by_role("link")).to_have_attribute(
        "href", "/v2/workspace/actions/quoted%22%20%26%20%3Cid%3E"
    )
    dangerous_nodes = notice.locator("img, svg, script, iframe, [onerror], [onload], [onclick]").count()
    injected = page.evaluate("window.__injected === undefined")
    rendered_text = page.locator("body").inner_text()
    assert dangerous_nodes == 0
    assert injected
    assert "PRIVATE-provider" not in rendered_text
    assert len(stream_bodies) == 1
    notice.get_by_role("button", name="Notify owner/admin").click()
    expect(notice.get_by_role("button", name="Reported", exact=True)).to_be_disabled()
    reports = [item for item in recovery.requests if item["path"].endswith("/report")]
    assert len(reports) == 1
    assert reports[0]["body"] == {"action_key": action["key"]}
    notice.get_by_role("button", name="Recheck and send preserved request").click()
    recovery.wait_complete()
    assert len(stream_bodies) == 2
    assert stream_bodies[1]["message"] == preserved_message
    assert "action_recovery" not in stream_bodies[1]
