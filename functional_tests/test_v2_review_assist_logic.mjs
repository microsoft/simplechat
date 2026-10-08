// test_v2_review_assist_logic.mjs
// Version: 0.261.299
// Implemented in: 0.261.299
// Executes the real V2 Review center AI assist logic (lib/reviewSuggestions.ts and the theme and
// address helpers in lib/reviewCenter.ts). Pins that suggestions and assist answers are read
// strictly, so a malformed or mismatched answer is never shown; that a suggestion's effect is
// described the way the queue shows it; that "Approve all" leaves out suspensions, blocks, stale
// suggestions and locked violations, while an individual tick still approves a suspension or block;
// that an approval's confirmation counts the warnings it sends and the requests it creates, and that
// a suspension or block the violation already records is never requested again from the queue; that
// a refused approval reads in the reviewer's terms; that
// the save applying a suggestion carries the reviewer's notification edits and a suspension's
// restore time; and that a triage runs ten records at a time, waits out the rate limit, fails only
// an unusable chunk, and stops or cancels with the rest reported unprocessed.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const review = await import('../application/v2_ui/src/lib/reviewCenter.ts');
const ai = await import('../application/v2_ui/src/lib/reviewSuggestions.ts');

const ID = 'a'.repeat(32);
const feedbackPayload = {
    acknowledged: true, analysisNotes: 'Missed the per diem rules.', actionTaken: '', responseToUser: 'Thanks.',
    theme: 'retrieval', archive: false,
};
const warnPayload = {
    status: 'Resolved', action: 'WarnUser', notes: 'A hateful remark.', notification_title: 'Safety warning',
    notification_message: 'Please keep messages respectful.', archive: false,
};
const presented = (payload, fields = {}) => ({
    id: ID, status: 'pending', created_at: '2026-10-08T00:00:00Z', created_by: { name: 'Ada' }, model: 'gpt',
    payload, rationale: 'Because.', confidence: 'high', ...fields,
});

/* Suggestions are read strictly; anything malformed reads as none. */
const feedback = ai.parseFeedbackSuggestion(presented(feedbackPayload));
assert.equal(feedback.payload.theme, 'retrieval');
assert.equal(feedback.createdBy, 'Ada');
assert.equal(ai.parseFeedbackSuggestion(presented({ ...feedbackPayload, theme: 'weather' })), null);
assert.equal(ai.parseFeedbackSuggestion(presented(feedbackPayload, { id: 'not-an-id' })), null);
assert.equal(ai.parseFeedbackSuggestion(presented(feedbackPayload, { status: 'unsaved' })), null, 'an unsaved suggestion has no id');
assert.equal(ai.parseFeedbackSuggestion(presented(feedbackPayload, { status: 'approved' })), null);
assert.equal(ai.parseFeedbackSuggestion(null), null);
assert.equal(ai.parseFeedbackSuggestion(presented({ ...feedbackPayload, acknowledged: 'yes' })), null);
const warn = ai.parseSafetySuggestion(presented(warnPayload));
assert.equal(warn.payload.notificationTitle, 'Safety warning');
assert.equal(ai.parseSafetySuggestion(presented({ ...warnPayload, notification_title: '' })), null, 'a warning needs its text');
assert.equal(ai.parseSafetySuggestion(presented({ ...warnPayload, action: 'Escalate' })), null);
assert.equal(ai.parseSafetySuggestion(presented({ ...warnPayload, action: 'SuspendUser' })), null, 'a suspension needs a duration');
const none = ai.parseSafetySuggestion(presented({ status: 'Dismissed', action: 'None', notes: 'False positive.', archive: true,
    notification_title: 'Ignored', suspend_duration: '7d' }));
assert.equal(none.payload.notificationTitle, null);
assert.equal(none.payload.suspendDuration, null);
const cleaned = ai.parseFeedbackSuggestion(presented({ ...feedbackPayload, analysisNotes: `Bell\x07 ${'n'.repeat(3000)}` }));
assert.ok(!cleaned.payload.analysisNotes.includes('\x07'));
assert.equal([...cleaned.payload.analysisNotes].length, ai.SUGGESTION_LIMITS.analysisNotes);

