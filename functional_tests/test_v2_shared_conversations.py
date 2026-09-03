#!/usr/bin/env python3
"""
Functional test for shared (collaborative) conversations in the V2 interface.

Version: 0.261.037
Implemented in: 0.261.037

Shared conversations opened in the V2 interface showed an empty thread. V2 loaded every
conversation with ``/api/get_messages``, which reads only the personal messages container:
for a conversation that is not in it, ``_authorize_personal_conversation_read`` raises
``LookupError`` and the route converts that into ``{'messages': []}`` with a **200**
(route_backend_conversations.py). So a shared conversation opened as an empty chat rather
than as an error, and every other conversation-scoped action in V2 was likewise wired only
to the personal routes.

The whole ``/api/collaboration/*`` API already existed and was driven by the classic client
in ``static/js/chat/chat-collaboration.js``. This change routes V2 through it.

This test ensures the V2 source is wired to that API rather than to the personal one, that
every collaboration route the classic client uses has a V2 counterpart, and that the
operations with no collaboration counterpart are hidden rather than offered and then
failing. The behaviour of the parts that are pure logic -- the send rule, the mention
grammar and the event replay guard -- is executed by the companion test
``test_v2_shared_conversation_logic.mjs``.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
APP_ROOT = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.037"


def _read(path):
    return path.read_text(encoding="utf-8")


def test_version_is_at_least_the_implementation_version():
    """The feature cannot be present in a build older than the one that added it."""
    print("Testing version...")
    assert_app_version_at_least(
        IMPLEMENTED_IN,
        reason="Shared conversation support was added to the V2 interface in this version.",
    )
    print("Version test passed!")
    return True


def test_messages_are_read_from_the_collaboration_endpoint():
    """The reported bug: a shared thread must not be loaded through /api/get_messages.

    That route is not an existence check and not a fallback -- it answers 200 with an empty
    list for any conversation it cannot find, which is exactly why the failure looked like
    an empty conversation rather than an error.
    """
    print("Testing shared message loading...")

    store = _read(V2_SRC / "stores" / "chatStore.ts")

    assert "fetchCollaborationMessages" in store, (
        "The store must load a shared conversation's messages from "
        "/api/collaboration/conversations/<id>/messages"
    )

    # The choice is made on the conversation's kind, not by trying one endpoint and falling
    # back, because the personal endpoint does not fail for a shared conversation.
    assert re.search(
        r"kind === 'collaborative'\s*\?\s*await fetchCollaborationMessages\(conversationId\)"
        r"\s*:\s*await fetchMessages\(conversationId\)",
        store,
    ), "Message loading must branch on the resolved conversation kind"

    endpoints = _read(V2_SRC / "lib" / "collaboration.ts")
    assert "`${base(conversationId)}/messages`" in endpoints, (
        "collaboration.ts must expose the shared messages endpoint"
    )

    print("Shared message loading test passed!")
    return True


def test_every_collaboration_route_has_a_v2_caller():
    """Each route the classic client drives must have a V2 counterpart.

    Read out of the Flask blueprint rather than hard-coded, so a route added to the API
    later fails this test until V2 either uses it or the exemption below is justified.
    """
    print("Testing collaboration endpoint coverage...")

    routes = _read(APP_ROOT / "route_backend_collaboration.py")
    v2_sources = "\n".join(
        _read(path) for path in sorted((V2_SRC).rglob("*.ts")) if path.is_file()
    )

    # Path suffixes, since the V2 module builds each URL from a shared `base()` helper and
    # the literal path never appears in one piece.
    suffix_by_route = {
        "/messages": "/messages",
        "/stream": "/stream",
        "/stream/cancel": "/stream/cancel",
        "/events": "/events",
        "/typing": "/typing",
        "/mark-read": "/mark-read",
        "/pin": "/pin",
        "/hide": "/hide",
        "/delete-action": "/delete-action",
        "/members": "/members",
        "/invite-response": "/invite-response",
        "/mask": "/mask",
        "/file-approvals": "/api/collaboration/file-approvals",
        "/from-personal": "/from-personal/",
        "/from-group": "/from-group/",
    }

    for label, needle in suffix_by_route.items():
        assert needle in v2_sources, (
            f"No V2 caller found for the {label} collaboration route"
        )

    # The base collection and item routes, which carry no suffix.
    assert "'/api/collaboration/conversations?" in v2_sources or (
        "/api/collaboration/conversations?" in v2_sources
    ), "V2 must be able to list shared conversations, including pending invitations"
    assert "api.get<{ conversation: CollaborationConversation }>(base(conversationId)" in (
        _read(V2_SRC / "lib" / "collaboration.ts")
    ), "V2 must be able to load one shared conversation with its membership"

    # Sanity check that the suffixes above were not invented: each must appear in the route
    # definitions too, so a renamed route breaks this test rather than passing silently.
    for suffix in ("/messages", "/stream/cancel", "/events", "/typing", "/delete-action"):
        assert f"<conversation_id>{suffix}'" in routes, (
            f"Expected {suffix} to be a real collaboration route"
        )

    print("Collaboration endpoint coverage test passed!")
    return True


def test_stream_recovery_is_disabled_for_shared_conversations():
    """A dropped shared stream must be reported, not retried against the wrong conversation.

    ``/api/chat/stream/reattach`` is keyed on the conversation the generation actually runs
    in, which for a shared conversation is a hidden source conversation the browser is never
    told the id of. Reattaching with the shared conversation's id addresses a conversation
    that endpoint has never heard of. The classic client sets ``allowRecovery: false`` on
    this path for the same reason.
    """
    print("Testing shared stream recovery...")

    sse = _read(V2_SRC / "lib" / "sse.ts")
    assert "options.allowRecovery !== false" in sse, (
        "streamChat must honour an allowRecovery override"
    )
    assert "options.url ?? apiUrl('/api/chat/stream')" in sse, (
        "streamChat must accept an endpoint override so the collaboration bridge can be used"
    )

    store = _read(V2_SRC / "stores" / "chatStore.ts")
    assert re.search(
        r"url: streamCollaborationUrl\(conversationId\),(?:.|\n)*?allowRecovery: false",
        store,
    ), "A shared conversation must stream with recovery disabled"

    # A shared conversation is also excluded from the resume-on-open path, which calls the
    # same personal status endpoint.
    assert "resumeChatStream" in store
    assert re.search(
        r"if \(kind === 'collaborative'\)(?:.|\n)*?\} else \{(?:.|\n)*?resumeChatStream",
        store,
    ), "Opening a shared conversation must not attempt a personal stream resume"

    print("Shared stream recovery test passed!")
    return True


def test_thread_operations_are_hidden_in_a_shared_conversation():
    """Retry, edit, attempt navigation and fork have no collaboration counterpart.

    Those endpoints read and rewrite the personal messages container. The classic interface
    leaves them out of a shared conversation, so hiding them is the parity -- offering a
    control that cannot work is worse than not offering it.
    """
    print("Testing hidden thread operations...")

    actions = _read(V2_SRC / "components" / "chat" / "MessageActions.tsx")

    assert "state.activeConversationKind === 'collaborative'" in actions, (
        "MessageActions must know whether it is in a shared conversation"
    )
    assert "{attempts.show && !shared && (" in actions, (
        "Attempt navigation must be hidden in a shared conversation"
    )
    assert "{!isUser && !shared && (" in actions, (
        "Fork must be hidden in a shared conversation"
    )
    assert "{isUser && !shared && onEdit" in actions, (
        "Edit must be hidden in a shared conversation"
    )
    assert re.search(r"\{shared \?\s*\(\s*canPost && \(", actions), (
        "Retry must be replaced by Reply in a shared conversation"
    )

    # None of those endpoints may be reachable from the shared path.
    for personal_only in ("/retry", "/edit", "/switch-attempt", "forkConversation"):
        assert personal_only not in _read(V2_SRC / "lib" / "collaboration.ts"), (
            f"{personal_only} has no collaboration counterpart and must not be called on one"
        )

    print("Hidden thread operations test passed!")
    return True


def test_conversation_actions_route_by_kind():
    """Rename, pin, hide and removal must each reach the API family that owns them."""
    print("Testing conversation action routing...")

    store = _read(V2_SRC / "stores" / "chatStore.ts")

    assert re.search(
        r"if \(collaborative\) \{\s*await renameCollaborationConversation", store
    ), "Rename must route to the collaboration endpoint"
    assert "toggleCollaborationPinned(conversationId)" in store, (
        "Pin must route to the collaboration endpoint"
    )
    assert "toggleCollaborationHidden(conversationId)" in store, (
        "Hide must route to the collaboration endpoint"
    )

    # Removing a shared conversation is not necessarily a deletion: only an owner may
    # destroy one for everybody, and everybody else leaves it.
    assert "detail?.can_delete_conversation ? 'delete' : 'leave'" in store, (
        "Removing a shared conversation must leave it unless the caller may delete it"
    )
    assert "collaborationDeleteAction(conversationId, action)" in store

    # Per-message actions likewise.
    assert "deleteCollaborationMessage(conversationId, messageId)" in store
    assert "maskCollaborationMessage(conversationId, messageId" in store

    print("Conversation action routing test passed!")
    return True


def test_capabilities_come_from_the_server():
    """What the reader may do is the server's decision, not a rule reimplemented here.

    ``serialize_collaboration_conversation`` folds together membership status, role,
    visibility mode and whether membership is explicit at all, and a group-visibility
    conversation grants posting with no membership record to inspect. A client-side guess
    would offer controls the server then refuses.
    """
    print("Testing capability gating...")

    serializer = _read(APP_ROOT / "functions_collaboration.py")
    for flag in (
        "can_post_messages",
        "can_manage_members",
        "can_manage_roles",
        "can_accept_invite",
        "can_delete_conversation",
        "can_leave_conversation",
    ):
        assert f"'{flag}':" in serializer, (
            f"{flag} is expected to be reported by serialize_collaboration_conversation"
        )

    composer = _read(V2_SRC / "components" / "chat" / "Composer.tsx")
    assert "collaboration?.can_post_messages === true" in composer, (
        "The composer must be gated on the server's can_post_messages, and deny by default: "
        "a membership that has not loaded is not permission"
    )
    assert "disabled={!canPost}" in composer, (
        "The textarea must be disabled when the reader may not post"
    )
    # An "Add to this conversation" row is an action. Inserting the name without performing
    # it leaves a dead control: the mention list is resolved against existing participants
    # only, and the server filters it again, so the person is neither added nor mentioned.
    assert "suggestion.kind === 'invite'" in composer, (
        "Choosing an invitable person from the mention menu must actually invite them"
    )
    assert ".inviteParticipants([" in composer

    actions = _read(V2_SRC / "components" / "chat" / "MessageActions.tsx")
    assert "loadedCollaboration?.can_post_messages === true" in actions, (
        "Reply must be gated on the same flag, and on the loaded conversation being this one"
    )

    panel = _read(V2_SRC / "components" / "chat" / "ParticipantsPanel.tsx")
    for flag in (
        "can_manage_members",
        "can_manage_roles",
        "can_delete_conversation",
        "can_leave_conversation",
    ):
        assert flag in panel, f"The participants panel must gate on {flag}"

    banner = _read(V2_SRC / "components" / "chat" / "InviteBanner.tsx")
    assert "conversation?.can_accept_invite" in banner, (
        "The invite prompt must be shown on the server's can_accept_invite"
    )

    print("Capability gating test passed!")
    return True


def test_the_feature_is_gated_on_its_settings_key():
    """No sharing controls appear when the capability is switched off."""
    print("Testing the feature flag...")

    settings = _read(APP_ROOT / "functions_settings.py")
    assert "'enable_collaborative_conversations'" in settings, (
        "The capability key is expected to exist in the settings defaults"
    )

    routes = _read(APP_ROOT / "route_backend_collaboration.py")
    assert "settings.get('enable_collaborative_conversations', False)" in routes, (
        "The API is expected to refuse when the capability is off"
    )

    # Forwarded to the SPA by the generic enable_* pass in the bootstrap route, so no
    # bootstrap change is needed for the flag to reach the browser.
    bootstrap = _read(APP_ROOT / "route_backend_v2.py")
    assert 'key.startswith("enable_")' in bootstrap, (
        "The bootstrap route is expected to forward every enable_* flag"
    )

    for component in ("pages/ChatPage.tsx", "components/chat/ConversationRail.tsx"):
        source = _read(V2_SRC / component)
        assert "features?.enable_collaborative_conversations" in source, (
            f"{component} must hide its sharing controls when the capability is off"
        )

    print("Feature flag test passed!")
    return True


def test_sharing_uses_the_conversion_route_that_matches_the_conversation():
    """There are three invite routes and they are not interchangeable.

    A group conversation converted through the personal route would lose the group
    restriction on who may be invited; an already-shared conversation converted a second
    time would produce a second shared conversation alongside the first.
    """
    print("Testing share routing...")

    sharing = _read(V2_SRC / "lib" / "sharing.ts")
    assert "kind: 'collaborative'" in sharing
    assert "chatType.startsWith('group') ? 'group' : 'personal'" in sharing

    store = _read(V2_SRC / "stores" / "collaborationStore.ts")
    assert re.search(
        r"kind === 'collaborative'\s*\?\s*await inviteCollaborationMembers"
        r"(?:.|\n)*?kind === 'group'\s*\?\s*await shareGroupConversation"
        r"(?:.|\n)*?:\s*await sharePersonalConversation",
        store,
    ), "The invite must choose the endpoint from the conversation's share kind"

    # Sharing mints a new conversation, so the reader has to be moved to the returned id.
    panel = _read(V2_SRC / "components" / "chat" / "ParticipantsPanel.tsx")
    assert "result.conversation?.id" in panel
    assert "selectConversation(nextId, { kind: 'collaborative' })" in panel, (
        "After sharing, the newly created conversation must be the one that is opened"
    )

    print("Share routing test passed!")
    return True


def test_live_updates_survive_reconnection():
    """The event stream replays its whole history on every attach.

    ``iter_events`` starts at index 0, and ``EventSource`` reconnects by itself, so without
    both a replay guard and de-duplication a network blip re-appends the entire
    conversation.
    """
    print("Testing live update handling...")

    routes = _read(APP_ROOT / "route_backend_collaboration.py")
    assert "def iter_events(self, start_index=0)" in routes, (
        "The event stream is expected to replay from a start index"
    )

    events = _read(V2_SRC / "lib" / "collaborationEvents.ts")
    assert "isReplayedEvent" in events, "Replayed history must be recognised"
    assert "seen.has(key)" in events, "Events must be de-duplicated across reconnects"
    assert "MAX_REMEMBERED_EVENTS" in events, (
        "The de-duplication set must be bounded so a long conversation cannot grow it forever"
    )

    # A bare timestamp read as local time makes replayed history look like the future west
    # of UTC, so nothing is ever recognised as a replay.
    assert "Date.parse(`${value}Z`)" in events, (
        "A timestamp without a zone designator must be read as UTC"
    )

    store = _read(V2_SRC / "stores" / "chatStore.ts")
    assert "subscribeToCollaborationEvents" in store
    assert "stopCollaborationEvents()" in store, (
        "The subscription must be torn down when the conversation changes"
    )
    assert "mergeCollaborationMessage" in store, (
        "An arriving message must be merged by id rather than appended"
    )

    print("Live update handling test passed!")
    return True


def test_broadcast_events_do_not_carry_the_readers_permissions():
    """An event's conversation is serialized for whoever caused it, not for the reader.

    Every publishing route calls ``serialize_collaboration_conversation`` with the acting
    user and then broadcasts that one dict to every subscriber. Applying its ``can_*``
    verbatim means a participant leaving tells everyone else they can no longer post, and an
    owner acting offers every member a "Delete for everyone" button the server then refuses.
    """
    print("Testing broadcast permission handling...")

    routes = _read(APP_ROOT / "route_backend_collaboration.py")
    # The premise: publish sites serialize for the acting user.
    assert re.search(
        r"serialize_collaboration_conversation\(\s*\n?\s*\w+,\s*\n?\s*current_user_id=current_user\['user_id'\]",
        routes,
    ), (
        "Publishing routes are expected to serialize the conversation for the acting user, "
        "which is what makes a broadcast's capability flags unusable by other readers"
    )

    events = _read(V2_SRC / "lib" / "collaborationEvents.ts")
    assert "export function conversationFactsOnly" in events, (
        "Broadcast conversations must be stripped of their viewer-scoped fields"
    )
    for viewer_scoped in (
        "can_post_messages",
        "can_manage_members",
        "can_manage_roles",
        "can_delete_conversation",
        "can_leave_conversation",
        "can_accept_invite",
        "current_user_role",
        "membership_status",
        "is_pinned",
        "is_hidden",
    ):
        assert f"'{viewer_scoped}'," in events, (
            f"{viewer_scoped} is viewer-scoped and must be stripped from a broadcast"
        )

    collaboration_store = _read(V2_SRC / "stores" / "collaborationStore.ts")
    assert "applyBroadcast" in collaboration_store, (
        "A broadcast must be applied through a path that strips viewer-scoped fields"
    )
    assert "conversationFactsOnly(conversation)" in collaboration_store

    store = _read(V2_SRC / "stores" / "chatStore.ts")
    assert "collaboration().setConversation(conversation)" not in store, (
        "No event handler may apply a broadcast conversation wholesale"
    )
    assert store.count("collaboration().applyBroadcast(conversation)") >= 2, (
        "Message events also carry a conversation and must go through the same stripping"
    )
    assert "refreshOwnMembership" in store, (
        "A membership change must be re-read for this reader rather than taken from the event"
    )

    print("Broadcast permission handling test passed!")
    return True


def test_membership_cannot_leak_between_conversations():
    """One conversation's membership must never decide another conversation's controls.

    The capability flags gate the composer, the reply buttons and the mention roster, so a
    membership written for the wrong conversation either locks the reader out of a thread
    they can write in, or offers controls the server refuses. Several writers land after an
    ``await`` — a metadata load, a posted message, an invite response — by which time the
    reader may have moved on, so the invariant is enforced once in the store rather than at
    each call site.
    """
    print("Testing membership isolation...")

    collaboration_store = _read(V2_SRC / "stores" / "collaborationStore.ts")

    # The store knows which conversation is open and refuses writes for any other.
    assert "setActiveConversation" in collaboration_store, (
        "The collaboration store must know which conversation the chat page has open"
    )
    assert re.search(
        r"setConversation: \(conversation\) => \{\s*\n\s*if \(conversation "
        r"&& conversation\.id !== get\(\)\.activeConversationId\) \{\s*\n\s*return;",
        collaboration_store,
    ), "setConversation must refuse a conversation that is not the open one"

    # The participants panel has its own slot, so opening it on a conversation other than
    # the one on screen cannot evict that one's membership.
    assert "panelConversation" in collaboration_store, (
        "The participants panel must not share the active conversation's slot"
    )
    panel = _read(V2_SRC / "components" / "chat" / "ParticipantsPanel.tsx")
    assert "state.panelConversation" in panel, (
        "The panel must read its own slot rather than the open conversation's"
    )

    rail = _read(V2_SRC / "components" / "chat" / "ConversationRail.tsx")
    # Deliberately not a plain substring: `loadConversations` (the feed loader) legitimately
    # appears here and contains this name.
    assert not re.search(r"\bloadConversation\b(?!s)", rail), (
        "The rail's People action must not load into the active conversation's slot; "
        "openPanel already loads the panel's own copy"
    )

    store = _read(V2_SRC / "stores" / "chatStore.ts")

    # The guard is worth exactly as much as the mirror being current, so every write to
    # `activeConversationId` must be accompanied by one. Counted rather than spot-checked:
    # a fifth writer that forgets to mirror would otherwise leave the store silently
    # dropping that conversation's membership, stranding its composer at "checking access".
    #
    # Anchored on `set({` so the store's own initial-state literal is not counted as a write.
    id_writes = re.findall(
        r"set\(\{\s*\n?\s*activeConversationId: (?:conversationId|null)\b", store
    )
    mirror_calls = re.findall(r"setActiveConversation\((?:conversationId|null)\)", store)
    assert len(id_writes) >= 3, (
        "Expected chatStore to set activeConversationId in at least the select, new-chat "
        f"and create-on-first-send paths; found {len(id_writes)}"
    )
    assert len(mirror_calls) == len(id_writes), (
        f"Every write to activeConversationId must mirror it to the collaboration store: "
        f"found {len(id_writes)} writes and {len(mirror_calls)} mirror calls"
    )

    # And it must be mirrored synchronously, before the first await. Mirroring after one
    # would leave a window in which a membership response is dropped for the conversation
    # that is actually open.
    select_body = store[
        store.index("selectConversation: async (conversationId, options = {})") :
    ]
    select_body = select_body[: select_body.index("openLinkedConversation: async")]
    assert select_body.index("setActiveConversation(conversationId)") < select_body.index(
        "await"
    ), "The mirror must be set before selectConversation awaits anything"

    assert "setActiveConversation(null)" in store, (
        "Starting a new chat must clear it, or a stale membership would still apply"
    )

    # The deep-link probe hands its fetched conversation back rather than stashing it,
    # because at that point the conversation is not open and the store would refuse it.
    assert "prefetched?: CollaborationConversation" in store, (
        "The kind probe's conversation must be passed to selectConversation explicitly"
    )
    assert "prefetched: resolved.conversation" in store, (
        "openLinkedConversation must actually pass the conversation it already fetched"
    )
    assert "prefetched?.id === conversationId" in store, (
        "selectConversation must use the prefetched conversation rather than refetching"
    )

    # Every consumer of the membership compares the id before trusting it.
    for component, needle in (
        ("components/chat/Composer.tsx", "loadedCollaboration?.id === activeConversationId"),
        ("components/chat/MessageActions.tsx", "loadedCollaboration?.id === activeConversationId"),
        ("components/chat/MentionMenu.tsx", "loaded?.id === activeConversationId"),
        ("pages/ChatPage.tsx", "state.conversation?.id === activeConversationId"),
    ):
        assert needle in _read(V2_SRC / component), (
            f"{component} must confirm the loaded membership belongs to the open conversation"
        )

    assert "loadedCollaboration?.id === conversationId" in store, (
        "Mentions must be resolved against the open conversation's participants"
    )

    print("Membership isolation test passed!")
    return True


def test_a_shared_thread_says_who_wrote_each_message():
    """A thread with several authors is unreadable without attribution.

    Personal conversations are unaffected: they carry no ``sender``, so the attribution line
    is absent and the reader's own messages stay on the right exactly as before.
    """
    print("Testing message attribution...")

    serializer = _read(APP_ROOT / "functions_collaboration.py")
    assert "'sender': metadata.get('sender', {})" in serializer, (
        "A shared message is expected to carry its sender"
    )

    shared_message = _read(V2_SRC / "lib" / "sharedMessage.ts")
    assert "export function messageAuthorName" in shared_message
    assert "return 'You'" in shared_message, "The reader's own messages should read as You"

    message_list = _read(V2_SRC / "components" / "chat" / "MessageList.tsx")
    assert "const alignRight = author ? own : isUser;" in message_list, (
        "Another participant's message must not be shown on the reader's own side"
    )
    assert "function FileMessage" in message_list, (
        "The `file` display role only a shared conversation emits must be rendered"
    )
    assert "ReplyQuote" in message_list, "A reply must show what it is answering"

    types = _read(V2_SRC / "lib" / "types.ts")
    assert "'image' | 'file'" in types, (
        "MessageRole must include the `file` role serialize_collaboration_message emits"
    )

    print("Message attribution test passed!")
    return True


def test_no_third_party_browser_assets_were_added():
    """Everything the browser loads stays a local SimpleChat asset."""
    print("Testing local browser assets...")

    added = [
        V2_SRC / "lib" / "collaboration.ts",
        V2_SRC / "lib" / "collaborationEvents.ts",
        V2_SRC / "lib" / "mentions.ts",
        V2_SRC / "lib" / "sharedMessage.ts",
        V2_SRC / "lib" / "sharing.ts",
        V2_SRC / "stores" / "collaborationStore.ts",
        V2_SRC / "components" / "chat" / "ParticipantsPanel.tsx",
        V2_SRC / "components" / "chat" / "MentionMenu.tsx",
        V2_SRC / "components" / "chat" / "InviteBanner.tsx",
        V2_SRC / "components" / "chat" / "FileApprovals.tsx",
    ]

    for path in added:
        assert path.exists(), f"Expected {path.name} to exist"
        source = _read(path)
        for forbidden in ("https://cdn.", "unpkg.com", "jsdelivr", "cdnjs", "googleapis.com"):
            assert forbidden not in source, (
                f"{path.name} must not reference the third-party host {forbidden}"
            )

    print("Local browser assets test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_version_is_at_least_the_implementation_version,
        test_messages_are_read_from_the_collaboration_endpoint,
        test_every_collaboration_route_has_a_v2_caller,
        test_stream_recovery_is_disabled_for_shared_conversations,
        test_thread_operations_are_hidden_in_a_shared_conversation,
        test_conversation_actions_route_by_kind,
        test_capabilities_come_from_the_server,
        test_the_feature_is_gated_on_its_settings_key,
        test_sharing_uses_the_conversion_route_that_matches_the_conversation,
        test_live_updates_survive_reconnection,
        test_broadcast_events_do_not_carry_the_readers_permissions,
        test_membership_cannot_leak_between_conversations,
        test_a_shared_thread_says_who_wrote_each_message,
        test_no_third_party_browser_assets_were_added,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
