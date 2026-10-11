# test_v2_pending_review_editor.py
"""
Owner-only pending email/calendar editor, durable history and rendered preview.
Version: 0.261.325
Implemented in: 0.261.325

Runs the real React components with a mocked HTTP boundary. No Graph send or
event creation occurs. Uses the shared local/Azure Playwright connection.
"""

from pathlib import Path
from functools import lru_cache
import subprocess

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.playwright_connection import connect_options  # noqa: F401
from ui_tests.fixtures.orchestration import harness_build
from ui_tests.test_v2_m365_pending_action_cards import (
    _collect_page_errors,
    _open_chat,
    _require_bundle,
    pending_action,
    thread,
)

pytestmark = pytest.mark.ui
ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def _review_styles():
    """Compile the actual incumbent theme/utilities, not a pretend mobile layout."""
    script = r"""
        const fs = require('node:fs');
        const path = require('node:path');
        const { compile } = require('@tailwindcss/node');
        const { Scanner } = require('@tailwindcss/oxide');
        (async () => {
            const root = path.resolve('src');
            const theme = path.join(root, 'styles', 'theme.css');
            const scanner = new Scanner({ sources: [{ base: root, pattern: '**/*.{ts,tsx,css}', negated: false }] });
            const compiler = await compile(fs.readFileSync(theme, 'utf8'), {
                base: path.dirname(theme), onDependency() {},
            });
            process.stdout.write(compiler.build(scanner.scan()));
        })().catch(error => { console.error(error); process.exit(1); });
    """
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT / "application" / "v2_ui",
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise AssertionError(f"Unable to compile incumbent review styles: {result.stderr}")
    return result.stdout

REVIEW_BACKEND = r"""({ action, draft }) => {
    const original = window.fetch;
    const json = (body, status = 200) => new Response(JSON.stringify(body), {
        status, headers: { 'Content-Type': 'application/json' },
    });
    window.reviewDraft = draft;
    window.reviewVersion = 'v1';
    window.reviewHistory = [];
    window.reviewRequests = [];
    window.reviewConflict = false;
    const response = (cursor='') => {
        const all = [...window.reviewHistory].reverse();
        const offset = cursor ? all.findIndex(item => item.id === cursor)+1 : 0;
        const items = all.slice(offset, offset+20);
        return ({ success: true, pending_action: window.actionsById[action.id],
        fields: window.reviewDraft, expected_version: window.reviewVersion,
        timezone_aliases: window.reviewTimezoneAliases ?? {},
        history: { items, next_cursor: all.length > offset+20 ? items.at(-1).id : '' } });
    };
    window.fetch = async (url, init = {}) => {
        const target = new URL(String(url), window.location.origin);
        const path = target.pathname;
        if (!/\/(review|assist|history)$/.test(path)) return original(url, init);
        const method = String(init.method || 'GET').toUpperCase();
        const body = init.body ? JSON.parse(init.body) : null;
        window.reviewRequests.push({ method, path, body });
        if (path.endsWith('/assist')) {
            const before = body.fields;
            const after = { ...before, subject: 'AI revised subject', body: 'AI revised body' };
            const reply = 'Improved the wording. Review before saving.';
            window.reviewHistory.push({ id: 'ai-1', kind: 'assist', origin: 'ai',
                submission_id: body.submission_id, instruction: body.instruction,
                reply, outcome: 'changed', from_fields: before, candidate_fields: after,
                expected_version:body.expected_version, created_at:new Date().toISOString(), saved:false, applied:false });
            window.reviewVersion = 'assist-v2';
            window.actionsById[action.id] = { ...window.actionsById[action.id], version: window.reviewVersion };
            if (window.deferReviewAssist) await new Promise(resolve => { window.releaseReviewAssist = resolve; });
            return json({ submission_id: body.submission_id, outcome: 'changed', reply,
                candidate: { values: Object.fromEntries(Object.entries(after).map(([key,value]) => ['/'+key,value])), new_items: [] },
                changes: [], warnings: [], ...response(), assist_turn_id: 'ai-1' });
        }
        if (path.endsWith('/history')) return json(response(target.searchParams.get('cursor') || ''));
        if (method === 'PATCH') {
            if (window.reviewConflict || body.expected_version !== window.reviewVersion)
                return json({ error: 'version_conflict', message: 'This action changed. Reload before saving.' }, 409);
            window.reviewHistory.push({ id: 'revision-'+window.reviewHistory.length,
                kind: 'revision', origin: body.origin, from_fields: window.reviewDraft,
                fields:body.fields, assist_turn_id:body.assist_turn_id, created_at:new Date().toISOString(), saved:true, applied:true });
            if (body.assist_turn_id) Object.assign(window.reviewHistory.find(item => item.id === body.assist_turn_id), {saved:true, applied:true});
            window.reviewDraft = body.fields;
            window.reviewVersion = 'v'+(window.reviewHistory.length+1);
            window.actionsById[action.id] = { ...window.actionsById[action.id],
                subject: body.fields.subject, version: window.reviewVersion,
                summary: { ...window.actionsById[action.id].summary,
                    ...body.fields, body_preview: body.fields.body } };
        }
        return json(response());
    };
}"""


