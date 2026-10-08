// M365Cards.tsx
// Microsoft 365 sharing preferences, chat and workflow connections, and workflow
// authorizations for the signed-in user.
//
// Mirrors the classic profile page's "Microsoft 365 sharing and workflows" section
// (static/js/profile/profile-m365.js) against the same /api/m365 routes. Every write needs
// the X-M365-CSRF-Token header; the token arrives on the GET responses and is refreshed once
// when the server reports it stale, as the classic page does.
//
// Every revocation and disconnect is confirmed first. None of them retract history that was
// already published to a conversation, and the dialogs say so.

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { clsx } from 'clsx';
import {
    Cable,
    KeyRound,
    Loader2,
    MessageSquare,
    RefreshCw,
    Share2,
    Unplug,
    Workflow,
} from 'lucide-react';
import { ApiError, request } from '../../lib/apiClient';
import {
    connectMicrosoft365,
    connectMicrosoft365Workflow,
    m365Sources,
    type M365Source,
} from '../../lib/m365Connect';
import { M365_APPROVALS_HREF } from '../../lib/m365Links';
import { toast } from '../../stores/toastStore';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { SettingsCard } from './SettingsCard';

export const M365_SOURCES: readonly M365Source[] = ['calendar', 'email', 'onedrive', 'spo'];

export const M365_SOURCE_LABELS: Record<M365Source, string> = {
    calendar: 'Calendar',
    email: 'Email',
    onedrive: 'OneDrive',
    spo: 'SharePoint Online (SPO)',
};

const SHORT_SOURCE_LABELS: Record<M365Source, string> = {
    calendar: 'Calendar',
    email: 'Email',
    onedrive: 'OneDrive',
    spo: 'SPO',
};

export type SharingChoice = 'ask' | 'request' | 'today' | 'always';
export type AnalysisChoice = 'ask' | 'always' | 'fast';
type AnalysisSource = 'onedrive' | 'spo';

export const SHARING_LABELS: Record<SharingChoice, string> = {
    ask: 'Ask before sharing',
    request: 'Prefer this request only',
    today: 'Prefer today',
    always: 'Prefer always, until revoked',
};

export const ANALYSIS_LABELS: Record<AnalysisChoice, string> = {
    ask: 'Ask before deeper analysis',
    always: 'Always allow deeper analysis within service limits',
    fast: 'Use a faster answer with coverage limitations',
};

const ANALYSIS_SOURCES: readonly AnalysisSource[] = ['onedrive', 'spo'];

const DURATION_LABELS: Record<string, string> = {
    no: 'No',
    request: 'Allow this request',
    today: 'Allow for today',
    always: 'Always allow',
};

const ANALYSIS_DECISION_LABELS: Record<string, string> = {
    request: 'Analyze more for this request',
    always: 'Always allow deeper analysis',
    fast: 'Use a faster answer',
};

const CHAT_STATUS_TEXT: Record<string, string> = {
    available: 'Signed in to Microsoft 365 for this session',
    not_connected: 'Not signed in to Microsoft 365 in this session',
    reconnect_required: 'Microsoft 365 needs you to sign in again',
};

/**
 * What the chat sign-in can do now. For a working sign-in the server lists the sources whose
 * permissions it already holds, including consent given at sign-in or by an administrator, so
 * this matches what chat actually does rather than only what was reconnected here.
 */
export function describeChatConnection(status: string, sources: M365Source[]): string {
    const labels = sources.map((source) => M365_SOURCE_LABELS[source]).join(', ');
    if (status === 'available') {
        return labels
            ? `${CHAT_STATUS_TEXT.available}. Chat can use: ${labels}. Microsoft still checks your access each time a source runs.`
            : `${CHAT_STATUS_TEXT.available}, but no source's permissions are granted yet. Connect the sources chat should use.`;
    }
    if (status === 'reconnect_required') {
        return labels
            ? `${CHAT_STATUS_TEXT.reconnect_required} before chat can use ${labels}.`
            : `${CHAT_STATUS_TEXT.reconnect_required} before chat can use your sources.`;
    }
    return `${CHAT_STATUS_TEXT.not_connected}. Chat asks you to connect the first time it needs a source, or connect here.`;
}

