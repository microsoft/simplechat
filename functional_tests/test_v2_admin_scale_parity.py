#!/usr/bin/env python3
# test_v2_admin_scale_parity.py
"""
Functional test pinning V1/V2 parity for the Admin Settings Scale group.
Version: 0.261.273
Implemented in: 0.261.273

Before this, the Scale group had no declared fields. Its two tabs drew whatever
``enable_*`` booleans the fallback scan matched by word stems, so the Redis
endpoint, port and credential, both cache TTLs, the Cosmos resource target and
every throughput guardrail were unreachable in V2, and the operational surfaces --
Redis Metrics, the Redis Explorer, Document Access Index status, Cosmos maintenance
and the throughput console -- did not exist there at all.

These are the structural checks. They read the two V1 panes and hold the schema to
them: every submitted field is claimed and none is invented; selects, number bounds
and the Redis credential agree; the nesting V1 expresses with enclosing divs and
Jinja blocks is carried on each field, including the index diagnostics V1 shows only
while ``enable_dai_debug`` is set, which V2 offers as a switch under Operations; the
always-on index flags stay uneditable;
defaults and mirrored constants agree with ``functions_cosmos_throughput.py``; and
the V2 surface drives the same admin APIs, with the same request bodies, that V1
does.

What a save does is covered by ``test_v2_admin_scale_normalization.py``, and the
browser logic by ``test_v2_admin_scale_logic.py``.
"""

import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
PANES_DIR = APP_ROOT / "templates" / "admin" / "_panes"
V1_ADMIN_JS = APP_ROOT / "static" / "js" / "admin" / "admin_settings.js"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
PAGE_TSX = V2_SRC / "pages" / "AdminSettingsPage.tsx"
COSMOS_TS = V2_SRC / "lib" / "cosmosThroughput.ts"
MAINTENANCE_TS = V2_SRC / "lib" / "scaleMaintenance.ts"

SCALE_GROUP_ID = "scale"

# The tabs that make up the Scale group, and the sections each contributes. Sourced
# from ADMIN_NAV and verified against it below.
SCALE_PANES = {
    "redis-caching": (
        "redis-cache-section",
        "redis-monitoring-section",
        "conversation-cache-section",
    ),
    "cosmos": (
        "document-access-index-section",
        "cosmos-maintenance-section",
        "cosmos-throughput-section",
        "cosmos-throughput-metrics-table-section",
    ),
}
SCALE_SECTION_IDS = {section for sections in SCALE_PANES.values() for section in sections}

EXPECTED_SECRET_KEYS = {"redis_key"}

# V1 wraps the index diagnostics in this Jinja condition. V2 gates the same fields on the
# same setting, which it declares as a switch under Operations > Debug Logging -- the
# classic page has no control for it.
V1_DAI_DEBUG_CONDITION = "settings.enable_dai_debug"
DAI_DEBUG_KEY = "enable_dai_debug"
DAI_DEBUG_SWITCH_SECTION = "debug-logging-section"

# Forced to True by normalize_document_access_index_required_settings on every read and
# write. A switch for one of these would appear to save and then revert.
ALWAYS_ON_DAI_KEYS = (
    "enable_document_access_index_container",
    "enable_document_access_index_write_through",
    "enable_document_access_index_reads",
    "enable_startup_document_access_index_backfill",
)

REDIS_ON = ("enable_redis_cache", "==", True)
DAI_DEBUG = (DAI_DEBUG_KEY, "==", True)
AUTOMATION_ON = ("cosmos_throughput_autoscale_enabled", "==", True)

# Each entry is the full set of conditions the field carries.
EXPECTED_DEPENDENCY_CHAINS = {
    # V1 wraps these in #redis_cache_settings, hidden while Redis Cache is off.
    "redis_url": {REDIS_ON},
    "redis_service_type": {REDIS_ON},
    "redis_port": {REDIS_ON},
    "redis_auth_type": {REDIS_ON},
    # #redis_key_container is also hidden for managed identity, which has no key.
    "redis_key": {REDIS_ON, ("redis_auth_type", "!=", "managed_identity")},
    # V1 shows these beside a switched-off cache. V2 nests them under their switch, as it
    # nests every setting that only matters while its capability is on.
    "conversation_cache_ttl_seconds": {("enable_conversation_cache", "==", True)},
    "document_access_index_cache_ttl_seconds": {
        DAI_DEBUG,
        ("enable_document_access_index_cache", "==", True),
    },
    "enable_document_access_index_shadow_validation": {DAI_DEBUG},
    "document_access_index_backfill_batch_size": {DAI_DEBUG},
    "document_access_index_repair_batch_size": {DAI_DEBUG},
    "enable_document_access_index_cache": {DAI_DEBUG},
    "enable_startup_app_maintenance": {("enable_app_maintenance", "==", True)},
}