def _open_editor(page, origin, calendar=False):
    action = pending_action(
        "act-review", action_mode="manual", can_edit=True,
        graph_resource_type="calendar" if calendar else "mail",
    )
    draft = {
        "subject": "Quarterly numbers", "body": "Hello Ann", "content_type": "Text",
        "to_recipients": ["ann@example.com"], "cc_recipients": [], "bcc_recipients": [],
    }
    if calendar:
        draft = {
            "subject": "Planning meeting", "body": "Agenda", "content_type": "Text",
            "attendee_recipients": ["ann@example.com"],
            "start_datetime": "2026-10-15T10:00:00.0000000",
            "end_datetime": "2026-10-15T11:00:00.0000000",
            "timezone": "America/New_York", "location": "Room 1", "teams_meeting_requested": True,
        }
    root = _open_chat(page, origin, messages=thread(action), listed=[action], by_id=[action])
    page.add_style_tag(content=_review_styles())
    page.evaluate("""() => {
        const bootstrap = window.OrchHarness.stores.bootstrap.useBootstrapStore;
        bootstrap.setState(state => ({ data: { ...state.data, features: { enable_action_ai_assistant: true } } }));
    }""")
    page.evaluate(REVIEW_BACKEND, {"action": action, "draft": draft})
    edit = root.get_by_test_id("v2-pending-action-edit")
    expect(edit).to_be_enabled()
    edit.click()
    dialog = page.get_by_role("dialog", name="Edit calendar invitation" if calendar else "Edit email", exact=True)
    expect(dialog).to_be_visible()
    expect(dialog.get_by_label("Title" if calendar else "Subject", exact=True)).to_have_value(draft["subject"])
    return root, dialog, edit


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}])
def test_direct_and_ai_edits_save_and_reopen_without_sending(page, viewport):
    _require_bundle()
    page.set_viewport_size(viewport)
    errors = _collect_page_errors(page)
    with harness_build.start_static_server() as origin:
        root, dialog, edit = _open_editor(page, origin)
        dialog.get_by_label("Subject", exact=True).fill("Direct revised subject")
        dialog.get_by_label("To", exact=True).fill("new@example.com")
        dialog.get_by_role("button", name="Save changes", exact=True).click()
        expect(dialog.get_by_role("status")).to_have_text("Saved draft")
        expect(root.get_by_text("Direct revised subject", exact=True)).to_be_visible()
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(edit).to_be_focused()
        edit.click()
        expect(dialog.get_by_label("Subject", exact=True)).to_have_value("Direct revised subject")
        expect(dialog.get_by_label("To", exact=True)).to_have_value("new@example.com")
        if viewport["width"] < 1024:
            dialog.get_by_role("button", name="Ask AI & history", exact=True).click()
        expect(dialog.get_by_text("Saved direct edits.", exact=True)).to_be_visible()
        dialog.get_by_label("Message Ask AI", exact=True).fill("Make this clearer")
        dialog.get_by_role("button", name="Send to Ask AI", exact=True).click()
        expect(dialog.get_by_text("Improved the wording. Review before saving.", exact=True)).to_be_visible()
        if viewport["width"] < 1024:
            dialog.get_by_role("button", name="Draft", exact=True).click()
        expect(dialog.get_by_label("Subject", exact=True)).to_have_value("AI revised subject")
        dialog.get_by_role("button", name="Save changes", exact=True).click()
        expect(dialog.get_by_role("status")).to_have_text("Saved draft")
        page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()
        expect(edit).to_be_focused()
        edit.click()
        expect(dialog.get_by_label("Subject", exact=True)).to_have_value("AI revised subject")
        if viewport["width"] < 1024:
            dialog.get_by_role("button", name="Ask AI & history", exact=True).click()
        expect(dialog.get_by_text("Improved the wording. Review before saving.", exact=True)).to_be_visible()
        requests = page.evaluate("() => window.requests.concat(window.reviewRequests)")
        assert not any(item["path"].endswith(("/approve", "/send-now", "/cancel")) for item in requests)
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
        assert errors == []


