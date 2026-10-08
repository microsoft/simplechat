// test_v2_review_center_logic.mjs
// Version: 0.261.298
// Implemented in: 0.261.298
// Executes the real V2 Review center modules (lib/reviewAccess.ts, lib/reviewCenter.ts and
// lib/reviewSelection.ts). Pins that section access mirrors the server's decorators -- the
// reviewer role named by Admin Settings, or Admin, and the area turned on -- and that the
// Safety remediation approvals category goes to the roles that raise or decide those requests;
// that filters read from an address are validated and written back without defaults, so a
// dashboard link and the list agree; that a violation reads its remediation state accurately,
// legacy Escalate included, and a warning being sent locks it like a pending request; that the
// remediation editor's standard notification mirrors the server's; that suspension presets
// count from the moment chosen; that bulk results report each failure; and that checked rows
// follow click and Shift+click, prune on reload, and "every matching" belongs to its filters.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const access = await import('../application/v2_ui/src/lib/reviewAccess.ts');
const review = await import('../application/v2_ui/src/lib/reviewCenter.ts');
const selection = await import('../application/v2_ui/src/lib/reviewSelection.ts');

/* Access mirrors feedback_admin_required / safety_violation_admin_required. */
function input(roles, features = {}, settings = {}) {
    return access.reviewAccessInput({ user: { roles }, features, settings });
}
const allOn = { enable_user_feedback: true, enable_content_safety: true };
assert.deepEqual(access.reviewSections(input(['Admin'], allOn)), ['feedback', 'safety']);
assert.equal(access.defaultReviewPath(input(['Admin'], allOn)), '/admin/review/feedback');
assert.deepEqual(access.reviewSections(input(['User'], allOn)), []);
assert.equal(access.defaultReviewPath(input(['User'], allOn)), null);
// A required reviewer role replaces Admin for that area only.
const required = { require_member_of_feedback_admin: true, require_member_of_safety_violation_admin: true };
assert.deepEqual(access.reviewSections(input(['Admin'], allOn, required)), []);
assert.deepEqual(access.reviewSections(input(['FeedbackAdmin'], allOn, required)), ['feedback']);
assert.deepEqual(access.reviewSections(input(['SafetyViolationAdmin'], allOn, required)), ['safety']);
assert.deepEqual(access.reviewSections(input(['FeedbackAdmin'], allOn)), [], 'FeedbackAdmin alone without the requirement');
// The area must be on; content screening alone turns safety review on.
assert.deepEqual(access.reviewSections(input(['Admin'], {})), []);
assert.deepEqual(access.reviewSections(input(['Admin'], { enable_content_screening: true })), ['safety']);
assert.deepEqual(access.reviewSections(input(['Admin'], { enable_user_feedback: true })), ['feedback']);
assert.equal(access.defaultReviewPath(input(['SafetyViolationAdmin'], allOn, required)), '/admin/review/safety');
// A malformed bootstrap grants nothing.
assert.deepEqual(access.reviewSections(access.reviewAccessInput(null)), []);
assert.deepEqual(access.reviewSections(access.reviewAccessInput({ user: { roles: 'Admin' }, features: allOn })), []);
for (const role of ['Admin', 'ControlCenterAdmin', 'SafetyViolationAdmin']) {
    assert.equal(access.canSeeSafetyRemediationApprovals([role]), true, role);
}
assert.equal(access.canSeeSafetyRemediationApprovals(['User', 'FeedbackAdmin']), false);

/* Filters round-trip through the address, and unknown values are dropped. */
const safetyParams = new URLSearchParams('status=open&action=Escalate&archive=all&search=  hate  &user_id=u1&category=Hate&severity=6&request=pending&warning=pending&restricted=1&date=2026-10-01&days=30&bogus=1');
const safety = review.readSafetyFilters(safetyParams);
assert.equal(safety.status, 'open');
assert.equal(safety.action, 'Escalate');
assert.equal(review.safetyFilterParams(safety).toString(),
    'status=open&action=Escalate&archive=all&search=hate&user_id=u1&category=Hate&severity=6&request=pending&warning=pending&restricted=1&date=2026-10-01&days=30');
const rejected = review.readSafetyFilters(new URLSearchParams('status=Closed&action=Nuke&archive=x&severity=high&request=sending&warning=maybe&date=10/01&days=12'));
assert.deepEqual(rejected, review.DEFAULT_SAFETY_FILTERS);
assert.equal(review.safetyFilterParams(review.DEFAULT_SAFETY_FILTERS).toString(), '');
const feedback = review.readFeedbackFilters(new URLSearchParams('type=Negative&ack=false&archive=archived&days=7'));
assert.equal(review.feedbackFilterParams(feedback).toString(), 'type=Negative&ack=false&archive=archived&days=7');
assert.deepEqual(review.readFeedbackFilters(new URLSearchParams('type=Angry&ack=maybe')), review.DEFAULT_FEEDBACK_FILTERS);
assert.equal(review.feedbackFiltersApplied(feedback), 4);
const paging = review.readReviewPaging(new URLSearchParams('page=3&size=50&selected=fb-1'));
assert.deepEqual(paging, { page: 3, pageSize: 50, selected: 'fb-1' });
assert.deepEqual(review.readReviewPaging(new URLSearchParams('page=-2&size=7')), { page: 1, pageSize: 20, selected: '' });
assert.equal(review.readReviewWindow('90'), '90');
assert.equal(review.readReviewWindow('45'), '30');

