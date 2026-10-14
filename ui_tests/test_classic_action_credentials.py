# test_classic_action_credentials.py
"""
UI coverage of private action credentials and YAMCS personal-slot authoring.
Version: 0.261.337
Implemented in: 0.261.333

Runs the production card asset, real Bootstrap partial and production stepper
with the configured local/Azure Playwright browser. Only APIs and the host
chat continuation callback are mocked; no credential enters a chat payload.
"""

import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from classic_action_credentials import ClassicCredentialFixture, credential_request


pytestmark = pytest.mark.ui


@pytest.fixture
def card(page):
    fixture = ClassicCredentialFixture(page)
    yield fixture
    fixture.assert_clean()


@pytest.fixture
def editor(page):
    fixture = ClassicCredentialFixture(page, modal=True)
    fixture.open()
    yield fixture
    fixture.assert_clean()


def _fill_new_identity(page, name="Mission login"):
    page.get_by_label("Identity name", exact=True).fill(name)
    page.get_by_label("Username", exact=True).fill("fixture-user")
    page.get_by_label("Password", exact=True).fill("fixture-secret-not-real")


@pytest.mark.parametrize("width", [390, 1440])
def test_private_card_saves_directly_and_continues_without_question_replay(card, width):
    page = card.page
    page.set_viewport_size({"width": width, "height": 900})
    card.open()
    expect(page.get_by_role("heading", name="Connect to Mission telemetry")).to_be_visible()
    expect(page.get_by_role("group", name="Proxy sign-in")).to_be_visible()
    _fill_new_identity(page)
    page.get_by_label("Password", exact=True).press("Tab")
    expect(page.get_by_role("button", name="Save and continue")).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.locator("#continuation-result")).to_have_text("Blocked read resumed")
    expect(page.locator("[data-credential-request-id]")).to_have_count(0)
    assert [post["path"] for post in card.posts] == [
        "/api/action-credentials/request-1/submit", "/api/action-credentials/request-1/continue",
    ]
    assert card.posts[0]["body"] == {
        "expected_etag": '"revision-1"',
        "slots": [{"slot": "proxy", "name": "Mission login", "credentials": {
            "auth_type": "username_password", "username": "fixture-user", "password": "fixture-secret-not-real",
        }}],
    }
    assert card.posts[1]["body"] == {"expected_etag": '"revision-2"'}
    assert all(post["headers"]["x-csrftoken"] == "fixture-csrf-token" for post in card.posts)
    assert page.evaluate("window.__continuedConversation") == "conversation-1"
    assert page.evaluate("localStorage.length + sessionStorage.length") == 0
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_compatible_existing_identities_and_independent_slots(card):
    card.current = credential_request([
        {"slot": "service", "auth_type": "api_key", "label": "Yamcs sign-in"},
        {"slot": "proxy", "auth_type": "username_password", "label": "Proxy sign-in"},
    ])
    card.open()
    service = card.page.get_by_role("group", name="Yamcs sign-in")
    proxy = card.page.get_by_role("group", name="Proxy sign-in")
    expect(service.get_by_role("option", name="My proxy identity")).to_have_count(0)
    expect(proxy.get_by_role("option", name="My service identity")).to_have_count(0)
    service.get_by_label("Personal identity", exact=True).select_option("user-key")
    proxy.get_by_label("Personal identity", exact=True).select_option("user-pass")
    expect(service.get_by_label("API key")).to_be_hidden()
    expect(proxy.get_by_label("Password", exact=True)).to_be_hidden()
    card.page.get_by_role("button", name="Save and continue").click()
    expect(card.page.locator("#continuation-result")).to_have_text("Blocked read resumed")
    assert card.posts[0]["body"]["slots"] == [
        {"slot": "service", "identity_id": "user-key"}, {"slot": "proxy", "identity_id": "user-pass"},
    ]


@pytest.mark.parametrize("auth_type,label", [("api_key", "API key"), ("bearer_token", "Bearer token")])
def test_masked_service_secret_fields(card, auth_type, label):
    card.current = credential_request([{"slot": "service", "auth_type": auth_type, "label": "Yamcs sign-in"}])
    card.open()
    expect(card.page.get_by_label(label)).to_have_attribute("type", "password")
    card.page.get_by_label("Identity name", exact=True).fill("My service login")
    card.page.get_by_label(label).fill("fixture-token")
    card.page.get_by_role("button", name="Save and continue").click()
    expect(card.page.locator("#continuation-result")).to_have_text("Blocked read resumed")
    assert card.posts[0]["body"]["slots"][0]["credentials"] == {"auth_type": auth_type, "secret": "fixture-token"}


