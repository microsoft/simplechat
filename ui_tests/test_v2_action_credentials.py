# test_v2_action_credentials.py
"""
Functional UI test for private credential cards in React V2.
Version: 0.261.348
Implemented in: 0.261.333
Continuation recovery regressions added in: 0.261.343

Exercises the real card and shared chat continuation, with closed local API fixtures.
Secrets must be submitted only to the credential endpoint, disappear on submission and
navigation, and never enter chat stores or browser storage. No Azure service is contacted.
"""

import sys
import json
import os
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "orchestration"))
import harness_build as hb
from test_v2_orchestration_plan_editor import make_plan


REQUEST = {
    "id": "credential-1",
    "etag": "etag-1",
    "conversation_id": "conversation-1",
    "action_name": "Shared Yamcs",
    "destination_label": "Mission telemetry",
    "reason": "missing",
    "status": "pending",
    "requirements": [
        {"slot": "proxy", "auth_type": "username_password", "label": "Proxy sign-in"}
    ],
    "identities": [{"id": "identity-1", "name": "Existing proxy", "auth_type": "username_password", "etag": "identity-etag-1"}],
}

SETUP = r"""
(request) => {
    const H = window.OrchHarness;
    H.reset();
    H.stores.chat.useChatStore.setState({
        activeConversationId: request.conversation_id,
        activeConversationKind: request.conversation_kind || 'personal',
    });
    H.stores.bootstrap.useBootstrapStore.setState({data: {user: {id: 'actor-1'}}});
    window.__credentialCalls = [];
    window.fetch = async (url, options = {}) => {
        const path = String(url);
        const body = options.body ? JSON.parse(options.body) : null;
        window.__credentialCalls.push({path, body, headers: options.headers});
        if (path.includes('/api/action-credentials/pending')) {
            return new Response(JSON.stringify({requests: [request], csrf_token: 'fixture-csrf-token'}), {headers: {'Content-Type': 'application/json'}});
        }
        if (path.endsWith('/submit')) {
            return new Response(JSON.stringify({credential_request: {...request, status: 'ready', etag: 'etag-2'}}),
                {headers: {'Content-Type': 'application/json'}});
        }
        if (path.endsWith('/api/action-credentials/' + request.id)) {
            return new Response(JSON.stringify({credential_request: {...request, status: 'ready', etag: 'etag-3'},
                csrf_token: 'fixture-csrf-token'}), {headers: {'Content-Type': 'application/json'}});
        }
        if (path.endsWith('/cancel')) {
            return new Response(JSON.stringify({credential_request: {...request, status: 'cancelled'}}),
                {headers: {'Content-Type': 'application/json'}});
        }
        if (path.endsWith('/continue')) {
            return new Response('data: ' + JSON.stringify({done: true, content: 'Telemetry resumed', message_id: 'answer-1'}) + '\n\n',
                {headers: {'Content-Type': 'text/event-stream'}});
        }
        if (path.includes('/messages')) return new Response(JSON.stringify([]), {headers: {'Content-Type': 'application/json'}});
        return new Response(JSON.stringify({}), {headers: {'Content-Type': 'application/json'}});
    };
    H.mount('mount-a', 'CredentialRequestCards', {
        conversationId: request.conversation_id, conversationKind: request.conversation_kind || 'personal',
    });
}
"""


