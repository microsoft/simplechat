// test_v2_shared_conversation_logic.mjs
//
// Runtime test for the pure logic behind V2 shared conversations.
// Version: 0.261.037
// Implemented in: 0.261.037
//
// The companion test, test_v2_shared_conversations.py, asserts that the V2 modules are wired
// to the right endpoints and that the actions with no collaboration counterpart are hidden.
// Those are source assertions: they prove the pieces are connected, not that they behave.
//
// This file executes the two decisions that are pure logic and where a quiet mistake is
// invisible until somebody is harmed by it:
//
//   1. The send rule. Getting it wrong either sends a private remark between colleagues to
//      the model, or silently swallows a question addressed to it.
//   2. The mention grammar. A mention that fails to match means the named person is never
//      notified; one that over-matches notifies the wrong person.
//
// Also covered is the event-stream replay guard, because failing it re-appends an entire
// conversation on every reconnect.
//
// Run directly with `node functional_tests/test_v2_shared_conversation_logic.mjs`. Requires
// Node 22.6 or newer, which strips the TypeScript types so the real modules can be imported
// rather than a copy of them.

import assert from 'node:assert/strict';
// Registers the resolver that lets the real V2 modules be imported by their bundler-style
// specifiers. Must be static, and must come before the dynamic imports below, because a
// static import is evaluated before this module's own body runs.
import './test_support/tsResolve.mjs';

const {
    buildMentionSuggestions,
    extractMentionedParticipants,
    findMentionAtCaret,
    mentionsCurrentUser,
    mentionsName,
    replaceMention,
    resolveInvocationTarget,
    resolveSendTarget,
    shouldInvokeAi,
} = await import('../application/v2_ui/src/lib/mentions.ts');
const {
    conversationFactsOnly,
    dispatchCollaborationEvent,
    isReplayedEvent,
    parseEventTimestamp,
} = await import('../application/v2_ui/src/lib/collaborationEvents.ts');
const {
    buildReplyPreview,
    isAiRequest,
    isOwnMessage,
    messageAuthorName,
    resolveReplyContext,
} = await import('../application/v2_ui/src/lib/sharedMessage.ts');
const { canShareConversation, panelTargetForConversation } = await import(
    '../application/v2_ui/src/lib/sharing.ts'
);

const checks = [];
function check(name, fn) {
    checks.push([name, fn]);
}

const AGENTS = [
    { id: 'agent-1', name: 'researcher', display_name: 'Research Assistant', scope_type: 'personal' },
    { id: 'agent-2', name: 'sam', display_name: 'Sam', scope_type: 'global' },
];

const MODELS = [
    { selection_key: 'user::ep1::gpt-4o', display_name: 'GPT-4o', deployment_name: 'gpt-4o', endpoint_id: 'ep1' },
    { selection_key: 'user::ep1::o3', display_name: 'o3', deployment_name: 'o3', endpoint_id: 'ep1' },
];

const CATALOGS = { agents: AGENTS, models: MODELS };

const PARTICIPANTS = [
    { user_id: 'u1', display_name: 'Ada Lovelace', email: 'ada@example.com' },
    { user_id: 'u2', display_name: 'Ada', email: 'ada2@example.com' },
    { user_id: 'u3', display_name: 'Grace Hopper', email: 'grace@example.com' },
];

const NOTHING_ENABLED = {
    documentSearch: false,
    webSearch: false,
    imageGeneration: false,
    deepResearch: false,
    urlAccess: false,
};

/* ------------------------------- the send rule ------------------------------- */

check('a plain remark between people does not reach the model', () => {
    // The whole point of a shared conversation: most messages are for the other humans.
    assert.equal(shouldInvokeAi('are we still meeting at four?', NOTHING_ENABLED, CATALOGS), false);
    assert.equal(resolveSendTarget('nice work on that', NOTHING_ENABLED, CATALOGS), null);
});

