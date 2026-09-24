// GroupWorkspacePage.tsx

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useBlocker, useLocation, useNavigate, useParams } from 'react-router-dom';
import { ArrowUpRight, LayoutGrid, Loader2, Lock, Users } from 'lucide-react';
import { AgentDelegationManager } from '../components/agents/AgentDelegationManager';
import { PageHeader } from '../components/layout/PageHeader';
import { EmptyState, GlassButton, GlassPanel, Skeleton } from '../components/ui/primitives';
import { GroupWorkspacePicker } from '../components/workspace/GroupWorkspacePicker';
import { WorkspaceLeavePrompt } from '../components/workspace/WorkspaceEditorFrame';
import { WorkspaceOverview } from '../components/workspace/WorkspaceOverview';
import { WorkspaceShell } from '../components/workspace/WorkspaceShell';
import { Pill, SectionIntro } from '../components/workspace/primitives';
import {
    GROUP_SECTION_BLURBS, GROUP_STATUS_LABELS, groupWorkspaceNavigationAvailability,
    groupWorkspacePath, classicGroupSectionLabel, readGroupDocumentTarget,
} from '../lib/groupWorkspaceNavigation';
import { GROUP_WORKSPACE_SECTION_IDS } from '../lib/workspaceContext';
import { resolveWorkspaceSections } from '../lib/workspaceSections';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { useGroupWorkspaceStore, WorkspaceRequestSuperseded } from '../stores/groupWorkspaceStore';
import { WORKSPACE_SECTIONS_BY_ID } from './workspace/sections';
import { WorkflowsSection } from './workspace/WorkflowsSection';
import { GroupDocumentsSection } from './workspace/DocumentsSection';
import { GroupTagsSection } from './workspace/TagsSection';
import { GroupPromptsSection } from './workspace/PromptsSection';
import { ActionsSection } from './workspace/ActionsSection';
import { ActionEditorPage } from './workspace/ActionEditorPage';
import { AgentsSection } from './workspace/AgentsSection';
import { AgentEditorPage } from './workspace/AgentEditorPage';
import { createGroupActionWorkbench } from '../lib/actionWorkbench';
import { createGroupAgentWorkbench } from '../lib/agentWorkbench';