@pytest.mark.parametrize("conversation_kind", ["personal", "collaborative"])
def test_private_credentials_save_continue_and_navigation(conversation_kind):
    errors = []
    request = {**REQUEST, "conversation_kind": conversation_kind}
    try:
        with hb.harness_page(collect_errors=errors) as page:
            page.evaluate(SETUP, request)
            card = page.get_by_role("region", name="Personal action credentials")
            card.wait_for()
            card.get_by_label("Username", exact=True).fill("private-user-sentinel")
            password = card.get_by_label("Password", exact=True)
            password.fill("private-password-sentinel")
            captured = page.evaluate("""() => JSON.stringify({
                chat: window.OrchHarness.stores.chat.useChatStore.getState(),
                orchestration: window.OrchHarness.stores.orchestration.useOrchestrationStore.getState(),
                local: {...localStorage}, session: {...sessionStorage}
            })""")
            assert "private-user-sentinel" not in captured
            assert "private-password-sentinel" not in captured
            card.get_by_role("button", name="Save and continue", exact=True).click()
            page.wait_for_function("() => window.__credentialCalls.some(call => call.path.endsWith('/continue'))")
            calls = page.evaluate("window.__credentialCalls")
            submit = next(call for call in calls if call["path"].endswith("/submit"))
            continued = next(call for call in calls if call["path"].endswith("/continue"))
            assert submit["body"]["slots"][0]["credentials"]["password"] == "private-password-sentinel"
            assert continued["body"] == {"expected_etag": "etag-2"}
            assert submit["headers"]["X-CSRFToken"] == "fixture-csrf-token"
            assert continued["headers"]["X-CSRFToken"] == "fixture-csrf-token"
            assert not any("/api/chat/stream" in call["path"] for call in calls)
            assert card.count() == 0
            captured = page.evaluate("""() => JSON.stringify({
                chat: window.OrchHarness.stores.chat.useChatStore.getState(),
                orchestration: window.OrchHarness.stores.orchestration.useOrchestrationStore.getState(),
                local: {...localStorage}, session: {...sessionStorage}
            })""")
            assert "private-password-sentinel" not in captured
            assert "private-user-sentinel" not in captured
            page.evaluate(SETUP, request)
            card.wait_for()
            card.get_by_label("Password", exact=True).fill("discard-on-navigation")
            page.evaluate("""() => window.OrchHarness.mount('mount-a', 'CredentialRequestCards',
                {conversationId: 'conversation-2', conversationKind: 'collaborative'})""")
            page.wait_for_function('() => document.querySelectorAll(\'input[type="password"]\').length === 0')
            assert page.locator('input[type="password"]').count() == 0
            page.evaluate("""(kind) => window.OrchHarness.mount('mount-a', 'CredentialRequestCards',
                {conversationId: 'conversation-1', conversationKind: kind})""", conversation_kind)
            card.wait_for()
            assert card.get_by_label("Password", exact=True).input_value() == ""
            card.get_by_label("Personal identity", exact=True).select_option("identity-1")
            assert card.get_by_label("Password", exact=True).count() == 0
            page.evaluate("window.__credentialCalls = []")
            card.get_by_role("button", name="Save and continue", exact=True).click()
            page.wait_for_function("() => window.__credentialCalls.filter(call => call.path.endsWith('/submit')).length === 1")
            latest = page.evaluate("window.__credentialCalls.find(call => call.path.endsWith('/submit')).body")
            assert latest["slots"] == [{"slot": "proxy", "identity_id": "identity-1"}]
            page.evaluate(SETUP, request)
            card.wait_for()
            card.get_by_label("Password", exact=True).fill("discard-on-account-change")
            page.evaluate("""() => window.OrchHarness.stores.bootstrap.useBootstrapStore.setState({
                data: {user: {id: 'actor-2'}}
            })""")
            page.wait_for_function('() => document.querySelector(\'input[type="password"]\')?.value === ""')
            assert card.get_by_label("Password", exact=True).input_value() == ""
            assert not errors, errors
    except hb.HarnessUnavailable as exc:
        pytest.skip(str(exc))


@pytest.mark.parametrize("status, copy", [
    (401, "Your session has expired."),
    (404, "Your access to this conversation could not be confirmed."),
    (503, "Unfinished action sign-in requests could not be checked."),
])
def test_pending_load_errors_have_truthful_copy_and_single_flight_retry(status, copy):
    errors = []
    with hb.harness_page(collect_errors=errors) as page:
        page.evaluate("""(status) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({data: {user: {id: 'actor-1'}}});
            window.__pendingChecks = 0;
            window.fetch = () => {
                window.__pendingChecks += 1;
                if (window.__pendingChecks === 1) return Promise.resolve(new Response('{}', {status}));
                return new Promise(resolve => { window.__finishPendingCheck = () => resolve(new Response(
                    JSON.stringify({requests: [], csrf_token: 'fixture-csrf-token'}),
                    {headers: {'Content-Type': 'application/json'}}
                )); });
            };
            H.mount('mount-a', 'CredentialRequestCards', {conversationId: 'shared', conversationKind: null});
        }""", status)
        assert page.evaluate("window.__pendingChecks") == 0
        page.evaluate("""() => window.OrchHarness.mount('mount-a', 'CredentialRequestCards',
            {conversationId: 'shared', conversationKind: 'collaborative'})""")
        alert = page.get_by_role("alert")
        alert.filter(has_text=copy).wait_for()
        page.get_by_role("button", name="Reload requests", exact=True).click()
        checking = page.get_by_role("button", name="Checking requests...", exact=True)
        checking.wait_for()
        assert checking.is_disabled()
        checking.evaluate("(node) => { node.click(); node.click(); }")
        assert page.evaluate("window.__pendingChecks") == 2
        assert alert.get_attribute("aria-busy") == "true"
        page.evaluate("window.__finishPendingCheck()")
        alert.wait_for(state="detached")
        assert page.get_by_role("region", name="Personal action credentials").count() == 0
        assert not errors, errors


