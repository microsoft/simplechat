// ConversationRail.tsx
// The conversation list inside the left rail: search, infinite paging, and per-row
// pin / rename / hide / delete actions.

import { useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { MoreHorizontal, Pin, Search, Trash2, EyeOff, Pencil } from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import { workspaceBadge, type WorkspaceBadgeTone } from '../../lib/conversationBadges';
import { Skeleton } from '../ui/primitives';
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

function ConversationRow({ conversation }: { conversation: Conversation }) {
    const {
        activeConversationId,
        selectConversation,
        removeConversation,
        renameConversation,
        togglePinned,
        toggleHidden,
    } = useChatStore();

    const [menuOpen, setMenuOpen] = useState(false);
    const [renaming, setRenaming] = useState(false);
    const [draftTitle, setDraftTitle] = useState(conversation.title);

    const isActive = conversation.id === activeConversationId;

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
                                void removeConversation(conversation.id);
                            }}
                            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm text-danger hover:bg-danger-soft"
                        >
                            <Trash2 size={14} /> Delete
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
    } = useChatStore();

    const sentinelRef = useRef<HTMLDivElement>(null);

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
                        <ConversationRow key={conversation.id} conversation={conversation} />
                    ))}
                </ul>

                <div ref={sentinelRef} className="h-1" />

                {conversationsLoading && conversations.length > 0 && (
                    <p className="py-2 text-center text-xs text-text-3">Loading…</p>
                )}
            </div>
        </div>
    );
}
