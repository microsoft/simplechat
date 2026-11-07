// FeedbackEditorPage.tsx
// One feedback record's review, as a full page: /admin/review/feedback/queue/<id>.
//
// Replaces the review dialog of the old Feedback Review page. The page keeps the workbench's
// filters in its address, so Back returns to the same list with the record still selected.
// Leaving with unsaved changes asks first. A save that finds the record changed since it
// was opened is refused rather than overwriting the newer version, and the page offers to
// reload it. The reviewer's name is recorded with every save, and the user is only told
// about the review when the reviewer chooses to notify them.
//
// When AI assist is on, Ask AI suggests a review: it fills the unsaved draft, marks each field
// it changed, and can be undone. The reviewer still saves. Applying a suggestion AI triage stored
// on the record saves through the suggestion, so it is marked applied and credited in the audit log.

import { useEffect, useId, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { clsx } from 'clsx';
import { ClipboardCheck, MessageSquareText, RotateCcw, TriangleAlert } from 'lucide-react';
import { FeedbackRetest } from '../../components/review/FeedbackRetest';
import { ReviewAskAiPanel, ReviewAskAiToggle, type AskAiSource } from '../../components/review/ReviewAskAiPanel';
import { ReviewEditorPlaceholder } from '../../components/review/ReviewEditorPlaceholder';
import { ReviewFact, ReviewTextBlock, ToneBadge } from '../../components/review/ReviewParts';
import { EditorFieldRow, EditorSwitch } from '../../components/workspace/EditorLayout';
import { WorkspaceEditorFrame } from '../../components/workspace/WorkspaceEditorFrame';
import { EmptyState, GlassButton, Skeleton } from '../../components/ui/primitives';
import { ApiError } from '../../lib/apiClient';
import {
    FEEDBACK_THEME_LABELS,
    FEEDBACK_THEMES,
    feedbackRatingTone,
    feedbackReviewerName,
    feedbackReviewState,
    feedbackRowTitle,
    feedbackUserLabel,
    formatReviewDate,
    isFeedbackTheme,
    safeReviewViewHref,
    type FeedbackRecord,
} from '../../lib/reviewCenter';
import {
    errorText,
    fetchFeedbackRecord,
    needsReload,
    saveFeedbackReview,
    saveReviewWithSuggestion,
    type FeedbackReviewChanges,
} from '../../lib/reviewCenterApi';
import {
    changedDraftGroups,
    draftKeyMarked,
    feedbackSuggestionChanges,
    parseFeedbackSuggestion,
    undoDraftGroups,
    undoReportText,
    type AnySuggestion,
    type DraftGroup,
    type FeedbackSuggestion,
} from '../../lib/reviewSuggestions';
import { useFeature } from '../../stores/bootstrapStore';

const TEXTAREA_CLASS = 'w-full rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none';
const AI_MARK_CLASS = 'ring-2 ring-change-ai/50';

interface FeedbackDraft {
    acknowledged: boolean;
    analysisNotes: string;
    actionTaken: string;
    responseToUser: string;
    theme: string;
    notifyUser: boolean;
}

const DRAFT_GROUPS: readonly DraftGroup<FeedbackDraft>[] = [
    { label: 'Acknowledged', keys: ['acknowledged'] },
    { label: 'Theme', keys: ['theme'] },
    { label: 'Analysis notes', keys: ['analysisNotes'] },
    { label: 'Action taken', keys: ['actionTaken'] },
    { label: 'Response to the user', keys: ['responseToUser'] },
];

interface AppliedSuggestion {
    source: AskAiSource;
    suggestionId: string | null;
    before: FeedbackDraft;
    after: FeedbackDraft;
}

function draftFrom(record: FeedbackRecord): FeedbackDraft {
    const review = record.adminReview ?? {};
    return {
        acknowledged: Boolean(review.acknowledged),
        analysisNotes: review.analysisNotes ?? '',
        actionTaken: review.actionTaken ?? '',
        responseToUser: review.responseToUser ?? '',
        theme: isFeedbackTheme(review.theme) ? review.theme : '',
        notifyUser: false,
    };
}

function sameDraft(a: FeedbackDraft, b: FeedbackDraft): boolean {
    return a.acknowledged === b.acknowledged && a.analysisNotes === b.analysisNotes && a.actionTaken === b.actionTaken
        && a.responseToUser === b.responseToUser && a.theme === b.theme && a.notifyUser === b.notifyUser;
}

function archiveNote(suggestion: AnySuggestion, record: FeedbackRecord): string[] {
    return suggestion.payload.archive && !record.isArchived
        ? ['It also suggests archiving this feedback. Archive it from the list after you save.']
        : [];
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
    const aiAvailable = useFeature('enable_admin_review_ai_assistant');
    const [assistOpen, setAssistOpen] = useState(false);
    const [applied, setApplied] = useState<AppliedSuggestion | null>(null);
    const [undoReport, setUndoReport] = useState<string | null>(null);
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
                setApplied(null);
                setUndoReport(null);
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
    const savedSuggestion = parseFeedbackSuggestion(record.ai_suggestion);
    const update = (changes: Partial<FeedbackDraft>) => setDraft((value) => (value ? { ...value, ...changes } : value));
    const marked = (key: keyof FeedbackDraft) => Boolean(applied && draftKeyMarked(current, applied.before, applied.after, key));
    const markedGroups = applied
        ? changedDraftGroups(applied.before, applied.after, DRAFT_GROUPS).filter((group) => group.keys.some(marked))
        : [];
    // The save goes through the stored suggestion only while the draft still holds what it applied.
    const appliedSuggestionId = applied?.source === 'saved' && markedGroups.length && savedSuggestion?.status === 'pending'
        && savedSuggestion.id === applied.suggestionId ? applied.suggestionId : null;

    const applySuggestion = (suggestion: AnySuggestion, source: AskAiSource) => {
        const payload = (suggestion as FeedbackSuggestion).payload;
        const next: FeedbackDraft = {
            ...current,
            acknowledged: payload.acknowledged,
            analysisNotes: payload.analysisNotes,
            actionTaken: payload.actionTaken,
            responseToUser: payload.responseToUser,
            theme: payload.theme,
        };
        setDraft(next);
        setApplied({ source, suggestionId: source === 'saved' ? suggestion.id : null, before: current, after: next });
        setUndoReport(null);
    };

    const undoSuggestion = () => {
        if (!applied) return;
        const result = undoDraftGroups(current, applied.before, applied.after, DRAFT_GROUPS);
        setDraft(result.draft);
        setApplied(null);
        setUndoReport(undoReportText(result.reverted, result.skipped));
    };

    const save = async () => {
        setSaving(true);
        setSaveError(null);
        const changes: Record<string, unknown> = {
            acknowledged: current.acknowledged,
            analysisNotes: current.analysisNotes,
            actionTaken: current.actionTaken,
            responseToUser: current.responseToUser,
            notify_user: current.notifyUser,
            etag: record.etag,
            // Lets the save go ahead when only an AI suggestion changed the record since it was opened.
            fingerprint: record.fingerprint,
        };
        // The theme is sent when it changed, and always with a suggestion, which is compared field by field.
        if (current.theme !== initial.theme || appliedSuggestionId) changes.theme = current.theme;
        try {
            const result = appliedSuggestionId
                ? await saveReviewWithSuggestion('feedback', record.id, changes, appliedSuggestionId)
                : await saveFeedbackReview(record.id, changes as FeedbackReviewChanges);
            const warning = typeof result.notification_warning === 'string' ? result.notification_warning : '';
            const base = warning
                ? `Review saved. ${warning}`
                : result.notified
                    ? 'Review saved and the user was notified.'
                    : 'Review saved.';
            const message = appliedSuggestionId ? `${base} The AI suggestion was marked as applied.` : base;
            navigate(backTo, {
                replace: true,
                state: {
                    workspaceEditorSaved: true,
                    workspaceEditorFrom: location.key,
                    reviewNotice: { message, warning: Boolean(warning) },
                },
            });
        } catch (cause) {
            setStale(needsReload(cause));
            setSaveError(errorText(cause, 'The review could not be saved.'));
            setSaving(false);
        }
    };

    const panelId = `${ids}-ask-ai`;
    const reload = stale ? (
        <GlassButton type="button" variant="subtle" onClick={() => setAttempt((value) => value + 1)} data-testid="v2-feedback-editor-reload">
            <RotateCcw size={15} aria-hidden="true" /> Reload
        </GlassButton>
    ) : null;

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
            onDiscard={() => {
                setDraft(initial);
                setApplied(null);
            }}
            saveLabel="Save review"
            actions={aiAvailable || reload ? (
                <>
                    {aiAvailable ? (
                        <ReviewAskAiToggle open={assistOpen} controls={panelId} onToggle={() => setAssistOpen((value) => !value)} />
                    ) : null}
                    {reload}
                </>
            ) : undefined}
            aiChangedSections={markedGroups.length ? new Set(['review']) : undefined}
            sidePanelOpen={aiAvailable && assistOpen}
            sidePanel={aiAvailable ? (
                <ReviewAskAiPanel
                    id={panelId}
                    section="feedback"
                    recordId={record.id}
                    saved={savedSuggestion}
                    describe={(suggestion) => feedbackSuggestionChanges(record, (suggestion as FeedbackSuggestion).payload)}
                    notesFor={(suggestion) => archiveNote(suggestion, record)}
                    locked={saving}
                    applied={markedGroups.length && applied
                        ? { source: applied.source, labels: markedGroups.map((group) => group.label) }
                        : null}
                    undoReport={undoReport}
                    onApply={applySuggestion}
                    onUndo={undoSuggestion}
                    onClose={() => setAssistOpen(false)}
                />
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
                            <div className={clsx('rounded-xl', marked('acknowledged') && AI_MARK_CLASS)}>
                                <EditorSwitch
                                    checked={current.acknowledged}
                                    onChange={(value) => update({ acknowledged: value })}
                                    label="Acknowledged"
                                    description="Marks the feedback as reviewed, so it leaves the queue of feedback awaiting review."
                                />
                            </div>
                            <EditorFieldRow
                                htmlFor={`${ids}-theme`}
                                label="Theme"
                                width="standard"
                                help="What the feedback is about. The Feedback dashboard counts feedback by theme."
                            >
                                <select
                                    id={`${ids}-theme`}
                                    value={current.theme}
                                    onChange={(event) => update({ theme: event.target.value })}
                                    className={clsx(TEXTAREA_CLASS, marked('theme') && AI_MARK_CLASS)}
                                    data-testid="v2-feedback-editor-theme"
                                >
                                    <option value="">Not classified</option>
                                    {FEEDBACK_THEMES.map((theme) => <option key={theme} value={theme}>{FEEDBACK_THEME_LABELS[theme]}</option>)}
                                </select>
                            </EditorFieldRow>
                            <EditorFieldRow htmlFor={`${ids}-analysis`} label="Analysis notes" help="For reviewers only; the user never sees these.">
                                <textarea
                                    id={`${ids}-analysis`}
                                    rows={4}
                                    maxLength={8000}
                                    value={current.analysisNotes}
                                    onChange={(event) => update({ analysisNotes: event.target.value })}
                                    className={clsx(TEXTAREA_CLASS, marked('analysisNotes') && AI_MARK_CLASS)}
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
                                    className={clsx(TEXTAREA_CLASS, marked('actionTaken') && AI_MARK_CLASS)}
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
                                    className={clsx(TEXTAREA_CLASS, marked('responseToUser') && AI_MARK_CLASS)}
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