check('mentioning a participant does not invoke the model', () => {
    // Naming a colleague notifies them. It must not also send the message to the AI, or
    // every "@Ada could you look at this" would produce an unwanted answer.
    assert.equal(
        shouldInvokeAi('@Ada Lovelace could you look at this?', NOTHING_ENABLED, CATALOGS),
        false,
    );
});

check('tagging an agent invokes it', () => {
    const target = resolveSendTarget('@Sam what do you make of this?', NOTHING_ENABLED, CATALOGS);
    assert.equal(target.target_type, 'agent');
    assert.equal(target.display_name, 'Sam');
    assert.equal(target.source_mode, 'explicit_tag');
    // Carried so the send can select that agent for this message alone, overriding the picker.
    assert.equal(target.agent_selection_key, 'agent-2');
});

check('tagging a model invokes it and carries its selection key', () => {
    const target = resolveSendTarget('@GPT-4o summarise the thread', NOTHING_ENABLED, CATALOGS);
    assert.equal(target.target_type, 'model');
    assert.equal(target.selection_key, 'user::ep1::gpt-4o');
});

check('the longest matching name wins', () => {
    // "Research Assistant" contains no other target, but a shorter name that is a prefix of
    // a longer one must not win: tagging @Sam and @Samuel has to be distinguishable.
    const agents = [
        { id: 'a', name: 'sam', display_name: 'Sam' },
        { id: 'b', name: 'samuel', display_name: 'Samuel' },
    ];
    const target = resolveInvocationTarget('@Samuel please help', agents, []);
    assert.equal(target.display_name, 'Samuel');
});

check('an AI toggle invokes the model without any tag', () => {
    // Matches buildCollaborativeInvocationTarget: an option that only makes sense as a
    // request to the assistant is itself the request.
    for (const [key, mode] of [
        ['imageGeneration', 'image_generation'],
        ['deepResearch', 'deep_research'],
        ['urlAccess', 'url_access'],
        ['webSearch', 'web_search'],
        ['documentSearch', 'workspace'],
    ]) {
        const target = resolveSendTarget('go on then', { ...NOTHING_ENABLED, [key]: true }, CATALOGS);
        assert.ok(target, `${key} should invoke the assistant`);
        assert.equal(target.source_mode, mode);
    }
});

check('a selected agent invokes the assistant', () => {
    const target = resolveSendTarget(
        'have a look',
        { ...NOTHING_ENABLED, agentSelection: 'agent-1' },
        CATALOGS,
    );
    assert.equal(target.source_mode, 'agent');
    assert.equal(target.display_name, 'Research Assistant');
});

check('a saved prompt invokes the assistant', () => {
    const target = resolveSendTarget('...', { ...NOTHING_ENABLED, promptId: 'p1' }, CATALOGS);
    assert.equal(target.source_mode, 'prompt');
});

check('the precedence order matches the classic client', () => {
    // Several options at once must be attributed consistently. Image generation outranks an
    // agent, which outranks deep research, and so on.
    const all = {
        ...NOTHING_ENABLED,
        imageGeneration: true,
        deepResearch: true,
        webSearch: true,
        documentSearch: true,
        agentSelection: 'agent-1',
    };
    assert.equal(resolveSendTarget('x', all, CATALOGS).source_mode, 'image_generation');

    const withoutImage = { ...all, imageGeneration: false };
    assert.equal(resolveSendTarget('x', withoutImage, CATALOGS).source_mode, 'agent');

    const withoutAgent = { ...withoutImage, agentSelection: undefined };
    assert.equal(resolveSendTarget('x', withoutAgent, CATALOGS).source_mode, 'deep_research');

    const withoutDeep = { ...withoutAgent, deepResearch: false };
    assert.equal(resolveSendTarget('x', withoutDeep, CATALOGS).source_mode, 'web_search');

    const workspaceOnly = { ...withoutDeep, webSearch: false };
    assert.equal(resolveSendTarget('x', workspaceOnly, CATALOGS).source_mode, 'workspace');
});