# Monitoring and manual scaling work with automation off, so these are not gated on it.
THROUGHPUT_KEYS_NOT_GATED_ON_AUTOMATION = {
    "cosmos_throughput_autoscale_enabled",
    "cosmos_throughput_container_policies",
}

THROUGHPUT_ENVIRONMENT = (
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_RESOURCE_GROUP",
    "AZURE_COSMOS_ACCOUNT_NAME",
    "AZURE_COSMOS_DATABASE_NAME",
)

# Each admin API the Scale surface calls: the route, its method, the V2 source that
# calls it, and the call target as written there.
SCALE_ROUTES = (
    (
        "/api/admin/settings/redis-monitoring/status",
        "GET",
        "components/admin/RedisMonitoringPanel.tsx",
        "STATUS_PATH",
    ),
    (
        "/api/admin/settings/redis-explorer/keys",
        "GET",
        "components/admin/RedisExplorer.tsx",
        "`${KEYS_PATH}?",
    ),
    (
        "/api/admin/settings/redis-explorer/value",
        "POST",
        "components/admin/RedisExplorer.tsx",
        "VALUE_PATH",
    ),
    (
        "/api/admin/settings/app-maintenance/status",
        "GET",
        "stores/scaleStatusStore.ts",
        "MAINTENANCE_STATUS_PATH",
    ),
    (
        "/api/admin/settings/app-maintenance/run",
        "POST",
        "components/admin/CosmosMaintenancePanel.tsx",
        "RUN_PATH",
    ),
    (
        "/api/admin/settings/app-maintenance/run",
        "POST",
        "components/admin/DocumentAccessIndexPanel.tsx",
        "RUN_PATH",
    ),
    (
        "/api/admin/settings/cosmos-throughput/status",
        "GET",
        "stores/scaleStatusStore.ts",
        "`${THROUGHPUT_PATH}/status`",
    ),
    (
        "/api/admin/settings/cosmos-throughput/validate-access",
        "POST",
        "stores/scaleStatusStore.ts",
        "`${THROUGHPUT_PATH}/validate-access`",
    ),
    (
        "/api/admin/settings/cosmos-throughput/scale",
        "POST",
        "stores/scaleStatusStore.ts",
        "`${THROUGHPUT_PATH}/scale`",
    ),
    (
        "/api/admin/settings/cosmos-throughput/convert-autoscale",
        "POST",
        "stores/scaleStatusStore.ts",
        "`${THROUGHPUT_PATH}/convert-autoscale`",
    ),
)

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")
JINJA_BLOCK_RE = re.compile(r"\{%-?\s*(if|endif|for|endfor)\b(.*?)-?%\}", re.DOTALL)

OPTION_RE = re.compile(r'<option value="([^"]*)"')
SELECT_BLOCK_RE = re.compile(
    r'<select[^>]*\sname="(?P<name>[^"]+)"(?P<body>.*?)</select>',
    re.DOTALL,
)
INPUT_RE = re.compile(r"<input(?P<attrs>[^>]*)>", re.DOTALL)
ATTR_RE = re.compile(r'(\w[\w-]*)="([^"]*)"')

fields_module = import_app_module("admin_settings_fields")
throughput_module = import_app_module("functions_cosmos_throughput")


def read_text(path):
    """Return a file's text, failing clearly when it has moved."""
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def read_pane(pane_id):
    """Return the raw markup for one Admin Settings pane."""
    return read_text(PANES_DIR / f"{pane_id}.html")


def collect_pane_field_names(markup):
    """Return literal form field names submitted by a pane."""
    return {name for name in FIELD_NAME_RE.findall(markup) if not JINJA_RE.search(name)}


def collect_conditional_field_names(markup, condition):
    """Return field names that only render inside ``{% if <condition> %}`` blocks.

    Blocks nest -- a checkbox inside the debug block carries its own
    ``{% if ... %}checked{% endif %}`` -- so tags are matched with a stack rather than
    by the nearest ``endif``.
    """
    names = set()
    stack = []
    for match in JINJA_BLOCK_RE.finditer(markup):
        tag, expression = match.group(1), match.group(2).strip()
        if tag in ("if", "for"):
            stack.append((tag, expression, match.end()))
            continue
        assert stack, f"Unbalanced {{% {tag} %}} in the pane markup"
        opened_tag, opened_expression, start = stack.pop()
        if opened_tag == "if" and opened_expression == condition:
            names |= collect_pane_field_names(markup[start:match.start()])
    assert not stack, "Unclosed Jinja block in the pane markup"
    return names


