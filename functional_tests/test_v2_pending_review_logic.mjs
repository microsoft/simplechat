// test_v2_pending_review_logic.mjs
// Version: 0.261.325
// Implemented in: 0.261.325
// Real editor proposal/undo boundaries and owner-authorized API requests; all network mocked.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const {
    applyPendingReviewValues, canEditPendingAction, fetchPendingReview, fetchPendingReviewHistory,
    pendingReviewView, savePendingReview, pendingActionCanLink, pendingActionLinkLabel, pendingReviewHistoryFromWire, pendingReviewDateTimeInput, pendingReviewApplySuggestion,
} = await import('../application/v2_ui/src/lib/pendingActionReview.ts');
const { createPendingReviewStore, pendingReviewDirty } = await import('../application/v2_ui/src/stores/pendingActionReviewStore.ts');
const { editorAssistUndoPlan } = await import('../application/v2_ui/src/lib/editorAssist.ts');

const draft = {
    subject: 'Quarterly numbers', body: '<p>Hi Ann.</p>', content_type: 'HTML',
    to_recipients: ['ann@example.com'], cc_recipients: [], bcc_recipients: [],
};
const action = { type: 'msgraph_pending_action', id: 'act-one', version: 'v1', status: 'pending',
    action_mode: 'manual', can_edit: true, viewer_is_owner: true };
assert.equal(canEditPendingAction(action), true);
assert.equal(canEditPendingAction({ ...action, status: 'editing', can_edit: true }), true);
assert.equal(canEditPendingAction({ ...action, status: 'editing', can_edit: false }), false);
assert.equal(pendingActionLinkLabel(action), 'Open draft in Outlook');
assert.equal(pendingActionCanLink({ ...action, status: 'sent', web_link: 'https://outlook.office.com/draft' }), false);
assert.equal(pendingActionCanLink({ ...action, status: 'sent', web_link_kind: 'sent', link_pending: true }), false);
assert.equal(pendingActionCanLink({ ...action, status: 'sent', web_link_kind: 'sent', link_pending: false }), true);
assert.equal(pendingActionCanLink({ ...action, status: 'sent', web_link_kind: 'sent', link_pending: false, link_status: 'unavailable',
    web_link: 'https://outlook.office.com/stale-draft' }), false);
assert.equal(pendingActionLinkLabel({ ...action, status: 'sent', web_link_kind: 'retained_draft' }), 'Open retained draft in Outlook');
assert.equal(pendingActionLinkLabel({ ...action, graph_resource_type: 'calendar' }), 'Open calendar event in Outlook');
assert.equal(pendingReviewDateTimeInput('2026-10-15T10:00:00.1234567'), '2026-10-15T10:00:00.123');
assert.equal(pendingReviewDateTimeInput('2026-10-15T10:00'), '2026-10-15T10:00');
assert.equal(pendingReviewDateTimeInput('2026-10-15T10:00:00.1234567+01:00'), '2026-10-15T10:00:00.1234567+01:00');
assert.equal(pendingReviewDateTimeInput('2026-10-15T14:00:00Z', 'America/New_York'), '2026-10-15T10:00:00');
assert.equal(pendingReviewDateTimeInput('2026-10-15T16:00:00.1234567+02:00', 'America/New_York'), '2026-10-15T10:00:00.123');
assert.equal(pendingReviewDateTimeInput('2026-10-15T14:00:00Z', 'Europe/London'), '2026-10-15T15:00:00');
assert.equal(pendingReviewDateTimeInput('2026-01-01T00:30:00Z', 'America/New_York'), '2025-12-31T19:30:00');
assert.equal(pendingReviewDateTimeInput('2026-10-15T18:30:00Z', 'Asia/Kolkata'), '2026-10-16T00:00:00');
assert.equal(pendingReviewDateTimeInput('2026-10-15T14:00:00Z', 'Eastern Standard Time',
    { 'Eastern Standard Time': 'America/New_York' }), '2026-10-15T10:00:00');
assert.equal(pendingReviewDateTimeInput('2026-10-15T14:00:00Z', 'Invalid/Zone'), '2026-10-15T14:00:00Z');
assert.equal(pendingReviewDateTimeInput('2026-10-15T10:00:00.1234567', 'America/New_York'), '2026-10-15T10:00:00.123');
assert.equal(pendingReviewDateTimeInput('2026-11-01T05:30:00Z', 'America/New_York'), '2026-11-01T01:30:00');
assert.equal(pendingReviewDateTimeInput('2026-11-01T06:30:00Z', 'America/New_York'), '2026-11-01T01:30:00');
for (const changes of [{ viewer_is_owner: false }, { can_edit: false }, { action_mode: 'delayed' },
    { status: 'sending' }, { status: 'sent' }, { status: 'cancelled' }]) {
    assert.equal(canEditPendingAction({ ...action, ...changes }), false);
}

const view = pendingReviewView(draft, false);
assert.deepEqual(view.fields.map((field) => field.path),
    ['/subject', '/to_recipients', '/cc_recipients', '/bcc_recipients', '/body', '/content_type']);
const edited = applyPendingReviewValues(draft, {
    ...view.values, '/subject': 'Updated', '/body': '<p>Changed</p>',
    '/to_recipients': ['new@example.com'], '/owner': 'attacker', '/action_mode': 'immediate',
}, false);
assert.equal(edited.subject, 'Updated');
assert.deepEqual(edited.to_recipients, ['new@example.com']);
assert.equal(edited.owner, undefined);
assert.equal(edited.action_mode, undefined);
assert.equal(edited.content_type, 'HTML');
assert.equal(draft.subject, 'Quarterly numbers');
assert.equal(applyPendingReviewValues(draft, { ...view.values, '/to_recipients': 42 }, false).to_recipients, draft.to_recipients);
const replay = pendingReviewApplySuggestion(draft,
    { ...draft, subject: 'Persisted suggestion', body: 'Suggested body', owner: 'attacker' },
    { ...draft, body: 'Newer local body' }, false);
