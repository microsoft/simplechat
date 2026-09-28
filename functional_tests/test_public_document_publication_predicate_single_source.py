# test_public_document_publication_predicate_single_source.py
"""
Functional test pinning the single source of the public "has publication" rule.
Version: 0.261.134
Implemented in: 0.261.134

Whether a public document carries a generated-artifact publication decides two
things that must agree: the publication adapter's own gate, and whether the
read/list projection consults that adapter at all. When the rule lived in two
places, a mirror could silently lose a condition and hide a pending
approve/reject/cancel from a reviewer behind a plain read-only document.

The rule now lives once, in the lightweight policy layer as
``public_document_has_publication``. This pins that:

* the policy layer defines it,
* the collaboration module does not define its own predicate and imports the
  policy one, and
* the publication adapter's ``_has_publication`` delegates to it rather than
  re-implementing the field checks.
"""

import ast
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.append(str(Path(__file__).resolve().parent))
from test_support.versioning import assert_app_version_at_least  # noqa: E402

POLICY = "functions_public_document_policy.py"
COLLABORATION = "functions_public_document_collaboration.py"
PUBLICATION = "functions_public_document_publication.py"
PREDICATE = "public_document_has_publication"


def _parse(name):
    return ast.parse((APP_DIR / name).read_text(encoding="utf-8"))


def _function_defs(module):
    return {
        node.name: node
        for node in ast.walk(_parse(module))
        if isinstance(node, ast.FunctionDef)
    }


def _imported_names(module, from_module):
    names = set()
    for node in ast.walk(_parse(module)):
        if isinstance(node, ast.ImportFrom) and node.module == from_module:
            names.update(alias.name for alias in node.names)
    return names


def _calls_within(func_node):
    return {
        node.func.id
        for node in ast.walk(func_node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.134")


def test_policy_defines_the_predicate():
    assert PREDICATE in _function_defs(POLICY), (
        f"{POLICY} must define {PREDICATE} as the single source of truth"
    )


def test_collaboration_imports_the_policy_predicate():
    imported = _imported_names(COLLABORATION, "functions_public_document_policy")
    assert PREDICATE in imported, (
        f"{COLLABORATION} must import {PREDICATE} from the policy layer"
    )


def test_collaboration_does_not_define_its_own_predicate():
    """A local mirror is exactly the drift this pin exists to forbid."""
    defs = _function_defs(COLLABORATION)
    offenders = {
        name for name in defs
        if "has_publication" in name and name != PREDICATE
    }
    assert offenders == set(), (
        f"{COLLABORATION} must not define its own has-publication predicate; "
        f"found {sorted(offenders)}. Import {PREDICATE} from the policy layer."
    )


def test_publication_adapter_delegates_to_the_policy_predicate():
    defs = _function_defs(PUBLICATION)
    assert "_has_publication" in defs, f"{PUBLICATION} must define _has_publication"

    imported = _imported_names(PUBLICATION, "functions_public_document_policy")
    assert PREDICATE in imported, (
        f"{PUBLICATION} must import {PREDICATE} from the policy layer"
    )

    called = _calls_within(defs["_has_publication"])
    assert PREDICATE in called, (
        f"{PUBLICATION}._has_publication must delegate to {PREDICATE}, "
        "not re-implement the field checks"
    )


def test_predicate_is_semantically_correct():
    """Exercise the real rule so the pin is not purely structural."""
    sys.path.insert(0, str(APP_DIR))
    try:
        from functions_public_document_policy import public_document_has_publication
        from functions_artifact_publication_readiness import PUBLICATION_BINDING
    finally:
        if str(APP_DIR) in sys.path:
            sys.path.remove(str(APP_DIR))

    assert public_document_has_publication({}) is False
    assert public_document_has_publication({"status": "in progress"}) is False
    assert public_document_has_publication({"status": "Pending Approval"}) is True
    assert public_document_has_publication(
        {"generated_artifact_promotion_status": "pending_approval"}
    ) is True
    assert public_document_has_publication(
        {"generated_artifact_promotion_status": "approved"}
    ) is True
    assert public_document_has_publication(
        {"generated_artifact_publication_receipt_id": "receipt-1"}
    ) is True
    assert public_document_has_publication({PUBLICATION_BINDING: {"id": "x"}}) is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
