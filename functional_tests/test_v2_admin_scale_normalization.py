#!/usr/bin/env python3
# test_v2_admin_scale_normalization.py
"""
Functional test for what a V2 save does to the Admin Settings Scale group.
Version: 0.261.260
Implemented in: 0.261.260

The Scale settings have rules that relate several values, and the server-rendered
page enforces them when its form is saved: Scale Up At must stay above Scale Down
At, each scale interval must cover the metrics window, and RU/s values round up to
the 1,000 RU/s increments Cosmos autoscale accepts. A V2 save carries only the keys
an administrator changed, so these checks pin that the merged result is what gets
judged, that each error lands on the control that caused it, and that a value the
server adjusts is reported rather than rewritten silently.

Two Scale values also have a stored shape the V2 editor does not share. The Redis
port is stored as text, because the connection test reads it with ``.strip()`` and
blank means "use the service's port". Container policies arrive from V1 as a JSON
string and from the V2 workbench as an object, and their scale timestamps belong to
the automation, so a page loaded before a scale must not write older ones back.
"""

import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


fields_module = import_app_module("admin_settings_fields")
throughput_module = import_app_module("functions_cosmos_throughput")
secret_utils = import_app_module("admin_settings_secret_utils")
normalize = fields_module.normalize_admin_settings_updates

UP_THRESHOLD = "cosmos_throughput_scale_up_threshold_percent"
DOWN_THRESHOLD = "cosmos_throughput_scale_down_threshold_percent"
UP_COOLDOWN = "cosmos_throughput_scale_up_cooldown_minutes"
DOWN_COOLDOWN = "cosmos_throughput_scale_down_cooldown_minutes"
METRICS_WINDOW = "cosmos_throughput_metrics_window_minutes"
POLICIES = "cosmos_throughput_container_policies"


def stored_settings(**overrides):
    """A stored settings document with the throughput defaults and automation on."""
    settings = throughput_module.get_default_cosmos_throughput_settings()
    settings["cosmos_throughput_autoscale_enabled"] = True
    settings.update(overrides)
    return settings


def v1_messages(settings):
    """The messages the server-rendered form shows for the same settings."""
    return throughput_module.validate_cosmos_throughput_policy_settings(settings)


def test_redis_port_is_stored_as_text_or_refused():
    """The connection test calls .strip() on the port, so it must stay a string."""
    print("Testing the Redis port...")

    assert_app_version_at_least("0.261.260")

    for submitted, stored in ((" 6380 ", "6380"), (10000, "10000"), ("", ""), (None, "")):
        normalized, errors, _ = normalize({"redis_port": submitted})
        assert not errors, (submitted, errors)
        assert normalized["redis_port"] == stored, (submitted, normalized["redis_port"])

    for refused in ("0", "65536", "-1", "63 80", "abc", "6379.5"):
        _, errors, _ = normalize({"redis_port": refused})
        assert errors.get("redis_port") == fields_module.REDIS_PORT_ERROR, (refused, errors)

    print("  Ports save as text, blank means the service default, and bad ports are refused.")
    return True


def test_redis_selects_and_credential():
    """An unknown option would store a value the Redis client does not understand."""
    print("\nTesting the Redis selects and credential...")

    _, errors, _ = normalize({"redis_auth_type": "password"})
    assert "redis_auth_type" in errors, errors

    normalized, errors, _ = normalize(
        {"redis_auth_type": "key_vault", "redis_service_type": "azure_managed_redis"}
    )
    assert not errors, errors
    assert normalized["redis_auth_type"] == "key_vault", normalized
    assert normalized["redis_service_type"] == "azure_managed_redis", normalized

    # The browser holds a placeholder for the stored key. It passes through the
    # normalizer, and the PATCH route swaps it back for the stored key before saving, as
    # it does for every declared secret.
    current = {"redis_key": "stored-access-key"}
    normalized, errors, _ = normalize({"redis_key": fields_module.SECRET_REDACTED_VALUE}, current)
    assert not errors, errors
    assert "redis_key" in fields_module.get_secret_field_keys()
    restored = secret_utils.resolve_admin_settings_secret_value(
        "redis_key", normalized["redis_key"], current
    )
    assert restored == "stored-access-key", "The placeholder must never replace the stored key."

    normalized, errors, _ = normalize({"redis_key": "  new-access-key  "})
    assert not errors, errors
    assert normalized["redis_key"] == "new-access-key", normalized

    print("  Unknown options are refused and an untouched key keeps its stored value.")
    return True


