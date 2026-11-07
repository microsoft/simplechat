#!/usr/bin/env python3
# test_orchestration_workflow_runs_admin.py
"""
Functional test for the admin switch that lets chat orchestration start saved workflows.
Version: 0.261.212
Implemented in: 0.261.212

This test ensures that ``enable_chat_orchestration_workflow_runs`` is off unless an administrator
turns it on, that it is independent of the workflow proposals switch, and that both admin surfaces
save it faithfully:

* ``get_settings`` seeds it off, and the registry names the same key the admin surfaces write.
* The V2 schema declares an off-by-default switch in the Chat Orchestration Capabilities section,
  after Propose Workflows From Chat, shown only while Chat Orchestration and personal workflows are
  both on, without displacing Enable Action Access as the section's header switch.
* The V2 settings update coerces the submitted value and changes nothing else, including the
  proposals switch; a save of another field keeps a hidden stored value.
* The Classic pane renders the switch with its help, and the Classic form reads it like its
  neighbouring checkboxes: present as ``on`` means on, absent means off, and neither workflow
  switch changes the other.
* ``update_settings`` stores only a real ``True`` as on and leaves an absent value alone.
* The capability allowlist offers Run workflows on both surfaces, with the settings it also needs.
* The admin documentation names the switch by its V2 label.
"""

import ast
import copy
import re
import sys
from contextlib import nullcontext
from itertools import product
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from werkzeug.datastructures import MultiDict


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_app_settings_store_consistency import FakeCosmos  # noqa: E402
from test_support.app_stubs import import_app_module  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_workflow_orchestration_limits_settings import (  # noqa: E402
    _classic_form_normalizer,
    _settings_writer,
)


KEY = "enable_chat_orchestration_workflow_runs"
LABEL = "Run Workflows From Chat"
PROPOSALS_KEY = "enable_chat_orchestration_workflows"
ACTION_FLAG = "enable_chat_orchestration_actions"
CAPABILITIES_KEY = "chat_orchestration_enabled_capabilities"
SECTION = "chat-orchestration-capabilities-section"
HELP_ID = "chat-orchestration-workflow-runs-help"
FIELDS = import_app_module("admin_settings_fields")
REGISTRY = import_app_module("functions_orchestration_registry")


def _render_classic_pane(settings):
    environment = Environment(
        loader=FileSystemLoader(APP_ROOT / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    template = environment.get_template("admin/_panes/chat-orchestration.html")
    return template.render(
        settings=settings,
        admin_landing_tab="chat-orchestration",
        orchestration_capabilities=REGISTRY.build_capability_client_projection(REGISTRY.CAPABILITY_REGISTRY),
        orchestration_selected_capabilities=REGISTRY.all_capability_ids(),
    )


def _input_tag(markup, element_id):
    match = re.search(rf'<input[^>]*\bid="{re.escape(element_id)}"[^>]*>', markup, re.S)
    assert match, f"The Classic pane has no input with id {element_id}"
    return match.group(0)


def test_version_is_at_least_the_workflow_runs_release():
    assert_app_version_at_least("0.261.212")


def test_the_setting_is_seeded_off_under_the_key_the_registry_names():
    tree = ast.parse((APP_ROOT / "functions_settings.py").read_text(encoding="utf-8"))
    get_settings = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "get_settings"
    )
    seeded = [
        value
        for node in ast.walk(get_settings) if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values)
        if isinstance(key, ast.Constant) and key.value == KEY
    ]
    assert len(seeded) == 1
    assert isinstance(seeded[0], ast.Constant) and seeded[0].value is False
    assert REGISTRY.WORKFLOW_RUNS_SETTING == KEY
    assert REGISTRY.WORKFLOW_PROPOSALS_SETTING == PROPOSALS_KEY
    assert REGISTRY.CAPABILITY_WORKFLOW_RUN == "workflow_run"


