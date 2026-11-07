#!/usr/bin/env python3
"""
UI test for the V2 chat orchestration auto-open asymmetry.
Version: 0.261.213
Implemented in: 0.261.085
Plan fixture identity re-synced with the controller in: 0.261.213

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

The controller adopts a streamed plan only when it carries plan, run and turn ids and names the
conversation the turn was started for; it drops any other plan without touching the drawer. So the
mocked stream answers as the server does, naming the started conversation and echoing the turn id
the client minted, and every case first asserts that the plan was adopted. A dropped plan can never
pass a "drawer stays shut" check.

No Azure credentials and no server are needed: the plan and run streams are mocked in the browser
and the controller and stores are the code that ships. The browser checks are skipped (reported,
not failed) when application/v2_ui/node_modules is absent.

Run: python ui_tests/test_v2_orchestration_auto_open.py
  or python -m pytest ui_tests/test_v2_orchestration_auto_open.py -q
"""

import sys
import traceback
from contextlib import ExitStack
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "orchestration"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "functional_tests"))

import harness_build as hb  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


pytestmark = pytest.mark.ui

IMPLEMENTED_IN = "0.261.085"
# Every plan is started for CONVERSATION; OTHER_CONVERSATION is a different thread put on screen.
CONVERSATION = "c1"
OTHER_CONVERSATION = "other"


def _plan(mode, conversation_id):
    """A runnable plan for ``conversation_id`` in the given approval mode: a search, then the answer.

    It carries no turn id on purpose. The client mints the turn id when the turn starts and the
    server echoes the one it was sent, so the mocked plan stream in _DRIVE_PLAN stamps it on.
    """
    if mode == "auto":
        approval = {"mode": "auto", "timeout_seconds": 0, "state": "approved"}
        status = "approved"
    else:
        approval = {"mode": mode, "timeout_seconds": 10, "state": "pending"}
        status = "awaiting_approval"
    return {
        "plan_id": f"plan-{mode}",
        "run_id": f"run-{mode}",
        "conversation_id": conversation_id,
        "planner_contract_version": 2,
        "intent": {"summary": f"A {mode} plan", "complexity": "simple"},
        "steps": [
            {
                "step_id": "s1",
                "capability_id": "search_documents",
                "title": "Search",
                "arguments": {"document_ids": ["docA"]},
                "role": "gather",
                "estimated_cost": "low",
            },
            {
                "step_id": "s2",
                "capability_id": "compose",
                "title": "Answer",
                "arguments": {},
                "role": "reason",
                "estimated_cost": "low",
            },
        ],
        "approval": approval,
        "status": status,
    }


# Seed visibility, mock the plan (and run) streams, and drive a fresh plan through the controller.
# The result reports what the controller requested and adopted, so a dropped plan is visible.
_DRIVE_PLAN = r"""
async (spec) => {
    const H = window.OrchHarness;
    H.reset();
    const { conv, visibleConv, mode, plan } = spec;
    const orch = H.stores.orchestration.useOrchestrationStore;
    const chat = H.stores.chat.useChatStore;
    chat.setState({ activeConversationId: conv, drawerMode: null, streamError: null });
    orch.getState().setVisibleConversation(visibleConv);

    const encoder = new TextEncoder();
    const planRequests = [];
    window.fetch = (url, options = {}) => {
        const requestUrl = String(url);
        if (requestUrl.includes('/api/v2/orchestration/plan')) {
            const request = typeof options.body === 'string' ? JSON.parse(options.body) : {};
            planRequests.push({ conversation_id: request.conversation_id, turn_id: request.turn_id });
            // As the server does, echo the turn id the client minted for this turn on the plan.
            const streamed = { ...plan, turn_id: request.turn_id };
            const frame = 'data: ' + JSON.stringify({ type: 'orchestration_plan', plan: streamed }) + '\n\n';
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

    const plans = Object.values(orch.getState().plans);
    return {
        drawerMode: chat.getState().drawerMode,
        streamError: chat.getState().streamError,
        planCount: plans.length,
        plans: plans.map((held) => ({
            plan_id: held.plan_id,
            conversation_id: held.conversation_id,
            turn_id: held.turn_id,
        })),
        planRequests,
    };
}
"""


def _drive_plan(page, mode, visible_conversation):
    """Start a fresh ``mode`` plan for CONVERSATION while ``visible_conversation`` is on screen."""
    return page.evaluate(
        _DRIVE_PLAN,
        {
            "conv": CONVERSATION,
            "visibleConv": visible_conversation,
            "mode": mode,
            "plan": _plan(mode, CONVERSATION),
        },
    )


