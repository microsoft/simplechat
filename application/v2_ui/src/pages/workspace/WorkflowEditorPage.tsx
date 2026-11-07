// WorkflowEditorPage.tsx
// A workflow's editor as a page of its workspace: /workspace/workflows/<id>, or .../new to create
// one, and the same paths under a group.
//
// The editor used to be a dialog over the workflows list. It is a page now for the reasons the
// Agents and Actions editors are: a workflow is long enough to want the whole width, the Admin
// wide frame and its On this page index need a page to live in, and an editor with its own
// address can be linked to, reloaded and left with the browser's Back. The editor itself is
// unchanged (`WorkflowEditorDialog` in its page presentation); this component finds the
// workflow, gates it on the workspace's permission hints, and owns how the page is left.
//
// Leaving with unsaved changes asks first, as the Agents and Actions editors do. In a personal
// workspace this page asks. In a group the group page already guards every navigation and the
// switch to another group, so this page only reports its draft there; a second router blocker
// would silently replace the group's.

import { useCallback, useEffect, useRef, useState, type MutableRefObject, type ReactNode } from 'react';
import { useBlocker, useNavigate } from 'react-router-dom';
import { ArrowLeft, Lock, TriangleAlert, Workflow } from 'lucide-react';
import { WorkflowEditorDialog } from '../../components/workflows/WorkflowEditorDialog';
import { WorkspaceLeavePrompt } from '../../components/workspace/WorkspaceEditorFrame';
import { EmptyState, GlassButton, Skeleton } from '../../components/ui/primitives';
import {
    fetchScopedWorkflows,
    fetchWorkflowEditorOptions,
    workflowErrorMessage,
    workflowScopeKey,
    type WorkflowDefinition,
    type WorkflowEditorOptions,
    type WorkflowScope,
} from '../../lib/workflowEditor';
import { NEW_WORKFLOW_RESOURCE, workflowListHref } from '../../lib/workflowRunLink';
import { isRecord } from '../../lib/workspaceAuthoring';

type EditorLoad =
    | { status: 'loading' }
    | { status: 'failed'; message: string }
    | { status: 'missing' }
    | { status: 'ready'; options: WorkflowEditorOptions; workflow: WorkflowDefinition | null };

/** Asks before a navigation would discard the draft, as the Agents and Actions editors do. */
function WorkflowLeaveGuard({ dirtyRef, busyRef, busy }: {
    dirtyRef: MutableRefObject<boolean>;
    busyRef: MutableRefObject<boolean>;
    busy: boolean;
}) {
    const blocker = useBlocker(({ currentLocation, nextLocation }) => {
        if (!dirtyRef.current && !busyRef.current) return false;
        // A save returns to the workbench on its own; that navigation never asks.
        if (isRecord(nextLocation.state) && nextLocation.state.workspaceEditorSaved === true) return false;
        return currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search;
    });
    return blocker.state === 'blocked' ? (
        <WorkspaceLeavePrompt saving={busy} onStay={() => blocker.reset()} onDiscard={() => blocker.proceed()} />
    ) : null;
}

/** A state the page shows instead of the editor, with the way back. */
function EditorPlaceholder({ scope, workflowId, children }: {
    scope: WorkflowScope;
    workflowId: string | null;
    children: ReactNode;
}) {
    const navigate = useNavigate();
    return (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="shrink-0 border-b border-edge px-1 py-3 sm:px-4 lg:px-6">
                <GlassButton type="button" size="sm" onClick={() => navigate(workflowListHref(scope, workflowId))}>
                    <ArrowLeft size={15} aria-hidden="true" /> Back
                </GlassButton>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-1 py-4 sm:px-4 lg:p-6">{children}</div>
        </div>
    );
}

