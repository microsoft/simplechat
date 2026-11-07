# test_public_document_call_boundary.py
"""
Functional test for the public document management call boundary.
Version: 0.261.133
Implemented in: 0.261.133

The M3B backend suite stubs the shared write primitives in
``functions_documents`` so it can test the public authorization, receipt, and
serialization boundary without re-exercising storage internals already covered
by the group suite. That is a reasonable trade, but it creates one blind spot:
a stub accepts any signature, so a future change to a shared primitive could
break the public wrappers while the stubbed suite stays green.

This pins the boundary itself. Every keyword the public management module
passes to a shared primitive must be one the *real* function accepts.
"""

import ast
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.append(str(Path(__file__).resolve().parent))
from test_support.versioning import assert_app_version_at_least  # noqa: E402


SHARED_PRIMITIVES = {
    "create_document",
    "update_document",
    "delete_document",
    "delete_document_revision",
    "process_document_upload_background",
}


def _parse(name):
    return ast.parse((APP_DIR / name).read_text(encoding="utf-8"))


def real_signatures():
    """Accepted keyword names per shared primitive, or None when it takes **kwargs."""
    signatures = {}
    for node in ast.walk(_parse("functions_documents.py")):
        if isinstance(node, ast.FunctionDef) and node.name in SHARED_PRIMITIVES:
            if node.args.kwarg is not None:
                signatures[node.name] = None
                continue
            signatures[node.name] = {
                argument.arg for argument in (*node.args.args, *node.args.kwonlyargs)
            }
    return signatures


def public_calls():
    """Every call the public management module makes into a shared primitive."""
    calls = []
    for node in ast.walk(_parse("functions_public_document_management.py")):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in SHARED_PRIMITIVES:
            calls.append((
                node.func.id,
                node.lineno,
                {keyword.arg for keyword in node.keywords if keyword.arg is not None},
            ))
    return calls


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.133")


def test_every_shared_primitive_still_exists():
    """A renamed primitive would leave the stubs passing and the app broken."""
    missing = SHARED_PRIMITIVES - set(real_signatures())

    assert missing == set(), f"shared primitives no longer defined: {sorted(missing)}"


def test_public_module_actually_calls_the_shared_primitives():
    """Guards against this test silently passing because the calls moved away."""
    called = {name for name, _line, _keywords in public_calls()}

    assert called, "functions_public_document_management.py calls no shared primitive"


@pytest.mark.parametrize("primitive", sorted(SHARED_PRIMITIVES))
def test_public_calls_use_keywords_the_real_primitive_accepts(primitive):
    signatures = real_signatures()
    accepted = signatures.get(primitive)
    if accepted is None:
        pytest.skip(f"{primitive} accepts **kwargs")

    for name, line, keywords in public_calls():
        if name != primitive:
            continue
        unknown = keywords - accepted
        assert unknown == set(), (
            f"functions_public_document_management.py:{line} passes "
            f"{sorted(unknown)} to {primitive}, which does not accept it"
        )


def test_public_scope_is_first_class_in_the_shared_primitives():
    """Public must be a real branch, not something that rides on **kwargs luck.

    `update_document` takes **kwargs, so a signature check cannot prove it
    handles public scope. It reads `public_workspace_id` explicitly and branches
    on it; pin that so the public wrappers keep a supported path.
    """
    signatures = real_signatures()
    for primitive, accepted in signatures.items():
        if accepted is not None:
            assert "public_workspace_id" in accepted, (
                f"{primitive} no longer accepts public_workspace_id"
            )

    source = (APP_DIR / "functions_documents.py").read_text(encoding="utf-8")
    assert "public_workspace_id = kwargs.get('public_workspace_id')" in source
    assert "is_public_workspace = public_workspace_id is not None" in source


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
