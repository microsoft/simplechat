// test_v2_m365_pending_actions_logic.mjs
// Version: 0.261.307
// Implemented in: 0.261.307
// Executes the pure rules behind the Microsoft 365 outgoing-action cards in V2 chat: which
// snapshot of an action to trust, where a card is drawn in the thread, how a card is recognised
// in a message or a stream frame, which links a card may carry, and how a notification about a
// saved action finds its way to the V2 chat page. Nothing here touches the network or React.

import assert from 'node:assert/strict';
import test from 'node:test';
import './test_support/tsResolve.mjs';

function refuseNetwork() {
    throw new Error('The pure pending-action rules never reach the network.');
}

globalThis.fetch = refuseNetwork;

// The repository resolver must be registered before extensionless TypeScript imports load.
const helpers = await import('../application/v2_ui/src/lib/m365PendingActions.ts');
const urls = await import('../application/v2_ui/src/lib/conversationUrl.ts');
const { normalizeNotification } = await import('../application/v2_ui/src/lib/notifications.ts');
const { resolveNotificationLink } = await import('../application/v2_ui/src/lib/notificationLinks.ts');

const {
    EMPTY_PENDING_ACTION_REFERENCE,
    ORPHAN_ANCHOR,
    PENDING_ACTIONS_UNAVAILABLE_MESSAGE,
    STREAMING_ANCHOR,
} = helpers;

const ORIGIN = 'https://simplechat.test';
const T1 = '2026-05-01T10:00:00Z';
const T2 = '2026-05-01T10:05:00Z';
const T3 = '2026-05-01T10:10:00Z';

/** A saved outgoing action as the server serializes it. */
function action(id = 'act-1', overrides = {}) {
    return {
        type: 'msgraph_pending_action',
        id,
        version: 'v1',
        status: 'pending',
        operation: 'send_mail',
        graph_resource_type: 'mail',
        subject: 'Quarterly numbers',
        summary: { subject: 'Quarterly numbers', body_preview: 'Hello', body_preview_truncated: false },
        can_cancel: true,
        can_send_now: true,
        viewer_is_owner: true,
        review_details_required: false,
        updated_at: T1,
        ...overrides,
    };
}

function reference(overrides = {}) {
    return { ...EMPTY_PENDING_ACTION_REFERENCE, ...overrides };
}

function anchorContext({ visible = [], byRequest = [], streaming = '' } = {}) {
    return {
        visibleMessageIds: new Set(visible),
        lastMessageByRequestId: new Map(byRequest),
        streamingUserMessageId: streaming,
    };
}

/* Links -------------------------------------------------------------------------------- */

test('a card only links to https addresses that carry no credentials', () => {
    assert.equal(helpers.safeWebLinkUrl('https://outlook.office.com/mail/id/1'), 'https://outlook.office.com/mail/id/1');
    for (const unsafe of [
        'http://outlook.office.com/mail',
        'javascript:alert(1)',
        'data:text/html,hi',
        'https://user:secret@outlook.office.com/',
        'https://user@outlook.office.com/',
        '//outlook.office.com/mail',
        'not a link',
        '',
        42,
        null,
        undefined,
    ]) {
        assert.equal(helpers.safeWebLinkUrl(unsafe), '', `${String(unsafe)} must not become a link`);
    }
});

test('a sharing decision links to its Approvals page, or to the list when it names none', () => {
    assert.equal(helpers.safeApprovalDecisionHref('req-1'), '/approvals/m365/req-1');
    assert.equal(helpers.safeApprovalDecisionHref('a b/c'), '/approvals/m365/a%20b%2Fc');
    for (const none of ['', undefined, null, 5]) {
        assert.equal(helpers.safeApprovalDecisionHref(none), '/approvals/m365');
    }
});

/* Display ------------------------------------------------------------------------------ */