export function WorkflowEditorPage({
    scope,
    resourceId,
    allowManage = true,
    operations,
    interactionDisabled = false,
    guardNavigation = true,
    scopeLabel,
    onDirtyChange,
    onBusyChange,
}: {
    scope: WorkflowScope;
    /** The workflow id from the path, or `new`. */
    resourceId: string;
    allowManage?: boolean;
    /** The group workflow hint's operations; without one, `allowManage` gates create and edit. */
    operations?: readonly string[];
    interactionDisabled?: boolean;
    /** Ask before leaving with unsaved changes. Off where the surrounding page already guards. */
    guardNavigation?: boolean;
    /** The workspace named under the editor's title. */
    scopeLabel?: string;
    onDirtyChange?: (dirty: boolean) => void;
    onBusyChange?: (busy: boolean) => void;
}) {
    const navigate = useNavigate();
    const scopeKey = workflowScopeKey(scope);
    const isNew = resourceId === NEW_WORKFLOW_RESOURCE;
    const offered = Array.isArray(operations) ? new Set(operations) : null;
    const canCreate = offered ? offered.has('create') : allowManage;
    const canEdit = offered ? offered.has('edit') : allowManage;
    const [load, setLoad] = useState<EditorLoad>({ status: 'loading' });
    const [attempt, setAttempt] = useState(0);
    // A reload after Ask AI changed the saved workflow opens a fresh editor on the saved version.
    const [instance, setInstance] = useState(0);
    const [busy, setBusy] = useState(false);
    const dirtyRef = useRef(false);
    const busyRef = useRef(false);

    // Refs update at once rather than on the next render, so a save can leave immediately
    // without its own navigation tripping the guard it just satisfied.
    const reportDirty = useCallback((value: boolean) => {
        dirtyRef.current = value;
        onDirtyChange?.(value);
    }, [onDirtyChange]);
    const reportBusy = useCallback((value: boolean) => {
        busyRef.current = value;
        setBusy(value);
        onBusyChange?.(value);
    }, [onBusyChange]);

    useEffect(() => {
        const controller = new AbortController();
        setLoad({ status: 'loading' });
        void Promise.all([
            fetchWorkflowEditorOptions(scope, controller.signal),
            isNew ? Promise.resolve(null) : fetchScopedWorkflows(scope, controller.signal),
        ]).then(([options, workflows]) => {
            if (controller.signal.aborted) return;
            if (isNew) {
                setLoad({ status: 'ready', options, workflow: null });
                return;
            }
            const workflow = workflows?.find((item) => item.id === resourceId) ?? null;
            setLoad(workflow ? { status: 'ready', options, workflow } : { status: 'missing' });
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) {
                setLoad({ status: 'failed', message: workflowErrorMessage(cause, 'Could not load workflow editor options.') });
            }
        });
        return () => controller.abort();
        // The scope key stands in for the scope object, which callers rebuild on every render.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [scopeKey, resourceId, isNew, attempt]);

    const backTo = isNew ? null : resourceId;

    // Ask AI offers this after the saved workflow changed while the editor was open. It discards
    // the draft and opens the saved version; a failure leaves the editor as it was.
    const reloadSaved = async () => {
        const [workflows, options] = await Promise.all([
            fetchScopedWorkflows(scope),
            fetchWorkflowEditorOptions(scope),
        ]);
        const fresh = workflows.find((item) => item.id === resourceId);
        reportDirty(false);
        setLoad(fresh ? { status: 'ready', options, workflow: fresh } : { status: 'missing' });
        setInstance((count) => count + 1);
    };

    if (load.status === 'loading') {
        return (
            <EditorPlaceholder scope={scope} workflowId={backTo}>
                <div role="status" className="mx-auto w-full max-w-[112rem] space-y-4">
                    <span className="sr-only">Loading the workflow editor</span>
                    <Skeleton className="h-8 w-72" />
                    <Skeleton className="h-48 w-full" />
                    <Skeleton className="h-48 w-full" />
                </div>
            </EditorPlaceholder>
        );
    }
    if (load.status === 'failed') {
        return (
            <EditorPlaceholder scope={scope} workflowId={backTo}>
                {/* Announced as it appears, as the section's own load failure is. */}
                <div role="alert">
                    <EmptyState
                        icon={<TriangleAlert size={28} />}
                        title="The workflow editor could not load"
                        description={load.message}
                        action={<GlassButton type="button" size="sm" variant="subtle" onClick={() => setAttempt((count) => count + 1)}>
                            Retry
                        </GlassButton>}
                    />
                </div>
            </EditorPlaceholder>
        );
    }
    if (load.status === 'missing') {
        return (
            <EditorPlaceholder scope={scope} workflowId={null}>
                <EmptyState
                    icon={<Workflow size={28} />}
                    title="Workflow not found"
                    description="This workflow is no longer available in this workspace."
                />
            </EditorPlaceholder>
        );
    }
    if (isNew && !canCreate) {
        return (
            <EditorPlaceholder scope={scope} workflowId={null}>
                <EmptyState
                    icon={<Lock size={28} />}
                    title="You can't create a workflow here"
                    description="You cannot create workflows with the current workspace access."
                />
            </EditorPlaceholder>
        );
    }

    return (
        <>
            <WorkflowEditorDialog
                key={`${scopeKey}:${resourceId}:${instance}`}
                presentation="page"
                pageScopeLabel={scopeLabel}
                scope={scope}
                workflow={load.workflow}
                options={{ ...load.options, can_manage: load.options.can_manage && (isNew ? canCreate : canEdit) }}
                interactionDisabled={interactionDisabled}
                onBusyChange={reportBusy}
                onDirtyChange={reportDirty}
                onReload={isNew ? undefined : reloadSaved}
                onClose={() => navigate(workflowListHref(scope, backTo))}
                onSaved={(saved) => {
                    reportBusy(false);
                    reportDirty(false);
                    navigate(workflowListHref(scope, saved.id ?? backTo), {
                        replace: true,
                        state: { workspaceEditorSaved: true },
                    });
                }}
            />
            {guardNavigation ? <WorkflowLeaveGuard dirtyRef={dirtyRef} busyRef={busyRef} busy={busy} /> : null}
        </>
    );
}
