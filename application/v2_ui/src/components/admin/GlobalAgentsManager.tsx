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
import { AlertCircle, Loader2, Plus, RefreshCw, Sparkles, Trash2 } from 'lucide-react';
import { api } from '../../lib/apiClient';
import { fetchGlobalAgentCatalog, GLOBAL_AGENT_WORKBENCH } from '../../lib/agentWorkbench';
import { AGENT_TYPE_LABELS } from '../../lib/workspaceAgentAuthoring';
import { GLOBAL_AGENTS_BASE_PATH, type AgentConfiguration } from '../../lib/workspaceAuthoring';
import { toast } from '../../stores/toastStore';
import { GlassButton } from '../ui/primitives';
import { ConfirmAction, Pill, SectionSearch } from '../workspace/primitives';
import { AgentIcon } from '../workspaceAgents/AgentIdentityFields';

/** Search appears once a list is long enough to need it. */
const SEARCH_THRESHOLD = 6;

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
            {help ? <p className="text-xs leading-relaxed text-text-3">{help}</p> : null}

            <div className="flex flex-wrap items-center gap-2">
                <GlassButton type="button" variant="primary" size="sm"
                    onClick={() => navigate(`${GLOBAL_AGENTS_BASE_PATH}/new`)}>
                    <Plus size={14} aria-hidden="true" />New agent
                </GlassButton>
                {templatesEnabled ? (
                    <GlassButton type="button" variant="subtle" size="sm"
                        onClick={() => navigate(`${GLOBAL_AGENTS_BASE_PATH}/new?templates=1`)}>
                        <Sparkles size={14} aria-hidden="true" />Start from a template
                    </GlassButton>
                ) : null}
                <GlassButton type="button" size="sm" disabled={loading} onClick={reload}>
                    <RefreshCw size={14} aria-hidden="true" />Refresh
                </GlassButton>
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
                <p role="status" className="flex items-center gap-2 py-4 text-sm text-text-3">
                    <Loader2 size={15} className="animate-spin" aria-hidden="true" />
                    Loading global agents…
                </p>
            ) : null}

            {agents !== null && agents.length === 0 ? (
                <p className="py-4 text-sm text-text-3">
                    No global agents yet. Create one, or start from an approved template, and it becomes
                    available as soon as it is saved.
                </p>
            ) : null}
            {agents !== null && agents.length > 0 && visible.length === 0 ? (
                <p role="status" className="py-2 text-sm text-text-3">No global agents match “{query}”.</p>
            ) : null}

            {visible.length ? (
                <ul className="space-y-2" aria-label="Global agents">
                    {visible.map((agent) => {
                        const label = agentLabel(agent);
                        const enabled = agent.is_enabled !== false;
                        const isDefault = Boolean(defaultName) && agent.name === defaultName;
                        const editorPath = `${GLOBAL_AGENTS_BASE_PATH}/${encodeURIComponent(agent.id)}`;
                        return (
                            <li key={agent.id} data-testid="global-agent-row"
                                className="flex flex-wrap items-start gap-3 rounded-xl border border-edge bg-surface-1 p-3">
                                <div className="flex min-w-0 flex-[1_1_16rem] items-start gap-3">
                                    <AgentIcon icon={agent.icon} />
                                    <div className="min-w-0 flex-1">
                                        <h3 className="break-words text-sm font-semibold text-text-1">
                                            <Link to={editorPath} className="hover:text-accent hover:underline">{label}</Link>
                                        </h3>
                                        {agent.description ? (
                                            <p className="mt-0.5 break-words text-xs text-text-3">{agent.description}</p>
                                        ) : null}
                                        <div className="mt-2 flex flex-wrap items-center gap-1.5">
                                            <Pill>{AGENT_TYPE_LABELS[agent.agent_type] ?? agent.agent_type}</Pill>
                                            {isDefault ? <Pill tone="accent">Default agent</Pill> : null}
                                            {!enabled ? <Pill tone="warn">Disabled</Pill> : null}
                                        </div>
                                        <p className="mt-1.5 break-words text-[11px] text-text-3">
                                            {modelSummary(agent)}{' · '}{agent.actions_to_load?.length ?? 0} actions{' · '}{agent.name}
                                        </p>
                                    </div>
                                </div>
                                <div className="flex flex-wrap items-center gap-1.5">
                                    <GlassButton type="button" size="sm" variant="subtle" onClick={() => navigate(editorPath)}>
                                        Edit
                                    </GlassButton>
                                    {enabled && !isDefault ? (
                                        <GlassButton type="button" size="sm" disabled={busy !== null}
                                            aria-label={`Make ${label} the default agent`}
                                            onClick={() => void makeDefault(agent)}>
                                            Make default
                                        </GlassButton>
                                    ) : null}
                                    <GlassButton type="button" size="sm" disabled={busy !== null}
                                        aria-label={`${enabled ? 'Disable' : 'Enable'} ${label}`}
                                        onClick={() => void toggleEnabled(agent)}>
                                        {busy === `enabled:${agent.id}` ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : null}
                                        {enabled ? 'Disable' : 'Enable'}
                                    </GlassButton>
                                    {isDefault ? (
                                        <span className="px-1 text-[11px] text-text-3">Choose another default to delete</span>
                                    ) : (
                                        <ConfirmAction icon={<Trash2 size={15} />} label={`Delete ${label}`} confirmLabel="Delete agent"
                                            busy={busy === `delete:${agent.id}`} disabled={busy !== null}
                                            onConfirm={() => void remove(agent)} />
                                    )}
                                </div>
                            </li>
                        );
                    })}
                </ul>
            ) : null}
        </div>
    );
}
