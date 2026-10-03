# test_workflow_orchestration_limits_settings.py
#!/usr/bin/env python3
"""
Functional test for the admin limits on workflows created from chat.
Version: 0.261.202
Implemented in: 0.261.202

This test ensures that the two limits chat orchestration workflows use are safe by default and
cannot be stored invalid:

* ``chat_orchestration_max_workflows_per_user``: default 20, a whole number from 1 to 100.
* ``chat_orchestration_min_workflow_interval_seconds``: default 3,600 (hourly), 60 to 86,400.

The V2 admin API and the settings writer reject an invalid value instead of clamping it. The
Classic admin form clamps it, like every other number on its Chat Orchestration pane. At use, a
missing value reads as its default and a corrupt stored value fails closed. Both fields appear in
the V2 schema only while Chat Orchestration is enabled. The orchestration schedule floor combines
with the general Workflow Minimum Schedule Interval, so the larger floor wins, and calendar
schedules always pass. The draft service tests cover enforcement itself.
"""

import ast
import copy
import logging
import re
import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest
from werkzeug.datastructures import MultiDict


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(ROOT / "functional_tests"))

# Configure local paths before importing the production leaf modules.
from app_settings_store import AppSettingsStore, COSMOS_METADATA_FIELDS, SETTINGS_REVISION_FIELD  # noqa: E402
from functions_workflow_definitions import WorkflowCadenceError, WorkflowPublicValidationError  # noqa: E402
from functions_workflow_limits import (  # noqa: E402
    CHAT_ORCHESTRATION_MAX_WORKFLOWS_DEFAULT,
    CHAT_ORCHESTRATION_MAX_WORKFLOWS_MAX,
    CHAT_ORCHESTRATION_MAX_WORKFLOWS_MIN,
    CHAT_ORCHESTRATION_MIN_WORKFLOW_INTERVAL_DEFAULT,
    CHAT_ORCHESTRATION_MIN_WORKFLOW_INTERVAL_MAX,
    CHAT_ORCHESTRATION_MIN_WORKFLOW_INTERVAL_MIN,
    WorkflowLoopLimitError,
    get_chat_orchestration_max_workflows_per_user,
    get_chat_orchestration_min_workflow_interval_seconds,
    get_orchestration_workflow_min_interval_seconds,
    validate_chat_orchestration_max_workflow_handoffs_per_day,
    validate_chat_orchestration_max_workflows_per_user,
    validate_chat_orchestration_min_workflow_interval_seconds,
    validate_workflow_max_loop_items,
    validate_workflow_max_repeat_iterations,
    validate_workflow_min_schedule_interval_seconds,
)
from functions_workflow_schedules import enforce_orchestration_workflow_cadence  # noqa: E402
from test_app_settings_store_consistency import FakeCosmos  # noqa: E402
from test_support.app_stubs import import_app_module  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


CAP = "chat_orchestration_max_workflows_per_user"
FLOOR = "chat_orchestration_min_workflow_interval_seconds"
GENERAL_FLOOR = "workflow_min_schedule_interval_seconds"
SECRET = "invalid-secret-value"
FIELDS = import_app_module("admin_settings_fields")
REGISTRY = import_app_module("functions_orchestration_registry")
INT_UTILS = import_app_module("admin_settings_int_utils")
CALENDARS = [
    {"kind": "calendar", "frequency": "daily", "time_of_day": "07:30", "timezone": "Europe/London"},
    {"kind": "calendar", "frequency": "weekdays", "time_of_day": "08:00", "timezone": "America/New_York"},
    {"kind": "calendar", "frequency": "weekly", "days_of_week": ["monday"], "time_of_day": "08:00",
     "timezone": "America/New_York"},
    {"kind": "calendar", "frequency": "monthly", "day_of_month": 31, "time_of_day": "23:59",
     "timezone": "Asia/Tokyo"},
]


def _production_function(filename, name, namespace):
    tree = ast.parse((APP_ROOT / filename).read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[function], type_ignores=[]), filename, "exec"), namespace)
    return namespace[name]


def _classic_form_normalizer():
    """The Classic admin form's Chat Orchestration reader, without the Azure-backed route module."""
    return _production_function("route_frontend_admin_settings.py", "normalize_chat_orchestration_settings", {
        "safe_int_with_source": INT_UTILS.safe_int_with_source,
        "all_capability_ids": REGISTRY.all_capability_ids,
        "get_field_definition": FIELDS.get_field_definition,
    })