def scale_schema_fields():
    """Return ``{key: field}`` for every keyed field the Scale sections declare."""
    return {
        field["key"]: field
        for section_id, field in fields_module.iter_fields()
        if section_id in SCALE_SECTION_IDS and field.get("key")
    }


def scale_schema_entries():
    """Return ``(section_id, field)`` for every Scale declaration, keyed or not."""
    return [
        (section_id, field)
        for section_id, field in fields_module.iter_fields()
        if section_id in SCALE_SECTION_IDS
    ]


def dependency_conditions(field):
    """Return ``(subject, operator, value)`` for each condition a field carries."""
    conditions = set()
    for condition in fields_module.iter_field_dependencies(field):
        if condition.get("flag"):
            conditions.add((f"flag:{condition['flag']}", "==", condition.get("equals", True)))
        elif "not_equals" in condition:
            conditions.add((condition["key"], "!=", condition["not_equals"]))
        else:
            conditions.add((condition["key"], "==", condition.get("equals", True)))
    return conditions


@contextmanager
def without_environment(names):
    """Clear environment variables for the duration, restoring them afterwards."""
    saved = {name: os.environ.pop(name) for name in names if name in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def read_ts_number(source, name):
    match = re.search(rf"export const {name} = (\d+);", source)
    assert match, f"cosmosThroughput.ts no longer exports {name} as a number literal"
    return int(match.group(1))


def read_ts_string(source, name):
    """Read a string constant written as one literal or several joined with ``+``."""
    match = re.search(rf"export const {name} =(.*?);\n", source, re.DOTALL)
    assert match, f"cosmosThroughput.ts no longer exports {name}"
    return "".join(re.findall(r"'([^']*)'", match.group(1)))


def read_ts_string_list(source, name):
    match = re.search(rf"export const {name} = \[(.*?)\] as const;", source, re.DOTALL)
    assert match, f"cosmosThroughput.ts no longer exports {name} as a const array"
    return re.findall(r"'([^']+)'", match.group(1))


def read_route_decorators(source, path):
    """Return ``(methods, decorator text)`` for one admin route, or ``None``."""
    match = re.search(
        rf"@bp\.route\('{re.escape(path)}', methods=\[(?P<methods>[^\]]*)\]\)"
        r"(?P<decorators>.*?)\n\s*def ",
        source,
        re.DOTALL,
    )
    if not match:
        return None
    methods = set(re.findall(r"'([A-Z]+)'", match.group("methods")))
    return methods, match.group("decorators")


def parse_object_literal_pairs(body):
    """Return ``{key: value}`` from a flat JavaScript object literal body."""
    pairs = {}
    for key, value in re.findall(r"(\w+)\s*:\s*([\w.]+)", body):
        pairs[key] = {"true": True, "false": False}.get(value, value)
    return pairs


def test_scale_panes_match_navigation():
    """The panes this test reads must be the ones ADMIN_NAV puts in the group."""
    print("Testing Scale pane list against ADMIN_NAV...")

    assert_app_version_at_least("0.261.273")

    group = next((g for g in ADMIN_NAV if g["id"] == SCALE_GROUP_ID), None)
    assert group, "ADMIN_NAV no longer defines a 'scale' group."

    nav_tabs = {tab["id"]: tuple(s["id"] for s in tab["sections"]) for tab in group["tabs"]}
    assert nav_tabs == SCALE_PANES, (
        "The Scale group's tabs or sections changed. Update SCALE_PANES and the "
        f"schema together.\n  ADMIN_NAV: {nav_tabs}\n  test: {SCALE_PANES}"
    )

    print(f"  {len(nav_tabs)} tab(s) and their sections match ADMIN_NAV.")
    return True


def test_every_v1_scale_field_is_claimed():
    """A field only V1 has is a setting the V2 surface cannot reach."""
    print("\nTesting that every V1 Scale field is claimed by the schema...")

    claimed = fields_module.get_legacy_field_names()
    excused = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)

    unclaimed = []
    total = 0
    for pane_id in SCALE_PANES:
        for name in sorted(collect_pane_field_names(read_pane(pane_id))):
            total += 1
            if name not in claimed and name not in excused:
                unclaimed.append(f"{pane_id}.html: {name}")

    assert not unclaimed, (
        "These fields exist in the server-rendered Scale panes but nothing in "
        "admin_settings_fields.py claims them, so they are missing from the V2 admin "
        "surface. Declare each one, or record why it has no V2 equivalent in "
        "LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT:\n  " + "\n  ".join(unclaimed)
    )

    print(f"  All {total} V1 Scale field(s) are claimed by the schema.")
    return True