@pytest.mark.parametrize("submit_status", [409, 403, 500])
def test_private_errors_clear_secrets_and_never_render_provider_text(card, submit_status):
    card.submit_status = submit_status
    card.open()
    _fill_new_identity(card.page)
    card.page.get_by_role("button", name="Save and continue").click()
    expect(card.page.get_by_role("alert")).to_be_visible()
    expect(card.page.get_by_label("Password", exact=True)).to_have_value("")
    expect(card.page.get_by_role("button", name="Cancel", exact=True)).to_be_enabled()
    expect(card.page.get_by_role("button", name="Refresh request")).to_be_visible()
    assert "SECRET-provider-stack" not in card.page.locator("body").inner_text()
    assert len(card.posts) == 1
    assert card.posts[0]["path"].endswith("/submit")


def test_ready_request_recovers_failed_continue_without_saving_twice(card):
    card.continue_status = 409
    card.open()
    _fill_new_identity(card.page)
    card.page.get_by_role("button", name="Save and continue").click()
    expect(card.page.get_by_role("alert")).to_be_visible()
    card.continue_status = 200
    card.page.get_by_role("button", name="Refresh request").click()
    expect(card.page.get_by_label("Password", exact=True)).to_have_count(0)
    card.page.get_by_role("button", name="Save and continue").click()
    expect(card.page.locator("#continuation-result")).to_have_text("Blocked read resumed")
    assert sum(post["path"].endswith("/submit") for post in card.posts) == 1
    assert len(card.posts) == 3


def test_rejected_personal_identity_can_rotate_with_its_own_revision(card):
    card.current["reason"] = "credentials_rejected"
    card.open()
    page = card.page
    page.get_by_label("Personal identity", exact=True).select_option("user-pass")
    page.get_by_label("Replace credentials in this personal identity").check()
    expect(page.get_by_label("Identity name", exact=True)).to_be_hidden()
    page.get_by_label("Username", exact=True).fill("fixture-rotated-user")
    page.get_by_label("Password", exact=True).fill("fixture-rotated-secret")
    page.get_by_role("button", name="Save and continue").click()
    expect(page.locator("#continuation-result")).to_have_text("Blocked read resumed")
    assert card.posts[0]["body"]["slots"] == [{
        "slot": "proxy", "identity_id": "user-pass", "expected_identity_etag": '"identity-1"',
        "credentials": {
            "auth_type": "username_password", "username": "fixture-rotated-user", "password": "fixture-rotated-secret",
        },
    }]


def test_stream_request_event_reads_current_request_and_csrf_before_display(card):
    card.open()
    page = card.page
    page.evaluate("window.SimpleChatActionCredentials.clear()")
    handled = page.evaluate("""dto => window.SimpleChatActionCredentials.handleEvent({
        type: 'action_credentials_required', credential_request: dto
    })""", card.current)
    assert handled
    expect(page.get_by_role("heading", name="Connect to Mission telemetry")).to_be_visible()
    _fill_new_identity(page)
    page.get_by_role("button", name="Save and continue").click()
    expect(page.locator("#continuation-result")).to_have_text("Blocked read resumed")
    assert card.posts[0]["headers"]["x-csrftoken"] == "fixture-csrf-token"


def test_production_stream_consumer_pauses_and_resumes_dedicated_request(page):
    fixture = ClassicCredentialFixture(page, real_stream=True)
    fixture.open()
    page.evaluate("""() => window.__sendOriginal({
        conversation_id: 'conversation-1', message: 'Read telemetry once'
    }, null, 'conversation-1')""")
    expect(page.get_by_role("heading", name="Connect to Mission telemetry")).to_be_visible()
    _fill_new_identity(page)
    page.get_by_role("button", name="Save and continue").click()
    expect(page.locator("#chatbox")).to_contain_text("Blocked read resumed")
    expect(page.locator("[data-credential-request-id]")).to_have_count(0)
    assert sum(post["path"] == "/api/chat/stream" for post in fixture.posts) == 1
    assert [post["path"] for post in fixture.posts] == [
        "/api/chat/stream", "/api/action-credentials/request-1/submit", "/api/action-credentials/request-1/continue",
    ]
    fixture.assert_clean()


def test_late_private_request_response_cannot_reappear_after_navigation(card):
    card.open()
    page = card.page
    page.evaluate("""() => {
        window.SimpleChatActionCredentials.clear();
        const fetchOriginal = window.fetch;
        window.fetch = (url, options) => String(url).endsWith('/request-1')
            ? new Promise(resolve => { window.__resolveCredentialRead = resolve; })
            : fetchOriginal(url, options);
    }""")
    page.evaluate("""dto => window.SimpleChatActionCredentials.handleEvent({
        type: 'action_credentials_required', credential_request: dto
    })""", card.current)
    expect(page.get_by_role("status")).to_contain_text("Loading private")
    page.evaluate("""dto => {
        window.currentConversationId = 'conversation-2';
        window.dispatchEvent(new CustomEvent('chat:conversation-context-changed'));
        window.__resolveCredentialRead(new Response(JSON.stringify({
            credential_request: dto, csrf_token: 'old-session-token'
        }), { headers: { 'Content-Type': 'application/json' } }));
    }""", card.current)
    expect(page.locator("#chat-action-credentials")).to_have_count(0)
    assert card.posts == []


