#!/usr/bin/env python3
# test_v2_admin_data_lifecycle_parity.py
"""
Functional test pinning V1/V2 parity for the Admin Settings Data Lifecycle group.
Version: 0.261.272
Implemented in: 0.261.272

Before this group was described, the V2 admin surface drew Retention Policy, Document
Classification and Conversation Archiving through its ``enable_*`` fallback scan: five
bare switches with their storage keys printed beneath them. Everything else the
server-rendered panes offer was missing -- six organization defaults, the run hour,
the last and next run, Run now, Force push, and the classification categories.

This test keeps the group described the way the other parity tests do: every form
field the classic panes submit must be claimed by the schema, the schema must not
claim a field classic does not have, and selects must offer the same values.

It also pins the behaviour the schema adds, because each piece guards against a
failure nobody would see until data was deleted at the wrong time:

  - the run hour is stored as an int (a string stops every retention run);
  - saving a workspace type or the hour reschedules the next run exactly as classic
    does, and nothing else moves it;
  - classification categories are refused with a message when a label is missing,
    repeated or too long, or a colour is not a hex value.

The TypeScript half -- held states, summaries, timestamps, and the rendered controls --
is in test_v2_admin_data_lifecycle_logic.ts, which this file bundles and runs.
"""

import ast
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
PANES_DIR = APP_ROOT / "templates" / "admin" / "_panes"
SETTINGS_MODULE = APP_ROOT / "functions_settings.py"
RETENTION_ROUTES = APP_ROOT / "route_backend_retention_policy.py"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_ADMIN = V2_DIR / "src" / "components" / "admin"
PAGE_TSX = V2_DIR / "src" / "pages" / "AdminSettingsPage.tsx"
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_admin_data_lifecycle_logic.ts"

DATA_LIFECYCLE_GROUP_ID = "data-lifecycle"
DATA_LIFECYCLE_PANES = {
    "retention": ("retention-policy-section",),
    "classification": ("document-classification-section",),
    "archiving": ("conversation-archiving-section",),
}

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")
OPTION_RE = re.compile(r'<option value="([^"]*)"')
SELECT_BLOCK_RE = re.compile(
    r'<select[^>]*\sname="(?P<name>[^"]+)"(?P<body>.*?)</select>',
    re.DOTALL,
)

fields_module = import_app_module("admin_settings_fields")


def read_pane(pane_id):
    """Return the raw markup for one Admin Settings pane."""
    pane_path = PANES_DIR / f"{pane_id}.html"
    assert pane_path.is_file(), f"Missing Admin Settings pane: {pane_path}"
    return pane_path.read_text(encoding="utf-8")


def collect_pane_field_names(markup):
    """Return literal form field names submitted by a pane."""
    return {name for name in FIELD_NAME_RE.findall(markup) if not JINJA_RE.search(name)}


def data_lifecycle_sections():
    return {section for sections in DATA_LIFECYCLE_PANES.values() for section in sections}


def declared_fields():
    """Return ``key -> field`` for the Data Lifecycle declarations."""
    sections = data_lifecycle_sections()
    return {
        field["key"]: field
        for section_id, field in fields_module.iter_fields()
        if section_id in sections and field.get("key")
    }


def read_application_default(key):
    """Read one literal default out of functions_settings.py without importing it."""
    tree = ast.parse(SETTINGS_MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for dict_key, dict_value in zip(node.keys, node.values):
            if isinstance(dict_key, ast.Constant) and dict_key.value == key:
                return ast.literal_eval(dict_value)
    raise AssertionError(f"No default for {key!r} in functions_settings.py")


def classic_next_run(hour, now):
    """The rule route_frontend_admin_settings.py applies on every classic save."""
    next_run = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run = next_run + timedelta(days=1)
    return next_run.isoformat()


def test_data_lifecycle_panes_match_navigation():
    """The panes this test reads must be the ones ADMIN_NAV puts in the group."""
    print("Testing Data Lifecycle pane list against ADMIN_NAV...")

    assert_app_version_at_least("0.261.272")

    group = next((g for g in ADMIN_NAV if g["id"] == DATA_LIFECYCLE_GROUP_ID), None)
    assert group, "ADMIN_NAV no longer defines a 'data-lifecycle' group."

    nav_tabs = {tab["id"]: tuple(s["id"] for s in tab["sections"]) for tab in group["tabs"]}
    assert nav_tabs == DATA_LIFECYCLE_PANES, (
        "The Data Lifecycle tabs or sections changed. Update DATA_LIFECYCLE_PANES and the "
        f"schema together.\n  ADMIN_NAV: {nav_tabs}\n  test: {DATA_LIFECYCLE_PANES}"
    )

    missing_sections = sorted(data_lifecycle_sections() - set(fields_module.ADMIN_SETTINGS_FIELDS))
    assert not missing_sections, (
        "These Data Lifecycle sections have no schema entry, so V2 falls back to bare "
        f"switches for them: {missing_sections}"
    )

    print(f"  {len(nav_tabs)} tab(s) match ADMIN_NAV and every section is described.")
    return True


def test_every_v1_field_is_claimed_by_the_schema():
    """A classic field with no V2 equivalent is invisible in the new UI."""
    print("\nTesting that every classic Data Lifecycle field is claimed by the schema...")

    claimed = fields_module.get_legacy_field_names()
    documented = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)

    unclaimed = {}
    total = 0
    for pane_id in DATA_LIFECYCLE_PANES:
        names = collect_pane_field_names(read_pane(pane_id))
        total += len(names)
        missing = sorted(names - claimed - documented)
        if missing:
            unclaimed[pane_id] = missing

    assert not unclaimed, (
        "These fields exist in the classic Data Lifecycle panes but are not described in "
        "admin_settings_fields.py, so they cannot appear in V2:\n"
        + "\n".join(f"  {pane}: {', '.join(names)}" for pane, names in unclaimed.items())
    )
    assert total >= 12, f"Only {total} classic field(s) were found; the extraction likely broke."

    print(f"  All {total} classic Data Lifecycle field(s) are claimed by the schema.")
    return True


