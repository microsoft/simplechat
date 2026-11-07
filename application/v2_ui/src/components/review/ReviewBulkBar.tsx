// ReviewBulkBar.tsx
// The bar a Review center workbench shows once records are checked: how many, the actions
// that apply to all of them, progress while they run, and what happened to each.
//
// Every bulk action reports per record. A batch that partly fails says which records were
// left unchanged and why, in the server's words, so the reviewer can act on each one
// rather than guess. The section supplies its own action buttons; this bar only frames
// them, which is where a later "Triage with AI" command joins the same bar.

import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { CheckCheck, Loader2, X } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import type { ReviewSectionId } from '../../lib/reviewAccess';
import { safeReviewViewHref, type ReviewView } from '../../lib/reviewCenter';
import { ReviewNotice } from './ReviewParts';

export interface BulkRunProgress {
    /** What is running, such as "Archiving". */
    label: string;
    done: number;
    total: number;
    /** More about where the run stands, such as a wait for the rate limit. */
    detail?: string;
}

export interface BulkRunReport {
    /** The sentence that leads the report, such as "Archived 18 of 20 violations." */
    summary: string;
    failures: { id: string; label: string; message: string }[];
    /** How the report reads; by default a warning when any record failed. */
    tone?: 'ok' | 'warn';
    /** Where to go next, such as the AI suggestions queue a triage filled. */
    link?: { label: string; section: ReviewSectionId; view: ReviewView };
}

export function ReviewBulkBar({
    count,
    summary,
    offerMatching,
    matchingBusy = false,
    onSelectMatching,
    onClear,
    actions,
    progress,
    onCancel,
    report,
    onDismissReport,
    testIdPrefix,
}: {
    /** How many records are checked. */
    count: number;
    /** The sentence describing what is checked. */
    summary: string;
    /** "Select all N matching", offered when the whole page is checked and more records match. */
    offerMatching?: { total: number; noun: string } | null;
    matchingBusy?: boolean;
    onSelectMatching?: () => void;
    onClear: () => void;
    actions: ReactNode;
    progress: BulkRunProgress | null;
    /** Offered while a run that can stop part way, such as a triage, is in progress. */
    onCancel?: () => void;
    report: BulkRunReport | null;
    onDismissReport: () => void;
    testIdPrefix: string;
}) {
    if (!count && !progress && !report) return null;
    return (
        <div className="space-y-2">
            {count || progress ? (
                <div
                    role="region"
                    aria-label="Bulk actions"
                    data-testid={`${testIdPrefix}-bulk-bar`}
                    className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-accent/40 bg-accent-soft px-3 py-2"
                >
                    <p aria-live="polite" className="flex min-w-0 items-center gap-1.5 text-sm font-medium text-text-1">
                        <CheckCheck size={15} aria-hidden="true" className="shrink-0 text-accent" />
                        <span data-testid={`${testIdPrefix}-bulk-summary`}>{summary}</span>
                    </p>
                    {offerMatching && onSelectMatching && !progress ? (
                        <button
                            type="button"
                            onClick={onSelectMatching}
                            disabled={matchingBusy}
                            data-testid={`${testIdPrefix}-select-matching`}
                            className="text-sm text-accent underline underline-offset-2 disabled:opacity-60"
                        >
                            {matchingBusy
                                ? 'Finding every match…'
                                : `Select all ${offerMatching.total.toLocaleString()} matching ${offerMatching.noun}`}
                        </button>
                    ) : null}
                    <div className="ml-auto flex flex-wrap items-center gap-2">
                        {progress ? (
                            <>
                                <p role="status" className="inline-flex items-center gap-1.5 text-sm text-text-2" data-testid={`${testIdPrefix}-bulk-progress`}>
                                    <Loader2 size={14} aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
                                    {progress.label} {Math.min(progress.done, progress.total).toLocaleString()} of {progress.total.toLocaleString()}…
                                    {progress.detail ? <span className="text-text-3"> {progress.detail}</span> : null}
                                </p>
                                {onCancel ? (
                                    <GlassButton type="button" size="sm" variant="ghost" onClick={onCancel} data-testid={`${testIdPrefix}-bulk-cancel`}>
                                        <X size={14} aria-hidden="true" /> Cancel
                                    </GlassButton>
                                ) : null}
                            </>
                        ) : (
                            <>
                                {actions}
                                <GlassButton type="button" size="sm" variant="ghost" onClick={onClear} data-testid={`${testIdPrefix}-bulk-clear`}>
                                    <X size={14} aria-hidden="true" /> Clear selection
                                </GlassButton>
                            </>
                        )}
                    </div>
                </div>
            ) : null}
            {report ? (
                <ReviewNotice tone={report.tone ?? (report.failures.length ? 'warn' : 'ok')} testId={`${testIdPrefix}-bulk-report`}>
                    <div className="flex items-start gap-2">
                        <div className="min-w-0 flex-1 space-y-1">
                            <p className="font-medium">{report.summary}</p>
                            {report.link ? (
                                <Link to={safeReviewViewHref(report.link.section, report.link.view)}
                                    className="text-sm text-accent underline underline-offset-2"
                                    data-testid={`${testIdPrefix}-bulk-report-link`}>
                                    {report.link.label}
                                </Link>
                            ) : null}
                            {report.failures.length ? (
                                <ul className="max-h-40 list-disc space-y-0.5 overflow-y-auto pl-5 text-xs">
                                    {report.failures.map((failure) => (
                                        <li key={failure.id}>
                                            <span className="font-medium">{failure.label}</span>: {failure.message}
                                        </li>
                                    ))}
                                </ul>
                            ) : null}
                        </div>
                        <button
                            type="button"
                            onClick={onDismissReport}
                            className="shrink-0 rounded-md p-0.5 text-text-2 hover:bg-surface-2 hover:text-text-1"
                        >
                            <X size={14} aria-hidden="true" />
                            <span className="sr-only">Dismiss</span>
                        </button>
                    </div>
                </ReviewNotice>
            ) : null}
        </div>
    );
}