check('an explicit tag beats an enabled toggle', () => {
    // The tag names something specific; the toggle is ambient. Reading the toggle first
    // would send an @-addressed question to whatever the picker happened to hold.
    const target = resolveSendTarget(
        '@o3 have a think',
        { ...NOTHING_ENABLED, webSearch: true, agentSelection: 'agent-1' },
        CATALOGS,
    );
    assert.equal(target.target_type, 'model');
    assert.equal(target.selection_key, 'user::ep1::o3');
});

/* ----------------------------- mention matching ------------------------------ */

check('a mention needs a boundary on both sides', () => {
    assert.equal(mentionsName('hello @Sam', 'Sam'), true);
    assert.equal(mentionsName('@Sam hello', 'Sam'), true);
    assert.equal(mentionsName('hi @Sam, welcome', 'Sam'), true);
    assert.equal(mentionsName('hi @Sam.', 'Sam'), true);
    // Without the trailing boundary, @Sam would also match @Samantha and notify the wrong
    // person.
    assert.equal(mentionsName('hi @Samantha', 'Sam'), false);
    // Without the leading boundary, an email address becomes a mention.
    assert.equal(mentionsName('write to me@Sam.example', 'Sam'), false);
});

check('the longest participant name wins when one is a prefix of another', () => {
    // Two real people, "Ada Lovelace" and "Ada". Reporting both would notify somebody who
    // was never addressed.
    const mentioned = extractMentionedParticipants('@Ada Lovelace can you check', PARTICIPANTS);
    assert.deepEqual(mentioned.map((p) => p.user_id), ['u1']);

    const shorter = extractMentionedParticipants('@Ada can you check', PARTICIPANTS);
    assert.deepEqual(shorter.map((p) => p.user_id), ['u2']);
});

check('several people can be mentioned at once', () => {
    const mentioned = extractMentionedParticipants('@Ada Lovelace and @Grace Hopper', PARTICIPANTS);
    assert.deepEqual(mentioned.map((p) => p.user_id).sort(), ['u1', 'u3']);
});

check('two people whose names overlap can both be named', () => {
    // "@Ada Lovelace" strikes out its own span, so the separate "@Ada" later in the message
    // is still found. Consuming matches must not cost a genuine second mention.
    const mentioned = extractMentionedParticipants(
        '@Ada Lovelace wrote it, and @Ada reviewed it',
        PARTICIPANTS,
    );
    assert.deepEqual(mentioned.map((p) => p.user_id).sort(), ['u1', 'u2']);
});

check('mention matching is case insensitive', () => {
    assert.deepEqual(
        extractMentionedParticipants('@ada lovelace', PARTICIPANTS).map((p) => p.user_id),
        ['u1'],
    );
});

check('a message with no mentions reports none', () => {
    assert.deepEqual(extractMentionedParticipants('nothing here', PARTICIPANTS), []);
    assert.deepEqual(extractMentionedParticipants('', PARTICIPANTS), []);
    assert.deepEqual(extractMentionedParticipants('@Ada', undefined), []);
});

check('being mentioned is read from the stored ids, not the text', () => {
    assert.equal(mentionsCurrentUser({ mentioned_user_ids: ['u1', 'u2'] }, 'u2'), true);
    assert.equal(mentionsCurrentUser({ mentioned_user_ids: ['u1'] }, 'u2'), false);
    assert.equal(mentionsCurrentUser({}, 'u2'), false);
    assert.equal(mentionsCurrentUser({ mentioned_user_ids: ['u2'] }, undefined), false);
});

/* --------------------------- typing a mention -------------------------------- */

check('an @ opens a mention only at a word boundary', () => {
    assert.deepEqual(findMentionAtCaret('@Ad', 3), { query: 'Ad', startIndex: 0, endIndex: 3 });
    assert.deepEqual(findMentionAtCaret('hi @Ad', 6), { query: 'Ad', startIndex: 3, endIndex: 6 });
    // An email address must not turn the rest of the line into a mention search.
    assert.equal(findMentionAtCaret('mail me@example', 15), null);
    assert.equal(findMentionAtCaret('no mention here', 15), null);
});

