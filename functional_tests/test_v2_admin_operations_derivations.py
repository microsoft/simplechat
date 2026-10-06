#!/usr/bin/env python3
# test_v2_admin_operations_derivations.py
"""
Functional test for the values the Operations settings calculate on save.
Version: 0.261.260
Implemented in: 0.261.260

Three Operations values are worked out by the server rather than typed: the next
scheduled Control Center refresh and each log's automatic turnoff time. The
server-rendered form calculated them on every save; the V2 settings PATCH did not,
so a schedule or timer edited in V2 would have been stored and then ignored. Both
surfaces, and the background checker that switches logs off, now share
``functions_logging_timers`` and ``functions_control_center_schedule``.

This test executes those rules through the V2 normalizer, pins that the classic
form and the checker call the same helpers, checks that turnoff times are stored in
UTC while ones written before that still expire when they were meant to, and runs
the browser-side checks in ``test_v2_admin_operations_logic.ts``, which hold the
readouts to the same answers.
"""

import ast
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Dict
from zoneinfo import ZoneInfo

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import APP_ROOT, import_app_module
from test_support.versioning import assert_app_version_at_least

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# Both modules are pure by design, so they are imported as shipped.
from functions_control_center_schedule import (  # noqa: E402
    resolve_control_center_auto_refresh_settings,
)
from functions_logging_timers import (  # noqa: E402
    is_logging_turnoff_due,
    parse_logging_turnoff_time,
    resolve_logging_timer_settings,
)


REPO_ROOT = APP_ROOT.parents[1]
V2_DIR = REPO_ROOT / "application" / "v2_ui"
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_admin_operations_logic.ts"

fields_module = import_app_module("admin_settings_fields")
normalize = fields_module.normalize_admin_settings_updates

TIMER_KEYS = (
    "debug_logging_timer_enabled",
    "debug_timer_value",
    "debug_timer_unit",
    "debug_logging_turnoff_time",
    "file_processing_logs_timer_enabled",
    "file_timer_value",
    "file_timer_unit",
    "file_processing_logs_turnoff_time",
)
SCHEDULE_KEYS = (
    "control_center_auto_refresh_time",
    "control_center_auto_refresh_hour",
    "control_center_auto_refresh_minute",
    "control_center_auto_refresh_timezone",
    "control_center_auto_refresh_next_run",
)


def stored_settings(**overrides):
    """A settings document with both timers and the schedule at their defaults."""
    settings = {
        "enable_debug_logging": False,
        "debug_logging_timer_enabled": False,
        "debug_timer_value": 1,
        "debug_timer_unit": "hours",
        "debug_logging_turnoff_time": None,
        "enable_file_processing_logs": True,
        "file_processing_logs_timer_enabled": False,
        "file_timer_value": 1,
        "file_timer_unit": "hours",
        "file_processing_logs_turnoff_time": None,
        "control_center_auto_refresh_enabled": True,
        "control_center_auto_refresh_time": "02:00",
        "control_center_auto_refresh_hour": 2,
        "control_center_auto_refresh_minute": 0,
        "control_center_auto_refresh_timezone": "America/New_York",
        "control_center_auto_refresh_next_run": "2026-10-07T06:00:00+00:00",
    }
    settings.update(overrides)
    return settings


def save(updates, current):
    normalized, errors, warnings = normalize(updates, current)
    assert not errors, errors
    return normalized, warnings


def test_switching_debug_logging_on_starts_a_utc_timer():
    """The V2 save works out the turnoff time, and stores it as an exact instant."""
    print("Testing that enabling a timed log sets a UTC turnoff...")

    assert_app_version_at_least("0.261.260")

    before = datetime.now(timezone.utc)
    normalized, _ = save(
        {
            "enable_debug_logging": True,
            "debug_logging_timer_enabled": True,
            "debug_timer_value": 2,
            "debug_timer_unit": "hours",
        },
        stored_settings(),
    )
    after = datetime.now(timezone.utc)

    stored = normalized["debug_logging_turnoff_time"]
    assert stored.endswith("+00:00"), f"Turnoff time is not stored in UTC: {stored}"
    turnoff = datetime.fromisoformat(stored)
    assert before + timedelta(hours=2) <= turnoff <= after + timedelta(hours=2), turnoff
    print("  The turnoff time is two hours from the save, in UTC.")