def test_schema_does_not_invent_scale_fields():
    """A V2 field with no V1 counterpart writes a setting nothing else reads."""
    print("\nTesting that the schema does not invent Scale fields...")

    pane_fields = set()
    for pane_id in SCALE_PANES:
        pane_fields |= collect_pane_field_names(read_pane(pane_id))

    invented = []
    for key, field in sorted(scale_schema_fields().items()):
        legacy_names = fields_module.LEGACY_FIELD_NAMES.get(key, [key])
        if any(name in pane_fields for name in legacy_names):
            continue
        if key in fields_module.V2_ONLY_FIELDS:
            continue
        invented.append(f"{key} (type {field.get('type')})")

    assert not invented, (
        "These schema fields have no counterpart in the server-rendered Scale panes, "
        "so saving them would write settings the rest of the application never "
        "reads. Remove them, or record the reason in V2_ONLY_FIELDS:\n  "
        + "\n  ".join(invented)
    )

    print("  Every Scale schema field maps back to a V1 field.")
    return True


def test_redis_credential_is_a_secret():
    """A credential declared as text is a credential sent to the browser."""
    print("\nTesting that the Redis credential is declared as a secret...")

    declared_secrets = fields_module.get_secret_field_keys()
    missing = sorted(EXPECTED_SECRET_KEYS - declared_secrets)

    assert not missing, (
        "These settings hold credentials but are not declared with the 'secret' type, "
        "so the V2 settings payload would carry their stored value to the browser:\n  "
        + "\n  ".join(missing)
    )

    # The key field is relabelled rather than duplicated in Key Vault mode, because it
    # is the same stored setting either way.
    redis_key = scale_schema_fields()["redis_key"]
    variants = redis_key.get("label_variants") or []
    assert any(
        variant.get("when") == {"key": "redis_auth_type", "equals": "key_vault"}
        for variant in variants
    ), "redis_key should read as the Key Vault secret name while Key Vault auth is chosen."

    print("  redis_key is a secret, relabelled for Key Vault authentication.")
    return True


def test_select_options_match_v1():
    """A select offering different values in each interface stores different data."""
    print("\nTesting Scale select option values against V1...")

    schema_fields = scale_schema_fields()

    checked = 0
    mismatches = []
    for pane_id in SCALE_PANES:
        for match in SELECT_BLOCK_RE.finditer(read_pane(pane_id)):
            name = match.group("name")
            field = schema_fields.get(name)
            if not field:
                mismatches.append(f"{name}: a V1 select with no schema field")
                continue
            checked += 1
            v1_values = OPTION_RE.findall(match.group("body"))
            v2_values = [option["value"] for option in field.get("options", [])]
            if v1_values != v2_values:
                mismatches.append(
                    f"{name}: V1 offers {v1_values}, schema offers {v2_values}"
                )

    assert not mismatches, (
        "These selects do not offer the same values, in the same order, in both "
        "interfaces:\n  " + "\n  ".join(mismatches)
    )
    assert checked, "No Scale selects were found; the pane parsing likely broke."

    print(f"  {checked} select(s) offer identical values in both interfaces.")
    return True


def test_number_bounds_match_v1():
    """A bound only one interface enforces lets a value through the other."""
    print("\nTesting Scale number bounds against V1...")

    schema_fields = scale_schema_fields()

    checked = 0
    mismatches = []
    for pane_id in SCALE_PANES:
        for match in INPUT_RE.finditer(read_pane(pane_id)):
            attrs = dict(ATTR_RE.findall(match.group("attrs")))
            if attrs.get("type") != "number":
                continue
            name = attrs.get("name")
            field = schema_fields.get(name)
            if field is None:
                mismatches.append(f"{name}: a V1 number input with no schema field")
                continue
            if field.get("type") != "number":
                # Checked separately below: the port is text so a blank stays blank.
                continue

            checked += 1
            for bound in ("min", "max", "step"):
                v1_bound = attrs.get(bound)
                v2_bound = field.get(bound)
                if v1_bound is None and v2_bound is None:
                    continue
                if v1_bound is None or v2_bound is None or int(v1_bound) != v2_bound:
                    mismatches.append(
                        f"{name}: V1 {bound}={v1_bound}, schema {bound}={v2_bound}"
                    )

    assert not mismatches, (
        "These number controls do not share bounds across the two interfaces:\n  "
        + "\n  ".join(mismatches)
    )

    print(f"  {checked} number control(s) share identical bounds.")
    return True