def test_cancel_after_ai_refreshes_saved_material_and_version_before_explicit_send(page):
    _require_bundle()
    with harness_build.start_static_server() as origin:
        root, dialog, _ = _open_editor(page, origin)
        expect(root.get_by_test_id("v2-pending-action-send")).to_be_disabled()
        dialog.get_by_label("Message Ask AI", exact=True).fill("Suggest clearer wording")
        dialog.get_by_role("button", name="Send to Ask AI", exact=True).click()
        expect(dialog.get_by_label("Subject", exact=True)).to_have_value("AI revised subject")
        page.evaluate("""() => {
            const saved = window.actionsById['act-review'];
            window.actionsById['act-review'] = { ...saved, version:'outlook-synchronized-v3',
                subject:'Synchronized Outlook subject',
                summary:{ ...saved.summary, subject:'Synchronized Outlook subject' } };
            window.reviewVersion = 'outlook-synchronized-v3';
        }""")
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        page.get_by_role("dialog", name="Discard unsaved changes?", exact=True).get_by_role(
            "button", name="Discard changes", exact=True,
        ).click()
        expect(dialog).not_to_be_visible()
        expect(root.get_by_text("Synchronized Outlook subject", exact=True)).to_be_visible()
        expect(root.get_by_test_id("v2-pending-action-send")).to_be_enabled()
        requests = page.evaluate("() => window.requests.concat(window.reviewRequests)")
        assert not any(item["path"].endswith(("/approve", "/send-now", "/cancel")) for item in requests)
        assert not any(item["method"] == "PATCH" for item in page.evaluate("() => window.reviewRequests"))
        root.get_by_test_id("v2-pending-action-send").click()
        page.wait_for_function("() => window.requests.some(item => /\\/(approve|send-now)$/.test(item.path))")
        sent = page.evaluate("() => window.requests.filter(item => /\\/(approve|send-now)$/.test(item.path))")
        assert len(sent) == 1
        assert sent[0]["body"]["expected_version"] == "outlook-synchronized-v3"


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}])
@pytest.mark.parametrize("newer_body", [False, True])
def test_reopened_suggestion_shows_changes_and_applies_locally_without_overwriting_newer_edits(page, viewport, newer_body):
    _require_bundle()
    page.set_viewport_size(viewport)
    with harness_build.start_static_server() as origin:
        root, dialog, edit = _open_editor(page, origin)
        mobile = viewport["width"] < 1024
        if mobile:
            dialog.get_by_role("button", name="Ask AI & history", exact=True).click()
        dialog.get_by_label("Message Ask AI", exact=True).fill("Improve the draft")
        dialog.get_by_role("button", name="Send to Ask AI", exact=True).click()
        expect(dialog.get_by_text("Improved the wording. Review before saving.", exact=True)).to_be_visible()
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        page.get_by_role("dialog", name="Discard unsaved changes?", exact=True).get_by_role(
            "button", name="Discard changes", exact=True,
        ).click()
        expect(edit).to_be_enabled()
        edit.click()
        expect(dialog.get_by_label("Subject", exact=True)).to_have_value("Quarterly numbers")
        if newer_body:
            dialog.get_by_label("Body", exact=True).fill("Keep this newer body")
        if mobile:
            dialog.get_by_role("button", name="Ask AI & history", exact=True).click()
        history = dialog.get_by_role("log", name="Draft review history", exact=True)
        changes = history.get_by_role("list", name="Changed fields", exact=True)
        expect(changes).to_contain_text("Subject")
        expect(changes).to_contain_text("Body")
        apply = history.get_by_role("button", name="Apply suggestion", exact=True)
        apply.focus()
        page.keyboard.press("Enter")
        expect(dialog.get_by_label("Subject", exact=True)).to_have_value("AI revised subject")
        expect(dialog.get_by_label("Body", exact=True)).to_have_value("Keep this newer body" if newer_body else "AI revised body")
        if newer_body:
            expect(dialog.get_by_role("alert")).to_contain_text("Your newer edits have been kept")
        requests = page.evaluate("() => window.requests.concat(window.reviewRequests)")
        assert not any(item["path"].endswith(("/approve", "/send-now", "/cancel")) for item in requests)
        assert not page.evaluate("() => window.reviewRequests.some(item => item.method === 'PATCH')")
        expect(root.get_by_test_id("v2-pending-action-send")).to_be_disabled()
        dialog.get_by_role("button", name="Save changes", exact=True).click()
        expect(dialog.get_by_role("status")).to_have_text("Saved draft")
        patch = page.evaluate("() => window.reviewRequests.filter(item => item.method === 'PATCH').at(-1).body")
        assert patch["origin"] == "ai"
        assert patch["assist_turn_id"] == "ai-1"
        assert patch["fields"]["body"] == ("Keep this newer body" if newer_body else "AI revised body")