/* Addresses: dashboard links open the workbench filtered, record ids are encoded. */
assert.equal(review.safeViolationsHref({ status: 'open' }), '/admin/review/safety/violations?status=open');
assert.equal(review.safeFeedbackQueueHref({ ack: 'false' }), '/admin/review/feedback/queue?ack=false');
assert.equal(review.safeReviewViewHref('safety', 'unchecked'), '/admin/review/safety/unchecked');
assert.equal(review.safeReviewViewHref('feedback', 'dashboard'), '/admin/review/feedback');
assert.equal(review.safeReviewRecordHref('safety', 'a/b c', new URLSearchParams('selected=a/b c')),
    '/admin/review/safety/violations/a%2Fb%20c?selected=a%2Fb+c');
assert.equal(review.safeApprovalRequestHref('approval 1', 'user-1'), '/approvals/all/approval%201?group_id=user-1');

/* Remediation state, as a row and the editor read it. */
const record = (fields) => ({ id: 'log-1', ...fields });
assert.deepEqual(review.ACTIONS, ['None', 'WarnUser', 'SuspendUser', 'BlockUser']);
assert.deepEqual(review.selectableSafetyActions(record({ action: 'Escalate' })), ['None', 'WarnUser', 'SuspendUser', 'BlockUser', 'Escalate']);
assert.deepEqual(review.selectableSafetyActions(record({ action: 'WarnUser' })), review.ACTIONS);
assert.equal(review.safetyActionLabel('Escalate'), 'Escalated (legacy)');
const pending = record({ action: 'SuspendUser', action_request_status: 'pending', action_requested_at: '2026-10-01T00:00:00Z' });
assert.equal(review.isRemediationPending(pending), true);
assert.equal(review.isSafetyRecordLocked(pending), true);
assert.equal(review.safetyActionBadge(pending).detail, 'Pending approval');
assert.match(review.remediationStatusText(pending), /^The suspension is waiting for another eligible reviewer to approve it\./);
const sending = record({ action: 'WarnUser', action_request_status: 'sending' });
assert.equal(review.isWarningSending(sending), true);
assert.equal(review.isSafetyRecordLocked(sending), true);
assert.equal(review.isRemediationPending(sending), false);
assert.equal(review.safetyActionBadge(sending).detail, 'Sending');
const warned = record({ action: 'WarnUser', action_request_status: 'executed', warning_acknowledgment_status: 'pending' });
assert.equal(review.isExecutedWarning(warned), true);
assert.equal(review.safetyActionBadge(warned).detail, 'Not yet acknowledged');
assert.equal(review.warningAcknowledgmentText(warned), 'Warning sent. Not yet acknowledged by the user.');
const acknowledged = { ...warned, warning_acknowledgment_status: 'acknowledged', warning_acknowledged_at: '2026-10-02T00:00:00Z' };
assert.match(review.warningAcknowledgmentText(acknowledged), /^Warning acknowledged /);
const denied = record({ action: 'BlockUser', action_request_status: 'denied' });
assert.equal(review.isSafetyRecordLocked(denied), false);
assert.match(review.remediationStatusText(denied), /block request was denied .* It can be requested again\./);
const failed = record({ action: 'SuspendUser', action_request_status: 'failed', action_execution_error: 'Traceback: secret detail' });
assert.doesNotMatch(review.remediationStatusText(failed), /Traceback|secret/, 'stored failure text is never quoted');
assert.equal(review.remediationStatusText(record({ action: 'None' })), null);

// A suspension or block the violation already records is requested again only on purpose,
// whatever became of its last request, and never while one waits or a warning is sent.
for (const state of ['executed', 'failed', 'denied', 'expired', null]) {
    assert.equal(review.offersRestrictionReissue(record({ action: 'BlockUser', action_request_status: state }), 'BlockUser'), true, String(state));
}
assert.equal(review.offersRestrictionReissue(pending, 'SuspendUser'), false);
assert.equal(review.offersRestrictionReissue(record({ action: 'SuspendUser', action_request_status: 'sending' }), 'SuspendUser'), false);
assert.equal(review.offersRestrictionReissue(denied, 'SuspendUser'), false, 'a changed action is requested anyway');
assert.equal(review.offersRestrictionReissue(record({ action: 'WarnUser', action_request_status: 'executed' }), 'WarnUser'), false);
assert.equal(
    review.existingRestrictionText(denied, 'BlockUser'),
    'This block request was denied. Saving updates the review only and requests nothing new. To ask another eligible reviewer to approve it again, select "Request this block again".',
);
assert.match(review.existingRestrictionText(failed, 'SuspendUser'), /^This suspension was approved but could not be applied\./);
assert.match(review.existingRestrictionText(record({ action: 'SuspendUser', action_request_status: 'expired' }), 'SuspendUser'), /^This suspension request expired without a decision\./);
assert.match(review.existingRestrictionText(record({ action: 'BlockUser', action_request_status: 'executed' }), 'BlockUser'), /^This block was approved and applied\./);
const top = review.topCategory(record({ triggered_categories: [{ category: 'Hate', severity: 2 }, { category: 'Violence', severity: 6 }] }));
assert.deepEqual(top, { category: 'Violence', severity: 6 });

