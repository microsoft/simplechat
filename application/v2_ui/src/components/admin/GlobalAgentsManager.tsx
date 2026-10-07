// GlobalAgentsManager.tsx
// The organisation's global agents, listed and managed from Admin Settings.
//
// The agents themselves are edited in the same V2 agent editor workspaces use, at
// /admin/agents/<id>. This list carries what the classic admin table offered around it:
// creating one (from scratch or an approved template), enabling or disabling one, making
// one the default, and deleting one. Each change saves on its own rather than through the
// settings save bar, because these are records, not settings.

import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AlertCircle, Loader2, Pencil, Plus, Power, RefreshCw, Sparkles, Star, Trash2 } from 'lucide-react';
import { api } from '../../lib/apiClient';
import { fetchGlobalAgentCatalog, GLOBAL_AGENT_WORKBENCH } from '../../lib/agentWorkbench';
import { AGENT_TYPE_LABELS } from '../../lib/workspaceAgentAuthoring';
import { GLOBAL_AGENTS_BASE_PATH, type AgentConfiguration } from '../../lib/workspaceAuthoring';
import { toast } from '../../stores/toastStore';
import { GlassButton } from '../ui/primitives';
import { ConfirmAction, RowAction, SectionSearch } from '../workspace/primitives';
import { AgentIcon } from '../workspaceAgents/AgentIdentityFields';
import { AdminListPill } from './AdminListPill';

/** Search appears once a list is long enough to need it, as it does for AI Connections. */
const SEARCH_THRESHOLD = 4;

interface EnabledResponse {
    success?: boolean;
    fallback_agent_name?: string | null;
}

function agentLabel(agent: AgentConfiguration): string {
    return agent.display_name || agent.name || 'Untitled agent';
}

function failure(cause: unknown, fallback: string): string {
    return cause instanceof Error && cause.message ? cause.message : fallback;
}

function modelSummary(agent: AgentConfiguration): string {
    if (agent.agent_type && agent.agent_type !== 'local') return 'Foundry-managed model';
    return agent.model_id || agent.azure_openai_gpt_deployment || agent.azure_agent_apim_gpt_deployment
        || 'Default model';
}