def test_navigation_discards_stale_pending_response():
    errors = []
    with hb.harness_page(collect_errors=errors) as page:
        page.evaluate("""() => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({data: {user: {id: 'actor-1'}}});
            window.__resolvePending = {};
            window.fetch = url => new Promise(resolve => {
                const id = new URL(url, location.origin).searchParams.get('conversation_id');
                window.__resolvePending[id] = payload => resolve(new Response(JSON.stringify(payload),
                    {headers: {'Content-Type': 'application/json'}}));
            });
            H.mount('mount-a', 'CredentialRequestCards', {conversationId: 'conversation-1', conversationKind: 'collaborative'});
        }""")
        page.wait_for_function("() => Boolean(window.__resolvePending['conversation-1'])")
        page.evaluate("""() => window.OrchHarness.mount('mount-a', 'CredentialRequestCards',
            {conversationId: 'conversation-2', conversationKind: 'collaborative'})""")
        page.wait_for_function("() => Boolean(window.__resolvePending['conversation-2'])")
        page.evaluate("""request => {
            window.__resolvePending['conversation-2']({requests: [], csrf_token: 'current-token'});
            window.__resolvePending['conversation-1']({requests: [request], csrf_token: 'stale-token'});
        }""", {**REQUEST, "conversation_kind": "collaborative"})
        page.wait_for_function("() => document.querySelectorAll('input[type=password]').length === 0")
        assert page.get_by_role("region", name="Personal action credentials").count() == 0
        assert not errors, errors


def test_action_source_controls_and_responsive_card():
    errors = []
    root = Path(__file__).resolve().parents[1]
    schemas = root / "application" / "single_app" / "static" / "json" / "schemas"
    definition = {
        "type": "yamcs", "display": "Yamcs",
        "allowed_auth_types": ["username_password", "key", "identity", "NoAuth"],
        "additional_fields_schema": json.loads((schemas / "yamcs_plugin.additional_settings.schema.json").read_text()),
        "metadata_schema": {},
    }
    initial = {
        "type": "yamcs", "name": "mission", "displayName": "Mission",
        "endpoint": "https://mission.example.test", "auth": {"type": "key", "key": ""},
        "identity_id": "", "is_global": True, "metadata": {},
        "additionalFields": {"instance": "simulator", "server_url": "https://mission.example.test", "auth_method": "api_key"},
    }
    try:
        with hb.harness_page(collect_errors=errors) as page:
            page.evaluate("""(props) => window.OrchHarness.mount('mount-a', 'ActionCredentialAuthoring', props)""",
                          {"initial": initial, "definition": definition})
            page.get_by_label("Yamcs credential source", exact=True).select_option("personal")
            page.get_by_label("Authentication method", exact=True).select_option("bearer_token")
            requirement = json.loads(page.get_by_label("Action credential requirements").inner_text())
            assert requirement["slots"]["service"]["auth_type"] == "bearer_token"
            page.get_by_label("Authentication method", exact=True).select_option("api_key")
            page.get_by_role("checkbox", name="Send Basic auth to a reverse proxy").check()
            page.get_by_label("Proxy credential source", exact=True).select_option("personal")
            assert page.get_by_label("Proxy username", exact=True).count() == 0
            requirement = json.loads(page.get_by_label("Action credential requirements").inner_text())
            assert set(requirement["slots"]) == {"service", "proxy"}
            assert page.get_by_role("button", name="Test connection").is_disabled()
            page.get_by_role("checkbox", name="Send Basic auth to a reverse proxy").uncheck()
            requirement = json.loads(page.get_by_label("Action credential requirements").inner_text())
            assert set(requirement["slots"]) == {"service"}
            page.evaluate(SETUP, {**REQUEST, "destination_label": "mission-" + "server-" * 40})
            card = page.get_by_role("region", name="Personal action credentials")
            card.wait_for()
            css = list((root / "application" / "single_app" / "static" / "v2" / "assets").glob("*.css"))
            if not css:
                raise AssertionError("Build the production V2 styles before visual checks.")
            page.add_style_tag(path=str(css[0]))
            screenshots = os.environ.get("SIMPLECHAT_CREDENTIAL_SCREENSHOT_DIR")
            for width, theme in ((1440, "light"), (390, "dark")):
                page.set_viewport_size({"width": width, "height": 900})
                page.evaluate("(dark) => document.documentElement.classList.toggle('dark', dark)", theme == "dark")
                size = card.bounding_box()
                assert size and size["x"] >= 0 and size["x"] + size["width"] <= width
                overflow = card.evaluate("(node) => node.scrollWidth > node.clientWidth")
                assert not overflow
                if screenshots:
                    card.screenshot(path=str(Path(screenshots) / f"credential-card-{theme}-{width}.png"))
            assert not errors, errors
    except hb.HarnessUnavailable as exc:
        pytest.skip(str(exc))