check('typing @ alone opens the menu with an empty query', () => {
    // Otherwise the menu only appears after a character, and there is no way to browse.
    assert.deepEqual(findMentionAtCaret('hello @', 7), { query: '', startIndex: 6, endIndex: 7 });
});

check('a mention ends at a newline', () => {
    assert.equal(findMentionAtCaret('@Ada\nnext line', 14), null);
});

check('a name with a space keeps matching as it is typed', () => {
    // The token runs to the caret rather than to the next space, which is what lets
    // "Ada Lovelace" be completed.
    assert.deepEqual(findMentionAtCaret('hi @Ada Love', 12), {
        query: 'Ada Love',
        startIndex: 3,
        endIndex: 12,
    });
});

check('replacing a mention leaves one space and a sane caret', () => {
    const match = findMentionAtCaret('hi @Ad', 6);
    const { value, caretIndex } = replaceMention('hi @Ad', match, '@Ada Lovelace');
    assert.equal(value, 'hi @Ada Lovelace ');
    assert.equal(caretIndex, value.length);

    // Not a second space when the text already continues with one.
    const midMatch = findMentionAtCaret('hi @Ad there', 6);
    assert.equal(replaceMention('hi @Ad there', midMatch, '@Ada').value, 'hi @Ada there');
});

/* ------------------------------ the mention menu ----------------------------- */

check('the menu offers participants, then AI targets, then invitations', () => {
    const rows = buildMentionSuggestions({
        query: '',
        participants: PARTICIPANTS,
        agents: AGENTS,
        models: MODELS,
        invitable: [{ user_id: 'u9', display_name: 'Alan Turing' }],
        canInvite: true,
        currentUserId: 'me',
        limit: 20,
    });
    const kinds = rows.map((row) => row.kind);
    assert.equal(kinds.indexOf('participant'), 0);
    assert.ok(kinds.indexOf('ai') > kinds.lastIndexOf('participant'));
    assert.ok(kinds.indexOf('invite') > kinds.lastIndexOf('ai'));
});

check('nobody already in the conversation is offered as an invitation', () => {
    // Otherwise the menu suggests adding somebody who is already there, and the server
    // rejects it.
    const rows = buildMentionSuggestions({
        query: 'Ada',
        participants: PARTICIPANTS,
        invitable: [{ user_id: 'u1', display_name: 'Ada Lovelace' }],
        canInvite: true,
        limit: 20,
    });
    assert.equal(rows.filter((row) => row.kind === 'invite').length, 0);
});

check('invitations are withheld from somebody who may not invite', () => {
    const rows = buildMentionSuggestions({
        query: '',
        participants: PARTICIPANTS,
        invitable: [{ user_id: 'u9', display_name: 'Alan Turing' }],
        canInvite: false,
        limit: 20,
    });
    assert.equal(rows.some((row) => row.kind === 'invite'), false);
});

check('the reader is never offered as somebody to invite', () => {
    const rows = buildMentionSuggestions({
        query: '',
        invitable: [{ user_id: 'me', display_name: 'Me' }],
        canInvite: true,
        currentUserId: 'me',
        limit: 20,
    });
    assert.equal(rows.length, 0);
});

/* ------------------------------ event handling ------------------------------- */

check('a timestamp without a zone is read as UTC', () => {
    // utc_now_iso does not always emit a designator, and Date.parse reads a bare timestamp
    // as local time. West of UTC that makes replayed history look like the future, so
    // nothing is ever recognised as a replay and the whole thread re-appends.
    assert.equal(parseEventTimestamp('2026-01-01T00:00:00'), Date.parse('2026-01-01T00:00:00Z'));
    assert.equal(parseEventTimestamp('2026-01-01T00:00:00Z'), Date.parse('2026-01-01T00:00:00Z'));
    assert.ok(Number.isNaN(parseEventTimestamp('')));
});

