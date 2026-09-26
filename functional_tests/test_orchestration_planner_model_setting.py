# test_orchestration_planner_model_setting.py
"""
Functional tests for the orchestration planner model dropdown's settings contract.
Version: 0.261.137
Implemented in: 0.261.137

The planner model used to be four free-text settings. Both admin pages now write them from one
dropdown. This checks the V2 schema (one component, four legacy-declared keys), the classic pane
(one select and four hidden form fields the unchanged save route reads), the server's combination
check on V2 saves, and -- through Node -- the shared choice logic of both interfaces.
Run with python -m pytest functional_tests/test_orchestration_planner_model_setting.py.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from werkzeug.datastructures import MultiDict

from test_orchestration_actions_admin import NORMALIZE_FORM
from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
FIELDS = import_app_module("admin_settings_fields")
SECTION = "chat-orchestration-planner-model-section"
DEPLOYMENT, MODEL_ID, ENDPOINT_ID, PROVIDER = (
    "chat_orchestration_planner_deployment",
    "chat_orchestration_planner_model_id",
    "chat_orchestration_planner_model_endpoint_id",
    "chat_orchestration_planner_model_provider",
)
KEYS = (DEPLOYMENT, MODEL_ID, ENDPOINT_ID, PROVIDER)


def selection(deployment="", model_id="", endpoint_id="", provider=""):
    return dict(zip(KEYS, (deployment, model_id, endpoint_id, provider)))


def normalize(updates, current=None):
    return FIELDS.normalize_admin_settings_updates(updates, current or {})


def test_implementation_version():
    assert_app_version_at_least("0.261.137")


def test_v2_schema_draws_one_dropdown_and_keeps_the_four_keys_validated():
    fields = FIELDS.get_admin_settings_fields()[SECTION]
    component = fields[0]
    assert component["type"] == "component" and component["component"] == "orchestration-planner-model"
    assert component["label"] == "Planner Model" and component["help"]
    assert component["depends_on"] == {"key": "enable_chat_orchestration", "equals": True}
    declared = {field["key"]: field for field in fields[1:]}
    assert set(declared) == set(KEYS)
    assert all(field["legacy"] is True and field["type"] == "text" for field in declared.values())
    assert set(KEYS) <= FIELDS.get_legacy_field_names()
    page = (REPO_ROOT / "application" / "v2_ui" / "src" / "pages" / "AdminSettingsPage.tsx").read_text(encoding="utf-8")
    assert "case 'orchestration-planner-model':" in page


def test_classic_pane_offers_one_select_and_submits_the_four_hidden_fields():
    environment = Environment(loader=FileSystemLoader(APP_ROOT / "templates"), autoescape=select_autoescape(["html"]))
    markup = environment.get_template("admin/_panes/chat-orchestration.html").render(
        settings=selection(model_id="mini", endpoint_id="east", provider="aoai"),
        admin_landing_tab="chat-orchestration",
        orchestration_capabilities=(), orchestration_selected_capabilities=(),
    )
    select = re.search(r'<select[^>]*id="chat_orchestration_planner_model"[^>]*>', markup)
    assert select and "name=" not in select.group(0), "the dropdown itself is never submitted"
    for key in KEYS:
        hidden = re.search(rf'<input type="hidden" id="{key}" name="{key}"\s+value="([^"]*)"', markup)
        assert hidden, f"{key} must be posted by a hidden field"
    assert re.search(r'name="chat_orchestration_planner_model_id"\s+value="mini"', markup)
    assert not re.search(r'<input type="text"[^>]*name="chat_orchestration_planner', markup)
    form = MultiDict([(key, value) for key, value in selection(" ", "mini ", " east", "aoai").items()])
    normalized = NORMALIZE_FORM(form, {})
    assert {key: normalized[key] for key in KEYS} == selection("", "mini", "east", "aoai")


@pytest.mark.parametrize("chosen", [
    selection(),
    selection(model_id="mini", endpoint_id="east", provider="aoai"),
    selection(model_id="terra", endpoint_id="west"),
    selection(deployment="terra", endpoint_id="west", provider="new_foundry"),
    selection(deployment="gpt-4o-mini"),
    selection(deployment="gpt-4o-mini", provider="AOAI"),
])
def test_resolvable_selections_save(chosen):
    normalized, errors, _warnings = normalize(chosen)
    assert errors == {}
    assert {key: normalized[key] for key in KEYS} == chosen


@pytest.mark.parametrize("chosen,key", [
    (selection(model_id="mini"), ENDPOINT_ID),
    (selection(model_id="mini", provider="aoai"), ENDPOINT_ID),
    (selection(endpoint_id="east"), MODEL_ID),
    (selection(endpoint_id="east", provider="aoai"), MODEL_ID),
    (selection(provider="aoai"), DEPLOYMENT),
    (selection(deployment="claude", provider="anthropic"), PROVIDER),
])
def test_selections_the_runtime_could_never_resolve_are_refused(chosen, key):
    _normalized, errors, _warnings = normalize(chosen)
    assert list(errors) == [key]


def test_a_partial_update_is_judged_against_the_saved_selection():
    current = selection(model_id="mini", endpoint_id="east", provider="aoai")
    _normalized, errors, _warnings = normalize({MODEL_ID: ""}, current)
    assert list(errors) == [MODEL_ID]
    normalized, errors, _warnings = normalize({PROVIDER: "aoai"}, current)
    assert errors == {} and normalized == {PROVIDER: "aoai"}


def test_unrelated_saves_never_reach_the_planner_check():
    current = selection(provider="aoai")
    normalized, errors, _warnings = normalize({"enable_chat_orchestration": True}, current)
    assert errors == {} and normalized == {"enable_chat_orchestration": True}


def test_shared_choice_logic_of_both_interfaces():
    node = shutil.which("node")
    assert node, "Node is required for the existing v2 TypeScript runtime tests."
    result = subprocess.run(
        [node, str(REPO_ROOT / "functional_tests" / "test_v2_orchestration_planner_model_logic.mjs")],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
