// PublicWorkspacePage.tsx
//
// The V2 public workspace surface. It mirrors GroupWorkspacePage but is deliberately simpler:
// there is no activate/reconcile handshake, because every read and every operation carries the
// workspace id in its immutable path. PUBLIC_WORKSPACES.setActive is fired only as a non-blocking
// courtesy that keeps the classic surface and chat scoping in step -- it never gates a read,
// navigation, or a document operation. From M3B the explorer can mutate documents, so the page
// tracks the explorer's dirty/busy state to warn before leaving with unsaved edits, but that
// state is never allowed to gate setActive.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useBlocker, useLocation, useNavigate, useParams } from 'react-router-dom';
import { ArrowUpRight, Globe, LayoutGrid, Loader2, Lock } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { EmptyState, GlassButton, GlassPanel, Skeleton } from '../components/ui/primitives';
import { PublicWorkspacePicker } from '../components/workspace/PublicWorkspacePicker';
import { WorkspaceLeavePrompt } from '../components/workspace/WorkspaceEditorFrame';
import { WorkspaceOverview } from '../components/workspace/WorkspaceOverview';
import { WorkspaceShell } from '../components/workspace/WorkspaceShell';
import { Pill, SectionIntro } from '../components/workspace/primitives';
import {
    PUBLIC_SECTION_BLURBS, PUBLIC_STATUS_LABELS, publicWorkspacePath,
    classicPublicSectionLabel, isPublicManageSection, readPublicDocumentTarget,
} from '../lib/publicWorkspaceNavigation';
import { PUBLIC_WORKSPACE_SECTION_IDS } from '../lib/workspaceContext';
import { usePublicWorkspaceLabels } from '../lib/publicWorkspaceLabels';
import { resolveWorkspaceSections } from '../lib/workspaceSections';
import { PUBLIC_WORKSPACES } from '../lib/workspaces';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { usePublicWorkspaceStore, PublicWorkspaceRequestSuperseded } from '../stores/publicWorkspaceStore';
import { WORKSPACE_SECTIONS_BY_ID } from './workspace/sections';
import { PUBLIC_MANAGE_SECTIONS } from './workspace/publicManageSections';
import { PublicDocumentsSection } from './workspace/DocumentsSection';
import { PublicMembersSection } from './workspace/PublicMembersSection';

const CLASSIC_WORKSPACE_HREF = '/public_workspaces';

