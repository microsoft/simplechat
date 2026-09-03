// ConversationRail.tsx
// The conversation list inside the left rail: search, infinite paging, and per-row
// pin / rename / hide / delete / export actions.
//
// It has two modes. Normally a row opens its conversation; in selection mode a row instead
// ticks a checkbox, so several conversations can be exported together. Selection mode is
// entered from the toolbar and leaves on its own once an export is started.

import { useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import {
    Download,
    Loader2,
    MoreHorizontal,
    Pin,
    Search,
    Trash2,
    EyeOff,
    LogOut,
    Pencil,
    Users,
    X,
} from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import { useCollaborationStore } from '../../stores/collaborationStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import { selectInFlightCount, useImageProposalStore } from '../../stores/imageProposalStore';
import { workspaceBadge, type WorkspaceBadgeTone } from '../../lib/conversationBadges';
import { canShareConversation, panelTargetForConversation } from '../../lib/sharing';
import { isCollaborative } from '../../lib/types';
import { Skeleton } from '../ui/primitives';
import { ConversationExportDialog } from './ConversationExportDialog';
import type { Conversation } from '../../lib/types';

/**
 * Tag colours, matching the badges shown beside an open conversation's title so the list
 * and the header describe a conversation the same way.
 */
const TAG_TONE: Record<WorkspaceBadgeTone, string> = {
    group: 'text-info',
    public: 'text-ok',
    shared: 'text-accent',
};

const TAG_TITLE: Record<WorkspaceBadgeTone, string> = {
    group: 'Working in a group workspace',
    public: 'Working in a public workspace',
    shared: 'Shared with other people',
};

/**
 * The workspace this conversation belongs to, shown under its title.
 *
 * Derived from the conversation the list already has: the feed returns the whole
 * conversation document, `chat_type` and `context` included, so no per-row request is
 * needed. A second line rather than an inline pill because the rail is narrow and group
 * names are long — inline, one of the two would always be truncated.
 */
function WorkspaceTag({ conversation }: { conversation: Conversation }) {
    const enabled = useUserSettingsStore(
        (state) => state.settings.showConversationWorkspaceTags !== false,
    );
    const badge = enabled ? workspaceBadge(conversation) : null;

    if (!badge) {
        return null;
    }

    return (
        <span
            title={TAG_TITLE[badge.tone]}
            className={clsx('block truncate text-[11px] leading-tight', TAG_TONE[badge.tone])}
        >
            {badge.label}
        </span>
    );
}

/**
 * How many images this conversation is still generating.
 *
 * Approving an image proposal is a background job in every sense that matters to the reader:
 * it keeps running after they leave the conversation, and it keeps running after they reload
 * the page. Without this the only report of it is on the cards themselves, which is no report
 * at all from anywhere else in the app — the complaint that motivated the whole change.
 */
function GeneratingImagesTag({ conversation }: { conversation: Conversation }) {
    const count = useImageProposalStore((state) => selectInFlightCount(state, conversation.id));

    if (count === 0) {
        return null;
    }

    const label = `Generating ${count} image${count === 1 ? '' : 's'}`;
    return (
        <span title={label} aria-label={label} className="flex shrink-0 items-center gap-1 text-accent">
            <Loader2 size={11} className="animate-spin" />
            {count > 1 && <span className="text-[11px] leading-none">{count}</span>}
        </span>
    );
}

function ConversationRow({
    conversation,
    onExport,
}: {
    conversation: Conversation;
    onExport: (conversationId: string) => void;
}) {
    const {
        activeConversationId,
        selectConversation,
        removeConversation,
        renameConversation,
        togglePinned,
        toggleHidden,
        selectionMode,
        selectedConversationIds,
        toggleConversationSelected,
    } = useChatStore();

    const [menuOpen, setMenuOpen] = useState(false);
    const [renaming, setRenaming] = useState(false);
    const [draftTitle, setDraftTitle] = useState(conversation.title);
    const openPanel = useCollaborationStore((state) => state.openPanel);
    const collaborationEnabled = useBootstrapStore((state) =>
        Boolean(state.data?.features?.enable_collaborative_conversations),
    );

    const isActive = conversation.id === activeConversationId;
    const isSelected = selectedConversationIds.includes(conversation.id);
    const shareable = collaborationEnabled && canShareConversation(conversation);
    const shared = isCollaborative(conversation);

    const commitRename = () => {
        const trimmed = draftTitle.trim();
        if (trimmed && trimmed !== conversation.title) {
            void renameConversation(conversation.id, trimmed);
        } else {
            setDraftTitle(conversation.title);
        }
        setRenaming(false);
    };

    if (renaming) {
        return (
            <li>
                <input
                    autoFocus
                    value={draftTitle}
                    onChange={(event) => setDraftTitle(event.target.value)}
                    onBlur={commitRename}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                            commitRename();
                        }
                        if (event.key === 'Escape') {
                            setDraftTitle(conversation.title);
                            setRenaming(false);
                        }
                    }}
                    className="w-full rounded-lg border border-accent bg-surface-solid px-2.5 py-2 text-sm text-text-1 outline-none"
                    aria-label="Conversation title"
                />
            </li>
        );
    }

    if (selectionMode) {
        return (
            <li>
                <label
                    className={clsx(
                        'flex w-full cursor-pointer items-center gap-2.5 rounded-lg py-2 pr-2 pl-2.5 transition-colors',
                        isSelected
                            ? 'bg-accent-soft text-accent'
                            : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
                    )}
                >
                    <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleConversationSelected(conversation.id)}
                        className="h-4 w-4 shrink-0 accent-[var(--accent)]"
                    />
                    {conversation.is_pinned && (
                        <Pin size={12} className="shrink-0 fill-current opacity-70" />
                    )}
                    <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm">
                            {conversation.title || 'Untitled conversation'}
                        </span>
                        <WorkspaceTag conversation={conversation} />
                    </span>
                </label>
            </li>
        );
    }

    return (
        <li className="group/row relative">
            <button
                type="button"
                onClick={() => void selectConversation(conversation.id)}
                className={clsx(
                    'flex w-full items-center gap-2 rounded-lg py-2 pr-8 pl-2.5 text-left transition-colors',
                    isActive
                        ? 'bg-accent-soft text-accent'
                        : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
                )}
            >
                {conversation.is_pinned && (
                    <Pin size={12} className="shrink-0 fill-current opacity-70" />
                )}
                <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">
                        {conversation.title || 'Untitled conversation'}
                    </span>
                    <WorkspaceTag conversation={conversation} />
                </span>
                {conversation.has_unread_assistant_response && (
                    <span
                        aria-label="Unread"
                        className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent"
                    />
                )}
                <GeneratingImagesTag conversation={conversation} />
            </button>

            <button
                type="button"
                aria-label={`Actions for ${conversation.title || 'conversation'}`}
                onClick={() => setMenuOpen((open) => !open)}
                className={clsx(
                    'absolute top-1.5 right-1 rounded-md p-1 text-text-3 transition-opacity',
                    'hover:bg-surface-3 hover:text-text-1 focus-visible:opacity-100',
                    menuOpen ? 'opacity-100' : 'opacity-0 group-hover/row:opacity-100',
                )}
            >
                <MoreHorizontal size={14} />
            </button>

            {menuOpen && (
                <>
                    {/* Click-away layer; keeps the menu dismissible without a global listener. */}
                    <div
                        className="fixed inset-0 z-40"
                        aria-hidden="true"
                        onClick={() => setMenuOpen(false)}
                    />
                    <div className="glass-modal absolute top-8 right-1 z-50 w-44 rounded-xl p-1">
                        <button
                            type="button"
                            onClick={() => {
                                setMenuOpen(false);
                                setRenaming(true);
                            }}
                            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm text-text-1 hover:bg-surface-2"
                        >
                            <Pencil size={14} /> Rename
                        </button>
                        {shareable && (
                            <button
                                type="button"
                                onClick={() => {
                                    setMenuOpen(false);
                                    // The panel loads its own copy of the membership into its
                                    // own slot. Loading it here as well would write the
                                    // conversation on screen's slot with a different
                                    // conversation's document.
                                    openPanel(
                                        panelTargetForConversation(conversation.id, conversation),
                                    );
                                }}
                                className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm text-text-1 hover:bg-surface-2"
                            >
                                <Users size={14} /> {shared ? 'People' : 'Share'}
                            </button>
                        )}
                        <button
                            type="button"
                            onClick={() => {
                                setMenuOpen(false);
                                void togglePinned(conversation.id);
                            }}
                            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm text-text-1 hover:bg-surface-2"
                        >
                            <Pin size={14} /> {conversation.is_pinned ? 'Unpin' : 'Pin'}
                        </button>
                        <button
                            type="button"
                            onClick={() => {
                                setMenuOpen(false);
                                void toggleHidden(conversation.id);
                            }}
                            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm text-text-1 hover:bg-surface-2"
                        >
                            <EyeOff size={14} /> Hide
                        </button>
                        <button
                            type="button"
                            onClick={() => {
                                setMenuOpen(false);
                                onExport(conversation.id);
                            }}
                            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm text-text-1 hover:bg-surface-2"
                        >
                            <Download size={14} /> Export
                        </button>
                        <button
                            type="button"
                            onClick={() => {
                                setMenuOpen(false);
                                void removeConversation(conversation.id);
                            }}
                            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm text-danger hover:bg-danger-soft"
                        >
                            {/* Named for what it will actually do. Only an owner can destroy
                                a shared conversation for everybody; anybody else leaves it,
                                and the thread carries on without them. */}
                            {shared && !conversation.can_delete_conversation ? (
                                <>
                                    <LogOut size={14} /> Leave
                                </>
                            ) : (
                                <>
                                    <Trash2 size={14} /> Delete
                                </>
                            )}
                        </button>
                    </div>
                </>
            )}
        </li>
    );
}