def test_calendar_edit_and_stale_save_keeps_working_copy(page):
    _require_bundle()
    with harness_build.start_static_server() as origin:
        _, dialog, _ = _open_editor(page, origin, calendar=True)
        expect(dialog.get_by_label("Teams meeting", exact=True)).to_be_checked()
        expect(dialog.get_by_label("Start", exact=True)).not_to_have_value("")
        expect(dialog.get_by_label("End", exact=True)).not_to_have_value("")
        dialog.get_by_label("Time zone", exact=True).fill("Europe/London")
        dialog.get_by_label("Attendees", exact=True).fill("other@example.com")
        page.evaluate("() => window.reviewConflict = true")
        dialog.get_by_role("button", name="Save changes", exact=True).click()
        expect(dialog.get_by_role("alert")).to_contain_text("Reload before saving")
        expect(dialog.get_by_label("Time zone", exact=True)).to_have_value("Europe/London")
        assert page.evaluate("() => window.reviewDraft.timezone") == "America/New_York"
        assert page.evaluate("() => window.reviewRequests.at(-1).body.fields.start_datetime") == "2026-10-15T10:00:00.0000000"


@pytest.mark.parametrize("offset", [False, True])
def test_saved_calendar_instants_display_selected_wall_time_without_rewriting_original_fields(page, offset):
    _require_bundle()
    with harness_build.start_static_server() as origin:
        _, dialog, edit = _open_editor(page, origin, calendar=True)
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        expect(edit).to_be_enabled()
        start = "2026-10-15T16:00:00.1234567+02:00" if offset else "2026-10-15T14:00:00Z"
        end = "2026-10-15T17:00:00.1234567+02:00" if offset else "2026-10-15T15:00:00Z"
        page.evaluate("""({start,end,zone}) => {
            window.reviewDraft = { ...window.reviewDraft, start_datetime:start, end_datetime:end, timezone:zone };
            window.reviewVersion = 'calendar-instant-v2';
            window.actionsById['act-review'] = { ...window.actionsById['act-review'], version:window.reviewVersion };
            window.reviewTimezoneAliases = { 'Eastern Standard Time':'America/New_York' };
        }""", {"start": start, "end": end, "zone": "Eastern Standard Time" if offset else "America/New_York"})
        edit.click()
        expect(dialog.get_by_label("Start", exact=True)).to_have_attribute("type", "datetime-local")
        expect(dialog.get_by_label("Start", exact=True)).to_have_value("2026-10-15T10:00:00.123" if offset else "2026-10-15T10:00")
        expect(dialog.get_by_label("End", exact=True)).to_have_value("2026-10-15T11:00:00.123" if offset else "2026-10-15T11:00")
        valid_start = dialog.get_by_label("Start", exact=True).evaluate("element => element.validity.valid")
        assert valid_start
        dialog.get_by_label("Time zone", exact=True).fill("Invalid/Zone")
        expect(dialog.get_by_label("Start", exact=True)).to_have_attribute("type", "text")
        expect(dialog.get_by_label("Start", exact=True)).to_have_value(start)
        expect(dialog.get_by_text(
            "This timestamp cannot be displayed in the selected time zone. The original ISO timestamp is shown unchanged.",
            exact=True,
        )).to_have_count(2)
        dialog.get_by_label("Time zone", exact=True).fill("Europe/London")
        expect(dialog.get_by_label("Start", exact=True)).to_have_value("2026-10-15T15:00:00.123" if offset else "2026-10-15T15:00")
        dialog.get_by_label("Title", exact=True).fill("Reviewed invitation")
        dialog.get_by_role("button", name="Save changes", exact=True).click()
        expect(dialog.get_by_role("status")).to_have_text("Saved draft")
        patch = page.evaluate("() => window.reviewRequests.filter(item => item.method === 'PATCH').at(-1).body")
        assert patch["fields"]["start_datetime"] == start
        assert patch["fields"]["end_datetime"] == end
        assert patch["fields"]["timezone"] == "Europe/London"
        assert not page.evaluate("() => window.requests.some(item => /\\/(approve|send-now|cancel)$/.test(item.path))")


def test_rendered_body_is_visible_and_safe_and_overflow_is_keyboard_accessible(page):
    _require_bundle()
    with harness_build.start_static_server() as origin:
        page.route("**/vendor/dompurify-3.4.14/purify.min.js", lambda route: route.fulfill(
            path=str(ROOT / "application" / "v2_ui" / "public" / "vendor" / "dompurify-3.4.14" / "purify.min.js"),
            content_type="text/javascript",
        ))
        action = pending_action("act-preview", summary={
            "subject": "Quarterly numbers", "to_recipients": ["ann@example.com"], "content_type": "html",
            "body_preview": "<p>First line</p>" * 8 + '<a href="https://example.com/report">Report</a>'
                + '<img src=x onerror="window.executed=true"><script>window.executed=true</script>'
                + '<a href="javascript:window.executed=true">Unsafe</a>',
        })
        root = _open_chat(page, origin, messages=thread(action), listed=[action], by_id=[action])
        page.add_style_tag(content=_review_styles())
        body = root.get_by_test_id("v2-pending-action-body")
        expect(body.locator("p")).to_have_count(8)
        expect(body).to_contain_text("First line")
        expect(body.locator("script, img, [onerror]")).to_have_count(0)
        expect(body.get_by_role("link", name="Report", exact=True)).to_have_attribute("href", "https://example.com/report")
        expect(body.locator('a[href^="javascript:"]')).to_have_count(0)
        more = root.get_by_role("button", name="Show More", exact=True)
        expect(more).to_be_visible()
        more.focus()
        page.keyboard.press("Enter")
        expect(root.get_by_role("button", name="Show Less", exact=True)).to_have_attribute("aria-expanded", "true")
        assert page.evaluate("() => window.executed") is None