test('the countdown counts down, and says so when the time is missing or has passed', () => {
    const now = Date.parse('2026-05-01T10:00:00Z');
    assert.equal(helpers.countdownText(action('a', { auto_send_at_utc: '2026-05-01T10:02:05Z' }), now), 'Scheduled in 2m 5s.');
    assert.equal(helpers.countdownText(action('a', { auto_send_at_utc: '2026-05-01T10:00:00.400Z' }), now), 'Scheduled in 0m 1s.');
    const reached = 'Scheduled time reached. Waiting for the server delivery status.';
    assert.equal(helpers.countdownText(action('a', { auto_send_at_utc: '2026-05-01T10:00:00Z' }), now), reached);
    assert.equal(helpers.countdownText(action('a', { auto_send_at_utc: '2026-05-01T09:00:00Z' }), now), reached);
    const missing = 'The scheduled time is unavailable. Refresh status to check it.';
    assert.equal(helpers.countdownText(action('a'), now), missing);
    assert.equal(helpers.countdownText(action('a', { auto_send_at_utc: 'soon' }), now), missing);
});

test('a card is headed by its subject, with the summary and a placeholder behind it', () => {
    assert.equal(helpers.actionSubject({ subject: 'Top', summary: { subject: 'Inner' } }), 'Top');
    assert.equal(helpers.actionSubject({ summary: { subject: 'Inner' } }), 'Inner');
    assert.equal(helpers.actionSubject({ subject: '', summary: {} }), '(No subject)');
    assert.equal(helpers.actionSubject({}), '(No subject)');
});

/* Which snapshot to trust -------------------------------------------------------------- */

test('merging a reference keeps what is known, trims what is new, and returns the same object when nothing changed', () => {
    const empty = EMPTY_PENDING_ACTION_REFERENCE;
    assert.equal(helpers.mergeReference(empty, null), empty);
    assert.equal(helpers.mergeReference(empty, undefined), empty);
    assert.equal(helpers.mergeReference(empty, {}), empty);
    assert.equal(helpers.mergeReference(empty, { messageId: '   ' }), empty);

    const known = helpers.mergeReference(empty, { messageId: ' m1 ', requestId: 42 });
    assert.deepEqual(known, reference({ messageId: 'm1', requestId: '42' }));

    // An empty field never erases what was known; a non-empty one replaces it.
    assert.equal(helpers.mergeReference(known, { messageId: '', userMessageId: '' }), known);
    assert.equal(helpers.mergeReference(known, { messageId: 'm1' }), known);
    assert.deepEqual(
        helpers.mergeReference(known, { messageId: 'm2', userMessageId: 'u1' }),
        reference({ messageId: 'm2', userMessageId: 'u1', requestId: '42' }),
    );
});

test('only pending, scheduled and review-required actions can still be changed', () => {
    for (const status of ['pending', 'scheduled', 'review_required']) {
        assert.equal(helpers.isActionableStatus(status), true, status);
    }
    for (const status of ['sending', 'sent', 'cancelled', 'canceled', 'failed', 'recovery_required', '', undefined]) {
        assert.equal(helpers.isActionableStatus(status), false, String(status));
    }
});

test('a stale snapshot is ignored: older, a finished action moved back to sendable, or a version already left behind', () => {
    const current = action('a', { version: 'v2', updated_at: T2 });
    const seen = new Set(['v1']);

    assert.equal(helpers.isStaleSnapshot(current, seen, action('a', { version: 'v2', updated_at: T1 }), true), true, 'older');
    assert.equal(helpers.isStaleSnapshot(current, seen, action('a', { version: 'v2', updated_at: T2 }), true), false, 'same');
    assert.equal(helpers.isStaleSnapshot(current, seen, action('a', { version: 'v3', updated_at: T3 }), true), false, 'newer');
    assert.equal(helpers.isStaleSnapshot(current, seen, action('a', { version: 'v1', updated_at: T3 }), true), true, 'revisited');
    // A version the card holds now is not "revisited" when the same version arrives again.
    assert.equal(helpers.isStaleSnapshot(current, new Set(['v2']), action('a', { version: 'v2', updated_at: T3 }), true), false);
    // Without timestamps nothing can be called older.
    assert.equal(
        helpers.isStaleSnapshot(
            action('a', { updated_at: undefined }), seen, action('a', { updated_at: undefined }), true,
        ),
        false,
    );

    const sent = action('a', { status: 'sent', version: 'v2', updated_at: T2 });
    const pendingAgain = action('a', { status: 'pending', version: 'v2', updated_at: T2 });
    assert.equal(helpers.isStaleSnapshot(sent, seen, pendingAgain, false), true, 'a frame must not un-send an action');
    assert.equal(helpers.isStaleSnapshot(sent, seen, pendingAgain, true), false, 'the server is the authority');
    const stillSent = action('a', { status: 'failed', version: 'v2', updated_at: T2 });
    assert.equal(helpers.isStaleSnapshot(sent, seen, stillSent, false), false, 'one finished state to another is allowed');
});