const SOURCE_PERMISSIONS_HELP =
    'Each source includes the permissions for all of its supported operations. Calendar includes reading events, creating invitations, mailbox timezone and recipient lookup. Email includes reading messages, managing drafts and read state, sending mail and recipient lookup. OneDrive and SPO include file discovery and reading. Microsoft shows the permissions before you consent.';

const SELECT_CLASS =
    'mt-1.5 w-full rounded-lg border border-edge bg-surface-solid px-2.5 py-2 text-sm text-text-1';
const PRIMARY_BUTTON =
    'inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-on-accent hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50';
const SECONDARY_BUTTON =
    'inline-flex items-center gap-1.5 rounded-lg border border-edge px-3 py-1.5 text-sm text-text-1 hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50';
const DANGER_BUTTON =
    'inline-flex items-center gap-1.5 rounded-lg border border-danger/40 px-3 py-1.5 text-sm text-danger hover:bg-danger-soft disabled:cursor-not-allowed disabled:opacity-50';

// ── Requests ────────────────────────────────────────────────────────────────

let csrfToken: string | null = null;
let csrfRefresh: Promise<unknown> | null = null;

function rememberCsrf(payload: unknown) {
    const token = (payload as { csrf_token?: unknown } | null)?.csrf_token;
    if (typeof token === 'string' && token.length >= 32) {
        csrfToken = token;
    }
}

/**
 * A Microsoft 365 API call. Reads keep the CSRF token they return; writes send it, and are
 * retried once with a fresh token when the server reports the old one stale.
 */
export async function m365Request<T>(
    path: string,
    options: { method?: string; body?: unknown; signal?: AbortSignal } = {},
    retried = false,
): Promise<T> {
    const method = options.method ?? 'GET';
    const write = method !== 'GET';
    if (write && !csrfToken) {
        await m365Request('/api/m365/preferences');
    }
    try {
        const result = await request<T>(path, {
            method,
            body: options.body,
            signal: options.signal,
            headers: write && csrfToken ? { 'X-M365-CSRF-Token': csrfToken } : {},
        });
        rememberCsrf(result);
        return result;
    } catch (error) {
        const code = error instanceof ApiError
            ? (error.payload as { error?: unknown } | null)?.error
            : undefined;
        if (write && !retried && error instanceof ApiError && error.status === 403 && code === 'm365_csrf_invalid') {
            csrfRefresh = csrfRefresh ?? m365Request('/api/m365/preferences').finally(() => {
                csrfRefresh = null;
            });
            await csrfRefresh;
            return m365Request<T>(path, options, true);
        }
        throw error;
    }
}

function errorText(error: unknown, fallback: string): string {
    return error instanceof ApiError || error instanceof Error ? error.message || fallback : fallback;
}

function spaced(value: string): string {
    return value.replaceAll('_', ' ');
}

export interface M365Binding {
    id: string;
    status?: string;
    execution_status?: string;
    self_authored?: boolean;
    decisions?: Record<string, { duration?: string }>;
    analysis_choice?: string;
    context?: { workflow_id?: string };
}

/** The classic Approvals wording for an authorization's state. */
export function describeBinding(binding: M365Binding): string {
    if (binding.self_authored === true && binding.status === 'approved') {
        return 'Decision: approved automatically because you saved this workflow revision yourself.';
    }
    const status = typeof binding.status === 'string' ? binding.status : 'unknown';
    const execution = typeof binding.execution_status === 'string' ? binding.execution_status : 'not reported';
    const summary = `Decision: ${spaced(status)}. Execution: ${spaced(execution)}.`;
    const outcomes = Object.entries(binding.decisions ?? {}).map(([source, decision]) => {
        const label = M365_SOURCE_LABELS[source as M365Source] ?? source;
        const duration = decision?.duration ?? '';
        return `${label}: ${DURATION_LABELS[duration] ?? duration}`;
    });
    if (outcomes.length) {
        return `${summary} Recorded source choices: ${outcomes.join('; ')}.`;
    }
    if (binding.analysis_choice && ANALYSIS_DECISION_LABELS[binding.analysis_choice]) {
        return `${summary} Recorded analysis choice: ${ANALYSIS_DECISION_LABELS[binding.analysis_choice]}.`;
    }
    return summary;
}

