// workflowAlertNotices.ts
// Workflow alerts as the V2 pop-up notice reads them: what one says, whether it may pop up,
// and how a burst of them from one workflow is shown as a single entry.
//
// The documents are the same ones the classic pop-up reads, from the same route, and every
// field here is resolved the way classic resolves it (static/js/notifications.js,
// populateWorkflowAlertModal), so the two interfaces never disagree about how loud an alert
// is or whether it interrupts at all. V2 is stricter in two places, deliberately:
//
// - Only alerts from the last 24 hours pop up. An alert that arrived while nobody was
//   looking belongs in the bell, not in the reader's face the next time they sign in
//   (roadmap gotcha 53). The route is asked for that window, and it is checked again here.
// - Links go through the bell's resolver, which only follows same-origin paths.
//
// Everything read from an alert is untrusted: a summary can quote an email or a web page.
// Callers render it as plain text and nothing else.

import { api } from './apiClient';
import { normalizeNotification, type AppNotification } from './notifications';
import { v2WorkflowRunPath } from './notificationLinks';
import { groupWorkspacePath } from './groupWorkspaceNavigation';
import { requireWorkspaceId } from './workspaceContext';
import { WORKFLOW_ALERT_SEVERITIES, type WorkflowAlertSeverity } from './workflowAlerts';
import type { WorkflowScope } from './workflowEditor';
import { WORKFLOW_LINK_PARAM, WORKFLOW_RUN_LINK_PARAM } from './workflowRunLink';
import { isWorkflowResultIdentifier, isWorkflowResultReadableStatus } from './workflowResults';

export const WORKFLOW_ALERT_NOTIFICATION_TYPE = 'workflow_priority_alert';

/** How far back an unread alert may still pop up. Older ones wait in the bell. */
export const WORKFLOW_ALERT_POPUP_WINDOW_HOURS = 24;

/** The most the route returns in one read (route_backend_notifications.py). */
export const WORKFLOW_ALERT_FETCH_LIMIT = 10;

/** A clock a few minutes fast on the server must not make a new alert look like the future. */
const FUTURE_SKEW_MS = 5 * 60_000;

const DETAIL_MAX_LENGTH = 4000;
const SUMMARY_MAX_LENGTH = 600;
const MAX_LINKS = 3;
const MAX_RULES = 10;
const MAX_CHIPS = 8;

export type WorkflowAlertCategory = 'alert' | 'failure';
export type WorkflowAlertDelivery = 'popup' | 'notify_only';

export interface WorkflowAlertRuleMatch {
    name: string;
    severity: string;
    reason: string;
}

export interface WorkflowAlertLink {
    label: string;
    /**
     * The link as a notification, so the bell's resolver can read it unchanged. Alerts carry
     * several links in `metadata.link_targets`; each is checked exactly as the notification's
     * own link would be.
     */
    notification: AppNotification;
}

/** Where the alert's workflow lives, so Open workflow can go to the right list. */
export type WorkflowAlertScope = { kind: 'personal' } | { kind: 'group'; groupId: string };

export interface WorkflowAlert {
    id: string;
    notification: AppNotification;
    priority: WorkflowAlertSeverity;
    category: WorkflowAlertCategory;
    delivery: WorkflowAlertDelivery;
    createdAt: string;
    /** Null when the server wrote a date that does not parse. */
    createdMs: number | null;
    workflowId: string | null;
    workflowName: string;
    title: string;
    summary: string;
    /** The longer text behind Show more. Empty when it would only repeat the summary. */
    detail: string;
    /** What went wrong, for a failed run. */
    error: string;
    triggerReason: string;
    matchedRules: WorkflowAlertRuleMatch[];
    enrichments: string[];
    triggerSource: string;
    runnerType: string;
    agentName: string;
    runId: string | null;
    /** The run's status when the alert was raised, lowercased. Empty when the alert names none. */
    runStatus: string;
    scope: WorkflowAlertScope | null;
    links: WorkflowAlertLink[];
}