check('history replayed on attach is not treated as new', () => {
    const subscribedAt = Date.parse('2026-01-01T12:00:00Z');
    const old = { occurred_at: '2026-01-01T11:00:00Z' };
    const live = { occurred_at: '2026-01-01T12:00:05Z' };
    assert.equal(isReplayedEvent(old, subscribedAt), true);
    assert.equal(isReplayedEvent(live, subscribedAt), false);
});

check('an event in the same instant as the subscription is live', () => {
    // Clock skew is real, and a message published as the stream opened is genuinely new.
    const subscribedAt = Date.parse('2026-01-01T12:00:00Z');
    assert.equal(isReplayedEvent({ occurred_at: '2026-01-01T11:59:59.500Z' }, subscribedAt), false);
});

check('an unparseable timestamp is treated as live', () => {
    // Dropping a real message is worse than repeating one, and de-duplication catches the
    // repeat either way.
    assert.equal(isReplayedEvent({ occurred_at: 'not a date' }, Date.now()), false);
});

check('each event type reaches its own handler', () => {
    const seen = [];
    const handlers = {
        onMessageCreated: () => seen.push('created'),
        onMessageDeleted: () => seen.push('deleted'),
        onMessageMasked: () => seen.push('masked'),
        onTyping: () => seen.push('typing'),
        onMembersInvited: () => seen.push('invited'),
        onMemberRemoved: () => seen.push('removed'),
        onMemberRoleUpdated: () => seen.push('role'),
        onInviteAnswered: (_p, accepted) => seen.push(accepted ? 'accepted' : 'declined'),
        onConversationDeleted: () => seen.push('conversation-deleted'),
        onConversationUpdated: () => seen.push('conversation-updated'),
    };

    dispatchCollaborationEvent(
        { event_type: 'collaboration.message.created', payload: { message: { id: 'm1' } } },
        handlers,
    );
    dispatchCollaborationEvent(
        { event_type: 'collaboration.message.deleted', payload: { message_id: 'm1' } },
        handlers,
    );
    dispatchCollaborationEvent(
        { event_type: 'collaboration.message.masked', payload: { message: { id: 'm1' } } },
        handlers,
    );
    dispatchCollaborationEvent(
        { event_type: 'collaboration.typing.updated', payload: { user: { user_id: 'u1' } } },
        handlers,
    );
    dispatchCollaborationEvent(
        { event_type: 'collaboration.invite.declined', payload: { participant: { user_id: 'u1' } } },
        handlers,
    );
    dispatchCollaborationEvent({ event_type: 'collaboration.deleted', payload: {} }, handlers);

    assert.deepEqual(seen, [
        'created',
        'deleted',
        'masked',
        'typing',
        'declined',
        'conversation-deleted',
    ]);
});

check('membership events also refresh the conversation they carry', () => {
    // Those routes serialize the conversation after applying the change, so it is the
    // freshest membership the client will ever see and must not be dropped.
    const updates = [];
    const handlers = { onConversationUpdated: (conversation) => updates.push(conversation.id) };

    dispatchCollaborationEvent(
        {
            event_type: 'collaboration.member.removed',
            payload: { conversation: { id: 'c1' }, participant: { user_id: 'u1' } },
        },
        handlers,
    );
    dispatchCollaborationEvent(
        { event_type: 'collaboration.updated', payload: { conversation: { id: 'c2' } } },
        handlers,
    );
    // A message event must NOT go down this path: it fires on every message, and refetching
    // membership each time would be pointless traffic.
    dispatchCollaborationEvent(
        {
            event_type: 'collaboration.message.created',
            payload: { conversation: { id: 'c3' }, message: { id: 'm1' } },
        },
        handlers,
    );

    assert.deepEqual(updates, ['c1', 'c2']);
});

check('an unknown event type is ignored rather than throwing', () => {
    dispatchCollaborationEvent({ event_type: 'collaboration.future.thing', payload: {} }, {});
    dispatchCollaborationEvent({}, {});
});

