// ConversationDrawer.tsx
// Right-hand drawer with three modes, mirroring the legacy offcanvas that hosts both a
// table of contents and the documents used in the conversation, plus the orchestration plan.
//
// Contents lists the user's turns so a long thread can be navigated; Documents lists the
// document-level citation aggregates the server records on the conversation, and the owner's
// SharePoint, OneDrive, email and calendar items with links that open them online; Plan hosts the
// orchestration plan surface when the feature is on.

import { useEffect, useMemo } from 'react';
import { clsx } from 'clsx';
import {
    CalendarDays,
    FileText,
    Files,
    ListOrdered,
    ListTree,
    Mail,
    Quote,
    TriangleAlert,
    X,
} from 'lucide-react';
import { useChatStore, type DrawerMode } from '../../stores/chatStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { collectConversationMedia } from '../../lib/conversationMedia';
import { m365SecondaryLine, readUsedM365Items } from '../../lib/m365Citations';
import { EmptyState, Skeleton } from '../ui/primitives';
import {
    GeneratedDocumentsSection,
    MediaSection,
    SectionHeading,
    useGeneratedDocuments,
} from './DrawerAssets';
import { M365KindIcon, M365OpenLink } from './M365CitationChip';
import { OrchestrationPlanPanel } from './OrchestrationPlanPanel';
import type { UsedDocument, UsedM365Item } from '../../lib/types';

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

/**
 * One Microsoft 365 item the conversation used, with a link that opens it where it lives.
 *
 * There is no download here: the item stays in SharePoint, OneDrive or Outlook, and opening it
 * there uses the reader's own sign-in, so they see exactly what their access allows.
 */
function M365ItemRow({ item }: { item: UsedM365Item }) {
    const title = (item.kind === 'file' && item.file_name) || item.title;
    const secondary = m365SecondaryLine(item);

    return (
        <li className="glass-flat rounded-xl p-3" data-m365-citation-id={item.citation_id}>
            <div className="flex items-start gap-2.5">
                <M365KindIcon kind={item.kind} size={16} className="mt-0.5 shrink-0 text-text-3" />
                <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-text-1" title={title}>
                        {title}
                    </p>
                    {secondary && (
                        <p className="mt-0.5 truncate text-xs text-text-3" title={secondary}>
                            {secondary}
                        </p>
                    )}
                    {(item.cited || item.content_read) && (
                        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-3">
                            {item.cited ? (
                                <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-1.5 py-0.5 text-accent">
                                    <Quote size={10} />
                                    Cited
                                </span>
                            ) : (
                                <span>Read while answering</span>
                            )}
                        </div>
                    )}
                </div>
                <M365OpenLink
                    record={item}
                    label="Open online"
                    className="inline-flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-accent transition-colors hover:bg-surface-2"
                />
            </div>
        </li>
    );
}

function M365Section({
    label,
    icon: Icon,
    items,
}: {
    label: string;
    icon: typeof Files;
    items: UsedM365Item[];
}) {
    return (
        <section aria-label={label}>
            <SectionHeading>
                <span className="inline-flex items-center gap-1.5">
                    <Icon size={11} aria-hidden="true" />
                    {label}
                </span>
            </SectionHeading>
            <ul className="space-y-2">
                {items.map((item) => (
                    <M365ItemRow key={item.citation_id} item={item} />
                ))}
            </ul>
        </section>
    );
}

function DocumentsMode() {
    const { metadata, metadataLoading, metadataError, activeConversationId, loadMetadata } =
        useChatStore();
    const collaborative = useChatStore((state) => state.activeConversationKind === 'collaborative');
    const messages = useChatStore((state) => state.messages);
    const media = useMemo(() => collectConversationMedia(messages), [messages]);
    const generated = useGeneratedDocuments(activeConversationId, collaborative);

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
    // Microsoft 365 items are listed only to their owner; the server sends no others.
    const m365 = useMemo(() => readUsedM365Items(metadata), [metadata]);

    const hasAssets = generated.documents.length > 0 || Boolean(generated.error) || media.length > 0;
    const assets = hasAssets && activeConversationId ? (
        <>
            <GeneratedDocumentsSection
                conversationId={activeConversationId}
                documents={generated.documents}
                error={generated.error}
            />
            <MediaSection items={media} onLocate={scrollToMessage} />
        </>
    ) : null;

    if (metadataLoading && !metadata) {
        return (
            <div className="space-y-4 p-3">
                {assets}
                <div className="space-y-2">
                    {Array.from({ length: 3 }).map((_, index) => (
                        <Skeleton key={index} className="h-16 w-full" />
                    ))}
                </div>
            </div>
        );
    }

    if (metadataError) {
        return (
            <div className="space-y-4 p-3">
                {assets}
                <div className="flex items-start gap-2 text-sm text-danger">
                    <TriangleAlert size={16} className="mt-0.5 shrink-0" />
                    {metadataError}
                </div>
            </div>
        );
    }

    if (documents.length === 0 && m365.total === 0 && !assets) {
        return (
            <EmptyState
                icon={<Files size={24} />}
                title="No documents used yet"
                description="Documents referenced while answering will be listed here."
            />
        );
    }

    return (
        <div className="space-y-4 p-3">
            {assets}
            {documents.length > 0 && (
                <section aria-label="Used in answers">
                    {(assets || m365.total > 0) && <SectionHeading>Used in answers</SectionHeading>}
                    <ul className="space-y-2">
                        {documents.map((document) => (
                            <DocumentRow key={document.document_id} document={document} />
                        ))}
                    </ul>
                </section>
            )}
            {m365.files.length > 0 && (
                <M365Section label="SharePoint & OneDrive" icon={Files} items={m365.files} />
            )}
            {m365.emails.length > 0 && <M365Section label="Email" icon={Mail} items={m365.emails} />}
            {m365.events.length > 0 && (
                <M365Section label="Calendar" icon={CalendarDays} items={m365.events} />
            )}
        </div>
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

    // Close on Escape, matching the dismissal behaviour of the rest of the app. A dialog opened
    // from the drawer, such as the media viewer or a document preview, takes that Escape itself.
    useEffect(() => {
        if (!drawerMode) {
            return;
        }
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape' && !document.querySelector('[role="dialog"][aria-modal="true"]')) {
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
            className="glass glass-edge absolute inset-y-0 right-0 z-30 flex w-[22rem] max-w-full shrink-0 flex-col rounded-none border-t-0 border-r-0 border-b-0 xl:static xl:z-auto"
        >
            <div className="flex min-h-14 shrink-0 flex-wrap items-center gap-2 border-b border-edge px-3 py-2">
                <div
                    role="tablist"
                    aria-label="Drawer mode"
                    className="flex min-w-0 flex-wrap gap-1 rounded-xl bg-surface-sunken p-1"
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
