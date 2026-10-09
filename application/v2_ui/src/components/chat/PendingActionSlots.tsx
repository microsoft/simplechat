// PendingActionSlots.tsx
// Where Microsoft 365 outgoing-action cards appear in the chat thread.
//
// A card sits under the reply that saved it, as it does in the classic interface. While that
// reply is still streaming it sits under the streaming bubble. A saved action whose message is
// not on screen falls into a conversation-level section, so a pending send is never hidden.
// A notification's deep link scrolls to its card and highlights it once.
//
// Placement is worked out once for the whole thread and handed to the bubbles through context,
// so a bubble re-renders only when one of its own cards moves, not every time a countdown ticks.

import {
    createContext,
    useContext,
    useEffect,
    useId,
    useMemo,
    useRef,
    useState,
    type ReactNode,
    type RefObject,
} from 'react';
import { clsx } from 'clsx';
import { Loader2, RefreshCw } from 'lucide-react';
import { bubbleWidthClass } from '../../lib/chatWidth';
import {
    lastMessageByRequestId,
    ORPHAN_ANCHOR,
    resolveAnchor,
    STREAMING_ANCHOR,
    type AnchorContext,
} from '../../lib/m365PendingActions';
import type { ChatMessage } from '../../lib/types';
import { useChatStore } from '../../stores/chatStore';
import { usePendingActions, usePendingActionsStoreApi } from '../../stores/m365PendingActionsStore';
import { useUiStore } from '../../stores/uiStore';
import { Notice } from '../approvals/ApprovalParts';
import { PendingActionCard } from '../approvals/PendingActionCard';
import { GlassButton, GlassPanel } from '../ui/primitives';

/** Card ids by the place they are drawn: a message id, the streaming slot, or the section. */
type Placement = ReadonlyMap<string, readonly string[]>;

const NO_PLACEMENT: Placement = new Map();
const NO_IDS: readonly string[] = [];
// These messages return before drawing a bubble body, so nothing can hang beneath them.
const UNANCHORABLE_ROLES: ReadonlySet<string> = new Set(['image', 'file', 'safety']);
const FOCUS_HIGHLIGHT_MS = 2500;
const UNAVAILABLE_MESSAGE =
    'That Microsoft 365 action is not available in this conversation. It may have been removed, or you may not have access to it.';

const PlacementContext = createContext<Placement>(NO_PLACEMENT);

function usePlacementIds(anchor: string): readonly string[] {
    return useContext(PlacementContext).get(anchor) ?? NO_IDS;
}

/**
 * Decide, for every card the store holds, which message it hangs under.
 *
 * Wrap the thread in this. It renders nothing itself; the placement it computes is read by
 * `InlinePendingActions` under each bubble and by the conversation-level section.
 */
export function PendingActionPlacementProvider({
    messages,
    children,
}: {
    messages: readonly ChatMessage[];
    children?: ReactNode;
}) {
    const entries = usePendingActions((state) => state.entries);
    const liveStream = usePendingActions((state) => state.liveStream);
    const conversationId = usePendingActions((state) => state.conversationId);

    const computed = useMemo(() => {
        const anchorable = messages.filter((message) => !UNANCHORABLE_ROLES.has(message.role));
        const context: AnchorContext = {
            visibleMessageIds: new Set(anchorable.map((message) => message.id)),
            lastMessageByRequestId: lastMessageByRequestId(anchorable),
            streamingUserMessageId:
                liveStream && liveStream.conversationId === conversationId ? liveStream.userMessageId : '',
        };
        const byAnchor = new Map<string, string[]>();
        for (const entry of Object.values(entries).sort((a, b) => a.order - b.order)) {
            const anchor = resolveAnchor(entry.reference, entry.action, context);
            const ids = byAnchor.get(anchor);
            if (ids) {
                ids.push(entry.id);
            } else {
                byAnchor.set(anchor, [entry.id]);
            }
        }
        return { byAnchor, signature: JSON.stringify(Array.from(byAnchor)) };
    }, [entries, liveStream, conversationId, messages]);

    // The entries object changes whenever any card ticks, but placement only changes when a card
    // moves. Keying the context value on the placement itself keeps a ticking countdown from
    // re-rendering every slot in the thread.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    const placement = useMemo(() => computed.byAnchor, [computed.signature]);

    return <PlacementContext.Provider value={placement}>{children}</PlacementContext.Provider>;
}

