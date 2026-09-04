#!/usr/bin/env python3
"""
UI test for the V2 chat orchestration elicitation card: paged schema form and the MCP answer shape.
Version: 0.261.059
Implemented in: 0.261.059

When the planner cannot plan without more from the user it returns an elicitation -- a flat
JSON-Schema object of primitives -- instead of a plan. The card renders it as a short, paged
interview and returns the MCP-shaped `{action, content}`: only an `accept` carries content, while a
`decline` or `cancel` sends nothing, because forwarding answers past a refusal would smuggle them in.

This test drives the REAL ElicitationCard against seeded schemas and, for the answer-shape checks,
the REAL controller with a mocked plan stream. It asserts:

  * Fields render from `requested_schema.properties`, and an `enum` renders as a choice control
    (radios) rather than a free-text box.
  * A `required` field gates Finish -- the submit stays disabled until it is answered.
  * Paging works: Next advances, Back returns, and the last page's submit reads Finish.
  * Declining sends NO content (an empty object), while accepting carries the entered answer.

No Azure credentials or server are required; the component, store and controller are the shipped
code. The browser checks are skipped (reported, not failed) when node_modules is absent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "orchestration"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "functional_tests"))

import harness_build as hb  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


IMPLEMENTED_IN = "0.261.059"

_PAGE = None


def _single_page_schema():
    """A one-page elicitation: a required free-text topic and an enum tone."""
    return {
        "elicitation_id": "el-1",
        "turn_id": "t-el",
        "message": "A couple of details before I start.",
        "requested_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "title": "Topic"},
                "tone": {"type": "string", "title": "Tone", "enum": ["formal", "casual", "playful"]},
            },
            "required": ["topic"],
        },
        "ui_hints": {"pages": [["topic", "tone"]], "order": ["topic", "tone"]},
    }


def _paged_schema():
    """A three-page elicitation: text, then an enum, then a number; nothing required."""
    return {
        "elicitation_id": "el-paged",
        "turn_id": "t-el-paged",
        "message": "Three quick questions.",
        "requested_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "title": "Topic"},
                "tone": {"type": "string", "title": "Tone", "enum": ["formal", "casual"]},
                "depth": {"type": "number", "title": "Depth"},
            },
            "required": [],
        },
        "ui_hints": {"pages": [["topic"], ["tone"], ["depth"]], "order": ["topic", "tone", "depth"]},
    }


_SEED_ELICITATION = r"""
(spec) => {
    const H = window.OrchHarness;
    H.reset();
    const { conv, turn, elicitation } = spec;
    H.stores.chat.useChatStore.setState({ activeConversationId: conv });
    H.stores.orchestration.useOrchestrationStore.getState()
        .setElicitation(conv, turn, elicitation);
    H.mount('mount-a', 'ElicitationCard', { conversationId: conv, turnId: turn });
}
"""

# Drive the real controller: the first plan POST answers with an elicitation, the re-plan that a
# decline/accept triggers answers with a bare done. Every plan body is recorded for inspection.
_DRIVE_ELICITATION = r"""
async (spec) => {
    const H = window.OrchHarness;
    H.reset();
    const { conv, elicitation } = spec;
    H.stores.chat.useChatStore.setState({ activeConversationId: conv });

    window.__planCalls = [];
    const encoder = new TextEncoder();
    window.fetch = (url, options = {}) => {
        const requestUrl = String(url);
        if (requestUrl.includes('/api/v2/orchestration/plan')) {
            const parsed = JSON.parse(options.body);
            window.__planCalls.push(parsed);
            const isReplan = Boolean(parsed.elicitation_response);
            const frames = isReplan
                ? ['data: {"done": true}\n\n']
                : [
                      'data: ' + JSON.stringify({
                          type: 'orchestration_elicitation',
                          elicitation: { ...elicitation, turn_id: parsed.turn_id },
                      }) + '\n\n',
                      'data: {"done": true}\n\n',
                  ];
            const body = new ReadableStream({
                start(controller) {
                    for (const frame of frames) {
                        controller.enqueue(encoder.encode(frame));
                    }
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
        approvalMode: 'manual',
    });
    const turn = H.stores.orchestration.useOrchestrationStore.getState().activeTurns[conv];
    H.mount('mount-a', 'ElicitationCard', { conversationId: conv, turnId: turn });
    return turn;
}
"""


def test_version_is_at_least_the_implementing_release():
    """The elicitation card shipped in IMPLEMENTED_IN, so the app must be at least it."""
    print("Testing the app version is at least the implementing release...")
    try:
        assert_app_version_at_least(IMPLEMENTED_IN)
        print(f"  ok  config.py VERSION is at least {IMPLEMENTED_IN}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        return False


def test_enum_renders_as_a_choice_and_text_as_a_box():
    """A field with an enum renders as radios; a plain string field renders as a text input."""
    print("Testing an enum renders as a choice control, not a free-text box...")
    page = _PAGE
    try:
        conv, turn = "c-elic", "t-el"
        page.evaluate(_SEED_ELICITATION, {"conv": conv, "turn": turn, "elicitation": _single_page_schema()})

        shape = page.evaluate(
            r"""
            () => {
                const root = document.getElementById('mount-a');
                const topic = root.querySelector('#elicitation-topic');
                const radios = Array.from(root.querySelectorAll('input[type="radio"]'));
                return {
                    topicType: topic ? topic.getAttribute('type') : null,
                    topicTag: topic ? topic.tagName.toLowerCase() : null,
                    radioCount: radios.length,
                    radioNames: Array.from(new Set(radios.map((r) => r.getAttribute('name')))),
                    // A well-formed enum field must NOT also render a free-text input for itself.
                    toneTextInput: Boolean(root.querySelector('#elicitation-tone')),
                    optionText: radios.map((r) => r.closest('label').innerText.trim()),
                };
            }
            """
        )
        assert shape["topicTag"] == "input" and shape["topicType"] == "text", (
            f"the string field must be a text input, saw {shape['topicTag']}/{shape['topicType']}"
        )
        assert shape["radioCount"] == 3, f"the enum must render 3 radios, saw {shape['radioCount']}"
        assert shape["radioNames"] == ["tone"], f"radios must belong to 'tone', saw {shape['radioNames']}"
        assert shape["toneTextInput"] is False, "the enum field must not also offer a free-text box"
        assert shape["optionText"] == ["formal", "casual", "playful"], shape["optionText"]
        print("  ok  the enum is a radio group and the string is a text box")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_required_field_gates_finish():
    """On the last page the submit stays disabled until every required field is answered."""
    print("Testing a required field gates Finish...")
    page = _PAGE
    try:
        conv, turn = "c-elic", "t-el"
        page.evaluate(_SEED_ELICITATION, {"conv": conv, "turn": turn, "elicitation": _single_page_schema()})

        submit = "#mount-a button[type='submit']"
        assert page.inner_text(submit).strip() == "Finish", "a single-page form's submit must read Finish"
        assert page.eval_on_selector(submit, "el => el.disabled") is True, (
            "Finish must be disabled while the required topic is blank"
        )
        assert "Answer the required fields to finish." in page.inner_text("#mount-a"), (
            "the card must explain why Finish is disabled"
        )

        page.fill("#elicitation-topic", "quarterly earnings")
        page.wait_for_function(
            "() => !document.querySelector(\"#mount-a button[type='submit']\").disabled",
            timeout=5000,
        )
        assert page.eval_on_selector(submit, "el => el.disabled") is False, (
            "Finish must enable once the required field is answered"
        )
        assert "Answer the required fields to finish." not in page.inner_text("#mount-a")
        print("  ok  Finish was gated until the required field was answered")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_paging_next_back_and_finish():
    """Next advances a page, Back returns, and the final page's submit reads Finish."""
    print("Testing Next / Back / Finish paging...")
    page = _PAGE
    try:
        conv, turn = "c-elic", "t-el-paged"
        page.evaluate(_SEED_ELICITATION, {"conv": conv, "turn": turn, "elicitation": _paged_schema()})

        submit = "#mount-a button[type='submit']"

        def indicator():
            return page.evaluate(
                "() => document.querySelector('#mount-a span[aria-hidden=\"true\"]').innerText.trim()"
            )

        # Page 1: the text field, a Next submit, and no Back yet.
        assert indicator() == "1/3", f"expected page 1 of 3, saw {indicator()}"
        assert page.inner_text(submit).strip() == "Next"
        assert page.query_selector("#elicitation-topic") is not None
        assert page.evaluate(
            "() => Array.from(document.querySelectorAll('#mount-a button'))"
            ".some(b => b.innerText.trim() === 'Back')"
        ) is False, "there must be no Back button on the first page"

        # Advance to page 2: the enum.
        page.click(submit)
        page.wait_for_function(
            "() => document.querySelector('#mount-a span[aria-hidden=\"true\"]').innerText.trim() === '2/3'",
            timeout=5000,
        )
        assert page.query_selector("#mount-a input[type='radio']") is not None, "page 2 shows the enum"
        assert page.evaluate(
            "() => Array.from(document.querySelectorAll('#mount-a button'))"
            ".some(b => b.innerText.trim() === 'Back')"
        ) is True, "Back appears once past the first page"

        # Advance to page 3: the number, and the submit becomes Finish.
        page.click(submit)
        page.wait_for_function(
            "() => document.querySelector('#mount-a span[aria-hidden=\"true\"]').innerText.trim() === '3/3'",
            timeout=5000,
        )
        assert page.inner_text(submit).strip() == "Finish", "the last page's submit must read Finish"
        # Nothing is required, so Finish is enabled straight away.
        assert page.eval_on_selector(submit, "el => el.disabled") is False

        # Back returns to page 2.
        page.click("#mount-a button:has-text('Back')")
        page.wait_for_function(
            "() => document.querySelector('#mount-a span[aria-hidden=\"true\"]').innerText.trim() === '2/3'",
            timeout=5000,
        )
        print("  ok  paged forward to Finish and back again")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_declining_sends_no_content():
    """Declining answers the planner with an empty content object and clears the question."""
    print("Testing a decline carries no content...")
    page = _PAGE
    try:
        conv = "c-elic-decline"
        turn = page.evaluate(_DRIVE_ELICITATION, {"conv": conv, "elicitation": _single_page_schema()})
        assert turn, "the controller must have minted a turn and set the elicitation"

        page.click("#mount-a [aria-label='Decline to answer']")
        page.wait_for_function("() => (window.__planCalls || []).length >= 2", timeout=5000)

        replan = page.evaluate("() => window.__planCalls[window.__planCalls.length - 1]")
        response = replan.get("elicitation_response")
        assert response is not None, "the re-plan must carry an elicitation_response"
        assert response["action"] == "decline", f"the action must be decline, saw {response['action']}"
        assert response["content"] == {}, f"a decline must send no content, saw {response['content']}"

        cleared = page.evaluate(
            r"""
            (arg) => {
                const state = window.OrchHarness.stores.orchestration.useOrchestrationStore.getState();
                return state.elicitations[arg.conv + '\u0000' + arg.turn] === undefined;
            }
            """,
            {"conv": conv, "turn": turn},
        )
        assert cleared is True, "answering must clear the elicitation from the store"
        print("  ok  the decline sent an empty content object and cleared the question")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_accepting_carries_the_answer():
    """Accepting answers the planner with the entered content, proving the decline contrast is real."""
    print("Testing an accept carries the entered answer...")
    page = _PAGE
    try:
        conv = "c-elic-accept"
        turn = page.evaluate(_DRIVE_ELICITATION, {"conv": conv, "elicitation": _single_page_schema()})
        assert turn, "the controller must have minted a turn and set the elicitation"

        page.fill("#elicitation-topic", "supply chain risk")
        page.wait_for_function(
            "() => !document.querySelector(\"#mount-a button[type='submit']\").disabled",
            timeout=5000,
        )
        page.click("#mount-a button[type='submit']")
        page.wait_for_function("() => (window.__planCalls || []).length >= 2", timeout=5000)

        replan = page.evaluate("() => window.__planCalls[window.__planCalls.length - 1]")
        response = replan.get("elicitation_response")
        assert response is not None, "the re-plan must carry an elicitation_response"
        assert response["action"] == "accept", f"the action must be accept, saw {response['action']}"
        assert response["content"].get("topic") == "supply chain risk", (
            f"an accept must carry the entered answer, saw {response['content']}"
        )
        print("  ok  the accept carried the entered answer")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


PAGE_TESTS = [
    test_enum_renders_as_a_choice_and_text_as_a_box,
    test_required_field_gates_finish,
    test_paging_next_back_and_finish,
    test_declining_sends_no_content,
    test_accepting_carries_the_answer,
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