@pytest.mark.parametrize("failure", ["network", "missing-global"])
def test_html_preview_loading_failure_and_local_retry_never_expose_source(page, failure):
    _require_bundle()
    with harness_build.start_static_server() as origin:
        attempts = []
        page.route("**/vendor/dompurify-3.4.14/purify.min.js", lambda route: attempts.append(route))
        action = pending_action("act-preview-retry", summary={
            "subject": "Quarterly numbers", "to_recipients": ["ann@example.com"], "content_type": "HTML",
            "body_preview": '<p>Private preview text</p><img src=x onerror="window.executed=true">',
        })
        root = _open_chat(page, origin, messages=thread(action), listed=[action], by_id=[action])
        page.add_style_tag(content=_review_styles())
        expect(root.get_by_role("status").filter(has_text="Preparing formatted preview")).to_be_visible()
        expect(root.get_by_test_id("v2-pending-action-body")).to_have_count(0)
        expect(root).not_to_contain_text("<p>Private preview text</p>")
        assert len(attempts) == 1
        if failure == "network":
            attempts[0].abort()
        else:
            attempts[0].fulfill(body="// Local asset did not register its sanitizer.", content_type="text/javascript")
        expect(root.get_by_role("alert")).to_contain_text("The body is hidden")
        expect(root.get_by_test_id("v2-pending-action-body")).to_have_count(0)
        expect(root).not_to_contain_text("<p>Private preview text</p>")
        root.get_by_role("button", name="Retry formatted preview", exact=True).click()
        expect(root.get_by_role("status").filter(has_text="Preparing formatted preview")).to_be_visible()
        assert len(attempts) == 2
        attempts[1].fulfill(
            path=str(ROOT / "application" / "v2_ui" / "public" / "vendor" / "dompurify-3.4.14" / "purify.min.js"),
            content_type="text/javascript",
        )
        body = root.get_by_test_id("v2-pending-action-body")
        expect(body).to_contain_text("Private preview text")
        expect(body.locator("img, [onerror]")).to_have_count(0)
        expect(root.get_by_role("alert")).to_have_count(0)
        assert page.evaluate("() => window.executed") is None


@pytest.mark.parametrize("link_status", ["available", "unavailable"])
def test_accepted_message_link_polling_never_resends_or_shows_stale_draft(page, link_status):
    _require_bundle()
    page.clock.install()
    with harness_build.start_static_server() as origin:
        action = pending_action("act-link", status="sent", graph_resource_type="mail",
            link_pending=True, link_status="pending", web_link_kind="draft",
            web_link="https://outlook.office.com/mail/stale-draft", can_send_now=False, can_approve=False, can_cancel=False)
        root = _open_chat(page, origin, messages=thread(action), listed=[action], by_id=[action])
        page.add_style_tag(content=_review_styles())
        expect(root.get_by_text("Accepted for sending", exact=True)).to_be_visible()
        expect(root.get_by_text(
            "Checking for the sent-message link. Microsoft 365 accepted the send; these read-only checks never send it again.",
            exact=True,
        )).to_be_visible()
        expect(root.get_by_role("link", name="Open draft in Outlook", exact=True)).to_have_count(0)
        expect(root.get_by_role("link", name="Open sent message in Outlook", exact=True)).to_have_count(0)
        page.evaluate("""status => {
            window.actionsById['act-link'] = { ...window.actionsById['act-link'],
                version:'link-resolved-v2', link_pending:false, link_status:status, web_link_kind:'sent',
                web_link:status === 'available' ? 'https://outlook.office.com/mail/sent-message' : 'https://outlook.office.com/mail/stale-draft' };
        }""", link_status)
        page.clock.fast_forward(16000)
        expect(root.get_by_text("Accepted for sending", exact=True)).to_be_visible()
        if link_status == "available":
            expect(root.get_by_role("link", name="Open sent message in Outlook", exact=True)).to_have_attribute(
                "href", "https://outlook.office.com/mail/sent-message",
            )
        else:
            expect(root.get_by_text(
                "Sent-message link unavailable. Check Outlook Sent Items; Microsoft 365 acceptance has not changed.",
                exact=True,
            )).to_be_visible()
            expect(root.get_by_role("link", name="Open sent message in Outlook", exact=True)).to_have_count(0)
        expect(root.get_by_role("link", name="Open draft in Outlook", exact=True)).to_have_count(0)
        expect(root.get_by_test_id("v2-pending-action-send")).to_have_count(0)
        requests = page.evaluate("() => window.requests")
        assert any(item["method"] == "GET" and item["path"] == "/api/msgraph/pending-actions/act-link" for item in requests)
        assert not any(item["path"].endswith(("/approve", "/send-now", "/cancel")) for item in requests)