/* --------------------- broadcast permissions are not mine -------------------- */

check("a broadcast conversation's permissions are dropped", () => {
    // Every publishing route serializes the conversation for the user who *caused* the
    // event and broadcasts that one dict to everybody. Applying its `can_*` verbatim means
    // a member leaving tells everyone else they can no longer post, and an owner acting
    // hands every member a "Delete for everyone" button the server then refuses.
    const broadcast = {
        id: 'c1',
        title: 'Design review',
        participants: [{ user_id: 'u1' }, { user_id: 'u2' }],
        participant_count: 2,
        message_count: 12,
        chat_type: 'personal_multi_user',
        can_post_messages: false,
        can_manage_members: true,
        can_manage_roles: true,
        can_delete_conversation: true,
        can_leave_conversation: true,
        can_accept_invite: true,
        current_user_role: 'owner',
        membership_status: 'removed',
        is_pinned: true,
        is_hidden: true,
        has_unread_assistant_response: true,
        last_unread_assistant_message_id: 'm-99',
        last_unread_assistant_at: '2026-01-01T00:00:00Z',
    };

    const facts = conversationFactsOnly(broadcast);

    for (const viewerScoped of [
        'can_post_messages',
        'can_manage_members',
        'can_manage_roles',
        'can_delete_conversation',
        'can_leave_conversation',
        'can_accept_invite',
        'current_user_role',
        'membership_status',
        'is_pinned',
        'is_hidden',
        // These three are hardcoded per-viewer by serialize_collaboration_conversation, and
        // matter most on the hot path: applying them from a message.created broadcast would
        // clear the reader's own unread marker every time anybody else writes.
        'has_unread_assistant_response',
        'last_unread_assistant_message_id',
        'last_unread_assistant_at',
    ]) {
        // Asserted present on the fixture first. `hasOwnProperty === false` passes trivially
        // for a key that was never set, so without this the test would stay green if a field
        // were dropped from VIEWER_SCOPED_FIELDS.
        assert.equal(
            Object.prototype.hasOwnProperty.call(broadcast, viewerScoped),
            true,
            `the fixture must carry ${viewerScoped} for its removal to mean anything`,
        );
        assert.equal(
            Object.prototype.hasOwnProperty.call(facts, viewerScoped),
            false,
            `${viewerScoped} belongs to whoever triggered the event and must not be applied`,
        );
    }

    // Everything that means the same to every reader survives, or the title and participant
    // list would stop updating.
    assert.equal(facts.id, 'c1');
    assert.equal(facts.title, 'Design review');
    assert.equal(facts.participant_count, 2);
    assert.equal(facts.message_count, 12);
    assert.deepEqual(facts.participants, [{ user_id: 'u1' }, { user_id: 'u2' }]);

    // The original is untouched, so a caller that legitimately holds its own copy is unharmed.
    assert.equal(broadcast.can_post_messages, false);
});

/* ---------------------------- message attribution ---------------------------- */

const sharedMessage = (id, senderId, name, extra = {}) => ({
    id,
    conversation_id: 'c1',
    role: 'user',
    content: `content of ${id}`,
    sender: { user_id: senderId, display_name: name },
    ...extra,
});

check('a personal message is attributed to nobody', () => {
    // No sender means no attribution line, which is what keeps personal conversations
    // looking exactly as they did.
    assert.equal(messageAuthorName({ id: 'm', role: 'user', content: 'hi' }, 'me'), '');
    assert.equal(isOwnMessage({ id: 'm', role: 'user', content: 'hi' }, 'me'), false);
});

check('the reader sees their own name as "You"', () => {
    assert.equal(messageAuthorName(sharedMessage('m1', 'me', 'Ada'), 'me'), 'You');
    assert.equal(messageAuthorName(sharedMessage('m2', 'u2', 'Grace'), 'me'), 'Grace');
    assert.equal(isOwnMessage(sharedMessage('m1', 'me', 'Ada'), 'me'), true);
});