/**
 * One entry in the notice: a single alert, or every alert from one workflow that arrived
 * together. A workflow failing on each run for an hour is one thing to know, not twelve.
 */
export interface WorkflowAlertEntry {
    key: string;
    /** Newest first. */
    alerts: WorkflowAlert[];
    /** The one the entry shows: the loudest, and the newest of those. */
    lead: WorkflowAlert;
    priority: WorkflowAlertSeverity;
    count: number;
    /** When the earliest alert in the entry arrived. */
    sinceMs: number | null;
}

const PRIORITY_RANK: Record<WorkflowAlertSeverity, number> = {
    info: 0,
    low: 1,
    medium: 2,
    high: 3,
    critical: 4,
};

export const WORKFLOW_ALERT_PRIORITY_LABELS: Record<WorkflowAlertSeverity, string> = {
    info: 'Info',
    low: 'Low',
    medium: 'Medium',
    high: 'High',
    critical: 'Critical',
};

/** High and critical alerts stay until they are opened or closed; the rest tuck away. */
export function workflowAlertStays(priority: WorkflowAlertSeverity): boolean {
    return PRIORITY_RANK[priority] >= PRIORITY_RANK.high;
}

export function workflowAlertPriorityRank(priority: WorkflowAlertSeverity): number {
    return PRIORITY_RANK[priority];
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown): string {
    return typeof value === 'string' ? value : '';
}

/** One line, whitespace collapsed. */
function oneLine(value: unknown): string {
    return text(value).replace(/\s+/g, ' ').trim();
}

