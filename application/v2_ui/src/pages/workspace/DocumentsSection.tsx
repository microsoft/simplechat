// DocumentsSection.tsx
// Hosts the documents explorer inside the personal workspace.
//
// Thin on purpose: the explorer owns its own command bar, rail, status bar and internal
// scrolling, so the only thing left for this section is the sentence explaining where these
// files can come from.

import { useMemo } from 'react';
import { ArrowUpRight, FolderSync } from 'lucide-react';
import { Link } from 'react-router-dom';
import { DocumentExplorer } from '../../components/documents/DocumentExplorer';
import { ScreeningWorkspaceControls } from '../../components/screening/ScreeningWorkspaceControls';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { createGroupDocumentReader, createPublicDocumentReader } from '../../lib/documentReadAdapter';
import { createGroupDocumentOperations, createPublicDocumentOperations } from '../../lib/documentOperations';
import { createDocumentCollaboration, createPublicDocumentCollaboration } from '../../lib/documentCollaboration';
import type { GroupWorkspaceContext, PublicWorkspaceContext } from '../../lib/workspaceContext';
import { GlassButton } from '../../components/ui/primitives';

export function GroupDocumentsSection({
    context, interactionDisabled, onOpenClassic, onDirtyChange, onBusyChange,
    linkedDocumentId, linkedDocumentError, onClearLinkedDocument,
}: {
    context: GroupWorkspaceContext;
    interactionDisabled: boolean;
    onOpenClassic: () => void;
    onDirtyChange: (dirty: boolean) => void;
    onBusyChange: (busy: boolean) => void;
    linkedDocumentId?: string | null;
    linkedDocumentError?: string | null;
    onClearLinkedDocument?: () => void;
}) {
    const reader = useMemo(() => createGroupDocumentReader(
        context.scope.id, context.workspace.name, context.document_queries,
    ), [context.scope.id, context.workspace.name, context.document_queries]);
    const operations = useMemo(() => createGroupDocumentOperations(
        { kind: 'group', id: context.scope.id, name: context.workspace.name }, context.document_management,
    ), [context.scope.id, context.workspace.name, context.document_management]);
    const collaboration = useMemo(() => createDocumentCollaboration(
        { kind: 'group', id: context.scope.id, name: context.workspace.name }, context.document_collaboration,
    ), [context.scope.id, context.workspace.name, context.document_collaboration]);
    const canChange = [...operations.supported].some((operation) => operation !== 'download');

    return (
        <div className="flex h-full min-h-0 flex-col gap-2">
            <div className="shrink-0">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <h2 className="text-base font-semibold text-text-1">Documents</h2>
                    <GlassButton size="sm" disabled={interactionDisabled} onClick={onOpenClassic}
                        aria-label="Open classic tools for group documents" title="Classic tools, including upgrading legacy documents">
                        Classic tools<ArrowUpRight size={14} />
                    </GlassButton>
                </div>
                <p className="mt-0.5 text-sm text-text-3">{canChange
                    ? 'Manage group files. Each action follows current document permissions.'
                    : 'Read-only browsing for this group.'}</p>
            </div>
            <div className="min-h-0 flex-1">
                <DocumentExplorer reader={reader} operations={operations} collaboration={collaboration}
                    canChat={context.document_permissions.can_chat}
                    interactionDisabled={interactionDisabled} workspaceStatus={context.status}
                    onDirtyChange={onDirtyChange} onBusyChange={onBusyChange}
                    linkedDocumentId={linkedDocumentId} linkedDocumentError={linkedDocumentError}
                    onClearLinkedDocument={onClearLinkedDocument} />
            </div>
        </div>
    );
}

export function PublicDocumentsSection({
    context, interactionDisabled, onOpenClassic, onDirtyChange, onBusyChange,
    linkedDocumentId, linkedDocumentError, onClearLinkedDocument,
}: {
    context: PublicWorkspaceContext;
    interactionDisabled: boolean;
    onOpenClassic: () => void;
    onDirtyChange: (dirty: boolean) => void;
    onBusyChange: (busy: boolean) => void;
    linkedDocumentId?: string | null;
    linkedDocumentError?: string | null;
    onClearLinkedDocument?: () => void;
}) {
    const reader = useMemo(() => createPublicDocumentReader(
        context.scope.id, context.workspace.name, context.document_queries,
    ), [context.scope.id, context.workspace.name, context.document_queries]);
    const operations = useMemo(() => createPublicDocumentOperations(
        { kind: 'public', id: context.scope.id, name: context.workspace.name }, context.document_management,
    ), [context.scope.id, context.workspace.name, context.document_management]);
    const collaboration = useMemo(() => createPublicDocumentCollaboration(
        { kind: 'public', id: context.scope.id, name: context.workspace.name }, context.document_collaboration,
    ), [context.scope.id, context.workspace.name, context.document_collaboration]);
    const canChange = [...operations.supported].some((operation) => operation !== 'download');

    return (
        <div className="flex h-full min-h-0 flex-col gap-2">
            <div className="shrink-0">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <h2 className="text-base font-semibold text-text-1">Documents</h2>
                    <GlassButton size="sm" disabled={interactionDisabled} onClick={onOpenClassic}
                        aria-label="Open classic public workspace" title="Browse public documents in classic">
                        <span className="hidden sm:inline">Browse in</span> Classic<ArrowUpRight size={14} />
                    </GlassButton>
                </div>
                <p className="mt-0.5 text-sm text-text-3">{canChange
                    ? 'Manage public files. Each action follows current document permissions.'
                    : 'Read-only browsing for this public workspace.'}</p>
            </div>
            <div className="min-h-0 flex-1">
                <DocumentExplorer reader={reader} operations={operations} collaboration={collaboration}
                    canChat={context.document_permissions.can_chat}
                    interactionDisabled={interactionDisabled} workspaceStatus={context.status}
                    onDirtyChange={onDirtyChange} onBusyChange={onBusyChange}
                    linkedDocumentId={linkedDocumentId} linkedDocumentError={linkedDocumentError}
                    onClearLinkedDocument={onClearLinkedDocument} />
            </div>
        </div>
    );
}

export function DocumentsSection({ syncEnabled }: { syncEnabled: boolean }) {
    const userId = useBootstrapStore((state) => state.data?.user.id);
    return (
        <div className="flex h-full min-h-0 flex-col gap-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div className="min-w-0">
                    <h2 className="text-base font-semibold text-text-1">Documents</h2>
                    <p className="mt-0.5 text-sm text-text-3">
                        Files you upload here are indexed and can be cited in chat. Everything
                        in this section is private to you.
                    </p>
                </div>

                {userId ? <ScreeningWorkspaceControls scope={{ scope_type: 'personal', scope_id: userId }} /> : null}

                {syncEnabled ? (
                    <p className="text-xs text-text-3">
                        Documents can also arrive automatically from a{' '}
                        <Link to="/workspace/sync" className="text-accent hover:underline">
                            file source
                        </Link>
                        .
                    </p>
                ) : (
                    <p className="flex items-center gap-1.5 text-xs text-text-3">
                        <FolderSync size={13} />
                        File sync is not enabled for your account, so documents can only be
                        added by uploading them.
                    </p>
                )}
            </div>

            <div className="min-h-0 flex-1">
                <DocumentExplorer />
            </div>
        </div>
    );
}
