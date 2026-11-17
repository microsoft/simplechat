// workflowActivitySnapshot.ts
// What the Workflow Activity page makes of the snapshot the server sends, kept apart from React so
// it runs in a test.
//
// `GET /api/{user|group}/workflows/activity` answers one object (functions_workflow_activity.py,
// build_workflow_activity_snapshot): the workflow, its conversation, the run, the run's activities
// in the order they began, how many lanes they fall into, and whether the run is still going. The
// same object arrives again, whole, on every frame of the stream while it is. Nothing here trusts
// its shape: the text in it is a workflow's own output, a model's words and a tool's arguments, so
// every field is read defensively and drawn only ever as text.
//
// The rules below are the classic page's (static/js/workflow/workflow-activity.js), ported so the
// two pages say the same thing about the same run: which statuses are live, what the caption says,
// how many tool calls there are, which activity is selected after a new snapshot lands, and when
// the timeline follows the newest one.

import { isPendingAction, type PendingAction } from './approvalsApi';
import { completenessReport } from './taskCompleteness';
import {
    hasWorkflowActivityIdentifier,
    isWorkflowActivityActive,
    workflowActivityScope,
    type WorkflowActivityQuery,
} from './workflowActivity';
import { workflowRunHref } from './workflowRunLink';
import { workflowStatusLabel } from './workflowWorkbench';

export interface WorkflowActivityEvent {
    content: string;
    detail: string;
    timestamp: string;
}

export interface WorkflowActivityRecord {
    id: string;
    title: string;
    summary: string;
    detail: string;
    status: string;
    kind: string;
    laneLabel: string;
    /** Which lane the activity sits in; the timeline indents each lane further. */
    laneIndex: number;
    startedAt: string;
    durationMs: number | null;
    events: readonly WorkflowActivityEvent[];
    /** The saved Microsoft 365 email or invitation this activity stands for, when it does. */
    pendingAction: PendingAction | null;
}

export interface WorkflowActivityTask {
    name: string;
    /** `workflow_result.task_completeness` as saved; read by lib/taskCompleteness.ts. */
    completeness: unknown;
}

export interface WorkflowActivityRun {
    id: string;
    status: string;
    triggerSource: string;
    startedAt: string;
    conversationId: string;
    workflowId: string;
    /** The agent, or else the model deployment, the run used. */
    runner: string;
    responsePreview: string;
    error: string;
    tasks: readonly WorkflowActivityTask[];
}

export interface WorkflowActivitySnapshot {
    workflowId: string;
    workflowName: string;
    conversationId: string;
    conversationTitle: string;
    run: WorkflowActivityRun | null;
    activities: readonly WorkflowActivityRecord[];
    live: boolean;
}

export const EMPTY_WORKFLOW_ACTIVITY_SNAPSHOT: WorkflowActivitySnapshot = Object.freeze({
    workflowId: '',
    workflowName: '',
    conversationId: '',
    conversationTitle: '',
    run: null,
    activities: [],
    live: false,
});

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : typeof value === 'number' ? String(value) : '';
}