def _settings_writer(storage):
    """The production ``update_settings`` over an in-memory settings store."""

    class ClosedError(Exception):
        pass

    namespace = {
        "copy": copy, "logging": logging, "contextmanager": contextmanager,
        "COSMOS_METADATA_FIELDS": COSMOS_METADATA_FIELDS,
        "SETTINGS_REVISION_FIELD": SETTINGS_REVISION_FIELD,
        "_get_app_settings_store": lambda: AppSettingsStore(storage),
        "validate_workflow_max_loop_items": validate_workflow_max_loop_items,
        "validate_workflow_max_repeat_iterations": validate_workflow_max_repeat_iterations,
        "validate_workflow_min_schedule_interval_seconds": validate_workflow_min_schedule_interval_seconds,
        "validate_chat_orchestration_max_workflows_per_user": validate_chat_orchestration_max_workflows_per_user,
        "validate_chat_orchestration_min_workflow_interval_seconds": (
            validate_chat_orchestration_min_workflow_interval_seconds
        ),
        "validate_chat_orchestration_max_workflow_handoffs_per_day": (
            validate_chat_orchestration_max_workflow_handoffs_per_day
        ),
        "cosmos_settings_container": storage,
        "validate_content_screening_settings": lambda *_args: None,
        "coerce_multi_model_endpoint_enablement": lambda _old, requested: requested,
        "is_tabular_processing_enabled": lambda _settings: False,
        "MatchConditions": SimpleNamespace(IfNotModified="etag"),
        "CosmosAccessConditionFailedError": ClosedError,
        "ScreeningConflictError": ClosedError,
        "ScreeningError": ClosedError,
        "AIConnectionError": ClosedError,
        "EMBEDDING_SELECTION_KEY": "embedding_model_selection",
        "log_event": lambda *_args, **_kwargs: None,
    }
    for name in (
        "normalize_group_workflow_assignment_settings",
        "normalize_agents_page_promoted_popular_settings",
        "normalize_document_access_index_required_settings",
        "normalize_inbound_mcp_settings",
        "normalize_public_workspace_display_settings",
        "normalize_key_vault_reminder_settings",
        "normalize_model_endpoint_identity_header_settings",
        "normalize_retired_orchestration_settings",
    ):
        namespace[name] = lambda _settings: None
    return _production_function("functions_settings.py", "update_settings", namespace)


def test_version_is_at_least_the_draft_service_release():
    assert_app_version_at_least("0.261.202")


def test_the_defaults_are_the_roadmap_defaults_and_the_safe_values():
    """20 workflows per user and an hourly floor; unset settings read as those defaults."""
    assert (CHAT_ORCHESTRATION_MAX_WORKFLOWS_DEFAULT, CHAT_ORCHESTRATION_MAX_WORKFLOWS_MIN,
            CHAT_ORCHESTRATION_MAX_WORKFLOWS_MAX) == (20, 1, 100)
    assert (CHAT_ORCHESTRATION_MIN_WORKFLOW_INTERVAL_DEFAULT, CHAT_ORCHESTRATION_MIN_WORKFLOW_INTERVAL_MIN,
            CHAT_ORCHESTRATION_MIN_WORKFLOW_INTERVAL_MAX) == (3600, 60, 86400)
    assert get_chat_orchestration_max_workflows_per_user({}) == 20
    assert get_chat_orchestration_min_workflow_interval_seconds({}) == 3600
    assert get_orchestration_workflow_min_interval_seconds({}) == 3600

    # get_settings seeds both keys from the same constants.
    tree = ast.parse((APP_ROOT / "functions_settings.py").read_text(encoding="utf-8"))
    get_settings = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "get_settings")
    seeded = {
        key.value: value.id
        for node in ast.walk(get_settings) if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values)
        if isinstance(key, ast.Constant) and key.value in {CAP, FLOOR} and isinstance(value, ast.Name)
    }
    assert seeded == {
        CAP: "CHAT_ORCHESTRATION_MAX_WORKFLOWS_DEFAULT",
        FLOOR: "CHAT_ORCHESTRATION_MIN_WORKFLOW_INTERVAL_DEFAULT",
    }


@pytest.mark.parametrize("validator, accepted, rejected, code, message", [
    (
        validate_chat_orchestration_max_workflows_per_user,
        (1, 20, 100, "1", " 50 ", "100"),
        (None, "", "abc", "1.5", "1e2", "\u0663", "12345678901", -1, 0, 101, 1.0, 20.5, True, False, [], {}),
        "chat_orchestration_workflow_limit_invalid",
        "Workflows Created From Chat Per User must be a whole number from 1 to 100.",
    ),
    (
        validate_chat_orchestration_min_workflow_interval_seconds,
        (60, 3600, 86400, "60", " 7200 ", "86400"),
        (None, "", "1h", "3600.0", "\u0663\u0666\u0660\u0660", -60, 0, 59, 86401, 3600.0, True, [], {}),
        "chat_orchestration_workflow_interval_invalid",
        "Minimum Schedule Interval For Workflows Created From Chat must be a whole number of seconds "
        "from 60 to 86,400.",
    ),
])
def test_values_are_validated_not_clamped(validator, accepted, rejected, code, message):
    """Whole numbers in range, or their decimal text, pass unchanged; everything else is refused."""
    for value in accepted:
        assert validator(value) == int(value)
    for value in rejected:
        with pytest.raises(WorkflowLoopLimitError) as raised:
            validator(value)
        assert raised.value.code == code
        assert raised.value.public_message == message == str(raised.value)


