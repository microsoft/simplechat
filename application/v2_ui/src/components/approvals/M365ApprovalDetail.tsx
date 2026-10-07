// M365ApprovalDetail.tsx
// The right-hand pane for one Microsoft 365 data-user approval.
//
// Mirrors the classic chat-m365-approvals dialog: the server decides who may approve or
// deny, which sharing durations a source allows, and whether a Run as review is complete.
// This pane only renders those facts and posts the user's choice back. Approval records a
// decision; it never means the work already ran.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { Loader2, RefreshCw } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import {
    ANALYSIS_CHOICE_LABELS,
    M365_SOURCE_LABELS,
    SHARING_DURATION_LABELS,
    analysisCounts,
    canDecideM365,
    decideM365Approval,
    describeM365Status,
    errorMessage,
    fetchM365Approval,
    formatDateTime,
    isValidTimezone,
    requestTypeLabel,
    runAsReview,
    sharingChoices,
    type M365Approval,
    type M365DecisionPayload,
    type SharingDuration,
} from '../../lib/approvalsApi';
import { toast } from '../../stores/toastStore';
import { GlassButton, Skeleton } from '../ui/primitives';
import { DetailEmpty, DetailShell, Fact, Facts, Notice, StatusBadge, fieldClass } from './ApprovalParts';

const SHARING_WARNING = [
    'You are publishing Microsoft 365 information to other conversation participants. Email and Calendar may contain personal information. OneDrive and SharePoint Online (SPO) may contain material participants cannot access at its source.',
    "Allowing sharing publishes the entire retained source-evidence snapshot, as well as generated answers, with the conversation's history. Participants can reuse that published snapshot without their own source access. Fresh searches and reads still require the data user's Microsoft 365 permissions. Revoking permission later does not retract already-published history or evidence.",
];
const TIMEZONE_HELP =
    'Today ends at your next local midnight. The server records this timezone and calculates expiry, including daylight-saving changes. A stricter action can require a new acknowledgement sooner.';
const SAVED_NOTICE = 'Decisions saved. Execution may be queued or require sign-in; approval is not execution success.';

function defaultTimezone(): string {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || '';
    } catch {
        return '';
    }
}

function contextText(approval: M365Approval, key: string): string {
    const value = approval.context?.[key];
    return typeof value === 'string' ? value : '';
}

function sourceList(approval: M365Approval): string {
    const sources = Object.keys(approval.sources ?? {});
    return sources.map((source) => M365_SOURCE_LABELS[source] ?? source).join(', ');
}

function ChoiceButton({
    pressed,
    onClick,
    disabled,
    children,
    testId,
}: {
    pressed: boolean;
    onClick: () => void;
    disabled?: boolean;
    children: string;
    testId?: string;
}) {
    return (
        <button
            type="button"
            aria-pressed={pressed}
            disabled={disabled}
            onClick={onClick}
            data-testid={testId}
            className={clsx(
                'rounded-xl border px-3 py-2 text-sm transition-colors disabled:opacity-50',
                pressed
                    ? 'border-accent bg-accent-soft font-semibold text-accent'
                    : 'border-edge bg-surface-1 text-text-1 hover:bg-surface-2',
            )}
        >
            {children}
        </button>
    );
}