def test_an_unrelated_save_leaves_timers_and_the_schedule_alone():
    """Saving one switch must not restart a timer or move a scheduled refresh."""
    print("\nTesting that unrelated saves calculate nothing...")

    normalized, _ = save({"app_title": "Renamed"}, stored_settings())
    calculated = [key for key in TIMER_KEYS + SCHEDULE_KEYS if key in normalized]
    assert not calculated, f"An unrelated save wrote: {calculated}"
    print("  Nothing is recalculated.")


def test_resaving_an_unchanged_timer_keeps_its_turnoff():
    """Only a timer change restarts the clock; legacy values keep their instant."""
    print("\nTesting that an unchanged timer keeps its turnoff...")

    utc_turnoff = "2026-10-07T09:00:00+00:00"
    current = stored_settings(
        enable_debug_logging=True,
        debug_logging_timer_enabled=True,
        debug_timer_value=3,
        debug_timer_unit="days",
        debug_logging_turnoff_time=utc_turnoff,
    )
    normalized, _ = save({"enable_debug_logging": True}, current)
    assert normalized["debug_logging_turnoff_time"] == utc_turnoff

    # Written before turnoff times were kept in UTC: server-local, no offset. The
    # instant survives the save, now with its offset made explicit.
    legacy = (datetime.now() + timedelta(days=2)).replace(microsecond=0).isoformat()
    normalized, _ = save(
        {"enable_debug_logging": True},
        {**current, "debug_logging_turnoff_time": legacy},
    )
    kept = parse_logging_turnoff_time(normalized["debug_logging_turnoff_time"])
    assert kept == parse_logging_turnoff_time(legacy), (kept, legacy)
    assert normalized["debug_logging_turnoff_time"].endswith("+00:00")
    print("  UTC and legacy turnoff times both survive a save unchanged.")


def test_switching_a_log_off_clears_its_turnoff():
    """A turnoff time for a log that is off would switch it off again later."""
    print("\nTesting that switching a log off clears its turnoff...")

    current = stored_settings(
        file_processing_logs_timer_enabled=True,
        file_processing_logs_turnoff_time="2026-10-07T09:00:00+00:00",
    )
    normalized, _ = save({"enable_file_processing_logs": False}, current)
    assert normalized["file_processing_logs_turnoff_time"] is None
    assert normalized["file_processing_logs_timer_enabled"] is True, (
        "The timer preference survives, so switching the log back on restarts it."
    )
    print("  The turnoff is cleared and the timer preference is kept.")


def test_a_unit_change_brings_the_duration_into_range_and_says_so():
    """Ninety minutes switched to hours is not a ninety-hour timer."""
    print("\nTesting the per-unit duration limit...")

    current = stored_settings(
        enable_debug_logging=True,
        debug_logging_timer_enabled=True,
        debug_timer_value=90,
        debug_timer_unit="minutes",
        debug_logging_turnoff_time="2026-10-07T09:00:00+00:00",
    )
    normalized, warnings = save({"debug_timer_unit": "hours"}, current)
    assert normalized["debug_timer_value"] == 24, normalized
    assert "debug_timer_value" in warnings and "24" in warnings["debug_timer_value"], warnings
    turnoff = datetime.fromisoformat(normalized["debug_logging_turnoff_time"])
    assert turnoff > datetime.now(timezone.utc) + timedelta(hours=23), (
        "A changed unit restarts the clock with the clamped duration."
    )
    print("  The duration is lowered to 24 hours with a warning.")


def test_refresh_time_and_timezone_are_validated_rather_than_replaced():
    """The shared normalizer quietly substitutes defaults; a typed value is refused."""
    print("\nTesting refresh time and timezone validation...")

    for bad_time in ("25:00", "2am", "", "02:60"):
        _normalized, errors, _ = normalize({"control_center_auto_refresh_time": bad_time}, stored_settings())
        assert "control_center_auto_refresh_time" in errors, bad_time
    for bad_zone in ("Mars/Olympus", "", "../etc/passwd"):
        _normalized, errors, _ = normalize({"control_center_auto_refresh_timezone": bad_zone}, stored_settings())
        assert "control_center_auto_refresh_timezone" in errors, bad_zone

    normalized, _ = save({"control_center_auto_refresh_time": "03:30:00"}, stored_settings())
    assert normalized["control_center_auto_refresh_time"] == "03:30", "Seconds are dropped."
    print("  Bad values are refused; seconds are dropped from good ones.")


