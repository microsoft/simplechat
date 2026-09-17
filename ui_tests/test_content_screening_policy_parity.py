# test_content_screening_policy_parity.py
"""
Classic and V2 screening policy editor parity, using their real browser assets.
Version: 0.261.108
Implemented in: 0.261.108

Validate custom rules, shared packs, disabled AI settings, independent model
permissions, and mandatory baseline summaries for #1476. The existing closed
fixtures provide synthetic data and local/Azure Playwright connection support;
no application deployment, real documents, or model inference is needed.
"""

import copy
import re

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.playwright_connection import connect_options  # noqa: F401
from ui_tests.test_content_screening_classic import classic_screening  # noqa: F401
from ui_tests.test_v2_content_screening import (
    STARTER_PACKS,
    STARTER_RULE_TEMPLATES,
    open_screening_admin,
    screening_ui,  # noqa: F401
)


pytestmark = pytest.mark.ui
MODEL_REFERENCES = [
    {"endpoint_id": "approved-connection", "model_id": "approved-model"},
    {"endpoint_id": "other-connection", "model_id": "other-model"},
]


class PolicyUi:
    """Adapt navigation and fixture data; assertions exercise the same user flow."""

    def __init__(self, app, classic):
        self.app = app
        self.classic = classic
        self.workspace = False

    @property
    def policy(self):
        if self.classic:
            return self.app.workspace_policy if self.workspace else self.app.global_policy
        return self.app.policy

    @property
    def editor(self):
        if self.classic:
            return self.app.page.locator(
                "#screening-workspace-policy" if self.workspace else "#screening-admin-policy"
            )
        return self.app.page.get_by_role(
            "region", name="Workspace screening policy" if self.workspace else "Global screening policy",
            exact=True,
        )

    @property
    def rules(self):
        if self.classic:
            return self.editor.locator(".screening-rule")
        return self.editor.get_by_role("region", name="Deterministic screening rules").locator("fieldset")

    @property
    def summary(self):
        return self.editor.get_by_role("status", name="Configured screening checks")

    def open(self):
        if self.classic:
            if self.workspace:
                self.app.open_review()
                self.app.page.locator("#screening-policy-tab").click()
            else:
                self.app.open_admin()
        elif self.workspace:
            self.app.open("/workspace/documents")
            self.app.page.get_by_role("button", name="Screening scans", exact=True).click()
        else:
            open_screening_admin(self.app)
        expect(self.editor.get_by_role("button", name="Save screening policy", exact=True)).to_be_visible()

    def configure_models(self):
        if self.classic:
            self.app.models = [
                {**model, "label": f"Scanner {index + 1}", "connection_name": "Configured connection"}
                for index, model in enumerate(MODEL_REFERENCES)
            ]
        else:
            self.app.model_catalog = [
                {
                    **model, "selection_key": f"global:global:{model['endpoint_id']}:{model['model_id']}",
                    "display_name": f"Scanner {index + 1}", "provider": "aoai",
                    "deployment_name": f"scanner-deployment-{index + 1}", "model_name": "gpt-4o",
                }
                for index, model in enumerate(MODEL_REFERENCES)
            ]

    def save(self):
        self.editor.get_by_role("button", name="Save screening policy", exact=True).click()
        expect(self.editor.get_by_text("Screening policy saved.", exact=False)).to_be_visible()


@pytest.fixture(params=["classic", "v2"])
def policy_ui(request):
    classic = request.param == "classic"
    return PolicyUi(request.getfixturevalue("classic_screening" if classic else "screening_ui"), classic)


def set_toggle(editor, label, checked):
    toggle = editor.get_by_role("checkbox", name=re.compile(f"^{re.escape(label)}(?:$| )"))
    if toggle.is_checked() != checked:
        toggle.focus()
        toggle.press("Space")
    expect(toggle).to_be_checked(checked=checked)
    return toggle