/* An assist answer must match what was asked, record for record. */
const answer = {
    section: 'safety', mode: 'triage',
    results: [
        { id: 'log-1', outcome: 'suggested', suggestion: presented(warnPayload) },
        { id: 'log-2', outcome: 'content_filtered', message: 'The content filter declined this record.' },
    ],
};
const parsed = ai.parseReviewAssistResponse('safety', 'triage', answer, ['log-1', 'log-2']);
assert.deepEqual(parsed.map((result) => result.outcome), ['suggested', 'content_filtered']);
assert.equal(parsed[1].message, 'The content filter declined this record.');
assert.equal(ai.parseReviewAssistResponse('feedback', 'triage', answer, ['log-1', 'log-2']), null, 'another section');
assert.equal(ai.parseReviewAssistResponse('safety', 'analyze', answer, ['log-1', 'log-2']), null, 'another mode');
assert.equal(ai.parseReviewAssistResponse('safety', 'triage', answer, ['log-2', 'log-1']), null, 'out of order');
assert.equal(ai.parseReviewAssistResponse('safety', 'triage', answer, ['log-1']), null, 'a result nobody asked for');
assert.equal(ai.parseReviewAssistResponse('safety', 'triage', { ...answer, results: [answer.results[0], { id: 'log-2', outcome: 'exploded' }] },
    ['log-1', 'log-2']), null);
assert.equal(ai.parseReviewAssistResponse('safety', 'triage', { ...answer, results: [{ id: 'log-1', outcome: 'suggested' }, answer.results[1]] },
    ['log-1', 'log-2']), null, 'a suggestion must come with a suggested outcome');
const unsaved = { id: null, status: 'unsaved', payload: warnPayload, rationale: 'r', confidence: 'low' };
assert.ok(ai.parseReviewAssistResponse('safety', 'analyze', { section: 'safety', mode: 'analyze', results: [
    { id: 'log-1', outcome: 'suggested', suggestion: unsaved }] }, ['log-1']));
assert.equal(ai.parseReviewAssistResponse('safety', 'triage', { section: 'safety', mode: 'triage', results: [
    { id: 'log-1', outcome: 'suggested', suggestion: unsaved }] }, ['log-1']), null, 'a triage suggestion is stored');

/* Failures read as plain sentences; a rate limit waits as the server says. */
const limited = ai.describeReviewAssistFailure(429, { error: '**Admin markdown**', code: 'assistant_rate_limited', retry_after_seconds: 30 }, '12');
assert.deepEqual([limited.code, limited.retryAfterSeconds], ['assistant_rate_limited', 12]);
assert.ok(!limited.message.includes('**'), 'the rate-limit Markdown is not shown raw');
const unavailable = ai.describeReviewAssistFailure(503, { error: 'The assistant is temporarily unavailable.', code: 'assistant_unavailable', retry_after_seconds: 7 });
assert.deepEqual([unavailable.message, unavailable.retryAfterSeconds], ['The assistant is temporarily unavailable.', 7]);
assert.equal(ai.describeReviewAssistFailure(403, null).message, "AI assist isn't available to you right now.");

/* What a suggestion changes, as the queue says it. */
const violation = { id: 'log-1', status: 'New', action: 'None', notes: '', etag: 'e1', triggered_categories: [] };
const warnChanges = ai.safetySuggestionChanges(violation, warn.payload);
assert.equal(ai.suggestionSummary(warnChanges), 'Status New → Resolved · Warn user · Notes: A hateful remark. · Notification: Safety warning');
const suspend = ai.parseSafetySuggestion(presented({ ...warnPayload, action: 'SuspendUser', suspend_duration: '7d', archive: true }));
assert.match(ai.suggestionSummary(ai.safetySuggestionChanges(violation, suspend.payload)), /Suspend user for 7 days.*Archive$/);
const record = { id: 'fb-1', adminReview: { acknowledged: false, theme: null }, isArchived: false, etag: 'f1' };
assert.equal(ai.suggestionSummary(ai.feedbackSuggestionChanges(record, feedback.payload)),
    'Acknowledged No → Yes · Theme Not classified → Retrieval · Analysis notes: Missed the per diem rules. · Response to the user: Thanks.');