def test_the_getters_fail_closed_on_a_corrupt_or_missing_settings_document():
    """A stored value outside its range is a server fault, never silently corrected at use."""
    assert get_chat_orchestration_max_workflows_per_user({CAP: 5}) == 5
    assert get_chat_orchestration_min_workflow_interval_seconds({FLOOR: "600"}) == 600
    for getter, key, value, code in (
        (get_chat_orchestration_max_workflows_per_user, CAP, 0, "chat_orchestration_workflow_limit_invalid"),
        (get_chat_orchestration_max_workflows_per_user, CAP, None, "chat_orchestration_workflow_limit_invalid"),
        (get_chat_orchestration_min_workflow_interval_seconds, FLOOR, 30,
         "chat_orchestration_workflow_interval_invalid"),
        (get_orchestration_workflow_min_interval_seconds, FLOOR, True,
         "chat_orchestration_workflow_interval_invalid"),
        (get_orchestration_workflow_min_interval_seconds, GENERAL_FLOOR, 0,
         "workflow_schedule_interval_limit_invalid"),
    ):
        with pytest.raises(WorkflowLoopLimitError) as raised:
            getter({key: value})
        assert raised.value.code == code
    for getter, code in (
        (get_chat_orchestration_max_workflows_per_user, "chat_orchestration_workflow_limit_unavailable"),
        (get_chat_orchestration_min_workflow_interval_seconds, "chat_orchestration_workflow_interval_unavailable"),
    ):
        with pytest.raises(WorkflowLoopLimitError) as raised:
            getter(["not", "a", "settings", "document"])
        assert raised.value.code == code


@pytest.mark.parametrize("settings, floor", [
    ({}, 3600),
    ({GENERAL_FLOOR: 300}, 3600),
    ({FLOOR: 60}, 60),
    ({FLOOR: 60, GENERAL_FLOOR: 7200}, 7200),
    ({FLOOR: 900, GENERAL_FLOOR: 900}, 900),
    ({FLOOR: 86400, GENERAL_FLOOR: 1}, 86400),
])
def test_the_larger_of_both_floors_applies(settings, floor):
    assert get_orchestration_workflow_min_interval_seconds(settings) == floor


@pytest.mark.parametrize("schedule, floor, allowed", [
    ({"unit": "hours", "value": 1}, 3600, True),
    ({"unit": "minutes", "value": 60}, 3600, True),
    ({"unit": "minutes", "value": 59}, 3600, False),
    ({"unit": "seconds", "value": 3599}, 3600, False),
    ({"unit": "hours", "value": 2}, 7200, True),
    ({"unit": "hours", "value": 23}, 86400, False),
    ({}, 86400, True),
])
def test_the_cadence_check_refuses_only_intervals_below_the_floor(schedule, floor, allowed):
    if allowed:
        assert enforce_orchestration_workflow_cadence(schedule, floor) is schedule
        return
    with pytest.raises(WorkflowCadenceError) as raised:
        enforce_orchestration_workflow_cadence(schedule, floor)
    assert isinstance(raised.value, WorkflowPublicValidationError)
    assert raised.value.code == "cadence_below_minimum"
    assert re.fullmatch(
        r"Workflows created from chat cannot run this often\. Choose an interval of at least [0-9]+ \w+, "
        r"or a daily, weekly or monthly schedule\.",
        raised.value.public_message,
    )


@pytest.mark.parametrize("schedule", CALENDARS, ids=[schedule["frequency"] for schedule in CALENDARS])
def test_calendar_schedules_always_pass_the_cadence_check(schedule):
    """Calendar schedules repeat at most daily, so even the largest floor admits them."""
    assert enforce_orchestration_workflow_cadence(schedule, CHAT_ORCHESTRATION_MIN_WORKFLOW_INTERVAL_MAX) is schedule