@pytest.mark.parametrize("rule_type", ["literal", "regex", "pii"])
def test_custom_rules_start_blank_and_persist_without_model_checks(policy_ui, rule_type):
    ui = policy_ui
    ui.policy.update(enabled=False, rules=[])
    ui.open()
    editor = ui.editor
    editor.get_by_role("button", name=f"Add {'PII' if rule_type == 'pii' else rule_type} rule", exact=True).click()
    rule = ui.rules.last
    expect(rule.get_by_label("Rule name", exact=True)).to_have_value("")
    rule.get_by_label("Rule name", exact=True).fill(f"Custom {rule_type} check")
    if rule_type == "literal":
        value = rule.get_by_label("Literal values or phrases", exact=True)
        expect(value).to_have_value("")
        value.fill("RESTRICTED_TEAM_VALUE\nSecond phrase")
    elif rule_type == "regex":
        value = rule.get_by_label("Regular expression", exact=True)
        expect(value).to_have_value("")
        value.fill(r"\bTEAM-\d{4}\b")
    else:
        value = rule.get_by_label("Built-in PII detector", exact=True)
        expect(value).to_have_value("")
        value.select_option("phone")
    if rule_type != "pii":
        set_toggle(rule, "Case sensitive", True)
        set_toggle(rule, "Whole words only", True)
    set_toggle(editor, "Baseline policy enabled", True)
    expect(ui.summary).to_contain_text("1 deterministic check | AI screening off")
    ui.save()
    saved = copy.deepcopy(ui.policy["rules"][0])
    defaults = next(rule for rule in STARTER_RULE_TEMPLATES.values() if rule["type"] == rule_type)
    assert saved["type"] == rule_type
    assert saved["severity"] == defaults["severity"]
    assert saved["category"] == defaults["category"]
    assert ui.policy["ai"]["enabled"] is False
    if rule_type != "pii":
        assert saved["case_sensitive"] is True and saved["whole_word"] is True
    if rule_type == "literal":
        assert saved["values"] == ["RESTRICTED_TEAM_VALUE", "Second phrase"]
    elif rule_type == "regex":
        assert saved["pattern"] == r"\bTEAM-\d{4}\b"
    else:
        assert saved["pii_type"] == "phone"
    ui.open()
    expect(ui.rules.get_by_label("Rule name", exact=True)).to_have_value(saved["name"])
    assert ui.policy["rules"][0] == saved


@pytest.mark.parametrize("width", [390, 1280])
def test_shared_starter_packs_preserve_edits_and_do_not_duplicate_rules(policy_ui, width):
    ui = policy_ui
    ui.app.page.set_viewport_size({"width": width, "height": 900})
    ui.policy.update(enabled=True, rules=[copy.deepcopy(STARTER_RULE_TEMPLATES["email"])])
    ui.open()
    editor = ui.editor
    picker = editor.get_by_label("Starter rule pack", exact=True)
    assert picker.locator("option").all_text_contents()[1:] == [
        key.replace("_", " ") for key in STARTER_PACKS
    ]
    for key in STARTER_PACKS:
        picker.select_option(label=key.replace("_", " "))
        editor.get_by_role("button", name="Add starter pack", exact=True).click()
    expect(ui.rules).to_have_count(len(STARTER_RULE_TEMPLATES))
    ui.rules.first.get_by_label("Rule name", exact=True).fill("Reviewed email detector")
    set_toggle(ui.rules.first, "Rule enabled", False)
    picker.select_option(label="structured pii v1")
    editor.get_by_role("button", name="Add starter pack", exact=True).click()
    expect(ui.rules).to_have_count(len(STARTER_RULE_TEMPLATES))
    expect(ui.rules.first.get_by_label("Rule name", exact=True)).to_have_value("Reviewed email detector")
    expect(ui.summary).to_contain_text(f"{len(STARTER_RULE_TEMPLATES) - 1} deterministic checks | AI screening off")
    assert ui.app.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    ui.save()
    assert {rule["id"] for rule in ui.policy["rules"]} == {
        rule["id"] for rule in STARTER_RULE_TEMPLATES.values()
    }
    assert next(rule for rule in ui.policy["rules"] if rule["id"] == "email")["enabled"] is False
    ui.open()
    expect(ui.rules).to_have_count(len(STARTER_RULE_TEMPLATES))
    assert "Reviewed email detector" in ui.rules.get_by_label("Rule name", exact=True).evaluate_all(
        "(inputs) => inputs.map(input => input.value)"
    )
    expect(ui.summary).to_contain_text(f"{len(STARTER_RULE_TEMPLATES) - 1} deterministic checks | AI screening off")