/** The cards that belong under one message, or under the streaming reply. */
export function InlinePendingActions({ anchor, className }: { anchor: string; className?: string }) {
    const ids = usePlacementIds(anchor);
    const chatWidth = useUiStore((state) => state.chatWidth);
    if (!ids.length) {
        return null;
    }
    return (
        <section
            aria-label="Microsoft 365 actions for this message"
            data-testid="v2-pending-action-slot"
            className={clsx('w-full space-y-2 self-start', className ?? 'mt-2', bubbleWidthClass(chatWidth))}
        >
            {ids.map((id) => (
                <PendingActionCard key={id} id={id} variant="inline" />
            ))}
        </section>
    );
}

/** Cards saved by a reply that is still streaming, drawn under the streaming bubble. */
export function StreamingPendingActions() {
    const ids = usePlacementIds(STREAMING_ANCHOR);
    if (!ids.length) {
        return null;
    }
    return (
        <div className="flex justify-start">
            <InlinePendingActions anchor={STREAMING_ANCHOR} className="" />
        </div>
    );
}

/** Read the conversation's saved actions when it opens, and again when the person returns to it. */
function usePendingActionsLifecycle(conversationId: string | null) {
    const api = usePendingActionsStoreApi();
    useEffect(() => {
        if (!conversationId) {
            return undefined;
        }
        const load = () => {
            void api.getState().loadList();
        };
        load();
        window.addEventListener('focus', load);
        window.addEventListener('online', load);
        return () => {
            window.removeEventListener('focus', load);
            window.removeEventListener('online', load);
        };
    }, [api, conversationId]);
}

interface Highlight {
    node: HTMLElement;
    timer: number;
}

function releaseHighlight(ref: { current: Highlight | null }) {
    const current = ref.current;
    if (!current) {
        return;
    }
    window.clearTimeout(current.timer);
    delete current.node.dataset.highlighted;
    ref.current = null;
}

/**
 * Bring a notification's card into view.
 *
 * The request waits for what it needs: the conversation's messages, the list of saved actions,
 * and the card to be drawn. Once the card is on screen it is scrolled to, highlighted for a
 * moment and focused, and the request is spent. If the card is not in the list it is fetched by
 * id; only when that also fails does the person hear that it is unavailable.
 */
function usePendingActionFocus(scrollRef: RefObject<HTMLElement>, pinnedRef: { current: boolean }) {
    const api = usePendingActionsStoreApi();
    const request = usePendingActions((state) => state.focusRequest);
    const conversationId = usePendingActions((state) => state.conversationId);
    const listStatus = usePendingActions((state) => state.listStatus);
    const referenceLoading = usePendingActions((state) => state.referenceLoading);
    const present = usePendingActions((state) => Boolean(state.focusRequest && state.entries[state.focusRequest.id]));
    const messagesLoading = useChatStore((state) => state.messagesLoading);
    // Read so the search for the card runs again after cards have been drawn into their slots.
    const placement = useContext(PlacementContext);
    const [unavailableFor, setUnavailableFor] = useState('');
    const lookedUp = useRef(0);
    const highlighted = useRef<Highlight | null>(null);

    useEffect(() => {
        if (!request || request.conversationId !== conversationId || messagesLoading) {
            return;
        }
        const root = scrollRef.current;
        if (!root) {
            return;
        }
        // Compared as data rather than interpolated into a selector, so no id can break out of one.
        const node = Array.from(root.querySelectorAll<HTMLElement>('[data-pending-action-id]')).find(
            (candidate) => candidate.dataset.pendingActionId === request.id,
        );

        if (node) {
            // Leave auto-scroll alone: it would otherwise pull the thread back to the bottom.
            pinnedRef.current = false;
            const rootBox = root.getBoundingClientRect();
            const nodeBox = node.getBoundingClientRect();
            const margin = Math.max(16, (root.clientHeight - nodeBox.height) / 2);
            const top = root.scrollTop + (nodeBox.top - rootBox.top) - margin;
            const reduced =
                typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            root.scrollTo({ top: Math.max(0, top), behavior: reduced ? 'auto' : 'smooth' });
            releaseHighlight(highlighted);
            node.dataset.highlighted = 'true';
            highlighted.current = {
                node,
                timer: window.setTimeout(() => releaseHighlight(highlighted), FOCUS_HIGHLIGHT_MS),
            };
            node.focus({ preventScroll: true });
            api.getState().clearFocus();
            return;
        }

        // The card is in the store but not drawn yet, or the lists it could appear in are still loading.
        if (present || listStatus === 'idle' || listStatus === 'loading' || referenceLoading) {
            return;
        }
        if (lookedUp.current === request.key) {
            return;
        }
        lookedUp.current = request.key;
        const { id, key } = request;
        void api
            .getState()
            .loadById(id)
            .then((action) => {
                const state = api.getState();
                if (action || state.focusRequest?.key !== key) {
                    return;
                }
                setUnavailableFor(state.conversationId);
                state.clearFocus();
            });
    }, [api, conversationId, listStatus, messagesLoading, pinnedRef, placement, present, referenceLoading, request, scrollRef]);

    // Only on unmount: clearing the focus request re-runs the effect above, which must not
    // cancel the highlight it just applied.
    useEffect(() => () => releaseHighlight(highlighted), []);

    return {
        unavailable: unavailableFor !== '' && unavailableFor === conversationId,
        dismissUnavailable: () => setUnavailableFor(''),
    };
}

