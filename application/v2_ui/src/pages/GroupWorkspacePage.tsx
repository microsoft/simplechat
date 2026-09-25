// GroupWorkspacePage.tsx

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useBlocker, useLocation, useNavigate, useParams } from 'react-router-dom';
import { ArrowUpRight, Compass, LayoutGrid, Loader2, Lock, Users } from 'lucide-react';
import { AgentDelegationManager } from '../components/agents/AgentDelegationManager';
import { PageHeader } from '../components/layout/PageHeader';
import { EmptyState, GlassButton, Skeleton } from '../components/ui/primitives';
import { GroupWorkspacePicker } from '../components/workspace/GroupWorkspacePicker';
import { WorkspaceLeavePrompt } from '../components/workspace/WorkspaceEditorFrame';
import { WorkspaceOverview } from '../components/workspace/WorkspaceOverview';
import { WorkspaceShell } from '../components/workspace/WorkspaceShell';
import { Pill, SectionIntro } from '../components/workspace/primitives';
import {
    GROUP_SECTION_BLURBS, GROUP_STATUS_LABELS, groupRoleLabel, groupWorkspaceNavigationAvailability,
    groupWorkspacePath, isGroupManageSection, isGroupWorkspaceSection, readGroupDocumentTarget,
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
import { GroupIdentitiesSection } from './workspace/GroupIdentitiesSection';
import { GroupEndpointsSection } from './workspace/GroupEndpointsSection';
import { GroupFileSourcesSection } from './workspace/GroupFileSourcesSection';
import { GroupMembersSection } from './workspace/GroupMembersSection';
import { GroupSettingsSection } from './workspace/GroupSettingsSection';
import { GroupActivitySection } from './workspace/GroupActivitySection';
import { GroupStatisticsSection } from './workspace/GroupStatisticsSection';
import { GROUP_MANAGE_SECTIONS } from './workspace/groupManageSections';
import { ActionsSection } from './workspace/ActionsSection';
import { ActionEditorPage } from './workspace/ActionEditorPage';
import { AgentsSection } from './workspace/AgentsSection';
import { AgentEditorPage } from './workspace/AgentEditorPage';
import { createGroupActionWorkbench } from '../lib/actionWorkbench';
import { createGroupAgentWorkbench } from '../lib/agentWorkbench';
import { createGroupIdentityWorkbench } from '../lib/identityWorkbench';
import { createGroupModelConnectionsAdapter } from '../lib/modelConnections';
import { createGroupFileSourceWorkbench } from '../lib/fileSourceWorkbench';
import { createGroupSettingsAdapter } from '../lib/groupSettings';

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

    // A successful profile or logo save re-reads the context so the header, picker and branding follow
    // the new name, colour and logo. Unlike the focus revalidate this is not gated on the busy flag,
    // because it fires from inside the still-in-flight save; the Settings section keeps its own drafts,
    // so this refresh can never wipe an edit.
    const refreshContextNow = useCallback(() => {
        const current = useGroupWorkspaceStore.getState();
        if (!groupId || !enabled || current.loading || current.activating || current.refreshing
            || current.needsReconciliation || current.context?.scope.id !== groupId) return;
        void current.revalidate(groupId).catch((cause: unknown) => {
            if (!(cause instanceof WorkspaceRequestSuperseded)) {
                setNotice(useGroupWorkspaceStore.getState().error || 'Could not refresh this workspace.');
            }
        });
    }, [groupId, enabled]);

    const context = state.context && state.context.scope.id === groupId && state.context.viewer_id === viewerId ? state.context : null;
    const ready = context && !state.loading && !state.activating && !state.needsReconciliation && !externalTarget;
    const accessUnconfirmed = state.refreshing || state.needsRevalidation;
    const basePath = groupId ? groupWorkspacePath(groupId) : '/groups';
    const sections = useMemo(() => GROUP_WORKSPACE_SECTION_IDS.map((id) => {
        const { label, icon, group } = WORKSPACE_SECTIONS_BY_ID[id];
        return {
            id, label, icon, group, blurb: GROUP_SECTION_BLURBS[id],
            // Every group section is native now, so none hands off to classic. The only marker left
            // flags Actions as Call-agent-only: when the group action capability is off but the
            // Call agent tools stay on (native_delegation), that delegation view is what the user
            // actually gets, so the nav slot advertises it by name.
            availabilityLabel: id === 'actions' && !context?.sections.actions.enabled && context?.native_delegation?.enabled
                ? 'Call agent' : undefined,
        };
    }), [context?.sections.actions.enabled, context?.native_delegation?.enabled]);
    // The Manage group's sections (M7B Members) resolve against the same server context, so one
    // navigation tree serves the whole group workspace.
    const resolved = useMemo(() => resolveWorkspaceSections(
        [...sections, ...GROUP_MANAGE_SECTIONS], context ? groupWorkspaceNavigationAvailability(context) : null,
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
    // native read-only collection. When the section is unavailable it shows its locked state with the
    // server's reason. The agent editor's action candidates and "New action" handoff reuse the group
    // action adapter, or stay dark when group actions are unavailable -- never falling back to a
    // personal action.
    const nativeAgents = Boolean(ready && section === 'agents' && selected?.enabled && context.sections.agents.enabled);
    const groupAgentAdapter = useMemo(
        () => context?.sections.agents.enabled
            ? createGroupAgentWorkbench({ kind: 'group', id: context.scope.id, name: context.workspace.name }, context.agent_management, groupActionAdapter)
            : null,
        [context?.scope.id, context?.workspace.name, context?.sections.agents.enabled, context?.agent_management, groupActionAdapter],
    );
    // Native group identities render only when the workspace advertises the Identities section as
    // available (context.sections.identities.enabled), which requires the caller to be a manager. A
    // member's section is unavailable and shows its locked state with the server's reason. Create is
    // gated on the identity_management hint; edit and delete are gated per row via each identity's
    // identity_actions -- never a personal-identity fallback. This section writes in a dialog, so
    // it keeps the personal SectionList layout rather than the full-bleed editor layout, and so it
    // needs no full-bleed flag of its own.
    const groupIdentityAdapter = useMemo(
        () => context?.sections.identities.enabled
            ? createGroupIdentityWorkbench({ kind: 'group', id: context.scope.id, name: context.workspace.name }, context.identity_management)
            : null,
        [context?.scope.id, context?.workspace.name, context?.sections.identities.enabled, context?.identity_management],
    );
    // Native group model endpoints render only when the workspace advertises the Endpoints section
    // as available (context.sections.endpoints.enabled), which requires the group model endpoint
    // capability. Create is gated on the endpoint_management hint; edit, enable, delete and test are
    // gated per row via each endpoint's endpoint_actions -- never a tenant-admin fallback. A member
    // gets an available section with an empty endpoint_management hint, so they see a read-only list.
    // The section reuses the admin ModelConnectionsManager through the scope-aware adapter, which
    // hides every admin-only affordance in group scope.
    const groupEndpointAdapter = useMemo(
        () => context?.sections.endpoints.enabled
            ? createGroupModelConnectionsAdapter({ kind: 'group', id: context.scope.id, name: context.workspace.name }, context.endpoint_management)
            : null,
        [context?.scope.id, context?.workspace.name, context?.sections.endpoints.enabled, context?.endpoint_management],
    );

    // Native group file sources render only when the workspace advertises the Sync section as
    // available (context.sections.sync.enabled), which requires the caller to be a manager. A
    // member's section is unavailable and shows its locked state with the server's reason. Create is
    // gated on the file_source_management hint; edit, sync and delete are gated per row via each source's
    // source_actions -- never a personal file-sync fallback. Writing happens in a dialog, so it
    // keeps the personal SectionList layout and needs no full-bleed flag of its own.
    const groupFileSourceAdapter = useMemo(
        () => context?.sections.sync.enabled
            ? createGroupFileSourceWorkbench({ kind: 'group', id: context.scope.id, name: context.workspace.name }, context.file_source_management)
            : null,
        [context?.scope.id, context?.workspace.name, context?.sections.sync.enabled, context?.file_source_management],
    );

    // The Manage group's Settings, Activity and Statistics sections (M7C) share one scoped client.
    // Its gating reads context.settings_management with no fallback: an absent hint (a member) is a
    // read-only surface, never an empty grant. The client itself only needs the group scope, so it
    // is built whenever a group is loaded; each section renders only when its own nav slot is
    // available, and the section's own controls come from the hint.
    // The Manage group's Settings, Activity and Statistics sections (M7C) share one scoped client.
    // The adapter is keyed on the group id ALONE, so a plain refocus (which reparses the context into
    // a new object) never rebuilds it and never discards the Settings section's open drafts. The
    // freshest settings_management hint is passed to the section separately so its controls still
    // re-gate on every context revalidation without the adapter churning.
    const groupSettingsAdapter = useMemo(
        () => context ? createGroupSettingsAdapter(context.scope, context.settings_management) : null,
        // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the group id only, on purpose (S1)
        [context?.scope.id],
    );

    useEffect(() => { setLogoFailed(false); }, [context?.scope.id, context?.workspace.logo_url]);
    useEffect(() => {
        setExternalTarget(null);
        setExternalPrompt(null);
        setNotice('');
        setDirty(false);
        setResourceBusy(false);
    }, [viewerId]);

    // A stray resource segment on a section that has no resource route -- every native group section,
    // including the Manage sections, except the actions and agents editors -- must never fall through
    // to a classic handoff. Once the context is loaded, drop the segment so the section itself
    // renders, turning a /workflows/<id> deep link into the ?workflow_id= query the workflows section
    // already understands. Actions and agents keep their editor route while that section is
    // available; when it is off they have no editor, so their stray segment is dropped too and the
    // section (or its lock) shows instead.
    useEffect(() => {
        if (!context || !groupId || !section || !resourceId
            || !(isGroupWorkspaceSection(section) || isGroupManageSection(section))) return;
        if (section === 'actions' && context.sections.actions.enabled) return;
        if (section === 'agents' && context.sections.agents.enabled) return;
        const target = section === 'workflows'
            ? `${groupWorkspacePath(groupId, 'workflows')}?workflow_id=${encodeURIComponent(resourceId)}`
            : groupWorkspacePath(groupId, section);
        navigate(target, { replace: true });
    }, [context, groupId, section, resourceId, navigate]);

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
    // After leaving, the group is no longer the caller's: re-read the bootstrap so the picker and
    // the saved active group drop it, then go back to /groups.
    const leftGroup = useCallback(async () => {
        reportDocumentBusy(false);
        await useBootstrapStore.getState().refresh();
        navigate('/groups', { replace: true });
    }, [navigate, reportDocumentBusy]);
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
            <PageHeader title="Group workspaces" description="Shared knowledge and tools for your team"
                leading={<Users size={20} className="text-accent" />}
                actions={(
                    <GlassButton size="sm" variant="subtle" onClick={() => navigate('/groups/directory')}>
                        <Compass size={14} />Browse all groups
                    </GlassButton>
                )} />
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
                            <p className="text-xs text-text-3">Role: {groupRoleLabel(context.role)}</p>
                        </div>
                        <Pill tone={context.status === 'active' ? 'neutral' : 'warn'}>Status: {GROUP_STATUS_LABELS[context.status]}</Pill>
                        {context.can_manage_workspace && (context.status === 'inactive' || context.status === 'unknown')
                            ? <GlassButton size="sm" disabled={resourceBusy || accessUnconfirmed}
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
                    action={<GlassButton size="sm" variant="subtle" onClick={() => navigate('/groups/directory')}>
                        <Compass size={14} />Browse the group directory</GlassButton>} />
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
                                description="Shared documents, prompts and automation for this group. A locked section shows why it's unavailable to you." />
                        </>
                    ) : !selected ? <EmptyState icon={<LayoutGrid size={28} />} title="Section not found" description="Choose a section from this workspace's navigation." />
                        : !selected.enabled ? <EmptyState icon={<Lock size={28} />} title={`${selected.section.label} is not available`} description={selected.reason ?? undefined} />
                            : section === 'members' && !resourceId ? (
                                <GroupMembersSection groupId={context.scope.id} groupName={context.workspace.name}
                                    viewerId={context.viewer_id} interactionDisabled={accessUnconfirmed}
                                    onBusyChange={reportDocumentBusy} onAccessChanged={revalidate} onLeft={leftGroup} />
                            )
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
                                    interactionDisabled={accessUnconfirmed}
                                    onDirtyChange={reportDocumentDirty} onBusyChange={reportDocumentBusy} />
                                    : <EmptyState icon={<Lock size={28} />} title="Tags are not available" description="You do not have access to this group's documents." />
                            )
                            : section === 'workflows' && !resourceId ? <WorkflowsSection scope={{ type: 'group', groupId: context.scope.id }}
                                allowManage={context.sections.workflows.can_manage} interactionDisabled={accessUnconfirmed}
                                onDirtyChange={setDirty} onBusyChange={setResourceBusy} />
                                : section === 'actions' && resourceId && groupActionAdapter ? (
                                    <ActionEditorPage adapter={groupActionAdapter} />
                                ) : section === 'actions' && !resourceId && groupActionAdapter ? (
                                    <>
                                        <div className="min-h-0 flex-1"><ActionsSection agentsEnabled={false} adapter={groupActionAdapter} /></div>
                                        {context.native_delegation?.enabled ? (
                                            <div className="mt-4 max-h-[45%] shrink-0 space-y-3 overflow-y-auto border-t border-edge pt-4">
                                                <SectionIntro title="Call agent" description={context.native_delegation.can_manage
                                                    ? 'Choose which agents this group can call and which local actions may trigger them.'
                                                    : 'The agents this group can call and the local actions that may trigger them.'} />
                                                <AgentDelegationManager scope={{ type: 'group', groupId: context.scope.id }}
                                                    allowManage={context.native_delegation.can_manage} interactionDisabled={accessUnconfirmed}
                                                    onDirtyChange={setDirty} onBusyChange={setResourceBusy} />
                                            </div>
                                        ) : null}
                                    </>
                                ) : section === 'actions' && context.native_delegation?.enabled && !resourceId ? (
                                    <>
                                        <SectionIntro title="Actions" description={context.native_delegation.can_manage
                                            ? 'Group actions are turned off for this group. You can still choose which agents this group can call and which local actions may trigger them.'
                                            : 'Group actions are turned off for this group. These are the agents this group can call and the local actions that may trigger them.'} />
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
                                ) : section === 'identities' && !resourceId && groupIdentityAdapter ? (
                                    <GroupIdentitiesSection adapter={groupIdentityAdapter}
                                        syncEnabled={context.sections.sync.enabled}
                                        actionsEnabled={context.sections.actions.enabled} />
                                ) : section === 'endpoints' && !resourceId && groupEndpointAdapter ? (
                                    <GroupEndpointsSection adapter={groupEndpointAdapter} />
                                ) : section === 'sync' && !resourceId && groupFileSourceAdapter ? (
                                    <GroupFileSourcesSection adapter={groupFileSourceAdapter} />
                                ) : section === 'settings' && !resourceId && groupSettingsAdapter ? (
                                    <GroupSettingsSection adapter={groupSettingsAdapter} management={context.settings_management}
                                        interactionDisabled={accessUnconfirmed}
                                        onBusyChange={reportDocumentBusy} onDirtyChange={reportDocumentDirty}
                                        onAccessChanged={revalidate} onSaved={refreshContextNow}
                                        onOpenClassic={() => openClassic(`/groups/${encodeURIComponent(context.scope.id)}`)} />
                                ) : section === 'activity' && !resourceId && groupSettingsAdapter ? (
                                    <GroupActivitySection adapter={groupSettingsAdapter} />
                                ) : section === 'statistics' && !resourceId && groupSettingsAdapter ? (
                                    <GroupStatisticsSection adapter={groupSettingsAdapter} />
                                ) : (
                                    <div className="flex items-center justify-center gap-2 py-12 text-sm text-text-3" role="status" aria-live="polite">
                                        <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                                        Opening the requested view...
                                    </div>
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