def test_shared_and_delayed_actions_have_no_edit_control(page):
    _require_bundle()
    with harness_build.start_static_server() as origin:
        shared = pending_action("act-shared", can_edit=True, action_mode="manual", viewer_is_owner=False)
        delayed = pending_action("act-delayed", can_edit=True, action_mode="delayed")
        root = _open_chat(page, origin, messages=thread(shared, delayed), listed=[shared, delayed], by_id=[shared, delayed])
        page.add_style_tag(content=_review_styles())
        expect(root.get_by_test_id("v2-pending-action-edit")).to_have_count(0)


def test_history_paging_and_undo_preserves_later_direct_edits(page):
    _require_bundle()
    with harness_build.start_static_server() as origin:
        _, dialog, edit = _open_editor(page, origin)
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        page.evaluate("""() => {
            const draft = window.reviewDraft;
            window.reviewHistory = Array.from({length: 25}, (_, index) => ({
                id: 'history-'+index, kind: 'revision', origin: 'direct', saved: true,
                reply: 'History marker '+index, from_fields: { ...draft, subject: 'before-'+index },
                fields: { ...draft, subject: 'subject-'+index },
            }));
            window.reviewDraft = { ...draft, subject: 'subject-24' };
        }""")
        edit.click()
        expect(dialog.get_by_text("History marker 24", exact=True)).to_be_visible()
        expect(dialog.get_by_text("History marker 0", exact=True)).to_have_count(0)
        dialog.get_by_role("button", name="Load older history", exact=True).click()
        expect(dialog.get_by_text("History marker 0", exact=True)).to_have_count(1)
        expect(dialog.get_by_text("History marker 24", exact=True)).to_have_count(1)
        dialog.get_by_label("Body", exact=True).fill("Later direct body")
        latest = dialog.get_by_text("History marker 24", exact=True).locator("..")
        latest.get_by_role("button", name="Undo this change", exact=True).click()
        expect(dialog.get_by_label("Subject", exact=True)).to_have_value("before-24")
        expect(dialog.get_by_label("Body", exact=True)).to_have_value("Later direct body")
        dialog.get_by_role("button", name="Save changes", exact=True).click()
        expect(dialog.get_by_role("status")).to_have_text("Saved draft")
        assert page.evaluate("() => window.reviewDraft.body") == "Later direct body"


def test_late_ai_response_cannot_overwrite_a_newer_action_revision(page):
    _require_bundle()
    with harness_build.start_static_server() as origin:
        _, dialog, _ = _open_editor(page, origin)
        page.evaluate("() => window.deferReviewAssist = true")
        dialog.get_by_label("Message Ask AI", exact=True).fill("Improve this")
        dialog.get_by_role("button", name="Send to Ask AI", exact=True).click()
        page.wait_for_function("() => typeof window.releaseReviewAssist === 'function'")
        page.evaluate("""() => {
            const next = { ...window.actionsById['act-review'], version: 'external-v3' };
            window.actionsById['act-review'] = next;
            window.reviewVersion = 'external-v3';
            window.OrchHarness.stores.pendingActions.chatPendingActionsStore.getState().remember(next, {authoritative:true});
            window.releaseReviewAssist();
        }""")
        expect(dialog.get_by_role("alert")).to_contain_text("Nothing was applied because the draft changed")
        expect(dialog.get_by_label("Subject", exact=True)).to_have_value("Quarterly numbers")
        assert not page.evaluate("() => window.reviewRequests.some(item => item.method === 'PATCH')")


def test_recipient_typing_and_unsaved_discard_are_not_lost_to_separator_normalization(page):
    _require_bundle()
    with harness_build.start_static_server() as origin:
        _, dialog, edit = _open_editor(page, origin)
        recipients = dialog.get_by_label("To", exact=True)
        recipients.press("End")
        recipients.press_sequentially("; other@example.com")
        expect(recipients).to_have_value("ann@example.com; other@example.com")
        page.keyboard.press("Escape")
        discard = page.get_by_role("dialog", name="Discard unsaved changes?", exact=True)
        expect(discard).to_be_visible()
        discard.get_by_role("button", name="Discard changes", exact=True).click()
        expect(dialog).not_to_be_visible()
        edit.click()
        expect(dialog.get_by_label("To", exact=True)).to_have_value("ann@example.com")


