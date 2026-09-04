#!/usr/bin/env python3
"""
UI test for the V2 chat orchestration plan card: approve, cancel, review, and the timed countdown.
Version: 0.261.085
Implemented in: 0.261.085

This test drives the REAL OrchestrationPlanCard component (bundled from application/v2_ui/src by
fixtures/orchestration/harness_entry.tsx) in a headless browser. It seeds the real orchestration
and chat stores, mounts the card, and asserts the consequences a reader actually depends on:

  * Approve runs the plan -- it POSTs the run request carrying the plan and the user's edits, and
    the run is recorded as completed once the stream's terminal frame arrives.
  * Cancel throws the plan away -- the inline card disappears and the store forgets the turn.
  * Review opens the drawer in `plan` mode rather than approving anything.
  * A `timed` plan shows a live "Runs in Ns" countdown and, left alone, runs itself on expiry.
  * A `manual` plan shows no countdown at all.

It needs no Azure credentials and no running server: the component and stores are the code that
ships, exercised over a local static file server. If application/v2_ui/node_modules is absent the
browser bundle cannot be built and the browser-driven checks are skipped (reported, not failed),
mirroring the functional_tests/test_v2_*.py convention.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "orchestration"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "functional_tests"))

import harness_build as hb  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


IMPLEMENTED_IN = "0.261.085"

# The runner sets this to the live Playwright page for the duration of the browser session, so the
# zero-argument checks below match the repository's TESTS-list convention.
_PAGE = None


def _plan(**overrides):
    """A minimal but valid raw plan: a search step over two documents, then the answer."""
    plan = {
        "plan_id": "plan-1",
        "run_id": "run-1",
        "conversation_id": overrides.pop("conversation_id", "c1"),
        "intent": {"summary": "Summarise the quarterly report", "complexity": "simple"},
        "steps": [
            {
                "step_id": "s1",
                "capability_id": "search_documents",
                "title": "Search the report",
                "arguments": {"document_ids": ["docA", "docB"]},
                "estimated_cost": "low",
            },
            {
                "step_id": "s2",
                "capability_id": "respond",
                "title": "Write the summary",
                "arguments": {},
                "estimated_cost": "low",
            },
        ],
        "approval": {"mode": "manual", "timeout_seconds": 10, "state": "pending"},
        "status": "awaiting_approval",
    }
    plan.update(overrides)
    return plan


# Seed the stores, optionally install a run-stream mock that records its calls, and mount the card.
_SEED_AND_MOUNT = r"""
(spec) => {
    const H = window.OrchHarness;
    H.reset();
    const { conv, turn, plan, mockRun } = spec;
    H.stores.chat.useChatStore.setState({ activeConversationId: conv });

    if (mockRun) {
        window.__runCalls = [];
        const encoder = new TextEncoder();
        window.fetch = (url, options = {}) => {
            const requestUrl = String(url);
            if (requestUrl.includes('/api/v2/orchestration/run')) {
                window.__runCalls.push({ url: requestUrl, body: options.body });
                const body = new ReadableStream({
                    start(controller) {
                        controller.enqueue(
                            encoder.encode('data: {"done": true, "message_id": "m1"}\n\n'),
                        );
                        controller.close();
                    },
                });
                return Promise.resolve(new Response(body, {
                    status: 200,
                    headers: { 'Content-Type': 'text/event-stream' },
                }));
            }
            return Promise.resolve(new Response('{}', {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            }));
        };
    }

    H.stores.orchestration.useOrchestrationStore.getState().setPlan(conv, turn, plan);
    H.mount('mount-a', 'OrchestrationPlanCard', { conversationId: conv, turnId: turn });
}
"""


def test_version_is_at_least_the_implementing_release():
    """The card behaviours asserted here shipped in IMPLEMENTED_IN, so the app must be at least it."""
    print("Testing the app version is at least the implementing release...")
    try:
        assert_app_version_at_least(IMPLEMENTED_IN)
        print(f"  ok  config.py VERSION is at least {IMPLEMENTED_IN}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        return False


def test_approve_runs_the_plan():
    """Approve POSTs the run with the plan and edits, and the run settles as completed."""
    print("Testing Approve runs the plan...")
    page = _PAGE
    try:
        conv, turn = "c-approve", "t1"
        page.evaluate(_SEED_AND_MOUNT, {"conv": conv, "turn": turn, "plan": _plan(), "mockRun": True})

        approve = page.query_selector('#mount-a [aria-label="Approve and run the plan"]')
        assert approve is not None, "the awaiting card must offer an Approve button"
        approve.click()

        page.wait_for_function(
            "(conv) => (window.OrchHarness.stores.orchestration.useOrchestrationStore"
            ".getState().history[conv] || []).length > 0",
            arg=conv,
            timeout=5000,
        )

        state = page.evaluate(
            r"""
            (conv) => {
                const calls = window.__runCalls || [];
                const history = window.OrchHarness.stores.orchestration.useOrchestrationStore
                    .getState().history[conv] || [];
                const parsed = calls.length ? JSON.parse(calls[0].body) : null;
                return {
                    callCount: calls.length,
                    url: calls.length ? calls[0].url : '',
                    body: parsed,
                    historyStatus: history.length ? history[0].status : '',
                    text: document.getElementById('mount-a').innerText,
                };
            }
            """,
            conv,
        )

        assert state["callCount"] == 1, f"expected exactly one run POST, saw {state['callCount']}"
        assert "/api/v2/orchestration/run" in state["url"], state["url"]
        assert state["body"]["plan_id"] == "plan-1", state["body"]
        assert state["body"]["run_id"] == "run-1", state["body"]
        assert state["body"]["conversation_id"] == conv, state["body"]
        assert "edits" in state["body"], "the run must carry the user's (empty) edit set"
        assert state["historyStatus"] == "completed", state["historyStatus"]
        # The settled card collapses to a single review line naming the outcome.
        assert "view" in state["text"] and "done" in state["text"], state["text"]
        print("  ok  Approve posted the run with the plan and settled it as completed")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_cancel_dismisses_the_plan():
    """Cancel forgets the turn, so the inline card disappears and no plan remains."""
    print("Testing Cancel dismisses the plan...")
    page = _PAGE
    try:
        conv, turn = "c-cancel", "t1"
        page.evaluate(_SEED_AND_MOUNT, {"conv": conv, "turn": turn, "plan": _plan(), "mockRun": False})

        cancel = page.query_selector('#mount-a [aria-label="Cancel this plan"]')
        assert cancel is not None, "the awaiting card must offer a Cancel button"
        cancel.click()

        page.wait_for_function(
            "(arg) => window.OrchHarness.stores.orchestration.useOrchestrationStore.getState()"
            ".plans[arg.conv + '\\u0000' + arg.turn] === undefined",
            arg={"conv": conv, "turn": turn},
            timeout=5000,
        )

        result = page.evaluate(
            r"""
            (conv) => ({
                text: document.getElementById('mount-a').innerText.trim(),
                hasApprove: Boolean(
                    document.querySelector('#mount-a [aria-label="Approve and run the plan"]'),
                ),
                activeTurn: window.OrchHarness.stores.orchestration.useOrchestrationStore
                    .getState().activeTurns[conv] || null,
            })
            """,
            conv,
        )

        assert result["hasApprove"] is False, "the card must be gone after Cancel"
        assert result["text"] == "", f"the card must render nothing, saw {result['text']!r}"
        assert result["activeTurn"] is None, "the turn must be cleared from the store"
        print("  ok  Cancel removed the card and cleared the turn")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_review_opens_the_drawer_in_plan_mode():
    """Review opens the drawer's plan mode without approving or cancelling anything."""
    print("Testing Review opens the drawer in plan mode...")
    page = _PAGE
    try:
        conv, turn = "c-review", "t1"
        page.evaluate(_SEED_AND_MOUNT, {"conv": conv, "turn": turn, "plan": _plan(), "mockRun": False})

        before = page.evaluate(
            "() => window.OrchHarness.stores.chat.useChatStore.getState().drawerMode",
        )
        assert before is None, f"the drawer must start closed, saw {before!r}"

        review = page.query_selector('#mount-a [aria-label="Review the plan in the drawer"]')
        assert review is not None, "the awaiting card must offer a Review button"
        review.click()

        after = page.evaluate(
            "() => window.OrchHarness.stores.chat.useChatStore.getState().drawerMode",
        )
        assert after == "plan", f"Review must set drawer mode to plan, saw {after!r}"
        # Review must not have run or dismissed the plan.
        still_there = page.query_selector('#mount-a [aria-label="Approve and run the plan"]')
        assert still_there is not None, "Review must leave the awaiting card in place"
        print("  ok  Review set the drawer to plan mode and left the plan awaiting")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_timed_plan_shows_a_countdown():
    """A timed plan renders a live countdown timer beside its controls."""
    print("Testing a timed plan shows a countdown...")
    page = _PAGE
    try:
        conv, turn = "c-timed", "t1"
        timed = _plan(approval={"mode": "timed", "timeout_seconds": 30, "state": "pending"})
        page.evaluate(_SEED_AND_MOUNT, {"conv": conv, "turn": turn, "plan": timed, "mockRun": False})

        timer = page.query_selector('#mount-a [role="timer"]')
        assert timer is not None, "a timed plan must render a role=timer element"
        text = timer.inner_text()
        assert "Runs in" in text and text.strip().endswith("s"), f"unexpected timer text {text!r}"
        aria = timer.get_attribute("aria-label") or ""
        assert "Runs automatically in" in aria, f"unexpected timer aria-label {aria!r}"
        # The decorative countdown ring is an aria-hidden svg inside the timer.
        ring = page.query_selector('#mount-a [role="timer"] svg[aria-hidden="true"]')
        assert ring is not None, "the countdown ring svg must be present and hidden from AT"
        print("  ok  the timed plan shows a labelled countdown with the ring")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_timed_plan_runs_itself_on_expiry():
    """Letting a short timed countdown lapse approves and runs the plan without a click."""
    print("Testing a timed plan runs itself on expiry...")
    page = _PAGE
    try:
        conv, turn = "c-expire", "t1"
        timed = _plan(approval={"mode": "timed", "timeout_seconds": 1, "state": "pending"})
        page.evaluate(_SEED_AND_MOUNT, {"conv": conv, "turn": turn, "plan": timed, "mockRun": True})

        # The countdown is shown up front...
        assert page.query_selector('#mount-a [role="timer"]') is not None, "expected a countdown"
        # ...and no run has been requested before it lapses.
        assert page.evaluate("() => (window.__runCalls || []).length") == 0

        page.wait_for_function(
            "() => (window.__runCalls || []).length > 0",
            timeout=6000,
        )
        status = page.evaluate(
            "(conv) => { const h = window.OrchHarness.stores.orchestration.useOrchestrationStore"
            ".getState().history[conv] || []; return h.length ? h[0].status : ''; }",
            conv,
        )
        assert status == "completed", f"the expired plan must run and complete, saw {status!r}"
        print("  ok  the countdown lapsed and the plan ran on its own")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_manual_plan_has_no_countdown():
    """A manual plan waits indefinitely, so it shows no countdown timer."""
    print("Testing a manual plan has no countdown...")
    page = _PAGE
    try:
        conv, turn = "c-manual", "t1"
        page.evaluate(_SEED_AND_MOUNT, {"conv": conv, "turn": turn, "plan": _plan(), "mockRun": False})

        timer = page.query_selector('#mount-a [role="timer"]')
        assert timer is None, "a manual plan must not render a countdown timer"
        text = page.inner_text("#mount-a")
        assert "Runs in" not in text, f"a manual plan must not mention a countdown: {text!r}"
        # It must still be a live, approvable card.
        assert page.query_selector('#mount-a [aria-label="Approve and run the plan"]') is not None
        print("  ok  the manual plan shows its controls with no countdown")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


PAGE_TESTS = [
    test_approve_runs_the_plan,
    test_cancel_dismisses_the_plan,
    test_review_opens_the_drawer_in_plan_mode,
    test_timed_plan_shows_a_countdown,
    test_timed_plan_runs_itself_on_expiry,
    test_manual_plan_has_no_countdown,
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
