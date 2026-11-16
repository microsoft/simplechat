// AgentsCatalogPage.tsx

import { useEffect, useMemo, useState } from 'react';
import { Bot, Info, LayoutGrid, List, Lock, Plus, RotateCcw } from 'lucide-react';
import { Link } from 'react-router-dom';
import { AgentCatalogBadges, AgentChatLink } from '../components/agentsCatalog/AgentCatalogParts';
import { AgentDetailsModal } from '../components/agentsCatalog/AgentDetailsModal';
import { PageHeader } from '../components/layout/PageHeader';
import { PlainMarkdown } from '../components/ui/PlainMarkdown';
import { EmptyState, GlassButton, GlassPanel } from '../components/ui/primitives';
import { SectionError, SectionSearch, SectionSkeleton } from '../components/workspace/primitives';
import { AgentIcon } from '../components/workspaceAgents/AgentIdentityFields';
import {
    AGENTS_CATALOG_ENDPOINT, CATALOG_VIEW_STORAGE_KEY, DEFAULT_CATALOG_PAGE, catalogAgentKey,
    catalogDisplayName, normalizeCatalogText, parseCatalogViewMode, readAgentsCatalog, tagsFor, visibleAgents,
    type AgentsCatalog, type CatalogAgent, type CatalogTab, type CatalogUsageWindow, type CatalogViewMode,
} from '../lib/agentCatalog';
import { api, ApiError } from '../lib/apiClient';
import { groupWorkspacePath } from '../lib/groupWorkspaceNavigation';
import { useBootstrapStore } from '../stores/bootstrapStore';

type LoadState = 'loading' | 'ready' | 'unavailable' | 'error';
const TABS: { value: CatalogTab; label: string }[] = [
    { value: 'popular', label: 'Popular' },
    { value: 'personal', label: 'Personal' },
    { value: 'group', label: 'Group' },
    { value: 'enterprise', label: 'Enterprise' },
];
const SELECTED_CATEGORY = 'bg-accent text-on-accent';
const CATEGORY_BUTTON = 'rounded-lg px-3 py-2 text-sm font-medium transition-colors';

function initialViewMode(): CatalogViewMode {
    try {
        return parseCatalogViewMode(window.localStorage.getItem(CATALOG_VIEW_STORAGE_KEY));
    } catch (error) {
        console.warn('Agent catalogue view preference could not be read.', error);
        return 'list';
    }
}

function AgentResult({
    agent, rank, view, onDetails,
}: {
    agent: CatalogAgent;
    rank: number | null;
    view: CatalogViewMode;
    onDetails: () => void;
}) {
    const card = view === 'card';
    return (
        <GlassPanel elevation="flat" className={`h-full p-4 ${card ? 'flex flex-col gap-3' : ''}`}>
            <article data-testid="catalog-agent" aria-label={catalogDisplayName(agent)}
                className={`flex min-w-0 gap-3 ${card ? 'h-full flex-col' : 'flex-col sm:flex-row sm:items-start'}`}>
                <div className="flex shrink-0 items-center gap-3">
                    {rank !== null ? (
                        <span aria-label={`Rank ${rank}`} className="w-6 text-center text-lg font-semibold tabular-nums text-text-3">
                            {rank}
                        </span>
                    ) : null}
                    <AgentIcon icon={agent.icon} />
                </div>
                <div className="min-w-0 flex-1 space-y-2 break-words">
                    <h3 className="text-base font-semibold text-text-1">{catalogDisplayName(agent)}</h3>
                    <AgentCatalogBadges agent={agent} />
                    <p className="line-clamp-3 text-sm leading-relaxed text-text-2">
                        {normalizeCatalogText(agent.description) || 'No description available.'}
                    </p>
                    <p className="text-xs text-text-3">{normalizeCatalogText(agent.model_label) || 'Default'}</p>
                    {agent.tags?.length ? (
                        <p className="text-xs text-text-3">{agent.tags.map(normalizeCatalogText).join(', ')}</p>
                    ) : null}
                </div>
                <div className={`flex shrink-0 items-center gap-2 ${card ? 'mt-auto pt-1' : 'sm:pt-0.5'}`}>
                    <AgentChatLink agent={agent} />
                    <GlassButton size="sm" variant="subtle" onClick={onDetails}
                        aria-label={`Details for ${catalogDisplayName(agent)}`}>
                        <Info size={14} aria-hidden="true" />
                        Details
                    </GlassButton>
                </div>
            </article>
        </GlassPanel>
    );
}