@pytest.mark.parametrize("key, default, minimum, maximum", [
    (CAP, 20, 1, 100),
    (FLOOR, 3600, 60, 86400),
])
def test_the_v2_admin_fields_are_gated_limits_that_refuse_invalid_values(key, default, minimum, maximum):
    """The V2 schema offers each limit only with Chat Orchestration on, and refuses bad input."""
    field = FIELDS.get_field_definition(key)
    assert (field["type"], field["default"], field["min"], field["max"], field["step"]) == (
        "number", default, minimum, maximum, 1,
    )
    assert field["depends_on"] == {"key": "enable_chat_orchestration", "equals": True}
    assert field["group"]["id"] == "limits"
    assert key in {item["key"] for item in FIELDS.ADMIN_SETTINGS_FIELDS["chat-orchestration-limits-section"]}
    assert FIELDS.field_dependencies_are_satisfied(field, {"enable_chat_orchestration": True}) is True
    assert FIELDS.field_dependencies_are_satisfied(field, {"enable_chat_orchestration": False}) is False

    current = {key: minimum + 1}
    normalized, errors, _warnings = FIELDS.normalize_admin_settings_updates({"chat_orchestration_max_steps": 4}, current)
    assert errors == {} and key not in normalized and current == {key: minimum + 1}
    normalized, errors, _warnings = FIELDS.normalize_admin_settings_updates({key: str(maximum)}, current)
    assert errors == {} and normalized == {key: maximum}
    for value in (minimum - 1, maximum + 1, True, 25.5, "", SECRET):
        normalized, errors, _warnings = FIELDS.normalize_admin_settings_updates({key: value}, current)
        assert key in errors and key not in normalized
        assert SECRET not in errors[key]


def test_the_classic_form_clamps_like_the_rest_of_its_pane():
    """The Classic Chat Orchestration pane clamps every number it reads; these two follow suit."""
    normalize = _classic_form_normalizer()

    def read(form, settings=None):
        values = normalize(MultiDict(form), settings or {})
        return values[CAP], values[FLOOR]

    assert read([]) == (20, 3600)
    assert read([], {CAP: 7, FLOOR: 900}) == (7, 900)
    assert read([(CAP, "12"), (FLOOR, "7200")]) == (12, 7200)
    assert read([(CAP, "0"), (FLOOR, "30")]) == (1, 60)
    assert read([(CAP, "500"), (FLOOR, "999999")]) == (100, 86400)
    assert read([(CAP, SECRET), (FLOOR, SECRET)], {CAP: 7, FLOOR: 900}) == (7, 900)


def test_the_classic_pane_bounds_match_the_v2_schema():
    """The template inputs and the Classic clamps use the same bounds and defaults as the schema."""
    pane = (APP_ROOT / "templates" / "admin" / "_panes" / "chat-orchestration.html").read_text(encoding="utf-8")
    tree = ast.parse((APP_ROOT / "route_frontend_admin_settings.py").read_text(encoding="utf-8"))
    clamps = {
        node.args[0].value: tuple(argument.value for argument in node.args[1:])
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_clamped"
        and node.args and isinstance(node.args[0], ast.Constant)
    }
    for key in (CAP, FLOOR):
        field = FIELDS.get_field_definition(key)
        assert clamps[key] == (field["default"], field["min"], field["max"])
        tag = re.search(rf'<input[^>]*\bname="{key}"[^>]*>', pane, re.S)
        assert tag, f"The Classic pane has no input for {key}"
        assert f'min="{field["min"]}"' in tag.group(0) and f'max="{field["max"]}"' in tag.group(0)
        assert f"else {field['default']} }}}}" in tag.group(0)


def test_the_settings_writer_validates_before_storing_and_keeps_absent_values():
    """``update_settings`` refuses an invalid limit before any write and stores valid text as a number."""
    storage = FakeCosmos()
    storage.document[CAP] = 15
    storage.document[FLOOR] = 1800
    writer = _settings_writer(storage)

    for update in ({CAP: 0}, {CAP: "101"}, {FLOOR: 59}, {FLOOR: True}, {CAP: 10, FLOOR: SECRET}):
        with pytest.raises(WorkflowLoopLimitError) as raised:
            writer(dict(update))
        assert SECRET not in raised.value.public_message
    assert storage.tokens == [] and not storage.writes

    embedding = ModuleType("functions_embedding_compatibility")
    embedding.embedding_settings_write_guard = lambda *_args, **_kwargs: nullcontext()
    with patch.dict(sys.modules, {"functions_embedding_compatibility": embedding}):
        assert writer({"allow_user_workflows": True})
        assert (storage.document[CAP], storage.document[FLOOR]) == (15, 1800)
        update = {CAP: "25", FLOOR: " 7200 "}
        assert writer(update)
        assert (storage.document[CAP], storage.document[FLOOR]) == (25, 7200)
        assert update == {CAP: "25", FLOOR: " 7200 "}


def test_the_admin_docs_describe_both_limits():
    """The Chat Orchestration admin page documents each limit with its default and key."""
    page = (ROOT / "docs" / "admin" / "orchestration.md").read_text(encoding="utf-8")
    for key, default in ((CAP, "20"), (FLOOR, "3600")):
        row = next((line for line in page.splitlines() if line.startswith("|") and f"`{key}`" in line), None)
        assert row, f"docs/admin/orchestration.md has no settings row for {key}"
        assert f"| {default} |" in row