def test_cache_and_index_values_keep_v1_bounds():
    """The V1 input bounds, enforced on the server by clamping as every number field is."""
    print("\nTesting cache TTL and batch size bounds...")

    cases = (
        ("conversation_cache_ttl_seconds", {0: 0, 120: 120, -1: 0}),
        ("document_access_index_cache_ttl_seconds", {60: 60, 900: 900, 59: 60, 901: 900}),
        ("document_access_index_backfill_batch_size", {1: 1, 1000: 1000, 0: 1, 1001: 1000}),
        ("document_access_index_repair_batch_size", {1: 1, 500: 500, 0: 1, 501: 500}),
    )
    for key, expectations in cases:
        for submitted, stored in expectations.items():
            normalized, errors, _ = normalize({key: submitted})
            assert not errors, (key, submitted, errors)
            assert normalized[key] == stored, (key, submitted, normalized[key])

    print(f"  {len(cases)} bounded value(s) stay inside the V1 range.")
    return True


def test_threshold_order_error_sits_on_both_thresholds():
    """Either threshold can be the one to move, so both carry the reason."""
    print("\nTesting the threshold order rule...")

    current = stored_settings()
    updates = {UP_THRESHOLD: 70, DOWN_THRESHOLD: 70}
    _, errors, _ = normalize(updates, current)

    expected = v1_messages({**current, **updates})
    assert expected == ["Cosmos throughput policy: Scale Up At must be higher than Scale Down At."], expected
    assert errors == {UP_THRESHOLD: expected[0], DOWN_THRESHOLD: expected[0]}, errors

    print("  Both thresholds carry the V1 message.")
    return True


def test_interval_errors_sit_on_the_interval_and_the_window():
    """Raising the window can break an interval nobody touched."""
    print("\nTesting the interval rules...")

    current = stored_settings()
    updates = {METRICS_WINDOW: 30}
    _, errors, _ = normalize(updates, current)

    up_message, down_message = v1_messages({**current, **updates})
    assert up_message == (
        "Cosmos throughput policy: Scale Up Interval must be greater than or equal to "
        "the Metrics Window (30 minutes)."
    ), up_message
    assert errors.get(UP_COOLDOWN) == up_message, errors
    assert errors.get(DOWN_COOLDOWN) == down_message, errors
    # The window is involved in both; it carries the first reason.
    assert errors.get(METRICS_WINDOW) == up_message, errors

    print("  Each interval error sits on its interval and on the metrics window.")
    return True


def test_a_partial_save_is_judged_with_the_stored_settings():
    """A save that sends one threshold can still break the pair."""
    print("\nTesting a partial save against stored settings...")

    current = stored_settings(**{DOWN_THRESHOLD: 85})
    _, errors, _ = normalize({UP_THRESHOLD: 80}, current)

    assert set(errors) == {UP_THRESHOLD, DOWN_THRESHOLD}, errors

    # The same change is accepted once the stored value no longer conflicts.
    _, errors, _ = normalize({UP_THRESHOLD: 80}, stored_settings(**{DOWN_THRESHOLD: 60}))
    assert not errors, errors

    print("  The merged state is what gets judged.")
    return True


def test_rules_wait_for_automation_and_repairs_are_reported():
    """V1 enforces the rules only while automation is on, and repairs otherwise."""
    print("\nTesting saves with automation off...")

    current = stored_settings(cosmos_throughput_autoscale_enabled=False)
    normalized, errors, warnings = normalize({UP_THRESHOLD: 50, DOWN_THRESHOLD: 60}, current)

    assert not errors, errors
    assert normalized[DOWN_THRESHOLD] == 49, normalized[DOWN_THRESHOLD]
    assert warnings.get(DOWN_THRESHOLD) == "Lowered to 49% so it stays below Scale Up At.", warnings

    # Turning automation off in the same save is the same situation.
    normalized, errors, warnings = normalize(
        {"cosmos_throughput_autoscale_enabled": False, UP_THRESHOLD: 50, DOWN_THRESHOLD: 60},
        stored_settings(),
    )
    assert not errors, errors
    assert normalized[DOWN_THRESHOLD] == 49, normalized

    print("  Nothing blocks the save; the repair is reported beside the threshold.")
    return True