def test_ready_request_resumes_same_orchestration_without_new_run():
    errors = []
    plan = make_plan("conversation-1", "turn-1")
    plan["status"] = "waiting"
    plan["approval"]["state"] = "approved"
    ready = {**REQUEST, "status": "ready", "run_id": plan["run_id"], "turn_id": "turn-1"}
    try:
        with hb.harness_page(collect_errors=errors) as page:
            page.evaluate(SETUP, ready)
            page.evaluate(r"""({plan, request}) => {
                const H = window.OrchHarness;
                const originalFetch = window.fetch;
                H.stores.chat.useChatStore.setState({messages: [{
                    id: 'original-question', conversation_id: request.conversation_id,
                    role: 'user', content: 'Read mission telemetry.',
                    metadata: {orchestration_turn_id: plan.turn_id}
                }]});
                window.fetch = async (url, options = {}) => {
                    const path = String(url);
                    if (path.endsWith('/runs/' + plan.run_id)) {
                        return new Response(JSON.stringify({run: {
                            run_id: plan.run_id, turn_id: plan.turn_id,
                            conversation_id: plan.conversation_id, status: 'waiting', outcome: 'waiting', plan
                        }}), {headers: {'Content-Type': 'application/json'}});
                    }
                    if (path.endsWith('/continue')) {
                        window.__credentialCalls.push({path, body: JSON.parse(options.body)});
                        const frames = [
                            {type: 'orchestration_step', run_id: plan.run_id, conversation_id: plan.conversation_id,
                             step_id: 'research', status: 'completed'},
                            {type: 'orchestration_done', done: true, status: 'completed', outcome: 'completed',
                             run_id: plan.run_id, turn_id: plan.turn_id, conversation_id: plan.conversation_id,
                             message_id: 'resumed-answer', user_message_id: 'original-question',
                             full_content: 'Mission telemetry resumed.'}
                        ];
                        return new Response(frames.map(frame => 'data: ' + JSON.stringify(frame) + '\n\n').join(''),
                            {headers: {'Content-Type': 'text/event-stream'}});
                    }
                    return originalFetch(url, options);
                };
            }""", {"plan": plan, "request": ready})
            card = page.get_by_role("region", name="Personal action credentials")
            card.wait_for()
            assert card.locator('input[type="password"]').count() == 0
            card.get_by_role("button", name="Continue", exact=True).click()
            page.wait_for_function("() => window.__credentialCalls.some(call => call.path.endsWith('/continue'))")
            page.wait_for_function("() => !window.OrchHarness.stores.chat.useChatStore.getState().streaming")
            calls = page.evaluate("window.__credentialCalls")
            continued = next(call for call in calls if call["path"].endswith("/continue"))
            assert continued["body"] == {"expected_etag": "etag-1"}
            assert not any(call["body"] and "plan_id" in call["body"] for call in calls)
            assert not any("/api/chat/stream" in call["path"] for call in calls)
            messages = page.evaluate("window.OrchHarness.stores.chat.useChatStore.getState().messages")
            assert len([message for message in messages if message["role"] == "user"]) == 1
            assert any(message["id"] == "resumed-answer" for message in messages)
            assert card.count() == 0
            assert not errors, errors
    except hb.HarnessUnavailable as exc:
        pytest.skip(str(exc))


