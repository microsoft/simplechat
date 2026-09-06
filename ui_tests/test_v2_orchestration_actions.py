# test_v2_orchestration_actions.py
"""
Browser coverage for action identity and tool citations in orchestration.
Version: 0.261.098
Implemented in: 0.261.098

Use the existing orchestration harness and real stores/components. Serve its
local bundle through request interception so local and Azure Playwright browsers
can run without an application server, credentials or integration traffic.
"""

import copy
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

# Register the shared Azure connection fixture after locating the UI helpers.
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(FIXTURES))
sys.path.insert(0, str(FIXTURES / "orchestration"))

import harness_build as hb
from v2_admin_settings import connect_options


pytestmark = pytest.mark.ui
ORIGIN = "http://orchestration.test"
CONVERSATION = "action-plan-conversation"
TURN = "action-plan-turn"
ACTIONS = [
    {"action_ref": "personal:ticket-lookup", "display_name": "Ticket lookup", "scope_label": "Personal"},
    {"action_ref": "group:ticket-lookup", "display_name": "Ticket lookup", "scope_label": "Support team"},
    {"action_ref": "global:ticket-lookup", "display_name": "Ticket lookup", "scope_label": "Enterprise"},
]


@pytest.fixture
def action_page(page):
    hb.ensure_bundle()
    errors = []
    unexpected_requests = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text) if message.type == "error" else None,
    )

    def serve(route):
        parsed = urlsplit(route.request.url)
        if f"{parsed.scheme}://{parsed.netloc}" == ORIGIN and parsed.path == "/":
            route.fulfill(path=str(hb.HERE / "harness.html"), content_type="text/html")
        elif f"{parsed.scheme}://{parsed.netloc}" == ORIGIN and parsed.path == "/harness.bundle.js":
            route.fulfill(path=str(hb.BUNDLE), content_type="application/javascript")
        elif f"{parsed.scheme}://{parsed.netloc}" == ORIGIN and parsed.path == "/favicon.ico":
            route.fulfill(status=204)
        else:
            unexpected_requests.append(route.request.url)
            route.abort()

    page.route("**/*", serve)
    page.goto(ORIGIN, wait_until="domcontentloaded")
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    yield page
    assert not errors, errors
    assert not unexpected_requests, unexpected_requests


def _plan(action_ref="group:ticket-lookup"):
    return {
        "plan_id": "action-plan",
        "run_id": "action-run",
        "turn_id": TURN,
        "conversation_id": CONVERSATION,
        "intent": {"summary": "Find the ticket status", "complexity": "simple"},
        "inputs": {"documents": [], "web": False, "actions": copy.deepcopy(ACTIONS)},
        "steps": [
            {
                "step_id": "lookup",
                "capability_id": "action_invoke",
                "phase": "knowledge",
                "title": "Look up the ticket",
                "rationale": "Use the existing ticket integration.",
                "arguments": {"action_ref": action_ref, "task": "Find the status of ticket 1234."},
                "depends_on": [],
                "optional": True,
                "enabled": True,
                "estimated_cost": "medium",
                "status": "pending",
            },
            {
                "step_id": "answer",
                "capability_id": "respond",
                "phase": "reasoning",
                "title": "Write the answer",
                "arguments": {},
                "depends_on": ["lookup"],
                "estimated_cost": "low",
            },
        ],
        "approval": {"mode": "manual", "state": "pending", "timeout_seconds": 10},
        "status": "awaiting_approval",
    }


def _seed(page, plan):
    page.evaluate(
        """
        ({conversation, turn, plan}) => {
            const harness = window.OrchHarness;
            harness.reset();
            const store = harness.stores.orchestration.useOrchestrationStore.getState();
            store.setPlan(conversation, turn, plan);
            harness.mount('mount-a', 'OrchestrationRunView', {
                conversationId: conversation, turnId: turn,
            });
        }
        """,
        {"conversation": CONVERSATION, "turn": TURN, "plan": plan},
    )
    expect(page.get_by_text(plan["intent"]["summary"], exact=True)).to_be_visible()


def _action_row(page):
    return page.get_by_role("listitem").filter(
        has=page.get_by_text("Look up the ticket", exact=True)
    )