def test_submission_clears_inputs_immediately_and_disables_duplicate_mutations(card):
    card.open()
    page = card.page
    _fill_new_identity(page)
    page.evaluate("""() => {
        const original = window.fetch;
        window.fetch = (url, options) => String(url).endsWith('/submit')
            ? new Promise(resolve => {
                window.__releaseCredentialSubmit = () => resolve(original(url, options));
            }) : original(url, options);
    }""")
    page.get_by_role("button", name="Save and continue").click()
    expect(page.get_by_label("Password", exact=True)).to_have_value("")
    expect(page.get_by_label("Password", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Save and continue")).to_be_disabled()
    expect(page.get_by_role("button", name="Cancel", exact=True)).to_be_disabled()
    expect(page.get_by_role("status")).to_contain_text("Saving your personal identity")
    page.evaluate("window.__releaseCredentialSubmit()")
    expect(page.locator("#continuation-result")).to_have_text("Blocked read resumed")
    assert len(card.posts) == 2


def test_pending_load_error_has_retry_and_does_not_become_a_chat_message(card):
    card.get_status = 503
    card.open()
    expect(card.page.get_by_role("alert")).to_contain_text("could not be refreshed")
    expect(card.page.locator("[data-credential-request-id]")).to_have_count(0)
    card.get_status = 200
    card.page.get_by_role("button", name="Retry", exact=True).click()
    expect(card.page.get_by_role("heading", name="Connect to Mission telemetry")).to_be_visible()
    assert card.posts == []


@pytest.mark.parametrize("operation", ["navigation", "signout", "unmount", "cancel"])
def test_secret_inputs_cleared_at_lifecycle_boundaries(card, operation):
    card.open()
    _fill_new_identity(card.page)
    card.page.evaluate("window.__oldPasswordInput = document.querySelector('input[type=password]')")
    if operation == "cancel":
        card.page.get_by_role("button", name="Cancel", exact=True).click()
        expect(card.page.locator("[data-credential-request-id]")).to_have_count(0)
        assert card.posts[0]["body"] == {"expected_etag": '"revision-1"'}
    elif operation == "navigation":
        card.page.evaluate("""() => {
            window.currentConversationId = 'conversation-2';
            window.dispatchEvent(new CustomEvent('chat:conversation-context-changed', {
                detail: { conversationId: 'conversation-2' }
            }));
        }""")
    elif operation == "signout":
        card.page.evaluate("window.dispatchEvent(new Event('simplechat:signout'))")
    else:
        card.page.evaluate("document.querySelector('[data-credential-request-id]').remove()")
    card.page.wait_for_function("window.__oldPasswordInput.value === ''")
    assert card.page.evaluate("window.__oldPasswordInput.value") == ""
    if operation == "navigation":
        card.page.evaluate("""() => window.SimpleChatActionCredentials.handleEvent({
            type: 'action_credentials_required', credential_request: {
                id: 'request-1', etag: 'stale', conversation_id: 'conversation-1',
                requirements: [], identities: [], status: 'pending'
            }
        })""")
        expect(card.page.locator("[data-credential-request-id]")).to_have_count(0)


def test_reload_restores_only_safe_pending_request_and_xss_is_inert(card):
    card.current["action_name"] = "<img src=x onerror=window.__xss=true>"
    card.current["destination_label"] = "<script>window.__xss=true</script>"
    card.current["identities"][0]["name"] = "<img src=x onerror=window.__xss=true>"
    card.open()
    _fill_new_identity(card.page)
    card.open()
    expect(card.page.get_by_label("Password", exact=True)).to_have_value("")
    expect(card.page.get_by_role("heading")).to_contain_text("<img")
    assert card.page.evaluate("window.__xss !== true")
    assert card.page.locator("#chatbox img, #chatbox script").count() == 0


@pytest.mark.parametrize("scope", ["personal", "group", "global"])
def test_classic_authoring_personal_slots_clear_competing_shared_credentials(editor, scope):
    editor.show_action(scope)
    page = editor.page
    page.locator("#yamcs-api-key").fill("fixture-shared-secret")
    page.get_by_label("Yamcs credential source", exact=True).select_option("personal")
    page.get_by_label("Server is behind a proxy that requires HTTP Basic authentication").check()
    page.locator("#yamcs-basic-auth-username").fill("shared-proxy")
    page.locator("#yamcs-basic-auth-password").fill("fixture-proxy-secret")
    page.get_by_label("Proxy credential source", exact=True).select_option("personal")
    expect(page.locator("#yamcs-api-key")).to_be_hidden()
    expect(page.locator("#yamcs-basic-auth-password")).to_be_hidden()
    valid = page.evaluate("window.pluginModalStepper.validateCurrentStep()")
    assert valid
    payload = editor.form_data()
    assert payload["credential_requirements"] == {"version": 1, "slots": {
        "service": {"source": "personal", "auth_type": "api_key"},
        "proxy": {"source": "personal", "auth_type": "username_password"},
    }}
    assert payload["auth"] == {"type": "NoAuth", "key": "", "identity": ""}
    assert payload["identity_id"] == ""
    assert payload["additionalFields"]["basic_auth_identity_id"] == ""
    assert payload["additionalFields"]["basic_auth_username"] == ""
    assert payload["additionalFields"]["basic_auth_password"] == ""
    expect(page.locator("#yamcs-test-connection-btn")).to_be_disabled()
    expect(page.locator("#yamcs-personal-test-note")).to_contain_text("use it in chat")
    page.evaluate("window.pluginModalStepper.goToStep(5)")
    expect(page.locator("#summary-yamcs-auth-method")).to_contain_text("Personal identity for each user")
    expect(page.locator("#summary-yamcs-basic-auth")).to_contain_text("Personal proxy sign-in")
    editor.show_action(scope, payload)
    expect(page.get_by_label("Yamcs credential source", exact=True)).to_have_value("personal")
    expect(page.get_by_label("Proxy credential source", exact=True)).to_have_value("personal")
    assert editor.form_data()["credential_requirements"] == payload["credential_requirements"]


def test_proxy_only_personal_mode_and_shared_mode_restoration(editor):
    editor.show_action()
    page = editor.page
    page.locator("#yamcs-auth-method").select_option("none")
    page.get_by_label("Server is behind a proxy that requires HTTP Basic authentication").check()
    page.get_by_label("Proxy credential source", exact=True).select_option("personal")
    valid = page.evaluate("window.pluginModalStepper.validateCurrentStep()")
    assert valid
    payload = editor.form_data()
    assert payload["auth"]["type"] == "NoAuth"
    assert payload["credential_requirements"] == {"version": 1, "slots": {
        "proxy": {"source": "personal", "auth_type": "username_password"},
    }}
    page.get_by_label("Proxy credential source", exact=True).select_option("shared")
    page.locator("#yamcs-basic-auth-username").fill("shared-user")
    page.locator("#yamcs-basic-auth-password").fill("fixture-shared-password")
    shared = editor.form_data()
    assert shared["credential_requirements"] == {"version": 1, "slots": {}}
    assert shared["additionalFields"]["basic_auth_password"] == "fixture-shared-password"


def test_legacy_reusable_identity_remains_same_scope_and_shared(editor):
    editor.show_action("global")
    page = editor.page
    page.locator("#yamcs-identity-select").select_option("shared-identity")
    expect(page.locator("#yamcs-auth-method")).to_be_disabled()
    expect(page.locator("#yamcs-api-key")).to_be_hidden()
    payload = editor.form_data()
    assert payload["identity_id"] == "shared-identity"
    assert payload["auth"] == {"type": "identity", "identity": "shared-identity"}
    assert payload["credential_requirements"] == {"version": 1, "slots": {}}
    assert payload["additionalFields"]["identity_auth_type"] == "api_key"
    page.get_by_label("Yamcs credential source", exact=True).select_option("personal")
    cleared = editor.form_data()
    assert cleared["identity_id"] == ""
    assert cleared["auth"] == {"type": "NoAuth", "key": "", "identity": ""}
    page.get_by_label("Yamcs credential source", exact=True).select_option("shared")
    expect(page.locator("#yamcs-api-key")).to_have_value("")
    expect(page.locator("#yamcs-auth-method")).to_be_enabled()
    assert editor.form_data()["credential_requirements"] == {"version": 1, "slots": {}}


@pytest.mark.parametrize("method", ["username_password", "bearer_token", "none"])
def test_authoring_rejects_personal_none_and_proxy_authorization_conflicts(editor, method):
    editor.show_action()
    page = editor.page
    page.get_by_label("Yamcs credential source", exact=True).select_option("personal")
    page.locator("#yamcs-auth-method").select_option(method)
    if method != "none":
        page.get_by_label("Server is behind a proxy that requires HTTP Basic authentication").check()
        page.get_by_label("Proxy credential source", exact=True).select_option("personal")
    valid = page.evaluate("window.pluginModalStepper.validateCurrentStep()")
    assert valid is False
    expect(page.locator("#plugin-modal-error")).to_be_visible()
