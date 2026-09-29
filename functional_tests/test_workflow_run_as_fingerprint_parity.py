#!/usr/bin/env python3
# test_workflow_run_as_fingerprint_parity.py
"""
Functional test for the workflow editor's Run as fingerprint mirror.
Version: 0.261.201
Implemented in: 0.261.201

This test ensures that the V2 workflow editor's list of Run as fingerprint fields
(application/v2_ui/src/lib/workflowRunAsFingerprint.ts) matches the fields the server
actually hashes in workflow_execution_fingerprint
(application/single_app/functions_m365_workflow_binding.py). The editor uses the list to
warn that saving requires re-approving Run as; when the two drift, the warning would be
missing for a change that clears the approval, or shown for one that does not.

The server side is measured, not transcribed: every candidate field is changed on its own
and kept only when the fingerprint changes.
"""

import ast
import inspect
import re
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "application" / "single_app"))
sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

import functions_m365_workflow_binding as binding  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

MIRROR_TS = REPO_ROOT / "application" / "v2_ui" / "src" / "lib" / "workflowRunAsFingerprint.ts"
AUTHORING_TSX = (
    REPO_ROOT / "application" / "v2_ui" / "src" / "components" / "workflows" / "WorkflowAuthoringHistory.tsx"
)

# Fields a workflow carries that the fingerprint must ignore, probed alongside every other candidate.
KNOWN_UNHASHED_FIELDS = {
    "name",
    "description",
    "is_enabled",
    "error_handling",
    "alert_priority",
    "alert_mode",
    "alert_rules",
    "alert_evaluation",
    "definition_revision",
    "active_run_id",
    "created_at",
    "updated_at",
}


def ts_string_list(source, name):
    """Read a `export const NAME = [ '...', ... ] as const;` string list from TypeScript."""
    match = re.search(rf"export const {name}\s*=\s*\[(.*?)\]\s*as const;", source, re.DOTALL)
    if not match:
        raise AssertionError(f"{name} was not found in {MIRROR_TS.name}")
    return re.findall(r"'([^']+)'", match.group(1))


def ts_string_constant(source, name):
    match = re.search(rf"export const {name}\s*=\s*'([^']+)';", source)
    if not match:
        raise AssertionError(f"{name} was not found in {MIRROR_TS.name}")
    return match.group(1)


def mirror_fields():
    source = MIRROR_TS.read_text(encoding="utf-8")
    base = ts_string_list(source, "WORKFLOW_RUN_AS_FINGERPRINT_BASE_FIELDS")
    optional = ts_string_list(source, "WORKFLOW_RUN_AS_FINGERPRINT_OPTIONAL_FIELDS")
    account = ts_string_constant(source, "WORKFLOW_RUN_AS_FINGERPRINT_ACCOUNT_FIELD")
    return base, optional, account


def authored_fields():
    """The fields the editor can change, read from WORKFLOW_AUTHORED_FIELDS."""
    source = AUTHORING_TSX.read_text(encoding="utf-8")
    match = re.search(r"WORKFLOW_AUTHORED_FIELDS[^=]*=\s*Object\.freeze\(\[(.*?)\]\)", source, re.DOTALL)
    if not match:
        raise AssertionError("WORKFLOW_AUTHORED_FIELDS was not found")
    return set(re.findall(r"'([^']+)'", match.group(1)))


def fingerprint_candidates(extra):
    """Every string the fingerprint function names, plus the given fields."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(binding.workflow_execution_fingerprint)))
    named = {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.isidentifier()
    }
    return named | set(binding.M365_WORKFLOW_FIELDS) | set(extra) | KNOWN_UNHASHED_FIELDS


def measured_server_fields(candidates):
    """The candidates whose value alone changes the server fingerprint."""
    empty = binding.workflow_execution_fingerprint({})
    hashed = set()
    for field in sorted(candidates):
        probed = binding.workflow_execution_fingerprint({field: f"probe-{field}"})
        if probed != empty:
            hashed.add(field)
    return hashed


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.201")
    print("  ok  the configured version includes the Run as fingerprint mirror")


def test_the_base_fields_mirror_m365_workflow_fields():
    base, _optional, _account = mirror_fields()
    server = list(binding.M365_WORKFLOW_FIELDS)
    duplicates = sorted({field for field in base if base.count(field) > 1})
    missing = sorted(set(server) - set(base))
    extra = sorted(set(base) - set(server))
    assert not duplicates, f"the mirror repeats {duplicates}"
    assert not missing and not extra, (
        f"WORKFLOW_RUN_AS_FINGERPRINT_BASE_FIELDS drifted from M365_WORKFLOW_FIELDS: "
        f"missing {missing}, unexpected {extra}"
    )
    print(f"  ok  the {len(base)} base fields match M365_WORKFLOW_FIELDS")


def test_the_mirror_matches_the_measured_fingerprint():
    base, optional, account = mirror_fields()
    mirrored = set(base) | set(optional) | {account}
    candidates = fingerprint_candidates(mirrored | authored_fields())
    measured = measured_server_fields(candidates)
    missing = sorted(measured - mirrored)
    extra = sorted(mirrored - measured)
    assert not missing, f"the server fingerprints {missing}, which the editor mirror does not list"
    assert not extra, f"the editor mirror lists {extra}, which do not change the server fingerprint"
    print(f"  ok  all {len(measured)} fingerprinted fields are mirrored, and nothing else")


def test_the_optional_fields_are_hashed_only_when_present():
    _base, optional, _account = mirror_fields()
    empty = binding.workflow_execution_fingerprint({})
    for field in optional:
        present = binding.workflow_execution_fingerprint({field: None})
        assert present != empty, f"{field} is listed as optional but its presence does not change the fingerprint"
    print(f"  ok  the {len(optional)} optional fields count as soon as they are present")


def test_unhashed_editor_fields_never_need_run_as_approval():
    base, optional, account = mirror_fields()
    mirrored = set(base) | set(optional) | {account}
    authored = authored_fields()
    measured = measured_server_fields(authored)
    unhashed = sorted(authored - measured)
    wrongly_mirrored = sorted(set(unhashed) & mirrored)
    assert "name" in unhashed and "description" in unhashed, unhashed
    assert not wrongly_mirrored, f"{wrongly_mirrored} are mirrored but not hashed"
    print(f"  ok  {len(unhashed)} editor fields, such as {', '.join(unhashed[:3])}, never ask for Run as approval")


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_the_base_fields_mirror_m365_workflow_fields,
    test_the_mirror_matches_the_measured_fingerprint,
    test_the_optional_fields_are_hashed_only_when_present,
    test_unhashed_editor_fields_never_need_run_as_approval,
]


if __name__ == "__main__":
    passed = 0
    for test in TESTS:
        try:
            test()
            passed += 1
        except Exception as error:  # noqa: BLE001 - report and continue to the next check
            print(f"FAIL  {test.__name__}: {error}")

    print(f"\n{passed}/{len(TESTS)} checks passed")
    sys.exit(0 if passed == len(TESTS) else 1)