// ── Shared pieces ───────────────────────────────────────────────────────────

interface PendingRevocation {
    title: string;
    description: string;
    confirmLabel: string;
    task: () => Promise<unknown>;
    done: string;
}

function StatusNote({ tone = 'info', children }: { tone?: 'info' | 'ok' | 'warn' | 'danger'; children: ReactNode }) {
    return (
        <p
            role="status"
            aria-live="polite"
            className={clsx(
                'rounded-lg border px-3 py-2 text-xs',
                tone === 'ok' && 'border-ok/30 bg-ok-soft text-ok',
                tone === 'warn' && 'border-warn/30 bg-warn-soft text-text-2',
                tone === 'danger' && 'border-danger/30 bg-danger-soft text-danger',
                tone === 'info' && 'border-edge bg-surface-2 text-text-2',
            )}
        >
            {children}
        </p>
    );
}

function SourceCheckboxes({
    legend,
    value,
    onChange,
    disabled,
    idPrefix,
}: {
    legend: string;
    value: M365Source[];
    onChange: (next: M365Source[]) => void;
    disabled?: boolean;
    idPrefix: string;
}) {
    return (
        <fieldset disabled={disabled}>
            <legend className="text-sm font-medium text-text-1">{legend}</legend>
            <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
                {M365_SOURCES.map((source) => (
                    <label key={source} htmlFor={`${idPrefix}-${source}`} className="inline-flex items-center gap-2 text-sm text-text-1">
                        <input
                            id={`${idPrefix}-${source}`}
                            type="checkbox"
                            checked={value.includes(source)}
                            onChange={(event) => onChange(
                                event.target.checked
                                    ? m365Sources([...value, source])
                                    : value.filter((item) => item !== source),
                            )}
                        />
                        {SHORT_SOURCE_LABELS[source]}
                    </label>
                ))}
            </div>
            <p className="mt-2 text-xs text-text-3">{SOURCE_PERMISSIONS_HELP}</p>
        </fieldset>
    );
}

// ── Sharing preferences ─────────────────────────────────────────────────────

interface Preferences {
    sources: Record<M365Source, SharingChoice>;
    extended_analysis: Record<AnalysisSource, AnalysisChoice>;
}

/** Validates the server's preferences; an unknown value is refused rather than guessed. */
export function readM365Preferences(value: unknown): Preferences {
    const raw = (value ?? {}) as { sources?: Record<string, unknown>; extended_analysis?: Record<string, unknown> };
    const sources = {} as Record<M365Source, SharingChoice>;
    for (const source of M365_SOURCES) {
        const choice = raw.sources?.[source];
        if (typeof choice !== 'string' || !(choice in SHARING_LABELS)) {
            throw new Error('The server returned an unsupported sharing preference. No changes have been made.');
        }
        sources[source] = choice as SharingChoice;
    }
    const analysis = {} as Record<AnalysisSource, AnalysisChoice>;
    for (const source of ANALYSIS_SOURCES) {
        const choice = raw.extended_analysis?.[source];
        if (typeof choice !== 'string' || !(choice in ANALYSIS_LABELS)) {
            throw new Error('The server returned an unsupported analysis preference. No changes have been made.');
        }
        analysis[source] = choice as AnalysisChoice;
    }
    return { sources, extended_analysis: analysis };
}

function samePreferences(left: Preferences | null, right: Preferences | null): boolean {
    return JSON.stringify(left) === JSON.stringify(right);
}