def test_redis_port_enforces_the_v1_range():
    """The port is declared as text, so its range lives in its validator."""
    print("\nTesting the Redis port range against V1...")

    markup = read_pane("redis-caching")
    port_input = next(
        dict(ATTR_RE.findall(match.group("attrs")))
        for match in INPUT_RE.finditer(markup)
        if 'name="redis_port"' in match.group("attrs")
    )
    low, high = int(port_input["min"]), int(port_input["max"])

    validate = fields_module._validate_redis_port
    assert validate(str(low)) == (str(low), None), validate(str(low))
    assert validate(str(high)) == (str(high), None), validate(str(high))
    assert validate(str(low - 1))[1], f"{low - 1} should be refused, as V1 refuses it"
    assert validate(str(high + 1))[1], f"{high + 1} should be refused, as V1 refuses it"
    # Blank means "use the port for the selected service", in both interfaces.
    assert validate("") == ("", None), validate("")

    field = scale_schema_fields()["redis_port"]
    assert field.get("type") == "text", (
        "redis_port must stay text: the connection test calls .strip() on it and a "
        "blank value has to survive a save."
    )

    print(f"  The port accepts {low}-{high} or blank, matching V1.")
    return True


def test_dependency_chains_are_complete():
    """A flat list has to carry every gate V1 expressed as a nested block."""
    print("\nTesting Scale field dependency chains...")

    schema_fields = scale_schema_fields()

    expected = dict(EXPECTED_DEPENDENCY_CHAINS)
    for key in throughput_module.COSMOS_THROUGHPUT_SETTING_KEYS:
        if key not in THROUGHPUT_KEYS_NOT_GATED_ON_AUTOMATION:
            # V1 hides #cosmos-throughput-automation-settings until automation is on.
            expected[key] = {AUTOMATION_ON}

    problems = []
    for key, conditions in sorted(expected.items()):
        field = schema_fields.get(key)
        if field is None:
            problems.append(f"{key}: not declared in a Scale section")
            continue
        actual = dependency_conditions(field)
        if actual != conditions:
            problems.append(f"{key}: expected {sorted(conditions)}, found {sorted(actual)}")

    for key in THROUGHPUT_KEYS_NOT_GATED_ON_AUTOMATION:
        field = schema_fields.get(key)
        if field is not None and dependency_conditions(field):
            problems.append(
                f"{key}: gated, but monitoring and manual scaling work with automation off"
            )

    assert not problems, (
        "The server-rendered page nests these controls inside enclosing blocks, so "
        "each gate has to be declared on the field itself for V2 to hide it in the "
        "same situations:\n  " + "\n  ".join(problems)
    )

    print(f"  All {len(expected)} dependency chain(s) are complete.")
    return True


def test_index_diagnostics_follow_the_debug_flag():
    """V1 renders the index diagnostics only while enable_dai_debug is set."""
    print("\nTesting the Document Access Index diagnostics gate...")

    gated_in_v1 = collect_conditional_field_names(read_pane("cosmos"), V1_DAI_DEBUG_CONDITION)
    assert gated_in_v1, "No fields were found inside the V1 debug block; parsing broke."

    excused = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)
    schema_fields = scale_schema_fields()

    problems = []
    for name in sorted(gated_in_v1):
        if name in excused:
            continue
        field = schema_fields.get(name)
        if field is None:
            problems.append(f"{name}: inside V1's debug block but not declared")
            continue
        if DAI_DEBUG not in dependency_conditions(field):
            problems.append(f"{name}: inside V1's debug block but not gated on {DAI_DEBUG_KEY}")

    for key, field in sorted(schema_fields.items()):
        if DAI_DEBUG in dependency_conditions(field) and key not in gated_in_v1:
            problems.append(f"{key}: gated on {DAI_DEBUG_KEY}, but V1 always shows it")

    # V1 never offers a control for the flag. V2 offers exactly one, under Operations,
    # recorded as V2-only, and never inside Scale, which only reads it.
    for pane_id in SCALE_PANES:
        if f'name="{DAI_DEBUG_KEY}"' in read_pane(pane_id):
            problems.append(f"{pane_id}.html: renders a control for {DAI_DEBUG_KEY}")
    owners = [
        (section_id, field)
        for section_id, field in fields_module.iter_fields()
        if field.get("key") == DAI_DEBUG_KEY
    ]
    if [section_id for section_id, _field in owners] != [DAI_DEBUG_SWITCH_SECTION]:
        problems.append(
            f"{DAI_DEBUG_KEY}: declared in {[section_id for section_id, _field in owners]}, "
            f"expected only {DAI_DEBUG_SWITCH_SECTION}"
        )
    elif owners[0][1].get("type") != "switch":
        problems.append(f"{DAI_DEBUG_KEY}: declared as {owners[0][1].get('type')!r}, expected a switch")
    if not fields_module.V2_ONLY_FIELDS.get(DAI_DEBUG_KEY):
        problems.append(f"{DAI_DEBUG_KEY}: not recorded in V2_ONLY_FIELDS, though V1 has no control")
    if DAI_DEBUG_KEY in fields_module.SUPPRESSED_CAPABILITY_KEYS:
        problems.append(f"{DAI_DEBUG_KEY}: suppressed, though it is declared as a switch")

    assert not problems, (
        "The index diagnostics no longer follow the debug flag the way V1 does:\n  "
        + "\n  ".join(problems)
    )

    print(f"  {len(gated_in_v1)} V1 diagnostic field(s) follow {DAI_DEBUG_KEY}.")
    return True