@pytest.mark.parametrize("action", ACTIONS, ids=["personal", "group", "global"])
def test_action_identity_is_matched_by_reference_not_name_or_position(action_page, action):
    _seed(action_page, _plan(action["action_ref"]))
    identity = action_page.get_by_test_id("orchestration-action-input")
    expect(identity).to_have_count(1)
    expect(identity).to_contain_text(action["display_name"])
    expect(identity).to_contain_text(action["scope_label"])
    for other in ACTIONS:
        if other["action_ref"] != action["action_ref"]:
            expect(identity).not_to_contain_text(other["scope_label"])
    expect(_action_row(action_page)).to_contain_text("Use an action")
    expect(_action_row(action_page)).to_contain_text("Find the status of ticket 1234.")
    expect(_action_row(action_page)).not_to_contain_text(action["action_ref"])
    sections = action_page.locator("#mount-a section")
    expect(sections.nth(0)).to_contain_text("Gathering knowledge")
    expect(sections.nth(0)).to_contain_text("Look up the ticket")
    expect(sections.nth(1)).to_contain_text("Reasoning")
    expect(sections.nth(1)).to_contain_text("Write the answer")


def test_action_labels_are_inert_and_only_public_metadata_survives(action_page):
    plan = _plan()
    display_name = '<img src=x onerror="window.actionLabelExecuted=true">'
    scope_label = '<svg onload="window.actionLabelExecuted=true">'
    plan["inputs"]["actions"] = [
        None,
        {"display_name": "No reference"},
        {
            "action_ref": "group:ticket-lookup",
            "display_name": display_name,
            "scope_label": scope_label,
            "manifest": {"api_key": "private-metadata-sentinel"},
            "endpoint": "https://private-endpoint.invalid",
        },
    ]
    task = '<script>window.actionLabelExecuted=true</script>'
    plan["steps"][0]["arguments"].update({
        "task": task,
        "display_name": "Planner-supplied identity",
        "manifest": {"api_key": "private-argument-sentinel"},
        "endpoint": "https://private-argument.invalid",
    })
    _seed(action_page, plan)
    identity = action_page.get_by_test_id("orchestration-action-input")
    expect(identity).to_contain_text(display_name)
    expect(identity).to_contain_text(scope_label)
    expect(_action_row(action_page)).to_contain_text(task)
    expect(action_page.locator("#mount-a img, #mount-a svg[onload], #mount-a script")).to_have_count(0)
    assert action_page.evaluate("() => window.actionLabelExecuted") is None
    expect(action_page.locator("#mount-a")).not_to_contain_text("private-")
    expect(action_page.locator("#mount-a")).not_to_contain_text("Planner-supplied identity")
    normalized = action_page.evaluate(
        "(plan) => window.OrchHarness.plan.normalizePlan(plan).inputs.actions", plan
    )
    assert normalized == [{
        "action_ref": "group:ticket-lookup",
        "display_name": display_name,
        "scope_label": scope_label,
    }]


@pytest.mark.parametrize("actions", [None, [], {"unexpected": "object"}, [ACTIONS[0]]])
def test_missing_or_unmatched_action_metadata_does_not_guess_identity(action_page, actions):
    plan = _plan()
    if actions is None:
        del plan["inputs"]["actions"]
    else:
        plan["inputs"]["actions"] = actions
    _seed(action_page, plan)
    expect(action_page.get_by_test_id("orchestration-action-input")).to_contain_text(
        "Action details unavailable"
    )
    expect(_action_row(action_page)).not_to_contain_text("group:ticket-lookup")
    expect(_action_row(action_page)).not_to_contain_text("Personal")


def test_older_non_action_plan_remains_unchanged(action_page):
    plan = _plan()
    del plan["inputs"]["actions"]
    plan["steps"] = [plan["steps"][1]]
    plan["steps"][0]["depends_on"] = []
    _seed(action_page, plan)
    expect(action_page.get_by_text("Write the answer", exact=True)).to_be_visible()
    expect(action_page.get_by_text("Always runs", exact=True)).to_be_visible()
    expect(action_page.get_by_test_id("orchestration-action-input")).to_have_count(0)


def test_action_step_keeps_existing_narrowing_controls(action_page):
    _seed(action_page, _plan())
    row = _action_row(action_page)
    row.get_by_text("Will run", exact=True).click()
    expect(row.get_by_text("Skipped", exact=True)).to_be_visible()
    expect(row.get_by_test_id("orchestration-action-input")).to_contain_text("Support team")
    disabled = action_page.evaluate(
        """
        ({conversation, turn}) => {
            const module = window.OrchHarness.stores.orchestration;
            return module.selectEdits(module.useOrchestrationStore.getState(), conversation, turn);
        }
        """,
        {"conversation": CONVERSATION, "turn": TURN},
    )
    assert disabled["disabled_step_ids"] == ["lookup"]
    row.get_by_text("Skipped", exact=True).click()
    expect(row.get_by_text("Will run", exact=True)).to_be_visible()