def test_schema_does_not_invent_data_lifecycle_fields():
    """A schema key with no classic counterpart would save a setting nothing reads."""
    print("\nTesting that the schema does not invent Data Lifecycle fields...")

    v1_names = set()
    for pane_id in DATA_LIFECYCLE_PANES:
        v1_names |= collect_pane_field_names(read_pane(pane_id))

    invented = []
    for key in declared_fields():
        legacy = fields_module.LEGACY_FIELD_NAMES.get(key, [key])
        if not any(name in v1_names for name in legacy):
            invented.append(key)

    assert not invented, (
        "These Data Lifecycle schema fields have no classic counterpart:\n  "
        + "\n  ".join(invented)
    )

    print(f"  All {len(declared_fields())} declared key(s) map back to a classic field.")
    return True


def test_selects_offer_the_classic_values():
    """The six defaults and the run hour must offer exactly what classic offers."""
    print("\nTesting select values against the classic Retention pane...")

    markup = read_pane("retention")
    v1_options = {
        match.group("name"): OPTION_RE.findall(match.group("body"))
        for match in SELECT_BLOCK_RE.finditer(markup)
    }

    fields = declared_fields()
    compared = 0
    for key, field in fields.items():
        if field.get("type") != "select":
            continue
        schema_values = [option["value"] for option in field["options"]]
        assert schema_values == v1_options.get(key), (
            f"{key} offers different values in each interface:\n"
            f"  schema: {schema_values}\n  classic: {v1_options.get(key)}"
        )
        compared += 1
    assert compared == 6, f"Expected six retention default selects, compared {compared}."

    # The classic hour select is a Jinja loop rather than literal options.
    assert "{% for hour in range(24) %}" in markup, "The classic run-hour loop changed."
    assert (fields_module.RETENTION_EXECUTION_HOUR_MIN, fields_module.RETENTION_EXECUTION_HOUR_MAX) == (0, 23)
    schedule_source = (V2_ADMIN / "RetentionSchedule.tsx").read_text(encoding="utf-8")
    assert "Array.from({ length: 24 }" in schedule_source, (
        "The V2 run-hour select should offer all 24 hours, as classic does."
    )

    print(f"  {compared} default select(s) and the 24-hour run time match classic.")
    return True


def test_defaults_mirror_the_application():
    """What V2 shows for a missing key must be what the application applies."""
    print("\nTesting declared defaults against functions_settings.py...")

    fields = declared_fields()
    for key, field in fields.items():
        if "default" not in field:
            continue
        expected = read_application_default(key)
        assert field["default"] == expected, (
            f"{key}: schema default {field['default']!r} != application {expected!r}"
        )
    assert fields["retention_policy_execution_hour"]["default"] == 2
    assert isinstance(fields["retention_policy_execution_hour"]["default"], int)

    print(f"  All {sum(1 for f in fields.values() if 'default' in f)} default(s) match.")
    return True


