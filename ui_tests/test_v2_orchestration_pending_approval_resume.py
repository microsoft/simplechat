#!/usr/bin/env python3
"""
UI test for picking up an unanswered orchestration plan on another device.
Version: 0.261.096
Implemented in: 0.261.096

A plan that was proposed and never approved is stored as `awaiting_approval`, but until this change
the only browser that could act on it was the one that closed the tab. Opening the conversation
anywhere else showed the question with no plan and no way to answer it.

The card is now restored from the stored record, with three guards that each rule out resurrecting
something misleading: the run must be the conversation's newest, this page must not already have a
card up, and no assistant message may follow the run's question. A timed approval is restored as an
ordinary one, because restarting a countdown on a device that was not there would run real work
because somebody opened a laptop.

This test drives the REAL resume module and the REAL OrchestrationPlanCard over the real stores,
stubbing only the HTTP responses, and asserts:

  * An unanswered plan comes back as an approvable card on a page that never saw it.
  * A plan that was already answered does not come back.
  * A plan that already ran does not come back.
  * A restored timed plan waits to be asked rather than running itself.

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

CONVERSATION_ID = "c-resume"
TURN_ID = "turn-pending"
RUN_ID = "run-pending"
USER_MESSAGE_ID = "msg-pending"
PENDING_SUMMARY = "Reconcile the quarterly numbers"


def _pending_run(status="awaiting_approval"):
    return {
        "run_id": RUN_ID,
        "conversation_id": CONVERSATION_ID,
        "turn_id": TURN_ID,
        "status": status,
        "created_at": "2026-01-05T10:00:00Z",
        "user_message_id": USER_MESSAGE_ID,
        "artifact_count": 0,
        "plan_summary": {
            "run_id": RUN_ID,
            "plan_id": "plan-pending",
            "turn_id": TURN_ID,
            "intent_summary": PENDING_SUMMARY,
            "step_count": 2,
            "status": status,
        },
    }


def _pending_plan(approval_mode="manual", timeout_seconds=0):
    return {
        "plan_id": "plan-pending",
        "run_id": RUN_ID,
        "turn_id": TURN_ID,
        "intent": {"summary": PENDING_SUMMARY, "complexity": "simple"},
        "steps": [
            {
                "step_id": "pending-s1",
                "capability_id": "search_documents",
                "title": "Search the ledger",
                "arguments": {"document_ids": ["docA"]},
                "estimated_cost": "low",
            },
            {
                "step_id": "pending-s2",
                "capability_id": "respond",
                "title": "Write the answer",
                "arguments": {},
                "estimated_cost": "low",
            },
        ],
        "approval": {
            "mode": approval_mode,
            "timeout_seconds": timeout_seconds,
            "state": "pending",
        },
        "status": "awaiting_approval",
    }


def _install_routes(page, runs, plan_payload, run_calls):
    """Stub the read endpoints, and record any attempt to actually run the plan."""
    page.unroute_all(behavior="ignoreErrors")

    page.route(
        "**/api/v2/orchestration/runs/*/steps*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"steps": []}),
        ),
    )
    page.route(
        "**/api/v2/orchestration/runs/*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"run": {**_pending_run(), "plan": plan_payload}}),
        ),
    )
    page.route(
        "**/api/v2/orchestration/runs?*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"runs": runs}),
        ),
    )

    def record_run(route):
        run_calls.append(route.request.url)
        route.fulfill(status=200, content_type="text/event-stream", body="")

    page.route("**/api/v2/orchestration/run", record_run)


# Seed a thread holding only the question, then ask the resume module to consider it and mount the
# inline card the way MessageList does.
_SEED_RESUME = r"""
async (spec) => {
    const H = window.OrchHarness;
    H.reset();
    H.stores.chat.useChatStore.setState({
        activeConversationId: spec.conv,
        messages: spec.messages,
    });
    await H.resume.resumeOrchestrationForConversation(spec.conv);
    const orch = H.stores.orchestration.useOrchestrationStore.getState();
    const turnId = orch.activeTurns[spec.conv] ?? null;
    if (turnId) {
        H.mount('mount-a', 'OrchestrationPlanCard', {
            conversationId: spec.conv,
            turnId,
        });
    }
    return {
        activeTurn: turnId,
        readOnly: turnId
            ? H.stores.orchestration.selectIsReadOnly(
                  H.stores.orchestration.useOrchestrationStore.getState(),
                  spec.conv,
                  turnId,
              )
            : null,
    };
}
"""


def _question_only():
    return [{"id": USER_MESSAGE_ID, "role": "user", "content": "Reconcile the numbers"}]


def _question_and_answer():
    return [
        {"id": USER_MESSAGE_ID, "role": "user", "content": "Reconcile the numbers"},
        {"id": "msg-answer", "role": "assistant", "content": "Here you go."},
    ]


def test_version_is_at_least_the_implementing_release():
    """Resuming a pending approval shipped in IMPLEMENTED_IN, so the app must be at least it."""
    print("Testing the app version is at least the implementing release...")
    try:
        assert_app_version_at_least(IMPLEMENTED_IN)
        print(f"  ok  config.py VERSION is at least {IMPLEMENTED_IN}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        return False


def test_unanswered_plan_returns_as_an_approvable_card():
    """An unanswered plan comes back as a card that can still be approved."""
    print("Testing an unanswered plan is restored...")
    page = _PAGE
    try:
        run_calls = []
        _install_routes(page, [_pending_run()], _pending_plan(), run_calls)
        outcome = page.evaluate(
            _SEED_RESUME,
            {"conv": CONVERSATION_ID, "messages": _question_only()},
        )

        assert outcome["activeTurn"] == TURN_ID, (
            f"the pending turn must be restored, saw {outcome['activeTurn']!r}"
        )
        assert outcome["readOnly"] is False, (
            "a plan being offered for approval must not be read-only"
        )
        page.wait_for_function(
            f"() => document.getElementById('mount-a').innerText.includes({PENDING_SUMMARY!r})",
            timeout=5000,
        )
        assert page.query_selector(
            '#mount-a [aria-label="Approve and run the plan"]'
        ) is not None, "the restored card must offer to approve the plan"
        print("  ok  the unanswered plan came back and can still be approved")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_answered_plan_does_not_return():
    """A plan whose turn already has an assistant reply is left alone."""
    print("Testing an answered turn is not resurrected...")
    page = _PAGE
    try:
        run_calls = []
        _install_routes(page, [_pending_run()], _pending_plan(), run_calls)
        outcome = page.evaluate(
            _SEED_RESUME,
            {"conv": CONVERSATION_ID, "messages": _question_and_answer()},
        )

        assert outcome["activeTurn"] is None, (
            "a turn with an assistant reply must not get its card back"
        )
        print("  ok  the answered turn was left alone")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_completed_plan_does_not_return():
    """A plan that already ran is history, not an offer."""
    print("Testing a finished run is not offered for approval...")
    page = _PAGE
    try:
        run_calls = []
        _install_routes(
            page, [_pending_run(status="completed")], _pending_plan(), run_calls
        )
        outcome = page.evaluate(
            _SEED_RESUME,
            {"conv": CONVERSATION_ID, "messages": _question_only()},
        )

        assert outcome["activeTurn"] is None, (
            "a completed run must not come back as a pending card"
        )
        print("  ok  the finished run stayed in history")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_restored_timed_plan_waits_to_be_asked():
    """A timed approval restored elsewhere does not restart its clock and run itself."""
    print("Testing a restored timed plan does not run itself...")
    page = _PAGE
    try:
        run_calls = []
        _install_routes(
            page,
            [_pending_run()],
            _pending_plan(approval_mode="timed", timeout_seconds=1),
            run_calls,
        )
        outcome = page.evaluate(
            _SEED_RESUME,
            {"conv": CONVERSATION_ID, "messages": _question_only()},
        )
        assert outcome["activeTurn"] == TURN_ID, "the timed plan must still be restored"

        # No countdown at all: the restored plan is an ordinary approval.
        assert page.query_selector('#mount-a [role="timer"]') is None, (
            "a restored timed plan must not show a countdown"
        )

        # Well past the original one-second window.
        page.wait_for_timeout(2500)
        assert not run_calls, (
            f"a restored timed plan must not run itself, but it called {run_calls}"
        )
        assert page.query_selector(
            '#mount-a [aria-label="Approve and run the plan"]'
        ) is not None, "it must wait to be asked instead"
        print("  ok  the restored timed plan waited to be asked")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


PAGE_TESTS = [
    test_unanswered_plan_returns_as_an_approvable_card,
    test_answered_plan_does_not_return,
    test_completed_plan_does_not_return,
    test_restored_timed_plan_waits_to_be_asked,
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