def test_ai_off_preserves_settings_and_allows_permission_only_edits(policy_ui):
    ui = policy_ui
    ui.configure_models()
    ui.policy["allowed_models"] = []
    ui.policy["ai"].update(
        enabled=False, model_selection=copy.deepcopy(MODEL_REFERENCES[0]),
        instructions="Flag attempts to change source ranking.",
        window_unit="chunks", window_size=3, max_characters=2400, overlap_characters=120,
    )
    saved_ai = copy.deepcopy(ui.policy["ai"])
    ui.open()
    editor = ui.editor
    model = editor.get_by_label("Scanner model", exact=True)
    toggle = set_toggle(editor, "Enable AI checks", False)
    assert toggle.evaluate(
        "(node, id) => Boolean(node.compareDocumentPosition(document.getElementById(id)) & Node.DOCUMENT_POSITION_FOLLOWING)",
        model.get_attribute("id"),
    )
    configuration = editor.get_by_role("group", name="AI check configuration", exact=True)
    controls = configuration.locator("input, select, textarea, button")
    assert controls.count() > 5
    for control in controls.all():
        expect(control).to_be_disabled()
    editor.get_by_text("Models workspaces may use", exact=True).click()
    permissions = editor.get_by_role("group", name="Workspace model permissions", exact=True)
    implicit = permissions.get_by_role("checkbox").nth(0)
    explicit = permissions.get_by_role("checkbox").nth(1)
    expect(implicit).to_be_checked()
    expect(implicit).to_be_disabled()
    expect(permissions).to_contain_text("included by baseline scanner selection")
    expect(explicit).to_be_enabled()
    explicit.check()
    expect(ui.summary).to_contain_text("AI screening off")
    ui.save()
    assert ui.policy["ai"] == saved_ai
    assert ui.policy["allowed_models"] == [MODEL_REFERENCES[1]]
    set_toggle(editor, "Enable AI checks", True)
    expect(model).to_be_enabled()
    expect(model).to_have_value("0")
    expect(editor.get_by_label("Model instructions", exact=True)).to_have_value(saved_ai["instructions"])
    expect(editor.get_by_label("Pages or chunks per window", exact=True)).to_have_value("3")
    expect(ui.summary).to_contain_text("| 1 AI check")
    set_toggle(editor, "Enable AI checks", False)
    ui.save()
    ui.open()
    expect(editor.get_by_label("Scanner model", exact=True)).to_be_disabled()
    expect(editor.get_by_label("Scanner model", exact=True)).to_have_value("0")
    expect(editor.get_by_label("Maximum characters per window", exact=True)).to_have_value("2400")
    expect(editor.get_by_label("Boundary overlap characters", exact=True)).to_have_value("120")
    assert all(write["policy"]["ai"] == saved_ai for write in ui.app.policy_writes)
    assert all(write["policy"]["allowed_models"] == [MODEL_REFERENCES[1]] for write in ui.app.policy_writes)