def test_execution_hour_is_stored_as_an_int():
    """execute_retention_policy passes the hour to datetime.replace, which needs an int."""
    print("\nTesting run-hour normalization...")

    normalize = fields_module.normalize_admin_settings_updates
    for submitted, expected in ((5, 5), ("7", 7), (" 0 ", 0), (23, 23), (6.0, 6)):
        normalized, errors, _ = normalize({"retention_policy_execution_hour": submitted}, {})
        assert not errors, errors
        assert normalized["retention_policy_execution_hour"] == expected
        assert type(normalized["retention_policy_execution_hour"]) is int

    for refused in (24, -1, "noon", True, 2.5, None, "12345"):
        normalized, errors, _ = normalize({"retention_policy_execution_hour": refused}, {})
        assert "retention_policy_execution_hour" in errors, refused
        assert "retention_policy_execution_hour" not in normalized

    print("  The hour is saved as an int and anything outside 0-23 is refused.")
    return True


def test_classification_categories_are_validated():
    """A category list that would break documents or badges is refused with a reason."""
    print("\nTesting classification category normalization...")

    normalize = fields_module.normalize_admin_settings_updates
    key = "document_classification_categories"

    normalized, errors, _ = normalize(
        {key: [{"label": "  Confidential ", "color": "#AABBCC", "extra": "dropped"}]}, {}
    )
    assert not errors, errors
    assert normalized[key] == [{"label": "Confidential", "color": "#aabbcc"}]

    normalized, errors, _ = normalize({key: []}, {})
    assert not errors and normalized[key] == []

    refusals = {
        "not a list": {"label": "A", "color": "#000000"},
        "missing label": [{"label": "  ", "color": "#000000"}],
        "non-string label": [{"label": 7, "color": "#000000"}],
        "bad colour": [{"label": "A", "color": "red"}],
        "short colour": [{"label": "A", "color": "#fff"}],
        "too long": [{"label": "x" * 81, "color": "#000000"}],
        "duplicate": [
            {"label": "Internal", "color": "#000000"},
            {"label": "INTERNAL", "color": "#ffffff"},
        ],
        "not an object": ["Internal"],
    }
    for case, value in refusals.items():
        normalized, errors, _ = normalize({key: value}, {})
        assert key in errors, f"{case} was accepted"
        assert key not in normalized

    _normalized, errors, _ = normalize({key: refusals["duplicate"]}, {})
    assert "Categories 1 and 2" in errors[key], errors[key]

    print("  Labels are trimmed, colours lower-cased, and bad lists refused with a reason.")
    return True


def test_saving_a_scope_or_hour_reschedules_the_next_run():
    """Classic recomputes the next run on save; V2 has to as well, and only then."""
    print("\nTesting next-run rescheduling...")

    apply_schedule = fields_module._apply_retention_schedule
    at_one = datetime(2026, 10, 6, 1, 0, tzinfo=timezone.utc)
    at_six = datetime(2026, 10, 6, 6, 0, tzinfo=timezone.utc)

    # Switching a type on schedules the next occurrence of the stored hour.
    normalized = {"enable_retention_policy_group": True}
    apply_schedule(normalized, {"retention_policy_execution_hour": 2}, now=at_one)
    assert normalized["retention_policy_next_run"] == classic_next_run(2, at_one)
    assert normalized["retention_policy_next_run"] == "2026-10-06T02:00:00+00:00"

    # A new hour that has already passed today moves to tomorrow.
    normalized = {"retention_policy_execution_hour": 5}
    apply_schedule(
        normalized,
        {"enable_retention_policy_personal": True, "retention_policy_execution_hour": 2,
         "retention_policy_next_run": "2026-10-07T02:00:00+00:00"},
        now=at_six,
    )
    assert normalized["retention_policy_next_run"] == "2026-10-07T05:00:00+00:00"

    # Switching the last type off clears the schedule.
    normalized = {"enable_retention_policy_public": False}
    apply_schedule(
        normalized,
        {"enable_retention_policy_public": True, "retention_policy_next_run": "2026-10-07T02:00:00+00:00"},
        now=at_six,
    )
    assert normalized["retention_policy_next_run"] is None

    # An unrelated save, or an unchanged switch, leaves a pending run alone.
    stored = {
        "enable_retention_policy_group": True,
        "retention_policy_execution_hour": 2,
        "retention_policy_next_run": "2026-10-06T02:00:00+00:00",
    }
    for untouched in (
        {"default_retention_document_group": "30"},
        {"enable_retention_policy_group": True},
    ):
        apply_schedule(untouched, stored, now=at_six)
        assert "retention_policy_next_run" not in untouched, untouched

    # A missing next run is filled in whenever a schedule key is saved.
    normalized = {"enable_retention_policy_group": True}
    apply_schedule(normalized, {**stored, "retention_policy_next_run": None}, now=at_six)
    assert normalized["retention_policy_next_run"] == "2026-10-07T02:00:00+00:00"

    # A hand-edited hour falls back to the default rather than failing the save.
    normalized = {"enable_retention_policy_personal": True}
    apply_schedule(normalized, {"retention_policy_execution_hour": "late"}, now=at_one)
    assert normalized["retention_policy_next_run"] == "2026-10-06T02:00:00+00:00"

    # Wired into the normalizer, and skipped when the save is refused.
    normalized, errors, _ = fields_module.normalize_admin_settings_updates(
        {"enable_retention_policy_group": True}, {"retention_policy_execution_hour": 2}
    )
    assert not errors and "retention_policy_next_run" in normalized
    normalized, errors, _ = fields_module.normalize_admin_settings_updates(
        {"enable_retention_policy_group": True, "retention_policy_execution_hour": 99}, {}
    )
    assert errors and "retention_policy_next_run" not in normalized

    for hour in (0, 2, 13, 23):
        for now in (at_one, at_six, datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc)):
            assert fields_module.compute_retention_next_run(hour, now) == classic_next_run(hour, now)

    print("  The next run moves exactly when classic would move it.")
    return True