def test_always_on_index_flags_are_not_editable():
    """A switch over a value the settings layer forces would revert on every save."""
    print("\nTesting the always-on Document Access Index flags...")

    settings_source = read_text(APP_ROOT / "functions_settings.py")
    forced = re.search(
        r"def normalize_document_access_index_required_settings\(settings\):(.*?)\n\ndef ",
        settings_source,
        re.DOTALL,
    )
    assert forced, "normalize_document_access_index_required_settings has moved or been renamed."

    editable = {
        field["key"]
        for _section_id, field in fields_module.iter_fields()
        if field.get("key") and not field.get("readonly")
    }

    problems = []
    for key in ALWAYS_ON_DAI_KEYS:
        if f"'{key}': True" not in forced.group(1):
            problems.append(f"{key}: no longer forced on, so it may need a real control")
        if key in editable:
            problems.append(f"{key}: declared as an editable field")
        if key not in fields_module.SUPPRESSED_CAPABILITY_KEYS:
            problems.append(f"{key}: not suppressed, so the fallback scan draws a switch")

    assert not problems, "The always-on index flags are mishandled:\n  " + "\n  ".join(problems)

    print(f"  All {len(ALWAYS_ON_DAI_KEYS)} always-on flag(s) stay uneditable.")
    return True


def test_every_throughput_setting_is_declared():
    """A throughput setting V2 cannot edit is one only the classic page can change."""
    print("\nTesting that every Cosmos throughput setting is declared...")

    declared = set(scale_schema_fields())
    missing = sorted(set(throughput_module.COSMOS_THROUGHPUT_SETTING_KEYS) - declared)

    assert not missing, (
        "COSMOS_THROUGHPUT_SETTING_KEYS lists settings the Scale schema does not "
        "declare:\n  " + "\n  ".join(missing)
    )

    print(f"  All {len(throughput_module.COSMOS_THROUGHPUT_SETTING_KEYS)} throughput setting(s) are declared.")
    return True


def test_throughput_defaults_match_the_application():
    """A declared default that differs from the application's misreports an unset value."""
    print("\nTesting Cosmos throughput defaults against functions_cosmos_throughput...")

    # The resource defaults read App Service settings. Cleared, they are the values a
    # fresh deployment without those settings starts from.
    with without_environment(THROUGHPUT_ENVIRONMENT):
        defaults = throughput_module.get_default_cosmos_throughput_settings()

    problems = []
    checked = 0
    for key, field in sorted(scale_schema_fields().items()):
        if not key.startswith("cosmos_throughput_") or field.get("type") == "component":
            continue
        checked += 1
        if "default" not in field:
            problems.append(f"{key}: declares no default")
        elif field["default"] != defaults.get(key):
            problems.append(
                f"{key}: schema default {field['default']!r}, application default "
                f"{defaults.get(key)!r}"
            )

    assert not problems, (
        "These throughput defaults disagree with get_default_cosmos_throughput_settings:\n  "
        + "\n  ".join(problems)
    )

    print(f"  {checked} throughput default(s) match the application.")
    return True


