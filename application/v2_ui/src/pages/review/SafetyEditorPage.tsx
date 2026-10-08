// SafetyEditorPage.tsx
// One safety violation's review, as a full page: /admin/review/safety/violations/<id>.
//
// Replaces the review dialog of the old Safety Violations page. The page keeps the
// workbench's filters in its address, so Back returns to the same list with the violation
// still selected, and leaving with unsaved changes asks first.
//
// What a save does depends on the action, and the page says so before it happens: a warning
// is sent as soon as the review is saved; a suspension or block creates an approval request
// that another eligible reviewer must approve. Saving a violation whose suspension or block
// was already requested or applied requests nothing more unless the reviewer asks to
// request it again. A violation waiting on an approval request, or whose warning is being
// sent, cannot be changed until that settles. A save that finds the violation changed since
// it was opened is refused rather than overwriting the newer version.

import { useEffect, useId, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { ClipboardCheck, ExternalLink, Gavel, ListFilter, RotateCcw, ShieldAlert, TriangleAlert, Undo2 } from 'lucide-react';
import { ReviewEditorPlaceholder } from '../../components/review/ReviewEditorPlaceholder';
import { ReviewFact, ReviewNotice, ReviewTextBlock, ToneBadge } from '../../components/review/ReviewParts';
import { EditorFieldRow, EditorFieldset } from '../../components/workspace/EditorLayout';
import { WorkspaceEditorFrame } from '../../components/workspace/WorkspaceEditorFrame';
import { EmptyState, GlassButton, Skeleton } from '../../components/ui/primitives';
import { ApiError } from '../../lib/apiClient';
import {
    APPROVAL_REQUIRED_ACTIONS,
    categorySummary,
    defaultNotificationMessage,
    defaultNotificationTitle,
    formatReviewDate,
    fromLocalDateTimeInput,
    isExecutedWarning,
    isSafetyRecordLocked,
    REMEDIATION_ACTIONS,
    remediationStatusText,
    safeApprovalRequestHref,
    safeReviewViewHref,
    safeViolationsHref,
    SAFETY_STATUSES,
    safetyActionBadge,
    safetyActionLabel,
    safetyRequestState,
    safetyRowTitle,
    safetyStatusTone,
    safetyUserLabel,
    selectableSafetyActions,
    SUSPEND_PRESETS,
    suspendPresetUntil,
    toLocalDateTimeInput,
    warningAcknowledgmentText,
    type SafetyRecord,
    type SuspendPreset,
} from '../../lib/reviewCenter';
import { errorText, fetchSafetyRecord, needsReload, saveSafetyReview, type SafetyReviewChanges } from '../../lib/reviewCenterApi';

const FIELD_CLASS = 'w-full rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none';

interface SafetyDraft {
    status: string;
    action: string;
    notes: string;
    title: string;
    titleEdited: boolean;
    message: string;
    messageEdited: boolean;
    preset: SuspendPreset | '';
    /** The restore time to request, as ISO 8601, or '' for none. */
    until: string;
    /** The custom restore time as the date-time field holds it. */
    customUntil: string;
    reissue: boolean;
}

/** A restore time as it reads in the notification: unambiguous whatever the user's time zone. */
function restoreText(until: string): string | null {
    if (!until) return null;
    const date = new Date(until);
    return Number.isNaN(date.getTime()) ? until : date.toUTCString();
}

function withDefaults(record: SafetyRecord, draft: SafetyDraft): SafetyDraft {
    return {
        ...draft,
        title: draft.titleEdited ? draft.title : defaultNotificationTitle(draft.action),
        message: draft.messageEdited
            ? draft.message
            : defaultNotificationMessage(record, draft.action, draft.notes, restoreText(draft.until)),
    };
}

function draftFrom(record: SafetyRecord): SafetyDraft {
    const action = record.action || 'None';
    const until = record.action === 'SuspendUser' && record.action_datetime_to_allow ? record.action_datetime_to_allow : '';
    const notes = record.notes ?? '';
    const defaultTitle = defaultNotificationTitle(action);
    const defaultMessage = defaultNotificationMessage(record, action, notes, restoreText(until));
    const title = record.action_notification_title || defaultTitle;
    const message = record.action_notification_message || defaultMessage;
    return {
        status: record.status || 'New',
        action,
        notes,
        title,
        titleEdited: title !== defaultTitle,
        message,
        messageEdited: message !== defaultMessage,
        preset: until ? 'custom' : '',
        until,
        customUntil: toLocalDateTimeInput(until),
        reissue: false,
    };
}

function sameDraft(a: SafetyDraft, b: SafetyDraft): boolean {
    return a.status === b.status && a.action === b.action && a.notes === b.notes && a.title === b.title
        && a.message === b.message && a.until === b.until && a.reissue === b.reissue && a.preset === b.preset;
}

/** Whether saving this draft sends a notification: a new warning, or a new suspension or block request. */
function sendsNotice(record: SafetyRecord, draft: SafetyDraft): boolean {
    const previous = record.action || 'None';
    if (draft.action === 'WarnUser') return !(previous === 'WarnUser' && safetyRequestState(record) === 'executed');
    if (APPROVAL_REQUIRED_ACTIONS.has(draft.action)) return draft.action !== previous || draft.reissue;
    return false;
}

type Load =
    | { status: 'loading' }
    | { status: 'failed'; message: string; missing: boolean }
    | { status: 'ready'; record: SafetyRecord };

function accessText(record: SafetyRecord): string {
    const access = record.user_access;
    if (!access) return 'Not available';
    if (!access.restricted) return 'Not restricted';
    if (access.kind === 'suspended') return `Suspended until ${formatReviewDate(access.until)}`;
    return 'Blocked';
}

export function SafetyEditorPage({ recordId }: { recordId: string }) {
    const navigate = useNavigate();
    const location = useLocation();
    const [searchParams] = useSearchParams();
    const backParams = new URLSearchParams(searchParams);
    backParams.set('selected', recordId);
    const backTo = safeReviewViewHref('safety', 'violations', backParams);
    const [load, setLoad] = useState<Load>({ status: 'loading' });
    const [attempt, setAttempt] = useState(0);
    const [draft, setDraft] = useState<SafetyDraft | null>(null);
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState<string | null>(null);
    const [stale, setStale] = useState(false);
    const ids = useId();

    useEffect(() => {
        const controller = new AbortController();
        setLoad({ status: 'loading' });
        fetchSafetyRecord(recordId, controller.signal)
            .then((record) => {
                setLoad({ status: 'ready', record });
                setDraft(draftFrom(record));
                setSaveError(null);
                setStale(false);
            })
            .catch((cause) => {
                if (controller.signal.aborted) return;
                const missing = cause instanceof ApiError && cause.status === 404;
                setLoad({ status: 'failed', message: errorText(cause, 'The violation could not be loaded.'), missing });
            });
        return () => controller.abort();
    }, [recordId, attempt]);

    if (load.status === 'loading' || (load.status === 'ready' && !draft)) {
        return (
            <ReviewEditorPlaceholder backTo={backTo}>
                <div role="status" className="space-y-4">
                    <span className="sr-only">Loading the violation</span>
                    <Skeleton className="h-8 w-72" />
                    <Skeleton className="h-48 w-full" />
                    <Skeleton className="h-48 w-full" />
                </div>
            </ReviewEditorPlaceholder>
        );
    }
    if (load.status === 'failed') {
        return (
            <ReviewEditorPlaceholder backTo={backTo}>
                <div role="alert">
                    <EmptyState
                        icon={<TriangleAlert size={28} />}
                        title={load.missing ? 'Violation not found' : 'The violation could not load'}
                        description={load.missing ? 'This violation was deleted or is no longer available.' : load.message}
                        action={load.missing ? undefined : (
                            <GlassButton type="button" size="sm" variant="subtle" onClick={() => setAttempt((value) => value + 1)}>Retry</GlassButton>
                        )}
                    />
                </div>
            </ReviewEditorPlaceholder>
        );
    }

    const record = load.record;
    const current = draft as SafetyDraft;
    const initial = draftFrom(record);
    const dirty = !sameDraft(current, initial);
    const locked = isSafetyRecordLocked(record);
    const previousAction = record.action || 'None';
    const fromAssistant = record.content_origin === 'assistant';
    const sends = sendsNotice(record, current);
    const restricting = APPROVAL_REQUIRED_ACTIONS.has(current.action);
    const offerReissue = restricting && current.action === previousAction && !locked;
    const actionWord = current.action === 'BlockUser' ? 'block' : 'suspension';
    const remediation = remediationStatusText(record);
    const acknowledgment = warningAcknowledgmentText(record);
    const badge = safetyActionBadge(record);

    const update = (changes: Partial<SafetyDraft>) => setDraft((value) => (value ? withDefaults(record, { ...value, ...changes }) : value));
    const choosePreset = (preset: SuspendPreset) => {
        if (preset === 'custom') {
            update({ preset, until: fromLocalDateTimeInput(current.customUntil) ?? '' });
            return;
        }
        update({ preset, until: suspendPresetUntil(preset)?.toISOString() ?? '' });
    };

    const save = async () => {
        if (sends && current.action === 'SuspendUser') {
            if (!current.until) {
                setStale(false);
                setSaveError('Choose how long the suspension lasts.');
                return;
            }
            if (new Date(current.until).getTime() <= Date.now()) {
                setStale(false);
                setSaveError('Choose a time in the future for access to return.');
                return;
            }
        }
        const payload: SafetyReviewChanges = {
            status: current.status,
            action: current.action,
            notes: current.notes,
            etag: record.etag,
        };
        if (sends) {
            payload.notification_title = current.title.trim();
            payload.notification_message = current.message.trim();
            if (current.action === 'SuspendUser') payload.datetime_to_allow = current.until;
        }
        if (offerReissue && current.reissue) payload.reissue = true;
        setSaving(true);
        setSaveError(null);
        try {
            const result = await saveSafetyReview(record.id, payload);
            const message = [result.message || 'Review saved.', result.audit_warning].filter(Boolean).join(' ');
            navigate(backTo, {
                replace: true,
                state: {
                    workspaceEditorSaved: true,
                    workspaceEditorFrom: location.key,
                    reviewNotice: { message, warning: Boolean(result.audit_warning) },
                },
            });
        } catch (cause) {
            setStale(needsReload(cause));
            setSaveError(errorText(cause, 'The review could not be saved.'));
            setSaving(false);
        }
    };

    const approvalLink = record.action_request_id ? (
        <Link
            to={safeApprovalRequestHref(record.action_request_id, record.user_id)}
            className="inline-flex items-center gap-1.5 text-sm text-accent underline underline-offset-2"
            data-testid="v2-safety-editor-approval-link"
        >
            <ExternalLink size={14} aria-hidden="true" /> Open the approval request
        </Link>
    ) : null;

    let actionCopy: string | null = null;
    if (current.action === 'WarnUser') {
        actionCopy = isExecutedWarning(record) && previousAction === 'WarnUser'
            ? 'This warning was already sent. Saving updates the review without sending the warning again.'
            : 'The warning is sent to the user as soon as you save, without a second reviewer. The user must acknowledge it the next time they use SimpleChat.';
    } else if (restricting && sends) {
        actionCopy = current.action === 'SuspendUser'
            ? 'A suspension restricts access, so saving creates an approval request. It applies only after another eligible reviewer approves it.'
            : 'A block restricts access, so saving creates an approval request. It applies only after another eligible reviewer approves it.';
    } else if (restricting) {
        actionCopy = `Saving keeps the ${actionWord} as it is and requests nothing new.`;
    }

    return (
        <WorkspaceEditorFrame
            title="Review safety violation"
            description={safetyRowTitle(record)}
            icon={ShieldAlert}
            backTo={backTo}
            dirty={dirty}
            saving={saving}
            locked={locked}
            lockBanner={(
                <ReviewNotice tone="info" testId="v2-safety-editor-locked">
                    <p>{remediation} This violation cannot be changed until {safetyRequestState(record) === 'sending' ? 'the warning is sent' : 'the request is decided'}.</p>
                    {approvalLink ? <p className="mt-1">{approvalLink}</p> : null}
                </ReviewNotice>
            )}
            error={stale ? `${saveError} Reloading discards your unsaved changes.` : saveError}
            onSave={() => void save()}
            onDiscard={() => setDraft(initial)}
            saveLabel="Save review"
            actions={stale || locked ? (
                <GlassButton type="button" variant="subtle" onClick={() => setAttempt((value) => value + 1)} data-testid="v2-safety-editor-reload">
                    <RotateCcw size={15} aria-hidden="true" /> Reload
                </GlassButton>
            ) : undefined}
            sections={[
                {
                    id: 'violation',
                    label: 'The violation',
                    description: 'What was flagged, why, and who sent it.',
                    icon: ShieldAlert,
                    content: (
                        <div className="space-y-4" data-testid="v2-safety-editor">
                            <div className="flex flex-wrap gap-1.5">
                                <ToneBadge tone={safetyStatusTone(record.status)}>{record.status || 'New'}</ToneBadge>
                                {record.action && record.action !== 'None' ? (
                                    <ToneBadge tone={badge.tone}>{badge.detail ? `${badge.label} · ${badge.detail}` : badge.label}</ToneBadge>
                                ) : null}
                                {record.isArchived ? <ToneBadge tone="neutral">Archived</ToneBadge> : null}
                            </div>
                            <ReviewTextBlock label="Flagged message" text={record.message} empty="No message captured." />
                            <dl className="grid gap-x-6 sm:grid-cols-2">
                                <ReviewFact label="Triggered categories">{categorySummary(record) || 'No triggered categories'}</ReviewFact>
                                <ReviewFact label="Flagged content">{fromAssistant ? 'An AI response' : 'A message the user sent'}</ReviewFact>
                                <ReviewFact label="Flagged">{formatReviewDate(record.created_at)}</ReviewFact>
                                <ReviewFact label="User">
                                    {safetyUserLabel(record)}{record.user_email && record.user_display_name ? ` · ${record.user_email}` : ''}
                                </ReviewFact>
                                <ReviewFact label="Access now">{accessText(record)}</ReviewFact>
                                <ReviewFact label="Other violations by this user">
                                    {record.user_violation_count === null || record.user_violation_count === undefined
                                        ? 'Not available'
                                        : record.user_violation_count.toLocaleString()}
                                </ReviewFact>
                            </dl>
                            {record.user_notes ? <ReviewTextBlock label="The user's notes" text={record.user_notes} empty="" /> : null}
                            {record.user_id ? (
                                <Link
                                    to={safeViolationsHref({ userId: record.user_id, archive: 'all' })}
                                    className="inline-flex items-center gap-1.5 text-sm text-accent underline underline-offset-2"
                                >
                                    <ListFilter size={14} aria-hidden="true" /> Show every violation by this user
                                </Link>
                            ) : null}
                        </div>
                    ),
                },
                {
                    id: 'review',
                    label: 'Review',
                    description: 'Where the review stands, and notes for other reviewers.',
                    icon: ClipboardCheck,
                    content: (
                        <div className="space-y-1">
                            <EditorFieldRow htmlFor={`${ids}-status`} label="Status" width="standard">
                                <select
                                    id={`${ids}-status`}
                                    value={current.status}
                                    onChange={(event) => update({ status: event.target.value })}
                                    className={FIELD_CLASS}
                                    data-testid="v2-safety-editor-status"
                                >
                                    {SAFETY_STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
                                </select>
                            </EditorFieldRow>
                            <EditorFieldRow
                                htmlFor={`${ids}-notes`}
                                label="Reviewer notes"
                                help="Kept with the violation. When a notification uses the standard message, these notes are added to it."
                            >
                                <textarea
                                    id={`${ids}-notes`}
                                    rows={4}
                                    value={current.notes}
                                    onChange={(event) => update({ notes: event.target.value })}
                                    className={FIELD_CLASS}
                                    data-testid="v2-safety-editor-notes"
                                />
                            </EditorFieldRow>
                        </div>
                    ),
                },
                {
                    id: 'remediation',
                    label: 'Remediation',
                    description: 'Warn the user, or ask another reviewer to suspend or block them.',
                    icon: Gavel,
                    content: (
                        <div className="space-y-3">
                            {remediation || acknowledgment ? (
                                <div className="space-y-1 rounded-xl bg-surface-2 p-3 text-sm text-text-2" data-testid="v2-safety-editor-remediation-state">
                                    {remediation ? <p>{remediation}</p> : null}
                                    {acknowledgment ? <p data-testid="v2-safety-warning-acknowledgment">{acknowledgment}</p> : null}
                                    {approvalLink}
                                </div>
                            ) : null}
                            <EditorFieldRow
                                htmlFor={`${ids}-action`}
                                label="Action"
                                width="standard"
                                help={fromAssistant ? 'AI-generated findings cannot be used to warn or restrict a user.' : undefined}
                            >
                                <select
                                    id={`${ids}-action`}
                                    value={current.action}
                                    onChange={(event) => update({
                                        action: event.target.value,
                                        titleEdited: false,
                                        messageEdited: false,
                                        reissue: false,
                                    })}
                                    className={FIELD_CLASS}
                                    data-testid="v2-safety-editor-action"
                                >
                                    {selectableSafetyActions(record).map((action) => (
                                        <option key={action} value={action} disabled={fromAssistant && REMEDIATION_ACTIONS.has(action)}>
                                            {safetyActionLabel(action)}
                                        </option>
                                    ))}
                                </select>
                            </EditorFieldRow>
                            {actionCopy ? (
                                <ReviewNotice tone={sends ? 'info' : 'ok'} testId="v2-safety-editor-action-copy">{actionCopy}</ReviewNotice>
                            ) : null}
                            {offerReissue ? (
                                <label className="flex items-start gap-2 text-sm text-text-1">
                                    <input
                                        type="checkbox"
                                        checked={current.reissue}
                                        onChange={(event) => update({ reissue: event.target.checked })}
                                        className="mt-0.5 h-4 w-4 accent-[var(--color-accent)]"
                                        data-testid="v2-safety-editor-reissue"
                                    />
                                    <span>
                                        Request this {actionWord} again
                                        <span className="block text-xs text-text-3">
                                            Creates a new approval request with the notification and {current.action === 'SuspendUser' ? 'restore time' : 'details'} below.
                                        </span>
                                    </span>
                                </label>
                            ) : null}
                            {current.action === 'SuspendUser' && sends ? (
                                <EditorFieldset legend="Suspension length" help="Access returns on its own at this time. The suspension starts once another reviewer approves it.">
                                    <div className="flex flex-wrap gap-x-5 gap-y-2">
                                        {SUSPEND_PRESETS.map((preset) => (
                                            <label key={preset.id} className="inline-flex items-center gap-2 text-sm text-text-1">
                                                <input
                                                    type="radio"
                                                    name={`${ids}-preset`}
                                                    value={preset.id}
                                                    checked={current.preset === preset.id}
                                                    onChange={() => choosePreset(preset.id)}
                                                    className="h-4 w-4 accent-[var(--color-accent)]"
                                                    data-testid={`v2-safety-editor-preset-${preset.id}`}
                                                />
                                                {preset.label}
                                            </label>
                                        ))}
                                    </div>
                                    {current.preset === 'custom' ? (
                                        <div className="max-w-xs">
                                            <label htmlFor={`${ids}-until`} className="mb-1 block text-xs text-text-2">Restore access at</label>
                                            <input
                                                id={`${ids}-until`}
                                                type="datetime-local"
                                                value={current.customUntil}
                                                onChange={(event) => update({
                                                    customUntil: event.target.value,
                                                    until: fromLocalDateTimeInput(event.target.value) ?? '',
                                                })}
                                                className={FIELD_CLASS}
                                                data-testid="v2-safety-editor-until"
                                            />
                                        </div>
                                    ) : null}
                                    {current.until ? (
                                        <p className="text-xs text-text-3" data-testid="v2-safety-editor-restore-at">
                                            Access returns {formatReviewDate(current.until)}.
                                        </p>
                                    ) : null}
                                </EditorFieldset>
                            ) : null}
                            {sends ? (
                                <>
                                    <EditorFieldRow htmlFor={`${ids}-title`} label="Notification title">
                                        <input
                                            id={`${ids}-title`}
                                            type="text"
                                            maxLength={200}
                                            value={current.title}
                                            onChange={(event) => update({ title: event.target.value, titleEdited: true })}
                                            className={FIELD_CLASS}
                                            data-testid="v2-safety-editor-title"
                                        />
                                    </EditorFieldRow>
                                    <EditorFieldRow
                                        htmlFor={`${ids}-message`}
                                        label="Notification message"
                                        help="What the user reads. It starts as the standard message for this action; leave it empty to send the standard message."
                                    >
                                        <textarea
                                            id={`${ids}-message`}
                                            rows={7}
                                            value={current.message}
                                            onChange={(event) => update({ message: event.target.value, messageEdited: true })}
                                            className={FIELD_CLASS}
                                            data-testid="v2-safety-editor-message"
                                        />
                                    </EditorFieldRow>
                                    {current.titleEdited || current.messageEdited ? (
                                        <GlassButton
                                            type="button"
                                            size="sm"
                                            variant="ghost"
                                            onClick={() => update({ titleEdited: false, messageEdited: false })}
                                        >
                                            <Undo2 size={14} aria-hidden="true" /> Use the standard title and message
                                        </GlassButton>
                                    ) : null}
                                </>
                            ) : null}
                        </div>
                    ),
                },
            ]}
        />
    );
}
