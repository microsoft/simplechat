#!/usr/bin/env python3
"""
UI test for the V2 chat orchestration auto-open asymmetry.
Version: 0.261.059
Implemented in: 0.261.059

The drawer opens ITSELF when a plan reaches awaiting-approval only in `manual` mode, and only for
the conversation on screen. This is a deliberate design rule, not an accident: manual approval is a
gate worth interrupting for, whereas throwing a panel open on every `auto` or `timed` message would
be intrusive when the inline card already carries the controls.

This test drives the REAL orchestration controller (startOrchestrationPlan) with a mocked plan
stream, once per approval mode, and asserts the drawer mode the controller leaves behind:

  * manual, visible on screen -> the drawer opens to `plan`.
  * auto -> the drawer stays shut (and the pre-approved plan runs).
  * timed -> the drawer stays shut.
  * manual, but a different conversation is on screen -> the drawer stays shut.

No Azure credentials and no server are needed: the plan and run streams are mocked in the browser
and the controller and stores are the code that ships. The browser checks are skipped (reported,
not failed) when application/v2_ui/node_modules is absent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "orchestration"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "functional_tests"))

import harness_build as hb  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


IMPLEMENTED_IN = "0.261.059"

_PAGE = None


def _plan(mode):
    """A runnable plan carrying the given approval mode, with a search step then the answer."""
    if mode == "auto":
        approval = {"mode": "auto", "timeout_seconds": 0, "state": "approved"}
        status = "approved"
    else:
        approval = {"mode": mode, "timeout_seconds": 10, "state": "pending"}
        status = "awaiting_approval"
    return {
        "plan_id": f"plan-{mode}",
        "run_id": f"run-{mode}",
        "intent": {"summary": f"A {mode} plan", "complexity": "simple"},
        "steps": [
            {
                "step_id": "s1",
                "capability_id": "search_documents",
                "title": "Search",
                "arguments": {"document_ids": ["docA"]},
                "estimated_cost": "low",
            },
            {
                "step_id": "s2",
                "capability_id": "respond",
                "title": "Answer",
                "arguments": {},
                "estimated_cost": "low",
            },
        ],
        "approval": approval,
        "status": status,
    }


# Seed visibility, mock the plan (and run) streams, and drive a fresh plan through the controller.
_DRIVE_PLAN = r"""
async (spec) => {
    const H = window.OrchHarness;
    H.reset();
    const { conv, visibleConv, mode, plan } = spec;
    const orch = H.stores.orchestration.useOrchestrationStore;
    const chat = H.stores.chat.useChatStore;
    chat.setState({ activeConversationId: conv, drawerMode: null });
    orch.getState().setVisibleConversation(visibleConv);

    const encoder = new TextEncoder();
    window.fetch = (url) => {
        const requestUrl = String(url);
        if (requestUrl.includes('/api/v2/orchestration/plan')) {
            const frame = 'data: ' + JSON.stringify({ type: 'orchestration_plan', plan }) + '\n\n';
            const body = new ReadableStream({
                start(controller) {
                    controller.enqueue(encoder.encode(frame));
                    controller.close();
                },
            });
            return Promise.resolve(new Response(body, {
                status: 200,
                headers: { 'Content-Type': 'text/event-stream' },
            }));
        }
        if (requestUrl.includes('/api/v2/orchestration/run')) {
            const body = new ReadableStream({
                start(controller) {
                    controller.enqueue(encoder.encode('data: {"done": true}\n\n'));
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

    await H.controller.startOrchestrationPlan({
        conversationId: conv,
        message: 'do the thing',
        approvalMode: mode,
        seeds: {},
    });
    await new Promise((resolve) => setTimeout(resolve, 40));

    return {
        drawerMode: chat.getState().drawerMode,
        planCount: Object.keys(orch.getState().plans).length,
    };
}
"""


def test_version_is_at_least_the_implementing_release():
    """The auto-open rule shipped in IMPLEMENTED_IN, so the app must be at least that version."""
    print("Testing the app version is at least the implementing release...")
    try:
        assert_app_version_at_least(IMPLEMENTED_IN)
        print(f"  ok  config.py VERSION is at least {IMPLEMENTED_IN}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        return False


def test_manual_plan_opens_the_drawer():
    """A manual plan for the visible conversation opens the drawer to plan mode by itself."""
    print("Testing a manual plan auto-opens the drawer...")
    page = _PAGE
    try:
        result = page.evaluate(
            _DRIVE_PLAN,
            {"conv": "c1", "visibleConv": "c1", "mode": "manual", "plan": _plan("manual")},
        )
        assert result["planCount"] >= 1, "the plan stream must have produced a plan"
        assert result["drawerMode"] == "plan", (
            f"manual must auto-open the drawer, saw {result['drawerMode']!r}"
        )
        print("  ok  the manual plan opened the drawer to plan mode")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_auto_plan_leaves_the_drawer_shut():
    """An auto plan is pre-approved and runs, but must not throw the drawer open."""
    print("Testing an auto plan leaves the drawer shut...")
    page = _PAGE
    try:
        result = page.evaluate(
            _DRIVE_PLAN,
            {"conv": "c1", "visibleConv": "c1", "mode": "auto", "plan": _plan("auto")},
        )
        assert result["planCount"] >= 1, "the plan stream must have produced a plan"
        assert result["drawerMode"] is None, (
            f"auto must leave the drawer shut, saw {result['drawerMode']!r}"
        )
        print("  ok  the auto plan ran without opening the drawer")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_timed_plan_leaves_the_drawer_shut():
    """A timed plan carries its countdown on the inline card, so the drawer stays shut."""
    print("Testing a timed plan leaves the drawer shut...")
    page = _PAGE
    try:
        result = page.evaluate(
            _DRIVE_PLAN,
            {"conv": "c1", "visibleConv": "c1", "mode": "timed", "plan": _plan("timed")},
        )
        assert result["planCount"] >= 1, "the plan stream must have produced a plan"
        assert result["drawerMode"] is None, (
            f"timed must leave the drawer shut, saw {result['drawerMode']!r}"
        )
        print("  ok  the timed plan left the drawer shut")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_manual_plan_for_another_conversation_stays_shut():
    """Even a manual plan must not yank a panel open over a different conversation on screen."""
    print("Testing a manual plan for an off-screen conversation stays shut...")
    page = _PAGE
    try:
        result = page.evaluate(
            _DRIVE_PLAN,
            {"conv": "c1", "visibleConv": "other", "mode": "manual", "plan": _plan("manual")},
        )
        assert result["planCount"] >= 1, "the plan stream must have produced a plan"
        assert result["drawerMode"] is None, (
            f"a plan for an off-screen conversation must not open the drawer, "
            f"saw {result['drawerMode']!r}"
        )
        print("  ok  the off-screen manual plan did not open the drawer")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


PAGE_TESTS = [
    test_manual_plan_opens_the_drawer,
    test_auto_plan_leaves_the_drawer_shut,
    test_timed_plan_leaves_the_drawer_shut,
    test_manual_plan_for_another_conversation_stays_shut,
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