@pytest.mark.parametrize("status,summary", [
    ("running", "Calling the selected action."),
    ("completed", "Found the ticket status."),
    ("failed", "Unable to run the selected action."),
    ("cancelled", "Stopped before another call."),
])
def test_action_identity_remains_visible_with_live_status(action_page, status, summary):
    plan = _plan()
    plan["status"] = "running"
    plan["approval"]["state"] = "approved"
    _seed(action_page, plan)
    action_page.evaluate(
        """
        ({conversation, turn, status, summary}) => {
            window.OrchHarness.stores.orchestration.useOrchestrationStore.getState()
                .updateStepStatus(conversation, turn, 'lookup', {status, summary});
        }
        """,
        {"conversation": CONVERSATION, "turn": TURN, "status": status, "summary": summary},
    )
    row = _action_row(action_page)
    expect(row.get_by_text(status, exact=True)).to_be_visible()
    expect(row.get_by_text(summary, exact=True)).to_be_visible()
    expect(row.get_by_test_id("orchestration-action-input")).to_contain_text("Support team")
    expect(row.get_by_role("checkbox")).to_have_count(0)


@pytest.mark.parametrize("include_web", [False, True], ids=["tools-only", "tools-and-web"])
def test_action_done_frame_renders_tool_citations_through_standard_sources(action_page, include_web):
    citations = [
        {
            "tool_name": "ticketLookup.get_ticket",
            "function_arguments": {"ticket_id": "1234"},
            "function_result": {"status": "open"},
            "artifact_id": "ticket-result",
        },
        {
            "tool_name": "ticketLookup.get_comments",
            "function_arguments": {"ticket_id": "1234"},
            "function_result": '<img src=x onerror="window.toolCitationExecuted=true">',
            "artifact_id": "ticket-comments",
        },
    ]
    web_citations = [{"url": "https://example.test/help", "title": "Ticket help"}] if include_web else []
    frames = [
        {"content": "Ticket 1234 is open."},
        {
            "done": True,
            "message_id": "action-citation-answer",
            "agent_citations": citations,
            "web_search_citations": web_citations,
            "hybrid_citations": [],
            "augmented": False,
        },
    ]
    requests = []

    def complete_run(route):
        requests.append(route.request.post_data_json)
        route.fulfill(
            content_type="text/event-stream",
            body="".join(f"data: {json.dumps(frame)}\n\n" for frame in frames),
        )

    action_page.route(f"{ORIGIN}/api/v2/orchestration/run", complete_run)
    _seed(action_page, _plan())
    message = action_page.evaluate(
        """
        async ({conversation, turn}) => {
            const harness = window.OrchHarness;
            harness.stores.chat.useChatStore.setState({activeConversationId: conversation});
            await harness.controller.approveAndRunPlan({
                conversationId: conversation, turnId: turn,
            });
            const answer = harness.stores.chat.useChatStore.getState().messages
                .find(message => message.id === 'action-citation-answer');
            harness.mount('mount-b', 'MessageList', {});
            return answer;
        }
        """,
        {"conversation": CONVERSATION, "turn": TURN},
    )
    assert len(requests) == 1
    assert requests[0]["plan_id"] == "action-plan"
    assert message.get("agent_citations") == citations
    assert message["web_search_citations"] == web_citations
    assert message["hybrid_citations"] == []
    answer = action_page.locator("#mount-b")
    expect(answer.get_by_text("Ticket 1234 is open.", exact=True)).to_be_visible()
    answer.get_by_role("button", name=f"Show sources ({2 + len(web_citations)})", exact=True).click()
    expect(answer.get_by_role("heading", name="Tool calls (2)", exact=True)).to_be_visible()
    expect(answer.get_by_role("heading", name=re.compile(r"^Documents"))).to_have_count(0)
    if include_web:
        expect(answer.get_by_role("heading", name="Web (1)", exact=True)).to_be_visible()
        expect(answer.get_by_role("link", name="Ticket help", exact=True)).to_have_attribute(
            "href", "https://example.test/help"
        )
    else:
        expect(answer.get_by_role("heading", name=re.compile(r"^Web"))).to_have_count(0)
    answer.get_by_text("ticketLookup.get_ticket", exact=True).click()
    expect(answer.get_by_text('"status": "open"', exact=False)).to_be_visible()
    answer.get_by_text("ticketLookup.get_comments", exact=True).click()
    expect(answer.get_by_text(citations[1]["function_result"], exact=True)).to_be_visible()
    expect(answer.locator("img[onerror]")).to_have_count(0)
    assert action_page.evaluate("() => window.toolCitationExecuted") is None
