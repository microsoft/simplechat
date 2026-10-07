#!/usr/bin/env python3
# test_v2_admin_scale_logic.py
"""
Functional test for the browser logic behind the Admin Settings Scale group.
Version: 0.261.260
Implemented in: 0.261.260

The Scale panels mirror two pieces of ``functions_cosmos_throughput.py`` so they can
explain a change before it is sent: the throughput policy rules a save must pass,
and the RU/s a manual scale will land on. The server stays authoritative, but a
browser copy that drifts would show an administrator a reason the server never
gives, or a confirmation promising a target the scale will not reach.

This runner generates cases from the real Python functions -- ``normalize_ru``,
``collect_cosmos_throughput_policy_errors``, ``normalize_container_policy`` and
``calculate_manual_scale_target`` -- together with the live field schema, writes
them to a temporary file, and executes ``test_v2_admin_scale_logic.ts`` against
them. A rule changed on one side therefore fails here until the other follows.
The TypeScript file also pins the presentation logic that has no server
counterpart.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
V2_DIR = REPO_ROOT / "application" / "v2_ui"
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_admin_scale_logic.ts"

fields_module = import_app_module("admin_settings_fields")
throughput_module = import_app_module("functions_cosmos_throughput")

POLICY_RULES = {"threshold_order", "scale_up_interval", "scale_down_interval"}


def _base_settings(**overrides):
    """Throughput settings as stored, with automation on and default guardrails."""
    settings = {
        "cosmos_throughput_autoscale_enabled": True,
        "cosmos_throughput_metrics_window_minutes": 5,
        "cosmos_throughput_scale_up_threshold_percent": 90,
        "cosmos_throughput_scale_down_threshold_percent": 70,
        "cosmos_throughput_scale_up_step_ru": 1000,
        "cosmos_throughput_scale_down_step_ru": 1000,
        "cosmos_throughput_scale_up_cooldown_minutes": 5,
        "cosmos_throughput_scale_down_cooldown_minutes": 20,
        "cosmos_throughput_min_ru": 2000,
        "cosmos_throughput_max_ru": 6000,
    }
    settings.update(overrides)
    return settings


def build_normalize_ru_cases():
    """Every value shape a stored setting or a status payload may hold."""
    values = [
        0, 1, 99, 100, 101, 399, 400, 401, 450, 999, 1000, 1001, 1450, 1500, 2500,
        9999, 10000, 10001, 12345, -5, 5.7, "1500", " 2000 ", "+3000", "1.5",
        "abc", "", None, True, False,
    ]
    modes = ["autoscale", "manual", "Autoscale", " autoscale ", None, ""]
    cases = []
    for value in values:
        for mode in modes:
            for direction in ("up", "down"):
                cases.append({
                    "value": value,
                    "mode": mode,
                    "direction": direction,
                    "expected": throughput_module.normalize_ru(value, mode=mode, direction=direction),
                })
    return cases


def build_policy_validation_cases():
    """Settings that pass, and settings that break each rule globally and per container."""
    broken_container = {"scale_up_threshold_percent": 50, "scale_down_threshold_percent": 60}
    scenarios = (
        ("automation off ignores broken values", _base_settings(
            cosmos_throughput_autoscale_enabled=False,
            cosmos_throughput_scale_up_threshold_percent=50,
            cosmos_throughput_scale_down_threshold_percent=60,
        )),
        ("valid settings", _base_settings()),
        ("threshold order", _base_settings(
            cosmos_throughput_scale_up_threshold_percent=70,
            cosmos_throughput_scale_down_threshold_percent=70,
        )),
        ("window longer than both intervals", _base_settings(
            cosmos_throughput_metrics_window_minutes=30,
        )),
        ("every global rule at once", _base_settings(
            cosmos_throughput_scale_up_threshold_percent=40,
            cosmos_throughput_scale_down_threshold_percent=60,
            cosmos_throughput_metrics_window_minutes=60,
        )),
        ("form strings are coerced before judging", _base_settings(
            cosmos_throughput_autoscale_enabled="on",
            cosmos_throughput_scale_up_threshold_percent="80",
            cosmos_throughput_scale_down_threshold_percent="85",
            cosmos_throughput_metrics_window_minutes="5",
        )),
        ("out-of-range values are clamped before judging", _base_settings(
            cosmos_throughput_scale_up_threshold_percent=150,
            cosmos_throughput_scale_down_threshold_percent=120,
        )),
        ("missing values use the defaults", {"cosmos_throughput_autoscale_enabled": True}),
        ("a container inherits a broken global policy", _base_settings(
            cosmos_throughput_scale_up_threshold_percent=70,
            cosmos_throughput_scale_down_threshold_percent=70,
            cosmos_throughput_container_policies={"conversations": {}},
        )),
        ("a container breaks its own interval", _base_settings(
            cosmos_throughput_metrics_window_minutes=10,
            cosmos_throughput_scale_up_cooldown_minutes=10,
            cosmos_throughput_container_policies={
                "conversations": {"scale_up_cooldown_minutes": 5},
                "documents": {"scale_down_cooldown_minutes": 15},
            },
        )),
        ("an enforced global policy skips containers", _base_settings(
            cosmos_throughput_enforce_container_defaults=True,
            cosmos_throughput_container_policies={"conversations": broken_container},
        )),
        ("a disabled container policy is skipped", _base_settings(
            cosmos_throughput_container_policies={
                "conversations": {**broken_container, "enabled": False},
            },
        )),
        ("explicit nulls fall back to the global policy", _base_settings(
            cosmos_throughput_container_policies={
                "conversations": {"scale_up_threshold_percent": None, "min_ru": None},
            },
        )),
        ("a blank container name is ignored", _base_settings(
            cosmos_throughput_container_policies={"  ": broken_container},
        )),
    )

    cases = []
    for name, settings in scenarios:
        problems = throughput_module.collect_cosmos_throughput_policy_errors(settings)
        container_errors = {}
        for problem in problems:
            if problem["scope"] == "container":
                container_errors.setdefault(problem["container_name"], set()).update(problem["fields"])
        cases.append({
            "name": name,
            "settings": settings,
            "rules": sorted({problem["rule"] for problem in problems}),
            "messages": [problem["message"] for problem in problems],
            "field_error_keys": sorted(
                {key for problem in problems for key in problem["setting_keys"]}
            ),
            "container_errors": {
                container: sorted(fields) for container, fields in container_errors.items()
            },
        })
    return cases


def build_container_policy_cases():
    """Container policies as saved, as left blank, and as typed into the classic form."""
    settings = _base_settings()
    broken = {
        "scale_up_threshold_percent": 50,
        "scale_down_threshold_percent": 60,
        "min_ru": 8000,
        "max_ru": 3000,
    }
    scenarios = (
        ("no saved policy inherits the global policy", "conversations", None, settings, True),
        ("an empty policy inherits the global policy", "conversations", {}, settings, True),
        ("own values", "conversations", {
            "min_ru": 2000,
            "max_ru": 6000,
            "scale_up_threshold_percent": 80,
            "enabled": "false",
        }, settings, True),
        ("explicit nulls", "conversations", {
            "min_ru": None,
            "max_ru": None,
            "scale_up_step_ru": None,
            "scale_up_threshold_percent": None,
            "auto_scale_up_enabled": None,
            "enabled": None,
        }, settings, True),
        ("broken relationships are repaired for use", "conversations", broken, settings, True),
        ("broken relationships are kept for validation", "conversations", broken, settings, False),
        ("values above SimpleChat's ceiling are capped", "conversations", {
            "min_ru": 15000,
            "max_ru": 20000,
        }, settings, True),
        ("strings from the classic form", "conversations", {
            "min_ru": "2500",
            "scale_down_cooldown_minutes": "30",
            "ignore_max_limit": "on",
            "convert_manual_to_autoscale_enabled": "yes",
        }, settings, True),
        ("the automation's timestamps pass through", "conversations", {
            "last_scale_up_at": "2026-01-01T00:00:00+00:00",
            "last_mode_conversion_at": "2026-01-02T00:00:00+00:00",
        }, settings, True),
        ("the policy's own name is used when none is given", "", {"container_name": "documents"}, settings, True),
        ("global values arriving as strings", "conversations", {}, {
            "cosmos_throughput_min_ru": "3000",
            "cosmos_throughput_auto_scale_up_enabled": "off",
            "cosmos_throughput_ignore_min_limit": "1",
        }, True),
    )

    cases = []
    for name, container, policy, source, repair in scenarios:
        normalized = throughput_module.normalize_cosmos_throughput_settings(
            source,
            repair_policy_relationships=repair,
        )
        cases.append({
            "name": name,
            "container": container,
            "policy": policy,
            "settings": source,
            "repair": repair,
            "expected": throughput_module.normalize_container_policy(
                container,
                policy,
                normalized,
                repair_policy_relationships=repair,
            ),
        })
    return cases


def _database(current_ru, mode="autoscale", scalable=True):
    return {"throughput": {"mode": mode, "current_ru": current_ru, "is_scalable": scalable}}


def _containers(*containers):
    return {"capacity_scope": "container", "containers": list(containers)}


def build_manual_scale_cases():
    """Manual scales up and down, against each guardrail that can stop them."""
    base = _base_settings()
    scenarios = (
        ("database up one step", base, _database(4000), "up", ""),
        ("database up stops at the maximum", base, _database(6000), "up", ""),
        ("database up past the maximum when it is ignored", _base_settings(
            cosmos_throughput_ignore_max_limit=True,
        ), _database(6000), "up", ""),
        ("database up is capped at SimpleChat's ceiling", _base_settings(
            cosmos_throughput_ignore_max_limit=True,
            cosmos_throughput_scale_up_step_ru=3000,
        ), _database(9000), "up", ""),
        ("database at the ceiling", _base_settings(
            cosmos_throughput_ignore_max_limit=True,
        ), _database(10000), "up", ""),
        ("database above the ceiling", base, _database(20000), "down", ""),
        ("database down one step", base, _database(4000), "down", ""),
        ("database down stops at the minimum", base, _database(2000), "down", ""),
        ("database down past the minimum when it is ignored", _base_settings(
            cosmos_throughput_ignore_min_limit=True,
        ), _database(2000), "down", ""),
        ("autoscale cannot go below its service minimum", _base_settings(
            cosmos_throughput_ignore_min_limit=True,
        ), _database(1000), "down", ""),
        ("manual throughput moves in 100 RU/s steps", base, _database(450, mode="manual"), "up", ""),
        ("manual throughput down to its service minimum", _base_settings(
            cosmos_throughput_ignore_min_limit=True,
        ), _database(1450, mode="manual"), "down", ""),
        ("unknown current throughput", base, _database(None), "up", ""),
        ("no throughput reported at all", base, {}, "up", ""),
        ("a container uses its own maximum", base, _containers({
            "container_name": "conversations",
            "mode": "autoscale",
            "current_ru": 4000,
            "is_scalable": True,
            "policy": {"max_ru": 4000},
        }), "up", "conversations"),
        ("a container inherits the global step", base, _containers({
            "container_name": "conversations",
            "mode": "autoscale",
            "current_ru": 3000,
            "is_scalable": True,
            "policy": {},
        }), "up", "conversations"),
        ("a container scales down within its own minimum", base, _containers({
            "container_name": "documents",
            "mode": "autoscale",
            "current_ru": 5000,
            "is_scalable": True,
            "policy": {"min_ru": 5000},
        }), "down", "documents"),
        ("a container above the ceiling", base, _containers({
            "container_name": "conversations",
            "mode": "autoscale",
            "current_ru": 12000,
            "is_scalable": True,
        }), "up", "conversations"),
    )

    cases = []
    for name, settings, status, direction, container in scenarios:
        try:
            expected = {
                "target": throughput_module.calculate_manual_scale_target(
                    settings, status, direction, container_name=container
                )
            }
        except throughput_module.CosmosThroughputError as error:
            expected = {"error": str(error)}
        cases.append({
            "name": name,
            "settings": settings,
            "status": status,
            "direction": direction,
            "container": container,
            "expected": expected,
        })
    return cases


def build_schema_sections():
    """Every declared section as the settings API sends it, labelled as in navigation."""
    schema = fields_module.get_admin_settings_fields()
    sections = []
    for group in ADMIN_NAV:
        for tab in group["tabs"]:
            for section in tab["sections"]:
                fields = schema.get(section["id"])
                if fields:
                    sections.append({
                        "sectionId": section["id"],
                        "label": section["label"],
                        "fields": fields,
                    })
    return sections


def build_mirror_cases():
    return {
        "normalize_ru": build_normalize_ru_cases(),
        "policy_validation": build_policy_validation_cases(),
        "container_policies": build_container_policy_cases(),
        "manual_scale": build_manual_scale_cases(),
        "sections": build_schema_sections(),
    }


def test_generated_cases_exercise_every_rule():
    """A mirror check over cases that never break a rule proves very little."""
    print("Testing the generated mirror cases...")

    assert_app_version_at_least("0.261.260")

    cases = build_mirror_cases()

    validation = cases["policy_validation"]
    broken_rules = {rule for case in validation for rule in case["rules"]}
    assert broken_rules == POLICY_RULES, f"Rules never exercised: {POLICY_RULES - broken_rules}"
    assert any(not case["messages"] for case in validation), "No case passes validation."
    assert any(case["container_errors"] for case in validation), "No case breaks a container policy."

    outcomes = cases["manual_scale"]
    errors = {case["expected"].get("error") for case in outcomes if "error" in case["expected"]}
    for message in (
        "Maximum RU/s limit is already reached.",
        "Minimum RU/s limit is already reached.",
        "Current Cosmos throughput could not be determined.",
        throughput_module.COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE,
    ):
        assert message in errors, f"No manual scale case produces: {message}"
    assert sum("target" in case["expected"] for case in outcomes) >= 8, "Too few successful scales."

    section_ids = {section["sectionId"] for section in cases["sections"]}
    for section_id in ("redis-cache-section", "conversation-cache-section", "keyvault-section"):
        assert section_id in section_ids, f"{section_id} is missing from the generated schema"

    json.dumps(cases)

    print(
        f"  {len(cases['normalize_ru'])} rounding, {len(validation)} validation, "
        f"{len(cases['container_policies'])} policy and {len(outcomes)} scale case(s)."
    )
    return True


def test_the_typescript_logic_checks_pass():
    """Execute the browser half, skipping when the front-end toolchain is absent."""
    print("\nTesting Scale logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return True

    assert LOGIC_CHECK_TS.exists(), "The TypeScript logic checks are missing"

    handle, cases_path = tempfile.mkstemp(prefix="scale-logic-cases-", suffix=".json")
    with os.fdopen(handle, "w", encoding="utf-8") as cases_file:
        json.dump(build_mirror_cases(), cases_file)

    # functional_tests/ has no node_modules of its own, so the bundle is written where
    # node can resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-admin-scale-check.mjs"
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
            env={**os.environ, "SCALE_LOGIC_CASES": cases_path},
            shell=(sys.platform == "win32"),
        )
    finally:
        if bundle.exists():
            bundle.unlink()
        os.unlink(cases_path)

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript logic checks failed")

    passed = result.stdout.count("  ok  ")
    print(f"  ok  {passed} TypeScript logic checks passed")
    return True


if __name__ == "__main__":
    tests = [
        test_generated_cases_exercise_every_rule,
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