@pytest.mark.parametrize("failure_kind", ["conflict", "error_sse", "transport"])
def test_failed_continuation_clears_secrets_and_refreshes_saved_revision(failure_kind):
    errors = []
    try:
        with hb.harness_page(collect_errors=errors) as page:
            page.evaluate(SETUP, REQUEST)
            page.evaluate(r"""(failureKind) => {
                const originalFetch = window.fetch;
                window.fetch = async (url, options = {}) => {
                    if (String(url).endsWith('/continue')) {
                        window.__credentialCalls.push({path: String(url), body: JSON.parse(options.body)});
                        if (failureKind === 'transport') throw new TypeError('Private provider failure sentinel');
                        if (failureKind === 'error_sse') return new Response(
                            'data: ' + JSON.stringify({error: 'The request could not be completed.'}) + '\n\n',
                            {headers: {'Content-Type': 'text/event-stream'}});
                        return new Response(JSON.stringify({error: 'request_changed'}), {
                            status: 409, headers: {'Content-Type': 'application/json'}
                        });
                    }
                    return originalFetch(url, options);
                };
            }""", failure_kind)
            card = page.get_by_role("region", name="Personal action credentials")
            card.wait_for()
            card.get_by_label("Username", exact=True).fill("rejected-user-sentinel")
            card.get_by_label("Password", exact=True).fill("rejected-secret-sentinel")
            card.get_by_role("button", name="Save and continue", exact=True).click()
            card.get_by_role("alert").wait_for()
            assert card.get_by_role("alert").inner_text() == (
                "Your credentials are saved, but continuation could not be confirmed. "
                "Refresh the saved request before trying again."
            )
            assert card.get_by_role("button", name="Continue", exact=True).is_disabled()
            assert card.get_by_role("button", name="Cancel blocked work", exact=True).is_disabled()
            screenshots = os.environ.get("SIMPLECHAT_CREDENTIAL_SCREENSHOT_DIR")
            if screenshots and failure_kind == "conflict":
                root = Path(__file__).resolve().parents[1]
                css = next((root / "application" / "single_app" / "static" / "v2" / "assets").glob("*.css"))
                page.add_style_tag(path=str(css))
                for width, theme in ((1440, "light"), (390, "dark")):
                    page.set_viewport_size({"width": width, "height": 900})
                    page.evaluate("(dark) => document.documentElement.classList.toggle('dark', dark)", theme == "dark")
                    overflow = card.evaluate("(node) => node.scrollWidth > node.clientWidth")
                    assert not overflow
                    card.screenshot(path=str(Path(screenshots) / f"credential-recovery-{theme}-{width}.png"))
            assert card.locator("input").count() == 0
            assert "rejected-secret-sentinel" not in card.inner_text()
            state = page.evaluate("""() => JSON.stringify({
                chat: window.OrchHarness.stores.chat.useChatStore.getState(),
                orchestration: window.OrchHarness.stores.orchestration.useOrchestrationStore.getState(),
                local: {...localStorage}, session: {...sessionStorage}
            })""")
            assert "rejected-user-sentinel" not in state
            assert "rejected-secret-sentinel" not in state
            assert "Private provider failure sentinel" not in card.inner_text()
            card.get_by_role("button", name="Refresh saved request", exact=True).click()
            page.wait_for_function('() => !document.querySelector(\'section[aria-label="Personal action credentials"] [role="alert"]\')')
            card.get_by_role("button", name="Cancel blocked work", exact=True).click()
            page.wait_for_function("() => window.__credentialCalls.some(call => call.path.endsWith('/cancel'))")
            cancellation = page.evaluate("window.__credentialCalls.find(call => call.path.endsWith('/cancel')).body")
            assert cancellation == {"expected_etag": "etag-3"}
            page.wait_for_function('() => !document.querySelector(\'section[aria-label="Personal action credentials"]\')')
            assert not errors, errors
    except hb.HarnessUnavailable as exc:
        pytest.skip(str(exc))