export function ConversationRail() {
    const {
        conversations,
        conversationsLoading,
        conversationsError,
        hasMore,
        searchTerm,
        setSearchTerm,
        loadConversations,
        loadMore,
        selectionMode,
        selectedConversationIds,
        setSelectionMode,
        selectAllConversations,
        clearConversationSelection,
    } = useChatStore();

    const sentinelRef = useRef<HTMLDivElement>(null);

    /**
     * The export in flight, or null.
     *
     * `skipSelection` records how it was started: from one conversation's own menu there is
     * nothing to review, so the wizard opens on the format choice instead.
     */
    const [exportRequest, setExportRequest] = useState<{
        ids: string[];
        skipSelection: boolean;
    } | null>(null);

    const allSelected =
        conversations.length > 0 && selectedConversationIds.length === conversations.length;

    useEffect(() => {
        void loadConversations({ reset: true });
        // Intentionally runs once: subsequent reloads are driven by search and mutations.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Paging is driven by an IntersectionObserver rather than a scroll handler so it does
    // not fire on every scroll frame.
    useEffect(() => {
        const sentinel = sentinelRef.current;
        if (!sentinel || !hasMore) {
            return;
        }

        const observer = new IntersectionObserver(
            (entries) => {
                if (entries[0]?.isIntersecting) {
                    void loadMore();
                }
            },
            { rootMargin: '120px' },
        );

        observer.observe(sentinel);
        return () => observer.disconnect();
    }, [hasMore, loadMore]);

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="px-3 pb-2">
                <div className="relative">
                    <Search
                        size={14}
                        className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-3"
                    />
                    <input
                        type="search"
                        value={searchTerm}
                        onChange={(event) => setSearchTerm(event.target.value)}
                        placeholder="Search chats"
                        aria-label="Search conversations"
                        className={clsx(
                            'w-full rounded-lg border border-edge bg-surface-sunken py-1.5 pr-2.5 pl-8',
                            'text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none',
                        )}
                    />
                </div>

                {selectionMode ? (
                    <div className="mt-2 flex items-center gap-1.5">
                        <span className="text-xs font-medium text-text-2">
                            {selectedConversationIds.length} selected
                        </span>
                        <button
                            type="button"
                            onClick={() =>
                                allSelected ? clearConversationSelection() : selectAllConversations()
                            }
                            className="rounded-md px-1.5 py-0.5 text-xs text-accent hover:bg-surface-2"
                        >
                            {allSelected ? 'Clear' : 'All'}
                        </button>
                        <button
                            type="button"
                            disabled={selectedConversationIds.length === 0}
                            onClick={() =>
                                setExportRequest({
                                    ids: [...selectedConversationIds],
                                    skipSelection: false,
                                })
                            }
                            className="ml-auto inline-flex items-center gap-1 rounded-md bg-accent px-2 py-1 text-xs font-medium text-on-accent transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            <Download size={12} /> Export
                        </button>
                        <button
                            type="button"
                            onClick={() => setSelectionMode(false)}
                            aria-label="Leave selection mode"
                            className="rounded-md p-1 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                        >
                            <X size={13} />
                        </button>
                    </div>
                ) : (
                    conversations.length > 0 && (
                        <div className="mt-2 flex justify-end">
                            <button
                                type="button"
                                onClick={() => setSelectionMode(true)}
                                className="rounded-md px-1.5 py-0.5 text-xs text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                            >
                                Select
                            </button>
                        </div>
                    )
                )}
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-2">
                {conversationsError && (
                    <p className="px-1 py-2 text-xs text-danger">{conversationsError}</p>
                )}

                {conversations.length === 0 && conversationsLoading && (
                    <div className="space-y-1.5 py-1">
                        {Array.from({ length: 6 }).map((_, index) => (
                            <Skeleton key={index} className="h-8 w-full" />
                        ))}
                    </div>
                )}

                {conversations.length === 0 && !conversationsLoading && !conversationsError && (
                    <p className="px-1 py-6 text-center text-xs text-text-3">
                        {searchTerm ? 'No conversations match.' : 'No conversations yet.'}
                    </p>
                )}

                <ul className="space-y-0.5">
                    {conversations.map((conversation) => (
                        <ConversationRow
                            key={conversation.id}
                            conversation={conversation}
                            onExport={(id) =>
                                setExportRequest({ ids: [id], skipSelection: true })
                            }
                        />
                    ))}
                </ul>

                <div ref={sentinelRef} className="h-1" />

                {conversationsLoading && conversations.length > 0 && (
                    <p className="py-2 text-center text-xs text-text-3">Loading…</p>
                )}
            </div>

            {exportRequest && (
                <ConversationExportDialog
                    conversationIds={exportRequest.ids}
                    skipSelection={exportRequest.skipSelection}
                    onClose={() => {
                        setExportRequest(null);
                        // Selection has served its purpose; leaving it ticked would make the
                        // next click ambiguous about whether it opens or adds to a selection.
                        setSelectionMode(false);
                    }}
                />
            )}
        </div>
    );
}