export function GlobalAgentsManager({ help, templatesEnabled }: { help?: string; templatesEnabled: boolean }) {
    const navigate = useNavigate();
    const [agents, setAgents] = useState<AgentConfiguration[] | null>(null);
    const [defaultName, setDefaultName] = useState('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState<string | null>(null);
    const [query, setQuery] = useState('');
    const [revision, setRevision] = useState(0);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError(null);
        void fetchGlobalAgentCatalog(controller.signal).then((catalog) => {
            if (controller.signal.aborted) return;
            setAgents(catalog.agents);
            setDefaultName(catalog.selectedAgentName);
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) setError(failure(cause, 'Could not load the global agents.'));
        }).finally(() => {
            if (!controller.signal.aborted) setLoading(false);
        });
        return () => controller.abort();
    }, [revision]);

    const reload = () => setRevision((value) => value + 1);

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        return [...(agents ?? [])]
            .filter((agent) => !needle || `${agentLabel(agent)} ${agent.name} ${agent.description}`.toLowerCase().includes(needle))
            .sort((left, right) => agentLabel(left).localeCompare(agentLabel(right)));
    }, [agents, query]);

    /** Run one change, report it, and re-read the list so every row shows the stored state. */
    const change = async (key: string, work: () => Promise<string>) => {
        setBusy(key);
        setError(null);
        try {
            toast.success(await work());
            reload();
        } catch (cause) {
            setError(failure(cause, 'The change could not be saved.'));
        } finally {
            setBusy(null);
        }
    };

    const toggleEnabled = (agent: AgentConfiguration) => change(`enabled:${agent.id}`, async () => {
        const enable = agent.is_enabled === false;
        const result = await api.patch<EnabledResponse>(
            `/api/admin/agents/${encodeURIComponent(agent.name)}/enabled`, { is_enabled: enable },
        );
        const label = agentLabel(agent);
        if (result.fallback_agent_name) {
            // The route names the new default by its stored name; show the name people see.
            const fallback = agents?.find((item) => item.name === result.fallback_agent_name);
            return `${label} disabled. ${fallback ? agentLabel(fallback) : result.fallback_agent_name} is now the default agent.`;
        }
        return `${label} ${enable ? 'enabled' : 'disabled'}.`;
    });

    const makeDefault = (agent: AgentConfiguration) => change(`default:${agent.id}`, async () => {
        await api.post('/api/admin/agents/selected_agent', { name: agent.name });
        return `${agentLabel(agent)} is now the default agent.`;
    });

    const remove = (agent: AgentConfiguration) => change(`delete:${agent.id}`, async () => {
        await GLOBAL_AGENT_WORKBENCH.deleteAgent(agent);
        return `${agentLabel(agent)} deleted.`;
    });

    return (
        <div className="min-w-0 space-y-3 py-3" data-testid="global-agents-manager">
            <div className="flex flex-wrap items-start justify-between gap-3">
                {help ? <p className="min-w-0 flex-[1_1_18rem] text-xs leading-relaxed text-text-3">{help}</p> : null}
                <div className="flex flex-wrap items-center gap-2">
                    <GlassButton type="button" variant="ghost" size="sm" disabled={loading} onClick={reload}>
                        <RefreshCw size={14} aria-hidden="true" />Refresh
                    </GlassButton>
                    {templatesEnabled ? (
                        <GlassButton type="button" variant="ghost" size="sm"
                            onClick={() => navigate(`${GLOBAL_AGENTS_BASE_PATH}/new?templates=1`)}>
                            <Sparkles size={14} aria-hidden="true" />Start from a template
                        </GlassButton>
                    ) : null}
                    <GlassButton type="button" variant="subtle" size="sm"
                        onClick={() => navigate(`${GLOBAL_AGENTS_BASE_PATH}/new`)}>
                        <Plus size={14} aria-hidden="true" />New agent
                    </GlassButton>
                </div>
            </div>

            {(agents?.length ?? 0) >= SEARCH_THRESHOLD ? (
                <SectionSearch value={query} onChange={setQuery} placeholder="Search global agents" />
            ) : null}

            {error ? (
                <p role="alert" className="flex items-start gap-1.5 rounded-lg bg-danger-soft px-3 py-2 text-xs text-danger">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                    {error}
                </p>
            ) : null}

            {loading && agents === null ? (
                <p role="status" className="flex items-center gap-2 py-4 text-xs text-text-3">
                    <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                    Loading global agents…
                </p>
            ) : null}

            {agents !== null && agents.length === 0 ? (
                <p className="rounded-lg border border-edge bg-surface-1 p-4 text-xs text-text-3">
                    No global agents yet. Create one, or start from an approved template, and it becomes
                    available as soon as it is saved.
                </p>
            ) : null}
            {agents !== null && agents.length > 0 && visible.length === 0 ? (
                <p role="status" className="rounded-lg border border-edge bg-surface-1 p-4 text-xs text-text-3">No global agents match “{query}”.</p>
            ) : null}

            {visible.length ? (
                <ul className="space-y-2" aria-label="Global agents">
                    {visible.map((agent) => {
                        const label = agentLabel(agent);
                        const enabled = agent.is_enabled !== false;
                        const isDefault = Boolean(defaultName) && agent.name === defaultName;
                        const editorPath = `${GLOBAL_AGENTS_BASE_PATH}/${encodeURIComponent(agent.id)}`;
                        const actionCount = agent.actions_to_load?.length ?? 0;
                        return (
                            <li key={agent.id} data-testid="global-agent-row"
                                className="flex items-start gap-3 rounded-lg border border-edge bg-surface-1 p-3">
                                <AgentIcon icon={agent.icon} />
                                <div className="min-w-0 flex-1">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <h3 className="min-w-0 break-words text-sm font-medium text-text-1">
                                            <Link to={editorPath} className="hover:text-accent hover:underline">{label}</Link>
                                        </h3>
                                        <AdminListPill tone={enabled ? 'ok' : 'muted'}>{enabled ? 'Enabled' : 'Disabled'}</AdminListPill>
                                        {isDefault ? <AdminListPill tone="accent">Default agent</AdminListPill> : null}
                                    </div>
                                    <p className="mt-0.5 break-words text-xs text-text-3">
                                        {AGENT_TYPE_LABELS[agent.agent_type] ?? agent.agent_type}{' · '}{modelSummary(agent)}
                                        {' · '}{actionCount} action{actionCount === 1 ? '' : 's'}
                                    </p>
                                    {agent.description ? (
                                        <p className="mt-1 break-words text-xs text-text-3">{agent.description}</p>
                                    ) : null}
                                    <p className="truncate font-mono text-[11px] text-text-3">{agent.name}</p>
                                    {isDefault ? (
                                        <p className="mt-1 text-[11px] text-text-3">Choose another default to delete</p>
                                    ) : null}
                                </div>
                                <div className="flex shrink-0 items-center gap-1">
                                    {enabled && !isDefault ? (
                                        <RowAction icon={<Star size={15} />} label={`Make ${label} the default agent`}
                                            busy={busy === `default:${agent.id}`} disabled={busy !== null}
                                            onClick={() => void makeDefault(agent)} />
                                    ) : null}
                                    <RowAction icon={<Power size={15} />} label={`${enabled ? 'Disable' : 'Enable'} ${label}`}
                                        busy={busy === `enabled:${agent.id}`} disabled={busy !== null}
                                        onClick={() => void toggleEnabled(agent)} />
                                    <RowAction icon={<Pencil size={15} />} label={`Edit ${label}`} onClick={() => navigate(editorPath)} />
                                    {!isDefault ? (
                                        <ConfirmAction icon={<Trash2 size={15} />} label={`Delete ${label}`} confirmLabel="Delete agent"
                                            busy={busy === `delete:${agent.id}`} disabled={busy !== null}
                                            onConfirm={() => void remove(agent)} />
                                    ) : null}
                                </div>
                            </li>
                        );
                    })}
                </ul>
            ) : null}
        </div>
    );
}