export function AgentsCatalogPage() {
    const bootstrap = useBootstrapStore((state) => state.data);
    const [catalog, setCatalog] = useState<AgentsCatalog>({ page: DEFAULT_CATALOG_PAGE, agents: [] });
    const [loadState, setLoadState] = useState<LoadState>('loading');
    const [attempt, setAttempt] = useState(0);
    const [tab, setTab] = useState<CatalogTab>('popular');
    const [window, setWindow] = useState<CatalogUsageWindow>('all_time');
    const [query, setQuery] = useState('');
    const [selectedTags, setSelectedTags] = useState<string[]>([]);
    const [view, setView] = useState<CatalogViewMode>(initialViewMode);
    const [details, setDetails] = useState<CatalogAgent | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        setLoadState('loading');
        api.get<unknown>(AGENTS_CATALOG_ENDPOINT, controller.signal).then((payload) => {
            if (controller.signal.aborted) return;
            setCatalog(readAgentsCatalog(payload));
            setLoadState('ready');
        }).catch((error: unknown) => {
            if (controller.signal.aborted) return;
            setLoadState(error instanceof ApiError && [400, 403, 404].includes(error.status) ? 'unavailable' : 'error');
        });
        return () => controller.abort();
    }, [attempt]);

    useEffect(() => {
        try {
            globalThis.localStorage.setItem(CATALOG_VIEW_STORAGE_KEY, view);
        } catch (error) {
            console.warn('Agent catalogue view preference could not be saved.', error);
        }
    }, [view]);

    const searching = Boolean(normalizeCatalogText(query));
    const popular = !searching && tab === 'popular';
    const shown = useMemo(() => visibleAgents({
        agents: catalog.agents, tab, window, query, tags: selectedTags,
    }), [catalog.agents, tab, window, query, selectedTags]);
    // Selected tags remain removable even when the current result set has no tags or agents.
    const tagOptions = useMemo(() => {
        const options = new Map<string, string>();
        for (const tag of [...tagsFor(shown), ...selectedTags]) options.set(tag.toLowerCase(), tag);
        return [...options.values()].sort((left, right) => left.localeCompare(right, undefined, { sensitivity: 'base' }));
    }, [shown, selectedTags]);
    const selectedTagKeys = new Set(selectedTags.map((tag) => tag.toLowerCase()));
    const resultsTitle = searching ? 'Search results' : TABS.find((entry) => entry.value === tab)?.label ?? 'Agents';
    const activeGroup = bootstrap?.scope.groups.find((group) => group.id === bootstrap.scope.active_group_id);
    const personalCreate = tab === 'personal' && bootstrap?.workspace.sections.agents?.enabled;
    const groupCreate = tab === 'group' && bootstrap?.features.enable_group_workspaces && bootstrap.settings.allow_group_agents === true;

    const selectTab = (next: CatalogTab) => {
        setTab(next);
        setQuery('');
        setSelectedTags([]);
    };
    const clearFilters = () => {
        setQuery('');
        setSelectedTags([]);
    };

    let content;
    if (loadState === 'loading') {
        content = <div role="status" aria-label="Loading agents"><SectionSkeleton /></div>;
    } else if (loadState === 'unavailable') {
        content = <EmptyState icon={<Lock size={28} />} title="Agents are not available"
            description="Agents have not been enabled for your account. Your administrators manage this access." />;
    } else if (loadState === 'error') {
        content = <SectionError message="Agents could not be loaded. Check your connection and try again."
            action={<GlassButton size="sm" onClick={() => setAttempt((count) => count + 1)}>
                <RotateCcw size={14} aria-hidden="true" />Try again
            </GlassButton>} />;
    } else {
        const page = catalog.page;
        const background = page.hero_color_mode === 'two_tone'
            ? `linear-gradient(120deg, ${page.hero_primary_color}, ${page.hero_secondary_color})`
            : page.hero_primary_color;
        content = (
            <>
                <section aria-label="Agent catalogue introduction" className="overflow-hidden rounded-2xl"
                    style={{ background }}>
                    <div className="bg-black/55 px-5 py-6 text-white lg:px-7 lg:py-8">
                        <h2 className="max-w-3xl break-words text-2xl font-semibold tracking-tight">{page.title}</h2>
                        <p className="mt-2 max-w-3xl break-words text-sm leading-relaxed">{page.subtitle}</p>
                    </div>
                </section>
                {page.disclaimer_markdown.trim() ? (
                    <div aria-label="Agent catalogue disclaimer" className="min-w-0 max-w-full overflow-x-auto">
                        <PlainMarkdown content={page.disclaimer_markdown} className="break-words" />
                    </div>
                ) : null}
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="w-full sm:max-w-md">
                        <SectionSearch value={query} onChange={setQuery} placeholder="Search agents" />
                    </div>
                    <div role="group" aria-label="Catalogue view" className="flex items-center gap-1">
                        <GlassButton size="icon" variant={view === 'list' ? 'subtle' : 'ghost'}
                            aria-label="List view" aria-pressed={view === 'list'} onClick={() => setView('list')}>
                            <List size={18} aria-hidden="true" />
                        </GlassButton>
                        <GlassButton size="icon" variant={view === 'card' ? 'subtle' : 'ghost'}
                            aria-label="Card view" aria-pressed={view === 'card'} onClick={() => setView('card')}>
                            <LayoutGrid size={18} aria-hidden="true" />
                        </GlassButton>
                    </div>
                </div>
                <div role="group" aria-label="Agent categories" className="flex w-fit max-w-full flex-wrap gap-0.5 rounded-xl border border-edge bg-surface-1 p-0.5">
                    {TABS.map((entry) => (
                        <button key={entry.value} type="button" aria-pressed={!searching && tab === entry.value}
                            onClick={() => selectTab(entry.value)}
                            className={`${CATEGORY_BUTTON} ${!searching && tab === entry.value ? SELECTED_CATEGORY : 'text-text-2 hover:bg-surface-2 hover:text-text-1'}`}>
                            {entry.label}
                        </button>
                    ))}
                    {searching ? <span aria-current="true" className={`${CATEGORY_BUTTON} ${SELECTED_CATEGORY}`}>Search results</span> : null}
                </div>
                {tagOptions.length ? (
                    <div role="group" aria-label="Filter agents by tag" className="flex min-w-0 flex-wrap items-center gap-2">
                        <span className="text-xs text-text-3">Tags</span>
                        {tagOptions.map((tag) => (
                            <GlassButton key={tag.toLowerCase()} size="sm"
                                variant={selectedTagKeys.has(tag.toLowerCase()) ? 'primary' : 'subtle'}
                                className="h-auto min-h-8 max-w-full break-words py-1.5 text-left"
                                aria-pressed={selectedTagKeys.has(tag.toLowerCase())}
                                onClick={() => setSelectedTags((current) => selectedTagKeys.has(tag.toLowerCase())
                                    ? current.filter((value) => value.toLowerCase() !== tag.toLowerCase()) : [...current, tag])}>
                                <span className="min-w-0 [overflow-wrap:anywhere]">{tag}</span>
                            </GlassButton>
                        ))}
                    </div>
                ) : null}
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
                        <h2 className="text-base font-semibold text-text-1">{resultsTitle}</h2>
                        <p className="text-xs text-text-3" aria-live="polite">{shown.length} {shown.length === 1 ? 'agent' : 'agents'}</p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        {popular ? (
                            <div role="group" aria-label="Popular usage window" className="inline-flex rounded-xl border border-edge bg-surface-1 p-0.5">
                                {(['all_time', '30_days'] as const).map((value) => (
                                    <button key={value} type="button" aria-pressed={window === value} onClick={() => setWindow(value)}
                                        className={`${CATEGORY_BUTTON} ${window === value ? SELECTED_CATEGORY : 'text-text-2 hover:text-text-1'}`}>
                                        {value === 'all_time' ? 'All time' : 'Last 30 days'}
                                    </button>
                                ))}
                            </div>
                        ) : null}
                        {searching || selectedTags.length ? <GlassButton size="sm" onClick={clearFilters}>Clear filters</GlassButton> : null}
                        {!searching && personalCreate ? (
                            <Link to="/workspace/agents/new" className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-medium text-on-accent hover:bg-accent-hover">
                                <Plus size={14} aria-hidden="true" />New agent
                            </Link>
                        ) : null}
                        {!searching && groupCreate ? (
                            <Link to={activeGroup ? groupWorkspacePath(activeGroup.id, 'agents') : '/groups'}
                                className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-medium text-on-accent hover:bg-accent-hover">
                                <Plus size={14} aria-hidden="true" />New agent
                            </Link>
                        ) : null}
                    </div>
                </div>
                {shown.length ? (
                    <ul aria-label="Agents" data-view={view}
                        className={view === 'card' ? 'grid gap-3 lg:grid-cols-2 2xl:grid-cols-3' : 'space-y-3'}>
                        {shown.map((agent, index) => (
                            <li key={catalogAgentKey(agent)} className="min-w-0">
                                <AgentResult agent={agent} rank={popular ? index + 1 : null} view={view}
                                    onDetails={() => setDetails(agent)} />
                            </li>
                        ))}
                    </ul>
                ) : (
                    <EmptyState icon={<Bot size={28} />}
                        title={catalog.agents.length ? 'No agents match the current view.' : 'No agents are available.'}
                        description={catalog.agents.length ? 'Try another category, search term or tag.' : 'Agents available to your account will appear here.'} />
                )}
            </>
        );
    }
    return (
        <div className="flex h-full min-h-0 flex-col">
            <link rel="stylesheet" href="/static/css/bootstrap-icons.css" />
            <PageHeader title="Agents" />
            <div data-testid="agents-catalog-scroll" className="min-h-0 flex-1 overflow-y-auto px-4 py-5 lg:px-6">
                <div className="mx-auto w-full max-w-6xl space-y-4 pb-10">{content}</div>
            </div>
            {details ? <AgentDetailsModal agent={details} showInstructions={catalog.page.show_instructions_in_details}
                onClose={() => setDetails(null)} /> : null}
        </div>
    );
}
