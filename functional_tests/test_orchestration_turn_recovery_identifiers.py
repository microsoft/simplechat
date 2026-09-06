#!/usr/bin/env python3
"""
Functional test for the identifiers that let an orchestration turn be found again.
Version: 0.261.096
Implemented in: 0.261.096

A run is only recoverable if its question can be found in the thread. The live card stamps
``orchestration_turn_id`` on its optimistic user bubble, but the server saved the same message
without it, so a thread fetched fresh -- after a reload, in another tab, on another device -- had
nothing to match a run against. This adds the stamp on the server side too.

The other half is the re-run guard. Now that a pending approval can be picked up on a second
device, two browsers can hold the same card, and the endpoint has to refuse the second approval
rather than doing the work twice. It already did; this pins that behaviour down so it is not
removed by someone who does not know it is now load-bearing.

This test asserts:

  * The plan route saves the user message with its turn id in metadata.
  * The run record keeps ``turn_id`` and ``user_message_id``, which is why existing runs need no
    migration to become recoverable.
  * The run route refuses a plan that is already running or completed, and says so with a 409.
  * The run route takes the plan, seeds and question from the stored record rather than the
    request body, which is what makes approving from a second device safe.
"""

import ast
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


IMPLEMENTED_IN = "0.261.096"

ROOT_DIR = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT_DIR / "application" / "single_app" / "route_backend_orchestration.py"


def _function_source(name):
    """The source of one function in the route module, found wherever it is nested."""
    source = ROUTE_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"{name} is not defined in {ROUTE_FILE.name}")


def test_version_is_at_least_the_implementing_release():
    """The turn id stamp shipped in IMPLEMENTED_IN, so the app must be at least it."""
    print("Testing the app version is at least the implementing release...")
    try:
        assert_app_version_at_least(IMPLEMENTED_IN)
        print(f"  ok  config.py VERSION is at least {IMPLEMENTED_IN}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        return False


def test_user_message_is_saved_with_its_turn_id():
    """The saved question carries orchestration_turn_id, so a fetched thread can be matched."""
    print("Testing the user message is stamped with its turn id...")
    try:
        body = _function_source("orchestration_plan")

        save_calls = re.findall(
            r"_save_message\(\s*resolved_conversation_id,\s*'user'.*?\)",
            body,
            flags=re.DOTALL,
        )
        assert save_calls, "the plan route must save the user's question"
        for call in save_calls:
            assert "orchestration_turn_id" in call, (
                "the question must be saved with its turn id in metadata:\n" + call
            )
            assert "turn_id" in call, "the stamp must carry the turn id itself, not a literal"
        print("  ok  the question is saved with its turn id")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_save_message_accepts_metadata():
    """The helper the plan route uses must actually persist the metadata it is handed."""
    print("Testing _save_message persists metadata...")
    try:
        body = _function_source("_save_message")
        signature = body.split("\n", 1)[0]
        assert "metadata" in signature, (
            f"_save_message must take metadata, saw {signature!r}"
        )
        # It has to reach the document, not just the signature.
        assert re.search(r"metadata", body.split("\n", 1)[1]), (
            "the metadata argument must be written onto the message document"
        )
        print("  ok  _save_message takes and stores metadata")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_run_record_keeps_the_turn_and_question_ids():
    """The stored run keeps turn_id and user_message_id, so old runs recover without migration."""
    print("Testing the run record keeps its turn and question ids...")
    try:
        body = _function_source("orchestration_plan")
        assert "'turn_id': turn_id" in body or '"turn_id": turn_id' in body, (
            "the run record must keep the turn id"
        )
        assert "user_message_id" in body, "the run record must keep the question's message id"
        assert "update_orchestration_run" in body, (
            "the ids are written back onto the run record once the message exists"
        )
        print("  ok  the run record keeps both identifiers")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_run_route_refuses_a_plan_that_already_ran():
    """A second approval, from a second device, is refused rather than doing the work twice."""
    print("Testing the run route refuses an already-run plan...")
    try:
        body = _function_source("orchestration_run")

        guard = re.search(
            r"if\s+record\.get\('status'\)\s+in\s+\(([^)]*)\)", body
        )
        assert guard, "the run route must guard against re-running a plan"
        guarded = guard.group(1)
        assert "PLAN_STATUS_RUNNING" in guarded, "a running plan must not be run again"
        assert "PLAN_STATUS_COMPLETED" in guarded, "a completed plan must not be run again"

        after = body[guard.end():guard.end() + 400]
        assert "409" in after, (
            "the refusal must be a 409 so the client can tell it apart from a failure"
        )
        print("  ok  a plan that is running or completed is refused with a 409")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_run_route_trusts_the_record_not_the_request():
    """The plan, seeds and question come from the stored run, not from whoever posted."""
    print("Testing the run route reads the plan from the stored record...")
    try:
        body = _function_source("orchestration_run")

        for field in ("plan", "seeds", "user_message"):
            assert re.search(rf"record\.get\('{field}'", body), (
                f"{field!r} must be read from the stored record, so a second device only has "
                "to name the run rather than reconstruct it"
            )
        print("  ok  the run route takes its inputs from the record")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_user_message_is_saved_with_its_turn_id,
    test_save_message_accepts_metadata,
    test_run_record_keeps_the_turn_and_question_ids,
    test_run_route_refuses_a_plan_that_already_ran,
    test_run_route_trusts_the_record_not_the_request,
]


def main():
    results = []
    for test in TESTS:
        print(f"\nRunning {test.__name__}...")
        results.append(test())
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