def test_the_v2_field_is_an_off_by_default_switch_gated_on_both_prerequisites():
    field = FIELDS.get_field_definition(KEY)
    assert (field["type"], field["label"], field["default"]) == ("switch", LABEL, False)
    section_keys = [item.get("key") for item in FIELDS.ADMIN_SETTINGS_FIELDS[SECTION]]
    assert section_keys.index(KEY) == section_keys.index(PROPOSALS_KEY) + 1
    # The first capability-role field becomes the section header, which stays Enable Action Access.
    assert "role" not in field
    section = FIELDS.ADMIN_SETTINGS_FIELDS[SECTION]
    assert [item.get("key") for item in section if item.get("role") == "capability"] == [ACTION_FLAG]

    for orchestration, workflows in product((False, True), repeat=2):
        satisfied = FIELDS.field_dependencies_are_satisfied(field, {
            "enable_chat_orchestration": orchestration,
            "allow_user_workflows": workflows,
        })
        assert satisfied == (orchestration and workflows), (orchestration, workflows)
    # The proposals switch is not a prerequisite: either workflow switch can be on alone.
    assert PROPOSALS_KEY not in str(field["depends_on"])

    help_text = field["help"]
    assert "always waits for the user to run it, whatever the approval mode" in help_text
    assert "Only workflows with durable execution on can be started this way." in help_text
    assert "Off by default, because a run does whatever its workflow is set up to do" in help_text
    assert "Requires Chat Orchestration and Enable Personal Workflows." in help_text
    assert FIELDS.get_field_definition("allow_user_workflows")["label"] == "Enable Personal Workflows"


@pytest.mark.parametrize("value, expected", [(True, True), (False, False), ("on", True), ("false", False)])
def test_the_v2_update_coerces_the_switch_and_changes_nothing_else(value, expected):
    current = {KEY: not expected, PROPOSALS_KEY: False, ACTION_FLAG: True, CAPABILITIES_KEY: ["web_search"]}
    before = copy.deepcopy(current)
    normalized, errors, _warnings = FIELDS.normalize_admin_settings_updates({KEY: value}, current)
    assert errors == {}
    assert normalized == {KEY: expected}
    assert current == before


def test_the_v2_proposals_switch_leaves_the_runs_switch_alone():
    for runs in (True, False):
        current = {KEY: runs, PROPOSALS_KEY: not runs}
        normalized, errors, _warnings = FIELDS.normalize_admin_settings_updates({PROPOSALS_KEY: runs}, current)
        assert errors == {}
        assert normalized == {PROPOSALS_KEY: runs}


def test_a_v2_save_of_another_field_keeps_a_hidden_stored_value():
    current = {KEY: True, "enable_chat_orchestration": False, "allow_user_workflows": False}
    before = copy.deepcopy(current)
    normalized, errors, _warnings = FIELDS.normalize_admin_settings_updates(
        {"chat_orchestration_max_steps": 4}, current
    )
    assert errors == {}
    assert normalized == {"chat_orchestration_max_steps": 4}
    assert current == before
    assert {**current, **normalized}[KEY] is True


def test_the_classic_pane_renders_the_switch_with_its_help():
    for stored, checked in ((True, True), (False, False), (None, False)):
        markup = _render_classic_pane({} if stored is None else {KEY: stored})
        tag = _input_tag(markup, KEY)
        assert 'type="checkbox"' in tag and f'name="{KEY}"' in tag
        assert f'aria-describedby="{HELP_ID}"' in tag
        assert bool(re.search(r"\schecked\b", tag)) is checked, stored
        # Each workflow switch reflects only its own stored value.
        proposals = _input_tag(markup, PROPOSALS_KEY)
        assert not re.search(r"\schecked\b", proposals), stored

    label = re.search(rf'<label[^>]*\bfor="{KEY}"[^>]*>(.*?)</label>', markup, re.S)
    assert label and " ".join(label.group(1).split()) == LABEL
    help_text = re.search(rf'<div[^>]*\bid="{HELP_ID}"[^>]*>(.*?)</div>', markup, re.S)
    assert help_text
    text = " ".join(help_text.group(1).split())
    assert text.startswith("Off by default, because a run does whatever its workflow is set up to do")
    assert "Requires Chat Orchestration and Enable Personal Workflows." in text
    assert "always waits for the user to run it, whatever the approval mode" in text