/**
 * The part of the thread that belongs to the conversation rather than to one message: saved
 * actions whose message is not on screen, a failed or partial read of the list, and the notice
 * for a deep link whose card cannot be shown. It also owns loading the list and the deep-link
 * focus, since both depend on the cards having been drawn.
 */
export function PendingActionsConversationSection({
    scrollRef,
    pinnedRef,
}: {
    scrollRef: RefObject<HTMLElement>;
    pinnedRef: { current: boolean };
}) {
    const api = usePendingActionsStoreApi();
    const headingId = useId();
    const activeConversationId = useChatStore((state) => state.activeConversationId);
    const messagesLoading = useChatStore((state) => state.messagesLoading);
    const orphanIds = usePlacementIds(ORPHAN_ANCHOR);
    const listError = usePendingActions((state) => state.listError);
    const referenceError = usePendingActions((state) => state.referenceError);
    const continuationToken = usePendingActions((state) => state.continuationToken);
    const loadingMore = usePendingActions((state) => state.loadingMore);
    const listLoading = usePendingActions((state) => state.listStatus === 'loading');

    usePendingActionsLifecycle(activeConversationId);
    const { unavailable, dismissUnavailable } = usePendingActionFocus(scrollRef, pinnedRef);

    // Held back while history loads, so a card is not shown here for an instant and then jump
    // under its message.
    const showSection =
        !messagesLoading &&
        (orphanIds.length > 0 || Boolean(listError) || Boolean(referenceError) || Boolean(continuationToken));
    if (!unavailable && !showSection) {
        return null;
    }

    return (
        <>
            {unavailable && (
                <div
                    role="status"
                    data-testid="v2-pending-action-focus-unavailable"
                    className="flex items-start justify-between gap-3 rounded-xl bg-warn-soft px-3 py-2 text-sm text-text-1"
                >
                    <p className="min-w-0 break-words">{UNAVAILABLE_MESSAGE}</p>
                    <GlassButton variant="ghost" size="sm" onClick={dismissUnavailable}>
                        Dismiss
                    </GlassButton>
                </div>
            )}

            {showSection && (
                <GlassPanel
                    elevation="flat"
                    role="region"
                    aria-labelledby={headingId}
                    data-testid="v2-pending-actions-section"
                    className="space-y-3 p-4"
                >
                    <div className="space-y-1">
                        <h2 id={headingId} className="text-sm font-semibold text-text-1">
                            Microsoft 365 outgoing actions for this conversation
                        </h2>
                        <p className="text-xs text-text-2">
                            Saved actions without a visible originating message appear here. Opening a card never
                            sends it.
                        </p>
                    </div>

                    {listError && <Notice tone="danger" testId="v2-pending-actions-error">{listError}</Notice>}
                    {referenceError && (
                        <Notice tone="danger" testId="v2-pending-actions-reference-error">{referenceError}</Notice>
                    )}

                    {orphanIds.length > 0 && (
                        <div className="space-y-2">
                            {orphanIds.map((id) => (
                                <PendingActionCard key={id} id={id} variant="inline" />
                            ))}
                        </div>
                    )}

                    <div className="flex flex-wrap items-center gap-2">
                        {continuationToken && (
                            <GlassButton
                                variant="subtle"
                                size="sm"
                                disabled={loadingMore}
                                onClick={() => void api.getState().loadList({ more: true })}
                                data-testid="v2-pending-actions-more"
                            >
                                {loadingMore && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
                                Load more outgoing actions
                            </GlassButton>
                        )}
                        <GlassButton
                            variant="ghost"
                            size="sm"
                            disabled={listLoading}
                            onClick={() => void api.getState().refreshList()}
                            data-testid="v2-pending-actions-refresh"
                        >
                            <RefreshCw size={14} className={clsx(listLoading && 'animate-spin')} aria-hidden="true" />
                            Refresh outgoing actions
                        </GlassButton>
                    </div>
                </GlassPanel>
            )}
        </>
    );
}
