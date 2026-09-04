// ConversationDrawer.tsx
// Right-hand drawer with three modes, mirroring the legacy offcanvas that hosts both a
// table of contents and the documents used in the conversation, plus the orchestration plan.
//
// Contents lists the user's turns so a long thread can be navigated; Documents lists the
// document-level citation aggregates the server records on the conversation; Plan hosts the
// orchestration plan surface when the feature is on.

import { useEffect, useMemo } from 'react';
import { clsx } from 'clsx';
import {
    FileText,
    Files,
    ListOrdered,
    ListTree,
    Quote,
    TriangleAlert,
    X,
} from 'lucide-react';
import { useChatStore, type DrawerMode } from '../../stores/chatStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { EmptyState, Skeleton } from '../ui/primitives';
import { OrchestrationPlanPanel } from './OrchestrationPlanPanel';
import type { UsedDocument } from '../../lib/types';

/** Scroll a message into view and flash it, so the jump target is obvious. */
function scrollToMessage(messageId: string) {
    const element = document.getElementById(`message-${messageId}`);
    if (!element) {
        return;
    }
    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    element.classList.add('ring-2', 'ring-accent', 'rounded-2xl');
    window.setTimeout(() => {
        element.classList.remove('ring-2', 'ring-accent', 'rounded-2xl');
    }, 1400);
}

function ContentsMode() {
    const messages = useChatStore((state) => state.messages);

    // The table of contents indexes the user's turns: those are the questions someone
    // scans for when navigating back through a long conversation.
    const userTurns = useMemo(
        () => messages.filter((message) => message.role === 'user'),
        [messages],
    );

    if (userTurns.length === 0) {
        return (
            <EmptyState
                icon={<ListOrdered size={24} />}
                title="Nothing to jump to yet"
                description="Your questions will be listed here so you can navigate a long conversation."
            />
        );
    }

    return (
        <ol className="space-y-1 p-3">
            {userTurns.map((message, index) => (
                <li key={message.id}>
                    <button
                        type="button"
                        onClick={() => scrollToMessage(message.id)}
                        className="flex w-full gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-surface-2"
                    >
                        <span className="mt-0.5 shrink-0 font-mono text-xs text-text-3">
                            {index + 1}
                        </span>
                        <span className="line-clamp-3 text-sm text-text-2">
                            {message.content}
                        </span>
                    </button>
                </li>
            ))}
        </ol>
    );
}

function scopeLabel(document: UsedDocument): string {
    const scope = document.scope;
    if (!scope?.type) {
        return '';
    }
    if (scope.name) {
        return scope.name;
    }
    if (scope.type === 'personal') {
        return 'Personal workspace';
    }
    if (scope.type === 'group') {
        return 'Group workspace';
    }
    if (scope.type === 'public') {
        return 'Public workspace';
    }
    return scope.type;
}

/** Summarize where in a document the citations landed. */
function locationLabel(document: UsedDocument): string {
    const pages = (document.page_numbers ?? []).filter(
        (page) => page !== null && page !== undefined && page !== '',
    );
    if (pages.length > 0) {
        return `Page${pages.length > 1 ? 's' : ''} ${pages.join(', ')}`;
    }
    const sheets = (document.sheet_names ?? []).filter(Boolean);
    if (sheets.length > 0) {
        return `Sheet${sheets.length > 1 ? 's' : ''} ${sheets.join(', ')}`;
    }
    return '';
}

function DocumentRow({ document }: { document: UsedDocument }) {
    const name =
        document.title || document.file_name || document.document_id || 'Untitled document';
    // A document can be attached to the conversation without having been cited yet, so
    // the badge distinguishes "used as grounding" from "actually referenced".
    const isCited = (document.citation_ids ?? []).length > 0;
    const scope = scopeLabel(document);
    const location = locationLabel(document);

    return (
        <li className="glass-flat rounded-xl p-3">
            <div className="flex items-start gap-2.5">
                <FileText size={16} className="mt-0.5 shrink-0 text-text-3" />
                <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-text-1" title={name}>
                        {name}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-3">
                        {isCited && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-1.5 py-0.5 text-accent">
                                <Quote size={10} />
                                Cited
                            </span>
                        )}
                        {location && <span>{location}</span>}
                        {scope && <span>{scope}</span>}
                        {document.classification && <span>{document.classification}</span>}
                    </div>
                </div>
            </div>
        </li>
    );
}

