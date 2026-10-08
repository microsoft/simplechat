// DashboardChat.tsx
// "Chat with this dashboard": open an orchestrated chat that answers from Control Center data.
//
// The chat needs three administrator settings and a Control Center action. The server reports
// each requirement; when they are all met the button goes straight to a new chat with a prompt
// describing the dashboard on screen, and otherwise it opens a checklist that marks each
// requirement met or not, with what to do. Nothing is sent for the person: they read, edit and
// send the prompt themselves.

import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { CheckCircle2, MessageSquareText, RefreshCw, XCircle } from 'lucide-react';
import { api } from '../../lib/apiClient';
import { composerDraftHandoffState } from '../../lib/composerDraftHandoff';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';

export type DashboardChatRequirement = {
    id: string;
    label: string;
    met: boolean;
    detail: string;
    remedy: string;
    settings_link: string | null;
};

export type DashboardChatReadiness = {
    ready: boolean;
    action: { name: string } | null;
    requirements: DashboardChatRequirement[];
};

export type DashboardChatContext = {
    startDate: string;
    endDate: string;
    /** The token filters in effect, already described in words, such as "model gpt-4o". */
    tokenFilters: string[];
};

const ADMIN_SETTINGS_PATH = /^\/admin\/(?:settings\/[a-z0-9-]+|actions(?:\/new\?type=[a-z_]+)?)$/;

/** Admin Settings paths from the readiness answer; anything else is dropped rather than linked. */
function safeAdminSettingsUrl(value: string | null): string | undefined {
    return value && ADMIN_SETTINGS_PATH.test(value) ? value : undefined;
}

/** The prompt a dashboard chat starts with, naming the action and the dashboard's range. */
export function buildDashboardChatPrompt(actionName: string, context: DashboardChatContext): string {
    const filters = context.tokenFilters.length
        ? ` For token usage, use the same filters as the dashboard: ${context.tokenFilters.join(', ')}.`
        : '';
    return `Using the ${actionName} action, help me understand the SimpleChat Control Center dashboard `
        + `for ${context.startDate} to ${context.endDate} (UTC). Summarize sign-ins and active users, `
        + 'conversations, document uploads and token usage, compare them with the previous period of the '
        + `same length, call out anything unusual, and chart the daily trends.${filters}`;
}

function RequirementRow({ requirement }: { requirement: DashboardChatRequirement }) {
    const Icon = requirement.met ? CheckCircle2 : XCircle;
    const settingsUrl = safeAdminSettingsUrl(requirement.settings_link);
    return (
        <li className="flex gap-3 py-3">
            <Icon size={18} aria-hidden="true"
                className={requirement.met ? 'mt-0.5 shrink-0 text-ok' : 'mt-0.5 shrink-0 text-danger'} />
            <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-text-1">
                    {requirement.label}
                    <span className={requirement.met ? 'ml-2 text-xs font-normal text-ok' : 'ml-2 text-xs font-normal text-danger'}>
                        {requirement.met ? 'Ready' : 'Needs set-up'}
                    </span>
                </p>
                {!requirement.met && requirement.detail ? <p className="mt-1 text-sm text-text-2">{requirement.detail}</p> : null}
                {!requirement.met && requirement.remedy ? <p className="mt-1 text-sm text-text-2">{requirement.remedy}</p> : null}
                {!requirement.met && settingsUrl ? (
                    <Link to={settingsUrl} className="mt-2 inline-flex text-sm font-medium text-accent underline-offset-2 hover:underline">
                        Open the setting
                    </Link>
                ) : null}
            </div>
        </li>
    );
}

export function DashboardChatButton({ context, disabled = false }: { context: DashboardChatContext; disabled?: boolean }) {
    const navigate = useNavigate();
    const [checking, setChecking] = useState(false);
    const [open, setOpen] = useState(false);
    const [readiness, setReadiness] = useState<DashboardChatReadiness | null>(null);
    const [error, setError] = useState<string | null>(null);
    const request = useRef<AbortController | null>(null);

    const check = async (): Promise<DashboardChatReadiness | null> => {
        request.current?.abort();
        const controller = new AbortController();
        request.current = controller;
        setChecking(true);
        setError(null);
        try {
            const result = await api.get<DashboardChatReadiness>(
                '/api/v2/control-center/dashboard/chat-readiness',
                controller.signal,
            );
            setReadiness(result);
            return result;
        } catch (cause) {
            if (!controller.signal.aborted) {
                setError(cause instanceof Error && cause.message ? cause.message : 'Dashboard chat requirements could not be checked.');
            }
            return null;
        } finally {
            if (request.current === controller) {
                setChecking(false);
            }
        }
    };

    const startChat = (result: DashboardChatReadiness) => {
        setOpen(false);
        navigate('/chat?new=1', {
            state: composerDraftHandoffState(
                buildDashboardChatPrompt(result.action?.name ?? 'Control Center', context),
                { orchestrate: true },
            ),
        });
    };

    const openChat = async () => {
        const result = await check();
        if (result?.ready) {
            startChat(result);
        } else {
            setOpen(true);
        }
    };

    const unmet = readiness?.requirements.filter((requirement) => !requirement.met).length ?? 0;
    return (
        <>
            <button type="button" onClick={() => void openChat()} disabled={disabled || checking}
                className="inline-flex items-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-on-accent hover:bg-accent-hover disabled:opacity-50">
                <MessageSquareText size={14} aria-hidden="true" />
                {checking && !open ? 'Checking…' : 'Chat with this dashboard'}
            </button>
            {open ? (
                <Modal
                    title="Set up dashboard chat"
                    description="Chat with this dashboard answers questions from Control Center data in an orchestrated chat."
                    onClose={() => setOpen(false)}
                    footer={(
                        <div className="flex flex-wrap items-center justify-end gap-2">
                            <GlassButton size="sm" variant="subtle" onClick={() => void check()} disabled={checking}>
                                <RefreshCw size={14} aria-hidden="true" />{checking ? 'Checking…' : 'Check again'}
                            </GlassButton>
                            <GlassButton size="sm" variant="primary" disabled={checking || !readiness?.ready}
                                onClick={() => readiness?.ready && startChat(readiness)}>
                                Start chat
                            </GlassButton>
                        </div>
                    )}
                >
                    <div aria-live="polite" className="space-y-3">
                        {error ? (
                            <p role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">
                                {error} Choose Check again to retry.
                            </p>
                        ) : null}
                        {readiness ? (
                            <>
                                <p className="text-sm text-text-2">
                                    {readiness.ready
                                        ? 'Everything is ready. Start the chat to open it with a prompt about this dashboard.'
                                        : `${unmet} of ${readiness.requirements.length} requirements need set-up before dashboard chat can run.`}
                                </p>
                                <ul aria-label="Dashboard chat requirements" className="divide-y divide-edge">
                                    {readiness.requirements.map((requirement) => (
                                        <RequirementRow key={requirement.id} requirement={requirement} />
                                    ))}
                                </ul>
                            </>
                        ) : null}
                    </div>
                </Modal>
            ) : null}
        </>
    );
}
