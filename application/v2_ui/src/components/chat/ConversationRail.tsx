// ConversationRail.tsx
// The conversation list inside the left rail: search, infinite paging, per-row
// pin / rename / hide / delete / export actions, and multi-select for acting on several
// conversations at once.
//
// Selection is hover-revealed rather than moded. Each row reserves a narrow left gutter
// that holds its pin marker at rest and a checkbox once the pointer is over it, so picking
// several conversations costs no permanent chrome and the list never changes shape. A plain
// click still opens a conversation — Ctrl/Cmd+click toggles a row and Shift+click extends a
// range, matching the workspace documents explorer, which shares the same selection algebra.
//
// The bulk bar appears only while something is selected, in the slot the old "Select" button
// used to occupy permanently.

import { useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import {
    Download,
    EyeOff,
    Loader2,
    LogOut,
    MoreHorizontal,
    Pencil,
    Pin,
    PinOff,
    Search,
    Trash2,
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
import { isEverythingSelected, selectionIntentFromEvent } from '../../lib/listSelection';
import {
    pinActionFor,
    removalActionFor,
    removalConfirmLabel,
    removalDescription,
    removalTitle,
    selectedConversations,
    summarizeRemoval,
} from '../../lib/conversationSelection';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { Skeleton } from '../ui/primitives';
import { ConversationExportDialog } from './ConversationExportDialog';
import type { ReactNode } from 'react';
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

/**
 * The row's left gutter: pin marker at rest, checkbox when picking.
 *
 * Width is reserved unconditionally. Revealing a checkbox on hover is only pleasant if
 * nothing moves when it appears, and a gutter that collapsed when a row was unpinned would
 * make the whole list jitter as the pointer travelled down it. Pinned rows pay nothing for
 * this, because the pin already stood there.
 *
 * `pointer-coarse:opacity-100` is the touch fallback: with no pointer to hover there is no
 * other way to reach the checkbox, so on those devices it is simply always visible.
 */
function SelectionGutter({
    conversation,
    showCheckbox,
    selected,
    onSelect,
}: {
    conversation: Conversation;
    /** Whether the checkbox is shown persistently rather than only on hover. */
    showCheckbox: boolean;
    selected: boolean;
    onSelect: (event: { shiftKey?: boolean; ctrlKey?: boolean; metaKey?: boolean }) => void;
}) {
    return (
        <span className="relative flex h-4 w-4 shrink-0 items-center justify-center">
            {conversation.is_pinned && !showCheckbox && (
                <Pin
                    size={12}
                    aria-hidden="true"
                    className="fill-current opacity-70 transition-opacity group-hover/row:opacity-0"
                />
            )}
            <input
                type="checkbox"
                checked={selected}
                // Kept mounted rather than conditionally rendered even while invisible, so
                // it stays in the tab order and a keyboard user can reach it at all.
                onClick={(event) => event.stopPropagation()}
                onChange={(event) => onSelect(event.nativeEvent as MouseEvent)}
                aria-label={`Select ${conversation.title || 'Untitled conversation'}`}
                className={clsx(
                    'absolute inset-0 h-4 w-4 cursor-pointer accent-[var(--accent)]',
                    !showCheckbox &&
                        'opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100',
                )}
            />
        </span>
    );
}

function ConversationRow({
    conversation,
    selected,
    anySelected,
    onExport,
    onRequestDelete,
}: {
    conversation: Conversation;
    selected: boolean;
    anySelected: boolean;
    onExport: (conversationId: string) => void;
    onRequestDelete: (conversation: Conversation) => void;
}) {
    const {
        activeConversationId,
        selectConversation,
        renameConversation,
        togglePinned,
        toggleHidden,
        applyConversationSelection,
        clearConversationSelection,
    } = useChatStore();

    const [menuOpen, setMenuOpen] = useState(false);
    const [renaming, setRenaming] = useState(false);
    const [draftTitle, setDraftTitle] = useState(conversation.title);
    const openPanel = useCollaborationStore((state) => state.openPanel);
    const collaborationEnabled = useBootstrapStore((state) =>
        Boolean(state.data?.features?.enable_collaborative_conversations),
    );

    const isActive = conversation.id === activeConversationId;
    const shareable = collaborationEnabled && canShareConversation(conversation);
    const shared = isCollaborative(conversation);
    // Once anything is picked, every row shows its box. That is what makes the state
    // legible — and it matters more here than in a table, because a plain click clears the
    // selection, so the user has to be able to see there is one to lose.
    const showCheckbox = selected || anySelected;

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
            <div
                className={clsx(
                    'flex w-full items-center gap-2 rounded-lg py-2 pr-8 pl-2.5 transition-colors',
                    selected || isActive
                        ? 'bg-accent-soft text-accent'
                        : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
                )}
            >
                <SelectionGutter
                    conversation={conversation}
                    selected={selected}
                    showCheckbox={showCheckbox}
                    onSelect={(event) =>
                        // A modifier held while ticking a box means the same as one held
                        // while clicking the row, so Shift+box still extends a range.
                        applyConversationSelection(
                            conversation.id,
                            event.shiftKey ? 'range' : 'toggle',
                        )
                    }
                />

                <button
                    type="button"
                    onClick={(event) => {
                        const intent = selectionIntentFromEvent(event);
                        if (intent !== 'replace') {
                            // Ctrl/Cmd and Shift are selection gestures, never navigation.
                            event.preventDefault();
                            applyConversationSelection(conversation.id, intent);
                            return;
                        }
                        // An unmodified click always opens. Keeping that invariant is why
                        // the selection is dropped here rather than added to: a rail whose
                        // primary action changes with invisible state is worse than one that
                        // occasionally loses a selection the user can see.
                        clearConversationSelection();
                        void selectConversation(conversation.id);
                    }}
                    className="flex min-w-0 flex-1 items-center gap-2 text-left"
                >
                    {/* The gutter is holding a checkbox, so a pinned row would otherwise
                        lose the only sign that it is pinned — exactly while the user is
                        deciding whether the bulk button should pin or unpin. */}
                    {conversation.is_pinned && showCheckbox && (
                        <Pin
                            size={11}
                            aria-label="Pinned"
                            className="shrink-0 fill-current opacity-60"
                        />
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
            </div>

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
                                onRequestDelete(conversation);
                            }}
                            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm text-danger hover:bg-danger-soft"
                        >
                            {/* Named for what it will actually do, through the same helper
                                the confirmation and the request use. Only an owner can
                                destroy a shared conversation for everybody; anybody else
                                leaves it, and the thread carries on without them. */}
                            {removalActionFor(conversation) === 'leave' ? (
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

/** One icon button in the bulk bar. Icon-only because labels wrap at this width. */
function BulkAction({
    label,
    onClick,
    danger = false,
    children,
}: {
    label: string;
    onClick: () => void;
    danger?: boolean;
    children: ReactNode;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            title={label}
            aria-label={label}
            className={clsx(
                'rounded-md p-1 transition-colors',
                danger
                    ? 'text-danger hover:bg-danger-soft'
                    : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
            )}
        >
            {children}
        </button>
    );
}

export function ConversationRail() {
    const {
        conversations,
        conversationsLoading,
        conversationsError,
        hasMore,
        searchTerm,
        selectedConversationIds,
        setSearchTerm,
        loadConversations,
        loadMore,
        selectAllConversations,
        clearConversationSelection,
        bulkRemoveConversations,
        bulkSetConversationsPinned,
        bulkHideSelectedConversations,
        removeConversation,
    } = useChatStore();

    const sentinelRef = useRef<HTMLDivElement>(null);
    const selectAllRef = useRef<HTMLInputElement>(null);

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

    /**
     * The removal awaiting confirmation, or null.
     *
     * Holds the conversations rather than their ids, because the dialog has to describe what
     * will happen to each — and a shared conversation the user can only step out of must not
     * be described as being deleted.
     */
    const [pendingRemoval, setPendingRemoval] = useState<{
        conversations: Conversation[];
        bulk: boolean;
    } | null>(null);
    const [removing, setRemoving] = useState(false);

    const selectedIdSet = useMemo(
        () => new Set(selectedConversationIds),
        [selectedConversationIds],
    );
    const selectedCount = selectedConversationIds.length;
    const anySelected = selectedCount > 0;

    const orderedIds = useMemo(
        () => conversations.map((conversation) => conversation.id),
        [conversations],
    );
    const allSelected = isEverythingSelected(selectedConversationIds, orderedIds);
    const someSelected = anySelected && !allSelected;

    const selection = useMemo(
        () => selectedConversations(conversations, selectedConversationIds),
        [conversations, selectedConversationIds],
    );
    // Unpin only when every selected conversation is already pinned; any other mix means the
    // user is pinning the ones that are not.
    const pinAction = pinActionFor(selection);

    useEffect(() => {
        if (selectAllRef.current) {
            // The indeterminate state is not expressible as an attribute, so it has to be
            // written to the node. Without it a partial selection reads as "none selected".
            selectAllRef.current.indeterminate = someSelected;
        }
    }, [someSelected]);

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

    const confirmRemoval = () => {
        if (!pendingRemoval) {
            return;
        }
        const { conversations: targets, bulk } = pendingRemoval;
        setRemoving(true);
        // The single removal is told which of delete-or-leave the dialog just promised,
        // rather than letting the store decide a second time from a copy of the permissions
        // that may have been refreshed since.
        const work = bulk
            ? bulkRemoveConversations()
            : removeConversation(targets[0].id, removalActionFor(targets[0]));
        void work.finally(() => {
            setRemoving(false);
            setPendingRemoval(null);
        });
    };

    const removalSummary = pendingRemoval
        ? summarizeRemoval(pendingRemoval.conversations)
        : null;

    return (
        <div
            className="flex h-full min-h-0 flex-col"
            onKeyDown={(event) => {
                // A dialog opened from the rail portals out of it, but focus stays on the
                // control that opened it — so without this guard, Escape would dismiss the
                // dialog *and* clear the selection behind it, losing what the user was
                // cancelling out of.
                if (exportRequest || pendingRemoval) {
                    return;
                }
                if (event.key === 'Escape' && anySelected) {
                    clearConversationSelection();
                    return;
                }
                // Scoped to the rail rather than the window, so it never takes select-all
                // away from the composer. Text inputs keep it for their own contents; a
                // checkbox has no text to select, so the rail may claim it there.
                const target = event.target;
                const typing =
                    target instanceof HTMLInputElement && target.type !== 'checkbox';
                if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a' && !typing) {
                    event.preventDefault();
                    selectAllConversations();
                }
            }}
        >
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

                {/* Only drawn while something is picked. At rest the rail is a line shorter
                    than it was when a permanent "Select" button lived here. */}
                {anySelected && (
                    <div className="mt-2 flex items-center gap-1 pl-2.5">
                        <input
                            ref={selectAllRef}
                            type="checkbox"
                            checked={allSelected}
                            onChange={() =>
                                allSelected
                                    ? clearConversationSelection()
                                    : selectAllConversations()
                            }
                            aria-label="Select all loaded conversations"
                            // Sits in the same column as the row checkboxes below it, so it
                            // reads as their header rather than as another action.
                            className="h-4 w-4 shrink-0 cursor-pointer accent-[var(--accent)]"
                        />
                        <span className="ml-1 truncate text-xs font-medium text-text-2">
                            {selectedCount} selected
                        </span>

                        <span className="ml-auto flex items-center gap-0.5">
                            <BulkAction
                                label={pinAction === 'unpin' ? 'Unpin' : 'Pin'}
                                onClick={() => void bulkSetConversationsPinned(pinAction)}
                            >
                                {pinAction === 'unpin' ? <PinOff size={14} /> : <Pin size={14} />}
                            </BulkAction>
                            <BulkAction
                                label="Hide"
                                onClick={() => void bulkHideSelectedConversations()}
                            >
                                <EyeOff size={14} />
                            </BulkAction>
                            <BulkAction
                                label="Export"
                                onClick={() =>
                                    setExportRequest({
                                        ids: [...selectedConversationIds],
                                        skipSelection: false,
                                    })
                                }
                            >
                                <Download size={14} />
                            </BulkAction>

                            {/* Separated so the irreversible action is not adjacent to the
                                reversible ones under a fast pointer. */}
                            <span className="mx-0.5 h-4 w-px bg-edge" aria-hidden="true" />
                            <BulkAction
                                label="Delete"
                                danger
                                onClick={() =>
                                    setPendingRemoval({ conversations: selection, bulk: true })
                                }
                            >
                                <Trash2 size={14} />
                            </BulkAction>
                            <BulkAction
                                label="Clear selection"
                                onClick={clearConversationSelection}
                            >
                                <X size={14} />
                            </BulkAction>
                        </span>
                    </div>
                )}

                {/* Announced rather than only drawn, so the count reaches a screen reader
                    that is not looking at the bar. */}
                <span aria-live="polite" className="sr-only">
                    {anySelected ? `${selectedCount} conversations selected` : ''}
                </span>
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
                            selected={selectedIdSet.has(conversation.id)}
                            anySelected={anySelected}
                            onExport={(id) => setExportRequest({ ids: [id], skipSelection: true })}
                            onRequestDelete={(target) =>
                                setPendingRemoval({ conversations: [target], bulk: false })
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
                        clearConversationSelection();
                    }}
                />
            )}

            {pendingRemoval && removalSummary && (
                <ConfirmDialog
                    title={removalTitle(removalSummary)}
                    description={removalDescription(removalSummary)}
                    confirmLabel={removalConfirmLabel(removalSummary)}
                    confirmIcon={
                        removalSummary.deleteCount === 0 ? (
                            <LogOut size={14} />
                        ) : (
                            <Trash2 size={14} />
                        )
                    }
                    busy={removing}
                    onConfirm={confirmRemoval}
                    onClose={() => setPendingRemoval(null)}
                >
                    <p className="text-xs text-text-2">
                        {removalSummary.deleteCount > 0
                            ? 'Deleted conversations and their messages cannot be recovered.'
                            : 'You can be invited back, but you will not see what was said while you were away.'}
                    </p>
                </ConfirmDialog>
            )}
        </div>
    );
}
