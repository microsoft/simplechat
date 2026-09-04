#!/usr/bin/env python3
"""
UI test for the V2 chat orchestration plan editing: narrowing only, never widening.
Version: 0.261.085
Implemented in: 0.261.085

A user may narrow a plan before it runs -- switch a step off, or drop a document from one -- but
there is deliberately NO affordance to ADD a step, a capability or a document. Widening client-side
would bypass the planner's reasoning and the authorization check that followed it, so the run view
offers only narrowing and the store makes widening unrepresentable.

This test drives the REAL OrchestrationRunView against a seeded plan and asserts:

  * A non-terminal step has an off switch; the terminal answering step shows "Always runs" with a
    lock and no switch at all.
  * Toggling a step off records it in the edit set and drops it from the plan the run would carry;
    toggling it back on clears that edit rather than widening past the plan's own default.
  * A document can be removed and restored; a document the step merely references
    (`left_document_id`) is shown but has no remove control.
  * There is no widening affordance anywhere: no "add" control, no free-text field, and the store
    exposes no method that could add a step, capability or document.

No Azure credentials or server are required; the component and store are the shipped code. The
browser checks are skipped (reported, not failed) when application/v2_ui/node_modules is absent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "orchestration"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "functional_tests"))

import harness_build as hb  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


IMPLEMENTED_IN = "0.261.085"

_PAGE = None


def _plan():
    """A manual (editable) plan: a search step over two documents plus a pinned one, then answer."""
    return {
        "plan_id": "plan-edit",
        "run_id": "run-edit",
        "intent": {"summary": "Compare the two filings", "complexity": "simple"},
        "steps": [
            {
                "step_id": "s1",
                "capability_id": "search_documents",
                "title": "Search the filings",
                "arguments": {
                    "document_ids": ["docA", "docB"],
                    "left_document_id": "docL",
                },
                "estimated_cost": "low",
            },
            {
                "step_id": "s2",
                "capability_id": "respond",
                "title": "Write the comparison",
                "arguments": {},
                "estimated_cost": "low",
            },
        ],
        "approval": {"mode": "manual", "timeout_seconds": 10, "state": "pending"},
        "status": "awaiting_approval",
    }


_SEED_RUNVIEW = r"""
(spec) => {
    const H = window.OrchHarness;
    H.reset();
    const { conv, turn, plan } = spec;
    H.stores.chat.useChatStore.setState({ activeConversationId: conv });
    H.stores.orchestration.useOrchestrationStore.getState().setPlan(conv, turn, plan);
    H.mount('mount-a', 'OrchestrationRunView', { conversationId: conv, turnId: turn });
}
"""


def _read_edits(page, conv, turn):
    return page.evaluate(
        r"""
        (arg) => {
            const H = window.OrchHarness;
            const orch = H.stores.orchestration.useOrchestrationStore.getState();
            const key = arg.conv + '\u0000' + arg.turn;
            const edits = orch.edits[key] || { disabled_step_ids: [], removed_document_ids: {} };
            const plan = orch.plans[key];
            const applied = H.plan.applyPlanEdits(plan, edits);
            const s1 = applied.steps.find((s) => s.step_id === 's1');
            return {
                disabled: edits.disabled_step_ids,
                removed: edits.removed_document_ids,
                appliedS1Docs: (s1 && s1.arguments.document_ids) || [],
                appliedS1Enabled: s1 ? s1.enabled : null,
            };
        }
        """,
        {"conv": conv, "turn": turn},
    )


def test_version_is_at_least_the_implementing_release():
    """The narrowing-only edit model shipped in IMPLEMENTED_IN; the app must be at least it."""
    print("Testing the app version is at least the implementing release...")
    try:
        assert_app_version_at_least(IMPLEMENTED_IN)
        print(f"  ok  config.py VERSION is at least {IMPLEMENTED_IN}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        return False


def test_step_has_off_switch_and_terminal_is_locked():
    """A non-terminal step carries an off switch; the terminal step is locked with no switch."""
    print("Testing the step switch and the locked terminal step...")
    page = _PAGE
    try:
        conv, turn = "c-edit", "t1"
        page.evaluate(_SEED_RUNVIEW, {"conv": conv, "turn": turn, "plan": _plan()})

        shape = page.evaluate(
            r"""
            () => {
                const items = Array.from(document.querySelectorAll('#mount-a ol > li'));
                return items.map((li) => ({
                    hasSwitch: Boolean(li.querySelector('input[type="checkbox"]')),
                    text: li.innerText,
                }));
            }
            """
        )
        assert len(shape) == 2, f"expected two steps, saw {len(shape)}"
        # First step (search) is editable: it has a switch and is not locked.
        assert shape[0]["hasSwitch"] is True, "the non-terminal step must have an off switch"
        assert "Always runs" not in shape[0]["text"], "the non-terminal step must not be locked"
        # Terminal answering step: locked, no switch.
        assert shape[1]["hasSwitch"] is False, "the terminal step must not have a switch"
        assert "Always runs" in shape[1]["text"], "the terminal step must read 'Always runs'"
        print("  ok  the search step has a switch and the answer step is locked")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_toggling_a_step_narrows_then_clears():
    """Switching a step off records the edit and drops it; switching on clears the edit."""
    print("Testing toggling a step narrows then clears...")
    page = _PAGE
    try:
        conv, turn = "c-edit", "t1"
        page.evaluate(_SEED_RUNVIEW, {"conv": conv, "turn": turn, "plan": _plan()})

        before = _read_edits(page, conv, turn)
        assert before["disabled"] == [], "no step should start disabled"
        assert before["appliedS1Enabled"] is True

        # The first step's toggle is the only label/checkbox in its list item.
        page.click("#mount-a ol > li:nth-child(1) label")
        page.wait_for_function(
            "(arg) => (window.OrchHarness.stores.orchestration.useOrchestrationStore.getState()"
            ".edits[arg.conv + '\\u0000' + arg.turn] || {disabled_step_ids: []})"
            ".disabled_step_ids.includes('s1')",
            arg={"conv": conv, "turn": turn},
            timeout=5000,
        )
        off = _read_edits(page, conv, turn)
        assert off["disabled"] == ["s1"], f"the step must be recorded disabled, saw {off['disabled']}"
        assert off["appliedS1Enabled"] is False, "the run's plan must drop the disabled step"

        # Toggling back on clears the edit -- it does not widen past the plan's own default.
        page.click("#mount-a ol > li:nth-child(1) label")
        page.wait_for_function(
            "(arg) => !(window.OrchHarness.stores.orchestration.useOrchestrationStore.getState()"
            ".edits[arg.conv + '\\u0000' + arg.turn] || {disabled_step_ids: []})"
            ".disabled_step_ids.includes('s1')",
            arg={"conv": conv, "turn": turn},
            timeout=5000,
        )
        on = _read_edits(page, conv, turn)
        assert on["disabled"] == [], f"toggling on must clear the edit, saw {on['disabled']}"
        print("  ok  the step toggled off (narrowing) and back on (clearing), never widening")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_document_removes_and_restores_and_pinned_is_readonly():
    """A removable document can be dropped and restored; the pinned document has no remove."""
    print("Testing document removal, restoration, and the read-only pinned document...")
    page = _PAGE
    try:
        conv, turn = "c-edit", "t1"
        page.evaluate(_SEED_RUNVIEW, {"conv": conv, "turn": turn, "plan": _plan()})

        # docL is referenced via left_document_id: shown, but with no remove control.
        assert page.query_selector('#mount-a [aria-label="Remove document docL from this step"]') is None, (
            "the pinned left_document_id must not be removable"
        )
        assert "docL" in page.inner_text("#mount-a"), "the pinned document should still be shown"

        remove = page.query_selector('#mount-a [aria-label="Remove document docA from this step"]')
        assert remove is not None, "a removable document must offer a remove control"
        remove.click()
        page.wait_for_selector('#mount-a [aria-label="Restore document docA"]', timeout=5000)

        removed = _read_edits(page, conv, turn)
        assert removed["removed"].get("s1") == ["docA"], removed["removed"]
        assert removed["appliedS1Docs"] == ["docB"], (
            f"the run's plan must drop only docA, saw {removed['appliedS1Docs']}"
        )

        page.click('#mount-a [aria-label="Restore document docA"]')
        page.wait_for_selector('#mount-a [aria-label="Remove document docA from this step"]', timeout=5000)
        restored = _read_edits(page, conv, turn)
        assert restored["removed"].get("s1", []) == [], "restoring must clear the removal"
        assert set(restored["appliedS1Docs"]) == {"docA", "docB"}, restored["appliedS1Docs"]
        print("  ok  a document removed and restored; the pinned document stayed read-only")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_there_is_no_widening_affordance():
    """No control or store method can add a step, capability or document to the plan."""
    print("Testing there is no way to widen the plan...")
    page = _PAGE
    try:
        conv, turn = "c-edit", "t1"
        page.evaluate(_SEED_RUNVIEW, {"conv": conv, "turn": turn, "plan": _plan()})

        dom = page.evaluate(
            r"""
            () => {
                const root = document.getElementById('mount-a');
                const buttons = Array.from(root.querySelectorAll('button'));
                const addButtons = buttons.filter((b) => {
                    const label = (b.getAttribute('aria-label') || '') + ' ' + (b.innerText || '');
                    return /\badd\b/i.test(label);
                });
                return {
                    freeTextInputs: root.querySelectorAll(
                        'input[type="text"], input:not([type]), textarea',
                    ).length,
                    addButtons: addButtons.length,
                    docChips: root.querySelectorAll('li ul li').length,
                };
            }
            """
        )
        assert dom["freeTextInputs"] == 0, "the run view must offer no free-text field to add things"
        assert dom["addButtons"] == 0, "the run view must offer no 'add' control"
        # Exactly the three documents the plan named are shown; the list cannot grow.
        assert dom["docChips"] == 3, f"expected the plan's three documents, saw {dom['docChips']}"

        store_shape = page.evaluate(
            r"""
            () => {
                const state = window.OrchHarness.stores.orchestration.useOrchestrationStore
                    .getState();
                const widening = ['addStep', 'addDocument', 'addCapability', 'widenPlan', 'insertStep'];
                const present = widening.filter((name) => typeof state[name] === 'function');
                // Removing a document that the plan never contained must be a no-op (unrepresentable).
                const key = 'c-edit\u0000t1';
                const plan = state.plans[key];
                const step = plan.steps.find((s) => s.step_id === 's1');
                state.removeDocument('c-edit', 't1', step, 'docGHOST');
                const after = window.OrchHarness.stores.orchestration.useOrchestrationStore
                    .getState().edits[key] || { removed_document_ids: {} };
                return {
                    wideningMethods: present,
                    ghostRecorded: (after.removed_document_ids.s1 || []).includes('docGHOST'),
                };
            }
            """
        )
        assert store_shape["wideningMethods"] == [], (
            f"the store must expose no widening method, saw {store_shape['wideningMethods']}"
        )
        assert store_shape["ghostRecorded"] is False, (
            "removing a document the plan never had must be a no-op, not an edit"
        )
        print("  ok  no add control, no free-text field, and no widening method")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


PAGE_TESTS = [
    test_step_has_off_switch_and_terminal_is_locked,
    test_toggling_a_step_narrows_then_clears,
    test_document_removes_and_restores_and_pinned_is_readonly,
    test_there_is_no_widening_affordance,
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