function DocumentsMode() {
    const { metadata, metadataLoading, metadataError, activeConversationId, loadMetadata } =
        useChatStore();

    useEffect(() => {
        if (activeConversationId && !metadata && !metadataLoading && !metadataError) {
            void loadMetadata(activeConversationId);
        }
    }, [activeConversationId, metadata, metadataLoading, metadataError, loadMetadata]);

    const documents = useMemo(() => {
        if (!metadata) {
            return [] as UsedDocument[];
        }
        // Three sources, all document-shaped: current aggregates, the pre-v2 tracking
        // list, and files uploaded straight into the conversation. De-duplicated by id so
        // a document present in more than one does not appear twice.
        const merged = new Map<string, UsedDocument>();
        for (const list of [
            metadata.used_documents,
            metadata.legacy_used_documents,
            metadata.linked_workspace_documents,
        ]) {
            for (const document of list ?? []) {
                const id = String(document?.document_id ?? '').trim();
                if (id && !merged.has(id)) {
                    merged.set(id, document);
                }
            }
        }
        return [...merged.values()];
    }, [metadata]);

    if (metadataLoading && !metadata) {
        return (
            <div className="space-y-2 p-3">
                {Array.from({ length: 3 }).map((_, index) => (
                    <Skeleton key={index} className="h-16 w-full" />
                ))}
            </div>
        );
    }

    if (metadataError) {
        return (
            <div className="flex items-start gap-2 p-3 text-sm text-danger">
                <TriangleAlert size={16} className="mt-0.5 shrink-0" />
                {metadataError}
            </div>
        );
    }

    if (documents.length === 0) {
        return (
            <EmptyState
                icon={<Files size={24} />}
                title="No documents used yet"
                description="Documents referenced while answering will be listed here."
            />
        );
    }

    return (
        <ul className="space-y-2 p-3">
            {documents.map((document) => (
                <DocumentRow key={document.document_id} document={document} />
            ))}
        </ul>
    );
}

export function ConversationDrawer() {
    const { drawerMode, setDrawerMode } = useChatStore();
    const contentsEnabled = useBootstrapStore((state) =>
        Boolean(state.data?.features?.enable_conversation_contents_drawer),
    );
    const orchestrationEnabled = useBootstrapStore((state) =>
        Boolean(
            state.data?.features?.enable_chat_orchestration &&
                state.data?.orchestration?.enabled,
        ),
    );

    // Close on Escape, matching the dismissal behaviour of the rest of the app.
    useEffect(() => {
        if (!drawerMode) {
            return;
        }
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setDrawerMode(null);
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [drawerMode, setDrawerMode]);

    if (!drawerMode) {
        return null;
    }

    const tabs: Array<{ id: Exclude<DrawerMode, null>; label: string; icon: typeof Files }> = [
        ...(contentsEnabled
            ? [{ id: 'contents' as const, label: 'Contents', icon: ListOrdered }]
            : []),
        { id: 'documents' as const, label: 'Documents', icon: Files },
        ...(orchestrationEnabled
            ? [{ id: 'plan' as const, label: 'Plan', icon: ListTree }]
            : []),
    ];

    return (
        <aside
            aria-label="Conversation details"
            className="glass glass-edge flex w-[22rem] shrink-0 flex-col rounded-none border-t-0 border-r-0 border-b-0"
        >
            <div className="flex h-14 shrink-0 items-center gap-2 border-b border-edge px-3">
                <div
                    role="tablist"
                    aria-label="Drawer mode"
                    className="flex gap-1 rounded-xl bg-surface-sunken p-1"
                >
                    {tabs.map((tab) => (
                        <button
                            key={tab.id}
                            type="button"
                            role="tab"
                            aria-selected={drawerMode === tab.id}
                            onClick={() => setDrawerMode(tab.id)}
                            className={clsx(
                                'inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm transition-colors',
                                drawerMode === tab.id
                                    ? 'bg-surface-3 font-medium text-text-1'
                                    : 'text-text-3 hover:text-text-1',
                            )}
                        >
                            <tab.icon size={14} />
                            {tab.label}
                        </button>
                    ))}
                </div>

                <button
                    type="button"
                    onClick={() => setDrawerMode(null)}
                    aria-label="Close panel"
                    className="ml-auto rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                >
                    <X size={17} />
                </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto">
                {drawerMode === 'contents' ? (
                    <ContentsMode />
                ) : drawerMode === 'plan' ? (
                    <OrchestrationPlanPanel />
                ) : (
                    <DocumentsMode />
                )}
            </div>
        </aside>
    );
}
