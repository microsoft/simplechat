// M365ApprovalInlineCard.tsx
// The Microsoft 365 approval a stopped plan step is waiting on, decided in the conversation.
//
// A plan step that has to read more of a SharePoint or OneDrive file than a quick read covers
// stops for the user's extended-analysis approval. Before this card, the user had to leave for
// Approvals, decide there, come back and retry. Here the same decision is posted to the same
// approvals API, and choosing an option continues the plan: the retry reuses every completed
// step and runs only the work that stopped. The server still decides who may approve, and the
// retry is matched to this approval by the step's stable request id.

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import {
    canDecideM365,
    decideM365Approval,
    errorMessage,
    fetchM365Approval,
    type M365Approval,
} from '../../lib/approvalsApi';
import { M365_APPROVALS_HREF } from '../../lib/m365Connect';

const SOURCE_NAMES: Record<string, string> = {
    calendar: 'Calendar',
    email: 'Email',
    onedrive: 'OneDrive',
    spo: 'SharePoint',
};

/** Where the personal "Extended analysis" preference for each file source is saved. */
const PREFERENCES_PATH = '/settings?tab=preferences';

type Phase = 'loading' | 'ready' | 'saving' | 'continuing' | 'unavailable';

function sourceName(approval: M365Approval): string {
    const sources = Object.keys(approval.sources ?? {});
    return sources.length === 1 ? SOURCE_NAMES[sources[0]] ?? 'Microsoft 365' : 'Microsoft 365';
}

/** A proposal count the server recorded, or null when it is missing or not a safe count. */
function proposalCount(approval: M365Approval, key: string): number | null {
    const value = approval.proposal?.[key];
    return typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : null;
}

