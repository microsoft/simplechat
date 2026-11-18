# test_bitbucket_action_configuration.py
"""
Functional UI tests for Classic and V2 Bitbucket action configuration.
Version: 0.261.450
Implemented in: 0.261.450

Real production components exercise repository discovery, fixed branches,
private token sources, connection links and narrow/mobile layouts.
"""

import json
from pathlib import Path
import sys

import pytest
from playwright.sync_api import expect


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))
from classic_action_credentials import ClassicCredentialFixture
from ui_tests.fixtures.orchestration import harness_build as hb


REPOSITORY = {"id": "1", "project": "team", "slug": "repo", "name": "Repository",
              "branch_mode": "any", "default_branch": ""}
ACTION = {
    "id": "review", "name": "code_review", "displayName": "Code review",
    "type": "bitbucket", "endpoint": "https://bitbucket.example.test",
    "auth": {"type": "user", "identity": "client-id", "key": ""},
    "additionalFields": {"edition": "data_center", "auth_method": "oauth", "repositories": []},
    "metadata": {},
}


def _reply(route, value):
    route.fulfill(content_type="application/json", body=json.dumps(value))


@pytest.mark.parametrize("width", [390, 1440])
def test_classic_bitbucket_repository_discovery_and_private_token_source(page, width):
    page.set_viewport_size({"width": width, "height": 1000})
    fixture = ClassicCredentialFixture(page, modal=True)
    page.route("**/api/*/plugins/types", lambda route: _reply(route, [
        {"type": "bitbucket", "display": "Bitbucket", "description": "Review repository source."},
    ]))
    page.route("**/api/bitbucket/connection?**", lambda route: _reply(route, {"connected": True, "csrf_token": "fixture-csrf"}))
    calls = []

    def discover(route):
        calls.append(route.request.post_data_json)
        assert route.request.headers["x-csrftoken"] == "fixture-csrf"
        _reply(route, {"repositories": [REPOSITORY], "next_cursor": None})

    page.route("**/api/bitbucket/discover", discover)
    fixture.open()
    fixture.show_action(manifest=ACTION)
    expect(page.get_by_role("link", name="Connect / reconnect my Bitbucket account")).to_have_attribute(
        "href", "/bitbucket/connect?action_ref=personal%3Aself%3Areview",
    )
    page.get_by_label("Data Center project key or Cloud workspace").fill("team")
    page.get_by_role("button", name="Find repositories", exact=True).click()
    page.get_by_role("checkbox", name="Repository (team/repo)").check()
    page.get_by_label("Allowed branches", exact=True).select_option("fixed")
    page.get_by_label("Fixed branch (required)").fill("main")
    form = fixture.form_data()
    assert form["additionalFields"]["repositories"] == [{**REPOSITORY, "branch_mode": "fixed", "default_branch": "main"}]
    assert calls == [{"action_ref": "personal:self:review", "project": "team", "cursor": 0}]
    page.get_by_label("Bitbucket authentication", exact=True).select_option("bearer_token")
    page.get_by_label("Token credential source").select_option("personal")
    form = fixture.form_data()
    assert form["auth"]["key"] == "" and form["identity_id"] == ""
    assert form["credential_requirements"] == {"version": 1, "slots": {"service": {"source": "personal", "auth_type": "bearer_token"}}}
    expect(page.get_by_label("Read-only token", exact=True)).to_be_hidden()
    expect(page.get_by_role("button", name="Find repositories", exact=True)).to_be_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    fixture.assert_clean()


@pytest.mark.parametrize("width", [390, 1440])
def test_v2_bitbucket_discovery_policy_and_oauth_connection(page, width):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    hb.ensure_bundle()
    with hb.start_static_server() as origin:
        page.goto(f"{origin}/{hb.HARNESS_HTML_REL}")
        page.wait_for_function("() => typeof window.OrchHarness?.mount === 'function'")
        css = next((ROOT / "application" / "single_app" / "static" / "v2" / "assets").glob("*.css"), None)
        if css is None:
            raise AssertionError("Build the production V2 UI before Bitbucket layout tests.")
        page.add_style_tag(url=f"{origin}/application/single_app/static/v2/assets/{css.name}")
        page.set_viewport_size({"width": width, "height": 1000})
        page.evaluate("""(initial) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({data: {user: {id: 'actor'}}});
            window.__bitbucketCalls = [];
            window.fetch = async (url, options = {}) => {
                window.__bitbucketCalls.push({url: String(url), body: options.body ? JSON.parse(options.body) : null, headers: options.headers});
                const result = String(url).includes('/connection?')
                    ? {connected: true, csrf_token: 'fixture-csrf'}
                    : {repositories: [{id: '1', project: 'team', slug: 'repo', name: 'Repository', branch_mode: 'any', default_branch: ''}], next_cursor: null};
                return new Response(JSON.stringify(result), {headers: {'Content-Type': 'application/json'}});
            };
            H.mount('mount-a', 'ActionCredentialAuthoring', {
                initial, definition: {type: 'bitbucket', display: 'Bitbucket',
                    allowed_auth_types: ['user', 'key', 'identity', 'username_password'], additional_fields_schema: {}, metadata_schema: {}}
            });
        }""", ACTION)
        expect(page.get_by_role("link", name="Connect / reconnect my Bitbucket account")).to_have_attribute(
            "href", "/bitbucket/connect?action_ref=global%3Aglobal%3Areview",
        )
        page.get_by_label("Data Center project key", exact=True).fill("team")
        page.get_by_role("button", name="Find repositories", exact=True).click()
        page.get_by_role("checkbox", name="Repository (repo)").check()
        page.get_by_label("Allowed branches", exact=True).select_option("fixed")
        page.get_by_label("Fixed branch", exact=True).fill("main")
        content = page.get_by_label("Bitbucket repository configuration").inner_text()
        assert json.loads(content) == [{**REPOSITORY, "branch_mode": "fixed", "default_branch": "main"}]
        page.get_by_label("Bitbucket authentication", exact=True).select_option("bearer_token")
        page.get_by_label("Token credential source", exact=True).select_option("identity")
        expect(page.get_by_label("Token credential source", exact=True)).to_have_value("identity")
        page.get_by_label("Token credential source", exact=True).select_option("personal")
        requirements = page.get_by_label("Action credential requirements").inner_text()
        assert json.loads(requirements) == {"version": 1, "slots": {"service": {"source": "personal", "auth_type": "bearer_token"}}}
        expect(page.get_by_label("Read-only token", exact=True)).to_have_count(0)
        calls = page.evaluate("window.__bitbucketCalls")
        discovered = next(call for call in calls if call["url"].endswith("/discover"))
        assert discovered["headers"]["X-CSRFToken"] == "fixture-csrf"
        assert discovered["body"] == {"action_ref": "global:global:review", "project": "team", "cursor": 0}
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not errors, errors