test('sign-in is asked for only until the reviewed version is acknowledged, and never of a non-owner', () => {
    assert.deepEqual(helpers.hydratedAuth(action('a', { viewer_is_owner: false, auth_required: true }), true, 'v1', { auth_required: true }), {
        auth: null,
        acknowledgedVersion: '',
    });

    const calendar = helpers.hydratedAuth(action('a', { auth_required: true, graph_resource_type: 'calendar' }), false, '', null);
    assert.deepEqual(calendar.auth, { auth_required: true, sources: ['calendar'], scopes: [] });
    const mail = helpers.hydratedAuth(action('a', { auth_required: true }), false, '', null);
    assert.deepEqual(mail.auth.sources, ['email']);
    const named = helpers.hydratedAuth(action('a', { auth_required: true, sources: ['email', 'calendar'], scopes: ['Mail.Send'] }), false, '', null);
    assert.deepEqual(named.auth, { auth_required: true, sources: ['email', 'calendar'], scopes: ['Mail.Send'] });

    // Acknowledged for this exact version: reconnecting once is enough.
    assert.deepEqual(
        helpers.hydratedAuth(action('a', { auth_required: true, version: 'v1' }), true, 'v1', { auth_required: true }),
        { auth: null, acknowledgedVersion: 'v1' },
    );
    assert.notEqual(helpers.hydratedAuth(action('a', { auth_required: true, version: 'v2' }), true, 'v1', null).auth, null);

    // Only the server can say sign-in is no longer needed.
    const pending = { auth_required: true, sources: ['email'] };
    assert.equal(helpers.hydratedAuth(action('a', { auth_required: false }), true, '', pending).auth, null);
    assert.equal(helpers.hydratedAuth(action('a', { auth_required: false }), false, '', pending).auth, pending);
    assert.equal(helpers.hydratedAuth(action('a'), false, '', pending).auth, pending);
});

test('the complete saved content counts as loaded only when the server said so for a full read', () => {
    assert.equal(helpers.hasLoadedFullDetails(action('a'), true), true);
    assert.equal(helpers.hasLoadedFullDetails(action('a', { summary: { body_preview: '' } }), true), true, 'an empty body is still a body');
    assert.equal(helpers.hasLoadedFullDetails(action('a'), false), false, 'a frame is not a full read');
    assert.equal(helpers.hasLoadedFullDetails(action('a', { review_details_required: undefined }), true), false);
    assert.equal(helpers.hasLoadedFullDetails(action('a', { review_details_required: true }), true), false);
    assert.equal(helpers.hasLoadedFullDetails(action('a', { summary: { body_preview: 'x', body_preview_truncated: true } }), true), false);
    assert.equal(helpers.hasLoadedFullDetails(action('a', { summary: {} }), true), false);
});

/* Polling ------------------------------------------------------------------------------ */