function formatBytes(bytes: number): string {
    const megabytes = bytes / (1024 * 1024);
    return megabytes >= 1 ? `${megabytes.toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** Why the step stopped, in the user's terms, from the counts the approval recorded. */
function readingSummary(approval: M365Approval): string {
    const tokens = proposalCount(approval, 'context_tokens');
    const files = proposalCount(approval, 'file_count');
    const bytes = proposalCount(approval, 'total_bytes');
    const parts: string[] = [];
    if (tokens) parts.push(`about ${tokens.toLocaleString()} tokens of file content`);
    if (files) parts.push(`${files.toLocaleString()} ${files === 1 ? 'file' : 'files'}`);
    if (bytes) parts.push(formatBytes(bytes));
    const detail = parts.length ? ` (${parts.join(', ')})` : '';
    return `To answer, this step needs to read more${detail} than a quick read covers.`;
}

function savedChoice(approval: M365Approval, source: string): string {
    if (approval.analysis_choice === 'always') return `Deeper reads are always allowed for ${source}.`;
    if (approval.analysis_choice === 'fast') return 'A quick read was chosen for this request.';
    if (approval.analysis_choice === 'request' || approval.status === 'approved') {
        return 'A deeper read was allowed for this request.';
    }
    return 'Your choice for this request is saved.';
}

export function M365ApprovalInlineCard({
    approvalId,
    stepTitle,
    canContinue,
    continuing,
    onContinue,
}: {
    approvalId: string;
    /** The plan step that stopped, for the card's explanation. */
    stepTitle?: string;
    /** Whether the stopped attempt can be continued now. */
    canContinue: boolean;
    /** True while a retry is being prepared or the conversation is busy. */
    continuing: boolean;
    /** Continue the plan from the step that stopped. */
    onContinue: () => Promise<void> | void;
}) {
    const [approval, setApproval] = useState<M365Approval | null>(null);
    const [phase, setPhase] = useState<Phase>('loading');
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        setPhase('loading');
        setError(null);
        fetchM365Approval(approvalId, controller.signal).then(
            (next) => {
                if (controller.signal.aborted) return;
                setApproval(next);
                setPhase('ready');
            },
            () => {
                if (!controller.signal.aborted) setPhase('unavailable');
            },
        );
        return () => controller.abort();
    }, [approvalId]);

    const proceed = async () => {
        setPhase('continuing');
        try {
            await onContinue();
        } finally {
            setPhase('ready');
        }
    };

    const choose = async (choice: 'request' | 'always' | 'fast') => {
        setError(null);
        setPhase('saving');
        try {
            setApproval(await decideM365Approval(approvalId, { choice }));
        } catch (cause) {
            setError(errorMessage(cause, 'Your choice could not be saved. Try again, or decide it in Approvals.'));
            setPhase('ready');
            return;
        }
        if (canContinue) {
            await proceed();
        } else {
            setPhase('ready');
        }
    };

    const approvalsLink = (
        <a href={M365_APPROVALS_HREF} className="font-medium text-accent underline underline-offset-2">
            Review the Microsoft 365 approval
        </a>
    );

    if (phase === 'loading') {
        return (
            <p role="status" className="flex items-center gap-2 text-text-3">
                <Loader2 size={13} className="animate-spin" />
                Loading the Microsoft 365 approval...
            </p>
        );
    }

    if (phase === 'unavailable' || !approval || approval.request_type !== 'm365_extended_analysis') {
        // Another kind of approval, or one this card can't open: decide it in Approvals.
        return (
            <div aria-label="Microsoft 365 approval" className="space-y-2">
                <p>{approvalsLink}, then continue.</p>
                {canContinue ? (
                    <GlassButton size="sm" variant="subtle" disabled={continuing} onClick={() => void proceed()}>
                        Retry from failed step
                    </GlassButton>
                ) : null}
            </div>
        );
    }

    const source = sourceName(approval);
    const busy = phase === 'saving' || phase === 'continuing' || continuing;
    const pending = canDecideM365(approval);
    const decided = !pending && ['approved', 'denied', 'executed'].includes(String(approval.status));

    return (
        <section
            aria-label="Microsoft 365 approval"
            data-testid="v2-m365-inline-approval"
            className="space-y-2 rounded-lg border border-edge bg-surface-1 p-3 text-sm text-text-2"
        >
            <p className="font-medium text-text-1">
                {pending ? `${source} needs your OK to read more` : `${source} approval`}
            </p>
            {pending ? (
                <>
                    <p>
                        {stepTitle ? <><strong className="font-medium text-text-1">{stepTitle}</strong>: </> : null}
                        {readingSummary(approval)}
                    </p>
                    <div className="flex flex-wrap gap-2" role="group" aria-label={`${source} file reading`}>
                        {approval.can_approve === true ? (
                            <>
                                <GlassButton
                                    size="sm" variant="primary" disabled={busy}
                                    data-testid="v2-m365-inline-approval-request"
                                    onClick={() => void choose('request')}
                                >
                                    Allow this time
                                </GlassButton>
                                <GlassButton
                                    size="sm" variant="subtle" disabled={busy}
                                    data-testid="v2-m365-inline-approval-always"
                                    onClick={() => void choose('always')}
                                >
                                    Always allow for {source}
                                </GlassButton>
                            </>
                        ) : null}
                        {approval.can_deny === true ? (
                            <GlassButton
                                size="sm" variant="ghost" disabled={busy}
                                data-testid="v2-m365-inline-approval-fast"
                                onClick={() => void choose('fast')}
                            >
                                Quick read only
                            </GlassButton>
                        ) : null}
                    </div>
                    <p className="text-xs text-text-3">
                        A quick read answers from what fits and says what it left out. You can change this
                        any time in{' '}
                        <Link to={PREFERENCES_PATH} className="text-accent underline underline-offset-2">
                            Settings
                        </Link>
                        .
                    </p>
                </>
            ) : decided ? (
                <div className="flex flex-wrap items-center gap-2">
                    <span>{savedChoice(approval, source)}</span>
                    {canContinue ? (
                        <GlassButton
                            size="sm" variant="primary" disabled={busy}
                            data-testid="v2-m365-inline-approval-continue"
                            onClick={() => void proceed()}
                        >
                            Continue
                        </GlassButton>
                    ) : null}
                </div>
            ) : (
                <p>This approval is no longer pending. {approvalsLink} or ask again.</p>
            )}
            {busy ? (
                <p role="status" className="flex items-center gap-2 text-text-3">
                    <Loader2 size={13} className="animate-spin" />
                    {phase === 'saving' ? 'Saving your choice...' : 'Continuing the plan...'}
                </p>
            ) : null}
            {error ? <p role="alert" className="text-danger">{error}</p> : null}
        </section>
    );
}