check('a sender is read from metadata when it is not on the message', () => {
    const message = {
        id: 'm',
        role: 'user',
        content: 'hi',
        metadata: { sender: { user_id: 'u2', display_name: 'Grace' } },
    };
    assert.equal(messageAuthorName(message, 'me'), 'Grace');
});

check('an AI request is distinguishable from a plain message', () => {
    // Both are role 'user'. Only message_kind separates them.
    assert.equal(isAiRequest(sharedMessage('m', 'u1', 'Ada', { message_kind: 'ai_request' })), true);
    assert.equal(isAiRequest(sharedMessage('m', 'u1', 'Ada', { message_kind: 'human_message' })), false);
    assert.equal(isAiRequest({ id: 'm', role: 'user', content: 'x' }), false);
});

check('a reply resolves against the loaded thread', () => {
    const target = sharedMessage('m1', 'u2', 'Grace');
    const reply = sharedMessage('m2', 'me', 'Ada', { reply_to_message_id: 'm1' });
    const context = resolveReplyContext(reply, [target, reply], 'me');
    assert.equal(context.message_id, 'm1');
    assert.equal(context.display_name, 'Grace');
    assert.equal(context.preview, 'content of m1');
});

check('a reply to a message that is not loaded renders nothing', () => {
    // It may have been deleted, or be above the loaded part of the thread. An empty quote
    // would be worse than none.
    const reply = sharedMessage('m2', 'me', 'Ada', { reply_to_message_id: 'gone' });
    assert.equal(resolveReplyContext(reply, [reply], 'me'), null);
    assert.equal(resolveReplyContext(sharedMessage('m3', 'me', 'Ada'), [], 'me'), null);
});

check('a reply preview is trimmed rather than unbounded', () => {
    const long = { id: 'm', role: 'user', content: 'x'.repeat(500) };
    const preview = buildReplyPreview(long);
    assert.ok(preview.length <= 140);
    assert.ok(preview.endsWith('\u2026'));
});

/* ------------------------------- sharing routes ------------------------------ */

check('a personal conversation is shared through the personal conversion route', () => {
    const target = panelTargetForConversation('c1', { chat_type: 'personal_single_user' });
    assert.equal(target.kind, 'personal');
});

check('a group conversation is shared through the group conversion route', () => {
    // The group route additionally restricts invitees to that group's members, so choosing
    // the personal one here would offer people the server refuses.
    const target = panelTargetForConversation('c1', {
        chat_type: 'group-single-user',
        group_id: 'g1',
    });
    assert.equal(target.kind, 'group');
    assert.equal(target.groupId, 'g1');
});

check('an already-shared conversation takes members directly', () => {
    // Converting a second time would create another shared conversation alongside the
    // first, which is the failure this distinction exists to prevent.
    const target = panelTargetForConversation('c1', {
        conversation_kind: 'collaborative',
        chat_type: 'group_multi_user',
        group_id: 'g1',
    });
    assert.equal(target.kind, 'collaborative');
});

check('a public workspace conversation cannot be shared', () => {
    // There is no conversion route for one, so offering to share it would be an action with
    // nothing behind it.
    assert.equal(canShareConversation({ chat_type: 'public' }), false);
    assert.equal(canShareConversation({ chat_type: 'personal_single_user' }), true);
    assert.equal(canShareConversation({ chat_type: 'group_multi_user' }), true);
    assert.equal(canShareConversation(null), false);
});

/* ----------------------------------- runner ---------------------------------- */

let passed = 0;
let failed = 0;

for (const [name, fn] of checks) {
    try {
        await fn();
        console.log(`ok   ${name}`);
        passed += 1;
    } catch (error) {
        console.log(`FAIL ${name}`);
        console.log(`     ${error.message}`);
        failed += 1;
    }
}

console.log(`\n${passed}/${passed + failed} runtime checks passed`);
process.exit(failed > 0 ? 1 : 0);