test('a scheduled action ticks, and is polled only once its time has come or a send is running', () => {
    const now = Date.parse('2026-05-01T10:00:00Z');
    const past = { will_auto_send: true, status: 'scheduled', auto_send_at_utc: '2026-05-01T09:59:00Z' };
    const future = { will_auto_send: true, status: 'scheduled', auto_send_at_utc: '2026-05-01T10:30:00Z' };

    assert.equal(helpers.isScheduled(action('a', past)), true);
    assert.equal(helpers.isScheduled(action('a', { ...past, auto_send_at_utc: 'soon' })), false);
    assert.equal(helpers.isScheduled(action('a', { ...past, status: 'sent' })), false);
    assert.equal(helpers.isScheduled(action('a', { ...past, will_auto_send: false })), false);

    assert.equal(helpers.needsTicking(action('a', future)), true);
    assert.equal(helpers.needsTicking(action('a', { status: 'sending' })), true);
    assert.equal(helpers.needsTicking(action('a', { ...future, status: 'sent' })), false);
    assert.equal(helpers.needsTicking(action('a', { status: 'pending' })), false);

    assert.equal(helpers.isPollDue(action('a', past), false, 0, now), true);
    assert.equal(helpers.isPollDue(action('a', past), true, 0, now), false, 'never while a request is running');
    assert.equal(helpers.isPollDue(action('a', past), false, now + 1, now), false, 'not before the next allowed time');
    assert.equal(helpers.isPollDue(action('a', future), false, 0, now), false, 'not before it is due');
    assert.equal(helpers.isPollDue(action('a', { status: 'sending' }), false, 0, now), true);
    assert.equal(helpers.isPollDue(action('a', { status: 'sending' }), true, 0, now), false);
    assert.equal(helpers.isPollDue(action('a', { ...past, auto_send_at_utc: 'soon' }), false, 0, now), false);
});

/* Reading what the server sent --------------------------------------------------------- */

test('actions are collected from a payload, and anything that is not a saved action is ignored', () => {
    assert.deepEqual(helpers.pendingActionsFromPayload(null), []);
    assert.deepEqual(helpers.pendingActionsFromPayload('text'), []);
    assert.deepEqual(helpers.pendingActionsFromPayload({}), []);

    const one = action('one');
    const two = action('two');
    const found = helpers.pendingActionsFromPayload({
        pending_action: one,
        m365_pending_actions: [two, { type: 'other', id: 'x' }, { type: 'msgraph_pending_action', id: '..' }, { type: 'msgraph_pending_action', id: '  ' }, null],
    });
    assert.deepEqual(found.map((item) => item.id), ['one', 'two']);
    assert.deepEqual(helpers.pendingActionsFromPayload({ pending_action: { id: 'no-type' } }), []);
    assert.deepEqual(helpers.pendingActionsFromPayload({ m365_pending_actions: 'nope' }), []);
});

test('a failure to build the cards is reported in the server wording, or with a fixed fallback', () => {
    assert.equal(helpers.pendingActionsErrorFromPayload(null), '');
    assert.equal(helpers.pendingActionsErrorFromPayload({}), '');
    assert.equal(helpers.pendingActionsErrorFromPayload({ m365_pending_actions_error: null }), '');
    assert.equal(helpers.pendingActionsErrorFromPayload({ m365_pending_actions_error: { message: ' Cards failed. ' } }), 'Cards failed.');
    assert.equal(helpers.pendingActionsErrorFromPayload({ m365_pending_actions_error: 'Plain text' }), 'Plain text');
    for (const bare of [{ error: 'm365_pending_actions_unavailable' }, {}, true]) {
        assert.equal(
            helpers.pendingActionsErrorFromPayload({ m365_pending_actions_error: bare }),
            PENDING_ACTIONS_UNAVAILABLE_MESSAGE,
        );
    }
    assert.match(PENDING_ACTIONS_UNAVAILABLE_MESSAGE, /Do not repeat the request/);
});

test('the ids a message says belong to it are deduplicated and must be safe to carry', () => {
    const ids = (values) => helpers.referencedActionIds({ metadata: { m365_pending_action_ids: values } });
    assert.deepEqual(ids(['a', ' a ', 'b', 'a']), ['a', 'b']);
    assert.deepEqual(ids(['a/b', 'a\\b', 'a?b', 'a#b', '.', '..', '', '  ', 5, null, {}, 'ok']), ['ok']);
    assert.deepEqual(ids('a'), []);
    assert.deepEqual(helpers.referencedActionIds({}), []);
    assert.deepEqual(helpers.referencedActionIds(null), []);
    assert.deepEqual(helpers.referencedActionIds({ metadata: {} }), []);
});