def test_v2_controls_use_the_existing_admin_routes():
    """Run now, reset and the schedule readout must reach admin-only routes that exist."""
    print("\nTesting the routes the Data Lifecycle controls call...")

    routes = RETENTION_ROUTES.read_text(encoding="utf-8")
    expected = {
        ("/api/admin/retention-policy/execute", "POST", "RetentionOperations.tsx"),
        ("/api/admin/retention-policy/force-push", "POST", "RetentionOperations.tsx"),
        ("/api/admin/retention-policy/settings", "GET", "RetentionSchedule.tsx"),
    }
    for path, method, component in expected:
        route = re.search(
            rf"@bp\.route\('{re.escape(path)}', methods=\['{method}'\]\)(.*?)\n    def ",
            routes,
            re.DOTALL,
        )
        assert route, f"{method} {path} is not registered"
        for decorator in ("@swagger_route(", "@login_required", "@admin_required"):
            assert decorator in route.group(1), f"{method} {path} is missing {decorator}"
        assert path in (V2_ADMIN / component).read_text(encoding="utf-8"), (
            f"{component} no longer calls {path}"
        )

    page = PAGE_TSX.read_text(encoding="utf-8")
    for branch in (
        "case 'retention-schedule':",
        "case 'retention-reset-defaults':",
        "case 'retention-run-now':",
        "case 'document-classification-categories':",
    ):
        assert branch in page, f"AdminSettingsPage.tsx has no {branch}"
    assert "onStoredSettingsChange={mergeStoredSettings}" in page, (
        "A run's new last and next run must reach the page's settings."
    )

    operations = (V2_ADMIN / "RetentionOperations.tsx").read_text(encoding="utf-8")
    assert "savedEnabledScopes(settings)" in operations, (
        "Run now and reset must offer only the types switched on in the saved settings."
    )
    assert "unsavedKeys(draft, RETENTION_RUN_KEYS)" in operations
    assert "unsavedKeys(draft, RETENTION_SETTING_KEYS)" in operations
    assert "dangerouslySetInnerHTML" not in operations

    print("  Every control calls a registered, admin-only route.")
    return True


def test_the_typescript_logic_checks_pass():
    """Execute the behavioural half, skipping when the front-end toolchain is absent."""
    print("\nTesting Data Lifecycle logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return True

    assert LOGIC_CHECK_TS.exists(), "The TypeScript logic checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where
    # node can resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-admin-data-lifecycle-check.mjs"
    try:
        subprocess.run(
            [
                "npx",
                "esbuild",
                str(LOGIC_CHECK_TS),
                "--bundle",
                "--platform=node",
                "--format=esm",
                "--packages=external",
                "--jsx=automatic",
                "--define:import.meta.env={}",
                f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(V2_DIR),
            check=True,
            shell=(sys.platform == "win32"),
        )
        result = subprocess.run(
            ["node", str(bundle)],
            cwd=str(V2_DIR),
            capture_output=True,
            text=True,
            shell=(sys.platform == "win32"),
        )
    finally:
        if bundle.exists():
            bundle.unlink()

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript logic checks failed")

    passed = result.stdout.count("  ok  ")
    print(f"  ok  {passed} TypeScript logic checks passed")
    return True


if __name__ == "__main__":
    tests = [
        test_data_lifecycle_panes_match_navigation,
        test_every_v1_field_is_claimed_by_the_schema,
        test_schema_does_not_invent_data_lifecycle_fields,
        test_selects_offer_the_classic_values,
        test_defaults_mirror_the_application,
        test_execution_hour_is_stored_as_an_int,
        test_classification_categories_are_validated,
        test_saving_a_scope_or_hour_reschedules_the_next_run,
        test_v2_controls_use_the_existing_admin_routes,
        test_the_typescript_logic_checks_pass,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