assert.equal(ai.suggestionSummary([]), 'Leaves the review as it is');
const warned = { ...violation, action: 'WarnUser', action_request_status: 'executed' };
assert.equal(ai.sendsWarning(violation, warn.payload), true);
assert.equal(ai.sendsWarning(warned, warn.payload), false, 'a warning already sent is not sent again');
assert.equal(ai.requestsRestriction(violation, suspend.payload), true);
assert.equal(ai.requestsRestriction({ ...violation, action: 'SuspendUser' }, suspend.payload), false);

/* The queue: Approve all leaves out restrictions, stale and locked rows. */
const entry = (id, section, rec, suggestion, state = 'ready') => ({ id, section, record: rec, suggestion, state });
const entries = [
    entry('log-1', 'safety', violation, warn),
    entry('log-2', 'safety', { ...violation, id: 'log-2' }, suspend),
    entry('log-3', 'safety', { ...violation, id: 'log-3' }, { ...warn, status: 'stale' }, 'stale'),
    entry('log-4', 'safety', { ...violation, id: 'log-4', action_request_status: 'pending' }, warn, 'locked'),
    entry('log-5', 'safety', { ...violation, id: 'log-5' }, none),
];
assert.equal(ai.suggestionRowState('safety', violation, warn), 'ready');
assert.equal(ai.suggestionRowState('safety', violation, { ...warn, status: 'stale' }), 'stale');
assert.equal(ai.suggestionRowState('safety', { ...violation, action_request_status: 'sending' }, warn), 'locked');
assert.equal(ai.suggestionRowState('feedback', { id: 'fb' }, feedback), 'ready');
assert.deepEqual(ai.approveAllIds(entries), ['log-1', 'log-5']);
const all = ai.planApproval(entries, entries.map((item) => item.id), 'all');
assert.deepEqual(all.ids, ['log-1', 'log-5']);
assert.deepEqual([all.warnings, all.restrictions, all.archives], [1, 0, 1]);
assert.deepEqual(all.skipped.map((item) => item.id), ['log-2', 'log-3', 'log-4']);
const ticked = ai.planApproval(entries, ['log-2', 'log-3'], 'selected');
assert.deepEqual(ticked.ids, ['log-2'], 'an individual tick approves a suspension');
assert.deepEqual([ticked.warnings, ticked.restrictions, ticked.archives], [0, 1, 1]);
const confirm = ai.approvalConfirmation(all, { singular: 'violation', plural: 'violations' });
assert.equal(confirm.title, 'Apply 2 suggestions?');
assert.match(confirm.description, /1 user is sent a warning straight away\./);
assert.match(confirm.description, /3 suggestions are left in the queue\./);
assert.match(ai.approvalConfirmation(ticked, { singular: 'violation', plural: 'violations' }).description,
    /1 suspension or block is requested; each applies only after another eligible reviewer approves it\./);

/* A suspension or block the violation already records is never requested again from the queue. */
const suspended = { ...violation, id: 'log-6', action: 'SuspendUser', action_request_status: 'executed', etag: 'e6' };
assert.equal(ai.repeatsRestriction(suspended, suspend.payload), true);
assert.equal(ai.repeatsRestriction(violation, suspend.payload), false);
assert.equal(ai.repeatsRestriction(suspended, warn.payload), false);
const repeatEntries = [...entries, entry('log-6', 'safety', suspended, suspend)];
assert.ok(!ai.approveAllIds(repeatEntries).includes('log-6'), 'Approve all still leaves a repeated suspension out');
const repeatPlan = ai.planApproval(repeatEntries, ['log-6'], 'selected');
assert.deepEqual([repeatPlan.ids, repeatPlan.restrictions, repeatPlan.repeats], [['log-6'], 0, 1]);
const repeatConfirm = ai.approvalConfirmation(repeatPlan, { singular: 'violation', plural: 'violations' }).description;
assert.match(repeatConfirm, /1 suspension or block is already on its violation, so nothing new is requested for it\./);
assert.doesNotMatch(repeatConfirm, /each applies only after/);
const repeatOp = ai.buildSuggestionOperation(repeatEntries[5], undefined, new Date('2026-10-01T00:00:00Z'));
assert.equal(repeatOp.changes.reissue, undefined, 'the queue never asks for a restriction again');
assert.equal(repeatOp.etag, 'e6', 'an approval is written on the version the reviewer saw');
assert.match(ai.repeatedRestrictionText(suspended, 'SuspendUser'),
    /^This suspension was approved and applied\. Approving updates the review only and requests nothing new\./);