test('a message gives its cards its own id and the request that created them', () => {
    assert.deepEqual(
        helpers.referenceForMessage({ id: ' m1 ', metadata: { m365_request_id: 'r1' } }),
        reference({ messageId: 'm1', requestId: 'r1' }),
    );
    assert.deepEqual(
        helpers.referenceForMessage({ message_id: 'm2', request_id: 'r2' }),
        reference({ messageId: 'm2', requestId: 'r2' }),
    );
    assert.deepEqual(helpers.referenceForMessage({ id: 'm3', message_id: 'other', request_id: 'r3', metadata: { m365_request_id: 'r4' } }),
        reference({ messageId: 'm3', requestId: 'r4' }));
    assert.deepEqual(helpers.referenceForMessage(null), reference());
    assert.deepEqual(helpers.referenceForMessage('text'), reference());
});

test('a stream frame places a card under the user turn until the reply exists', () => {
    // A creation frame has no reply yet, so whatever message id it carries is not the card's home.
    assert.deepEqual(
        helpers.referenceForStreamFrame(
            { type: 'm365_pending_action', message_id: 'not-a-reply', user_message_id: 'u1', request_id: 'r1' },
            { userMessageId: 'pending-1' },
        ),
        reference({ userMessageId: 'u1', fallbackMessageId: 'pending-1', requestId: 'r1' }),
    );

    // A terminal frame names the saved reply, and the user turn comes from the stream.
    assert.deepEqual(
        helpers.referenceForStreamFrame(
            { done: true, message_id: 'reply-1' },
            { userMessageId: 'u2', requestId: 'r9' },
        ),
        reference({ messageId: 'reply-1', userMessageId: 'u2', fallbackMessageId: 'u2', requestId: 'r9' }),
    );

    // What the caller knows about the viewed conversation outranks the frame's own message id.
    assert.equal(helpers.referenceForStreamFrame({ done: true, message_id: 'reply-1' }, { messageId: 'mine' }).messageId, 'mine');
    // The request id is the frame's, then its metadata's, then the caller's.
    assert.equal(
        helpers.referenceForStreamFrame({ request_id: 'a', metadata: { m365_request_id: 'b' } }, { requestId: 'c' }).requestId,
        'a',
    );
    assert.equal(helpers.referenceForStreamFrame({ metadata: { m365_request_id: 'b' } }, { requestId: 'c' }).requestId, 'b');
    assert.equal(helpers.referenceForStreamFrame({}, { requestId: 'c' }).requestId, 'c');
    assert.deepEqual(helpers.referenceForStreamFrame(null), reference());
});

test('a message is re-read only when it brings new or different cards', () => {
    const card = action('a1', { version: 'v1', updated_at: T1, status: 'pending' });
    const message = { id: 'm1', metadata: { m365_request_id: 'r1', m365_pending_action_ids: ['b'] }, m365_pending_actions: [card] };

    assert.equal(helpers.messageTrackKey(message), `m1|r1|a1@v1@${T1}@pending|b`);
    assert.equal(helpers.messageTrackKey({ ...message }), helpers.messageTrackKey(message), 'stable for the same content');

    assert.equal(helpers.messageTrackKey({ id: 'm2' }), '', 'nothing to track');
    assert.equal(helpers.messageTrackKey({ role: 'assistant', m365_pending_actions: [card] }), '', 'no id to attribute it to');
    assert.equal(helpers.messageTrackKey({ id: 'm3', m365_pending_actions: [{ id: 'x' }], metadata: {} }), '', 'not a saved action');
    assert.equal(helpers.messageTrackKey(null), '');
    assert.equal(helpers.messageTrackKey({ message_id: 'm4', metadata: { m365_pending_action_ids: ['z'] } }), 'm4|||z');

    for (const changed of [
        { version: 'v2' },
        { updated_at: T2 },
        { status: 'sent' },
    ]) {
        assert.notEqual(
            helpers.messageTrackKey({ ...message, m365_pending_actions: [{ ...card, ...changed }] }),
            helpers.messageTrackKey(message),
            JSON.stringify(changed),
        );
    }
});

