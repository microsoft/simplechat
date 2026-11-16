#!/usr/bin/env python3
# test_workflow_reply_replaces_agent_posted_message.py
"""
Functional test for a workflow's mirrored reply replacing the run's own posted message.
Version: 0.261.253
Implemented in: 0.261.253

This test ensures that when a workflow run creates a conversation, posts its own message there
and then has its reply mirrored in:

- the mirrored reply keeps the run's full content and every citation, maps included;
- the run's posted message stays stored but is marked superseded_by_workflow_reply, so clients
  do not show it, while messages people wrote, and posts that were not made through the agent
  action, are never marked;
- the workflow's own conversation is hidden the first time a run delivers into a conversation it
  created, and is never hidden again once a person shows it;
- a failure while hiding never undoes the mirror, and a retried mirror changes nothing;
- the classic client skips a superseded message in both its personal and shared message loops.

The real runner functions are compiled from functions_workflow_runner.py with Cosmos, the
collaboration store and logging replaced by in-memory fakes.
"""

import ast
import copy
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
# Appended, so the application's modules never shadow the test packages.
sys.path.append(str(APP_ROOT))

from collaboration_models import (  # noqa: E402
    COLLABORATION_KIND,
    GROUP_MULTI_USER_CHAT_TYPE,
    PERSONAL_MULTI_USER_CHAT_TYPE,
    normalize_collaboration_user,
)

RUNNER_FILE = APP_ROOT / "functions_workflow_runner.py"
MINIMUM_VERSION = "0.261.253"
RUNNER_FUNCTIONS = {
    "_extract_created_conversation_docs_from_citations",
    "_is_collaboration_target_conversation",
    "_extract_run_posted_message_ids_from_citations",
    "_hide_run_posts_superseded_by_reply",
    "_hide_workflow_conversation_after_delivery",
    "_mirror_workflow_visualizations_to_created_conversations",
}
RUNNER_CONSTANTS = {"WORKFLOW_REPLY_SUPERSEDED_METADATA_KEY"}

NOW = "2026-10-03T14:00:00+00:00"
WORKFLOW = {"id": "workflow-1", "name": "Alert watch", "user_id": "owner-1", "runner_type": "agent"}
WORKFLOW_CONVERSATION_ID = "workflow-conversation-1"
FULL_REPLY = "## Alert triage\n\nEverything the run found, with its map and sources."
MAP_CITATION = {
    "plugin_name": "AzureMapsOpenLayersPlugin",
    "function_name": "create_map_visualization",
    "success": True,
    "function_result": {"render_type": "azure_maps_openlayers", "map_payload": {"title": "Route", "markers": []}},
}
LOOKUP_CITATION = {
    "plugin_name": "toll_plate_reads",
    "function_name": "getPlateTrack",
    "success": True,
    "function_result": {"results": [{"read_id": "R-1"}]},
}


class NotFound(Exception):
    """Stands in for CosmosResourceNotFoundError."""


class FakeContainer:
    """A Cosmos container keyed by (partition key, id), recording every write."""

    def __init__(self, partition_field):
        self.partition_field = partition_field
        self.items = {}
        self.upserts = []
        self.fail_upserts_for = set()

    def seed(self, item):
        self.items[(item[self.partition_field], item["id"])] = copy.deepcopy(item)

    def get(self, partition_key, item_id):
        return copy.deepcopy(self.items.get((partition_key, item_id)))

    def read_item(self, item, partition_key):
        try:
            return copy.deepcopy(self.items[(partition_key, item)])
        except KeyError:
            raise NotFound(item) from None

    def upsert_item(self, item):
        if item["id"] in self.fail_upserts_for:
            raise RuntimeError("Cosmos write failed")
        self.upserts.append(copy.deepcopy(item))
        self.seed(item)
        return item


def _load_runner(namespace):
    tree = ast.parse(RUNNER_FILE.read_text(encoding="utf-8"), filename=str(RUNNER_FILE))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in RUNNER_FUNCTIONS:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in RUNNER_CONSTANTS for target in node.targets
        ):
            nodes.append(node)
    found = {node.name for node in nodes if isinstance(node, ast.FunctionDef)}
    assert found == RUNNER_FUNCTIONS, f"Missing runner functions: {sorted(RUNNER_FUNCTIONS - found)}"
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(RUNNER_FILE), "exec"), namespace)
    return namespace