export function GroupWorkspacePage() {
    const { groupId, section, resourceId } = useParams<{ groupId?: string; section?: string; resourceId?: string }>();
    const navigate = useNavigate();
    const location = useLocation();
    const linkedWorkflow = new URLSearchParams(location.search).get('workflow_id');
    const linkedDocument = useMemo(() => readGroupDocumentTarget(location.search), [location.search]);
    const hasDocumentLink = Boolean(linkedDocument.id || linkedDocument.error);
    const bootstrap = useBootstrapStore((state) => state.data);
    const state = useGroupWorkspaceStore();
    const viewerId = bootstrap?.user?.id;
    const enabled = Boolean(bootstrap?.features?.enable_group_workspaces);
    const activeGroupId = bootstrap?.scope?.active_group_id;
    const [dirty, setDirty] = useState(false);
    const [resourceBusy, setResourceBusy] = useState(false);
    const [notice, setNotice] = useState('');
    const [retry, setRetry] = useState(0);
    const [externalPrompt, setExternalPrompt] = useState<string | null>(null);
    const [externalTarget, setExternalTarget] = useState<string | null>(null);
    const [logoFailed, setLogoFailed] = useState(false);
    const dirtyRef = useRef(false);
    const busyRef = useRef(false);
    const initialization = useRef<{ key: string; promise: Promise<unknown> } | null>(null);
    dirtyRef.current = dirty;
    busyRef.current = resourceBusy;
    const reportDocumentDirty = useCallback((value: boolean) => { dirtyRef.current = value; setDirty(value); }, []);
    const reportDocumentBusy = useCallback((value: boolean) => { busyRef.current = value; setResourceBusy(value); }, []);

    const blocker = useBlocker(({ currentLocation, nextLocation }) => {
        const transitioning = useGroupWorkspaceStore.getState().activating;
        return (dirtyRef.current || busyRef.current || transitioning)
            && (currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search);
    });
    const blockerRef = useRef(blocker);
    blockerRef.current = blocker;

    useEffect(() => {
        if (!groupId && !hasDocumentLink && enabled && activeGroupId && !state.activating && !state.needsReconciliation && !externalTarget) {
            navigate(`${groupWorkspacePath(activeGroupId, linkedWorkflow ? 'workflows' : undefined)}${location.search}`, { replace: true });
        }
        if (groupId && !section && linkedWorkflow && !hasDocumentLink && enabled) {
            navigate(`${groupWorkspacePath(groupId, 'workflows')}${location.search}`, { replace: true });
        }
        if (groupId && !section && hasDocumentLink && enabled) {
            navigate(`${groupWorkspacePath(groupId, 'documents')}${location.search}`, { replace: true });
        }
    }, [groupId, enabled, activeGroupId, section, linkedWorkflow, location.search, navigate,
        state.activating, state.needsReconciliation, externalTarget, hasDocumentLink]);

    useEffect(() => {
        if (!groupId || !viewerId || !enabled) {
            initialization.current = null;
            return;
        }
        const key = JSON.stringify([groupId, viewerId, retry]);
        const current = useGroupWorkspaceStore.getState();
        if (current.needsReconciliation) return;
        if (initialization.current?.key !== key) {
            setNotice('');
            const active = useBootstrapStore.getState().data?.scope?.active_group_id;
            const sameContext = current.context?.scope.id === groupId && current.context.viewer_id === viewerId;
            const promise = active !== groupId
                ? current.activate(groupId, () => !dirtyRef.current && !busyRef.current)
                : sameContext ? current.revalidate(groupId) : current.load(groupId);
            initialization.current = { key, promise };
        }
        let mounted = true;
        void initialization.current.promise.catch((cause: unknown) => {
            if (mounted && !(cause instanceof WorkspaceRequestSuperseded)) {
                setNotice(useGroupWorkspaceStore.getState().error || 'Could not load this workspace. Please retry.');
            }
        });
        return () => { mounted = false; };
    }, [groupId, viewerId, enabled, retry]);

    useEffect(() => {
        if (!dirty && !resourceBusy && !state.activating) return;
        const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
        window.addEventListener('beforeunload', beforeUnload);
        return () => window.removeEventListener('beforeunload', beforeUnload);
    }, [dirty, resourceBusy, state.activating]);

    const revalidate = useCallback(() => {
        const current = useGroupWorkspaceStore.getState();
        if (!groupId || !enabled || document.visibilityState !== 'visible' || busyRef.current
            || current.loading || current.activating || current.refreshing || current.needsReconciliation
            || current.context?.scope.id !== groupId) return;
        void current.revalidate(groupId).then(() => {
            if (!useGroupWorkspaceStore.getState().error) setNotice('');
        }).catch((cause: unknown) => {
            if (!(cause instanceof WorkspaceRequestSuperseded)) {
                setNotice(useGroupWorkspaceStore.getState().error || 'Could not refresh this workspace.');
            }
        });
    }, [groupId, enabled]);
    useEffect(() => {
        window.addEventListener('focus', revalidate);
        document.addEventListener('visibilitychange', revalidate);
        return () => {
            window.removeEventListener('focus', revalidate);
            document.removeEventListener('visibilitychange', revalidate);
        };
    }, [revalidate]);

    const context = state.context && state.context.scope.id === groupId && state.context.viewer_id === viewerId ? state.context : null;
    const ready = context && !state.loading && !state.activating && !state.needsReconciliation && !externalTarget;
    const accessUnconfirmed = state.refreshing || state.needsRevalidation;
    const basePath = groupId ? groupWorkspacePath(groupId) : '/groups';
    const sections = useMemo(() => GROUP_WORKSPACE_SECTION_IDS.map((id) => {
        const { label, icon, group } = WORKSPACE_SECTIONS_BY_ID[id];
        return {
            id, label, icon, group, blurb: GROUP_SECTION_BLURBS[id],
            availabilityLabel: id === 'workflows' || id === 'documents' || id === 'tags' || id === 'prompts' ? undefined
                : id === 'agents' ? (context?.sections.agents.enabled ? undefined : 'Classic')
                : id === 'actions' ? (context?.sections.actions.enabled ? undefined
                    : context?.native_delegation?.enabled ? 'Call agent' : 'Classic')
                : 'Classic',
        };
    }), [context?.native_delegation?.enabled, context?.sections.actions.enabled, context?.sections.agents.enabled]);
    const resolved = useMemo(() => resolveWorkspaceSections(
        sections, context ? groupWorkspaceNavigationAvailability(context) : null,
    ), [sections, context]);
    const selected = resolved.find((entry) => entry.section.id === section);
    const nativeDocuments = Boolean(ready && section === 'documents' && !resourceId
        && selected?.enabled && context.document_permissions.can_view);
    const nativePrompts = Boolean(ready && section === 'prompts' && !resourceId && selected?.enabled);
    // Native actions render whenever the workspace advertises the Actions section as available
    // (context.sections.actions.enabled), which requires the group action capability -- not merely
    // native_delegation, which enables the nav slot on its own. A read-only member has an available
    // section with an empty action_management hint, so they still get the native (read-only)
    // workbench. When the section is unavailable the surface falls through to the Call agent view.
    // The editor view is full-bleed too, matching the personal action editor's 'full' layout.
    const nativeActions = Boolean(ready && section === 'actions' && selected?.enabled && context.sections.actions.enabled);
    const groupActionAdapter = useMemo(
        () => context?.sections.actions.enabled
            ? createGroupActionWorkbench({ kind: 'group', id: context.scope.id, name: context.workspace.name }, context.action_management)
            : null,
        [context?.scope.id, context?.workspace.name, context?.sections.actions.enabled, context?.action_management],
    );
    // Native group agents render only when the workspace advertises the Agents section as available
    // (context.sections.agents.enabled), which requires the group agent capability. A read-only
    // member has an available section with an empty agent_management hint, so they still get the
    // native read-only collection. When the section is unavailable it falls through to Classic. The
    // agent editor's action candidates and "New action" handoff reuse the group action adapter, or
    // stay dark when group actions are unavailable -- never falling back to a personal action.
    const nativeAgents = Boolean(ready && section === 'agents' && selected?.enabled && context.sections.agents.enabled);
    const groupAgentAdapter = useMemo(
        () => context?.sections.agents.enabled
            ? createGroupAgentWorkbench({ kind: 'group', id: context.scope.id, name: context.workspace.name }, context.agent_management, groupActionAdapter)
            : null,
        [context?.scope.id, context?.workspace.name, context?.sections.agents.enabled, context?.agent_management, groupActionAdapter],
    );

    useEffect(() => { setLogoFailed(false); }, [context?.scope.id, context?.workspace.logo_url]);
    useEffect(() => {
        setExternalTarget(null);
        setExternalPrompt(null);
        setNotice('');
        setDirty(false);
        setResourceBusy(false);
    }, [viewerId]);

    const selectGroup = async (id: string) => {
        setNotice('');
        try {
            const result = await state.activate(id, () => !dirtyRef.current && !busyRef.current);
            if (result.status === 'activated') {
                if (blockerRef.current.state === 'blocked') blockerRef.current.reset();
                const params = new URLSearchParams(location.search);
                if (groupId && id !== groupId) {
                    params.delete('workflow_id');
                }
                if (id !== groupId) {
                    params.delete('document_id');
                    params.delete('group_id');
                    params.delete('group_ids');
                }
                const nextSection = section || (params.get('workflow_id') ? 'workflows' : undefined);
                navigate(`${groupWorkspacePath(id, nextSection)}${params.size ? `?${params}` : ''}`, { replace: !groupId });
            }
        } catch (cause) {
            if (!(cause instanceof WorkspaceRequestSuperseded)) {
                setNotice(useGroupWorkspaceStore.getState().error || 'Could not switch workspaces.');
            }
        } finally {
            if (blockerRef.current.state === 'blocked' && !dirtyRef.current && !busyRef.current) blockerRef.current.reset();
        }
    };
    const clearDocumentLink = useCallback(() => {
        const params = new URLSearchParams(location.search);
        params.delete('document_id');
        params.delete('group_id');
        params.delete('group_ids');
        navigate(`${location.pathname}${params.size ? `?${params}` : ''}`, { replace: true });
    }, [location.pathname, location.search, navigate]);
    const recover = async () => {
        setNotice('');
        try {
            const recovered = await state.reconcile();
            navigate(recovered ? groupWorkspacePath(recovered.scope.id, section) : '/groups', { replace: true });
        } catch (cause) {
            if (!(cause instanceof WorkspaceRequestSuperseded)) setNotice(useGroupWorkspaceStore.getState().error || 'Could not confirm your selection.');
        }
    };
    const openClassic = (href: string) => {
        if (dirtyRef.current || busyRef.current) setExternalPrompt(href);
        else setExternalTarget(href);
    };
    useEffect(() => {
        if (!externalTarget || !groupId) return;
        let mounted = true;
        void useGroupWorkspaceStore.getState().activate(groupId, () => true).then((result) => {
            if (mounted && result.status === 'activated') window.location.assign(externalTarget);
        }).catch((cause: unknown) => {
            if (mounted && !(cause instanceof WorkspaceRequestSuperseded)) {
                setNotice(useGroupWorkspaceStore.getState().error || 'Could not open the classic workspace.');
                setExternalTarget(null);
            }
        });
        return () => { mounted = false; };
    }, [externalTarget, groupId]);

    const header = (
        <>
            <PageHeader title="Group workspaces" description="Shared knowledge and tools for your team" leading={<Users size={20} className="text-accent" />} />
            <div className="shrink-0 space-y-3 border-b border-edge px-4 py-3">
                <GroupWorkspacePicker key={viewerId} value={state.pendingGroupId ?? groupId}
                    selectedName={context?.workspace.name || bootstrap?.scope?.groups?.find((group) => group.id === groupId)?.name}
                    disabled={dirty || resourceBusy || state.loading || state.activating || Boolean(externalTarget) || state.needsReconciliation}
                    onSelect={(id) => void selectGroup(id)} />
                {ready ? (
                    <div className="flex min-w-0 flex-wrap items-center gap-3">
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-lg border bg-surface-1"
                            style={{ borderColor: context.workspace.hero_color }}>
                            {context.workspace.logo_url && !logoFailed ? (
                                <img src={context.workspace.logo_url} alt="" className="h-full w-full object-contain" onError={() => setLogoFailed(true)} />
                            ) : <Users size={18} className="text-text-2" />}
                        </div>
                        <div className="min-w-0 flex-1 basis-48">
                            <p className="break-words text-sm font-semibold text-text-1">{context.workspace.name}</p>
                            <p className="text-xs text-text-3">Role: {context.role === 'DocumentManager' ? 'Document manager' : context.role === 'User' ? 'Member' : context.role}</p>
                        </div>
                        <Pill tone={context.status === 'active' ? 'neutral' : 'warn'}>Status: {GROUP_STATUS_LABELS[context.status]}</Pill>
                        {context.can_manage_workspace ? <GlassButton size="sm" disabled={resourceBusy || accessUnconfirmed}
                            onClick={() => openClassic(`/groups/${encodeURIComponent(context.scope.id)}`)}>
                            Manage group (classic)<ArrowUpRight size={14} />
                        </GlassButton> : null}
                    </div>
                ) : null}
                {dirty ? <p role="status" className="text-xs text-warn">Save or cancel your group changes before switching groups.</p> : null}
                {state.refreshing ? <p role="status" className="text-xs text-text-3">Refreshing workspace access...</p> : null}
            </div>
        </>
    );

    if (!enabled) return (
        <div className="flex h-full flex-col">
            <PageHeader title="Group workspaces" />
            <div className="p-4"><EmptyState icon={<Lock size={28} />} title="Group workspaces are not enabled"
                description="Your administrator has not enabled group workspaces for this deployment." /></div>
        </div>
    );

    const error = notice || state.error;
    return (
        <WorkspaceShell header={header} basePath={basePath} sections={ready ? resolved : []} fullBleed={nativeDocuments || nativePrompts || nativeActions || nativeAgents}>
            {error ? <div role="alert" className="mb-4 space-y-2 rounded-xl border border-danger/30 bg-danger-soft p-3 text-sm text-danger">
                <p>{error}</p>
                {state.needsReconciliation ? <GlassButton size="sm" disabled={state.loading || state.activating} onClick={() => void recover()}>Refresh workspace selection</GlassButton>
                    : <GlassButton size="sm" disabled={state.loading || state.refreshing || state.activating} onClick={() => {
                        setNotice('');
                        if (state.needsRevalidation) revalidate();
                        else setRetry((value) => value + 1);
                    }}>Retry workspace details</GlassButton>}
            </div> : null}
            {ready && activeGroupId !== context.scope.id ? (
                <div role="status" className="mb-4 space-y-2 rounded-xl border border-edge p-3 text-sm text-text-2">
                    <p>Your active group changed elsewhere. This page still shows {context.workspace.name}; its requests stay scoped to this group.</p>
                    <GlassButton size="sm" disabled={dirty || resourceBusy || accessUnconfirmed} onClick={() => void selectGroup(context.scope.id)}>Make this group active</GlassButton>
                </div>
            ) : null}
            {state.loading || state.activating || externalTarget ? (
                <div role="status" className="space-y-3">
                    <p className="flex items-center gap-2 text-sm text-text-2"><Loader2 size={16} className="animate-spin" />
                        {externalTarget ? 'Opening the selected group in classic...' : state.activating ? 'Switching workspace...' : 'Loading workspace details...'}</p>
                    <Skeleton className="h-20 w-full" /><Skeleton className="h-32 w-full" />
                </div>
            ) : !groupId ? (
                <EmptyState icon={<Users size={28} />} title="Choose a group workspace"
                    description={hasDocumentLink ? 'A document link must include its explicit group. Choose a group and open the document from that workspace.'
                        : 'Select a group above to load its details and shared tools.'}
                    action={<a href="/profile?tab=groups" className="text-sm text-accent underline">Find or manage your groups in classic</a>} />
            ) : ready ? (
                <div key={`${context.scope.id}:${section ?? 'overview'}`}
                    className={nativeDocuments || nativePrompts || nativeActions || nativeAgents ? 'flex min-h-0 flex-1 flex-col' : 'space-y-4'}>
                    {!section ? (
                        <>
                            <dl className="space-y-2 text-sm text-text-2">
                                <div><dt className="text-xs text-text-3">About this group</dt><dd className="break-words">{context.workspace.description || 'No description provided.'}</dd></div>
                                <div><dt className="text-xs text-text-3">Owner</dt><dd className="break-words">{context.workspace.owner.display_name || 'Owner information unavailable'}{context.workspace.owner.email ? ` · ${context.workspace.owner.email}` : ''}</dd></div>
                            </dl>
                            <WorkspaceOverview basePath={basePath} resolved={resolved} showRelationships={false}
                                description="Shared documents, prompts and automation for this group. Sections marked Classic open in the existing interface while their V2 experience is being built." />
                        </>
                    ) : !selected ? <EmptyState icon={<LayoutGrid size={28} />} title="Section not found" description="Choose a section from this workspace's navigation." />
                        : !selected.enabled ? <EmptyState icon={<Lock size={28} />} title={`${selected.section.label} is not available`} description={selected.reason ?? undefined} />
                            : section === 'documents' && !resourceId ? (
                                context.document_permissions.can_view ? <GroupDocumentsSection context={context}
                                    interactionDisabled={accessUnconfirmed} onOpenClassic={() => openClassic('/group_workspaces')}
                                    onDirtyChange={reportDocumentDirty} onBusyChange={reportDocumentBusy}
                                    linkedDocumentId={linkedDocument.id} linkedDocumentError={linkedDocument.error}
                                    onClearLinkedDocument={clearDocumentLink} />
                                    : <EmptyState icon={<Lock size={28} />} title="Documents are not available" description="You do not have access to this group's documents." />
                            )
                            : section === 'tags' && !resourceId ? (
                                context.document_permissions.can_view ? <GroupTagsSection context={context}
                                    interactionDisabled={accessUnconfirmed} onOpenClassic={() => openClassic('/group_workspaces')}
                                    onDirtyChange={reportDocumentDirty} onBusyChange={reportDocumentBusy} />
                                    : <EmptyState icon={<Lock size={28} />} title="Tags are not available" description="You do not have access to this group's documents." />
                            )
                            : section === 'workflows' && !resourceId ? <WorkflowsSection scope={{ type: 'group', groupId: context.scope.id }}
                                allowManage={context.sections.workflows.can_manage} interactionDisabled={accessUnconfirmed}
                                onOpenClassic={() => openClassic('/group_workspaces')}
                                onDirtyChange={setDirty} onBusyChange={setResourceBusy} />
                                : section === 'actions' && resourceId && groupActionAdapter ? (
                                    <ActionEditorPage adapter={groupActionAdapter} />
                                ) : section === 'actions' && !resourceId && groupActionAdapter ? (
                                    <>
                                        <div className="min-h-0 flex-1"><ActionsSection agentsEnabled={false} adapter={groupActionAdapter} /></div>
                                        {context.native_delegation?.enabled ? (
                                            <div className="mt-4 max-h-[45%] shrink-0 space-y-3 overflow-y-auto border-t border-edge pt-4">
                                                <SectionIntro title="Call agent" description="Choose which agents this group can call and which local actions may trigger them." />
                                                <AgentDelegationManager scope={{ type: 'group', groupId: context.scope.id }}
                                                    allowManage={context.native_delegation.can_manage} interactionDisabled={accessUnconfirmed}
                                                    onDirtyChange={setDirty} onBusyChange={setResourceBusy} />
                                            </div>
                                        ) : null}
                                    </>
                                ) : section === 'actions' && context.native_delegation?.enabled && !resourceId ? (
                                    <>
                                        <SectionIntro title="Actions" description="Manage Call agent actions and their local callers. Other group actions still use the classic editor." />
                                        <GlassButton size="sm" disabled={resourceBusy || accessUnconfirmed} onClick={() => openClassic('/group_workspaces')}>Open classic group workspace<ArrowUpRight size={14} /></GlassButton>
                                        <AgentDelegationManager scope={{ type: 'group', groupId: context.scope.id }}
                                            allowManage={context.native_delegation.can_manage} interactionDisabled={accessUnconfirmed}
                                            onDirtyChange={setDirty} onBusyChange={setResourceBusy} />
                                    </>
                                ) : section === 'agents' && resourceId && groupAgentAdapter ? (
                                    <AgentEditorPage adapter={groupAgentAdapter} />
                                ) : section === 'agents' && !resourceId && groupAgentAdapter ? (
                                    <div className="min-h-0 flex-1"><AgentsSection actionsEnabled={groupAgentAdapter.canCreateActions} adapter={groupAgentAdapter} /></div>
                                ) : section === 'prompts' && !resourceId ? (
                                    <GroupPromptsSection context={context} />
                                ) : (
                                    <GlassPanel elevation="flat" className="space-y-4 p-5">
                                        <SectionIntro title={selected.section.label} description={selected.section.blurb} />
                                        <p className="text-sm text-text-2">This section is available in the classic group workspace. Choose {classicGroupSectionLabel(selected.section.id, selected.section.label)} there; {context.workspace.name} will be selected for you.</p>
                                        <GlassButton variant="primary" disabled={resourceBusy || accessUnconfirmed}
                                            onClick={() => openClassic('/group_workspaces')}>Open classic group workspace<ArrowUpRight size={15} /></GlassButton>
                                    </GlassPanel>
                                )}
                </div>
            ) : !error ? <EmptyState title="Workspace details unavailable" description="Select another group or refresh workspace details." /> : null}
            {blocker.state === 'blocked' || externalPrompt ? <WorkspaceLeavePrompt
                saving={resourceBusy || state.activating}
                switching={state.activating}
                onStay={() => { if (blocker.state === 'blocked') blocker.reset(); setExternalPrompt(null); }}
                onDiscard={() => {
                    setDirty(false);
                    if (externalPrompt) { setExternalTarget(externalPrompt); setExternalPrompt(null); }
                    else if (blocker.state === 'blocked') blocker.proceed();
                }} /> : null}
        </WorkspaceShell>
    );
}
