// ActionsSection.tsx

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { LayoutGrid, List, Plug, Plus, RefreshCw, Shield, Trash2 } from 'lucide-react';
import { EmptyState, GlassButton, GlassPanel } from '../../components/ui/primitives';
import { ConfirmAction, Pill, SectionError, SectionIntro, SectionSearch, SectionSkeleton } from '../../components/workspace/primitives';
import { errorMessage, useSectionResource } from '../../components/workspace/useSectionResource';
import { ACTION_INPUT_CLASS } from '../../components/workspaceActions/ActionFields';
import {
    ACTION_AUTHORING_UNAVAILABLE, actionCanEdit, actionDetailPath, actionResourceKey, actionScope,
    actionTypeLabel, filterAuthoringActions,
} from '../../lib/workspaceActionLogic';
import { fetchActionEditorHints } from '../../lib/workspaceActionServices';
import type { ActionConfiguration, ActionTypeDefinition } from '../../lib/workspaceAuthoring';
import {
    PERSONAL_ACTION_WORKBENCH, createGroupActionWorkbench, type ActionWorkbenchAdapter,
} from '../../lib/actionWorkbench';
import type { GroupWorkspaceContext } from '../../lib/workspaceContext';
import { useBootstrapStore } from '../../stores/bootstrapStore';

export { actionTypeLabel } from '../../lib/workspaceActionLogic';

let collectionState = { owner: '', query: '', type: '', scope: '', view: 'list', scrollTop: 0 };