class MirrorHarness:
    """The real mirror, with the stores it writes to held in memory."""

    def __init__(self):
        self.collaboration_messages = FakeContainer("conversation_id")
        self.personal_messages = FakeContainer("conversation_id")
        self.conversations = FakeContainer("id")
        self.cache_bumps = []
        self.notifications = []
        self.mirrored_sources = []
        self.warnings = []
        self.runner = _load_runner({
            "logging": logging,
            "CosmosResourceNotFoundError": NotFound,
            "cosmos_collaboration_messages_container": self.collaboration_messages,
            "cosmos_messages_container": self.personal_messages,
            "cosmos_conversations_container": self.conversations,
            "COLLABORATION_KIND": COLLABORATION_KIND,
            "GROUP_MULTI_USER_CHAT_TYPE": GROUP_MULTI_USER_CHAT_TYPE,
            "PERSONAL_MULTI_USER_CHAT_TYPE": PERSONAL_MULTI_USER_CHAT_TYPE,
            "normalize_collaboration_user": normalize_collaboration_user,
            "_utc_now_iso": lambda: NOW,
            "log_event": self.log_event,
            "bump_conversation_cache_version": self.bump_cache,
            "get_collaboration_conversation": lambda conversation_id: {
                "id": conversation_id, "chat_type": GROUP_MULTI_USER_CHAT_TYPE,
            },
            "mirror_source_message_to_collaboration": self.mirror_to_collaboration,
            "create_collaboration_message_notifications": lambda conversation, message: self.notifications.append(
                message["id"],
            ),
            "_mirror_assistant_message_to_personal_conversation": self.mirror_to_personal,
        })
        self.conversations.seed({
            "id": WORKFLOW_CONVERSATION_ID, "user_id": "owner-1", "chat_type": "workflow", "is_hidden": False,
        })

    # Collaborators ---------------------------------------------------------------------------

    def log_event(self, message, extra=None, level=logging.INFO, **kwargs):
        if level >= logging.WARNING:
            self.warnings.append(message)

    def bump_cache(self, user_id, reason="conversation_changed"):
        self.cache_bumps.append((user_id, reason))

    def mirror_to_collaboration(self, conversation, source_doc, sender, reply_to_message_id=None, extra_metadata=None):
        """Like the real mirror: one mirrored message per source message, found again on a retry."""
        mirror_id = f"{conversation['id']}_mirror"
        existing = self.collaboration_messages.get(conversation["id"], mirror_id)
        if existing:
            return existing, conversation, False
        self.mirrored_sources.append(copy.deepcopy(source_doc))
        mirrored = {
            "id": mirror_id, "conversation_id": conversation["id"], "role": "assistant",
            "content": source_doc["content"], "agent_citations": source_doc["agent_citations"],
            "metadata": {**(extra_metadata or {}), "sender": sender},
        }
        self.collaboration_messages.seed(mirrored)
        return mirrored, conversation, True

    def mirror_to_personal(self, workflow, source_doc, created_conversation, citations):
        self.mirrored_sources.append({**copy.deepcopy(source_doc), "agent_citations": copy.deepcopy(citations)})
        mirrored = {
            "id": f"{created_conversation['id']}-reply", "conversation_id": created_conversation["id"],
            "role": "assistant", "content": source_doc["content"], "agent_citations": citations,
            "metadata": {"source": "workflow_mirror"},
        }
        self.personal_messages.seed(mirrored)
        return mirrored

    # The run ---------------------------------------------------------------------------------

    def deliver(self, citations):
        """Mirror a finished run's reply, the way the runner's mirror_outputs unit does."""
        source_reply = {
            "id": "reply-1", "conversation_id": WORKFLOW_CONVERSATION_ID, "role": "assistant",
            "content": FULL_REPLY, "agent_citations": copy.deepcopy(citations),
            "hybrid_citations": [], "web_search_citations": [],
            "metadata": {"workflow": {"run_id": "run-1", "trigger_source": "scheduled"}},
        }
        return self.runner["_mirror_workflow_visualizations_to_created_conversations"](
            WORKFLOW, source_reply, {"agent_citations": copy.deepcopy(citations)},
        )

    def marker(self, container, conversation_id, message_id):
        doc = container.get(conversation_id, message_id) or {}
        return (doc.get("metadata") or {}).get("superseded_by_workflow_reply")

    def workflow_conversation(self):
        return self.conversations.get(WORKFLOW_CONVERSATION_ID, WORKFLOW_CONVERSATION_ID)