def test_a_schedule_change_moves_the_next_run():
    """The next run follows the new zone's clock and is stored in UTC."""
    print("\nTesting that a schedule change recalculates the next run...")

    before = datetime.now(timezone.utc)
    normalized, _ = save(
        {
            "control_center_auto_refresh_time": "03:30",
            "control_center_auto_refresh_timezone": "Europe/Paris",
        },
        stored_settings(),
    )
    assert normalized["control_center_auto_refresh_hour"] == 3
    assert normalized["control_center_auto_refresh_minute"] == 30
    next_run = datetime.fromisoformat(normalized["control_center_auto_refresh_next_run"])
    assert next_run.utcoffset() == timedelta(0), "The next run is not stored in UTC."
    local = next_run.astimezone(ZoneInfo("Europe/Paris"))
    assert (local.hour, local.minute) == (3, 30), local
    assert before < next_run <= before + timedelta(days=1, minutes=1), next_run
    print(f"  Next run {next_run.isoformat()} is 03:30 in Paris.")


def test_an_unchanged_schedule_keeps_its_next_run_and_off_clears_it():
    """Re-saving keeps the stored run; switching the refresh off clears it."""
    print("\nTesting schedule preservation and clearing...")

    current = stored_settings()
    normalized, _ = save({"control_center_auto_refresh_enabled": True}, current)
    assert normalized["control_center_auto_refresh_next_run"] == current["control_center_auto_refresh_next_run"]

    normalized, _ = save({"control_center_auto_refresh_enabled": False}, current)
    assert normalized["control_center_auto_refresh_next_run"] is None
    print("  An unchanged schedule keeps its run; a disabled one has none.")


def test_the_shared_helpers_apply_the_classic_rules():
    """The rules the classic form always applied, now in one place."""
    print("\nTesting the shared timer and schedule helpers directly...")

    now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    existing = {
        "enable_debug_logging": True,
        "debug_logging_timer_enabled": True,
        "debug_timer_value": 1,
        "debug_timer_unit": "weeks",
        "debug_logging_turnoff_time": "2026-10-10T00:00:00+00:00",
    }
    same = resolve_logging_timer_settings("debug", dict(existing), existing, now=now)
    assert same["debug_logging_turnoff_time"] == "2026-10-10T00:00:00+00:00"

    changed = resolve_logging_timer_settings("debug", {**existing, "debug_timer_value": 2}, existing, now=now)
    assert changed["debug_logging_turnoff_time"] == "2026-10-20T12:00:00+00:00"

    unreadable = resolve_logging_timer_settings(
        "debug", dict(existing), {**existing, "debug_logging_turnoff_time": "not a time"}, now=now,
    )
    assert unreadable["debug_logging_turnoff_time"] == "2026-10-13T12:00:00+00:00", (
        "An unreadable stored time is replaced, since the checker could never act on it."
    )

    schedule = resolve_control_center_auto_refresh_settings(
        {"control_center_auto_refresh_time": "02:00"},
        {"control_center_auto_refresh_enabled": True, "control_center_auto_refresh_next_run": None},
        current_time=datetime(2026, 1, 15, 6, 30, tzinfo=timezone.utc),
    )
    assert schedule["control_center_auto_refresh_next_run"] == "2026-01-15T07:00:00+00:00"
    print("  Preserve, recalculate and replace-unreadable all behave as the classic form did.")


def test_the_checker_reads_utc_and_legacy_turnoffs():
    """A timer set before the upgrade still ends; a UTC one ends on time."""
    print("\nTesting turnoff due checks...")

    now = datetime.now(timezone.utc)
    assert is_logging_turnoff_due((now - timedelta(minutes=1)).isoformat(), now=now)
    assert not is_logging_turnoff_due((now + timedelta(minutes=1)).isoformat(), now=now)

    local_now = datetime.now()
    assert is_logging_turnoff_due((local_now - timedelta(minutes=1)).isoformat())
    assert not is_logging_turnoff_due((local_now + timedelta(minutes=5)).isoformat())

    for unusable in (None, "", "garbage", 42):
        assert not is_logging_turnoff_due(unusable), unusable
    print("  UTC and legacy server-local times are both honoured.")


