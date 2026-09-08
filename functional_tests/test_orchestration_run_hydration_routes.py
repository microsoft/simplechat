# test_orchestration_run_hydration_routes.py
"""
Functional test for the orchestration run hydration endpoints and their projections.
Version: 0.261.105
Implemented in: 0.261.099

Orchestration runs have always been persisted, but nothing in the browser read them back, so a
conversation opened after a reload or on another device showed no history for work that plainly
happened. The read path that fixes that is two endpoints and the projections behind them:

  * ``GET /api/v2/orchestration/runs`` lists a conversation's runs, lean by default. The stored
    record holds an entire plan and the seeds that constrained it; the map view draws one line per
    run and needs neither. Listing twenty-five runs must not put twenty-five plans on the wire.
  * ``GET /api/v2/orchestration/runs/<run_id>`` returns one run with its plan, for the single run
    the user actually opened.

This test asserts the projections are an allowlist -- so a field added to the stored record is not
published by accident -- that the detail projection agrees with the listing about everything except
the plan, and that both routes are registered with the app's standard authentication decorators.
"""

import ast
import re
import sys
from pathlib import Path
from copy import deepcopy

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.orchestration_research import _definitions  # noqa: E402
from test_support.app_stubs import stubbed_config  # noqa: E402
from test_support.orchestration_revisions import AtomicMemoryContainer  # noqa: E402


IMPLEMENTED_IN = "0.261.099"

ROOT_DIR = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT_DIR / "application" / "single_app" / "route_backend_orchestration.py"

# A stored run carrying both the fields the client needs and the ones it must never be handed.
STORED_RUN = {
    "id": "run-1",
    "run_id": "run-1",
    "conversation_id": "conv-1",
    "user_id": "user-1",
    "turn_id": "turn-1",
    "turn_index": "3",
    "status": "completed",
    "created_at": "2026-01-05T10:00:00Z",
    "started_at": "2026-01-05T10:00:01Z",
    "completed_at": "2026-01-05T10:02:00Z",
    "error": None,
    "user_message": "Reconcile the quarterly numbers",
    "user_message_id": "msg-1",
    "assistant_message_id": "msg-2",
    "revision": "2",
    "plan_summary": {
        "run_id": "run-1",
        "intent_summary": "Reconcile the quarterly numbers",
        "step_count": 2,
    },
    "capabilities_used": ["search_documents", "respond"],
    "artifacts": [{"id": "a1"}, {"id": "a2"}],
    "approval": {"mode": "manual", "state": "approved", "approved_by": "user-1"},
    # Heavy or internal, and none of it belongs in a listing.
    "plan": {"steps": [{"step_id": "s1"}], "inputs": {"documents": [{"document_id": "d1"}]}},
    "seeds": {"selected_document_ids": ["d1"], "internal_hint": "do not publish"},
    # These three were once stripped by name in the route. The allowlist replaced that
    # blocklist, so they are kept here to prove the replacement is not a regression.
    "conversation_context": {"messages": [{"id": "msg-0", "content": "private"}]},
    "request_resolution": {"resolved_from": "internal"},
    "user_message_fingerprint": "fingerprint-internal",
    "_rid": "cosmos-internal",
    "_etag": "etag-internal",
}


def _load_projections():
    """Import the two projection helpers without importing the whole Flask app.

    ``route_backend_orchestration`` pulls in Cosmos clients and Azure settings at import time,
    which a functional test has no business requiring. The helpers are pure functions of a dict,
    so they are compiled out of the module source with only the small dependency they use.
    """
    source = ROUTE_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {"_text", "_coerce_int", "_run_summary_row", "_run_detail_row"}
    picked = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    missing = wanted - {node.name for node in picked}
    if missing:
        raise AssertionError(f"missing helpers in the route module: {sorted(missing)}")
    registry = _definitions("functions_orchestration_registry.py")
    events = _definitions("functions_orchestration_events.py")
    with stubbed_config(
        cosmos_orchestration_runs_container=AtomicMemoryContainer('conversation_id'),
        cosmos_orchestration_run_steps_container=AtomicMemoryContainer('run_id'),
    ):
        from functions_orchestration_recovery import public_execution_fields
        from functions_orchestration_schema import safe_failure
    namespace = {
        "deepcopy": deepcopy,
        "required_capability_ids": registry["required_capability_ids"],
        "merge_reasoning_adjustments": events["merge_reasoning_adjustments"],
        "public_execution_fields": public_execution_fields,
        "safe_failure": safe_failure,
    }
    exec(compile(ast.Module(body=picked, type_ignores=[]), str(ROUTE_FILE), "exec"), namespace)
    return namespace