def test_the_classic_form_reads_the_switch_like_its_neighbours():
    normalize = _classic_form_normalizer()
    options = [option["value"] for option in FIELDS.get_field_definition(CAPABILITIES_KEY)["options"]]

    for selection in ([], options):
        form = MultiDict((CAPABILITIES_KEY, value) for value in selection)
        form.add("enable_chat_orchestration", "on")
        unchecked = normalize(form, {KEY: True})
        form.add(KEY, "on")
        checked = normalize(form, {})
        # An unticked browser checkbox is absent from the post, so a stored True is turned off.
        assert unchecked[KEY] is False, selection
        assert checked[KEY] is True, selection
        assert checked[PROPOSALS_KEY] is False and unchecked[PROPOSALS_KEY] is False
        assert checked[CAPABILITIES_KEY] == unchecked[CAPABILITIES_KEY]

    proposals_only = normalize(MultiDict([(PROPOSALS_KEY, "on")]), {KEY: True})
    assert (proposals_only[PROPOSALS_KEY], proposals_only[KEY]) == (True, False)

    for value in ("true", "1", "yes"):
        values = normalize(MultiDict([(KEY, value)]), {})
        assert values[KEY] is False, value


def test_the_settings_writer_stores_only_a_real_true():
    storage = FakeCosmos()
    writer = _settings_writer(storage)
    embedding = ModuleType("functions_embedding_compatibility")
    embedding.embedding_settings_write_guard = lambda *_args, **_kwargs: nullcontext()

    with patch.dict(sys.modules, {"functions_embedding_compatibility": embedding}):
        for value, stored in ((True, True), ("true", False), (1, False), ("on", False), (None, False), (False, False)):
            update = {KEY: value}
            saved = writer(update)
            assert saved, value
            assert storage.document[KEY] is stored, value
            assert update == {KEY: value} and type(update[KEY]) is type(value)

        storage.document[KEY] = True
        saved = writer({"allow_user_workflows": True})
        assert saved
        assert storage.document[KEY] is True
        saved = writer({PROPOSALS_KEY: False})
        assert saved
        assert storage.document[KEY] is True


def test_the_capability_allowlist_offers_run_workflows_with_its_requirement():
    field = FIELDS.get_field_definition(CAPABILITIES_KEY)
    values = [option["value"] for option in field["options"]]
    run_options = [option for option in field["options"] if option["value"] == REGISTRY.CAPABILITY_WORKFLOW_RUN]
    requirement = "Run workflows also requires Run Workflows From Chat and personal workflows."
    assert run_options == [{"value": "workflow_run", "label": "Run workflows"}]
    assert values.index("workflow_run") == values.index("workflow_propose") + 1
    assert sorted(values) == sorted(REGISTRY.all_capability_ids())
    assert requirement in field["help"]

    markup = _render_classic_pane({})
    tag = _input_tag(markup, "chat_orchestration_capability_workflow_run")
    label = re.search(r'<label[^>]*\bfor="chat_orchestration_capability_workflow_run"[^>]*>(.*?)</label>', markup, re.S)
    assert f'name="{CAPABILITIES_KEY}"' in tag and 'value="workflow_run"' in tag
    # An empty stored allowlist means every capability, so the Classic box starts ticked.
    assert re.search(r"\schecked\b", tag)
    assert label and " ".join(label.group(1).split()).startswith("Run workflow ")
    assert requirement in " ".join(markup.split())


def test_the_admin_docs_name_the_switch_by_its_v2_label():
    page = (ROOT / "docs" / "admin" / "orchestration.md").read_text(encoding="utf-8")
    row = next((line for line in page.splitlines() if line.startswith("|") and f"`{KEY}`" in line), None)
    assert row, f"docs/admin/orchestration.md has no settings row for {KEY}"
    assert row.startswith(f"| {LABEL} |")
    assert "| Off |" in row
    assert "`allow_user_workflows`" in row
    assert "0.261.212" in row


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