def test_mirrored_constants_agree():
    """The schema and the browser copy service limits they cannot import."""
    print("\nTesting constants mirrored from functions_cosmos_throughput...")

    ts_source = read_text(COSMOS_TS)
    module = throughput_module

    pairs = (
        (
            "admin_settings_fields.COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU",
            fields_module.COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU,
            module.COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU,
        ),
        (
            "admin_settings_fields.COSMOS_THROUGHPUT_MIN_RU",
            fields_module.COSMOS_THROUGHPUT_MIN_RU,
            module.COSMOS_THROUGHPUT_DEFAULT_MIN_RU,
        ),
        (
            "admin_settings_fields.COSMOS_THROUGHPUT_DEFAULT_DATABASE_NAME",
            fields_module.COSMOS_THROUGHPUT_DEFAULT_DATABASE_NAME,
            module.DEFAULT_COSMOS_DATABASE_NAME,
        ),
        (
            "cosmosThroughput.ts COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU",
            read_ts_number(ts_source, "COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU"),
            module.COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU,
        ),
        (
            "cosmosThroughput.ts COSMOS_THROUGHPUT_AUTOSCALE_MIN_RU",
            read_ts_number(ts_source, "COSMOS_THROUGHPUT_AUTOSCALE_MIN_RU"),
            module.COSMOS_THROUGHPUT_AUTOSCALE_MIN_RU,
        ),
        (
            "cosmosThroughput.ts COSMOS_THROUGHPUT_MANUAL_MIN_RU",
            read_ts_number(ts_source, "COSMOS_THROUGHPUT_MANUAL_MIN_RU"),
            module.COSMOS_THROUGHPUT_MANUAL_MIN_RU,
        ),
        (
            "cosmosThroughput.ts COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE",
            read_ts_string(ts_source, "COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE"),
            module.COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE,
        ),
        (
            "cosmosThroughput.ts COSMOS_THROUGHPUT_SETTING_KEYS",
            read_ts_string_list(ts_source, "COSMOS_THROUGHPUT_SETTING_KEYS"),
            list(module.COSMOS_THROUGHPUT_SETTING_KEYS),
        ),
        (
            "cosmosThroughput.ts COSMOS_POLICY_RUNTIME_FIELDS",
            read_ts_string_list(ts_source, "COSMOS_POLICY_RUNTIME_FIELDS"),
            list(module.COSMOS_THROUGHPUT_POLICY_RUNTIME_FIELDS),
        ),
    )

    drift = [
        f"{name}: {mirrored!r} != {source!r}"
        for name, mirrored, source in pairs
        if mirrored != source
    ]
    assert not drift, (
        "These copies no longer match functions_cosmos_throughput.py:\n  " + "\n  ".join(drift)
    )

    print(f"  All {len(pairs)} mirrored constant(s) agree.")
    return True


def test_v2_calls_the_admin_routes_v1_uses():
    """A renamed route or a changed method would break the V2 panels silently."""
    print("\nTesting the admin APIs the Scale surface calls...")

    routes_source = read_text(APP_ROOT / "route_backend_settings.py")

    problems = []
    for path, method, relative, target in SCALE_ROUTES:
        route = read_route_decorators(routes_source, path)
        if route is None:
            problems.append(f"{path}: no such route in route_backend_settings.py")
            continue
        methods, decorators = route
        if method not in methods:
            problems.append(f"{path}: accepts {sorted(methods)}, the V2 surface sends {method}")
        for decorator in ("@swagger_route(", "@login_required", "@admin_required"):
            if decorator not in decorators:
                problems.append(f"{path}: missing {decorator}")

        source = read_text(V2_SRC / relative)
        if path.split("/api/admin/settings/", 1)[1].split("/", 1)[0] not in source:
            problems.append(f"{relative}: does not reference {path}")
        call = re.compile(rf"api\.{method.lower()}<[^>]*>\(\s*{re.escape(target)}")
        if not call.search(source):
            problems.append(f"{relative}: no api.{method.lower()}(...) call to {target}")

    assert not problems, (
        "The Scale surface and the admin routes it calls disagree:\n  " + "\n  ".join(problems)
    )

    print(f"  All {len(SCALE_ROUTES)} call(s) reach an admin-guarded route with the right method.")
    return True


