// PlanReplaySaveCard.tsx
// Lets the requester save one completed chat orchestration plan as a read-only personal workflow.

import { useCallback, useId, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { CalendarClock, ChevronDown, RefreshCw } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { WorkflowScheduleFields } from '../workflows/WorkflowScheduleFields';
import { workflowProposalLink } from '../../lib/workflowProposals';
import {
    fetchWorkflowEditorOptions,
    type WorkflowEditorOptions,
    type WorkflowSchedule,
    type WorkflowScope,
} from '../../lib/workflowEditor';
import {
    PLAN_REPLAY_ALERT_NOTICE,
    describePlanReplayTimeHandling,
    fetchPlanReplayPreview,
    planReplayError,
    planReplayRunTimeZone,
    savePlanReplayWorkflow,
    type PlanReplayPreview,
} from '../../lib/workflowPlanReplay';

const PERSONAL_SCOPE: WorkflowScope = { type: 'personal' };

function Detail({ term, children }: { term: string; children: ReactNode }) {
    return (
        <div className="min-w-0 sm:grid sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-3">
            <dt className="font-medium text-text-2">{term}</dt>
            <dd className="break-words text-text-1">{children}</dd>
        </div>
    );
}

function minimumCadenceText(seconds: number): string {
    const units: Array<[number, string, string]> = [
        [86400, 'day', 'days'],
        [3600, 'hour', 'hours'],
        [60, 'minute', 'minutes'],
    ];
    for (const [size, one, many] of units) {
        if (seconds >= size && seconds % size === 0) {
            const value = seconds / size;
            return `${value.toLocaleString()} ${value === 1 ? one : many}`;
        }
    }
    return `${seconds.toLocaleString()} ${seconds === 1 ? 'second' : 'seconds'}`;
}

function defaultSchedule(minimumSeconds: number): WorkflowSchedule {
    if (minimumSeconds <= 60) return { unit: 'minutes', value: 1 };
    if (minimumSeconds % 3600 === 0) return { unit: 'hours', value: Math.max(1, minimumSeconds / 3600) };
    if (minimumSeconds % 60 === 0) return { unit: 'minutes', value: Math.max(1, minimumSeconds / 60) };
    return { unit: 'seconds', value: minimumSeconds };
}

function defaultName(request: string): string {
    const trimmed = request.replace(/\s+/g, ' ').trim();
    if (!trimmed) return '';
    return trimmed.length > 72 ? `${trimmed.slice(0, 69).trimEnd()}…` : trimmed;
}

export function PlanReplaySaveCard({
    runId,
    conversationId,
}: {
    runId: string;
    conversationId: string;
}) {
    const panelId = useId();
    const [expanded, setExpanded] = useState(false);
    const [loading, setLoading] = useState(false);
    const [preview, setPreview] = useState<PlanReplayPreview | null>(null);
    const [options, setOptions] = useState<WorkflowEditorOptions | null>(null);
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [scheduled, setScheduled] = useState(false);
    const [schedule, setSchedule] = useState<WorkflowSchedule>({ unit: 'hours', value: 24 });
    const [enabled, setEnabled] = useState(false);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [errorCode, setErrorCode] = useState('');
    const [saved, setSaved] = useState<{ id: string; name: string; created: boolean; enabled: boolean } | null>(null);

    const load = useCallback(async () => {
        setExpanded(true);
        setLoading(true);
        setError('');
        setErrorCode('');
        setSaved(null);
        try {
            const [nextPreview, nextOptions] = await Promise.all([
                fetchPlanReplayPreview(runId, conversationId),
                fetchWorkflowEditorOptions(PERSONAL_SCOPE),
            ]);
            setPreview(nextPreview);
            setOptions(nextOptions);
            setName((current) => current || defaultName(nextPreview.request));
            setSchedule(defaultSchedule(nextPreview.min_interval_seconds));
        } catch (cause) {
            const replayError = planReplayError(cause);
            setError(replayError.text);
            setErrorCode(replayError.code);
        } finally {
            setLoading(false);
        }
    }, [conversationId, runId]);

    const save = async () => {
        if (!preview || saving) return;
        setSaving(true);
        setError('');
        setErrorCode('');
        try {
            const response = await savePlanReplayWorkflow(runId, {
                conversation_id: conversationId,
                plan_sha256: preview.plan_sha256,
                ...(name.trim() ? { name: name.trim() } : {}),
                ...(description.trim() ? { description: description.trim() } : {}),
                trigger_type: scheduled ? 'interval' : 'manual',
                ...(scheduled ? { schedule } : {}),
                enabled: scheduled && enabled,
            });
            const workflowName = typeof response.workflow.name === 'string' ? response.workflow.name : name;
            setSaved({
                id: String(response.workflow.id ?? ''),
                name: workflowName || 'Saved chat plan',
                created: response.created,
                enabled: response.workflow.is_enabled === true,
            });
        } catch (cause) {
            const replayError = planReplayError(cause);
            setError(replayError.text);
            setErrorCode(replayError.code);
        } finally {
            setSaving(false);
        }
    };

    if (!expanded) {
        return (
            <div className="mt-3">
                <GlassButton type="button" size="sm" variant="subtle" aria-expanded="false"
                    aria-controls={panelId} onClick={() => void load()}>
                    <CalendarClock size={14} aria-hidden="true" /> Repeat on a schedule
                </GlassButton>
            </div>
        );
    }

    return (
        <section id={panelId} aria-label="Save chat plan as workflow"
            className="mt-3 space-y-3 rounded-2xl border border-edge bg-surface-1 p-3 text-sm text-text-1">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                    <p className="flex items-center gap-2 font-medium text-text-1">
                        <CalendarClock size={16} aria-hidden="true" /> Save this chat plan
                    </p>
                    <p className="mt-1 text-text-2">
                        The frozen steps can run later as a personal workflow.
                    </p>
                </div>
                <GlassButton type="button" size="sm" variant="ghost" aria-expanded="true"
                    aria-controls={panelId} onClick={() => setExpanded(false)}>
                    <ChevronDown size={14} aria-hidden="true" /> Collapse
                </GlassButton>
            </div>

            {loading ? <p role="status" className="text-text-3">Loading saved-plan preview…</p> : null}
            {error ? (
                <div role="alert" className="space-y-2 rounded-xl border border-danger/40 bg-danger/5 p-3 text-danger">
                    <p>{error}</p>
                    {errorCode === 'plan_hash_mismatch' ? (
                        <GlassButton type="button" size="sm" variant="subtle" onClick={() => void load()}>
                            <RefreshCw size={14} aria-hidden="true" /> Reload plan
                        </GlassButton>
                    ) : null}
                </div>
            ) : null}

            {preview ? (
                <>
                    <dl className="space-y-1.5">
                        <Detail term="Request">{preview.request}</Detail>
                        <Detail term="Time">{describePlanReplayTimeHandling(planReplayRunTimeZone(scheduled ? schedule : null, preview.time_zone))}</Detail>
                        <Detail term="Cadence">At least every {minimumCadenceText(preview.min_interval_seconds)}.</Detail>
                        <Detail term="Step cap">{preview.max_steps.toLocaleString()} steps per saved plan.</Detail>
                        <Detail term="Runs as">
                            You, in the workflow&apos;s own conversation. It only reads sources this plan read, and access is checked again.
                        </Detail>
                        <Detail term="Alerts">{PLAN_REPLAY_ALERT_NOTICE}</Detail>
                    </dl>
                    <ol aria-label="Frozen plan steps" className="space-y-2">
                        {preview.steps.map((step) => (
                            <li key={step.step_id} className="rounded-lg border border-edge bg-surface-2 p-2">
                                <p className="break-words font-medium text-text-1">{`${step.number}. ${step.title}`}</p>
                                <p className="break-words text-text-2">{step.capability_label}</p>
                            </li>
                        ))}
                    </ol>
                    {preview.refusals.length ? (
                        <div role="status" className="rounded-xl border border-warn/40 bg-warn/5 p-3 text-text-2">
                            <p className="font-medium text-text-1">This plan has replay notes:</p>
                            <ul className="mt-1 list-disc space-y-1 pl-5">
                                {preview.refusals.map((refusal, index) => (
                                    <li key={`${refusal.code}-${refusal.step_number}-${index}`}>
                                        {/* A step refusal already starts with "Step N (label)". */}
                                        {refusal.step_number > 0 ? refusal.message : `Whole plan: ${refusal.message}`}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    ) : null}
                    {!preview.eligible ? null : saved ? (
                        <div role="status" className="space-y-2 rounded-xl border border-success/30 bg-success/10 p-3 text-text-1">
                            <p className="font-medium">
                                {saved.created
                                    ? saved.enabled ? 'Saved and scheduled.' : 'Saved as a paused workflow.'
                                    : 'This plan is already saved as a workflow.'}
                            </p>
                            {saved.id ? (
                                <Link to={workflowProposalLink(saved.id)}
                                    className="inline-flex h-8 items-center rounded-xl px-3 text-sm font-medium text-accent hover:bg-surface-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
                                    Open workflow
                                </Link>
                            ) : null}
                        </div>
                    ) : options ? (
                        <div className="space-y-3 rounded-xl border border-edge bg-surface-2 p-3">
                            <label className="block space-y-1">
                                <span className="font-medium text-text-1">Workflow name</span>
                                <input className="min-h-10 w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none"
                                    value={name} onChange={(event) => setName(event.target.value)}
                                    placeholder="Let SimpleChat pick a name" />
                            </label>
                            <label className="block space-y-1">
                                <span className="font-medium text-text-1">Description</span>
                                <textarea className="min-h-20 w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none"
                                    value={description} onChange={(event) => setDescription(event.target.value)}
                                    placeholder="Optional" />
                            </label>
                            <label className="flex items-start gap-2">
                                <input type="checkbox" className="mt-1 accent-[var(--accent)]"
                                    checked={scheduled} onChange={(event) => setScheduled(event.target.checked)} />
                                <span>
                                    <span className="block font-medium text-text-1">Run on a schedule</span>
                                    <span className="block text-text-2">Manual workflows can still be started from Workflows.</span>
                                </span>
                            </label>
                            <WorkflowScheduleFields
                                triggerField={<p className="font-medium text-text-1">Schedule</p>}
                                schedule={schedule}
                                options={options}
                                scheduled={scheduled}
                                onChange={(update) => setSchedule((current) => update(current))}
                            />
                            <label className="flex items-start gap-2">
                                <input type="checkbox" className="mt-1 accent-[var(--accent)]"
                                    checked={enabled} disabled={!scheduled}
                                    onChange={(event) => setEnabled(event.target.checked)} />
                                <span>
                                    <span className="block font-medium text-text-1">Turn on the schedule now</span>
                                    <span className="block text-text-2">Off by default. A paused workflow is saved but does not run automatically.</span>
                                </span>
                            </label>
                            <GlassButton type="button" variant="primary" disabled={saving} onClick={() => void save()}>
                                {saving ? 'Saving…' : 'Save workflow'}
                            </GlassButton>
                        </div>
                    ) : null}
                </>
            ) : null}
        </section>
    );
}
