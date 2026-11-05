# test_staging_terms_onboarding.py
"""Verify pinned, CI-only staging onboarding without bypassing consent changes.

Version: 0.261.402
Implemented in: 0.261.401
"""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "staging_auth_under_test", ROOT / "ui_tests" / "staging_auth.py",
)
AUTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTH)
TEXT = "Reviewed staging notice"
PIN = hashlib.sha256(TEXT.encode()).hexdigest()
BASE_URL = "https://stage.example.test"


@pytest.mark.parametrize("origin,expected", [(BASE_URL, {"chatTutorialDismissed": "dismissed"}), ("https://other.example.test", {})])
def test_tutorial_preference_is_browser_and_origin_scoped(origin, expected):
    class Context:
        def add_init_script(self, script):
            self.script = script

    context = Context()
    AUTH.prepare_staging_browser(context, BASE_URL)
    probe = """
const vm = require('node:vm');
const data = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const values = {};
vm.runInNewContext(data.script, {
    URL,
    window: { location: { origin: data.origin }, localStorage: { setItem: (key, value) => { values[key] = value; } } },
});
console.log(JSON.stringify(values));
"""
    result = subprocess.run(
        ["node", "-e", probe], input=json.dumps({"script": context.script, "origin": origin}),
        text=True, capture_output=True, check=True,
    )
    values = json.loads(result.stdout)
    assert values == expected


class Page:
    def __init__(self, path="/terms-of-use", text=TEXT, active_content=0):
        self.url = BASE_URL + path
        self.text = text
        self.active_content = active_content
        self.clicks = 0
        self.destination = BASE_URL + "/chats"

    def locator(self, selector):
        return self

    def wait_for(self, **kwargs):
        return None

    def inner_text(self):
        return self.text

    def count(self):
        return self.active_content

    def get_by_role(self, role, **kwargs):
        assert role == "button" and kwargs == {"name": "Accept and continue", "exact": True}
        return self

    def click(self):
        self.clicks += 1
        self.url = self.destination

    def wait_for_url(self, predicate, **kwargs):
        assert predicate(self.url)


def test_current_reviewed_content_is_accepted_in_ci_only():
    page = Page(text="  Reviewed \n staging notice ")
    completed = AUTH.complete_staging_terms_onboarding(
        page, BASE_URL, access_token="ci-test-token", terms_sha256=PIN,
    )
    assert completed is True
    assert page.clicks == 1
    assert page.url == BASE_URL + "/chats"


def test_existing_onboarding_needs_no_pin_or_additional_consent():
    page = Page(path="/chats")
    completed = AUTH.complete_staging_terms_onboarding(page, BASE_URL)
    assert completed is False
    assert page.clicks == 0


def test_default_port_and_host_case_use_the_same_origin():
    page = Page()
    completed = AUTH.complete_staging_terms_onboarding(
        page, "https://STAGE.example.test:443",
        access_token="ci-test-token", terms_sha256=PIN,
    )
    assert completed is True
    assert page.clicks == 1


def test_non_ascii_content_is_preserved_in_the_reviewed_digest():
    page = Page(text="\u00a0Reviewed staging notice\u00a0")
    digest = hashlib.sha256(page.text.encode("utf-8")).hexdigest()
    completed = AUTH.complete_staging_terms_onboarding(
        page, BASE_URL, access_token="ci-test-token", terms_sha256=digest,
    )
    assert completed is True


def test_origin_with_credentials_is_not_accepted():
    page = Page()
    with pytest.raises(AssertionError, match="without credentials"):
        AUTH.complete_staging_terms_onboarding(
            page, "https://name:password@stage.example.test",
            access_token="ci-test-token", terms_sha256=PIN,
        )
    assert page.clicks == 0


@pytest.mark.parametrize("pin", ["", "invalid", "a" * 63])
def test_missing_or_malformed_review_pin_never_clicks(pin):
    page = Page()
    with pytest.raises(AssertionError, match="reviewed SIMPLECHAT_UI_TERMS_SHA256"):
        AUTH.complete_staging_terms_onboarding(
            page, BASE_URL, access_token="ci-test-token", terms_sha256=pin,
        )
    assert page.clicks == 0


def test_changed_terms_never_reuse_previous_approval():
    page = Page(text="Different terms")
    with pytest.raises(AssertionError, match="terms changed"):
        AUTH.complete_staging_terms_onboarding(
            page, BASE_URL, access_token="ci-test-token", terms_sha256=PIN,
        )
    assert page.clicks == 0


def test_browser_state_for_a_human_identity_is_not_autoaccepted():
    page = Page()
    with pytest.raises(AssertionError, match="dedicated CI bearer identity"):
        AUTH.complete_staging_terms_onboarding(page, BASE_URL, terms_sha256=PIN)
    assert page.clicks == 0


def test_foreign_origin_never_receives_consent():
    page = Page()
    page.url = "https://other.example.test/terms-of-use"
    with pytest.raises(AssertionError, match="configured staging origin"):
        AUTH.complete_staging_terms_onboarding(
            page, BASE_URL, access_token="ci-test-token", terms_sha256=PIN,
        )
    assert page.clicks == 0


def test_linked_or_active_content_requires_manual_review():
    page = Page(active_content=1)
    with pytest.raises(AssertionError, match="manual review"):
        AUTH.complete_staging_terms_onboarding(
            page, BASE_URL, access_token="ci-test-token", terms_sha256=PIN,
        )
    assert page.clicks == 0


def test_external_post_consent_redirect_is_not_success():
    page = Page()
    page.destination = "https://other.example.test/chats"
    with pytest.raises(AssertionError, match="returned outside"):
        AUTH.complete_staging_terms_onboarding(
            page, BASE_URL, access_token="ci-test-token", terms_sha256=PIN,
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