/* Placement ---------------------------------------------------------------------------- */

test('a card is drawn under the reply that saved it when that reply is on screen', () => {
    const context = anchorContext({ visible: ['reply', 'u1'], streaming: 'u1' });
    assert.equal(
        helpers.resolveAnchor(reference({ messageId: 'reply', userMessageId: 'u1' }), {}, context),
        'reply',
        'a visible reply wins even while a later turn streams',
    );
});

test('a card saved by the reply that is still streaming goes to the streaming slot', () => {
    const context = anchorContext({ visible: ['u1'], streaming: 'u1' });
    assert.equal(helpers.resolveAnchor(reference({ userMessageId: 'u1' }), {}, context), STREAMING_ANCHOR);
    assert.equal(helpers.resolveAnchor(reference({ fallbackMessageId: 'u1' }), {}, context), STREAMING_ANCHOR);
    assert.equal(
        helpers.resolveAnchor(reference({ messageId: 'gone', userMessageId: 'u1' }), {}, context),
        STREAMING_ANCHOR,
        'a reply that is not on screen is not an anchor',
    );
    assert.equal(
        helpers.resolveAnchor(reference({ userMessageId: 'u0' }), {}, context),
        ORPHAN_ANCHOR,
        'a card for another turn is not drawn under the one that streams',
    );
});

test('without a visible reply the card falls back to its user turn, then its request, then the conversation section', () => {
    assert.equal(helpers.resolveAnchor(reference({ userMessageId: 'u1' }), {}, anchorContext({ visible: ['u1'] })), 'u1');
    assert.equal(helpers.resolveAnchor(reference({ userMessageId: 'x', fallbackMessageId: 'u2' }), {}, anchorContext({ visible: ['u2'] })), 'u2');

    const byRequest = anchorContext({ visible: ['m9'], byRequest: [['r1', 'm9'], ['r2', 'hidden']] });
    assert.equal(helpers.resolveAnchor(reference({ requestId: 'r1' }), {}, byRequest), 'm9');
    assert.equal(helpers.resolveAnchor(reference(), { request_id: 'r1' }, byRequest), 'm9', 'the action itself can name the request');
    assert.equal(helpers.resolveAnchor(reference({ requestId: 'r2' }), {}, byRequest), ORPHAN_ANCHOR, 'a hidden message is no anchor');
    assert.equal(helpers.resolveAnchor(reference({ requestId: 'unknown' }), {}, byRequest), ORPHAN_ANCHOR);

    assert.equal(helpers.resolveAnchor(reference(), {}, anchorContext({ visible: ['m1'] })), ORPHAN_ANCHOR);
    // An empty id must never match an empty member of the visible set.
    assert.equal(helpers.resolveAnchor(reference(), {}, anchorContext({ visible: [''] })), ORPHAN_ANCHOR);
    assert.equal(ORPHAN_ANCHOR, '');
    assert.notEqual(STREAMING_ANCHOR, ORPHAN_ANCHOR);
});

test('messages are indexed by request, and the newest user turn is the one that streams', () => {
    const index = helpers.lastMessageByRequestId([
        { id: 'a', metadata: { m365_request_id: 'r1' } },
        { id: 'b', metadata: { m365_request_id: 'r1' } },
        { id: 'c' },
        { id: '', metadata: { m365_request_id: 'r2' } },
        { id: 'd', metadata: { m365_request_id: '  ' } },
    ]);
    assert.deepEqual([...index], [['r1', 'b']]);

    assert.equal(helpers.latestUserMessageId([
        { id: 'u1', role: 'user' }, { id: 'a1', role: 'assistant' }, { id: 'u2', role: 'user' }, { id: 'a2', role: 'assistant' },
    ]), 'u2');
    assert.equal(helpers.latestUserMessageId([{ id: 'a1', role: 'assistant' }]), '');
    assert.equal(helpers.latestUserMessageId([{ id: ' ', role: 'user' }, { id: 'u1', role: 'user' }, { role: 'user' }]), 'u1');
    assert.equal(helpers.latestUserMessageId([]), '');
});