/* The standard notification mirrors functions_safety_remediation._default_notification_message. */
const violation = record({ triggered_categories: [{ category: 'Hate', severity: 4 }] });
assert.equal(review.defaultNotificationTitle('SuspendUser'), 'Account Suspension Notice');
assert.equal(review.defaultNotificationMessage(violation, 'SuspendUser', ' Repeated. ', 'Mon, 05 Oct 2026 00:00:00 GMT'), [
    'A safety review has been completed for recent activity in your workspace.',
    'Violation ID: log-1',
    'Triggered categories: Hate(s=4)',
    'Action taken: Your access has been temporarily suspended pending the date below.',
    'Access restores automatically after: Mon, 05 Oct 2026 00:00:00 GMT',
    'Admin notes: Repeated.',
].join('\n'));
const now = new Date('2026-10-01T00:00:00Z');
assert.equal(review.suspendPresetUntil('24h', now).toISOString(), '2026-10-02T00:00:00.000Z');
assert.equal(review.suspendPresetUntil('30d', now).toISOString(), '2026-10-31T00:00:00.000Z');
assert.equal(review.suspendPresetUntil('custom', now), null);
assert.equal(review.fromLocalDateTimeInput(''), null);
assert.equal(review.fromLocalDateTimeInput(review.toLocalDateTimeInput('2026-10-01T12:30:00Z')), '2026-10-01T12:30:00.000Z');

/* Bulk results name each failure, in the server's words. */
const report = review.buildBulkReport([
    { id: 'a', op: 'archive', ok: true, status: 200 },
    { id: 'b', op: 'archive', ok: false, status: 409, code: 'remediation_pending', error: 'Waiting on approval.' },
    { id: 'c', op: 'archive', ok: false, status: 404, code: 'not_found' },
], 'Archived', { singular: 'violation', plural: 'violations' }, (id) => `Record ${id}`);
assert.equal(report.summary, 'Archived 1 of 3 violations. 2 were not changed.');
assert.deepEqual(report.failures, [
    { id: 'b', label: 'Record b', message: 'Waiting on approval.' },
    { id: 'c', label: 'Record c', message: 'The change could not be made.' },
]);
assert.equal(review.buildBulkReport([{ id: 'a', op: 'delete', ok: true, status: 200 }], 'Deleted',
    { singular: 'violation', plural: 'violations' }, String).summary, 'Deleted 1 violation.');
assert.deepEqual(review.chunkIds([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);

/* Checked rows: toggle, Shift+click range, prune on reload, and "every matching". */
const rows = ['r1', 'r2', 'r3', 'r4'];
let state = selection.EMPTY_REVIEW_SELECTION;
state = selection.toggleChecked(state, 'r1', false, rows, 'k');
state = selection.toggleChecked(state, 'r3', true, rows, 'k');
assert.deepEqual(selection.checkedIds(state, 'k'), ['r1', 'r2', 'r3']);
state = selection.toggleChecked(state, 'r2', false, rows, 'k');
assert.deepEqual(selection.checkedIds(state, 'k'), ['r1', 'r3']);
state = selection.pruneReviewSelection(state, ['r3', 'r4'], 'k');
assert.deepEqual(selection.checkedIds(state, 'k'), ['r3'], 'rows no longer shown are dropped');
state = selection.togglePageChecked(state, rows, 'k');
assert.deepEqual(selection.checkedIds(state, 'k'), rows);
state = selection.togglePageChecked(state, rows, 'k');
assert.deepEqual(selection.checkedIds(state, 'k'), []);
const matching = selection.selectMatching({ ids: ['r1', 'x9'], total: 742, capped: true, cap: 500 }, 'k');
assert.deepEqual(selection.checkedIds(matching, 'k'), ['r1', 'x9']);
assert.equal(selection.selectionSummary(matching, 'k', { singular: 'violation', plural: 'violations' }),
    '2 violations selected, the first 500 of 742 matching');
assert.deepEqual(selection.checkedIds(matching, 'other-filters'), [], 'a change of filters drops "every matching"');
assert.equal(selection.pruneReviewSelection(matching, ['r1'], 'k'), matching, 'every matching survives a reload of its filters');
const narrowed = selection.toggleChecked(matching, 'r2', false, rows, 'k');
assert.deepEqual(selection.checkedIds(narrowed, 'k'), ['r1', 'r2'], 'a click keeps the page rows that matched');
assert.deepEqual(selection.checkedIds(selection.keepFailures(['r4']), 'k'), ['r4']);
assert.deepEqual(selection.checkedIds(selection.keepFailures([]), 'k'), []);

console.log('PASS: Review center access, filters, remediation state and selection');