def _assert_plan_adopted(result, mode):
    """Assert the controller adopted the one streamed plan, for the conversation and turn it began.

    The controller drops a plan that lacks an id or names another conversation, and a dropped plan
    leaves the drawer shut too. Checking adoption first keeps each drawer assertion meaningful.
    """
    requests = result["planRequests"]
    assert len(requests) == 1, f"the controller must request exactly one plan, saw {result!r}"
    turn_id = requests[0]["turn_id"]
    assert requests[0]["conversation_id"] == CONVERSATION and turn_id, (
        f"the plan request must name {CONVERSATION!r} and carry the client's turn id, saw {result!r}"
    )
    assert result["planCount"] == 1, (
        f"the controller must adopt the streamed plan, but it holds {result['planCount']} plan(s) "
        f"and reported {result['streamError']!r}"
    )
    expected = {"plan_id": f"plan-{mode}", "conversation_id": CONVERSATION, "turn_id": turn_id}
    assert result["plans"] == [expected], (
        f"the adopted plan must belong to {CONVERSATION!r} and the requested turn, saw {result!r}"
    )


def _report_page_errors(errors):
    """Print uncaught page errors for diagnosis; as before, they are reported, not failed on."""
    if errors:
        print("\nUncaught page errors observed during the run:")
        for message in errors:
            print(f"  !!  {message}")


@pytest.fixture(scope="module")
def orchestration_page():
    """One harness page shared by the module; skipped, not failed, without the v2_ui toolchain."""
    errors = []
    with ExitStack() as stack:
        try:
            page = stack.enter_context(hb.harness_page(collect_errors=errors))
        except hb.HarnessUnavailable as exc:
            pytest.skip(f"skipped the browser-driven checks: {exc}")
        else:
            yield page
    _report_page_errors(errors)


def test_version_is_at_least_the_implementing_release():
    """The auto-open rule shipped in IMPLEMENTED_IN, so the app must be at least that version."""
    print("Testing the app version is at least the implementing release...")
    assert_app_version_at_least(IMPLEMENTED_IN)
    print(f"  ok  config.py VERSION is at least {IMPLEMENTED_IN}")


def test_manual_plan_opens_the_drawer(orchestration_page):
    """A manual plan for the visible conversation opens the drawer to plan mode by itself."""
    print("Testing a manual plan auto-opens the drawer...")
    result = _drive_plan(orchestration_page, "manual", visible_conversation=CONVERSATION)
    _assert_plan_adopted(result, "manual")
    assert result["drawerMode"] == "plan", (
        f"manual must auto-open the drawer, saw {result['drawerMode']!r}"
    )
    print("  ok  the manual plan opened the drawer to plan mode")


def test_auto_plan_leaves_the_drawer_shut(orchestration_page):
    """An auto plan is pre-approved and runs, but must not throw the drawer open."""
    print("Testing an auto plan leaves the drawer shut...")
    result = _drive_plan(orchestration_page, "auto", visible_conversation=CONVERSATION)
    _assert_plan_adopted(result, "auto")
    assert result["drawerMode"] is None, (
        f"auto must leave the drawer shut, saw {result['drawerMode']!r}"
    )
    print("  ok  the auto plan ran without opening the drawer")


def test_timed_plan_leaves_the_drawer_shut(orchestration_page):
    """A timed plan carries its countdown on the inline card, so the drawer stays shut."""
    print("Testing a timed plan leaves the drawer shut...")
    result = _drive_plan(orchestration_page, "timed", visible_conversation=CONVERSATION)
    _assert_plan_adopted(result, "timed")
    assert result["drawerMode"] is None, (
        f"timed must leave the drawer shut, saw {result['drawerMode']!r}"
    )
    print("  ok  the timed plan left the drawer shut")


def test_manual_plan_for_another_conversation_stays_shut(orchestration_page):
    """Even a manual plan must not yank a panel open over a different conversation on screen.

    The plan is still adopted for the conversation it was started for; only the drawer stays shut.
    """
    print("Testing a manual plan for an off-screen conversation stays shut...")
    result = _drive_plan(orchestration_page, "manual", visible_conversation=OTHER_CONVERSATION)
    _assert_plan_adopted(result, "manual")
    assert result["drawerMode"] is None, (
        f"a plan for an off-screen conversation must not open the drawer, "
        f"saw {result['drawerMode']!r}"
    )
    print("  ok  the off-screen manual plan did not open the drawer")


PAGE_TESTS = [
    test_manual_plan_opens_the_drawer,
    test_auto_plan_leaves_the_drawer_shut,
    test_timed_plan_leaves_the_drawer_shut,
    test_manual_plan_for_another_conversation_stays_shut,
]


def _run(test, *args):
    """Run one check for the script runner, reporting a failure rather than stopping the run."""
    try:
        test(*args)
    except Exception as exc:  # noqa: BLE001 - every failure is reported, then the run carries on
        print(f"Test failed: {exc}")
        traceback.print_exc()
        return False
    return True


def main():
    results = [_run(test_version_is_at_least_the_implementing_release)]

    errors = []
    try:
        with hb.harness_page(collect_errors=errors) as page:
            for test in PAGE_TESTS:
                print(f"\nRunning {test.__name__}...")
                page.evaluate("() => window.OrchHarness.reset()")
                results.append(_run(test, page))
    except hb.HarnessUnavailable as exc:
        print(f"\n  --  skipped the browser-driven checks: {exc}")
        results.extend([True] * len(PAGE_TESTS))

    _report_page_errors(errors)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
