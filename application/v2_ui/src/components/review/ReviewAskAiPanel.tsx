// ReviewAskAiPanel.tsx
// The Ask AI side panel for the Review center's record editors: analyze the record, read the
// suggested review and why the AI suggests it, and apply it to the unsaved draft, where each field
// it changed is marked and can be undone. A suggestion stored by AI triage is offered the same way.
//
// Nothing here saves. Applying only fills the draft; the reviewer reads it, changes what they want
// and saves through the editor's normal save. Every string can come from the model or the server,
// so all of it renders as React text: nothing reaches an HTML sink and nothing is parsed as Markdown.

import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Loader2, RotateCcw, Sparkles, X } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { WorkflowAssistElapsed } from '../workflows/WorkflowAskAiTab';
import type { ReviewSectionId } from '../../lib/reviewAccess';
import { postReviewAssist } from '../../lib/reviewAssistApi';
import { formatReviewDate } from '../../lib/reviewCenter';
import type {
    AnySuggestion,
    ReviewAssistFailure,
    ReviewAssistResult,
    SuggestionChange,
} from '../../lib/reviewSuggestions';
import { ToneBadge } from './ReviewParts';

export type AskAiSource = 'saved' | 'analysis';

export interface ReviewAskAiApplied {
    source: AskAiSource;
    /** The labels of the draft fields the suggestion changed. */
    labels: string[];
}

type Analysis =
    | { state: 'idle' }
    | { state: 'running'; startedAt: number; controller: AbortController }
    | { state: 'done'; result: ReviewAssistResult }
    | { state: 'failed'; failure: ReviewAssistFailure };

const CONFIDENCE_LABELS = { low: 'Low confidence', medium: 'Medium confidence', high: 'High confidence' } as const;