function SharingCard({
    refreshKey,
    onRevoke,
}: {
    refreshKey: number;
    onRevoke: (pending: PendingRevocation) => void;
}) {
    const [stored, setStored] = useState<Preferences | null>(null);
    const [draft, setDraft] = useState<Preferences | null>(null);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

    useEffect(() => {
        const controller = new AbortController();
        m365Request<{ preferences?: unknown }>('/api/m365/preferences', { signal: controller.signal })
            .then((response) => {
                const preferences = readM365Preferences(response.preferences);
                setStored(preferences);
                setDraft(preferences);
                setLoadError(null);
            })
            .catch((error) => {
                if (!controller.signal.aborted) setLoadError(errorText(error, 'Microsoft 365 preferences could not be loaded.'));
            });
        return () => controller.abort();
    }, [refreshKey]);

    const save = async () => {
        if (!draft) return;
        setSaving(true);
        try {
            const response = await m365Request<{ preferences?: unknown }>('/api/m365/preferences', {
                method: 'PATCH',
                body: draft,
            });
            const preferences = readM365Preferences(response.preferences);
            setStored(preferences);
            setDraft(preferences);
            toast.success('Microsoft 365 preferences saved. Previously published history is unchanged.');
        } catch (error) {
            toast.error(errorText(error, 'Microsoft 365 preferences could not be saved.'));
        } finally {
            setSaving(false);
        }
    };

    return (
        <SettingsCard
            title="Microsoft 365 sharing"
            sectionId="m365-sharing"
            Icon={Share2}
            description="How readily evidence from your Calendar, Email, OneDrive and SharePoint is shared into conversations. Sharing publishes the generated answer and its retained evidence to every participant, including people without access at the source."
            actions={(
                <button
                    type="button"
                    onClick={() => void save()}
                    disabled={!draft || saving || samePreferences(stored, draft)}
                    className={PRIMARY_BUTTON}
                >
                    {saving ? 'Saving…' : 'Save'}
                </button>
            )}
        >
            {loadError ? (
                <StatusNote tone="danger">{loadError}</StatusNote>
            ) : !draft ? (
                <StatusNote>Loading Microsoft 365 preferences…</StatusNote>
            ) : (
                <div className="space-y-4">
                    <div className="grid gap-3 lg:grid-cols-2">
                        {M365_SOURCES.map((source) => (
                            <div key={source} className="flex flex-col rounded-xl border border-edge p-3">
                                <label className="block">
                                    <span className="block text-sm font-medium text-text-1">{M365_SOURCE_LABELS[source]}</span>
                                    <select
                                        value={draft.sources[source]}
                                        onChange={(event) => setDraft({
                                            ...draft,
                                            sources: { ...draft.sources, [source]: event.target.value as SharingChoice },
                                        })}
                                        className={SELECT_CLASS}
                                    >
                                        {(Object.keys(SHARING_LABELS) as SharingChoice[]).map((choice) => (
                                            <option key={choice} value={choice}>{SHARING_LABELS[choice]}</option>
                                        ))}
                                    </select>
                                </label>
                                {(source === 'onedrive' || source === 'spo') && (
                                    <label className="mt-3 block">
                                        <span className="block text-sm font-medium text-text-1">Extended analysis</span>
                                        <select
                                            value={draft.extended_analysis[source]}
                                            onChange={(event) => setDraft({
                                                ...draft,
                                                extended_analysis: {
                                                    ...draft.extended_analysis,
                                                    [source]: event.target.value as AnalysisChoice,
                                                },
                                            })}
                                            className={SELECT_CLASS}
                                        >
                                            {(Object.keys(ANALYSIS_LABELS) as AnalysisChoice[]).map((choice) => (
                                                <option key={choice} value={choice}>{ANALYSIS_LABELS[choice]}</option>
                                            ))}
                                        </select>
                                    </label>
                                )}
                                <div className="mt-auto pt-3">
                                    <button
                                        type="button"
                                        className={DANGER_BUTTON}
                                        onClick={() => onRevoke({
                                            title: `Revoke ${M365_SOURCE_LABELS[source]} sharing approvals?`,
                                            description: `Existing ${M365_SOURCE_LABELS[source]} sharing approvals end, and you are asked again before anything else is published.`,
                                            confirmLabel: 'Revoke',
                                            task: () => m365Request(`/api/m365/sources/${encodeURIComponent(source)}/revoke`, {
                                                method: 'POST',
                                                body: {},
                                            }),
                                            done: `${M365_SOURCE_LABELS[source]} sharing approvals revoked.`,
                                        })}
                                    >
                                        Revoke approvals
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                    <dl className="grid gap-1 text-xs sm:grid-cols-[10rem_minmax(0,1fr)]">
                        <dt className="font-medium text-text-2">Browser timezone</dt>
                        <dd className="text-text-1">{timezone || 'Unavailable; confirm it when approving sharing.'}</dd>
                    </dl>
                    <p className="text-xs text-text-3">
                        You confirm your timezone with each sharing approval; it is not stored here. "Today" ends at the
                        next local midnight in that timezone. Saving a preferred duration does not itself approve
                        publication: you still acknowledge each share, an action can require a shorter duration, and
                        changing a source's preference ends its earlier approvals. Private chats need no sharing
                        acknowledgement.
                    </p>
                </div>
            )}
        </SettingsCard>
    );
}

// ── Chat connection ─────────────────────────────────────────────────────────

interface ChatConnection {
    status?: string;
    sources?: unknown;
}

function ChatConnectionCard({ refreshKey }: { refreshKey: number }) {
    const [connection, setConnection] = useState<{ status: string; sources: M365Source[] } | null>(null);
    const [selected, setSelected] = useState<M365Source[]>([]);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [connecting, setConnecting] = useState(false);
    const [reload, setReload] = useState(0);

    useEffect(() => {
        const controller = new AbortController();
        m365Request<{ connection?: ChatConnection }>('/api/m365/chat/connection', { signal: controller.signal })
            .then((response) => {
                const status = response.connection?.status;
                const rawSources = response.connection?.sources;
                const sources = m365Sources(rawSources);
                if (
                    typeof status !== 'string'
                    || !(status in CHAT_STATUS_TEXT)
                    || !Array.isArray(rawSources)
                    || sources.length !== rawSources.length
                ) {
                    throw new Error('The chat sign-in status could not be verified. Refresh before trying again.');
                }
                setConnection({ status, sources });
                setSelected(sources);
                setLoadError(null);
            })
            .catch((error) => {
                if (!controller.signal.aborted) setLoadError(errorText(error, 'The chat sign-in status could not be loaded.'));
            });
        return () => controller.abort();
    }, [refreshKey, reload]);

    const connect = async () => {
        if (!selected.length) {
            toast.error('Select at least one source to reconnect for chat.');
            return;
        }
        setConnecting(true);
        try {
            await connectMicrosoft365(selected);
            toast.success('Microsoft 365 is connected for chat. Retry your original question in the conversation.');
            setReload((value) => value + 1);
        } catch (error) {
            toast.error(errorText(error, 'Microsoft 365 sign-in could not start.'));
        } finally {
            setConnecting(false);
        }
    };

    return (
        <SettingsCard
            title="Chat connection"
            sectionId="m365-chat-connection"
            Icon={MessageSquare}
            description="Your Microsoft 365 sign-in for chat in this browser session. Chat uses it to read the sources you allow, and asks you to connect when one needs more permission. It needs neither Key Vault nor a saved workflow connection, and reconnecting leaves sharing approvals, workflow credentials and workflow authorizations unchanged."
        >
            <div className="space-y-4">
                {loadError ? (
                    <StatusNote tone="danger">{loadError}</StatusNote>
                ) : !connection ? (
                    <StatusNote>Loading chat sign-in status…</StatusNote>
                ) : (
                    <StatusNote tone={connection.status === 'reconnect_required' ? 'warn' : connection.status === 'available' ? 'ok' : 'info'}>
                        {describeChatConnection(connection.status, connection.sources)}
                    </StatusNote>
                )}
                <SourceCheckboxes
                    legend="Sources to connect for chat"
                    value={selected}
                    onChange={setSelected}
                    disabled={!connection || connecting}
                    idPrefix="m365-chat-source"
                />
                <button
                    type="button"
                    onClick={() => void connect()}
                    disabled={!connection || connecting}
                    className={PRIMARY_BUTTON}
                >
                    {connecting ? <Loader2 size={14} className="animate-spin" /> : <Cable size={14} />}
                    Reconnect Microsoft 365 for chat
                </button>
            </div>
        </SettingsCard>
    );
}

// ── Workflow connection and authorizations ──────────────────────────────────

interface WorkflowConnection {
    id?: string;
    status?: string;
    account_username?: string;
    tenant_id?: string;
    cloud?: string;
    sources?: unknown;
    authorized_scopes?: unknown;
}

interface WorkflowAvailability {
    available: boolean;
    message: string;
}

/** Whether this deployment can save workflow connections, as the server reports it. */
export function readWorkflowAvailability(value: unknown): WorkflowAvailability {
    const raw = (value ?? {}) as { available?: unknown; message?: unknown };
    // An older server that does not report readiness is treated as ready; Connect then says why if not.
    if (raw.available !== false) return { available: true, message: '' };
    return {
        available: false,
        message: typeof raw.message === 'string' && raw.message.trim()
            ? raw.message.trim()
            : 'Workflow connections are not set up on this deployment yet. Ask an administrator.',
    };
}

function WorkflowConnectionCard({
    refreshKey,
    onRevoke,
    onConnected,
}: {
    refreshKey: number;
    onRevoke: (pending: PendingRevocation) => void;
    onConnected: () => void;
}) {
    const [connection, setConnection] = useState<WorkflowConnection | null | undefined>(undefined);
    const [availability, setAvailability] = useState<WorkflowAvailability>({ available: true, message: '' });
    const [selected, setSelected] = useState<M365Source[]>([]);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [connecting, setConnecting] = useState(false);

    useEffect(() => {
        const controller = new AbortController();
        m365Request<{ connection?: WorkflowConnection | null; workflow_connections?: unknown }>(
            '/api/m365/connections',
            { signal: controller.signal },
        )
            .then((response) => {
                if (!Object.prototype.hasOwnProperty.call(response, 'connection')) {
                    throw new Error('The workflow connection status could not be verified.');
                }
                setConnection(response.connection ?? null);
                setAvailability(readWorkflowAvailability(response.workflow_connections));
                setSelected(m365Sources(response.connection?.sources));
                setLoadError(null);
            })
            .catch((error) => {
                if (!controller.signal.aborted) setLoadError(errorText(error, 'The workflow connection could not be loaded.'));
            });
        return () => controller.abort();
    }, [refreshKey]);

    const connect = async () => {
        if (!selected.length) {
            toast.error('Select at least one source to connect for workflows.');
            return;
        }
        setConnecting(true);
        try {
            // A popup, so the result comes back here rather than to a classic page.
            await connectMicrosoft365Workflow(selected);
            toast.success('Microsoft 365 is connected for workflows. Each Run as workflow still needs your authorization.');
            onConnected();
        } catch (error) {
            toast.error(errorText(error, 'The workflow connection could not start.'));
        } finally {
            setConnecting(false);
        }
    };

    const status = connection?.status || 'disconnected';
    const scopes = Array.isArray(connection?.authorized_scopes)
        ? connection.authorized_scopes.filter((scope): scope is string => typeof scope === 'string')
        : [];
    const details: [string, string][] = [
        ['Account', connection?.account_username || 'Not connected'],
        ['Tenant', connection?.tenant_id || 'Not connected'],
        ['Cloud', connection?.cloud || 'Deployment configuration'],
        ['Authorized sources', m365Sources(connection?.sources).map((source) => M365_SOURCE_LABELS[source]).join(', ') || 'None'],
        ['Delegated permissions', scopes.join(', ') || 'None'],
    ];
    const blocked = !availability.available;

    return (
        <SettingsCard
            title="Workflow connection"
            sectionId="m365-workflow-connection"
            Icon={Workflow}
            description="A saved Microsoft 365 sign-in that workflows can run as. It is separate from chat sign-in, sharing preferences and workflow approval: each Run as workflow revision still needs your explicit authorization, and a disconnected workflow account does not affect chat."
        >
            <div className="space-y-4">
                {loadError ? (
                    <StatusNote tone="danger">{loadError}</StatusNote>
                ) : connection === undefined ? (
                    <StatusNote>Loading workflow connection…</StatusNote>
                ) : (
                    <>
                        {blocked ? <StatusNote tone="warn">{availability.message}</StatusNote> : null}
                        <StatusNote tone={status === 'connected' ? 'ok' : 'info'}>
                            Workflow connection: {spaced(status)}.
                        </StatusNote>
                        <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[10rem_minmax(0,1fr)]">
                            {details.map(([label, value]) => (
                                <div key={label} className="contents">
                                    <dt className="font-medium text-text-2">{label}</dt>
                                    <dd className="break-words text-text-1">{value}</dd>
                                </div>
                            ))}
                        </dl>
                    </>
                )}
                <SourceCheckboxes
                    legend="Sources to connect for workflows"
                    value={selected}
                    onChange={setSelected}
                    disabled={connection === undefined || connecting || blocked}
                    idPrefix="m365-workflow-source"
                />
                <div className="flex flex-wrap gap-2">
                    <button
                        type="button"
                        onClick={() => void connect()}
                        disabled={connection === undefined || connecting || blocked}
                        className={PRIMARY_BUTTON}
                    >
                        {connecting ? <Loader2 size={14} className="animate-spin" /> : <Cable size={14} />}
                        {connection?.id && status !== 'disconnected' ? 'Reconnect for workflows' : 'Connect for workflows'}
                    </button>
                    <button
                        type="button"
                        disabled={!connection?.id || status === 'disconnected'}
                        className={DANGER_BUTTON}
                        onClick={() => {
                            const connectionId = connection?.id;
                            if (!connectionId) return;
                            onRevoke({
                                title: 'Disconnect the workflow account?',
                                description: 'Workflows can no longer run as this account, and its workflow authorizations stop working. You stay signed in to other applications.',
                                confirmLabel: 'Disconnect',
                                task: () => m365Request('/api/m365/connections/disconnect', {
                                    method: 'POST',
                                    body: { connection_id: connectionId },
                                }),
                                done: 'Workflow account disconnected.',
                            });
                        }}
                    >
                        <Unplug size={14} />
                        Disconnect
                    </button>
                </div>
                <p className="text-xs text-text-3">
                    A saved workflow sign-in is encrypted with this deployment's key in Key Vault, which SimpleChat
                    creates the first time anyone connects. There is no plaintext or application-identity fallback.
                </p>
            </div>
        </SettingsCard>
    );
}

function WorkflowAuthorizationsCard({
    refreshKey,
    onRevoke,
}: {
    refreshKey: number;
    onRevoke: (pending: PendingRevocation) => void;
}) {
    const [items, setItems] = useState<M365Binding[] | null>(null);
    const [continuation, setContinuation] = useState<string | null>(null);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [loadingMore, setLoadingMore] = useState(false);

    const loadPage = useCallback(async (token: string | null, signal?: AbortSignal) => {
        const query = new URLSearchParams({ page_size: '20' });
        if (token) query.set('continuation_token', token);
        const response = await m365Request<{ items?: unknown; continuation_token?: string | null }>(
            `/api/m365/bindings?${query}`,
            { signal },
        );
        if (!Array.isArray(response.items)) {
            throw new Error('Workflow authorizations could not be read.');
        }
        return { items: response.items as M365Binding[], next: response.continuation_token || null };
    }, []);

    useEffect(() => {
        const controller = new AbortController();
        loadPage(null, controller.signal)
            .then((page) => {
                setItems(page.items);
                setContinuation(page.next);
                setLoadError(null);
            })
            .catch((error) => {
                if (!controller.signal.aborted) setLoadError(errorText(error, 'Workflow authorizations could not be loaded.'));
            });
        return () => controller.abort();
    }, [refreshKey, loadPage]);

    const loadMore = async () => {
        if (!continuation) return;
        setLoadingMore(true);
        try {
            const page = await loadPage(continuation);
            setItems((current) => [...(current ?? []), ...page.items]);
            setContinuation(page.next);
        } catch (error) {
            toast.error(errorText(error, 'More authorizations could not be loaded.'));
        } finally {
            setLoadingMore(false);
        }
    };

    return (
        <SettingsCard
            title="Workflow authorizations"
            sectionId="m365-workflow-authorizations"
            Icon={KeyRound}
            description="The workflow revisions you have allowed to run as your Microsoft 365 account. Only your own authorizations are listed; decide pending requests from Approvals."
            actions={(
                <Link to={M365_APPROVALS_HREF} className={SECONDARY_BUTTON}>
                    Open Approvals
                </Link>
            )}
        >
            {loadError ? (
                <StatusNote tone="danger">{loadError}</StatusNote>
            ) : items === null ? (
                <StatusNote>Loading workflow authorizations…</StatusNote>
            ) : items.length === 0 ? (
                <p className="text-xs text-text-3">No workflow authorizations.</p>
            ) : (
                <ul className="space-y-2">
                    {items.map((binding) => (
                        <li key={binding.id} className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-edge p-3">
                            <div className="min-w-0 flex-1 basis-64">
                                <p className="text-sm font-medium break-words text-text-1">
                                    Workflow {binding.context?.workflow_id || 'authorization'}
                                </p>
                                <p className="mt-0.5 text-xs break-words text-text-3">{describeBinding(binding)}</p>
                            </div>
                            {(binding.status === 'pending' || binding.status === 'approved') && (
                                <button
                                    type="button"
                                    className={DANGER_BUTTON}
                                    onClick={() => onRevoke({
                                        title: 'Revoke this workflow authorization?',
                                        description: "This workflow revision can no longer use your Microsoft 365 account.",
                                        confirmLabel: 'Revoke',
                                        task: () => m365Request(`/api/m365/bindings/${encodeURIComponent(binding.id)}/revoke`, {
                                            method: 'POST',
                                            body: {},
                                        }),
                                        done: 'Workflow authorization revoked.',
                                    })}
                                >
                                    Revoke
                                </button>
                            )}
                        </li>
                    ))}
                </ul>
            )}
            {continuation && (
                <button
                    type="button"
                    onClick={() => void loadMore()}
                    disabled={loadingMore}
                    className={clsx(SECONDARY_BUTTON, 'mt-3')}
                >
                    {loadingMore ? <Loader2 size={14} className="animate-spin" /> : null}
                    Load more authorizations
                </button>
            )}
        </SettingsCard>
    );
}

// ── Section ─────────────────────────────────────────────────────────────────

/**
 * Every Microsoft 365 card, sharing one confirmation dialog and one refresh, so a
 * revocation in one card refreshes the state shown in the others.
 */
export function M365Cards() {
    const [refreshKey, setRefreshKey] = useState(0);
    const [pending, setPending] = useState<PendingRevocation | null>(null);
    const [busy, setBusy] = useState(false);
    const [revokeError, setRevokeError] = useState<string | null>(null);

    const confirm = async () => {
        if (!pending || busy) return;
        setBusy(true);
        setRevokeError(null);
        try {
            await pending.task();
            toast.success(pending.done);
            setPending(null);
            setRefreshKey((value) => value + 1);
        } catch (error) {
            setRevokeError(errorText(error, 'The change could not be made. No permission has been changed.'));
        } finally {
            setBusy(false);
        }
    };

    const openRevocation = (next: PendingRevocation) => {
        setRevokeError(null);
        setPending(next);
    };

    return (
        <>
            <div className="flex justify-end">
                <button
                    type="button"
                    onClick={() => setRefreshKey((value) => value + 1)}
                    className={SECONDARY_BUTTON}
                >
                    <RefreshCw size={14} aria-hidden="true" />
                    Refresh Microsoft 365 status
                </button>
            </div>
            <SharingCard refreshKey={refreshKey} onRevoke={openRevocation} />
            <ChatConnectionCard refreshKey={refreshKey} />
            <WorkflowConnectionCard
                refreshKey={refreshKey}
                onRevoke={openRevocation}
                onConnected={() => setRefreshKey((value) => value + 1)}
            />
            <WorkflowAuthorizationsCard refreshKey={refreshKey} onRevoke={openRevocation} />

            {pending && (
                <ConfirmDialog
                    title={pending.title}
                    confirmLabel={pending.confirmLabel}
                    busy={busy}
                    onConfirm={() => void confirm()}
                    onClose={() => {
                        if (!busy) setPending(null);
                    }}
                >
                    <p className="text-xs text-text-2">{pending.description}</p>
                    <p className="mt-2 text-xs text-text-3">
                        Answers and evidence already published to conversations are not removed.
                    </p>
                    {revokeError && (
                        <p role="alert" className="mt-3 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
                            {revokeError}
                        </p>
                    )}
                </ConfirmDialog>
            )}
        </>
    );
}