def test_ru_values_round_up_with_a_warning():
    """Cosmos autoscale moves in 1,000 RU/s steps, and SimpleChat stops at 10,000."""
    print("\nTesting RU/s rounding and caps...")

    current = stored_settings()

    normalized, errors, warnings = normalize({"cosmos_throughput_scale_up_step_ru": 1500}, current)
    assert not errors, errors
    assert normalized["cosmos_throughput_scale_up_step_ru"] == 2000, normalized
    assert warnings["cosmos_throughput_scale_up_step_ru"] == (
        "Saved as 2,000 RU/s. Cosmos autoscale moves in 1,000 RU/s increments, so values round up."
    ), warnings

    normalized, errors, warnings = normalize({"cosmos_throughput_min_ru": 12000}, current)
    assert not errors, errors
    assert normalized["cosmos_throughput_min_ru"] == 10000, normalized
    assert warnings["cosmos_throughput_min_ru"] == (
        "Saved as 10,000 RU/s, the most SimpleChat scales to."
    ), warnings

    normalized, errors, warnings = normalize(
        {"cosmos_throughput_min_ru": 5000, "cosmos_throughput_max_ru": 3000}, current
    )
    assert not errors, errors
    assert normalized["cosmos_throughput_max_ru"] == 5000, normalized
    assert warnings["cosmos_throughput_max_ru"] == (
        "Raised to 5,000 RU/s so it is not below Minimum RU/s."
    ), warnings
    assert "cosmos_throughput_min_ru" not in warnings, warnings

    # A value that needs no adjustment says nothing.
    _, _, warnings = normalize({"cosmos_throughput_scale_down_step_ru": 3000}, current)
    assert not warnings, warnings

    print("  Adjusted values are saved as the server stores them, with a reason.")
    return True


def test_container_policies_accept_both_shapes():
    """V1 posts a JSON string and the V2 workbench an object; both mean the same."""
    print("\nTesting container policy shapes...")

    current = stored_settings()
    policies = {"conversations": {"min_ru": 2000, "max_ru": 6000}, "  ": {"min_ru": 1000}}

    from_object, errors, _ = normalize({POLICIES: policies}, current)
    assert not errors, errors
    from_json, errors, _ = normalize({POLICIES: json.dumps(policies)}, current)
    assert not errors, errors

    assert from_object[POLICIES] == from_json[POLICIES], (from_object[POLICIES], from_json[POLICIES])
    assert list(from_object[POLICIES]) == ["conversations"], "A blank container name is dropped."
    saved = from_object[POLICIES]["conversations"]
    assert (saved["min_ru"], saved["max_ru"], saved["container_name"]) == (2000, 6000, "conversations"), saved
    # A value the policy leaves out is stored as the global value it inherits, as V1 stores it.
    assert saved[UP_THRESHOLD.replace("cosmos_throughput_", "")] == current[UP_THRESHOLD], saved

    for bad, message in (
        ("not json", "Container policies could not be read."),
        (["conversations"], "Container policies must be an object keyed by container name."),
        ({"conversations": "fast"}, "The policy for conversations must be an object."),
    ):
        _, errors, _ = normalize({POLICIES: bad}, current)
        assert errors.get(POLICIES) == message, (bad, errors)

    print("  Both shapes save the same policies, and malformed ones are refused.")
    return True