function SuggestionCard({
    heading,
    suggestion,
    changes,
    notes,
    applyLabel,
    disabled,
    onApply,
    testId,
}: {
    heading: string;
    suggestion: AnySuggestion;
    changes: readonly SuggestionChange[];
    notes: readonly string[];
    applyLabel: string;
    disabled: boolean;
    onApply: () => void;
    testId: string;
}) {
    return (
        <section aria-label={heading} data-testid={testId} className="space-y-2 rounded-xl border border-change-ai/40 bg-surface-1 p-3 text-xs">
            <div className="flex flex-wrap items-center gap-1.5">
                <h3 className="text-sm font-semibold text-text-1">{heading}</h3>
                {suggestion.confidence ? (
                    <ToneBadge tone={suggestion.confidence === 'high' ? 'ok' : suggestion.confidence === 'medium' ? 'info' : 'warn'}>
                        {CONFIDENCE_LABELS[suggestion.confidence]}
                    </ToneBadge>
                ) : null}
            </div>
            {changes.length ? (
                <ul aria-label="What it would change" className="space-y-1">
                    {changes.map((change) => (
                        <li key={change.field} className="break-words text-text-1">
                            <span className="font-medium">{change.label}</span>
                            {change.detail ? <span className="text-text-2">: {change.detail}</span> : null}
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="text-text-2">It would leave the review as it is.</p>
            )}
            {suggestion.rationale ? (
                <p className="break-words text-text-2">
                    <span className="font-medium text-text-1">Why: </span>
                    {suggestion.rationale}
                </p>
            ) : null}
            {notes.map((note) => <p key={note} className="text-text-3">{note}</p>)}
            <GlassButton type="button" size="sm" variant="subtle" disabled={disabled || !changes.length} onClick={onApply}
                data-testid={`${testId}-apply`}>
                <Sparkles size={14} aria-hidden="true" /> {applyLabel}
            </GlassButton>
        </section>
    );
}

/** The editor header button that opens the Ask AI panel. */
export function ReviewAskAiToggle({ open, controls, onToggle }: { open: boolean; controls: string; onToggle: () => void }) {
    return (
        <GlassButton type="button" variant="subtle" aria-expanded={open} aria-controls={open ? controls : undefined}
            onClick={onToggle} data-testid="v2-review-ask-ai-toggle">
            <Sparkles size={15} aria-hidden="true" /> Ask AI
        </GlassButton>
    );
}

export function ReviewAskAiPanel({
    id,
    section,
    recordId,
    saved,
    describe,
    notesFor,
    locked,
    lockedReason,
    applied,
    undoReport,
    onApply,
    onUndo,
    onClose,
}: {
    id: string;
    section: ReviewSectionId;
    recordId: string;
    /** The record's suggestion from AI triage, in whatever state it is, or null. */
    saved: AnySuggestion | null;
    /** What a suggestion would change in the stored review. */
    describe: (suggestion: AnySuggestion) => SuggestionChange[];
    /** Anything the reviewer should know that applying can't do, such as archiving. */
    notesFor: (suggestion: AnySuggestion) => string[];
    /** The draft can't take changes now, such as a violation held by a request or a save in progress. */
    locked: boolean;
    lockedReason?: string;
    applied: ReviewAskAiApplied | null;
    undoReport: string | null;
    onApply: (suggestion: AnySuggestion, source: AskAiSource) => void;
    onUndo: () => void;
    onClose: () => void;
}) {
    const [analysis, setAnalysis] = useState<Analysis>({ state: 'idle' });
    const running = analysis.state === 'running' ? analysis : null;
    const statusRef = useRef<HTMLDivElement>(null);

    // Leaving the editor cancels a request still in flight.
    useEffect(() => () => {
        if (running) running.controller.abort();
    }, [running]);

    const analyze = async () => {
        const controller = new AbortController();
        setAnalysis({ state: 'running', startedAt: Date.now(), controller });
        const answer = await postReviewAssist(section, 'analyze', [recordId], controller.signal);
        if (answer.ok) setAnalysis({ state: 'done', result: answer.results[0] });
        else if ('failure' in answer) setAnalysis({ state: 'failed', failure: answer.failure });
        else setAnalysis({ state: 'idle' });
        requestAnimationFrame(() => statusRef.current?.focus());
    };

    const savedPending = saved && saved.status === 'pending' ? saved : null;
    const result = analysis.state === 'done' ? analysis.result : null;
    const analyzed = result?.outcome === 'suggested' ? result.suggestion : null;

    return (
        <aside id={id} aria-label="Ask AI" data-testid="v2-review-ask-ai"
            className="flex min-h-0 w-full flex-1 flex-col border-edge bg-surface-0 xl:w-[400px] xl:flex-none xl:border-l">
            <div className="flex shrink-0 items-center gap-2 border-b border-edge px-3 py-2">
                <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-change-ai-soft text-change-ai">
                    <Sparkles size={14} aria-hidden="true" />
                </span>
                <h2 className="flex-1 text-sm font-semibold text-text-1">Ask AI</h2>
                <button type="button" aria-label="Close Ask AI" onClick={onClose}
                    className="rounded-md p-1 text-text-3 hover:bg-surface-2 hover:text-text-1">
                    <X size={14} aria-hidden="true" />
                </button>
            </div>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
                <p className="text-xs text-text-3">
                    AI suggestions are a starting point, and can be wrong. Check every field it fills in: nothing is
                    saved, sent or requested until you save the review yourself.
                </p>

                {locked && lockedReason ? (
                    <p className="rounded-lg bg-surface-2 p-2 text-xs text-text-2" data-testid="v2-review-ask-ai-locked">{lockedReason}</p>
                ) : null}

                {applied ? (
                    <div role="status" className="space-y-1.5 rounded-xl border border-change-ai/40 bg-change-ai-soft p-3 text-xs text-text-1"
                        data-testid="v2-review-ask-ai-applied">
                        <p className="font-medium">
                            Applied to your draft: {applied.labels.join(', ')}. Review the marked fields, then save.
                        </p>
                        {applied.source === 'saved' ? (
                            <p className="text-text-2">Saving records that you applied this AI suggestion.</p>
                        ) : null}
                        <button type="button" onClick={onUndo} disabled={locked}
                            className="inline-flex items-center gap-1 rounded-lg px-1 py-0.5 font-medium text-accent hover:bg-surface-1 disabled:opacity-50"
                            data-testid="v2-review-ask-ai-undo">
                            <RotateCcw size={12} aria-hidden="true" /> Undo
                        </button>
                    </div>
                ) : null}
                {undoReport ? <p role="status" className="text-xs text-text-2" data-testid="v2-review-ask-ai-undone">{undoReport}</p> : null}

                {savedPending ? (
                    <SuggestionCard
                        heading="Suggestion from AI triage"
                        suggestion={savedPending}
                        changes={describe(savedPending)}
                        notes={[
                            ...notesFor(savedPending),
                            savedPending.createdBy || savedPending.createdAt
                                ? `Asked for by ${savedPending.createdBy || 'a reviewer'} ${formatReviewDate(savedPending.createdAt)}.`
                                : '',
                        ].filter(Boolean)}
                        applyLabel="Apply to draft"
                        disabled={locked || Boolean(running)}
                        onApply={() => onApply(savedPending, 'saved')}
                        testId="v2-review-ask-ai-saved"
                    />
                ) : saved?.status === 'stale' ? (
                    <p className="rounded-lg bg-warn-soft p-2 text-xs text-text-1" data-testid="v2-review-ask-ai-stale">
                        AI triage suggested a review earlier, but this record has changed since, so that suggestion no
                        longer fits. Analyze it again for a current one.
                    </p>
                ) : null}

                <div className="flex flex-wrap items-center gap-2">
                    <GlassButton type="button" size="sm" variant="primary" onClick={() => void analyze()}
                        disabled={locked || Boolean(running)} data-testid="v2-review-ask-ai-analyze">
                        {running ? <Loader2 size={14} aria-hidden="true" className="animate-spin" /> : <Sparkles size={14} aria-hidden="true" />}
                        {analysis.state === 'idle' || running ? 'Analyze this record' : 'Analyze again'}
                    </GlassButton>
                    {running ? (
                        <>
                            <WorkflowAssistElapsed startedAt={running.startedAt} testId="v2-review-ask-ai-elapsed" />
                            <GlassButton type="button" size="sm" variant="ghost" onClick={() => running.controller.abort()}>
                                Cancel
                            </GlassButton>
                        </>
                    ) : null}
                </div>

                <div ref={statusRef} tabIndex={-1} role="status" aria-live="polite" className="space-y-2 focus:outline-none">
                    {running ? <p className="text-xs text-text-2">Analyzing the record. This can take up to a minute.</p> : null}
                    {analysis.state === 'failed' ? (
                        <p className="flex items-start gap-1.5 rounded-lg bg-danger-soft p-2 text-xs text-text-1" data-testid="v2-review-ask-ai-error">
                            <AlertTriangle size={12} aria-hidden="true" className="mt-0.5 shrink-0 text-danger" />
                            <span className="min-w-0 flex-1 break-words">
                                {analysis.failure.message}
                                {analysis.failure.retryAfterSeconds ? ` Try again in ${analysis.failure.retryAfterSeconds} s.` : ''}
                            </span>
                        </p>
                    ) : null}
                    {result && !analyzed ? (
                        <p className="rounded-lg bg-warn-soft p-2 text-xs text-text-1" data-testid="v2-review-ask-ai-outcome">
                            {result.message || 'No suggestion was made. Review this record yourself.'}
                        </p>
                    ) : null}
                </div>

                {analyzed ? (
                    <SuggestionCard
                        heading="Suggested review"
                        suggestion={analyzed}
                        changes={describe(analyzed)}
                        notes={notesFor(analyzed)}
                        applyLabel="Apply to draft"
                        disabled={locked || Boolean(running)}
                        onApply={() => onApply(analyzed, 'analysis')}
                        testId="v2-review-ask-ai-suggestion"
                    />
                ) : null}
            </div>
        </aside>
    );
}