assert.match(ai.repeatedRestrictionText({ ...suspended, action: 'BlockUser', action_request_status: 'denied' }, 'BlockUser'),
    /^This block request was denied\..*"Request this block again"\.$/);
assert.match(ai.repeatedRestrictionText({ ...suspended, action_request_status: '' }, 'SuspendUser'),
    /^This violation already records a suspension\./);

/* A refused approval or dismissal reads in the reviewer's terms. */
assert.match(ai.suggestionFailureText('record_changed', 'Fallback.'),
    /^The record changed since this suggestion was shown, so nothing was saved\..*triage the record again/);
assert.match(ai.suggestionFailureText('suggestion_stale', 'Fallback.'), /no longer fits/);
assert.match(ai.suggestionFailureText('suggestion_not_pending', 'Fallback.'), /already applied, dismissed or replaced/);
assert.equal(ai.suggestionFailureText('not_found', 'Fallback.'), 'Fallback.');
assert.equal(ai.suggestionFailureText(undefined, 'Fallback.'), 'Fallback.');

/* The save that applies a suggestion. */
const now = new Date('2026-10-01T00:00:00Z');
const warnOp = ai.buildSuggestionOperation(entries[0], { message: '  Edited message.  ' }, now);
assert.deepEqual(warnOp, {
    id: 'log-1', op: 'update', suggestion_id: ID, etag: 'e1',
    changes: { status: 'Resolved', action: 'WarnUser', notes: 'A hateful remark.', notification_title: 'Safety warning',
        notification_message: 'Edited message.' },
});
const suspendOp = ai.buildSuggestionOperation(entries[1], undefined, now);
assert.equal(suspendOp.changes.datetime_to_allow, '2026-10-08T00:00:00.000Z');
assert.equal(ai.buildSuggestionOperation(entries[4], undefined, now).changes.notification_title, undefined);
const feedbackOp = ai.buildSuggestionOperation(entry('fb-1', 'feedback', record, feedback), undefined, now);
assert.deepEqual(feedbackOp.changes, { acknowledged: true, analysisNotes: 'Missed the per diem rules.', actionTaken: '',
    responseToUser: 'Thanks.', theme: 'retrieval' });
assert.equal(feedbackOp.changes.notify_user, undefined, 'applying a suggestion never notifies the user');
assert.equal(ai.buildSuggestionOperation(entry('x', 'feedback', record, { ...feedback, id: null, status: 'unsaved' })), null);
assert.deepEqual(ai.archiveFollowUps(entries, ['log-1', 'log-2', 'log-5']), [
    { id: 'log-2', op: 'archive', archived: true },
    { id: 'log-5', op: 'archive', archived: true },
]);

/* Triage: ten at a time, waiting out the rate limit, failing only an unusable chunk. */
const ids = Array.from({ length: 23 }, (_, index) => `log-${index + 1}`);
const suggested = (chunk) => ({ ok: true, results: chunk.map((id) => ({ id, outcome: 'suggested', suggestion: warn, message: '', code: null })) });
const instant = () => Promise.resolve();
let calls = [];
let run = await ai.runTriage({
    ids,
    signal: new AbortController().signal,
    sleep: instant,
    post: async (chunk) => {
        calls.push(chunk.length);
        if (calls.length === 2) return { ok: false, failure: { status: 429, code: 'assistant_rate_limited', message: 'Wait.', retryAfterSeconds: 2 } };
        if (calls.length === 4) return { ok: false, failure: { status: 502, code: 'assistant_output_invalid', message: 'Unusable.', retryAfterSeconds: null } };
        return suggested(chunk);
    },
});
assert.deepEqual(calls, [10, 10, 10, 3]);
assert.equal(run.results.length, 23);
assert.deepEqual(run.results.slice(-3).map((result) => result.outcome), ['failed', 'failed', 'failed']);
assert.equal(run.cancelled, false);
assert.equal(run.stopped, null);
const report = ai.buildTriageReport(run, { singular: 'violation', plural: 'violations' }, (id) => `Violation ${id}`);
assert.equal(report.summary, 'AI suggested reviews for 20 of 23 violations. Nothing changes until you approve them in the AI suggestions queue.');
assert.equal(report.failures.length, 3);
assert.equal(report.tone, 'warn');
assert.deepEqual(ai.triageRetryIds(run), ['log-21', 'log-22', 'log-23'], 'records without a suggestion stay checked');