export function ActionsSection({ agentsEnabled, adapter = PERSONAL_ACTION_WORKBENCH }: { agentsEnabled: boolean; adapter?: ActionWorkbenchAdapter }) {
    const isGroup = adapter.scope.kind === 'group';
    const navigate = useNavigate();
    const owner = useBootstrapStore((state) => state.data?.user?.id ?? '');
    const refreshBootstrap = useBootstrapStore((state) => state.refresh);
    const { items, loading, error, refresh, setItems, setError } =
        useSectionResource<ActionConfiguration>(adapter.listActions, 'Failed to load actions.');
    const [catalogue, setCatalogue] = useState<ActionTypeDefinition[]>([]);
    const [catalogueError, setCatalogueError] = useState<string | null>(null);
    const [catalogueVersion, setCatalogueVersion] = useState(0);
    const [canAuthor, setCanAuthor] = useState<boolean | null>(null);
    const [capabilityError, setCapabilityError] = useState<string | null>(null);
    const [busyId, setBusyId] = useState<string | null>(null);
    const list = useRef<HTMLDivElement>(null);
    const loadedOwner = useRef(owner);
    const scrollRestored = useRef(false);
    const [filters, setFilters] = useState(() => {
        if (collectionState.owner !== owner) collectionState = { owner, query: '', type: '', scope: '', view: 'list', scrollTop: 0 };
        return { ...collectionState };
    });

    useEffect(() => {
        if (filters.owner !== owner) {
            collectionState = { owner, query: '', type: '', scope: '', view: 'list', scrollTop: 0 };
            setFilters(collectionState);
            scrollRestored.current = false;
        } else {
            collectionState = { ...filters, scrollTop: collectionState.scrollTop };
        }
    }, [owner, filters]);
    useEffect(() => {
        if (loadedOwner.current !== owner) {
            loadedOwner.current = owner;
            setItems([]);
            setBusyId(null);
            void refresh();
        }
    }, [owner, refresh, setItems]);
    useEffect(() => {
        const controller = new AbortController();
        setCatalogueError(null);
        setCapabilityError(null);
        void adapter.fetchTypes(controller.signal).then(setCatalogue).catch((cause: unknown) => {
            if (!controller.signal.aborted) setCatalogueError(errorMessage(cause, 'Could not load action types.'));
        });
        // Group authoring is gated entirely by the server hint on the adapter, never the personal
        // /api/user/agent/settings capability, so a group member's create rights are read from the
        // workspace's action_management block rather than their own plugin permission.
        if (isGroup) {
            setCanAuthor(adapter.allows('create'));
        } else {
            setCanAuthor(null);
            void fetchActionEditorHints(controller.signal).then((hints) => {
                if (!controller.signal.aborted) setCanAuthor(hints.canAuthor);
            }).catch((cause: unknown) => {
                if (!controller.signal.aborted) {
                    setCanAuthor(false);
                    setCapabilityError(errorMessage(cause, 'Could not load action authoring permissions.'));
                }
            });
        }
        return () => controller.abort();
    }, [owner, catalogueVersion, adapter, isGroup]);
    useEffect(() => {
        if (!loading && !error && !scrollRestored.current && list.current) {
            list.current.scrollTop = collectionState.scrollTop;
            scrollRestored.current = true;
        }
    }, [loading, error, items.length]);

    const labels = useMemo(() => new Map(catalogue.map((type) => [type.type, type.display])), [catalogue]);
    const types = useMemo(() => [...new Set([...catalogue.map(({ type }) => type), ...items.map(({ type }) => type)])]
        .sort((left, right) => (labels.get(left) || actionTypeLabel(left)).localeCompare(labels.get(right) || actionTypeLabel(right))),
    [catalogue, items, labels]);
    const visible = useMemo(() => filterAuthoringActions(items, filters.query, filters.type, filters.scope, catalogue),
        [items, filters, catalogue]);

    const remove = async (action: ActionConfiguration) => {
        if (!action.id) return;
        if (isGroup ? !adapter.allows('delete', action) : actionScope(action) === 'provided') return;
        const key = actionResourceKey(action);
        setBusyId(key);
        setError(null);
        try {
            await adapter.deleteAction(action);
            if (loadedOwner.current !== owner) return;
            await Promise.all([refresh(), refreshBootstrap()]);
        } catch (cause) {
            if (loadedOwner.current === owner) setError(errorMessage(cause, 'Could not delete the action.'));
        } finally {
            if (loadedOwner.current === owner) setBusyId(null);
        }
    };

    return (
        <div className="flex h-full min-h-0 flex-col gap-4" data-testid="workspace-actions">
            <SectionIntro title="Actions"
                description={isGroup
                    ? 'Tools an agent may call in this workspace. Configure an API, database, application, or another agent here, then decide which agents may use it.'
                    : 'Tools an agent may call on your behalf. Configure an API, database, application, or another agent here, then decide which agents may use it.'}
                actions={<GlassButton type="button" variant="primary" size="sm" disabled={canAuthor !== true}
                    onClick={() => navigate(`${adapter.basePath}/new`)}>
                    <Plus size={16} /> New action
                </GlassButton>} />
            {agentsEnabled ? <p className="text-xs text-text-3">
                Actions run only when permitted by an <Link to="/workspace/agents" className="text-accent hover:underline">agent</Link>.
            </p> : null}
            {!isGroup && canAuthor === null ? <p role="status" className="text-xs text-text-3">Checking action authoring permissions…</p> : null}
            {!isGroup && canAuthor === false && !capabilityError ? <p role="status" className="text-xs text-text-3">{ACTION_AUTHORING_UNAVAILABLE}</p> : null}
            <div className="flex flex-wrap items-end gap-2">
                <div className="min-w-44 flex-1">
                    <SectionSearch value={filters.query} onChange={(query) => setFilters((current) => ({ ...current, query }))}
                        placeholder="Search actions" />
                </div>
                <label className="min-w-36 flex-1 text-xs text-text-3 sm:max-w-52">
                    Type
                    <select aria-label="Action type filter" className={`${ACTION_INPUT_CLASS} mt-1`} value={filters.type}
                        onChange={(event) => setFilters((current) => ({ ...current, type: event.target.value }))}>
                        <option value="">All types</option>
                        {types.map((type) => <option key={type} value={type}>{labels.get(type) || actionTypeLabel(type)}</option>)}
                    </select>
                </label>
                <label className="min-w-32 text-xs text-text-3">
                    Scope
                    <select aria-label="Action scope filter" className={`${ACTION_INPUT_CLASS} mt-1`} value={filters.scope}
                        onChange={(event) => setFilters((current) => ({ ...current, scope: event.target.value }))}>
                        <option value="">All scopes</option><option value="personal">My actions</option><option value="provided">Provided</option>
                    </select>
                </label>
                <div className="flex items-center gap-1" role="group" aria-label="Action view">
                    <GlassButton type="button" size="icon" title="List view" aria-label="List view" aria-pressed={filters.view === 'list'}
                        onClick={() => setFilters((current) => ({ ...current, view: 'list' }))}><List size={17} /></GlassButton>
                    <GlassButton type="button" size="icon" title="Card view" aria-label="Card view" aria-pressed={filters.view === 'cards'}
                        onClick={() => setFilters((current) => ({ ...current, view: 'cards' }))}><LayoutGrid size={17} /></GlassButton>
                    <GlassButton type="button" size="icon" title="Refresh actions" aria-label="Refresh actions" disabled={loading}
                        onClick={() => { void refresh(); setCatalogueVersion((version) => version + 1); }}><RefreshCw size={16} /></GlassButton>
                </div>
            </div>
            {error ? <SectionError message={error} /> : null}
            {catalogueError ? <SectionError message={`${catalogueError} Existing actions are still listed; retry with Refresh actions.`} /> : null}
            {capabilityError ? <SectionError message={`${capabilityError} Reading actions and permitted deletion remain available. Retry with Refresh actions.`} /> : null}
            <div ref={list} className="min-h-0 flex-1 overflow-y-auto pb-3 pr-1"
                onScroll={(event) => { collectionState.scrollTop = event.currentTarget.scrollTop; }}>
                {loading ? <SectionSkeleton /> : !error && !visible.length ? (
                    <EmptyState icon={<Plug size={28} />}
                        title={items.length ? 'No actions match these filters' : 'No actions yet'}
                        description={items.length ? 'Search by name, description, or connector type.' :
                            canAuthor === true ? 'Create an action to make a tool available to your agents.' : 'No readable actions are available in this workspace.'}
                        action={items.length ? <GlassButton type="button" onClick={() => setFilters((current) => ({ ...current, query: '', type: '', scope: '' }))}>
                            Clear filters
                        </GlassButton> : canAuthor === true ? <GlassButton type="button" variant="primary"
                            onClick={() => navigate(`${adapter.basePath}/new`)}>New action</GlassButton> : undefined} />
                ) : (
                    <ul className={filters.view === 'cards' ? 'grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3' : 'space-y-2'}>
                        {visible.map((action, index) => {
                            const provided = actionScope(action) === 'provided';
                            const editable = isGroup ? adapter.allows('edit', action) : actionCanEdit(action, canAuthor === true);
                            const deletable = Boolean(action.id) && (isGroup ? adapter.allows('delete', action) : !provided);
                            const label = action.displayName || action.name || 'Untitled action';
                            return (
                                <li key={action.id ? actionResourceKey(action) : `missing-${index}`} className="min-w-0"
                                    data-testid="workspace-action" data-action-id={action.id}
                                    data-action-scope={provided ? 'global' : isGroup ? 'group' : 'personal'} data-action-type={action.type}>
                                    <GlassPanel elevation="flat" className={`flex min-w-0 gap-3 p-4 ${filters.view === 'cards' ? 'h-full flex-col' : 'flex-wrap items-center'}`}>
                                        <div className="flex min-w-0 flex-1 items-start gap-3">
                                            <Plug size={18} className="mt-0.5 shrink-0 text-text-3" />
                                            <div className="min-w-0">
                                                {action.id ? <Link to={actionDetailPath(action, adapter.basePath)} className="break-words text-sm font-semibold text-text-1 hover:text-accent hover:underline">{label}</Link>
                                                    : <span className="text-sm font-semibold text-text-1">{label}</span>}
                                                <p className="mt-1 line-clamp-2 break-words text-xs text-text-3">{action.description || 'No description.'}</p>
                                                <p className="mt-1 break-all text-[11px] text-text-3">{action.id || 'Missing resource ID — reload before editing.'}</p>
                                            </div>
                                        </div>
                                        <div className="flex flex-wrap items-center gap-2">
                                            <Pill>{labels.get(action.type) || actionTypeLabel(action.type)}</Pill>
                                            <Pill tone={provided ? 'accent' : 'neutral'}>{provided ? <span className="inline-flex items-center gap-1"><Shield size={11} />Provided · Read only</span> : isGroup ? 'Group' : 'Personal'}</Pill>
                                            {!provided && !editable ? <Pill>Read only</Pill> : null}
                                        </div>
                                        <div className="flex items-center justify-end gap-2">
                                            {action.id ? <Link to={actionDetailPath(action, adapter.basePath)} aria-label={`${editable ? 'Edit' : 'View'} ${label}`}
                                                className="rounded-lg px-2 py-1.5 text-sm text-accent hover:bg-accent-soft">
                                                {editable ? 'Edit' : 'View details'}
                                            </Link> : null}
                                            {deletable ? <ConfirmAction icon={<Trash2 size={15} />} label={`Delete ${label}`}
                                                confirmLabel="Delete action" busy={busyId === actionResourceKey(action)} disabled={busyId !== null}
                                                onConfirm={() => void remove(action)} /> : null}
                                        </div>
                                    </GlassPanel>
                                </li>
                            );
                        })}
                    </ul>
                )}
            </div>
        </div>
    );
}

/**
 * The actions collection for a group workspace.
 *
 * Memoises a group adapter on the workspace identity and its `action_management` hint so the
 * collection reloads only when the workspace or its offered operations change, mirroring
 * `GroupPromptsSection`. Agent links are hidden because group agents are a later milestone.
 */
export function GroupActionsSection({ context }: { context: GroupWorkspaceContext }) {
    const adapter = useMemo(
        () => createGroupActionWorkbench(
            { kind: 'group', id: context.scope.id, name: context.workspace.name }, context.action_management),
        [context.scope.id, context.workspace.name, context.action_management],
    );
    return <ActionsSection agentsEnabled={false} adapter={adapter} />;
}