def agent_post(conversation_id, message_id, content="Opening briefing"):
    return {
        "id": message_id, "conversation_id": conversation_id, "role": "user", "content": content,
        "metadata": {"posted_via": "agent_action", "content_format": "markdown",
                     "sender": {"user_id": "owner-1", "display_name": "Workflow owner"}},
    }


def person_message(conversation_id, message_id, content="Looking at it now."):
    return {
        "id": message_id, "conversation_id": conversation_id, "role": "user", "content": content,
        "metadata": {"sender": {"user_id": "member-1", "display_name": "Team member"}},
    }


def created(function_name, conversation, seeded_message=None, success=True):
    result = {"success": success, "conversation": conversation}
    if seeded_message is not None:
        result.update(message=seeded_message, seeded_initial_message=True)
    return {
        "plugin_name": "SimpleChatPlugin", "function_name": function_name,
        "success": success, "function_result": result,
    }


def added(conversation, message, success=True):
    return {
        "plugin_name": "SimpleChatPlugin", "function_name": "add_conversation_message", "success": success,
        "function_result": {"success": success, "conversation": conversation, "message": message},
    }


GROUP = {"id": "group-1", "chat_type": GROUP_MULTI_USER_CHAT_TYPE, "conversation_kind": COLLABORATION_KIND}
PERSONAL = {"id": "personal-1", "chat_type": "personal_single_user"}


def test_group_conversation_keeps_the_full_reply_and_hides_the_run_post():
    """The created group conversation shows the run's whole reply, once."""
    print("Testing the group conversation delivery...")
    harness = MirrorHarness()
    seed = agent_post("group-1", "group-1_seed")
    harness.collaboration_messages.seed(seed)
    citations = [created("create_group_conversation", GROUP, seeded_message=seed), MAP_CITATION, LOOKUP_CITATION]

    delivered = harness.deliver(citations)

    assert delivered == ["group-1_mirror"], delivered
    [source] = harness.mirrored_sources
    assert source["content"] == FULL_REPLY
    assert source["agent_citations"] == citations, "Every citation, the map included, travels with the reply."
    assert harness.notifications == ["group-1_mirror"]

    stored_seed = harness.collaboration_messages.get("group-1", "group-1_seed")
    assert stored_seed["content"] == seed["content"], "The run's post stays stored."
    assert stored_seed["metadata"]["posted_via"] == "agent_action"
    assert harness.marker(harness.collaboration_messages, "group-1", "group-1_seed") == {
        "message_id": "group-1_mirror", "workflow_id": "workflow-1", "superseded_at": NOW,
    }
    assert harness.marker(harness.collaboration_messages, "group-1", "group-1_mirror") is None

    conversation = harness.workflow_conversation()
    assert conversation["is_hidden"] is True
    assert conversation["workflow_delivery_hidden_at"] == NOW
    assert harness.cache_bumps == [("owner-1", "workflow_conversation_hidden_after_delivery")]
    assert harness.warnings == []
    print("  Group delivery passed.")
    return True


def test_personal_conversation_hides_the_run_post_after_its_reply():
    """A created personal conversation follows the same rule on the personal message store."""
    print("Testing the personal conversation delivery...")
    harness = MirrorHarness()
    seed = agent_post("personal-1", "personal-seed")
    harness.personal_messages.seed(seed)

    delivered = harness.deliver([created("create_personal_conversation", PERSONAL, seeded_message=seed), MAP_CITATION])

    assert delivered == ["personal-1-reply"], delivered
    assert harness.marker(harness.personal_messages, "personal-1", "personal-seed")["message_id"] == "personal-1-reply"
    assert harness.collaboration_messages.upserts == [], "The shared store is never touched for a personal conversation."
    assert harness.workflow_conversation()["is_hidden"] is True
    print("  Personal delivery passed.")
    return True


