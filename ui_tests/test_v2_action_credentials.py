# test_v2_action_credentials.py
"""
Functional UI test for private credential cards in React V2.
Version: 0.261.335
Implemented in: 0.261.333

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
    H.stores.chat.useChatStore.setState({activeConversationId: request.conversation_id});
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
    H.mount('mount-a', 'CredentialRequestCards', {conversationId: request.conversation_id});
}
"""


def test_private_credentials_save_continue_and_navigation():
    errors = []
    try:
        with hb.harness_page(collect_errors=errors) as page:
            page.evaluate(SETUP, REQUEST)
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
            page.evaluate(SETUP, REQUEST)
            card.wait_for()
            card.get_by_label("Password", exact=True).fill("discard-on-navigation")
            page.evaluate("""() => window.OrchHarness.mount('mount-a', 'CredentialRequestCards',
                {conversationId: 'conversation-2'})""")
            page.wait_for_function('() => document.querySelectorAll(\'input[type="password"]\').length === 0')
            assert page.locator('input[type="password"]').count() == 0
            page.evaluate("""() => window.OrchHarness.mount('mount-a', 'CredentialRequestCards',
                {conversationId: 'conversation-1'})""")
            card.wait_for()
            assert card.get_by_label("Password", exact=True).input_value() == ""
            card.get_by_label("Personal identity", exact=True).select_option("identity-1")
            assert card.get_by_label("Password", exact=True).count() == 0
            page.evaluate("window.__credentialCalls = []")
            card.get_by_role("button", name="Save and continue", exact=True).click()
            page.wait_for_function("() => window.__credentialCalls.filter(call => call.path.endsWith('/submit')).length === 1")
            latest = page.evaluate("window.__credentialCalls.find(call => call.path.endsWith('/submit')).body")
            assert latest["slots"] == [{"slot": "proxy", "identity_id": "identity-1"}]
            page.evaluate(SETUP, REQUEST)
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


def test_failed_continuation_clears_secrets_and_cancels_with_saved_revision():
    errors = []
    try:
        with hb.harness_page(collect_errors=errors) as page:
            page.evaluate(SETUP, REQUEST)
            page.evaluate(r"""() => {
                const originalFetch = window.fetch;
                window.fetch = async (url, options = {}) => {
                    if (String(url).endsWith('/continue')) {
                        window.__credentialCalls.push({path: String(url), body: JSON.parse(options.body)});
                        return new Response(JSON.stringify({error: 'request_changed'}), {
                            status: 409, headers: {'Content-Type': 'application/json'}
                        });
                    }
                    return originalFetch(url, options);
                };
            }""")
            card = page.get_by_role("region", name="Personal action credentials")
            card.wait_for()
            card.get_by_label("Username", exact=True).fill("rejected-user-sentinel")
            card.get_by_label("Password", exact=True).fill("rejected-secret-sentinel")
            card.get_by_role("button", name="Save and continue", exact=True).click()
            card.get_by_role("alert").wait_for()
            assert card.locator("input").count() == 0
            assert "rejected-secret-sentinel" not in card.inner_text()
            state = page.evaluate("""() => JSON.stringify({
                chat: window.OrchHarness.stores.chat.useChatStore.getState(),
                orchestration: window.OrchHarness.stores.orchestration.useOrchestrationStore.getState(),
                local: {...localStorage}, session: {...sessionStorage}
            })""")
            assert "rejected-user-sentinel" not in state
            assert "rejected-secret-sentinel" not in state
            card.get_by_role("button", name="Cancel blocked work", exact=True).click()
            page.wait_for_function("() => window.__credentialCalls.some(call => call.path.endsWith('/cancel'))")
            cancellation = page.evaluate("window.__credentialCalls.find(call => call.path.endsWith('/cancel')).body")
            assert cancellation == {"expected_etag": "etag-2"}
            page.wait_for_function('() => !document.querySelector(\'section[aria-label="Personal action credentials"]\')')
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