function record(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/** The deepest a lane is drawn: any more would leave a card no room, and the data is unchanged. */
const MAX_DRAWN_LANE = 8;

function normalizeEvent(value: unknown): WorkflowActivityEvent | null {
    const event = record(value);
    return event ? { content: text(event.content), detail: text(event.detail), timestamp: text(event.timestamp) } : null;
}

function normalizeActivity(value: unknown, index: number): WorkflowActivityRecord | null {
    const activity = record(value);
    if (!activity) {
        return null;
    }
    const duration = Number(activity.duration_ms);
    const lane = Math.trunc(Number(activity.lane_index));
    return {
        id: text(activity.id) || `activity-${index}`,
        title: text(activity.title),
        summary: text(activity.summary),
        detail: text(activity.detail),
        status: text(activity.status).toLowerCase(),
        kind: text(activity.kind),
        laneLabel: text(activity.lane_label),
        laneIndex: Number.isFinite(lane) && lane > 0 ? Math.min(lane, MAX_DRAWN_LANE) : 0,
        startedAt: text(activity.started_at),
        durationMs: Number.isFinite(duration) && duration > 0 ? duration : null,
        events: (Array.isArray(activity.events) ? activity.events : []).flatMap((item) => {
            const event = normalizeEvent(item);
            return event ? [event] : [];
        }),
        // Only the shape the card draws; anything else is the server describing something this
        // page has no control for, and is not guessed at.
        pendingAction: isPendingAction(activity.pending_action) ? activity.pending_action : null,
    };
}

function normalizeRun(value: unknown): WorkflowActivityRun | null {
    const run = record(value);
    if (!run) {
        return null;
    }
    return {
        id: text(run.id),
        status: text(run.status).toLowerCase(),
        triggerSource: text(run.trigger_source),
        startedAt: text(run.started_at),
        conversationId: text(run.conversation_id),
        workflowId: text(run.workflow_id),
        runner: text(run.agent_display_name) || text(run.agent_name) || text(run.model_deployment_name),
        responsePreview: text(run.response_preview),
        error: text(run.error),
        tasks: (Array.isArray(run.task_results) ? run.task_results : []).flatMap((item) => {
            const task = record(item);
            return task
                ? [{ name: text(task.task_name), completeness: record(task.workflow_result)?.task_completeness }]
                : [];
        }),
    };
}

/** Read a snapshot, from the endpoint or a stream frame, into the shape the page draws. Never throws. */
export function normalizeWorkflowActivitySnapshot(value: unknown): WorkflowActivitySnapshot {
    const raw = record(value) ?? {};
    const workflow = record(raw.workflow);
    const conversation = record(raw.conversation);
    return {
        workflowId: text(workflow?.id),
        workflowName: text(workflow?.name),
        conversationId: text(conversation?.id),
        conversationTitle: text(conversation?.title),
        run: normalizeRun(raw.run),
        activities: (Array.isArray(raw.activities) ? raw.activities : []).flatMap((item, index) => {
            const activity = normalizeActivity(item, index);
            return activity ? [activity] : [];
        }),
        live: raw.live === true,
    };
}

/* Words and numbers -------------------------------------------------------------------------- */

/** The heading: the workflow's name, else its conversation's title. */
export function activityTitle(snapshot: WorkflowActivitySnapshot): string {
    return snapshot.workflowName || snapshot.conversationTitle || 'Workflow activity';
}

/**
 * The line under the heading: how the run started, how it stands, and what ran it.
 *
 * "manual run completed using Weekly digest agent." Underscored states read as words
 * ("awaiting sign in"), which the classic page prints as stored.
 */
export function activityCaption(snapshot: WorkflowActivitySnapshot): string {
    const run = snapshot.run;
    if (!run) {
        return 'Waiting for a captured workflow run.';
    }
    const status = run.status.replace(/_/g, ' ') || 'captured';
    const base = `${run.triggerSource || 'manual'} run ${status}`;
    return run.runner ? `${base} using ${run.runner}.` : `${base}.`;
}

export interface WorkflowActivityStats {
    /** The run's id, shortened to what can be read aloud. */
    run: string;
    activities: number;
    toolCalls: number;
    started: string;
}

export function activityStats(snapshot: WorkflowActivitySnapshot): WorkflowActivityStats {
    return {
        run: snapshot.run ? snapshot.run.id.slice(0, 8) || 'Captured' : 'Pending',
        activities: snapshot.activities.length,
        toolCalls: snapshot.activities.filter((activity) => activity.kind === 'tool_invocation').length,
        started: formatActivityDateTime(snapshot.run?.startedAt),
    };
}

/** The conversation "Open workflow" opens: the workflow's own, else the one the run wrote to. */
export function activityConversationId(snapshot: WorkflowActivitySnapshot): string {
    return snapshot.conversationId || snapshot.run?.conversationId || '';
}

/**
 * The run in the Workflows section's run history, in the workspace the page was opened for, or
 * null when the run, or the group its workspace is, cannot be named in a link.
 */
export function activityRunHref(query: WorkflowActivityQuery, workflowId: string, runId: string): string | null {
    if (!workflowId || !runId) {
        return null;
    }
    try {
        return workflowRunHref(workflowId, runId, workflowActivityScope(query));
    } catch {
        // A group the link did not name has no path of its own.
        return null;
    }
}

/** `--` for nothing, the text itself for what is not a date, otherwise "Jan 5, 2025, 9:05 AM". */
export function formatActivityDateTime(value: unknown, locale?: string, timeZone?: string): string {
    const raw = text(value);
    if (!raw) {
        return '--';
    }
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) {
        return raw;
    }
    try {
        return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(date);
    } catch {
        return raw;
    }
}