@pytest.mark.parametrize("request_status,run_status", [
    ("failed", "failed"), ("completed", "completed"), ("superseded", "waiting"),
    ("continuing", "running"), ("pending", "failed"), ("ready", "failed"), ("ready", "waiting"),
    ("ready", "unconfirmed"),
])
def test_refresh_uses_authoritative_credential_and_run_state(request_status, run_status):
    errors = []
    plan = make_plan("conversation-1", "turn-1")
    plan["status"] = "waiting"
    plan["approval"]["state"] = "approved"
    ready = {**REQUEST, "status": "ready", "run_id": plan["run_id"], "turn_id": plan["turn_id"]}
    try:
        with hb.harness_page(collect_errors=errors) as page:
            page.evaluate(SETUP, ready)
            page.evaluate(r"""({plan, request, requestStatus, runStatus}) => {
                const originalFetch = window.fetch;
                window.__refreshed = false;
                window.fetch = async (url, options = {}) => {
                    const path = String(url).split('?')[0];
                    if (path.endsWith('/api/action-credentials/' + request.id)) {
                        window.__refreshed = true;
                        window.__credentialCalls.push({path, body: null});
                        return new Response(JSON.stringify({credential_request: {...request,
                            status: requestStatus, etag: 'etag-4'}}),
                            {headers: {'Content-Type': 'application/json'}});
                    }
                    if (path.endsWith('/runs/' + plan.run_id)) {
                        window.__credentialCalls.push({path: String(url), body: null});
                        if (window.__refreshed && runStatus === 'unconfirmed') return new Response('{}',
                            {headers: {'Content-Type': 'application/json'}});
                        return new Response(JSON.stringify({run: {
                            run_id: plan.run_id, turn_id: plan.turn_id, conversation_id: plan.conversation_id,
                            status: window.__refreshed ? runStatus : 'waiting',
                            outcome: window.__refreshed ? runStatus : 'waiting', plan
                        }}), {headers: {'Content-Type': 'application/json'}});
                    }
                    if (path.endsWith('/continue')) {
                        window.__credentialCalls.push({path, body: JSON.parse(options.body)});
                        return new Response('{}', {status: 409, headers: {'Content-Type': 'application/json'}});
                    }
                    return originalFetch(url, options);
                };
            }""", {"plan": plan, "request": ready, "requestStatus": request_status, "runStatus": run_status})
            card = page.get_by_role("region", name="Personal action credentials")
            card.wait_for()
            card.get_by_role("button", name="Continue", exact=True).click()
            card.get_by_role("alert").wait_for()
            card.get_by_role("button", name="Refresh saved request", exact=True).click()
            page.wait_for_function("() => window.__refreshed && document.querySelector('form')?.getAttribute('aria-busy') === 'false'")
            if request_status == "ready" and run_status == "waiting":
                assert card.get_by_role("button", name="Continue", exact=True).is_enabled()
                assert card.get_by_role("alert").count() == 0
                card.get_by_role("button", name="Continue", exact=True).click()
                card.get_by_role("alert").wait_for()
                continued = page.evaluate("window.__credentialCalls.filter(call => call.path.endsWith('/continue'))")
                assert [call["body"]["expected_etag"] for call in continued] == ["etag-1", "etag-4"]
            elif run_status == "unconfirmed":
                assert card.get_by_role("button", name="Continue", exact=True).is_disabled()
                assert "could not be refreshed" in card.get_by_role("alert").inner_text()
            else:
                assert card.get_by_role("button", name="Continue", exact=True).count() == 0
                assert card.get_by_role("button", name="Cancel blocked work", exact=True).count() == 0
                assert "Review run details" in card.get_by_role("alert").inner_text()
            assert card.locator('input[type="password"]').count() == 0
            calls = page.evaluate("window.__credentialCalls")
            assert not any(call["path"].endswith("/submit") for call in calls)
            if request_status == "ready":
                assert any("conversation_id=conversation-1" in call["path"] for call in calls)
            assert not errors, errors
    except hb.HarnessUnavailable as exc:
        pytest.skip(str(exc))