calls = [];
run = await ai.runTriage({
    ids, signal: new AbortController().signal, sleep: instant,
    post: async (chunk) => {
        calls.push(chunk.length);
        return calls.length === 2
            ? { ok: false, failure: { status: 403, code: 'review_assistant_disabled', message: 'Turned off.', retryAfterSeconds: null } }
            : suggested(chunk);
    },
});
assert.equal(run.stopped.code, 'review_assistant_disabled');
assert.equal(run.unprocessed.length, 13, 'the refused chunk and the rest are reported unprocessed');
assert.deepEqual(ai.triageRetryIds(run), ids.slice(10), 'records never sent stay checked');
assert.match(ai.buildTriageReport(run, { singular: 'violation', plural: 'violations' }, String).summary, /Stopped: Turned off\./);

const controller = new AbortController();
calls = [];
run = await ai.runTriage({
    ids, signal: controller.signal, sleep: instant,
    post: async (chunk) => {
        calls.push(chunk.length);
        controller.abort();
        return suggested(chunk);
    },
});
assert.deepEqual(calls, [10]);
assert.equal(run.cancelled, true);
assert.equal(run.unprocessed.length, 13);
assert.match(ai.buildTriageReport(run, { singular: 'violation', plural: 'violations' }, String).summary, /Cancelled; 13 violations not sent\./);

run = await ai.runTriage({
    ids: ['log-1'], signal: new AbortController().signal, sleep: instant,
    post: async () => ({ ok: false, failure: { status: 429, code: 'assistant_rate_limited', message: 'Wait.', retryAfterSeconds: 600 } }),
});
assert.equal(run.stopped.code, 'assistant_rate_limited', 'a wait longer than the limit stops the run');
const waits = [];
await ai.waitSeconds(3, new AbortController().signal, (left) => waits.push(left), instant);
assert.deepEqual(waits, [3, 2, 1]);

/* Applying a suggestion to a draft is undone group by group, keeping later edits. */
const groups = [
    { label: 'Status', keys: ['status'] },
    { label: 'Action', keys: ['action', 'title'] },
    { label: 'Notes', keys: ['notes'] },
];
const before = { status: 'New', action: 'None', title: '', notes: 'Old.' };
const after = { status: 'Resolved', action: 'WarnUser', title: 'Warning', notes: 'Old.' };
assert.deepEqual(ai.changedDraftGroups(before, after, groups).map((group) => group.label), ['Status', 'Action']);
const edited = { ...after, title: 'My own title' };
assert.equal(ai.draftKeyMarked(edited, before, after, 'status'), true);
assert.equal(ai.draftKeyMarked(edited, before, after, 'title'), false, 'an edited field is no longer marked');
assert.equal(ai.draftKeyMarked(edited, before, after, 'notes'), false, 'an unchanged field is never marked');
const undone = ai.undoDraftGroups(edited, before, after, groups);
assert.deepEqual(undone.draft, { status: 'New', action: 'WarnUser', title: 'My own title', notes: 'Old.' });
assert.deepEqual([undone.reverted, undone.skipped], [['Status'], ['Action']]);
assert.equal(ai.undoReportText(undone.reverted, undone.skipped), 'Undone: Status. Kept because you changed it since: Action.');

/* Themes ride in the address like every other filter, and the queue has an address. */
const themed = review.readFeedbackFilters(new URLSearchParams('theme=tone&days=30'));
assert.equal(themed.theme, 'tone');
assert.equal(review.feedbackFilterParams(themed).toString(), 'days=30&theme=tone');
assert.equal(review.readFeedbackFilters(new URLSearchParams('theme=weather')).theme, '');
assert.equal(review.feedbackFiltersApplied(themed), 2);
assert.equal(review.feedbackThemeLabel('latency'), 'Speed');
assert.equal(review.feedbackThemeLabel('weather'), 'Not classified');
assert.equal(review.safeReviewViewHref('safety', 'suggestions'), '/admin/review/safety/suggestions');
assert.equal(review.safeFeedbackQueueHref({ theme: 'accuracy', archive: 'all' }), '/admin/review/feedback/queue?archive=all&theme=accuracy');

console.log('PASS: Review center AI assist parsing, queue approvals, operations and triage');