/** "450 ms", "3.2 s", "42 s" or "2m 5s"; nothing for a duration that is missing or not positive. */
export function formatActivityDuration(value: unknown): string {
    const milliseconds = Number(value);
    if (!Number.isFinite(milliseconds) || milliseconds <= 0) {
        return '';
    }
    if (milliseconds < 1000) {
        return `${Math.round(milliseconds)} ms`;
    }
    const seconds = milliseconds / 1000;
    if (seconds < 60) {
        return `${seconds.toFixed(seconds >= 10 ? 0 : 1)} s`;
    }
    return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

/* Status ------------------------------------------------------------------------------------- */

export type ActivityTone = 'accent' | 'warn' | 'danger' | 'ok' | 'neutral';

export interface ActivityStatusView {
    label: string;
    tone: ActivityTone;
    /** Which glyph goes with the words, so the state is not carried by colour alone. */
    glyph: 'running' | 'waiting' | 'done' | 'failed' | 'cancelled' | 'idle';
}

const DONE = new Set(['completed', 'complete', 'succeeded', 'success', 'finished', 'done']);
const FAILED = new Set(['failed', 'error', 'invalid', 'incomplete']);
const CANCELLED = new Set(['cancelled', 'canceled']);

/**
 * How a run's or an activity's status is drawn.
 *
 * Running is the accent; every other live state, a wait for a person or a sign-in, is a warning;
 * a failure is danger and a finish is ok; a run that was stopped is neutral, as the classic
 * badge is. The words are the ones the rest of V2 uses for the same status.
 */
export function activityStatusView(status: string): ActivityStatusView {
    const value = status.trim().toLowerCase();
    const label = workflowStatusLabel(value) || 'Idle';
    if (value === 'running') {
        return { label, tone: 'accent', glyph: 'running' };
    }
    if (isWorkflowActivityActive(value)) {
        return { label, tone: 'warn', glyph: 'waiting' };
    }
    if (FAILED.has(value)) {
        return { label, tone: 'danger', glyph: 'failed' };
    }
    if (DONE.has(value)) {
        return { label, tone: 'ok', glyph: 'done' };
    }
    if (value === 'completed_partial') {
        return { label, tone: 'warn', glyph: 'failed' };
    }
    if (CANCELLED.has(value)) {
        return { label, tone: 'neutral', glyph: 'cancelled' };
    }
    return { label, tone: 'neutral', glyph: 'idle' };
}

export interface WorkflowActivityCancel {
    visible: boolean;
    /** Cancelling is already under way. */
    disabled: boolean;
    label: string;
    workflowId: string;
    runId: string;
}

/** Whether Cancel run is on offer, for which run, and what it says. The page's own ids stand in for missing ones. */
export function activityCancel(snapshot: WorkflowActivitySnapshot, query: WorkflowActivityQuery): WorkflowActivityCancel {
    const workflowId = snapshot.workflowId || query.workflowId;
    const runId = snapshot.run?.id || query.runId;
    const status = snapshot.run?.status ?? '';
    const cancelling = status === 'cancelling';
    return {
        visible: Boolean(workflowId && runId && isWorkflowActivityActive(status)),
        disabled: cancelling,
        label: cancelling ? 'Cancelling' : 'Cancel run',
        workflowId,
        runId,
    };
}

/* The response preview ----------------------------------------------------------------------- */

export interface WorkflowActivityResponse {
    heading: 'Run Error' | 'Response Preview';
    text: string;
}

/** What the response panel shows: the run's error when it has one, else its response preview. */
export function activityResponse(run: WorkflowActivityRun | null): WorkflowActivityResponse | null {
    if (!run) {
        return null;
    }
    if (run.error) {
        return { heading: 'Run Error', text: run.error };
    }
    return run.responsePreview ? { heading: 'Response Preview', text: run.responsePreview } : null;
}

/** "Show response preview", "Hide run error". */
export function responseToggleLabel(expanded: boolean, heading: string): string {
    return `${expanded ? 'Hide' : 'Show'} ${heading.trim().toLowerCase() || 'response preview'}`;
}

/** The statuses `TaskCompletenessDetails` has words for; a report in any other is not drawn. */
const COMPLETENESS_STATUSES: ReadonlySet<string> = new Set([
    'complete',
    'incomplete',
    'verification_unavailable',
    'checking',
    'checked',
    'correcting',
    'repairing_assessment',
    'disabled',
]);

export interface WorkflowActivityCheck {
    key: string;
    name: string;
    completeness: unknown;
}

/** The tasks that saved an answer check, named, for the panel to draw. Tasks without one are skipped. */
export function activityChecks(run: WorkflowActivityRun | null): WorkflowActivityCheck[] {
    return (run?.tasks ?? []).flatMap((task, index) => {
        const report = completenessReport(task.completeness);
        return report && COMPLETENESS_STATUSES.has(String(report.status))
            ? [{ key: `${index}-${task.name}`, name: task.name || 'Task', completeness: task.completeness }]
            : [];
    });
}

/* Selection and following -------------------------------------------------------------------- */

export interface ActivitySelection {
    selectedId: string;
    /** The detail panel shows whichever activity is newest, until the reader picks another. */
    followLatest: boolean;
}

export const INITIAL_ACTIVITY_SELECTION: ActivitySelection = Object.freeze({ selectedId: '', followLatest: true });

/**
 * The selection after a snapshot lands.
 *
 * Following, it moves to the newest activity. Otherwise a reader's pick stays while it is still
 * there; when it is gone the running activity, and failing that the newest, is picked for them --
 * without resuming the following, which only picking the newest activity, or Refresh, does.
 */
export function resolveActivitySelection(
    selection: ActivitySelection,
    activities: readonly WorkflowActivityRecord[],
): ActivitySelection {
    const latest = activities[activities.length - 1];
    if (!latest) {
        return selection;
    }
    if (selection.followLatest) {
        return selection.selectedId === latest.id ? selection : { selectedId: latest.id, followLatest: true };
    }
    if (activities.some((activity) => activity.id === selection.selectedId)) {
        return selection;
    }
    const running = activities.find((activity) => activity.status === 'running');
    return { selectedId: (running ?? latest).id, followLatest: false };
}

/** The reader picked an activity: they follow the timeline again exactly when it is the newest. */
export function pickActivity(
    activities: readonly WorkflowActivityRecord[],
    id: string,
): ActivitySelection {
    const latest = activities[activities.length - 1];
    return { selectedId: id, followLatest: Boolean(latest) && latest.id === id };
}

export function selectedActivity(
    selection: ActivitySelection,
    activities: readonly WorkflowActivityRecord[],
): WorkflowActivityRecord | null {
    return activities.find((activity) => activity.id === selection.selectedId) ?? null;
}

/** How near the bottom still counts as at it, so a reader who scrolled up is left where they are. */
export const TIMELINE_BOTTOM_THRESHOLD_PX = 24;

export function isScrolledNearBottom(
    metrics: { scrollHeight: number; scrollTop: number; clientHeight: number },
    threshold = TIMELINE_BOTTOM_THRESHOLD_PX,
): boolean {
    return metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight <= threshold;
}

/**
 * Whether the page should be holding the live stream open.
 *
 * Only once a snapshot has been read, and only with something to name. With no run yet it
 * listens, since the run may be about to begin; with one it listens while the run is live or in a
 * state that can still change, and stops once it has settled.
 */
export function shouldListenForUpdates(
    query: WorkflowActivityQuery,
    snapshot: WorkflowActivitySnapshot | null,
    streamSupported = typeof EventSource !== 'undefined',
): boolean {
    if (!snapshot || !streamSupported || !hasWorkflowActivityIdentifier(query)) {
        return false;
    }
    return !snapshot.run || snapshot.live || isWorkflowActivityActive(snapshot.run.status);
}

/** Whether the card's action has moved on from what the snapshot last said, so the timeline should be read again. */
export function pendingActionMoved(held: PendingAction | null | undefined, next: PendingAction): boolean {
    return (
        !held ||
        held.id !== next.id ||
        held.version !== next.version ||
        held.status !== next.status ||
        held.updated_at !== next.updated_at
    );
}