@pytest.mark.parametrize("refresh_result", ["ready", "unavailable", "cancelled"])
def test_unconfirmed_save_requires_real_refresh_without_resubmission(refresh_result):
    errors = []
    try:
        with hb.harness_page(collect_errors=errors) as page:
            page.evaluate(SETUP, REQUEST)
            page.evaluate(r"""({request, refreshResult}) => {
                const originalFetch = window.fetch;
                window.fetch = async (url, options = {}) => {
                    const path = String(url);
                    if (path.endsWith('/submit')) {
                        window.__credentialCalls.push({path, body: JSON.parse(options.body)});
                        throw new TypeError('Connection lost after saving');
                    }
                    if (refreshResult !== 'ready' && path.endsWith('/api/action-credentials/credential-1')) {
                        window.__credentialCalls.push({path, body: null});
                        if (refreshResult === 'unavailable') throw new TypeError('PRIVATE_SENTINEL');
                        return new Response(JSON.stringify({credential_request: {...request,
                            status: refreshResult, etag: 'etag-3'}}), {headers: {'Content-Type': 'application/json'}});
                    }
                    return originalFetch(url, options);
                };
            }""", {"request": REQUEST, "refreshResult": refresh_result})
            card = page.get_by_role("region", name="Personal action credentials")
            card.wait_for()
            card.get_by_label("Personal identity", exact=True).select_option("identity-1")
            card.get_by_role("button", name="Save and continue", exact=True).click()
            card.get_by_role("alert").wait_for()
            assert card.get_by_role("alert").inner_text() == (
                "Saving could not be confirmed. Refresh the saved request before entering credentials again."
            )
            assert card.get_by_role("button", name="Save and continue", exact=True).is_disabled()
            assert card.locator("input").count() == 0
            card.get_by_role("button", name="Refresh saved request", exact=True).click()
            if refresh_result == "unavailable":
                card.get_by_text("The saved request could not be refreshed. Reload this conversation before trying again.").wait_for()
                assert card.get_by_role("button", name="Save and continue", exact=True).is_disabled()
                assert "PRIVATE_SENTINEL" not in card.inner_text()
            elif refresh_result == "cancelled":
                card.get_by_text("This work is no longer waiting for these credentials. Review the conversation before starting new work.").wait_for()
                assert card.get_by_role("button", name="Save and continue", exact=True).count() == 0
                assert card.get_by_role("status").count() == 0
            else:
                card.get_by_role("button", name="Continue", exact=True).click()
                page.wait_for_function("() => window.__credentialCalls.some(call => call.path.endsWith('/continue'))")
                continued = page.evaluate("window.__credentialCalls.find(call => call.path.endsWith('/continue')).body")
                assert continued == {"expected_etag": "etag-3"}
            calls = page.evaluate("window.__credentialCalls")
            assert len([call for call in calls if call["path"].endswith("/submit")]) == 1
            assert not errors, errors
    except hb.HarnessUnavailable as exc:
        pytest.skip(str(exc))


def test_duplicate_submit_and_unmount_do_not_start_another_continuation():
    errors = []
    try:
        with hb.harness_page(collect_errors=errors) as page:
            page.evaluate(SETUP, REQUEST)
            page.evaluate(r"""(request) => {
                const originalFetch = window.fetch;
                window.fetch = async (url, options = {}) => {
                    if (String(url).endsWith('/submit')) {
                        window.__credentialCalls.push({path: String(url), body: JSON.parse(options.body)});
                        return new Promise(resolve => {window.__finishSave = () => resolve(new Response(
                            JSON.stringify({credential_request: {...request, status: 'ready', etag: 'etag-2'}}),
                            {headers: {'Content-Type': 'application/json'}}));});
                    }
                    return originalFetch(url, options);
                };
            }""", REQUEST)
            card = page.get_by_role("region", name="Personal action credentials")
            card.wait_for()
            card.get_by_label("Personal identity", exact=True).select_option("identity-1")
            card.locator("form").evaluate("""form => {
                form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
                form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
            }""")
            page.wait_for_function("() => typeof window.__finishSave === 'function'")
            page.evaluate("""() => window.OrchHarness.mount('mount-a', 'CredentialRequestCards',
                {conversationId: 'conversation-2'})""")
            page.wait_for_function('() => !document.querySelector(\'section[aria-label="Personal action credentials"]\')')
            page.evaluate("async () => {window.__finishSave(); await new Promise(resolve => setTimeout(resolve, 0));}")
            calls = page.evaluate("window.__credentialCalls")
            assert len([call for call in calls if call["path"].endswith("/submit")]) == 1
            assert not any(call["path"].endswith("/continue") for call in calls)
            assert not errors, errors
    except hb.HarnessUnavailable as exc:
        pytest.skip(str(exc))


