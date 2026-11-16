# test_v2_admin_schema_vocabulary.py
#!/usr/bin/env python3
"""
Functional test for the Admin Settings schema vocabulary added for Knowledge.
Version: 0.261.274
Implemented in: 0.261.084
Runtime flag evaluation, open_until_set and on_enable added in: 0.261.265
Anchored group coverage added in: 0.261.266
label_variants and requires.when coverage added in: 0.261.274

The Knowledge group needs control kinds the schema could not previously express:
credentials, domain allow lists, workspace assignment lists, server-computed
status readouts, multi-condition visibility, and cross-section prerequisites.

The checks here pin the parts of that vocabulary where a mistake is silent or
destructive rather than obvious:

secrets
    A browser is sent a placeholder instead of a stored credential. If the
    normalizer wrote that placeholder back, saving any unrelated toggle on the
    page would replace every key in the settings document with the literal
    string "***REDACTED***". That is unrecoverable without a backup, so it gets
    the most coverage here.

dependency evaluation
    ``any_of`` and value equality decide whether a control is visible at all. A
    wrong answer hides a setting an administrator needs, and the same rules run
    on the server when ``min_selected`` is enforced.

list coercion
    Domain lists and assignment lists have to round-trip through the shapes the
    server-rendered panes already store, or a value saved in one interface is
    unreadable in the other.

anchored groups
    A group may name the switch it is drawn beneath. An anchor that names nothing,
    or a panel that does not depend on its switch, leaves the panel either with no
    row to sit under or visible beneath a switch that is off.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


fields_module = import_app_module("admin_settings_fields")
normalize = fields_module.normalize_admin_settings_updates

REDACTED = fields_module.SECRET_REDACTED_VALUE


def _secret_field(**overrides):
    field = {"key": "test_secret", "type": "secret", "label": "Test secret"}
    field.update(overrides)
    return field


def test_declared_types_are_renderable():
    """A type the renderer does not implement would draw nothing at all."""
    print("Testing declared field types...")

    assert_app_version_at_least("0.261.084")

    for new_type in ("secret", "string_list", "id_list", "status"):
        assert new_type in fields_module.FIELD_TYPES, (
            f"{new_type!r} is missing from FIELD_TYPES, so the schema test would "
            "reject any field declaring it."
        )

    assert "status" in fields_module.NON_PATCHABLE_TYPES, (
        "A status readout is computed by the server. Allowing it through the "
        "PATCH would let a browser write a value nothing reads."
    )

    for patchable in ("secret", "string_list", "id_list"):
        assert patchable not in fields_module.NON_PATCHABLE_TYPES, (
            f"{patchable!r} must be savable through the settings PATCH."
        )

    print(f"  {len(fields_module.FIELD_TYPES)} field type(s) declared.")
    return True


def test_redaction_placeholder_matches_the_settings_module():
    """Two spellings of the placeholder would make secrets unsavable."""
    print("\nTesting the redaction placeholder against admin_settings_secret_utils...")

    source = (
        Path(__file__).resolve().parents[1]
        / "application"
        / "single_app"
        / "admin_settings_secret_utils.py"
    ).read_text(encoding="utf-8")

    expected_line = f'ADMIN_SETTINGS_SECRET_REDACTED_VALUE = "{REDACTED}"'
    assert expected_line in source, (
        "admin_settings_fields.SECRET_REDACTED_VALUE no longer matches "
        "admin_settings_secret_utils.ADMIN_SETTINGS_SECRET_REDACTED_VALUE. "
        "The schema and dependency-light secret helper must agree without "
        "importing functions_settings and initializing its Azure dependencies.\n"
        f"  schema module: {expected_line}"
    )

    print(f"  Both modules agree on {REDACTED!r}.")
    return True


def test_unchanged_secret_is_dropped_rather_than_written():
    """Writing the placeholder back would destroy every stored credential."""
    print("\nTesting that an untouched secret is left alone...")

    field = _secret_field()
    result, error = fields_module._normalize_secret(REDACTED, field)
    assert error is None, error
    assert result is fields_module.SECRET_UNCHANGED, (
        "The placeholder must normalize to the SECRET_UNCHANGED marker so the "
        f"update loop can drop it. Got {result!r}."
    )

    # Whitespace around the placeholder still means "untouched"; a browser or an
    # autofill extension may add it.
    padded, error = fields_module._normalize_secret(f"  {REDACTED}  ", field)
    assert error is None, error
    assert padded is fields_module.SECRET_UNCHANGED, padded

    print("  The placeholder normalizes to SECRET_UNCHANGED.")
    return True


def test_changed_secret_is_trimmed_and_bounded():
    """A real credential still has to save, and an absurd one is refused."""
    print("\nTesting that a real secret still saves...")

    field = _secret_field()

    stored, error = fields_module._normalize_secret("  s3cr3t-value  ", field)
    assert error is None, error
    assert stored == "s3cr3t-value", stored

    # Clearing a credential is a legitimate action, so an empty value is stored
    # rather than being mistaken for "unchanged".
    cleared, error = fields_module._normalize_secret("", field)
    assert error is None, error
    assert cleared == "", repr(cleared)

    _, error = fields_module._normalize_secret(
        "x" * (fields_module.SECRET_MAX_LENGTH + 1), field
    )
    assert error, "An over-length secret should be refused."

    print("  Real secrets are trimmed, clearable and length-bounded.")
    return True


def test_string_list_round_trips_the_v1_shape():
    """Domain lists are stored as arrays, matching the settings document."""
    print("\nTesting string_list coercion...")

    field = {
        "key": "test_domains",
        "type": "string_list",
        "label": "Domains",
        "entry_pattern": r"^[A-Za-z0-9*.-]+$",
        "entry_label": "domain",
    }

    entries, error = fields_module._normalize_string_list(
        "example.com\n  *.contoso.com  \n\nEXAMPLE.com\n", field
    )
    assert error is None, error
    assert entries == ["example.com", "*.contoso.com"], (
        "Entries should be trimmed, blank lines dropped and duplicates removed "
        "case-insensitively, in the order given. A list holding both Example.com "
        f"and example.com would behave unpredictably. Got {entries!r}."
    )

    # The server-rendered form splits on commas and semicolons too, so a value
    # saved there has to read back the same way.
    split, error = fields_module._normalize_string_list("a.example, b.example; c.example", field)
    assert error is None, error
    assert split == ["a.example", "b.example", "c.example"], split

    # The V2 editor works with an array; the stored shape is the same.
    from_array, error = fields_module._normalize_string_list(
        ["a.example", "b.example"], field
    )
    assert error is None, error
    assert from_array == ["a.example", "b.example"], from_array

    _, error = fields_module._normalize_string_list("not a domain", field)
    assert error, "A value failing entry_pattern should be refused."
    assert "domain" in error, f"The message should name the entry type: {error!r}"

    empty, error = fields_module._normalize_string_list("", field)
    assert error is None, error
    assert empty == [], empty

    print("  string_list trims, dedupes, validates and stores as an array.")
    return True


def test_id_list_accepts_both_stored_and_edited_shapes():
    """V1 stores a JSON string in a textarea; V2 edits an array of objects."""
    print("\nTesting id_list coercion...")

    field = {"key": "test_ids", "type": "id_list", "label": "Assignments"}

    from_json, error = fields_module._normalize_id_list('["a", "b", "a"]', field)
    assert error is None, error
    assert from_json == ["a", "b"], from_json

    # The assignment picker holds records, not bare ids.
    from_records, error = fields_module._normalize_id_list(
        [{"id": "x", "name": "Group X"}, "y", "", None], field
    )
    assert error is None, error
    assert from_records == ["x", "y"], from_records

    empty, error = fields_module._normalize_id_list("", field)
    assert error is None, error
    assert empty == [], empty

    _, error = fields_module._normalize_id_list("not json", field)
    assert error, "A malformed stored value should be refused, not silently emptied."

    bounded, error = fields_module._normalize_id_list(
        ["a", "b", "c"], {**field, "max_entries": 2}
    )
    assert error, "max_entries should be enforced."

    print("  id_list reads both the stored JSON string and edited records.")
    return True


def test_dependency_evaluation_supports_every_declared_shape():
    """Visibility decides whether a setting is reachable, so the rules must hold."""
    print("\nTesting dependency evaluation...")

    evaluate = fields_module.evaluate_dependency
    values = {
        "flag_on": True,
        "flag_off": False,
        "auth": "managed_identity",
        # The server-rendered form stores checkbox state as "on".
        "form_checkbox": "on",
        "absent": None,
    }
    read = values.get

    assert evaluate(None, read) is True, "A field with no condition is always visible."

    assert evaluate({"key": "flag_on", "equals": True}, read)
    assert not evaluate({"key": "flag_off", "equals": True}, read)
    assert evaluate({"key": "flag_off", "equals": False}, read)
    assert evaluate({"key": "absent", "equals": False}, read), (
        "A key missing from the settings document should read as off, not raise."
    )
    assert evaluate({"key": "form_checkbox", "equals": True}, read), (
        'A checkbox stored by the V1 form as "on" must count as enabled.'
    )

    assert evaluate({"key": "auth", "equals": "managed_identity"}, read)
    assert not evaluate({"key": "auth", "equals": "key"}, read)
    assert evaluate({"key": "auth", "not_equals": "key"}, read)

    # The Speech resource block is revealed by any of three capability toggles.
    any_of = {
        "any_of": [
            {"key": "flag_off", "equals": True},
            {"key": "absent", "equals": True},
            {"key": "flag_on", "equals": True},
        ]
    }
    assert evaluate(any_of, read)
    assert not evaluate(
        {"any_of": [{"key": "flag_off", "equals": True}, {"key": "absent", "equals": True}]},
        read,
    )

    all_of = {
        "all_of": [
            {"key": "flag_on", "equals": True},
            {"key": "auth", "equals": "managed_identity"},
        ]
    }
    assert evaluate(all_of, read)
    assert not evaluate(
        {"all_of": [{"key": "flag_on", "equals": True}, {"key": "flag_off", "equals": True}]},
        read,
    )

    # Nesting is what lets one field say "enabled, and using key auth".
    nested = {
        "all_of": [
            {"key": "flag_on", "equals": True},
            {"any_of": [{"key": "auth", "equals": "key"}, {"key": "form_checkbox", "equals": True}]},
        ]
    }
    assert evaluate(nested, read)

    print("  equals, not_equals, any_of, all_of and nesting all evaluate correctly.")
    return True


def test_declared_groups_and_requires_are_well_formed():
    """A typo in a variant or mode renders a group nobody can open."""
    print("\nTesting group and requires descriptors...")

    problems = []
    group_keys = {}
    for section_id, field in fields_module.iter_fields():
        group = field.get("group")
        if isinstance(group, dict) and field.get("key"):
            group_keys.setdefault((section_id, group.get("id")), set()).add(field["key"])

    for section_id, field in fields_module.iter_fields():
        group = field.get("group")
        if isinstance(group, dict):
            variant = group.get("variant")
            if variant and variant not in fields_module.GROUP_VARIANTS:
                problems.append(
                    f"{section_id}.{field.get('key')}: group variant {variant!r} "
                    f"is not one of {fields_module.GROUP_VARIANTS}"
                )
            # The renderer opens the group while this key is blank, so it has to
            # be a key the group itself holds; anything else never opens or
            # never closes.
            waits_on = group.get("open_until_set")
            if waits_on and waits_on not in group_keys.get((section_id, group.get("id")), set()):
                problems.append(
                    f"{section_id}.{field.get('key')}: open_until_set {waits_on!r} is not "
                    f"a field of group {group.get('id')!r}"
                )

        requires = field.get("requires")
        if isinstance(requires, dict):
            if not requires.get("key"):
                problems.append(
                    f"{section_id}.{field.get('key')}: requires is missing a key"
                )
            mode = requires.get("mode", "block")
            if mode not in fields_module.REQUIRES_MODES:
                problems.append(
                    f"{section_id}.{field.get('key')}: requires mode {mode!r} is "
                    f"not one of {fields_module.REQUIRES_MODES}"
                )

    assert not problems, "\n  ".join(["Malformed descriptors:"] + problems)

    print("  All declared groups and prerequisites are well formed.")
    return True


def _condition_problems(condition, declared_keys, runtime_flags):
    """Describe what is wrong with one ``depends_on``-shaped condition, if anything."""
    if not isinstance(condition, dict):
        return [f"condition {condition!r} is not an object"]
    if "any_of" in condition or "all_of" in condition:
        nested = condition.get("any_of") or condition.get("all_of") or []
        return [problem for item in nested for problem in _condition_problems(item, declared_keys, runtime_flags)]
    if condition.get("flag"):
        if condition["flag"] not in runtime_flags:
            return [f"names runtime flag {condition['flag']!r}, which the settings API never sends"]
        return []
    key = condition.get("key")
    if not key:
        return ["condition names neither a key nor a flag"]
    if key not in declared_keys:
        return [f"condition reads {key!r}, which no field declares"]
    if "equals" not in condition and "not_equals" not in condition:
        return [f"condition on {key!r} has neither equals nor not_equals"]
    return []


def test_label_variants_and_conditional_requirements_are_well_formed():
    """A condition naming the wrong key never holds, and the label never changes."""
    print("\nTesting label_variants and requires.when descriptors...")

    assert_app_version_at_least("0.261.274")

    declared_keys = {
        field["key"] for _section_id, field in fields_module.iter_fields() if field.get("key")
    }
    # The flags a field may depend on; mirrors RUNTIME_FLAGS in test_v2_admin_settings_schema.py.
    runtime_flags = {"mcp_ui_enabled", "content_understanding_supported"}

    problems = []
    variant_count = 0
    conditional_count = 0
    for section_id, field in fields_module.iter_fields():
        name = f"{section_id}.{field.get('key') or field.get('component') or field.get('label')}"

        variants = field.get("label_variants")
        if variants is not None:
            if not isinstance(variants, list) or not variants:
                problems.append(f"{name}: label_variants must be a non-empty list")
                variants = []
            for variant in variants:
                variant_count += 1
                if not isinstance(variant, dict):
                    problems.append(f"{name}: a label variant is not an object")
                    continue
                if not any(isinstance(variant.get(part), str) and variant[part].strip() for part in ("label", "help")):
                    problems.append(f"{name}: a label variant changes neither label nor help")
                if "when" not in variant:
                    problems.append(f"{name}: a label variant has no when condition")
                    continue
                problems.extend(
                    f"{name}: label variant {problem}"
                    for problem in _condition_problems(variant["when"], declared_keys, runtime_flags)
                )

        requires = field.get("requires")
        if isinstance(requires, dict) and "when" in requires:
            conditional_count += 1
            problems.extend(
                f"{name}: requires.when {problem}"
                for problem in _condition_problems(requires["when"], declared_keys, runtime_flags)
            )

    assert variant_count, "No label variants are declared; the Redis key should carry one."
    assert conditional_count, "No conditional prerequisites are declared; Redis should carry one."
    assert not problems, "\n  ".join(["Malformed conditional descriptors:"] + problems)

    print(
        f"  {variant_count} label variant(s) and {conditional_count} conditional "
        "prerequisite(s) read real settings."
    )
    return True


def _required_conditions(dependency):
    """Conditions that must all hold for a dependency to hold, as (key, expected).

    Branches of an ``any_of`` are left out, because none of them is individually
    required, and so is ``not_equals``, which says what a value is not.
    """
    if not dependency:
        return set()
    if isinstance(dependency, list):
        return set().union(*(_required_conditions(item) for item in dependency))
    if "all_of" in dependency:
        return set().union(
            *(_required_conditions(item) for item in dependency["all_of"])
        )
    if "any_of" in dependency or "not_equals" in dependency or not dependency.get("key"):
        return set()
    return {(dependency["key"], repr(dependency.get("equals", True)))}


def test_anchored_groups_hang_off_a_switch_above_them():
    """An anchored panel needs a switch to sit under, and must vanish with it."""
    print("\nTesting anchored groups...")

    problems = []
    anchored = 0
    for section_id, fields in fields_module.get_admin_settings_fields().items():
        anchors_by_group = {}
        for index, field in enumerate(fields):
            group = field.get("group")
            if not isinstance(group, dict):
                continue
            anchor = group.get("anchor")
            anchors_by_group.setdefault(group.get("id"), set()).add(anchor)
            if not anchor:
                continue

            anchored += 1
            name = f"{section_id}.{field.get('key') or field.get('label')}"
            lead = next(
                (earlier for earlier in fields[:index] if earlier.get("key") == anchor),
                None,
            )
            if lead is None:
                problems.append(
                    f"{name}: anchor {anchor!r} is not a field declared earlier in "
                    f"{section_id}, so the panel has no row to sit under"
                )
                continue
            if lead.get("type") != "switch" or lead.get("readonly"):
                problems.append(f"{name}: anchor {anchor!r} is not an editable switch")
            if lead.get("group"):
                problems.append(
                    f"{name}: anchor {anchor!r} is itself grouped; the renderer only "
                    "anchors panels under ungrouped switches"
                )

            # The panel must disappear whenever its switch is off or hidden, and
            # visibility is not transitive, so it carries the switch's own
            # conditions as well as the switch itself.
            required = _required_conditions(field.get("depends_on"))
            expected = {(anchor, repr(True))} | _required_conditions(lead.get("depends_on"))
            missing = sorted(expected - required)
            if missing:
                problems.append(
                    f"{name}: does not require {missing}, so it could show while "
                    f"{anchor!r} is off or hidden"
                )

        for group_id, anchors in anchors_by_group.items():
            if len(anchors) > 1:
                problems.append(
                    f"{section_id}: group {group_id!r} names different anchors "
                    f"{sorted(str(anchor) for anchor in anchors)}, so the panel would "
                    "split depending on which field is read first"
                )

    assert not problems, "\n  ".join(["Malformed anchored groups:"] + problems)

    print(f"  {anchored} anchored field(s) sit under a switch they depend on.")
    return True


def test_on_enable_effects_are_well_formed():
    """A companion naming a missing key or option would be saved and never read."""
    print("\nTesting on_enable descriptors...")

    declared = fields_module.get_declared_setting_keys()
    problems = []
    checked = 0

    for section_id, field in fields_module.iter_fields():
        effect = field.get("on_enable")
        if not effect:
            continue
        checked += 1
        identity = f"{section_id}.{field.get('key')}"

        # Only a switch has an "on", and a mirror cannot be turned on from here.
        if field.get("type") != "switch" or field.get("readonly"):
            problems.append(f"{identity}: on_enable needs an editable switch")
        # The acknowledgement path sets the switch after a dialog, past the place
        # the page applies companions, so the two are not combined.
        if field.get("requires_acknowledgement"):
            problems.append(f"{identity}: on_enable cannot be combined with an acknowledgement")

        companions = effect.get("set") or {}
        if not companions:
            problems.append(f"{identity}: on_enable sets nothing")
        for companion, value in companions.items():
            target = fields_module.get_field_definition(companion)
            if companion not in declared or target is None:
                problems.append(f"{identity}: sets undeclared key {companion!r}")
                continue
            options = [option["value"] for option in target.get("options", [])]
            if options and value not in options:
                problems.append(
                    f"{identity}: sets {companion}={value!r}, which is not one of {options}"
                )

        when = effect.get("when")
        for condition in ([when] if isinstance(when, dict) else when or []):
            if condition.get("key") and condition["key"] not in declared:
                problems.append(f"{identity}: when reads undeclared key {condition['key']!r}")

    assert not problems, "\n  ".join(["Malformed on_enable descriptors:"] + problems)
    assert checked, "No on_enable descriptor was checked; Enhanced extraction should declare one."

    print(f"  {checked} on_enable descriptor(s) are well formed.")
    return True


def test_runtime_flag_conditions_follow_the_flags_given():
    """The server must judge a flag the way the browser does, or not at all."""
    print("\nTesting runtime flag evaluation...")

    evaluate = fields_module.evaluate_dependency
    gated = [
        {"key": "enable_thing", "equals": True},
        {"flag": "content_understanding_supported", "equals": True},
    ]
    read = {"enable_thing": True}.get

    assert evaluate(gated, read, {"content_understanding_supported": True}) is True
    assert evaluate(gated, read, {"content_understanding_supported": False}) is False
    assert evaluate(gated, read, {}) is False, "an absent flag reads as off, as in the browser"
    assert evaluate(
        {"flag": "content_understanding_supported", "equals": False}, read, {}
    ) is True

    # Without flags the server cannot judge the condition, so it does not let it
    # suppress anything -- the same answer _dependency_is_satisfied gives.
    assert evaluate(gated, read) is True
    assert evaluate({"any_of": [{"flag": "mcp_ui_enabled", "equals": True}]}, read) is True

    print("  Flag conditions follow the flags given, and count as met without them.")
    return True


def test_secret_keys_are_discoverable_for_redaction():
    """The settings endpoint needs the list to redact before it responds."""
    print("\nTesting secret key discovery...")

    declared = fields_module.get_secret_setting_keys()
    assert isinstance(declared, set), type(declared)

    for _section_id, field in fields_module.iter_fields():
        if field.get("type") == "secret":
            assert field["key"] in declared, (
                f"{field['key']} is declared as a secret but is not reported by "
                "get_secret_setting_keys(), so it would be sent to the browser "
                "in plain text."
            )

    print(f"  {len(declared)} secret key(s) reported for redaction.")
    return True


def test_undeclared_keys_still_pass_through():
    """The enable_* fallback scan must keep saving while groups are described."""
    print("\nTesting fallback pass-through...")

    normalized, errors, _ = normalize({"enable_something_undescribed": True})
    assert not errors, errors
    assert normalized["enable_something_undescribed"] is True, normalized

    print("  Undeclared keys still save unchanged.")
    return True


if __name__ == "__main__":
    tests = [
        test_declared_types_are_renderable,
        test_redaction_placeholder_matches_the_settings_module,
        test_unchanged_secret_is_dropped_rather_than_written,
        test_changed_secret_is_trimmed_and_bounded,
        test_string_list_round_trips_the_v1_shape,
        test_id_list_accepts_both_stored_and_edited_shapes,
        test_dependency_evaluation_supports_every_declared_shape,
        test_declared_groups_and_requires_are_well_formed,
        test_label_variants_and_conditional_requirements_are_well_formed,
        test_anchored_groups_hang_off_a_switch_above_them,
        test_on_enable_effects_are_well_formed,
        test_runtime_flag_conditions_follow_the_flags_given,
        test_secret_keys_are_discoverable_for_redaction,
        test_undeclared_keys_still_pass_through,
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