def test_maintenance_runs_send_the_v1_request_bodies():
    """A run body V1 does not send asks the maintenance job for something untested."""
    print("\nTesting the maintenance run request bodies against V1...")

    v1_source = read_text(V1_ADMIN_JS)
    v1_bodies = []
    for match in re.finditer(r"fetch\('/api/admin/settings/app-maintenance/run'", v1_source):
        body = re.search(r"JSON\.stringify\(\{(.*?)\}\)", v1_source[match.end():], re.DOTALL)
        assert body, "A V1 maintenance run has no JSON body; the parsing broke."
        v1_bodies.append(parse_object_literal_pairs(body.group(1)))
    assert v1_bodies, "No V1 maintenance runs were found; the parsing broke."

    ts_source = read_text(MAINTENANCE_TS)
    block = re.search(
        r"export const MAINTENANCE_RUN_PAYLOADS = \{(.*?)\n\} as const;", ts_source, re.DOTALL
    )
    assert block, "scaleMaintenance.ts no longer exports MAINTENANCE_RUN_PAYLOADS."
    v2_payloads = {
        name: parse_object_literal_pairs(body)
        for name, body in re.findall(r"(\w+): \{(.*?)\}", block.group(1), re.DOTALL)
    }
    assert v2_payloads, "No V2 maintenance payloads were parsed."

    routes_source = read_text(APP_ROOT / "route_backend_settings.py")
    handler = re.search(
        r"def run_app_maintenance_admin\(\):(.*?)\n    @bp\.route", routes_source, re.DOTALL
    )
    assert handler, "run_app_maintenance_admin has moved or been renamed."
    read_keys = set(re.findall(r"payload\.get\('([a-z_]+)'", handler.group(1)))
    read_keys |= set(re.findall(r"'([a-z_]+)' in payload", handler.group(1)))

    problems = []
    for name, payload in sorted(v2_payloads.items()):
        unread = sorted(set(payload) - read_keys)
        if unread:
            problems.append(f"{name}: sends {unread}, which the run route never reads")
        if not any(set(body) == set(payload) for body in v1_bodies):
            problems.append(f"{name}: matches no request V1 sends")

    for body in v1_bodies:
        matching = [payload for payload in v2_payloads.values() if set(payload) == set(body)]
        if not matching:
            problems.append(f"V1 run {sorted(body)}: has no V2 equivalent")
            continue
        for key, value in body.items():
            if isinstance(value, bool):
                if any(payload[key] != value for payload in matching):
                    problems.append(f"V1 run {sorted(body)}: V2 sends a different {key}")
            elif {payload[key] for payload in matching} != {True, False}:
                # V1 passes a variable here, such as applyChanges or reset, so V2 needs
                # an action for each value.
                problems.append(f"V1 run {sorted(body)}: V2 does not offer both values of {key}")

    assert not problems, (
        "The V2 maintenance runs differ from the V1 ones:\n  " + "\n  ".join(problems)
    )

    print(f"  {len(v2_payloads)} V2 run(s) cover all {len(v1_bodies)} V1 request bodies.")
    return True


def test_settings_api_sends_the_scale_context():
    """The page reads the resolved Cosmos target from the GET."""
    print("\nTesting the V2 settings GET for Scale context...")

    source = read_text(APP_ROOT / "route_backend_v2.py")

    missing = []
    for _section_id, field in scale_schema_entries():
        source_key = field.get("status_source")
        if source_key and f'"{source_key}"' not in source:
            missing.append(source_key)
    assert not missing, (
        "These Scale status readouts are declared but the settings GET never builds "
        f"them: {missing}"
    )
    assert "def _build_cosmos_throughput_readout(" in source, (
        "The saved throughput target readout is built by _build_cosmos_throughput_readout."
    )

    print("  The GET sends every declared Scale readout.")
    return True


def test_every_scale_component_has_a_renderer():
    """A declared component with no branch in the page renders nothing at all."""
    print("\nTesting that every Scale component is rendered...")

    page = read_text(PAGE_TSX)
    components = sorted(
        {field["component"] for _section_id, field in scale_schema_entries() if field.get("component")}
    )
    missing = [name for name in components if f"case '{name}':" not in page]

    assert not missing, (
        "These Scale components are declared but AdminSettingsPage.tsx has no branch "
        f"for them: {missing}"
    )

    print(f"  All {len(components)} Scale component(s) have a renderer.")
    return True


if __name__ == "__main__":
    tests = [
        test_scale_panes_match_navigation,
        test_every_v1_scale_field_is_claimed,
        test_schema_does_not_invent_scale_fields,
        test_redis_credential_is_a_secret,
        test_select_options_match_v1,
        test_number_bounds_match_v1,
        test_redis_port_enforces_the_v1_range,
        test_dependency_chains_are_complete,
        test_index_diagnostics_follow_the_debug_flag,
        test_always_on_index_flags_are_not_editable,
        test_every_throughput_setting_is_declared,
        test_throughput_defaults_match_the_application,
        test_mirrored_constants_agree,
        test_v2_calls_the_admin_routes_v1_uses,
        test_maintenance_runs_send_the_v1_request_bodies,
        test_settings_api_sends_the_scale_context,
        test_every_scale_component_has_a_renderer,
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