def test_only_the_runs_own_agent_posts_are_hidden():
    """Later agent posts are hidden too; people's messages and unmarked posts never are."""
    print("Testing which messages are hidden...")
    harness = MirrorHarness()
    seed = agent_post("group-1", "group-1_seed")
    follow_up = agent_post("group-1", "group-1_follow_up", content="Meeting booked for 6 p.m.")
    reply = person_message("group-1", "group-1_person")
    # Claimed by a tool result, but not written through the agent action: never hidden.
    unmarked = person_message("group-1", "group-1_unmarked", content="Typed by a person.")
    for message in (seed, follow_up, reply, unmarked):
        harness.collaboration_messages.seed(message)

    harness.deliver([
        created("create_group_conversation", GROUP, seeded_message=seed),
        added(GROUP, follow_up),
        added(GROUP, unmarked),
        added(GROUP, {"id": "group-1_failed", "conversation_id": "group-1"}, success=False),
        MAP_CITATION,
    ])

    assert harness.marker(harness.collaboration_messages, "group-1", "group-1_seed")
    assert harness.marker(harness.collaboration_messages, "group-1", "group-1_follow_up")
    assert harness.marker(harness.collaboration_messages, "group-1", "group-1_person") is None
    assert harness.marker(harness.collaboration_messages, "group-1", "group-1_unmarked") is None
    written = sorted(item["id"] for item in harness.collaboration_messages.upserts)
    assert written == ["group-1_follow_up", "group-1_seed"], written
    print("  Hidden-message selection passed.")
    return True


def test_a_conversation_created_without_a_post_still_gets_the_reply():
    """Without a post of the run's own there is nothing to hide, and the reply is still delivered."""
    print("Testing a created conversation with no opening post...")
    harness = MirrorHarness()
    person = person_message("group-1", "group-1_person")
    harness.collaboration_messages.seed(person)

    delivered = harness.deliver([created("create_group_conversation", GROUP), MAP_CITATION])

    assert delivered == ["group-1_mirror"], delivered
    assert harness.collaboration_messages.upserts == []
    assert harness.marker(harness.collaboration_messages, "group-1", "group-1_person") is None
    assert harness.workflow_conversation()["is_hidden"] is True, "The reply was delivered, so the run's record steps back."
    print("  No-post delivery passed.")
    return True


def test_a_run_that_creates_nothing_leaves_its_conversation_alone():
    """No created conversation, no delivery: the workflow conversation is where the result lives."""
    print("Testing a run that creates no conversation...")
    harness = MirrorHarness()

    delivered = harness.deliver([MAP_CITATION, LOOKUP_CITATION])
    failed = harness.deliver([created("create_group_conversation", {}, success=False)])

    assert delivered == [] and failed == []
    assert harness.workflow_conversation()["is_hidden"] is False
    assert harness.cache_bumps == []
    print("  No-delivery run passed.")
    return True


def test_the_workflow_conversation_is_hidden_once_and_a_person_can_show_it_again():
    """Later runs never overrule a person who showed the conversation again."""
    print("Testing the one-time hide of the workflow conversation...")
    harness = MirrorHarness()
    harness.deliver([created("create_group_conversation", GROUP), MAP_CITATION])
    assert harness.workflow_conversation()["is_hidden"] is True

    shown_again = harness.workflow_conversation()
    shown_again["is_hidden"] = False
    harness.conversations.seed(shown_again)
    harness.deliver([created("create_personal_conversation", PERSONAL), MAP_CITATION])

    conversation = harness.workflow_conversation()
    assert conversation["is_hidden"] is False
    assert conversation["workflow_delivery_hidden_at"] == NOW
    assert len(harness.cache_bumps) == 1, harness.cache_bumps

    hide = harness.runner["_hide_workflow_conversation_after_delivery"]
    harness.conversations.seed({"id": "already-hidden", "user_id": "u", "chat_type": "workflow", "is_hidden": True})
    harness.conversations.seed({"id": "ordinary-chat", "user_id": "u", "chat_type": "personal_single_user"})
    assert hide("already-hidden") is False
    assert "workflow_delivery_hidden_at" not in harness.conversations.get("already-hidden", "already-hidden")
    assert hide("ordinary-chat") is False
    assert "is_hidden" not in harness.conversations.get("ordinary-chat", "ordinary-chat")
    assert hide("missing") is False and hide("") is False
    print("  One-time hide passed.")
    return True


