// FeedbackEditorPage.tsx
// One feedback record's review, as a full page: /admin/review/feedback/queue/<id>.
//
// Replaces the review dialog of the old Feedback Review page. The page keeps the workbench's
// filters in its address, so Back returns to the same list with the record still selected.
// Leaving with unsaved changes asks first. A save that finds the record changed since it
// was opened is refused rather than overwriting the newer version, and the page offers to
// reload it. The reviewer's name is recorded with every save, and the user is only told
// about the review when the reviewer chooses to notify them.

import { useEffect, useId, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { ClipboardCheck, MessageSquareText, RotateCcw, TriangleAlert } from 'lucide-react';
import { FeedbackRetest } from '../../components/review/FeedbackRetest';
import { ReviewEditorPlaceholder } from '../../components/review/ReviewEditorPlaceholder';
import { ReviewFact, ReviewTextBlock, ToneBadge } from '../../components/review/ReviewParts';
import { EditorFieldRow, EditorSwitch } from '../../components/workspace/EditorLayout';
import { WorkspaceEditorFrame } from '../../components/workspace/WorkspaceEditorFrame';
import { EmptyState, GlassButton, Skeleton } from '../../components/ui/primitives';
import { ApiError } from '../../lib/apiClient';
import {
    feedbackRatingTone,
    feedbackReviewerName,
    feedbackReviewState,
    feedbackRowTitle,
    feedbackUserLabel,
    formatReviewDate,
    safeReviewViewHref,
    type FeedbackRecord,
} from '../../lib/reviewCenter';
import { errorText, fetchFeedbackRecord, needsReload, saveFeedbackReview } from '../../lib/reviewCenterApi';

const TEXTAREA_CLASS = 'w-full rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none';

interface FeedbackDraft {
    acknowledged: boolean;
    analysisNotes: string;
    actionTaken: string;
    responseToUser: string;
    notifyUser: boolean;
}

function draftFrom(record: FeedbackRecord): FeedbackDraft {
    const review = record.adminReview ?? {};
    return {
        acknowledged: Boolean(review.acknowledged),
        analysisNotes: review.analysisNotes ?? '',
        actionTaken: review.actionTaken ?? '',
        responseToUser: review.responseToUser ?? '',
        notifyUser: false,
    };
}

function sameDraft(a: FeedbackDraft, b: FeedbackDraft): boolean {
    return a.acknowledged === b.acknowledged && a.analysisNotes === b.analysisNotes && a.actionTaken === b.actionTaken
        && a.responseToUser === b.responseToUser && a.notifyUser === b.notifyUser;
}

type Load =
    | { status: 'loading' }
    | { status: 'failed'; message: string; missing: boolean }
    | { status: 'ready'; record: FeedbackRecord };

export function FeedbackEditorPage({ recordId }: { recordId: string }) {
    const navigate = useNavigate();
    const location = useLocation();
    const [searchParams] = useSearchParams();
    const backParams = new URLSearchParams(searchParams);
    backParams.set('selected', recordId);
    const backTo = safeReviewViewHref('feedback', 'queue', backParams);
    const [load, setLoad] = useState<Load>({ status: 'loading' });
    const [attempt, setAttempt] = useState(0);
    const [draft, setDraft] = useState<FeedbackDraft | null>(null);
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState<string | null>(null);
    const [stale, setStale] = useState(false);
    const ids = useId();

    useEffect(() => {
        const controller = new AbortController();
        setLoad({ status: 'loading' });
        fetchFeedbackRecord(recordId, controller.signal)
            .then((record) => {
                setLoad({ status: 'ready', record });
                setDraft(draftFrom(record));
                setSaveError(null);
                setStale(false);
            })
            .catch((cause) => {
                if (controller.signal.aborted) return;
                const missing = cause instanceof ApiError && cause.status === 404;
                setLoad({ status: 'failed', message: errorText(cause, 'The feedback could not be loaded.'), missing });
            });
        return () => controller.abort();
    }, [recordId, attempt]);

    if (load.status === 'loading' || (load.status === 'ready' && !draft)) {
        return (
            <ReviewEditorPlaceholder backTo={backTo}>
                <div role="status" className="space-y-4">
                    <span className="sr-only">Loading the feedback</span>
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
                        title={load.missing ? 'Feedback not found' : 'The feedback could not load'}
                        description={load.missing ? 'This feedback was deleted or is no longer available.' : load.message}
                        action={load.missing ? undefined : (
                            <GlassButton type="button" size="sm" variant="subtle" onClick={() => setAttempt((value) => value + 1)}>Retry</GlassButton>
                        )}
                    />
                </div>
            </ReviewEditorPlaceholder>
        );
    }

    const record = load.record;
    const current = draft as FeedbackDraft;
    const initial = draftFrom(record);
    const dirty = !sameDraft(current, initial);
    const state = feedbackReviewState(record);
    const review = record.adminReview ?? {};
    const reviewer = feedbackReviewerName(review);
    const update = (changes: Partial<FeedbackDraft>) => setDraft((value) => (value ? { ...value, ...changes } : value));

    const save = async () => {
        setSaving(true);
        setSaveError(null);
        try {
            const result = await saveFeedbackReview(record.id, {
                acknowledged: current.acknowledged,
                analysisNotes: current.analysisNotes,
                actionTaken: current.actionTaken,
                responseToUser: current.responseToUser,
                notify_user: current.notifyUser,
                etag: record.etag,
            });
            const message = result.notification_warning
                ? `Review saved. ${result.notification_warning}`
                : result.notified
                    ? 'Review saved and the user was notified.'
                    : 'Review saved.';
            navigate(backTo, {
                replace: true,
                state: {
                    workspaceEditorSaved: true,
                    workspaceEditorFrom: location.key,
                    reviewNotice: { message, warning: Boolean(result.notification_warning) },
                },
            });
        } catch (cause) {
            setStale(needsReload(cause));
            setSaveError(errorText(cause, 'The review could not be saved.'));
            setSaving(false);
        }
    };

    return (
        <WorkspaceEditorFrame
            title="Review feedback"
            description={feedbackRowTitle(record)}
            icon={MessageSquareText}
            backTo={backTo}
            dirty={dirty}
            saving={saving}
            error={stale ? `${saveError} Reloading discards your unsaved changes.` : saveError}
            onSave={() => void save()}
            onDiscard={() => setDraft(initial)}
            saveLabel="Save review"
            actions={stale ? (
                <GlassButton type="button" variant="subtle" onClick={() => setAttempt((value) => value + 1)} data-testid="v2-feedback-editor-reload">
                    <RotateCcw size={15} aria-hidden="true" /> Reload
                </GlassButton>
            ) : undefined}
            sections={[
                {
                    id: 'feedback',
                    label: 'The feedback',
                    description: 'What the user asked, the response they rated, and why.',
                    icon: MessageSquareText,
                    content: (
                        <div className="@container space-y-4" data-testid="v2-feedback-editor">
                            <div className="flex flex-wrap gap-1.5">
                                <ToneBadge tone={feedbackRatingTone(record.feedbackType)}>{record.feedbackType || 'Unrated'}</ToneBadge>
                                <ToneBadge tone={state.tone}>{state.label}</ToneBadge>
                                {record.isArchived ? <ToneBadge tone="neutral">Archived</ToneBadge> : null}
                            </div>
                            <dl className="grid gap-x-6 sm:grid-cols-2">
                                <ReviewFact label="From">{feedbackUserLabel(record)}{record.userEmail && record.userDisplayName ? ` · ${record.userEmail}` : ''}</ReviewFact>
                                <ReviewFact label="Sent">{formatReviewDate(record.timestamp)}</ReviewFact>
                            </dl>
                            <ReviewTextBlock label="Prompt" text={record.prompt} empty="No prompt captured." />
                            <ReviewTextBlock label="Reason given" text={record.reason} empty="The user gave no reason." />
                            <FeedbackRetest record={record} testIdPrefix="v2-feedback-editor" />
                        </div>
                    ),
                },
                {
                    id: 'review',
                    label: 'Your review',
                    description: 'What you found, what was done about it, and what to tell the user.',
                    icon: ClipboardCheck,
                    content: (
                        <div className="space-y-1">
                            <EditorSwitch
                                checked={current.acknowledged}
                                onChange={(value) => update({ acknowledged: value })}
                                label="Acknowledged"
                                description="Marks the feedback as reviewed, so it leaves the queue of feedback awaiting review."
                            />
                            <EditorFieldRow htmlFor={`${ids}-analysis`} label="Analysis notes" help="For reviewers only; the user never sees these.">
                                <textarea
                                    id={`${ids}-analysis`}
                                    rows={4}
                                    maxLength={8000}
                                    value={current.analysisNotes}
                                    onChange={(event) => update({ analysisNotes: event.target.value })}
                                    className={TEXTAREA_CLASS}
                                    data-testid="v2-feedback-editor-analysis"
                                />
                            </EditorFieldRow>
                            <EditorFieldRow htmlFor={`${ids}-action`} label="Action taken" help="What changed because of this feedback, if anything.">
                                <textarea
                                    id={`${ids}-action`}
                                    rows={3}
                                    maxLength={8000}
                                    value={current.actionTaken}
                                    onChange={(event) => update({ actionTaken: event.target.value })}
                                    className={TEXTAREA_CLASS}
                                />
                            </EditorFieldRow>
                            <EditorFieldRow
                                htmlFor={`${ids}-response`}
                                label="Response to the user"
                                help="Shown to the user with their feedback in their settings."
                            >
                                <textarea
                                    id={`${ids}-response`}
                                    rows={4}
                                    maxLength={8000}
                                    value={current.responseToUser}
                                    onChange={(event) => update({ responseToUser: event.target.value })}
                                    className={TEXTAREA_CLASS}
                                    data-testid="v2-feedback-editor-response"
                                />
                            </EditorFieldRow>
                            <EditorSwitch
                                checked={current.notifyUser}
                                onChange={(value) => update({ notifyUser: value })}
                                label="Notify the user"
                                description={current.responseToUser.trim()
                                    ? 'When you save, the user gets a notification with your response that opens their feedback.'
                                    : 'When you save, the user gets a notification that their feedback was reviewed, which opens their feedback.'}
                            />
                            <dl className="grid gap-x-6 border-t border-edge pt-2 sm:grid-cols-2">
                                <ReviewFact label="Last reviewed">
                                    {review.reviewTimestamp
                                        ? `${formatReviewDate(review.reviewTimestamp)}${reviewer ? ` by ${reviewer}` : ''}`
                                        : 'Not reviewed yet'}
                                </ReviewFact>
                                <ReviewFact label="User last notified">{review.userNotifiedAt ? formatReviewDate(review.userNotifiedAt) : 'Never'}</ReviewFact>
                            </dl>
                        </div>
                    ),
                },
            ]}
        />
    );
}