def test_container_policy_timestamps_come_from_the_stored_document():
    """A page loaded before a scale must not reset the cooldown it started."""
    print("\nTesting container policy timestamps...")

    current = stored_settings(**{
        POLICIES: {
            "conversations": {
                "container_name": "conversations",
                "min_ru": 2000,
                "last_scale_up_at": "2026-01-02T03:04:05+00:00",
            },
        },
    })
    submitted = {
        "conversations": {
            "min_ru": 3000,
            "last_scale_up_at": "2020-01-01T00:00:00+00:00",
            "last_scale_down_at": "2020-01-01T00:00:00+00:00",
        },
    }

    normalized, errors, _ = normalize({POLICIES: submitted}, current)
    assert not errors, errors
    saved = normalized[POLICIES]["conversations"]
    assert saved["min_ru"] == 3000, saved
    assert saved["last_scale_up_at"] == "2026-01-02T03:04:05+00:00", saved
    assert saved["last_scale_down_at"] is None, (
        "A timestamp the automation never wrote must not be accepted from the browser."
    )

    print("  Timestamps are taken from the stored document, never the browser.")
    return True


def test_container_policy_rules_follow_v1():
    """Container rules are skipped while the global policy is enforced, as in V1."""
    print("\nTesting container policy rules...")

    broken = {"conversations": {"scale_up_threshold_percent": 50, "scale_down_threshold_percent": 60}}

    current = stored_settings()
    _, errors, _ = normalize({POLICIES: broken}, current)
    expected = "Container 'conversations' policy: Scale Up At must be higher than Scale Down At."
    assert errors == {POLICIES: expected}, errors
    assert v1_messages({**current, POLICIES: broken}) == [expected]

    _, errors, _ = normalize(
        {POLICIES: broken}, stored_settings(cosmos_throughput_enforce_container_defaults=True)
    )
    assert not errors, errors

    disabled = {"conversations": {**broken["conversations"], "enabled": False}}
    _, errors, _ = normalize({POLICIES: disabled}, current)
    assert not errors, errors

    print("  Container errors match V1 and are skipped when V1 skips them.")
    return True


def test_policy_errors_name_declared_settings():
    """An error keyed to an undeclared setting has no control to appear beside."""
    print("\nTesting that every policy error names a declared setting...")

    declared = {
        field["key"] for _section_id, field in fields_module.iter_fields() if field.get("key")
    }
    broken = stored_settings(**{
        UP_THRESHOLD: 50,
        DOWN_THRESHOLD: 60,
        METRICS_WINDOW: 60,
        POLICIES: {"conversations": {"scale_up_threshold_percent": 10, "scale_down_threshold_percent": 20}},
    })
    problems = throughput_module.collect_cosmos_throughput_policy_errors(broken)
    assert {problem["rule"] for problem in problems} == {
        "threshold_order",
        "scale_up_interval",
        "scale_down_interval",
    }, problems

    undeclared = sorted(
        {key for problem in problems for key in problem["setting_keys"]} - declared
    )
    assert not undeclared, f"Errors keyed to undeclared settings: {undeclared}"
    assert [problem["message"] for problem in problems] == v1_messages(broken)

    print(f"  All {len(problems)} error(s) sit on declared settings with V1's messages.")
    return True


def test_an_unrelated_save_is_not_blocked():
    """A stored throughput problem must not stop an administrator saving anything else."""
    print("\nTesting a save with no throughput keys...")

    current = stored_settings(**{UP_THRESHOLD: 50, DOWN_THRESHOLD: 60})
    normalized, errors, warnings = normalize({"enable_redis_cache": True}, current)

    assert not errors, errors
    assert not warnings, warnings
    assert normalized == {"enable_redis_cache": True}, normalized

    print("  Only saves that touch throughput settings are judged by its rules.")
    return True


if __name__ == "__main__":
    tests = [
        test_redis_port_is_stored_as_text_or_refused,
        test_redis_selects_and_credential,
        test_cache_and_index_values_keep_v1_bounds,
        test_threshold_order_error_sits_on_both_thresholds,
        test_interval_errors_sit_on_the_interval_and_the_window,
        test_a_partial_save_is_judged_with_the_stored_settings,
        test_rules_wait_for_automation_and_repairs_are_reported,
        test_ru_values_round_up_with_a_warning,
        test_container_policies_accept_both_shapes,
        test_container_policy_timestamps_come_from_the_stored_document,
        test_container_policy_rules_follow_v1,
        test_policy_errors_name_declared_settings,
        test_an_unrelated_save_is_not_blocked,
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
