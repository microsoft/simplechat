# test_v2_shared_orchestration_routing.py
"""
UI test for Orchestrate in V2 shared conversations.
Version: 0.261.269
Implemented in: 0.261.269 (Refs #1659)

With Orchestrate on, a shared conversation used to send every message to the planner, so a remark
addressed only to another person was answered by the model. The composer now applies the shared
conversation's send rule first, the same rule a manual send applies.

This test drives the REAL Composer, chat store and orchestration controller over a seeded
bootstrap, with the browser's fetch replaced, and asserts:

  * "@Ada ..." from the person who started the conversation is posted to the participants: one
    message post with the mention, and no plan request.
  * "@Research Assistant ..." from that person starts a plan whose request carries the AI target,
    the tagged agent and the mentions, and posts no message.
  * The same request from another participant is answered the classic way: no plan request, and
    one shared assistant stream.

The browser checks are skipped (reported, not failed) when node_modules is absent.

Run: python ui_tests/test_v2_shared_orchestration_routing.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "orchestration"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "functional_tests"))

import harness_build as hb  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


pytestmark = pytest.mark.ui

IMPLEMENTED_IN = "0.261.269"
CONVERSATION = "shared-1"
OWNER = {"user_id": "owner", "display_name": "Owner Person", "email": "owner@example.test"}
ADA = {"user_id": "ada", "display_name": "Ada Lovelace", "email": "ada@example.test"}
AGENTS = [{"id": "agent-1", "name": "researcher", "display_name": "Research Assistant", "scope_type": "personal"}]
MODELS = [{
    "selection_key": "user::ep1::gpt-4o", "display_name": "GPT-4o",
    "deployment_name": "gpt-4o", "endpoint_id": "ep1",
}]

_PAGE = None

# Seed a shared conversation, replace fetch with a recorder that answers like the server, and mount
# the real Composer.
_SEED = r"""
(spec) => {
    const H = window.OrchHarness;
    H.reset();
    window.__requests = [];
    const encoder = new TextEncoder();
    const json = (value) => new Response(JSON.stringify(value), {
        status: 200, headers: { 'Content-Type': 'application/json' },
    });
    const sse = (frames) => new Response(new ReadableStream({
        start(controller) {
            for (const frame of frames) {
                controller.enqueue(encoder.encode('data: ' + JSON.stringify(frame) + '\n\n'));
            }
            controller.close();
        },
    }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
    const conversationPath = `/api/collaboration/conversations/${spec.conversation}`;
    window.fetch = (url, options = {}) => {
        const path = new URL(String(url), window.location.origin).pathname;
        const method = String(options.method || 'GET').toUpperCase();
        let body = null;
        try {
            body = typeof options.body === 'string' ? JSON.parse(options.body) : null;
        } catch {
            body = null;
        }
        window.__requests.push({ path, method, body });
        if (path.endsWith('/api/v2/orchestration/plan')) {
            return Promise.resolve(sse([{ conversation_id: spec.conversation, error: 'Stopped by the test.' }]));
        }
        if (path === `${conversationPath}/stream`) {
            return Promise.resolve(sse([{ done: true, message_id: 'assistant-1', full_content: 'A classic answer.' }]));
        }
        if (path === `${conversationPath}/messages` && method === 'POST') {
            return Promise.resolve(json({
                conversation: spec.collaboration,
                message: {
                    id: 'posted-1', conversation_id: spec.conversation, role: 'user',
                    content: body?.content ?? '', metadata: {}, sender: { user_id: spec.user.id },
                },
            }));
        }
        return Promise.resolve(json({}));
    };
    H.stores.bootstrap.useBootstrapStore.setState({
        data: {
            features: { enable_chat_orchestration: true, enable_collaborative_conversations: true },
            orchestration: {
                enabled: true, show_manual_controls: true, default_approval_mode: 'manual',
                allow_user_approval_override: true, timed_approval_seconds: 8,
            },
            settings: {},
            catalogs: { prompts: [], models: spec.models, agents: spec.agents },
            user: spec.user,
        },
    });
    H.stores.chat.useChatStore.setState({
        activeConversationId: spec.conversation, activeConversationKind: 'collaborative', messages: [],
    });
    H.stores.collaboration.useCollaborationStore.setState({ conversation: spec.collaboration, replyTo: null });
    H.mount('mount-a', 'Composer', {});
}
"""


def _collaboration(started_by):
    return {
        "id": CONVERSATION, "title": "Launch plan", "chat_type": "personal_multi_user",
        "conversation_kind": "collaborative", "user_id": started_by,
        "participants": [
            {**OWNER, "role": "owner", "status": "accepted"},
            {**ADA, "role": "member", "status": "accepted"},
        ],
        "membership_status": "accepted", "can_post_messages": True, "can_accept_invite": False,
    }


def _seed(page, *, reader, started_by="owner"):
    page.evaluate(_SEED, {
        "conversation": CONVERSATION,
        "collaboration": _collaboration(started_by),
        "user": {"id": reader["user_id"], "display_name": reader["display_name"], "email": reader["email"]},
        "agents": AGENTS,
        "models": MODELS,
    })
    orchestrate = page.locator('#mount-a [title="Orchestrate"]')
    orchestrate.wait_for(state="visible", timeout=5000)
    assert orchestrate.get_attribute("aria-pressed") == "true", "Orchestrate must be on for these checks"


_SENT = "(request) => request.method === 'POST' && !request.path.endsWith('/typing')"


def _send(page, text):
    """Send ``text`` and return the POSTs it made, leaving out typing indicators."""
    page.get_by_role("textbox", name="Message", exact=True).fill(text)
    page.get_by_role("button", name="Send to this conversation", exact=True).click()
    page.wait_for_function(f"() => window.__requests.some({_SENT})", timeout=5000)
    page.wait_for_timeout(150)
    return page.evaluate(f"() => window.__requests.filter({_SENT})")


def _paths(requests):
    return [request["path"] for request in requests]


def test_version_is_at_least_the_implementing_release():
    """Shared Orchestrate routing shipped in IMPLEMENTED_IN, so the app must be at least it."""
    print("Testing the app version is at least the implementing release...")
    try:
        assert_app_version_at_least(IMPLEMENTED_IN)
        print(f"  ok  config.py VERSION is at least {IMPLEMENTED_IN}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        return False


def test_a_message_to_a_person_is_posted_without_a_plan():
    """'@Ada ...' with Orchestrate on reaches Ada, never the model."""
    print("Testing a message to a person is posted without a plan...")
    page = _PAGE
    try:
        _seed(page, reader=OWNER)
        requests = _send(page, "@Ada Lovelace can you check the launch dates?")

        assert _paths(requests) == [f"/api/collaboration/conversations/{CONVERSATION}/messages"], requests
        post = requests[0]["body"]
        assert post["content"] == "@Ada Lovelace can you check the launch dates?"
        assert [person["user_id"] for person in post["mentioned_participants"]] == ["ada"]
        print("  ok  the message was posted to the participants and no plan was requested")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_a_tagged_agent_is_planned_for_the_person_who_started_the_conversation():
    """'@Research Assistant ...' starts a plan that uses that agent and says who was addressed."""
    print("Testing a tagged agent is planned for the conversation's owner...")
    page = _PAGE
    try:
        _seed(page, reader=OWNER)
        requests = _send(page, "@Research Assistant summarize what @Ada Lovelace decided")

        assert _paths(requests) == ["/api/v2/orchestration/plan"], requests
        plan = requests[0]["body"]
        assert plan["conversation_id"] == CONVERSATION
        assert plan["invocation_target"]["target_type"] == "agent"
        assert plan["invocation_target"]["display_name"] == "Research Assistant"
        assert plan["agent_info"]["name"] == "researcher", plan
        assert [person["user_id"] for person in plan["mentioned_participants"]] == ["ada"]
        print("  ok  the plan request carries the agent, the target and the mentions")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_another_participant_is_answered_the_classic_way():
    """Only the person who started the conversation plans in it; others get a classic answer."""
    print("Testing another participant's request is answered without a plan...")
    page = _PAGE
    try:
        _seed(page, reader=ADA, started_by="owner")
        requests = _send(page, "@Research Assistant summarize the launch plan")

        assert "/api/v2/orchestration/plan" not in _paths(requests), requests
        assert _paths(requests) == [f"/api/collaboration/conversations/{CONVERSATION}/stream"], requests
        print("  ok  the request went to the shared assistant stream, not the planner")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


PAGE_TESTS = [
    test_a_message_to_a_person_is_posted_without_a_plan,
    test_a_tagged_agent_is_planned_for_the_person_who_started_the_conversation,
    test_another_participant_is_answered_the_classic_way,
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