def test_version_is_at_least_the_implementing_release():
    """The hydration endpoints shipped in IMPLEMENTED_IN, so the app must be at least it."""
    print("Testing the app version is at least the implementing release...")
    try:
        assert_app_version_at_least(IMPLEMENTED_IN)
        print(f"  ok  config.py VERSION is at least {IMPLEMENTED_IN}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        return False


def test_summary_projection_is_an_allowlist():
    """The listing publishes exactly the named fields, and nothing the record happens to hold."""
    print("Testing the run summary projection is an allowlist...")
    try:
        helpers = _load_projections()
        row = helpers["_run_summary_row"](STORED_RUN)

        expected_keys = {
            "run_id",
            "conversation_id",
            "turn_id",
            "turn_index",
            "status",
            "created_at",
            "started_at",
            "completed_at",
            "error",
            "user_message",
            "user_message_id",
            "assistant_message_id",
            "plan_summary",
            "capabilities_used",
            "artifact_count",
            "revision",
            "approval",
            "attempt_index", "retry_of_run_id", "failure", "failures", "recovery",
        }
        assert set(row) == expected_keys, (
            f"unexpected listing shape: extra={sorted(set(row) - expected_keys)} "
            f"missing={sorted(expected_keys - set(row))}"
        )

        # The heavy and the internal are both absent.
        for forbidden in (
            "plan", "seeds", "user_id", "_rid", "_etag", "artifacts",
            "conversation_context", "request_resolution", "user_message_fingerprint",
        ):
            assert forbidden not in row, f"{forbidden!r} must not be published by the listing"
        assert "approved_by" not in row["approval"], (
            "the approving user id must not be echoed back"
        )
        assert set(row["approval"]) == {"mode", "state"}

        # The values the map view actually reads survive the projection.
        assert row["run_id"] == "run-1"
        assert row["turn_id"] == "turn-1"
        assert row["turn_index"] == 3, "turn_index must be coerced to an int"
        assert row["revision"] == 2, "revision must be coerced to an int"
        assert row["artifact_count"] == 2, "artifacts must be reduced to a count"
        assert row["capabilities_used"] == ["search_documents", "respond"]
        assert row["plan_summary"]["intent_summary"] == "Reconcile the quarterly numbers"
        assert row["user_message_id"] == "msg-1", (
            "the question's message id is what anchors a restored card to the thread"
        )
        print("  ok  the listing publishes only the fields it names")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_detail_projection_adds_only_the_plan():
    """The detail row is the listing row plus the plan, so the two cannot drift apart."""
    print("Testing the run detail projection adds only the plan...")
    try:
        helpers = _load_projections()
        original = deepcopy(STORED_RUN)
        summary = helpers["_run_summary_row"](STORED_RUN)
        detail = helpers["_run_detail_row"](STORED_RUN)

        assert set(detail) - set(summary) == {"plan"}, (
            f"the detail row must add only the plan, saw {sorted(set(detail) - set(summary))}"
        )
        for key, value in summary.items():
            assert detail[key] == value, f"{key!r} disagrees between the listing and the detail"
        assert detail["plan"]["steps"][0]["step_id"] == "s1", "the plan must be returned in full"
        assert "seeds" not in detail, "the seeds stay server-side even in the detail"
        assert STORED_RUN == original, "Projection must not rewrite immutable saved plans"
        assert detail["plan"]["inputs"]["required_capabilities"] == []
        automatic = deepcopy(STORED_RUN)
        automatic["plan"]["inputs"]["web"] = True
        automatic["seeds"] = {"web_search": False}
        projected = helpers["_run_detail_row"](automatic)
        assert projected["plan"]["inputs"]["required_capabilities"] == []
        automatic["seeds"]["web_search"] = True
        assert helpers["_run_detail_row"](automatic)["plan"]["inputs"]["required_capabilities"] == ["web_search"]
        for forbidden in (
            "conversation_context", "request_resolution", "user_message_fingerprint",
        ):
            assert forbidden not in detail, (
                f"{forbidden!r} must not ride along with the plan"
            )
        print("  ok  the detail row is the listing row plus the plan")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_projections_tolerate_a_sparse_record():
    """A partly written run -- one that failed early -- projects without raising."""
    print("Testing the projections tolerate a sparse record...")
    try:
        helpers = _load_projections()
        row = helpers["_run_summary_row"]({"run_id": "run-x", "status": "failed"})

        assert row["run_id"] == "run-x"
        assert row["turn_index"] == 0, "a missing turn_index must default rather than raise"
        assert row["revision"] == 0
        assert row["artifact_count"] == 0
        assert row["capabilities_used"] == []
        assert row["plan_summary"] == {}
        assert row["approval"] == {"mode": None, "state": None}

        # And a record that is not a dict at all is projected to empty rather than exploding.
        empty = helpers["_run_summary_row"](None)
        assert empty["run_id"] is None
        assert helpers["_run_detail_row"](None)["plan"] == {}
        print("  ok  a sparse or absent record projects cleanly")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_routes_are_registered_with_the_standard_decorators():
    """Both read routes carry the swagger wrapper and the app's authentication decorators."""
    print("Testing the hydration routes carry the standard decorators...")
    try:
        source = ROUTE_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source)

        found = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if not (isinstance(func, ast.Attribute) and func.attr == "route"):
                    continue
                if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                    continue
                found[decorator.args[0].value] = node

        for rule in (
            "/api/v2/orchestration/runs",
            "/api/v2/orchestration/runs/<run_id>",
            "/api/v2/orchestration/runs/<run_id>/steps",
        ):
            assert rule in found, f"{rule} is not registered"
            names = []
            for decorator in found[rule].decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
                    names.append(decorator.func.id)
                elif isinstance(decorator, ast.Name):
                    names.append(decorator.id)
            assert "swagger_route" in names, f"{rule} is missing @swagger_route"
            assert "login_required" in names, f"{rule} is missing @login_required"
            assert "user_required" in names, f"{rule} is missing @user_required"

        # The detail route must not be a listing in disguise: it reads one run by id and lets
        # the stored-run helper enforce ownership rather than filtering afterwards.
        detail_source = ast.get_source_segment(
            source, found["/api/v2/orchestration/runs/<run_id>"]
        )
        assert "get_orchestration_run(" in detail_source, (
            "the detail route must read through get_orchestration_run, which checks ownership"
        )
        assert re.search(r"404", detail_source), (
            "a run that is missing or not the caller's must be a 404"
        )
        print("  ok  both read routes are registered and guarded")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_listing_projects_unless_the_plan_is_asked_for():
    """The listing route projects by default and only returns full records on request."""
    print("Testing the listing route projects by default...")
    try:
        source = ROUTE_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        listing = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "orchestration_runs":
                listing = node
                break
        assert listing is not None, "orchestration_runs is missing"

        body = ast.get_source_segment(source, listing)
        assert "_run_summary_row" in body, "the listing must project its rows"
        assert "include_plan" in body, (
            "a caller that genuinely wants the plans must have a way to ask"
        )
        # The lean summary is what a caller gets without asking for anything.
        assert re.search(r"else\s+_run_summary_row", body) or re.search(
            r"if\s+not\s+include_plan", body
        ), "the summary projection must be the default path, not the opt-in one"
        # The opt-in path is projected too. This is the part that actually matters: asking
        # for plans must not be a way to ask for the raw stored record, which carries the
        # conversation context, the request resolution and the message fingerprint.
        assert "_run_detail_row" in body, (
            "include_plan must widen the projection, not bypass it"
        )
        assert not re.search(r"jsonify\(\s*\{\s*['\"]runs['\"]\s*:\s*runs\s*\}", body), (
            "the listing must never serialise the stored records as they are"
        )
        print("  ok  both listing paths project, and neither returns a raw record")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_summary_projection_is_an_allowlist,
    test_detail_projection_adds_only_the_plan,
    test_projections_tolerate_a_sparse_record,
    test_routes_are_registered_with_the_standard_decorators,
    test_listing_projects_unless_the_plan_is_asked_for,
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