/* The URL vocabulary -------------------------------------------------------------------- */

test('an action id is carried only when it is safe in a path, a query and a selector', () => {
    assert.equal(urls.normalizePendingActionId('act-1'), 'act-1');
    assert.equal(urls.normalizePendingActionId('  act-1  '), 'act-1');
    assert.equal(urls.normalizePendingActionId('x'.repeat(200)), 'x'.repeat(200));
    for (const unsafe of [
        'a/b', 'a\\b', 'a?b', 'a#b', '.', '..', '', '   ', 'x'.repeat(201), 'a\nb', 'a\u0000b', 'a\u007fb',
        5, null, undefined, {}, [],
    ]) {
        assert.equal(urls.normalizePendingActionId(unsafe), '', `${JSON.stringify(unsafe)} must be refused`);
    }
    assert.equal(helpers.normalizePendingActionId, urls.normalizePendingActionId, 'one rule for links and cards');
});

test('the one-shot focus parameter is read only when it names a safe id', () => {
    assert.equal(urls.M365_PENDING_ACTION_PARAM, 'm365_pending_action');
    assert.equal(urls.readPendingActionFocus(new URLSearchParams('m365_pending_action=act-1')), 'act-1');
    assert.equal(urls.readPendingActionFocus(new URLSearchParams('m365_pending_action=%20act-1%20')), 'act-1');
    for (const query of ['', 'conversationId=c', 'm365_pending_action=', 'm365_pending_action=a%2Fb', 'm365_pending_action=..']) {
        assert.equal(urls.readPendingActionFocus(new URLSearchParams(query)), null, query);
    }
});

test('a link to a saved action opens its conversation, and still opens it when the id cannot be carried', () => {
    assert.equal(urls.chatHrefForPendingAction('conv-1', 'act-1'), '/chat?conversationId=conv-1&m365_pending_action=act-1');
    assert.equal(
        urls.chatHrefForPendingAction('conv 1&x', 'act 1'),
        '/chat?conversationId=conv%201%26x&m365_pending_action=act%201',
        'both ids are encoded',
    );
    assert.equal(urls.chatHrefForPendingAction('conv-1', 'a/b'), urls.chatHrefForConversation('conv-1'));
    assert.equal(urls.chatHrefForPendingAction('conv-1', ''), '/chat?conversationId=conv-1');
});

test('the address sync strips the one-shot focus parameter and keeps the conversation', () => {
    const arrived = new URLSearchParams('conversationId=conv-1&m365_pending_action=act-1');
    const synced = urls.syncedConversationParams(arrived, 'conv-1');
    assert.ok(synced, 'the parameter is a difference that must be written back');
    assert.equal(synced.has('m365_pending_action'), false);
    assert.equal(synced.get('conversationId'), 'conv-1');

    // Other parameters survive, and the same address does not rewrite itself again.
    const other = urls.syncedConversationParams(new URLSearchParams('conversationId=conv-1&m365_pending_action=act-1&keep=1'), 'conv-1');
    assert.equal(other.get('keep'), '1');
    assert.equal(urls.syncedConversationParams(synced, 'conv-1'), null);
    assert.equal(urls.syncedConversationParams(new URLSearchParams('conversationId=conv-1'), 'conv-1'), null);

    // Even a parameter that was refused as unsafe is removed rather than left to linger.
    const refused = urls.syncedConversationParams(new URLSearchParams('conversationId=conv-1&m365_pending_action=a%2Fb'), 'conv-1');
    assert.equal(refused.has('m365_pending_action'), false);
    // A conversation change still rewrites the parameter it owns.
    assert.equal(urls.syncedConversationParams(new URLSearchParams('conversationId=conv-1'), 'conv-2').get('conversationId'), 'conv-2');
});