assert.equal(replay.draft.subject, 'Persisted suggestion');
assert.equal(replay.draft.body, 'Newer local body');
assert.equal(replay.draft.owner, undefined);
assert.deepEqual(replay.applied, ['/subject']);
assert.deepEqual(replay.skipped, ['/body']);
const repeated = pendingReviewApplySuggestion(draft,
    { ...draft, subject: 'Persisted suggestion', body: 'Suggested body' }, replay.draft, false);
assert.deepEqual(repeated.applied, []);
assert.equal(repeated.draft.body, 'Newer local body');
const invalidReplay = pendingReviewApplySuggestion(draft,
    { ...draft, to_recipients: 42, subject: 'x'.repeat(501) }, draft, false);
assert.deepEqual(invalidReplay.applied, []);
assert.deepEqual(invalidReplay.draft, draft);

const calendar = {
    subject: 'Planning', body: 'Agenda', content_type: 'Text', attendee_recipients: ['ann@example.com'],
    start_datetime: '2026-10-15T10:00:00', end_datetime: '2026-10-15T11:00:00',
    timezone: 'America/New_York', location: 'Room 1', teams_meeting_requested: true,
};
assert.ok(pendingReviewView(calendar, true).fields.some((field) => field.path === '/timezone'));
assert.ok(!pendingReviewView(calendar, true).fields.some((field) => field.path === '/to_recipients'));
const calendarReplay = pendingReviewApplySuggestion(calendar,
    { ...calendar, location: 'Suggested room', teams_meeting_requested: false },
    { ...calendar, location: 'Newer room' }, true);
assert.equal(calendarReplay.draft.location, 'Newer room');
assert.equal(calendarReplay.draft.teams_meeting_requested, false);
assert.deepEqual(calendarReplay.skipped, ['/location']);
const undo = editorAssistUndoPlan(
    [{ path: '/subject', before: 'Quarterly numbers', after: 'Updated' },
        { path: '/body', before: draft.body, after: edited.body }],
    view.values, { ...pendingReviewView(edited, false).values, '/body': 'Later direct edit' });
assert.equal(undo.patch['/subject'], 'Quarterly numbers');
assert.ok(undo.skipped.includes('/body'));

const store = createPendingReviewStore();
store.getState().load({ pending_action: action, draft, version: 'v1', assist_enabled: true, history: [] });
store.getState().edit(edited, 'ai');
assert.equal(pendingReviewDirty(store.getState().review.draft, store.getState().draft), true);
assert.equal(store.getState().attribution, 'ai');
store.getState().acceptAssist({ ...action, version: 'v2' }, 'v2', 'ai-1');
assert.equal(store.getState().review.version, 'v2', 'assist history commits advance the reviewed ETag');
assert.equal(store.getState().draft.subject, 'Updated', 'new ETag must not discard the unsaved proposal');
store.getState().appendHistory([{ id: 'h1', kind: 'assist', instruction: 'Improve' }], 'next');
store.getState().appendHistory([{ id: 'h1', kind: 'assist', instruction: 'Improve' }, { id: 'h2', kind: 'revision' }], '');
assert.equal(store.getState().history.length, 2);
store.getState().clear();
assert.equal(store.getState().draft, null);
assert.equal(store.getState().history.length, 0);

const requests = [];
const historyWire = pendingReviewHistoryFromWire({ history: { items: [
    { id: 'h2', kind: 'revision', origin: 'ai', fields: edited, from_fields: draft, saved: true },
    { id: 'h1', kind: 'assist', candidate_fields: edited, from_fields: draft, submission_id: 'sub-1' },
], next_cursor: 'h1' } });
assert.deepEqual(historyWire.history.map((item) => item.id), ['h1', 'h2']);
assert.equal(historyWire.history[1].before.subject, draft.subject);
assert.equal(historyWire.history[0].after.subject, edited.subject);
globalThis.fetch = async (url, init = {}) => {
    requests.push({ url, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : null, headers: init.headers });
    const data = String(url).endsWith('/api/m365/preferences') ? { csrf_token: 'c'.repeat(40) }
        : { success: true, pending_action: action, fields: draft, expected_version: 'v1',
            history: { items: [], next_cursor: '' } };
    return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } });
};
await fetchPendingReview('act-one');
await savePendingReview('act-one', 'v1', edited, 'ai');
const loadedHistory = await fetchPendingReviewHistory('act-one', 'opaque token');
assert.equal(loadedHistory.version, 'v1');
assert.equal(loadedHistory.pending_action.id, 'act-one');
assert.equal(loadedHistory.draft.body, draft.body);
const update = requests.find((request) => request.method === 'PATCH');
assert.deepEqual(update.body, { expected_version: 'v1', fields: edited, origin: 'ai' });
assert.equal(update.headers['X-M365-CSRF-Token'], 'c'.repeat(40));
assert.ok(requests.at(-1).url.includes('cursor=opaque+token'));
assert.ok(requests.every((request) => !/send-now|approve|\/cancel/.test(request.url)), 'review never sends');
console.log('Pending review owner, fields, proposal/undo, history and CSRF contracts passed.');
