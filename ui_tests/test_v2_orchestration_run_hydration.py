#!/usr/bin/env python3
"""
UI test for hydrating a conversation's stored orchestration runs into the V2 plan drawer.
Version: 0.261.096
Implemented in: 0.261.096

Orchestration runs have always been written to Cosmos and read back by the planner, but nothing in
the browser ever asked for them. The drawer's Map view built its rows purely from what this page
happened to watch, so a conversation opened after a reload -- or in a second tab, or on another
device -- showed an empty panel for work that plainly happened. The fix is a fetch: the Map asks
the server for the conversation's runs and merges them with whatever it saw itself.

This test drives the REAL OrchestrationPlanPanel over the real stores, stubbing only the HTTP
responses, and asserts:

  * A conversation this page never watched still lists its stored runs in the Map.
  * A stored run expands to the step titles the server recorded, fetched on demand.
  * A locally-observed run is not duplicated by its stored copy.
  * Choosing a stored row loads that run's plan into the Run view and marks it as a record, with
    the step controls withheld.
  * A failed fetch says so and offers to try again, rather than claiming there is no history.

The browser checks are skipped (reported, not failed) when node_modules is absent.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "orchestration"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "functional_tests"))

import harness_build as hb  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


IMPLEMENTED_IN = "0.261.096"

_PAGE = None

CONVERSATION_ID = "c-hydrate"
STORED_SUMMARY = "Reconcile the quarterly numbers"
OLDER_STORED_SUMMARY = "Draft the incident report"
LOCAL_SUMMARY = "Summarise today's tickets"


def _stored_run(run_id, turn_id, summary, status="completed", step_count=2):
    """A run summary shaped the way route_backend_orchestration projects one."""
    return {
        "run_id": run_id,
        "conversation_id": CONVERSATION_ID,
        "turn_id": turn_id,
        "status": status,
        "created_at": "2026-01-05T10:00:00Z",
        "completed_at": "2026-01-05T10:02:00Z",
        "user_message_id": f"msg-{turn_id}",
        "artifact_count": 0,
        "plan_summary": {
            "run_id": run_id,
            "plan_id": f"plan-{run_id}",
            "turn_id": turn_id,
            "intent_summary": summary,
            "step_count": step_count,
            "status": status,
        },
    }


def _stored_plan(run_id, turn_id, summary):
    """The full plan a run detail response carries."""
    return {
        "plan_id": f"plan-{run_id}",
        "run_id": run_id,
        "turn_id": turn_id,
        "intent": {"summary": summary, "complexity": "simple"},
        "steps": [
            {
                "step_id": f"{run_id}-s1",
                "capability_id": "search_documents",
                "title": "Search the ledger",
                "arguments": {"document_ids": ["docA"]},
                "estimated_cost": "low",
            },
            {
                "step_id": f"{run_id}-s2",
                "capability_id": "respond",
                "title": "Write the answer",
                "arguments": {},
                "estimated_cost": "low",
            },
        ],
        "approval": {"mode": "manual", "timeout_seconds": 0, "state": "approved"},
        "status": "completed",
    }


def _stored_steps(run_id):
    return [
        {
            "run_id": run_id,
            "step_id": f"{run_id}-s1",
            "step_index": 0,
            "title": "Search the ledger",
            "status": "completed",
            "summary": "Found 4 matching entries",
        },
        {
            "run_id": run_id,
            "step_id": f"{run_id}-s2",
            "step_index": 1,
            "title": "Write the answer",
            "status": "completed",
            "summary": "",
        },
    ]


def _install_routes(page, runs, fail_list=False):
    """Stub the three orchestration read endpoints for this page.

    Registered most-specific first: Playwright matches routes in registration order, so the steps
    and detail patterns must be offered before the bare list pattern that would otherwise swallow
    them.
    """
    page.unroute_all(behavior="ignoreErrors")

    def steps_handler(route):
        run_id = route.request.url.split("/runs/")[1].split("/steps")[0]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"steps": _stored_steps(run_id)}),
        )

    def detail_handler(route):
        run_id = route.request.url.split("/runs/")[1].split("?")[0]
        summary = STORED_SUMMARY if run_id == "run-stored" else OLDER_STORED_SUMMARY
        turn_id = "turn-stored" if run_id == "run-stored" else "turn-older"
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "run": {
                        **_stored_run(run_id, turn_id, summary),
                        "plan": _stored_plan(run_id, turn_id, summary),
                    }
                }
            ),
        )

    def list_handler(route):
        if fail_list:
            route.fulfill(
                status=500,
                content_type="application/json",
                body=json.dumps({"error": "boom"}),
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"runs": runs}),
        )

    page.route("**/api/v2/orchestration/runs/*/steps*", steps_handler)
    page.route("**/api/v2/orchestration/runs/*", detail_handler)
    page.route("**/api/v2/orchestration/runs?*", list_handler)


# Mount the drawer straight onto the Map view for a conversation this page never watched.
_SEED_MAP = r"""
(spec) => {
    const H = window.OrchHarness;
    H.reset();
    H.stores.chat.useChatStore.setState({ activeConversationId: spec.conv, messages: [] });
    H.mount('mount-a', 'OrchestrationPlanPanel', {});
}
"""

# The same, but with one run this page watched itself, so the merge can be checked.
_SEED_MAP_WITH_LOCAL = r"""
(spec) => {
    const H = window.OrchHarness;
    H.reset();
    const orch = H.stores.orchestration.useOrchestrationStore.getState();
    H.stores.chat.useChatStore.setState({ activeConversationId: spec.conv, messages: [] });

    orch.setPlan(spec.conv, spec.turn, spec.plan);
    orch.beginRun({
        conversationId: spec.conv,
        turnId: spec.turn,
        runId: spec.runId,
        planId: spec.planId,
        startedAt: Date.now() - 5000,
    });
    orch.endRun(spec.runId, 'completed');

    H.mount('mount-a', 'OrchestrationPlanPanel', {});
}
"""


def _local_plan():
    return {
        "plan_id": "plan-local",
        "run_id": "run-local",
        "intent": {"summary": LOCAL_SUMMARY, "complexity": "simple"},
        "steps": [
            {
                "step_id": "local-s1",
                "capability_id": "respond",
                "title": "Write the answer",
                "arguments": {},
                "estimated_cost": "low",
            }
        ],
        "approval": {"mode": "manual", "timeout_seconds": 0, "state": "approved"},
        "status": "completed",
    }


def _open_map(page):
    page.click("#mount-a button[role='tab']:has-text('Map')")
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll(\"#mount-a [role='tab']\"))"
        ".find(t => t.innerText.trim() === 'Map').getAttribute('aria-selected') === 'true'",
        timeout=5000,
    )


def test_version_is_at_least_the_implementing_release():
    """Run hydration shipped in IMPLEMENTED_IN, so the app must be at least it."""
    print("Testing the app version is at least the implementing release...")
    try:
        assert_app_version_at_least(IMPLEMENTED_IN)
        print(f"  ok  config.py VERSION is at least {IMPLEMENTED_IN}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        return False


def test_stored_runs_appear_without_being_watched():
    """A conversation this page never watched still lists its stored runs."""
    print("Testing stored runs are fetched into the Map...")
    page = _PAGE
    try:
        _install_routes(
            page,
            [
                _stored_run("run-stored", "turn-stored", STORED_SUMMARY),
                _stored_run("run-older", "turn-older", OLDER_STORED_SUMMARY, status="failed"),
            ],
        )
        page.evaluate(_SEED_MAP, {"conv": CONVERSATION_ID})
        _open_map(page)

        page.wait_for_function(
            f"() => document.getElementById('mount-a').innerText.includes({STORED_SUMMARY!r})",
            timeout=5000,
        )
        text = page.inner_text("#mount-a")
        assert STORED_SUMMARY in text, "the newest stored run must be listed"
        assert OLDER_STORED_SUMMARY in text, "every stored run must be listed"
        assert "2 steps" in text, "the stored step count must be shown without loading the plan"
        assert "Failed" in text, "a stored run's outcome must be shown"
        print("  ok  the Map listed runs it never watched")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_stored_row_expands_to_fetched_steps():
    """Expanding a stored row fetches and shows the step titles the server recorded."""
    print("Testing a stored row expands to its steps...")
    page = _PAGE
    try:
        _install_routes(page, [_stored_run("run-stored", "turn-stored", STORED_SUMMARY)])
        page.evaluate(_SEED_MAP, {"conv": CONVERSATION_ID})
        _open_map(page)
        page.wait_for_function(
            f"() => document.getElementById('mount-a').innerText.includes({STORED_SUMMARY!r})",
            timeout=5000,
        )

        assert "Search the ledger" not in page.inner_text("#mount-a"), (
            "steps must not be fetched until the row is opened"
        )
        page.click("#mount-a button[aria-label='Expand steps']")
        page.wait_for_function(
            "() => document.getElementById('mount-a').innerText.includes('Search the ledger')",
            timeout=5000,
        )
        text = page.inner_text("#mount-a")
        assert "Search the ledger" in text and "Write the answer" in text, (
            "the recorded step titles must be shown"
        )
        print("  ok  the stored row fetched its steps on demand")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_local_run_is_not_duplicated_by_its_stored_copy():
    """A run this page watched appears once, not twice, when the server also reports it."""
    print("Testing the local and stored copies of one run are merged...")
    page = _PAGE
    try:
        _install_routes(
            page,
            [
                _stored_run("run-local", "turn-local", LOCAL_SUMMARY),
                _stored_run("run-stored", "turn-stored", STORED_SUMMARY),
            ],
        )
        page.evaluate(
            _SEED_MAP_WITH_LOCAL,
            {
                "conv": CONVERSATION_ID,
                "turn": "turn-local",
                "runId": "run-local",
                "planId": "plan-local",
                "plan": _local_plan(),
            },
        )
        _open_map(page)
        page.wait_for_function(
            f"() => document.getElementById('mount-a').innerText.includes({STORED_SUMMARY!r})",
            timeout=5000,
        )

        rows = page.evaluate(
            "() => document.querySelectorAll('#mount-a ol > li').length"
        )
        assert rows == 2, f"expected one row per run, saw {rows}"
        print("  ok  the observed run was not duplicated by its stored copy")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_choosing_a_stored_row_loads_a_read_only_run():
    """A stored row loads its plan into the Run view, marked as a record and not editable."""
    print("Testing a stored row opens read-only in the Run view...")
    page = _PAGE
    try:
        _install_routes(page, [_stored_run("run-stored", "turn-stored", STORED_SUMMARY)])
        page.evaluate(_SEED_MAP, {"conv": CONVERSATION_ID})
        _open_map(page)
        page.wait_for_selector(
            f"#mount-a button:has-text({STORED_SUMMARY!r})", timeout=5000
        )
        page.click(f"#mount-a button:has-text({STORED_SUMMARY!r})")

        page.wait_for_function(
            "() => document.getElementById('mount-a').innerText.includes('cannot be changed')",
            timeout=5000,
        )
        text = page.inner_text("#mount-a")
        assert STORED_SUMMARY in text, "the Run view must show the chosen run's plan"
        assert "Search the ledger" in text, "the stored plan's steps must be shown"
        toggles = page.evaluate(
            "() => document.querySelectorAll(\"#mount-a [role='switch']\").length"
        )
        assert toggles == 0, "a record of a finished run must not offer to narrow its steps"
        print("  ok  the stored run opened as an unchangeable record")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_failed_fetch_is_reported_not_hidden():
    """A failed history fetch says so and offers a retry, rather than showing an empty map."""
    print("Testing a failed history fetch is reported...")
    page = _PAGE
    try:
        _install_routes(page, [], fail_list=True)
        page.evaluate(_SEED_MAP, {"conv": CONVERSATION_ID})
        _open_map(page)

        page.wait_for_function(
            "() => document.getElementById('mount-a').innerText.includes('could not be loaded')",
            timeout=5000,
        )
        assert page.evaluate(
            "() => Array.from(document.querySelectorAll('#mount-a button'))"
            ".some(b => b.innerText.trim() === 'Try again')"
        ), "a failed fetch must offer a retry"

        # The retry succeeds once the endpoint recovers.
        _install_routes(page, [_stored_run("run-stored", "turn-stored", STORED_SUMMARY)])
        page.click("#mount-a button:has-text('Try again')")
        page.wait_for_function(
            f"() => document.getElementById('mount-a').innerText.includes({STORED_SUMMARY!r})",
            timeout=5000,
        )
        print("  ok  the failure was reported and the retry recovered")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


PAGE_TESTS = [
    test_stored_runs_appear_without_being_watched,
    test_stored_row_expands_to_fetched_steps,
    test_local_run_is_not_duplicated_by_its_stored_copy,
    test_choosing_a_stored_row_loads_a_read_only_run,
    test_failed_fetch_is_reported_not_hidden,
]


def main():
    results = [test_version_is_at_least_the_implementing_release()]

    errors = []
    try:
        with hb.harness_page(collect_errors=errors) as page:
            global _PAGE
            _PAGE = page
            for test in PAGE_TESTS:
                print(f"\nRunning {test.__name__}...")
                page.evaluate("() => window.OrchHarness.reset()")
                results.append(test())
    except hb.HarnessUnavailable as exc:
        print(f"\n  --  skipped the browser-driven checks: {exc}")
        results.extend([True] * len(PAGE_TESTS))

    if errors:
        print("\nUncaught page errors observed during the run:")
        for message in errors:
            print(f"  !!  {message}")

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