def test_every_writer_uses_the_shared_helpers():
    """A third copy of the rules is how the two surfaces drifted in the first place."""
    print("\nTesting that the classic form, the PATCH and the checker share the rules...")

    classic = (APP_ROOT / "route_frontend_admin_settings.py").read_text(encoding="utf-8")
    checker = (APP_ROOT / "background_tasks.py").read_text(encoding="utf-8")
    schema = (APP_ROOT / "admin_settings_fields.py").read_text(encoding="utf-8")

    assert classic.count("resolve_logging_timer_settings(") == 2, "The classic form has its own timer rules."
    assert "resolve_control_center_auto_refresh_settings(" in classic
    assert "timer_limits = {" not in classic, "The classic form still carries a private copy of the limits."
    assert "is_logging_turnoff_due(" in checker
    assert "datetime.fromisoformat(turnoff_time)" not in checker, "The checker still parses times itself."
    assert "resolve_logging_timer_settings(kind, incoming, current_settings)" in schema
    assert "resolve_control_center_auto_refresh_settings(incoming, current_settings)" in schema
    print("  All three writers call the shared helpers.")


def _load_function(path, name, namespace):
    """Execute one function from an application module, without its imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name
    )
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


def test_runtime_state_reports_how_the_process_started():
    """The readouts compare saved settings with this, so it must be accurate."""
    print("\nTesting the runtime state accessors...")

    root_logger = logging.getLogger()
    for environ, configured, app_logger, expected in (
        ({}, False, None, (False, False, False)),
        ({"APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=x"}, True, root_logger, (True, True, True)),
        ({"APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=x"}, True, logging.getLogger("azure_monitor"), (True, True, False)),
    ):
        state = _load_function(
            APP_ROOT / "functions_appinsights.py",
            "get_appinsights_runtime_state",
            {
                "os": SimpleNamespace(environ=environ),
                "logging": logging,
                "Dict": Dict,
                "_appinsights_logger": app_logger,
                "_azure_monitor_configured": configured,
            },
        )()
        assert (
            state["connection_configured"],
            state["exporter_configured"],
            state["global_logging_active"],
        ) == expected, state
        assert all(isinstance(value, bool) for value in state.values()), "Only booleans may leave the server."

    registered = _load_function(
        APP_ROOT / "swagger_wrapper.py",
        "are_swagger_routes_registered",
        {"Flask": object, "SWAGGER_BLUEPRINT_NAME": "swagger_docs"},
    )
    assert registered(SimpleNamespace(blueprints={"swagger_docs": object()}))
    assert not registered(SimpleNamespace(blueprints={}))
    print("  Application Insights and Swagger report how this process started.")


def test_the_connection_readout_explains_each_state():
    """Global logging without a destination silently does nothing; the readout says so."""
    print("\nTesting the Application Insights connection readout...")

    readout_for = lambda state: _load_function(  # noqa: E731
        APP_ROOT / "route_backend_v2.py",
        "_build_appinsights_connection_readout",
        {"get_appinsights_runtime_state": lambda: state},
    )()

    missing = readout_for({"connection_configured": False, "exporter_configured": False, "global_logging_active": False})
    failed = readout_for({"connection_configured": True, "exporter_configured": False, "global_logging_active": False})
    connected = readout_for({"connection_configured": True, "exporter_configured": True, "global_logging_active": False})

    assert missing["ok"] is False and "not set" in missing["message"]
    assert failed["ok"] is False and "did not start" in failed["message"]
    assert connected["ok"] is True
    print("  Missing, failed and connected states each read differently.")


def test_the_typescript_logic_checks_pass():
    """The browser readouts follow the same rules; skipped without the front-end toolchain."""
    print("\nTesting the Operations readout logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return

    assert LOGIC_CHECK_TS.exists(), "The TypeScript logic checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where
    # node can resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-admin-operations-check.mjs"
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


if __name__ == "__main__":
    tests = [
        test_switching_debug_logging_on_starts_a_utc_timer,
        test_an_unrelated_save_leaves_timers_and_the_schedule_alone,
        test_resaving_an_unchanged_timer_keeps_its_turnoff,
        test_switching_a_log_off_clears_its_turnoff,
        test_a_unit_change_brings_the_duration_into_range_and_says_so,
        test_refresh_time_and_timezone_are_validated_rather_than_replaced,
        test_a_schedule_change_moves_the_next_run,
        test_an_unchanged_schedule_keeps_its_next_run_and_off_clears_it,
        test_the_shared_helpers_apply_the_classic_rules,
        test_the_checker_reads_utc_and_legacy_turnoffs,
        test_every_writer_uses_the_shared_helpers,
        test_runtime_state_reports_how_the_process_started,
        test_the_connection_readout_explains_each_state,
        test_the_typescript_logic_checks_pass,
    ]

    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