/* Where a notification about a saved action goes ---------------------------------------- */

function notice(overrides = {}) {
    return normalizeNotification({
        id: 'n-1',
        notification_type: 'system_announcement',
        title: 'A Microsoft 365 action needs your attention',
        message: 'An email is waiting to be sent.',
        created_at: '2026-05-01T09:05:00Z',
        is_read: false,
        link_url: '',
        link_context: {},
        metadata: {},
        type_config: { icon: 'bi-envelope', color: 'info' },
        ...overrides,
    });
}

const resolve = (overrides) => resolveNotificationLink(notice(overrides), ORIGIN);
const conversation = (conversationId, pendingActionId) => ({
    target: pendingActionId
        ? { kind: 'conversation', conversationId, pendingActionId }
        : { kind: 'conversation', conversationId },
    error: null,
});

test('a notice about a saved action opens the V2 conversation and names the action, whichever chat address it carries', () => {
    const metadata = { m365_pending_action_id: 'act-1', conversation_id: 'conv-1' };
    for (const link of [
        '/chats?conversationId=conv-1&m365_pending_action=act-1',
        '/chats?conversation_id=conv-1&m365_pending_action=act-1',
        '/chat?conversationId=conv-1&m365_pending_action=act-1',
        '/v2/chat?conversationId=conv-1&m365_pending_action=act-1',
        '/chats/?conversationId=conv-1&m365_pending_action=act-1',
        `${ORIGIN}/chats?conversationId=conv-1&m365_pending_action=act-1`,
    ]) {
        assert.deepEqual(resolve({ link_url: link, metadata }), conversation('conv-1', 'act-1'), link);
    }
});

test('a notice about a saved action never becomes a classic page', () => {
    const resolved = resolve({
        link_url: '/chats?conversationId=conv-1&m365_pending_action=act-1',
        metadata: { m365_pending_action_id: 'act-1' },
    });
    assert.equal(resolved.error, null);
    assert.equal(resolved.target.kind, 'conversation');
    assert.equal('href' in resolved.target, false, 'no classic address is built for it');
});

test('an action id a link must not carry opens the conversation without a focus request', () => {
    for (const bad of ['act%2F1', 'act%5C1', 'act%3F1', 'act%231', '..', '.', '', '%00', 'x'.repeat(201)]) {
        assert.deepEqual(
            resolve({ link_url: `/chats?conversationId=conv-1&m365_pending_action=${bad}`, metadata: { m365_pending_action_id: 'act-1' } }),
            conversation('conv-1'),
            bad,
        );
    }
});

test('the conversation id still has to be one a path can carry', () => {
    const invalid = 'This notification has an invalid link. Open the destination directly.';
    for (const bad of ['conv%2F1', 'conv%5C1', '..']) {
        assert.deepEqual(
            resolve({ link_url: `/chats?conversationId=${bad}&m365_pending_action=act-1`, metadata: { m365_pending_action_id: 'act-1' } }),
            { target: null, error: invalid },
            bad,
        );
    }
    // A chat link with no conversation opens the chat page itself, never an action on its own.
    assert.deepEqual(resolve({ link_url: '/chats?m365_pending_action=act-1' }), { target: { kind: 'route', path: '/chat' }, error: null });
});

test('a notice about a saved action without a conversation opens the V2 Approvals page', () => {
    assert.deepEqual(resolve({ link_url: '/approvals' }), { target: { kind: 'route', path: '/approvals' }, error: null });
    assert.deepEqual(
        resolve({ link_url: '/approvals?status=pending#m365' }),
        { target: { kind: 'route', path: '/approvals?status=pending#m365' }, error: null },
    );
});

test('a link to another site is never followed, whatever it says about an action', () => {
    const resolved = resolve({
        link_url: 'https://elsewhere.test/chats?conversationId=conv-1&m365_pending_action=act-1',
        metadata: { m365_pending_action_id: 'act-1' },
    });
    assert.equal(resolved.target, null);
    assert.match(resolved.error, /another site/);
});