export function M365ApprovalDetail({ approvalId, onChanged }: { approvalId: string; onChanged: () => void }) {
    const [approval, setApproval] = useState<M365Approval | null>(null);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState('');
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState('');
    const [savedNotice, setSavedNotice] = useState('');
    const [sharing, setSharing] = useState<Record<string, SharingDuration>>({});
    const [timezone, setTimezone] = useState(defaultTimezone);
    const [choice, setChoice] = useState('');

    const load = useCallback(
        async (signal?: AbortSignal) => {
            setLoading(true);
            setLoadError('');
            try {
                const next = await fetchM365Approval(approvalId, signal);
                setApproval(next);
                setSharing({});
                setChoice('');
            } catch (error) {
                if (signal?.aborted) return;
                setApproval(null);
                setLoadError(errorMessage(error, 'The Microsoft 365 approval could not be opened.'));
            } finally {
                if (!signal?.aborted) setLoading(false);
            }
        },
        [approvalId],
    );

    useEffect(() => {
        const controller = new AbortController();
        setSavedNotice('');
        setSaveError('');
        void load(controller.signal);
        return () => controller.abort();
    }, [load]);

    if (loading && !approval) {
        return (
            <div className="space-y-3 p-6" aria-busy="true">
                <Skeleton className="h-6 w-1/2" />
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-24 w-full" />
            </div>
        );
    }
    if (!approval) {
        return (
            <div className="p-6">
                <Notice tone="danger" testId="v2-m365-approval-error">
                    {loadError || 'The Microsoft 365 approval could not be opened.'}
                </Notice>
            </div>
        );
    }

    const submit = async (payload: M365DecisionPayload) => {
        setSaving(true);
        setSaveError('');
        setSavedNotice('');
        try {
            const saved = await decideM365Approval(approval.id, payload);
            setApproval(saved);
            setSavedNotice(SAVED_NOTICE);
            toast.success('Decision saved.');
            onChanged();
        } catch (error) {
            setSaveError(errorMessage(error, 'The decision could not be saved.'));
            if (error instanceof ApiError && error.status === 409) {
                await load();
            }
        } finally {
            setSaving(false);
        }
    };

    return (
        <DetailShell
            title={requestTypeLabel(approval.request_type)}
            subtitle={describeM365Status(approval)}
            badge={<StatusBadge status={approval.status} />}
        >
            <div className="flex justify-end">
                <GlassButton size="sm" variant="ghost" onClick={() => void load()} disabled={loading || saving}>
                    {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                    Refresh
                </GlassButton>
            </div>
            <Facts>
                <Fact label="Reason">{approval.reason}</Fact>
                <Fact label="Workflow">{contextText(approval, 'workflow_id')}</Fact>
                <Fact label="Conversation">{contextText(approval, 'conversation_id')}</Fact>
                <Fact label="Requested">{formatDateTime(approval.created_at)}</Fact>
                <Fact label="Request expires">{formatDateTime(approval.expires_at)}</Fact>
            </Facts>
            {savedNotice ? <Notice tone="ok" testId="v2-m365-approval-saved">{savedNotice}</Notice> : null}
            {saveError ? <Notice tone="danger" testId="v2-m365-approval-save-error">{saveError}</Notice> : null}
            {canDecideM365(approval) ? (
                <DecisionForm
                    approval={approval}
                    saving={saving}
                    sharing={sharing}
                    setSharing={setSharing}
                    timezone={timezone}
                    setTimezone={setTimezone}
                    choice={choice}
                    setChoice={setChoice}
                    onSubmit={submit}
                />
            ) : (
                <ReadOnlyDecision approval={approval} />
            )}
        </DetailShell>
    );
}

function ReadOnlyDecision({ approval }: { approval: M365Approval }) {
    const decisions = Object.entries(approval.decisions ?? {});
    return (
        <div className="space-y-3" data-testid="v2-m365-approval-readonly">
            <Notice tone={approval.status === 'pending' ? 'warn' : 'info'}>
                {approval.status === 'pending'
                    ? 'This request is not actionable by your account.'
                    : 'This saved decision is read-only. Approval does not mean execution has completed.'}
            </Notice>
            {decisions.length || approval.analysis_choice ? (
                <Facts>
                    {decisions.map(([source, decision]) => (
                        <Fact key={source} label={M365_SOURCE_LABELS[source] ?? source}>
                            {[
                                SHARING_DURATION_LABELS[decision?.duration as SharingDuration] ?? decision?.duration ?? 'Not reported',
                                decision?.expires_at ? `expires ${formatDateTime(decision.expires_at)}` : '',
                            ]
                                .filter(Boolean)
                                .join(' · ')}
                        </Fact>
                    ))}
                    <Fact label="Recorded analysis choice">
                        {approval.analysis_choice
                            ? ANALYSIS_CHOICE_LABELS[approval.analysis_choice] ?? approval.analysis_choice
                            : ''}
                    </Fact>
                </Facts>
            ) : null}
        </div>
    );
}

function DecisionForm({
    approval,
    saving,
    sharing,
    setSharing,
    timezone,
    setTimezone,
    choice,
    setChoice,
    onSubmit,
}: {
    approval: M365Approval;
    saving: boolean;
    sharing: Record<string, SharingDuration>;
    setSharing: (next: Record<string, SharingDuration>) => void;
    timezone: string;
    setTimezone: (value: string) => void;
    choice: string;
    setChoice: (value: string) => void;
    onSubmit: (payload: M365DecisionPayload) => Promise<void>;
}) {
    if (approval.request_type === 'm365_source_sharing') {
        return (
            <SharingForm
                approval={approval}
                saving={saving}
                sharing={sharing}
                setSharing={setSharing}
                timezone={timezone}
                setTimezone={setTimezone}
                onSubmit={onSubmit}
            />
        );
    }
    if (approval.request_type === 'm365_extended_analysis') {
        return <AnalysisForm approval={approval} saving={saving} choice={choice} setChoice={setChoice} onSubmit={onSubmit} />;
    }
    return <RunAsForm approval={approval} saving={saving} choice={choice} setChoice={setChoice} onSubmit={onSubmit} />;
}

function SharingForm({
    approval,
    saving,
    sharing,
    setSharing,
    timezone,
    setTimezone,
    onSubmit,
}: {
    approval: M365Approval;
    saving: boolean;
    sharing: Record<string, SharingDuration>;
    setSharing: (next: Record<string, SharingDuration>) => void;
    timezone: string;
    setTimezone: (value: string) => void;
    onSubmit: (payload: M365DecisionPayload) => Promise<void>;
}) {
    const plan = useMemo(() => {
        if (approval.context?.shared !== true) {
            return { error: 'This sharing request does not describe a shared conversation. Refresh before deciding.' };
        }
        const sources = Object.keys(approval.sources ?? {});
        if (!sources.length) {
            return { error: 'This sharing request does not list any sources. Refresh before deciding.' };
        }
        try {
            return { sources: sources.map((source) => ({ source, choices: sharingChoices(approval, source) })) };
        } catch (error) {
            return { error: errorMessage(error, 'The sharing request could not be verified.') };
        }
    }, [approval]);

    if ('error' in plan) {
        return <Notice tone="danger">{plan.error}</Notice>;
    }
    const needsTimezone = Object.values(sharing).includes('today');
    const complete = plan.sources.every(({ source }) => Boolean(sharing[source]));
    const timezoneValid = !needsTimezone || isValidTimezone(timezone);

    const save = () => {
        const decisions: Record<string, { duration: SharingDuration; timezone?: string }> = {};
        for (const { source } of plan.sources) {
            const duration = sharing[source];
            decisions[source] = duration === 'today' ? { duration, timezone: timezone.trim() } : { duration };
        }
        void onSubmit({ decisions });
    };

    return (
        <div className="space-y-4" data-testid="v2-m365-sharing-form">
            <Notice tone="warn">
                {SHARING_WARNING.map((paragraph) => (
                    <p key={paragraph.slice(0, 24)} className="[&+p]:mt-2">
                        {paragraph}
                    </p>
                ))}
            </Notice>
            {plan.sources.map(({ source, choices }) => (
                <fieldset key={source} className="space-y-2 rounded-xl border border-edge p-3">
                    <legend className="px-1 text-sm font-semibold text-text-1">{M365_SOURCE_LABELS[source]}</legend>
                    <p className="text-xs text-text-3">No continues without this source. Other agent capabilities remain available.</p>
                    {choices.length ? (
                        <div className="flex flex-wrap gap-2" role="group" aria-label={`${M365_SOURCE_LABELS[source]} sharing`}>
                            {choices.map((duration) => (
                                <ChoiceButton
                                    key={duration}
                                    pressed={sharing[source] === duration}
                                    disabled={saving}
                                    testId={`v2-m365-sharing-${source}-${duration}`}
                                    onClick={() => setSharing({ ...sharing, [source]: duration })}
                                >
                                    {SHARING_DURATION_LABELS[duration]}
                                </ChoiceButton>
                            ))}
                        </div>
                    ) : (
                        <p className="text-sm text-text-2">Your account cannot choose an option for this source.</p>
                    )}
                </fieldset>
            ))}
            {needsTimezone ? (
                <label className="block space-y-1 text-sm">
                    <span className="font-medium text-text-1">Your timezone</span>
                    <input
                        className={fieldClass}
                        value={timezone}
                        disabled={saving}
                        onChange={(event) => setTimezone(event.target.value)}
                        aria-invalid={!timezoneValid}
                        data-testid="v2-m365-sharing-timezone"
                    />
                    <span className="block text-xs text-text-3">{TIMEZONE_HELP}</span>
                    {!timezoneValid ? <span className="block text-xs text-danger">Enter a valid IANA timezone, such as America/New_York.</span> : null}
                </label>
            ) : null}
            <div className="flex justify-end">
                <GlassButton
                    variant="primary"
                    disabled={saving || !complete || !timezoneValid}
                    onClick={save}
                    data-testid="v2-m365-approval-save"
                >
                    {saving ? <Loader2 size={14} className="animate-spin" /> : null}
                    Save decisions
                </GlassButton>
            </div>
        </div>
    );
}

function AnalysisForm({
    approval,
    saving,
    choice,
    setChoice,
    onSubmit,
}: {
    approval: M365Approval;
    saving: boolean;
    choice: string;
    setChoice: (value: string) => void;
    onSubmit: (payload: M365DecisionPayload) => Promise<void>;
}) {
    const counts = useMemo(() => {
        try {
            return { counts: analysisCounts(approval) };
        } catch (error) {
            return { error: errorMessage(error, 'The requested analysis counts could not be verified.') };
        }
    }, [approval]);
    if ('error' in counts) return <Notice tone="danger">{counts.error}</Notice>;
    const choices = [
        ...(approval.can_deny === true ? ['fast'] : []),
        ...(approval.can_approve === true ? ['request', 'always'] : []),
    ];
    return (
        <div className="space-y-4" data-testid="v2-m365-analysis-form">
            <Facts>
                <Fact label="Sources">{sourceList(approval)}</Fact>
                {counts.counts.map(([label, value]) => (
                    <Fact key={label} label={label}>
                        {value.toLocaleString()}
                    </Fact>
                ))}
            </Facts>
            <p className="text-sm text-text-2">
                A faster answer uses the available evidence and explains what was not covered. Deeper analysis remains subject to service limits.
            </p>
            <ChoiceGroup label="Analysis choice" choices={choices} labels={ANALYSIS_CHOICE_LABELS} value={choice} onChange={setChoice} disabled={saving} />
            <SaveChoice saving={saving} disabled={!choice} onSave={() => void onSubmit({ choice })} />
        </div>
    );
}

const RUN_AS_LABELS: Record<string, string> = { deny: 'No', approve: 'Allow this workflow revision' };

function RunAsForm({
    approval,
    saving,
    choice,
    setChoice,
    onSubmit,
}: {
    approval: M365Approval;
    saving: boolean;
    choice: string;
    setChoice: (value: string) => void;
    onSubmit: (payload: M365DecisionPayload) => Promise<void>;
}) {
    const review = runAsReview(approval);
    const choices = [
        ...(approval.can_deny === true ? ['deny'] : []),
        ...(approval.can_approve === true && review ? ['approve'] : []),
    ];
    return (
        <div className="space-y-4" data-testid="v2-m365-run-as-form">
            <p className="text-sm text-text-2">
                This authorizes only this workflow revision and its sources, instructions, inputs, schedule, and destinations.
                Changes require renewed authorization. A connected account alone is not approval.
            </p>
            <Facts>
                <Fact label="Sources">{sourceList(approval)}</Fact>
                            </Facts>
            {review ? (
                <section className="space-y-3">
                    <h3 className="text-sm font-semibold text-text-1">Workflow revision to authorize</h3>
                    {review.map(([label, value]) => (
                        <div key={label}>
                            <p className="text-xs font-medium tracking-wide text-text-3 uppercase">{label}</p>
                            <p className="mt-1 rounded-xl bg-surface-2 p-3 text-sm whitespace-pre-wrap text-text-1">{value}</p>
                        </div>
                    ))}
                </section>
            ) : (
                <Notice tone="warn">
                    The workflow revision details are unavailable. Approval is disabled until the server supplies the instructions,
                    inputs, schedule, and destinations to review. You can still choose No.
                </Notice>
            )}
            <ChoiceGroup label="Workflow Run as decision" choices={choices} labels={RUN_AS_LABELS} value={choice} onChange={setChoice} disabled={saving} />
            <SaveChoice saving={saving} disabled={!choice} onSave={() => void onSubmit({ choice })} />
        </div>
    );
}

function ChoiceGroup({
    label,
    choices,
    labels,
    value,
    onChange,
    disabled,
}: {
    label: string;
    choices: string[];
    labels: Record<string, string>;
    value: string;
    onChange: (value: string) => void;
    disabled: boolean;
}) {
    if (!choices.length) return <p className="text-sm text-text-2">Your account cannot choose an option for this request.</p>;
    return (
        <div className="flex flex-wrap gap-2" role="group" aria-label={label}>
            {choices.map((option) => (
                <ChoiceButton
                    key={option}
                    pressed={value === option}
                    disabled={disabled}
                    testId={`v2-m365-choice-${option}`}
                    onClick={() => onChange(option)}
                >
                    {labels[option] ?? option}
                </ChoiceButton>
            ))}
        </div>
    );
}

function SaveChoice({ saving, disabled, onSave }: { saving: boolean; disabled: boolean; onSave: () => void }) {
    return (
        <div className="flex justify-end">
            <GlassButton variant="primary" disabled={saving || disabled} onClick={onSave} data-testid="v2-m365-approval-save">
                {saving ? <Loader2 size={14} className="animate-spin" /> : null}
                Save decision
            </GlassButton>
        </div>
    );
}

export function M365ApprovalPlaceholder() {
    return <DetailEmpty title="Select a request" description="Choose a request from the list to review it here." />;
}
