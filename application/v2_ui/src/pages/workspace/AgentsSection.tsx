// AgentsSection.tsx

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { LayoutGrid, List, Plus, RefreshCw, Sparkles, Trash2 } from 'lucide-react';
import { EmptyState, GlassButton, GlassPanel } from '../../components/ui/primitives';
import { ConfirmAction, Pill, SectionIntro, SectionSearch, SectionSkeleton } from '../../components/workspace/primitives';
import { errorMessage, useSectionResource } from '../../components/workspace/useSectionResource';
import { AgentIcon } from '../../components/workspaceAgents/AgentIdentityFields';
import { AgentNotice } from '../../components/workspaceAgents/AgentFields';
import { deleteAuthoringAgent, fetchAuthoringAgents } from '../../lib/workspaceAuthoringApi';
import type { AgentConfiguration } from '../../lib/workspaceAuthoring';
import { AGENT_INPUT_CLASS, AGENT_TYPE_LABELS, agentText } from '../../lib/workspaceAgentAuthoring';
import { readAgentKnowledge } from '../../lib/workspaceAgentKnowledge';
import { useBootstrapStore } from '../../stores/bootstrapStore';

let collectionState = { owner: '', query: '', type: '', scope: '', view: 'list', scrollTop: 0 };

export function AgentsSection({ actionsEnabled }: { actionsEnabled: boolean }) {
    const owner = useBootstrapStore((state) => state.data?.user?.id ?? '');
    const refreshBootstrap = useBootstrapStore((state) => state.refresh);
    const navigate = useNavigate();
    const location = useLocation();
    const list = useRef<HTMLDivElement>(null);
    const scrollRestored = useRef(false);
    const { items, loading, error, refresh, setItems, setError } =
        useSectionResource<AgentConfiguration>(fetchAuthoringAgents, 'Failed to load agents.');
    const [filters, setFilters] = useState(() => {
        if (collectionState.owner !== owner) collectionState = { owner, query: '', type: '', scope: '', view: 'list', scrollTop: 0 };
        return { ...collectionState };
    });
    const [busyId, setBusyId] = useState<string | null>(null);
    useEffect(() => {
        if (filters.owner !== owner) {
            collectionState = { owner, query: '', type: '', scope: '', view: 'list', scrollTop: 0 };
            setFilters(collectionState);
            scrollRestored.current = false;
        }
        else collectionState = { ...filters, scrollTop: collectionState.scrollTop };
    }, [filters, owner]);
    useEffect(() => {
        if (!loading && !error && items.length && !scrollRestored.current && list.current) {
            list.current.scrollTop = collectionState.scrollTop;
            scrollRestored.current = true;
        }
    }, [loading, error, items.length]);
    const visible = useMemo(() => items.filter((agent) => {
        const label = AGENT_TYPE_LABELS[agent.agent_type] ?? agent.agent_type;
        return `${agent.display_name} ${agent.name} ${agent.description} ${agent.agent_type} ${label}`.toLowerCase().includes(filters.query.trim().toLowerCase()) &&
            (!filters.type || filters.type === agent.agent_type) &&
            (!filters.scope || (filters.scope === 'provided') === Boolean(agent.is_global));
    }), [items, filters]);
    const remove = async (agent: AgentConfiguration) => {
        if (agent.is_global) return;
        setBusyId(agent.id);
        setError(null);
        try {
            await deleteAuthoringAgent(agent.id);
            setItems(items.filter((item) => item.is_global || item.id !== agent.id));
            await Promise.all([refresh(), refreshBootstrap()]);
        } catch (cause) {
            setError(errorMessage(cause, 'Could not delete the agent.'));
        } finally {
            setBusyId(null);
        }
    };

    return (
        <div className="flex h-full min-h-0 flex-col gap-4">
            <link rel="stylesheet" href="/static/css/bootstrap-icons.css" />
            <div className="shrink-0 space-y-4">
                <SectionIntro title="Agents"
                    description="Build reusable assistants with their own model, instructions, knowledge, and actions. Provided agents can be viewed and used, but not changed here."
                    actions={<GlassButton type="button" variant="primary" size="sm" onClick={() => navigate('/workspace/agents/new')}><Plus size={14} />New agent</GlassButton>} />
                <div className="flex flex-wrap items-center gap-2">
                    <GlassButton type="button" size="sm" onClick={() => navigate('/workspace/agents/new?templates=1')}><Sparkles size={14} />Examples &amp; templates</GlassButton>
                    <GlassButton type="button" size="sm" disabled={loading} onClick={() => void refresh()}><RefreshCw size={14} />Refresh</GlassButton>
                    <div className="ml-auto flex gap-1" aria-label="Agent browsing view">
                        <GlassButton type="button" size="icon" aria-label="List view" aria-pressed={filters.view === 'list'} onClick={() => setFilters((current) => ({ ...current, view: 'list' }))}><List size={17} /></GlassButton>
                        <GlassButton type="button" size="icon" aria-label="Card view" aria-pressed={filters.view === 'cards'} onClick={() => setFilters((current) => ({ ...current, view: 'cards' }))}><LayoutGrid size={17} /></GlassButton>
                    </div>
                </div>
                <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_10rem_9rem]">
                    <SectionSearch value={filters.query} onChange={(query) => setFilters((current) => ({ ...current, query }))} placeholder="Search agents by name, description or type" />
                    <select aria-label="Filter agent type" value={filters.type} className={AGENT_INPUT_CLASS} onChange={(event) => setFilters((current) => ({ ...current, type: event.target.value }))}>
                        <option value="">All agent types</option>
                        {Object.entries(AGENT_TYPE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                    <select aria-label="Filter agent scope" value={filters.scope} className={AGENT_INPUT_CLASS} onChange={(event) => setFilters((current) => ({ ...current, scope: event.target.value }))}>
                        <option value="">All ownership</option><option value="personal">Personal</option><option value="provided">Provided</option>
                    </select>
                </div>
                {error ? <AgentNotice error>{error}</AgentNotice> : null}
                {location.state?.workspaceEditorSaved === true ? <p role="status" className="text-xs text-ok">Agent saved.</p> : null}
            </div>
            <div ref={list} className="min-h-0 flex-1 overflow-y-auto pb-4 pr-1"
                onScroll={(event) => { collectionState.scrollTop = event.currentTarget.scrollTop; }}>
                {loading ? <SectionSkeleton /> : null}
                {!loading && !visible.length && !error ? <EmptyState icon={<Sparkles size={28} />}
                    title={items.length ? 'No agents match your search' : 'No agents yet'}
                    description={items.length ? 'Try another name, description or type.' : 'Create an agent or start from an approved template.'} /> : null}
                <ul className={filters.view === 'cards' ? 'grid gap-3 lg:grid-cols-2 2xl:grid-cols-3' : 'space-y-3'}>
                    {visible.map((agent) => {
                        const provided = Boolean(agent.is_global);
                        const label = agent.display_name || agent.name || 'Untitled agent';
                        const path = `/workspace/agents/${encodeURIComponent(agent.id)}${provided ? '?scope=global' : ''}`;
                        const knowledge = readAgentKnowledge(agent);
                        return (
                            <li key={`${provided ? 'global' : 'personal'}:${agent.id}`} className="min-w-0">
                                <GlassPanel elevation="flat" className={`h-full p-4 ${filters.view === 'cards' ? 'space-y-3' : 'flex flex-wrap items-start gap-3'}`}>
                                    <div className="flex min-w-0 flex-1 items-start gap-3">
                                        <AgentIcon icon={agent.icon} />
                                        <div className="min-w-0 flex-1">
                                            <h3 className="break-words text-sm font-semibold text-text-1"><Link to={path} className="hover:text-accent hover:underline">{label}</Link></h3>
                                            <p className="mt-1 break-words text-sm text-text-3">{agent.description}</p>
                                            <div className="mt-2 flex flex-wrap items-center gap-2">
                                                <Pill>{AGENT_TYPE_LABELS[agent.agent_type] || agent.agent_type}</Pill>
                                                <Pill tone={provided ? 'accent' : 'neutral'}>{provided ? 'Provided · read only' : 'Personal'}</Pill>
                                                {agent.is_enabled === false ? <Pill tone="warn">Disabled</Pill> : null}
                                            </div>
                                            <p className="mt-2 break-words text-xs text-text-3">
                                                {agent.model_id || agent.azure_openai_gpt_deployment || agent.azure_agent_apim_gpt_deployment || (agent.agent_type === 'local' ? 'Configured model default' : 'Foundry-managed model')}
                                                {' · '}{agent.actions_to_load?.length ?? 0} actions{knowledge.enabled ? ` · ${knowledge.document_ids.length} explicit knowledge documents` : ''}
                                            </p>
                                            <p className="mt-1 break-all text-[10px] text-text-3">{provided ? 'global' : 'personal'} · {agent.id}</p>
                                            {agent.tags?.length ? <p className="mt-1 break-words text-xs text-text-3">{agent.tags.join(' · ')}</p> : null}
                                        </div>
                                    </div>
                                    <div className="flex flex-wrap items-center gap-2">
                                        <GlassButton type="button" size="sm" onClick={() => navigate(path)}>{provided ? 'View details' : 'Edit'}</GlassButton>
                                        {agent.is_enabled !== false ? <Link to={`/chat?agent_id=${encodeURIComponent(agent.id)}&agent_scope=${provided ? 'global' : 'personal'}&new=1`} className="rounded-lg px-2 py-1.5 text-xs font-medium text-accent hover:bg-accent-soft">Use in chat</Link> : null}
                                        {!provided ? <ConfirmAction icon={<Trash2 size={15} />} label={`Delete ${label}`} confirmLabel="Delete agent"
                                            busy={busyId === agent.id} disabled={busyId !== null} onConfirm={() => void remove(agent)} /> : null}
                                    </div>
                                </GlassPanel>
                            </li>
                        );
                    })}
                </ul>
                {!actionsEnabled ? <p className="mt-3 text-xs text-text-3">Action creation is unavailable. Agent editors can still assign permitted existing actions.</p> : null}
                {loading && items.length ? <p className="mt-2 text-xs text-text-3">Refreshing the saved catalogue…</p> : null}
                {agentText(filters.query) ? <p role="status" className="mt-3 text-xs text-text-3">{visible.length} matching agents</p> : null}
            </div>
        </div>
    );
}