export function PublicWorkspacePage() {
    const { workspaceId, section, resourceId } = useParams<{ workspaceId?: string; section?: string; resourceId?: string }>();
    const navigate = useNavigate();
    const location = useLocation();
    const linkedDocument = useMemo(() => readPublicDocumentTarget(location.search), [location.search]);
    const hasDocumentLink = Boolean(linkedDocument.id || linkedDocument.error);
    const bootstrap = useBootstrapStore((state) => state.data);
    const state = usePublicWorkspaceStore();
    const viewerId = bootstrap?.user?.id;
    const enabled = Boolean(bootstrap?.features?.enable_public_workspaces);
    const labels = usePublicWorkspaceLabels();
    const activeWorkspaceId = bootstrap?.scope?.active_public_workspace_id;
    const [notice, setNotice] = useState('');
    const [retry, setRetry] = useState(0);
    const [logoFailed, setLogoFailed] = useState(false);
    const [dirty, setDirty] = useState(false);
    const [resourceBusy, setResourceBusy] = useState(false);
    const dirtyRef = useRef(false);
    const busyRef = useRef(false);
    const initialization = useRef<{ key: string; promise: Promise<unknown> } | null>(null);
    dirtyRef.current = dirty;
    busyRef.current = resourceBusy;
    // The explorer reports busy/dirty for the M3B management operations. These gate only the
    // leave-blocker and the beforeunload warning, never setActive, reads, or the operations.
    const reportDocumentDirty = useCallback((value: boolean) => { dirtyRef.current = value; setDirty(value); }, []);
    const reportDocumentBusy = useCallback((value: boolean) => { busyRef.current = value; setResourceBusy(value); }, []);

    const blocker = useBlocker(({ currentLocation, nextLocation }) =>
        (dirtyRef.current || busyRef.current)
        && (currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search));

    useEffect(() => {
        if (!workspaceId && !hasDocumentLink && enabled && activeWorkspaceId) {
            navigate(`${publicWorkspacePath(activeWorkspaceId)}${location.search}`, { replace: true });
        }
        if (workspaceId && !section && hasDocumentLink && enabled) {
            navigate(`${publicWorkspacePath(workspaceId, 'documents')}${location.search}`, { replace: true });
        }
    }, [workspaceId, enabled, activeWorkspaceId, section, location.search, navigate, hasDocumentLink]);

    // The Manage sections (M10A Members) have no item route, so a stray trailing segment opens the
    // section itself rather than leaving the reader on a URL that renders nothing it understands.
    useEffect(() => {
        if (!workspaceId || !section || !resourceId || !isPublicManageSection(section)) return;
        navigate(publicWorkspacePath(workspaceId, section), { replace: true });
    }, [workspaceId, section, resourceId, navigate]);

    useEffect(() => {
        if (!workspaceId || !viewerId || !enabled) {
            initialization.current = null;
            return;
        }
        const key = JSON.stringify([workspaceId, viewerId, retry]);
        const current = usePublicWorkspaceStore.getState();
        if (initialization.current?.key !== key) {
            setNotice('');
            const sameContext = current.context?.scope.id === workspaceId && current.context.viewer_id === viewerId;
            const promise = sameContext ? current.revalidate(workspaceId) : current.load(workspaceId);
            initialization.current = { key, promise };
        }
        let mounted = true;
        void initialization.current.promise.catch((cause: unknown) => {
            if (mounted && !(cause instanceof PublicWorkspaceRequestSuperseded)) {
                setNotice(usePublicWorkspaceStore.getState().error || 'Could not load this workspace. Please retry.');
            }
        });
        return () => { mounted = false; };
    }, [workspaceId, viewerId, enabled, retry]);

    const revalidate = useCallback(() => {
        const current = usePublicWorkspaceStore.getState();
        if (!workspaceId || !enabled || document.visibilityState !== 'visible'
            || current.loading || current.refreshing || current.context?.scope.id !== workspaceId) return;
        void current.revalidate(workspaceId).then(() => {
            if (!usePublicWorkspaceStore.getState().error) setNotice('');
        }).catch((cause: unknown) => {
            if (!(cause instanceof PublicWorkspaceRequestSuperseded)) {
                setNotice(usePublicWorkspaceStore.getState().error || 'Could not refresh this workspace.');
            }
        });
    }, [workspaceId, enabled]);
    useEffect(() => {
        window.addEventListener('focus', revalidate);
        document.addEventListener('visibilitychange', revalidate);
        return () => {
            window.removeEventListener('focus', revalidate);
            document.removeEventListener('visibilitychange', revalidate);
        };
    }, [revalidate]);

    const context = state.context && state.context.scope.id === workspaceId && state.context.viewer_id === viewerId ? state.context : null;
    const ready = context && !state.loading;
    const basePath = workspaceId ? publicWorkspacePath(workspaceId) : '/public';
    const sections = useMemo(() => PUBLIC_WORKSPACE_SECTION_IDS.map((id) => {
        const { label, icon, group } = WORKSPACE_SECTIONS_BY_ID[id];
        return {
            id, label, icon, group, blurb: PUBLIC_SECTION_BLURBS[id],
            availabilityLabel: id === 'documents' ? undefined : 'Classic',
        };
    }), []);
    const resolved = useMemo(() => resolveWorkspaceSections([...sections, ...PUBLIC_MANAGE_SECTIONS], context), [sections, context]);
    const selected = resolved.find((entry) => entry.section.id === section);
    const nativeDocuments = Boolean(ready && section === 'documents' && !resourceId
        && selected?.enabled && context.document_permissions.can_view);

    useEffect(() => { setLogoFailed(false); }, [context?.scope.id, context?.workspace.logo_url]);
    useEffect(() => {
        setNotice('');
        setDirty(false);
        setResourceBusy(false);
    }, [viewerId]);

    useEffect(() => {
        if (!dirty && !resourceBusy) return;
        const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
        window.addEventListener('beforeunload', beforeUnload);
        return () => window.removeEventListener('beforeunload', beforeUnload);
    }, [dirty, resourceBusy]);

    const selectWorkspace = useCallback((id: string) => {
        setNotice('');
        // setActive is a courtesy for the classic surface and chat scoping. It is deliberately
        // fire-and-forget: navigation and reads target the id in the path, never this write.
        void PUBLIC_WORKSPACES.setActive(id).catch((cause: unknown) => {
            const detail = cause instanceof Error ? cause.message : 'setActive failed';
            console.warn(`${labels.singular} setActive did not complete: ${detail}`);
        });
        const params = new URLSearchParams(location.search);
        if (id !== workspaceId) {
            params.delete('document_id');
            params.delete('public_workspace_id');
            params.delete('group_id');
            params.delete('group_ids');
        }
        navigate(`${publicWorkspacePath(id, section)}${params.size ? `?${params}` : ''}`, { replace: !workspaceId });
    }, [location.search, navigate, section, workspaceId]);

    const clearDocumentLink = useCallback(() => {
        const params = new URLSearchParams(location.search);
        params.delete('document_id');
        params.delete('public_workspace_id');
        params.delete('group_id');
        params.delete('group_ids');
        navigate(`${location.pathname}${params.size ? `?${params}` : ''}`, { replace: true });
    }, [location.pathname, location.search, navigate]);

    const openClassic = useCallback((href: string) => { window.location.assign(href); }, []);

    const header = (
        <>
            <PageHeader title={labels.plural} description="Read-only shared knowledge published for everyone" leading={<Globe size={20} className="text-accent" />}
                actions={<GlassButton size="sm" variant="subtle" onClick={() => navigate('/public/directory')}><LayoutGrid size={14} />Public directory</GlassButton>} />
            <div className="shrink-0 space-y-3 border-b border-edge px-4 py-3">
                <PublicWorkspacePicker key={viewerId} value={state.pendingWorkspaceId ?? workspaceId}
                    selectedName={context?.workspace.name || bootstrap?.scope?.public_workspaces?.find((workspace) => workspace.id === workspaceId)?.name}
                    disabled={state.loading}
                    onSelect={(id) => selectWorkspace(id)} />
                {ready ? (
                    <div className="flex min-w-0 flex-wrap items-center gap-3">
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-lg border bg-surface-1"
                            style={{ borderColor: context.workspace.hero_color }}>
                            {context.workspace.logo_url && !logoFailed ? (
                                <img src={context.workspace.logo_url} alt="" className="h-full w-full object-contain" onError={() => setLogoFailed(true)} />
                            ) : <Globe size={18} className="text-text-2" />}
                        </div>
                        <div className="min-w-0 flex-1 basis-48">
                            <p className="break-words text-sm font-semibold text-text-1">{context.workspace.name}</p>
                            <p className="text-xs text-text-3">Read-only {labels.lower_singular}</p>
                        </div>
                        <Pill tone={context.status === 'active' ? 'neutral' : 'warn'}>Status: {PUBLIC_STATUS_LABELS[context.status]}</Pill>
                    </div>
                ) : null}
                {state.refreshing ? <p role="status" className="text-xs text-text-3">Refreshing workspace access...</p> : null}
            </div>
        </>
    );

    if (!enabled) return (
        <div className="flex h-full flex-col">
            <PageHeader title={labels.plural} />
            <div className="p-4"><EmptyState icon={<Lock size={28} />} title={`${labels.plural} are not enabled`}
                description={`Your administrator has not enabled ${labels.lower_plural} for this deployment.`} /></div>
        </div>
    );

    const error = notice || state.error;
    return (
        <WorkspaceShell header={header} basePath={basePath} sections={ready ? resolved : []} fullBleed={nativeDocuments}>
            {error ? <div role="alert" className="mb-4 space-y-2 rounded-xl border border-danger/30 bg-danger-soft p-3 text-sm text-danger">
                <p>{error}</p>
                <GlassButton size="sm" disabled={state.loading || state.refreshing} onClick={() => {
                    setNotice('');
                    setRetry((value) => value + 1);
                }}>Retry workspace details</GlassButton>
            </div> : null}
            {state.loading ? (
                <div role="status" className="space-y-3">
                    <p className="flex items-center gap-2 text-sm text-text-2"><Loader2 size={16} className="animate-spin" />Loading workspace details...</p>
                    <Skeleton className="h-20 w-full" /><Skeleton className="h-32 w-full" />
                </div>
            ) : !workspaceId ? (
                <EmptyState icon={<Globe size={28} />} title={`Choose a ${labels.lower_singular}`}
                    description={hasDocumentLink ? `A document link must include its explicit ${labels.lower_singular}. Choose one and open the document from that workspace.`
                        : `Select a ${labels.lower_singular} above to browse its published documents.`}
                    action={<GlassButton size="sm" variant="subtle" onClick={() => navigate('/public/directory')}><LayoutGrid size={14} />Browse the public directory</GlassButton>} />
            ) : ready ? (
                <div key={`${context.scope.id}:${section ?? 'overview'}`}
                    className={nativeDocuments ? 'flex min-h-0 flex-1 flex-col' : 'space-y-4'}>
                    {!section ? (
                        <>
                            <dl className="space-y-2 text-sm text-text-2">
                                <div><dt className="text-xs text-text-3">About this workspace</dt><dd className="break-words">{context.workspace.description || 'No description provided.'}</dd></div>
                                <div><dt className="text-xs text-text-3">Owner</dt><dd className="break-words">{context.workspace.owner.display_name || 'Owner information unavailable'}{context.workspace.owner.email ? ` · ${context.workspace.owner.email}` : ''}</dd></div>
                            </dl>
                            <WorkspaceOverview basePath={basePath} resolved={resolved} showRelationships={false}
                                description={`Published documents for this ${labels.lower_singular}. Sections marked Classic open in the existing interface while their V2 experience is being built.`} />
                        </>
                    ) : !selected ? <EmptyState icon={<LayoutGrid size={28} />} title="Section not found" description="Choose a section from this workspace's navigation." />
                        : !selected.enabled ? <EmptyState icon={<Lock size={28} />} title={`${selected.section.label} is not available`} description={selected.reason ?? undefined} />
                            : section === 'members' && !resourceId ? (
                                <PublicMembersSection workspaceId={context.scope.id} workspaceName={context.workspace.name}
                                    viewerId={context.viewer_id} interactionDisabled={false}
                                    onBusyChange={reportDocumentBusy} onAccessChanged={revalidate} />
                            )
                            : section === 'documents' && !resourceId ? (
                                context.document_permissions.can_view ? <PublicDocumentsSection context={context}
                                    interactionDisabled={false} onOpenClassic={() => openClassic(CLASSIC_WORKSPACE_HREF)}
                                    onDirtyChange={reportDocumentDirty} onBusyChange={reportDocumentBusy}
                                    linkedDocumentId={linkedDocument.id} linkedDocumentError={linkedDocument.error}
                                    onClearLinkedDocument={clearDocumentLink} />
                                    : <EmptyState icon={<Lock size={28} />} title="Documents are not available" description={`You do not have access to this ${labels.lower_singular}'s documents.`} />
                            ) : (
                                <GlassPanel elevation="flat" className="space-y-4 p-5">
                                    <SectionIntro title={selected.section.label} description={selected.section.blurb} />
                                    <p className="text-sm text-text-2">This section is available in the classic {labels.lower_singular}. Choose {classicPublicSectionLabel(selected.section.id, selected.section.label)} there; {context.workspace.name} will be selected for you.</p>
                                    <GlassButton variant="primary" onClick={() => openClassic(CLASSIC_WORKSPACE_HREF)}>Open classic {labels.lower_singular}<ArrowUpRight size={15} /></GlassButton>
                                </GlassPanel>
                            )}
                </div>
            ) : !error ? <EmptyState title="Workspace details unavailable" description={`Select another ${labels.lower_singular} or refresh workspace details.`} /> : null}
            {blocker.state === 'blocked' ? <WorkspaceLeavePrompt
                saving={resourceBusy}
                onStay={() => { if (blocker.state === 'blocked') blocker.reset(); }}
                onDiscard={() => {
                    setDirty(false);
                    if (blocker.state === 'blocked') blocker.proceed();
                }} /> : null}
        </WorkspaceShell>
    );
}
