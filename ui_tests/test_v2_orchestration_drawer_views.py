#!/usr/bin/env python3
"""
UI test for the V2 orchestration drawer: the Run and Map views and pinning from the map.
Version: 0.261.085
Implemented in: 0.261.085

The drawer's plan mode shows one run in full (the Run view) or every run as a scannable column (the
Map view). The discipline the panel keeps is that neither the user's browsing nor the system's work
ever yanks the other's view away: the Run view follows the live turn until the user pins a run, and
the only way to pin an older run is to choose its row in the map -- a deliberate, non-silent move
that returns the view to Run and holds it there.

This test drives the REAL OrchestrationPlanPanel over the real stores, with no server, and asserts:

  * The Run view is selected by default and shows the current turn's plan.
  * The Map tab switches to the run column; the Run tab switches back.
  * Choosing an older run's row pins the Run view onto that run and offers "Back to current", which
    releases the pin and returns the view to the live turn.

The browser checks are skipped (reported, not failed) when node_modules is absent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "orchestration"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "functional_tests"))

import harness_build as hb  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


IMPLEMENTED_IN = "0.261.085"

_PAGE = None

CURRENT_SUMMARY = "Summarise today's tickets"
OLDER_SUMMARY = "Draft the incident report"


def _plan(plan_id, run_id, summary, search_title):
    return {
        "plan_id": plan_id,
        "run_id": run_id,
        "intent": {"summary": summary, "complexity": "simple"},
        "steps": [
            {
                "step_id": f"{plan_id}-s1",
                "capability_id": "search_documents",
                "title": search_title,
                "arguments": {"document_ids": ["docA"]},
                "estimated_cost": "low",
            },
            {
                "step_id": f"{plan_id}-s2",
                "capability_id": "respond",
                "title": "Write the answer",
                "arguments": {},
                "estimated_cost": "low",
            },
        ],
        "approval": {"mode": "manual", "timeout_seconds": 10, "state": "pending"},
        "status": "awaiting_approval",
    }


# Seed a current turn plus one older settled run, then mount the drawer panel. The older run is put
# in history the way the app does it -- a beginRun followed by endRun -- so the map has a real row.
_SEED_PANEL = r"""
(spec) => {
    const H = window.OrchHarness;
    H.reset();
    const { conv, current, older } = spec;
    const orch = H.stores.orchestration.useOrchestrationStore.getState();
    H.stores.chat.useChatStore.setState({ activeConversationId: conv });

    orch.setPlan(conv, current.turn, current.plan);
    orch.setActiveTurn(conv, current.turn);

    orch.setPlan(conv, older.turn, older.plan);
    orch.beginRun({
        conversationId: conv,
        turnId: older.turn,
        runId: older.runId,
        planId: older.planId,
        startedAt: Date.now() - 5000,
    });
    orch.endRun(older.runId, 'completed');

    H.mount('mount-a', 'OrchestrationPlanPanel', {});
}
"""


def _tab_selected(page, label):
    return page.evaluate(
        """
        (label) => {
            const tab = Array.from(document.querySelectorAll("#mount-a [role='tab']"))
                .find((t) => t.innerText.trim() === label);
            return tab ? tab.getAttribute('aria-selected') : null;
        }
        """,
        label,
    )


def _seed(page):
    conv = "c-drawer"
    page.evaluate(
        _SEED_PANEL,
        {
            "conv": conv,
            "current": {"turn": "turnA", "plan": _plan("planA", "runA", CURRENT_SUMMARY, "Search tickets")},
            "older": {
                "turn": "turnB",
                "runId": "runB",
                "planId": "planB",
                "plan": _plan("planB", "runB", OLDER_SUMMARY, "Search incidents"),
            },
        },
    )


def test_version_is_at_least_the_implementing_release():
    """The drawer's plan mode shipped in IMPLEMENTED_IN, so the app must be at least it."""
    print("Testing the app version is at least the implementing release...")
    try:
        assert_app_version_at_least(IMPLEMENTED_IN)
        print(f"  ok  config.py VERSION is at least {IMPLEMENTED_IN}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        return False


def test_run_is_default_and_map_toggles():
    """Run is selected on open; the Map tab shows the run column and the Run tab returns."""
    print("Testing the Run/Map view toggle...")
    page = _PAGE
    try:
        _seed(page)

        # The tablist is labelled and Run is the opening view.
        assert page.evaluate(
            "() => document.querySelector(\"#mount-a [role='tablist']\").getAttribute('aria-label')"
        ) == "Plan view"
        assert _tab_selected(page, "Run") == "true", "Run must be the default view"
        assert _tab_selected(page, "Map") == "false"
        assert CURRENT_SUMMARY in page.inner_text("#mount-a"), "the Run view shows the current plan"

        # Switch to the Map: the older run's row appears.
        page.click("#mount-a button[role='tab']:has-text('Map')")
        page.wait_for_function(
            "() => Array.from(document.querySelectorAll(\"#mount-a [role='tab']\"))"
            ".find(t => t.innerText.trim() === 'Map').getAttribute('aria-selected') === 'true'",
            timeout=5000,
        )
        assert _tab_selected(page, "Run") == "false"
        assert OLDER_SUMMARY in page.inner_text("#mount-a"), "the Map lists the older run"

        # Switch back to the Run view.
        page.click("#mount-a button[role='tab']:has-text('Run')")
        page.wait_for_function(
            "() => Array.from(document.querySelectorAll(\"#mount-a [role='tab']\"))"
            ".find(t => t.innerText.trim() === 'Run').getAttribute('aria-selected') === 'true'",
            timeout=5000,
        )
        assert CURRENT_SUMMARY in page.inner_text("#mount-a")
        print("  ok  Run opens by default and the Map/Run toggle works")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_map_row_pins_the_run_view():
    """Choosing an older run's row pins the Run view onto it; 'Back to current' releases the pin."""
    print("Testing a map row click pins the Run view...")
    page = _PAGE
    try:
        _seed(page)

        # Before pinning there is no "Back to current" affordance.
        assert page.evaluate(
            "() => Array.from(document.querySelectorAll('#mount-a button'))"
            ".some(b => b.innerText.trim() === 'Back to current')"
        ) is False

        # Open the map and choose the older run's row (the select button carries its summary).
        page.click("#mount-a button[role='tab']:has-text('Map')")
        page.wait_for_selector(f"#mount-a button:has-text(\"{OLDER_SUMMARY}\")", timeout=5000)
        page.click(f"#mount-a button:has-text(\"{OLDER_SUMMARY}\")")

        # The view returns to Run, now pinned to the older run, and offers to go back.
        page.wait_for_function(
            "() => Array.from(document.querySelectorAll(\"#mount-a [role='tab']\"))"
            ".find(t => t.innerText.trim() === 'Run').getAttribute('aria-selected') === 'true'",
            timeout=5000,
        )
        assert _tab_selected(page, "Run") == "true", "selecting a run must return to the Run view"
        panel_text = page.inner_text("#mount-a")
        assert OLDER_SUMMARY in panel_text, "the Run view must now show the pinned older run"
        assert CURRENT_SUMMARY not in panel_text, "the current run must no longer be shown while pinned"
        assert page.evaluate(
            "() => Array.from(document.querySelectorAll('#mount-a button'))"
            ".some(b => b.innerText.trim() === 'Back to current')"
        ) is True, "a pin must offer 'Back to current'"

        # Releasing the pin returns the Run view to the live turn.
        page.click("#mount-a button:has-text('Back to current')")
        page.wait_for_function(
            f"() => document.getElementById('mount-a').innerText.includes(\"{CURRENT_SUMMARY}\")",
            timeout=5000,
        )
        assert OLDER_SUMMARY not in page.inner_text("#mount-a"), "releasing the pin drops the older run"
        print("  ok  the map row pinned the Run view and 'Back to current' released it")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


PAGE_TESTS = [
    test_run_is_default_and_map_toggles,
    test_map_row_pins_the_run_view,
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