def test_existing_assist_configuration_leaves_direct_edit_and_history_available(page):
    _require_bundle()
    with harness_build.start_static_server() as origin:
        _, dialog, _ = _open_editor(page, origin)
        page.evaluate("""() => {
            const bootstrap = window.OrchHarness.stores.bootstrap.useBootstrapStore;
            bootstrap.setState(state => ({ data: { ...state.data, features: { enable_action_ai_assistant: false } } }));
        }""")
        expect(dialog.get_by_label("Message Ask AI", exact=True)).to_have_count(0)
        expect(dialog.get_by_label("Subject", exact=True)).to_be_enabled()
        expect(dialog.get_by_text("Ask AI is unavailable. You can still edit directly and review saved history.", exact=True)).to_be_visible()


def test_expired_editing_claim_can_reopen_for_authorized_reconciliation(page):
    _require_bundle()
    with harness_build.start_static_server() as origin:
        root, dialog, _ = _open_editor(page, origin)
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        page.evaluate("""() => {
            const expired = { ...window.actionsById['act-review'], status:'editing',
                can_edit:true, can_send_now:false, can_approve:false, version:'expired-claim-v2' };
            window.OrchHarness.stores.pendingActions.chatPendingActionsStore.getState().remember(expired, {authoritative:true});
            window.actionsById['act-review'] = { ...expired, status:'review_required', version:'reconciled-v3' };
            window.reviewVersion = 'reconciled-v3';
        }""")
        edit = root.get_by_test_id("v2-pending-action-edit")
        expect(edit).to_be_enabled()
        edit.click()
        expect(dialog.get_by_label("Subject", exact=True)).to_have_value("Quarterly numbers")
        expect(dialog.get_by_label("Subject", exact=True)).to_be_enabled()
        assert page.evaluate("() => window.reviewRequests.at(-1).method") == "GET"
        requests = page.evaluate("() => window.requests.concat(window.reviewRequests)")
        assert not any(item["path"].endswith(("/approve", "/send-now", "/cancel")) for item in requests)


@pytest.mark.parametrize("material_changed", [False, True])
def test_history_paging_adopts_only_unchanged_material_revision(page, material_changed):
    _require_bundle()
    with harness_build.start_static_server() as origin:
        _, dialog, edit = _open_editor(page, origin)
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        expect(edit).to_be_enabled()
        page.evaluate("""() => {
            window.reviewHistory = Array.from({length:25}, (_, index) => ({
                id:'turn-'+index, kind:'assist', origin:'ai', reply:'Saved turn '+index,
                candidate_fields:window.reviewDraft, saved:false, applied:false,
            }));
        }""")
        edit.click()
        expect(dialog.get_by_label("Body", exact=True)).to_have_value("Hello Ann")
        dialog.get_by_label("Body", exact=True).fill("Local working body")
        page.evaluate("""changed => {
            window.reviewVersion = 'history-v2';
            window.actionsById['act-review'] = { ...window.actionsById['act-review'], version:'history-v2' };
            if (changed) window.reviewDraft = { ...window.reviewDraft, body:'Externally changed body' };
        }""", material_changed)
        dialog.get_by_role("button", name="Load older history", exact=True).click()
        expect(dialog.get_by_text("Saved turn 0", exact=True)).to_have_count(1)
        expect(dialog.get_by_label("Body", exact=True)).to_have_value("Local working body")
        if material_changed:
            expect(dialog.get_by_role("alert")).to_contain_text("Reload the saved draft before saving")
            expect(dialog.get_by_label("Body", exact=True)).to_be_disabled()
            expect(dialog.get_by_role("button", name="Save changes", exact=True)).to_be_disabled()
            assert not page.evaluate("() => window.reviewRequests.some(item => item.method === 'PATCH')")
        else:
            expect(dialog.get_by_label("Body", exact=True)).to_be_enabled()
            dialog.get_by_role("button", name="Save changes", exact=True).click()
            expect(dialog.get_by_role("status")).to_have_text("Saved draft")
            patches = page.evaluate("() => window.reviewRequests.filter(item => item.method === 'PATCH')")
            assert patches[-1]["body"]["expected_version"] == "history-v2"
            assert patches[-1]["body"]["fields"]["body"] == "Local working body"