/** Line breaks kept, runs of blank lines and trailing spaces not. */
function paragraphs(value: unknown): string {
    return text(value)
        .replace(/\r\n?/g, '\n')
        .replace(/[ \t]+\n/g, '\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}

function cap(value: string, length: number): string {
    return value.length > length ? `${value.slice(0, length - 1).trimEnd()}…` : value;
}

function safeId(value: unknown): string | null {
    if (typeof value !== 'string' || !value.trim()) {
        return null;
    }
    try {
        return requireWorkspaceId(value.trim());
    } catch {
        return null;
    }
}

function readPriority(metadata: Record<string, unknown>, notification: AppNotification): WorkflowAlertSeverity {
    const raw = oneLine(metadata.priority || notification.priority || 'medium').toLowerCase();
    return (WORKFLOW_ALERT_SEVERITIES as readonly string[]).includes(raw) ? raw as WorkflowAlertSeverity : 'medium';
}

function readCategory(metadata: Record<string, unknown>, notification: AppNotification): WorkflowAlertCategory {
    return oneLine(metadata.category || notification.category || 'alert').toLowerCase() === 'failure'
        ? 'failure'
        : 'alert';
}

/**
 * Popup unless the alert says otherwise, as classic and the server both read it: an alert
 * written before delivery existed interrupted, and still does.
 */
function readDelivery(metadata: Record<string, unknown>, topLevel: unknown): WorkflowAlertDelivery {
    return oneLine(metadata.delivery || topLevel || '').toLowerCase() === 'notify_only' ? 'notify_only' : 'popup';
}

function readTitle(metadata: Record<string, unknown>, notification: AppNotification, workflowName: string): string {
    const explicit = oneLine(metadata.event_title || metadata.alert_title);
    if (explicit) {
        return explicit;
    }
    const stripped = oneLine(notification.title)
        .replace(/^(info|low|medium|high|critical)\s+priority\s+workflow\s+alert:\s*/i, '')
        .trim();
    return stripped || workflowName || 'Workflow alert';
}

function readRules(value: unknown): WorkflowAlertRuleMatch[] {
    if (!Array.isArray(value)) {
        return [];
    }
    return value
        .filter(isRecord)
        .map((rule) => ({
            name: oneLine(rule.rule_name) || 'Unnamed rule',
            severity: oneLine(rule.severity).toLowerCase(),
            reason: oneLine(rule.reason),
        }))
        .slice(0, MAX_RULES);
}

function readLabels(value: unknown): string[] {
    if (!Array.isArray(value)) {
        return [];
    }
    const seen = new Set<string>();
    const labels: string[] = [];
    for (const item of value) {
        const label = cap(oneLine(item), 80);
        if (label && !seen.has(label.toLowerCase())) {
            seen.add(label.toLowerCase());
            labels.push(label);
        }
    }
    return labels.slice(0, MAX_CHIPS);
}

/** The link to a conversation the workflow created: where the card's Open button goes first. */
export const WORKFLOW_ALERT_CREATED_LINK_LABEL = 'Open created conversation';

/**
 * What a link button says.
 *
 * Classic calls the link to the conversation a workflow posts into "Open workflow". V2 also
 * offers an Open workflow action that goes to the workflow itself, so that link is named
 * for where it actually leads.
 */
function linkLabel(raw: unknown): string {
    const label = oneLine(raw);
    const lower = label.toLowerCase();
    if (lower === 'open workflow') {
        return 'Open workflow conversation';
    }
    if (lower.startsWith('open created')) {
        return WORKFLOW_ALERT_CREATED_LINK_LABEL;
    }
    if (lower.startsWith('open updated')) {
        return 'Open conversation';
    }
    return cap(label, 60) || 'Open conversation';
}

function linkNotification(base: AppNotification, linkUrl: string, linkContext: Record<string, unknown>): AppNotification {
    return { ...base, link_url: linkUrl, link_context: linkContext };
}

function readLinks(metadata: Record<string, unknown>, notification: AppNotification): WorkflowAlertLink[] {
    const links: WorkflowAlertLink[] = [];
    const seen = new Set<string>();
    const targets = Array.isArray(metadata.link_targets) ? metadata.link_targets : [];
    for (const target of targets) {
        if (!isRecord(target)) {
            continue;
        }
        const linkUrl = text(target.link_url).trim();
        if (!linkUrl) {
            continue;
        }
        const context = isRecord(target.link_context) ? target.link_context : {};
        const key = text(context.conversation_id).trim() || linkUrl;
        if (seen.has(key)) {
            continue;
        }
        seen.add(key);
        links.push({ label: linkLabel(target.label), notification: linkNotification(notification, linkUrl, context) });
        if (links.length >= MAX_LINKS) {
            break;
        }
    }
    if (!links.length && notification.link_url.trim()) {
        links.push({ label: 'Open conversation', notification });
    }
    return links;
}

/**
 * The workflow's home. Written on the alert by the runner: `workflow_scope`, and
 * `workflow_group_id` for a group workflow. It is never read from `metadata.group_id`, which
 * classic takes as the group to make active when a notification opens. An alert from before
 * the runner wrote them is placed by the conversation it posted into, and one that cannot be
 * placed offers neither Open run nor Open workflow rather than a guess.
 */
function readScope(metadata: Record<string, unknown>): WorkflowAlertScope | null {
    const written = oneLine(metadata.workflow_scope).toLowerCase();
    if (written === 'group') {
        const groupId = safeId(metadata.workflow_group_id);
        if (groupId) {
            return { kind: 'group', groupId };
        }
        const linked = readLinkedScope(metadata);
        return linked?.kind === 'group' ? linked : null;
    }
    if (written === 'personal') {
        return { kind: 'personal' };
    }
    return readLinkedScope(metadata);
}

/** The workspace of the conversation the workflow posted into, from its Open workflow link. */
function readLinkedScope(metadata: Record<string, unknown>): WorkflowAlertScope | null {
    const targets = Array.isArray(metadata.link_targets) ? metadata.link_targets : [];
    const workflowTarget = targets.find((target) => isRecord(target) && oneLine(target.label).toLowerCase() === 'open workflow');
    const context = isRecord(workflowTarget) && isRecord(workflowTarget.link_context) ? workflowTarget.link_context : null;
    if (!context) {
        return null;
    }
    const workspaceType = oneLine(context.workspace_type).toLowerCase();
    if (workspaceType === 'group') {
        const groupId = safeId(context.group_id);
        return groupId ? { kind: 'group', groupId } : null;
    }
    return workspaceType === 'personal' ? { kind: 'personal' } : null;
}

function parseTime(value: string): number | null {
    if (!value) {
        return null;
    }
    const ms = Date.parse(value);
    return Number.isNaN(ms) ? null : ms;
}

/**
 * A workflow alert as the notice uses it, or null for anything that is not one.
 *
 * `raw` is the document exactly as the route sent it. The top-level `delivery` the route
 * adds is read from it before the shared normalizer, which keeps only the fields the bell
 * needs, drops it.
 */
export function readWorkflowAlert(raw: unknown): WorkflowAlert | null {
    const notification = normalizeNotification(raw);
    if (!notification || notification.notification_type !== WORKFLOW_ALERT_NOTIFICATION_TYPE) {
        return null;
    }
    const metadata = notification.metadata;
    const workflowName = cap(oneLine(metadata.workflow_name), 120) || 'Workflow';
    const title = cap(readTitle(metadata, notification, workflowName), 160);
    const error = cap(paragraphs(metadata.error), DETAIL_MAX_LENGTH);
    const longText = paragraphs(metadata.alert_detail || metadata.response_preview);
    const summary = cap(
        oneLine(metadata.alert_summary || notification.message) || oneLine(longText) || 'Workflow update available.',
        SUMMARY_MAX_LENGTH,
    );
    const detail = longText && oneLine(longText) !== summary && longText !== error
        ? cap(longText, DETAIL_MAX_LENGTH)
        : '';
    const agentName = cap(oneLine(metadata.agent_display_name || metadata.agent_name), 80);
    return {
        id: notification.id,
        notification,
        priority: readPriority(metadata, notification),
        category: readCategory(metadata, notification),
        delivery: readDelivery(metadata, isRecord(raw) ? raw.delivery : undefined),
        createdAt: notification.created_at,
        createdMs: parseTime(notification.created_at),
        workflowId: safeId(metadata.workflow_id),
        workflowName,
        title,
        summary,
        detail,
        error,
        triggerReason: cap(oneLine(metadata.trigger_reason), 400),
        matchedRules: readRules(metadata.matched_rules),
        enrichments: readLabels(metadata.alert_enrichments),
        triggerSource: cap(oneLine(metadata.trigger_source), 40),
        runnerType: cap(oneLine(metadata.runner_type), 40),
        agentName,
        runId: safeId(metadata.run_id),
        runStatus: cap(oneLine(metadata.status), 40).toLowerCase(),
        scope: readScope(metadata),
        links: readLinks(metadata, notification),
    };
}

/**
 * Whether an alert may pop up now: it asked to, nobody has read it, and it is recent.
 * An alert with a date that does not parse is left in the bell, where its age does not matter.
 */
export function isWorkflowAlertPopupEligible(alert: WorkflowAlert, now: number = Date.now()): boolean {
    if (alert.delivery !== 'popup' || alert.notification.is_read || alert.createdMs === null) {
        return false;
    }
    const age = now - alert.createdMs;
    return age <= WORKFLOW_ALERT_POPUP_WINDOW_HOURS * 3_600_000 && age >= -FUTURE_SKEW_MS;
}

function compareAlerts(left: WorkflowAlert, right: WorkflowAlert): number {
    const byPriority = PRIORITY_RANK[right.priority] - PRIORITY_RANK[left.priority];
    if (byPriority !== 0) {
        return byPriority;
    }
    return (right.createdMs ?? 0) - (left.createdMs ?? 0);
}

/**
 * Group alerts by workflow, loudest first.
 *
 * An entry is as loud as its loudest alert, and among equals the one with the newest alert
 * leads, so a storm never hides a fresh critical alert from another workflow behind it.
 */
export function groupWorkflowAlerts(alerts: WorkflowAlert[]): WorkflowAlertEntry[] {
    const groups = new Map<string, WorkflowAlert[]>();
    for (const alert of alerts) {
        const key = alert.workflowId ? `workflow:${alert.workflowId}` : `alert:${alert.id}`;
        const members = groups.get(key);
        if (members) {
            if (!members.some((member) => member.id === alert.id)) {
                members.push(alert);
            }
        } else {
            groups.set(key, [alert]);
        }
    }
    const entries: WorkflowAlertEntry[] = [];
    for (const [key, members] of groups) {
        const newestFirst = [...members].sort((left, right) => (right.createdMs ?? 0) - (left.createdMs ?? 0));
        const lead = [...members].sort(compareAlerts)[0];
        const times = members.map((member) => member.createdMs).filter((ms): ms is number => ms !== null);
        entries.push({
            key,
            alerts: newestFirst,
            lead,
            priority: lead.priority,
            count: members.length,
            sinceMs: times.length ? Math.min(...times) : null,
        });
    }
    return entries.sort((left, right) => compareAlerts(left.lead, right.lead));
}

/** Every notification id an entry stands for. */
export function workflowAlertEntryIds(entry: WorkflowAlertEntry): string[] {
    return entry.alerts.map((alert) => alert.id);
}

/**
 * A time as the notice and card show it: "9:02 AM" today, "Sun 11:40 PM" on another day. A
 * popped-up alert is at most a day old, so the weekday is only needed once it crosses midnight.
 */
export function formatWorkflowAlertClock(ms: number, now: number = Date.now()): string {
    const when = new Date(ms);
    const sameDay = when.toDateString() === new Date(now).toDateString();
    return when.toLocaleString([], sameDay
        ? { hour: 'numeric', minute: '2-digit' }
        : { weekday: 'short', hour: 'numeric', minute: '2-digit' });
}

/** "Failed 5 times since 9:00 AM", or null for a single alert. */
export function describeWorkflowAlertGroup(entry: WorkflowAlertEntry): string | null {
    if (entry.count < 2) {
        return null;
    }
    const since = entry.sinceMs !== null ? ` since ${formatWorkflowAlertClock(entry.sinceMs)}` : '';
    const allFailed = entry.alerts.every((alert) => alert.category === 'failure');
    return allFailed ? `Failed ${entry.count} times${since}` : `${entry.count} alerts${since}`;
}

/**
 * Why the reader is seeing the alert, in words: "Build watcher is set to alert at high
 * priority when a run fails." or "Build watcher sent this alert at high priority." The rules
 * that matched are listed under it.
 */
export function describeWorkflowAlertReason(alert: WorkflowAlert): string {
    const priority = WORKFLOW_ALERT_PRIORITY_LABELS[alert.priority].toLowerCase();
    return alert.category === 'failure'
        ? `${alert.workflowName} is set to alert at ${priority} priority when a run fails.`
        : `${alert.workflowName} sent this alert at ${priority} priority.`;
}

// The runner's own reason is a log line -- "HIGH alert triggered by: Rule A, Rule B" -- that
// the sentence above and the matched rules already say better.
const LOGGED_REASON = /^(?:info|low|medium|high|critical)\s+alert\s+triggered(?:\.|\s+by:.*)?$/i;

/** The server's trigger reason, when it says more than the log line the runner writes. */
export function workflowAlertServerReason(alert: WorkflowAlert): string | null {
    const reason = alert.triggerReason.trim();
    return reason && !LOGGED_REASON.test(reason) ? reason : null;
}

/**
 * Where Open workflow goes: the workflows list of the workspace the workflow lives in, naming
 * the workflow and the run that raised the alert in Track P's link form (workflowRunLink.ts).
 * The workflows section then opens that run's history with the run expanded, so a failed run
 * lands on its own history. Without a run id it names the workflow alone, and without a
 * workflow id it is the plain list. Null when the alert cannot be placed.
 */
export function workflowAlertWorkflowPath(alert: WorkflowAlert): string | null {
    if (!alert.scope) {
        return null;
    }
    let listPath = '/workspace/workflows';
    if (alert.scope.kind === 'group') {
        try {
            listPath = groupWorkspacePath(alert.scope.groupId, 'workflows');
        } catch {
            return null;
        }
    }
    if (!alert.workflowId) {
        return listPath;
    }
    const params = new URLSearchParams({ [WORKFLOW_LINK_PARAM]: alert.workflowId });
    if (alert.runId) {
        params.set(WORKFLOW_RUN_LINK_PARAM, alert.runId);
    }
    return `${listPath}?${params}`;
}

/**
 * Where Open run goes: the run that raised the alert, opened in its workflow's run history in
 * the workspace the workflow lives in (notificationLinks.ts v2WorkflowRunPath). It is the same
 * address Open workflow names for an alert with a run. Null when the alert names no run or
 * cannot be placed, and the card then offers Open workflow, or neither.
 */
export function workflowAlertOpenRunPath(alert: WorkflowAlert): string | null {
    const scope: WorkflowScope | null = alert.scope
        ? (alert.scope.kind === 'group' ? { type: 'group', groupId: alert.scope.groupId } : { type: 'personal' })
        : null;
    return v2WorkflowRunPath(scope, alert.workflowId, alert.runId);
}

export interface WorkflowAlertFollowUp {
    label: string;
    run: () => void | Promise<void>;
}

export interface WorkflowAlertFollowUpOptions {
    /** The reader may ask about workflow results in chat: the bootstrap's per-user flag. */
    enabled: boolean;
    /** Open a chat about the run; the card passes the shared entry point. */
    open: (workflowId: string, runId: string) => void;
}

/**
 * The follow-up chat action for an alert: phase 6a's Ask about this.
 *
 * Offered for a personal workflow's alert that names a run which had finished when the alert
 * was raised, and only while the reader may ask about workflow results. A group alert, an
 * alert without a run, and a failed or cancelled run get none. The chat reads the run again
 * before anything is selected, so a result that changed or went away since is reported there.
 */
export function workflowAlertFollowUpAction(
    alert: WorkflowAlert,
    options?: WorkflowAlertFollowUpOptions,
): WorkflowAlertFollowUp | null {
    const { workflowId, runId } = alert;
    if (!options?.enabled || alert.scope?.kind !== 'personal' ||
        !isWorkflowResultIdentifier(workflowId) || !isWorkflowResultIdentifier(runId) ||
        !isWorkflowResultReadableStatus(alert.runStatus)) {
        return null;
    }
    const { open } = options;
    return { label: 'Ask about this', run: () => open(workflowId, runId) };
}

/**
 * Read the unread pop-up alerts from the last 24 hours, newest first.
 *
 * `complete` is true when the answer is shorter than the page asked for: it is every unread
 * pop-up alert there is, and the store retires a shown alert it no longer lists. So a failure
 * must never look like a short answer. Asking with `since_hours` makes the route answer a
 * failed storage read with a 500 rather than an empty list, and anything that is not a
 * successful answer is thrown here. The caller then keeps the alerts it already has.
 */
export async function fetchWorkflowAlerts(signal?: AbortSignal): Promise<{ alerts: WorkflowAlert[]; complete: boolean }> {
    const params = new URLSearchParams({
        limit: String(WORKFLOW_ALERT_FETCH_LIMIT),
        since_hours: String(WORKFLOW_ALERT_POPUP_WINDOW_HOURS),
    });
    const payload = await api.get<unknown>(`/api/notifications/workflow-alerts?${params}`, signal);
    if (!isRecord(payload) || payload.success === false || !Array.isArray(payload.notifications)) {
        throw new Error('Workflow alerts could not be read.');
    }
    const alerts = payload.notifications
        .map(readWorkflowAlert)
        .filter((alert): alert is WorkflowAlert => alert !== null);
    return {
        alerts,
        // A full page may have left older alerts out; a shorter one is everything there is.
        complete: payload.notifications.length < WORKFLOW_ALERT_FETCH_LIMIT,
    };
}