def test_a_retried_mirror_changes_nothing():
    """The mirror is found again on a retry; nothing is notified, posted or re-stamped twice."""
    print("Testing a retried mirror...")
    harness = MirrorHarness()
    seed = agent_post("group-1", "group-1_seed")
    harness.collaboration_messages.seed(seed)
    citations = [created("create_group_conversation", GROUP, seeded_message=seed), MAP_CITATION]

    harness.deliver(citations)
    writes = len(harness.collaboration_messages.upserts)
    retried = harness.deliver(citations)

    assert retried == [], "Nothing new was mirrored."
    assert harness.notifications == ["group-1_mirror"]
    assert len(harness.collaboration_messages.upserts) == writes, "An already hidden post is not rewritten."
    assert harness.marker(harness.collaboration_messages, "group-1", "group-1_seed")["message_id"] == "group-1_mirror"
    print("  Retry passed.")
    return True


def test_a_failure_while_hiding_never_undoes_the_delivery():
    """Hiding is best effort: the post stays visible and the reply is still delivered."""
    print("Testing a failed hide...")
    harness = MirrorHarness()
    seed = agent_post("group-1", "group-1_seed")
    harness.collaboration_messages.seed(seed)
    harness.collaboration_messages.fail_upserts_for.add("group-1_seed")

    delivered = harness.deliver([created("create_group_conversation", GROUP, seeded_message=seed), MAP_CITATION])

    assert delivered == ["group-1_mirror"], delivered
    assert harness.marker(harness.collaboration_messages, "group-1", "group-1_seed") is None
    assert any("Failed to hide a run-posted message" in warning for warning in harness.warnings), harness.warnings
    assert harness.workflow_conversation()["is_hidden"] is True
    print("  Failed hide passed.")
    return True


def test_classic_message_loops_skip_superseded_messages():
    """Both classic loops leave a superseded message out before rendering it."""
    print("Testing the classic message loops...")
    personal = (APP_ROOT / "static" / "js" / "chat" / "chat-messages.js").read_text(encoding="utf-8")
    shared = (APP_ROOT / "static" / "js" / "chat" / "chat-collaboration.js").read_text(encoding="utf-8")

    personal_loop = personal[personal.index("data.messages.forEach((msg) => {"):]
    assert personal_loop.index("msg.metadata.superseded_by_workflow_reply") < personal_loop.index("appendMessage(")
    shared_loop = shared[shared.index("messages.forEach(message => {"):]
    skip = shared_loop.index("message?.metadata?.superseded_by_workflow_reply")
    assert skip < shared_loop.index("renderCollaborationMessage(decoratedMessage)")
    # Cached before returning, so a later reply that quotes it still resolves.
    assert shared_loop.index("cacheCollaborationMessage(message);", skip) < shared_loop.index("return;", skip)
    print("  Classic loops passed.")
    return True


def test_version():
    assert_app_version_at_least(MINIMUM_VERSION)
    return True


if __name__ == "__main__":
    tests = [
        test_group_conversation_keeps_the_full_reply_and_hides_the_run_post,
        test_personal_conversation_hides_the_run_post_after_its_reply,
        test_only_the_runs_own_agent_posts_are_hidden,
        test_a_conversation_created_without_a_post_still_gets_the_reply,
        test_a_run_that_creates_nothing_leaves_its_conversation_alone,
        test_the_workflow_conversation_is_hidden_once_and_a_person_can_show_it_again,
        test_a_retried_mirror_changes_nothing,
        test_a_failure_while_hiding_never_undoes_the_delivery,
        test_classic_message_loops_skip_superseded_messages,
        test_version,
    ]
    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001 - report every failure
            import traceback

            print(f"FAILED {test.__name__}: {exc}")
            traceback.print_exc()
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