@pytest.mark.parametrize("lifecycle", ["sent", "cancelled", "editing", "denied"])
def test_retained_assist_input_survives_close_but_is_deleted_when_action_is_not_editable(page, lifecycle):
    _require_bundle()
    with harness_build.start_static_server() as origin:
        _, dialog, edit = _open_editor(page, origin)
        dialog.get_by_label("Message Ask AI", exact=True).fill("Retained private input")
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        expect(edit).to_be_enabled()
        retained = page.evaluate("() => window.OrchHarness.stores.assistThread.useAssistThreadStore.getState().threads['pending-review:act-review']")
        assert retained["draft"]["text"] == "Retained private input"
        edit.click()
        expect(dialog.get_by_label("Message Ask AI", exact=True)).to_have_value("Retained private input")
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        expect(edit).to_be_enabled()
        page.evaluate("""lifecycle => {
            const changed = { ...window.actionsById['act-review'], can_edit:false,
                viewer_is_owner:lifecycle !== 'denied',
                status:lifecycle === 'denied' ? 'pending' : lifecycle, version:'noneditable-v2' };
            window.actionsById['act-review'] = changed;
            window.OrchHarness.stores.pendingActions.chatPendingActionsStore.getState().remember(changed, {authoritative:true});
        }""", lifecycle)
        expect(edit).to_have_count(0)
        cleared = page.evaluate("() => window.OrchHarness.stores.assistThread.useAssistThreadStore.getState().threads['pending-review:act-review']")
        assert cleared is None


def test_terminal_action_deletes_pending_global_thread_and_late_assist_cannot_restore_it(page):
    _require_bundle()
    with harness_build.start_static_server() as origin:
        _, dialog, _ = _open_editor(page, origin)
        page.evaluate("() => window.deferReviewAssist = true")
        dialog.get_by_label("Message Ask AI", exact=True).fill("Pending private instruction")
        dialog.get_by_role("button", name="Send to Ask AI", exact=True).click()
        page.wait_for_function("() => typeof window.releaseReviewAssist === 'function'")
        page.evaluate("""() => {
            const terminal = { ...window.actionsById['act-review'], status:'sent', can_edit:false,
                can_send_now:false, can_approve:false, version:'terminal-v3' };
            window.actionsById['act-review'] = terminal;
            window.reviewHistory = [];
            window.OrchHarness.stores.pendingActions.chatPendingActionsStore.getState().remember(terminal, {authoritative:true});
        }""")
        expect(dialog.get_by_label("Subject", exact=True)).to_have_count(0)
        page.evaluate("""async () => {
            window.releaseReviewAssist();
            await new Promise(resolve => window.requestAnimationFrame(resolve));
        }""")
        expect(dialog.get_by_text("Improved the wording. Review before saving.", exact=True)).to_have_count(0)
        cleared = page.evaluate("() => window.OrchHarness.stores.assistThread.useAssistThreadStore.getState().threads['pending-review:act-review']")
        assert cleared is None


def test_partial_save_pause_keeps_working_copy_until_recovery_or_terminal_action(page):
    _require_bundle()
    with harness_build.start_static_server() as origin:
        _, dialog, _ = _open_editor(page, origin)
        dialog.get_by_label("Subject", exact=True).fill("Unsaved working subject")
        page.evaluate("""() => {
            const state = window.OrchHarness.stores.pendingActions.chatPendingActionsStore.getState();
            const blocked = { ...window.actionsById['act-review'], status:'review_required',
                can_edit:false, can_send_now:false, version:'partial-v2' };
            window.actionsById['act-review'] = blocked;
            state.remember(blocked, {authoritative:true});
        }""")
        expect(dialog.get_by_label("Subject", exact=True)).to_have_value("Unsaved working subject")
        expect(dialog.get_by_label("Subject", exact=True)).to_be_disabled()
        expect(dialog.get_by_role("button", name="Save changes", exact=True)).to_be_disabled()
        page.evaluate("""() => {
            window.actionsById['act-review'] = { ...window.actionsById['act-review'],
                status:'pending', can_edit:true, can_send_now:true, version:'repaired-v3' };
            window.reviewVersion = 'repaired-v3';
        }""")
        dialog.get_by_role("button", name="Reload saved draft", exact=True).click()
        page.get_by_role("dialog", name="Discard unsaved changes?", exact=True).get_by_role(
            "button", name="Discard and reload", exact=True,
        ).click()
        expect(dialog.get_by_label("Subject", exact=True)).to_have_value("Quarterly numbers")
        expect(dialog.get_by_label("Subject", exact=True)).to_be_enabled()
        dialog.get_by_label("Subject", exact=True).fill("Another unsaved subject")
        dialog.get_by_label("Message Ask AI", exact=True).fill("Active private input")
        page.evaluate("""() => {
            const terminal = { ...window.actionsById['act-review'], status:'sent',
                can_edit:false, can_send_now:false, version:'terminal-v4' };
            window.OrchHarness.stores.pendingActions.chatPendingActionsStore.getState().remember(terminal, {authoritative:true});
        }""")
        expect(dialog.get_by_label("Subject", exact=True)).to_have_count(0)
        expect(dialog.get_by_role("log", name="Draft review history", exact=True)).not_to_contain_text("Another unsaved subject")
        cleared = page.evaluate("() => window.OrchHarness.stores.assistThread.useAssistThreadStore.getState().threads['pending-review:act-review']")
        assert cleared is None