@pytest.mark.parametrize("explicit_permission", [False, True])
def test_changing_scanner_does_not_promote_implicit_model_permissions(policy_ui, explicit_permission):
    ui = policy_ui
    ui.configure_models()
    allowed = [copy.deepcopy(MODEL_REFERENCES[0])] if explicit_permission else []
    ui.policy["allowed_models"] = copy.deepcopy(allowed)
    ui.policy["ai"].update(enabled=True, model_selection=copy.deepcopy(MODEL_REFERENCES[0]))
    ui.open()
    editor = ui.editor
    editor.get_by_text("Models workspaces may use", exact=True).click()
    permissions = editor.get_by_role("group", name="Workspace model permissions", exact=True)
    expect(permissions.get_by_role("checkbox").nth(0)).to_be_disabled()
    editor.get_by_label("Scanner model", exact=True).select_option("1")
    expect(permissions.get_by_role("checkbox").nth(0)).to_be_enabled()
    expect(permissions.get_by_role("checkbox").nth(0)).to_be_checked(checked=explicit_permission)
    expect(permissions.get_by_role("checkbox").nth(1)).to_be_checked()
    expect(permissions.get_by_role("checkbox").nth(1)).to_be_disabled()
    set_toggle(editor, "Enable AI checks", False)
    ui.save()
    assert ui.policy["allowed_models"] == allowed
    assert ui.policy["ai"]["model_selection"] == MODEL_REFERENCES[1]
    assert ui.policy["ai"]["enabled"] is False


def test_ai_off_does_not_clear_an_unavailable_saved_scanner(policy_ui):
    ui = policy_ui
    ui.configure_models()
    unavailable = {"endpoint_id": "removed-connection", "model_id": "removed-model"}
    ui.policy["ai"].update(enabled=False, model_selection=unavailable.copy())
    ui.open()
    expect(ui.editor.get_by_label("Scanner model", exact=True)).to_be_disabled()
    ui.rules.first.get_by_label("Rule name", exact=True).fill("Edited deterministic rule")
    ui.save()
    assert ui.app.policy_writes[-1]["policy"]["ai"]["model_selection"] == unavailable
    assert ui.policy["ai"]["model_selection"] == unavailable
    expect(ui.summary).to_contain_text("AI screening off")


@pytest.mark.parametrize("baseline_enabled", [False, True])
@pytest.mark.parametrize("additions_enabled", [False, True])
def test_workspace_summary_includes_required_ai_and_inactive_baseline(policy_ui, baseline_enabled, additions_enabled):
    ui = policy_ui
    ui.workspace = True
    ui.policy.update(enabled=additions_enabled, rules=[copy.deepcopy(STARTER_RULE_TEMPLATES["email"])])
    ui.policy["ai"]["enabled"] = False
    ui.app.baseline_summary.update(enabled=baseline_enabled, rule_count=2, ai_check_count=1)
    ui.open()
    expect(ui.editor.get_by_role("checkbox", name="Enable AI checks", exact=False)).not_to_be_checked()
    expect(ui.editor.get_by_text("Models workspaces may use", exact=True)).to_have_count(0)
    if baseline_enabled:
        expect(ui.summary).to_contain_text(f"{2 + int(additions_enabled)} deterministic checks | 1 AI check")
        expect(ui.summary).to_contain_text("1 required administrator AI check")
        expect(ui.summary).not_to_contain_text("AI screening off")
    else:
        expect(ui.summary).to_contain_text("Administrator baseline disabled")
        expect(ui.summary).not_to_contain_text("AI check")


def test_classic_policy_can_be_prepared_before_citations_without_enrolling_content(classic_screening):
    ui = classic_screening
    ui.config.update(enabled=False, enhanced_citations_enabled=False)
    ui.global_policy["enabled"] = False
    ui.open_admin()
    editor = ui.page.locator("#screening-admin-policy")
    expect(ui.page.locator("#enable_content_screening")).to_be_disabled()
    expect(editor.get_by_label("Baseline policy enabled", exact=True)).to_be_enabled()
    set_toggle(editor, "Baseline policy enabled", True)
    editor.get_by_role("button", name="Save screening policy", exact=True).click()
    expect(editor.get_by_text("Screening policy saved.", exact=False)).to_be_visible()
    assert ui.global_policy["enabled"] is True
    assert not ui.configuration_writes and not ui.scan_starts