def test_replace_existing_identity_uses_its_revision_fence():
    errors = []
    try:
        with hb.harness_page(collect_errors=errors) as page:
            page.evaluate(SETUP, {**REQUEST, "reason": "credentials_rejected"})
            card = page.get_by_role("region", name="Personal action credentials")
            card.wait_for()
            card.get_by_label("Personal identity", exact=True).select_option("identity-1")
            card.get_by_role("checkbox", name="Replace credentials in this personal identity").check()
            assert card.get_by_label("Identity name", exact=True).count() == 0
            card.get_by_label("Username", exact=True).fill("rotated-principal")
            card.get_by_label("Password", exact=True).fill("rotated-private-secret")
            card.get_by_role("button", name="Save and continue", exact=True).click()
            page.wait_for_function("() => window.__credentialCalls.some(call => call.path.endsWith('/continue'))")
            submitted = page.evaluate("window.__credentialCalls.find(call => call.path.endsWith('/submit')).body")
            assert submitted["slots"] == [{
                "slot": "proxy", "identity_id": "identity-1", "expected_identity_etag": "identity-etag-1",
                "credentials": {"auth_type": "username_password", "username": "rotated-principal", "password": "rotated-private-secret"},
            }]
            state = page.evaluate("""() => JSON.stringify({
                chat: window.OrchHarness.stores.chat.useChatStore.getState(),
                orchestration: window.OrchHarness.stores.orchestration.useOrchestrationStore.getState(),
                local: {...localStorage}, session: {...sessionStorage}
            })""")
            assert "rotated-private-secret" not in state
            assert "rotated-principal" not in state
            assert not errors, errors
    except hb.HarnessUnavailable as exc:
        pytest.skip(str(exc))


@pytest.mark.parametrize("auth_type", ["api_key", "bearer_token", "username_password"])
def test_service_credential_fields_and_direct_submission(auth_type):
    errors = []
    request = {**REQUEST, "requirements": [{
        "slot": "service", "auth_type": auth_type, "label": "Yamcs sign-in",
    }]}
    try:
        with hb.harness_page(collect_errors=errors) as page:
            page.evaluate(SETUP, request)
            card = page.get_by_role("region", name="Personal action credentials")
            card.wait_for()
            if auth_type == "username_password":
                card.get_by_label("Username", exact=True).fill("service-principal-sentinel")
            else:
                assert card.get_by_label("Username", exact=True).count() == 0
            label = "Password" if auth_type == "username_password" else "API key" if auth_type == "api_key" else "Bearer token"
            secret = card.get_by_label(label, exact=True)
            assert secret.get_attribute("type") == "password"
            secret.fill("service-secret-sentinel")
            card.get_by_role("button", name="Save and continue", exact=True).click()
            page.wait_for_function("() => window.__credentialCalls.some(call => call.path.endsWith('/continue'))")
            submitted = page.evaluate("window.__credentialCalls.find(call => call.path.endsWith('/submit')).body")
            slot = submitted["slots"][0]
            assert slot["slot"] == "service"
            assert slot["credentials"]["auth_type"] == auth_type
            key = "password" if auth_type == "username_password" else "secret"
            assert slot["credentials"][key] == "service-secret-sentinel"
            state = page.evaluate("JSON.stringify(window.OrchHarness.stores.chat.useChatStore.getState())")
            assert "service-secret-sentinel" not in state
            assert "service-principal-sentinel" not in state
            assert not errors, errors
    except hb.HarnessUnavailable as exc:
        pytest.skip(str(exc))
