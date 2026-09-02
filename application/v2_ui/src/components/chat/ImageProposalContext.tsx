// ImageProposalContext.tsx
// Connects `simpleimage` cards to the assistant message they were written in.
//
// A card is rendered from deep inside `AssistantMarkdown`, several layers below the message
// bubble, and it needs three things the markdown renderer has no business knowing about: the
// id of the message that proposed it, the images already generated for that message, and a
// way to take part in "Approve all". Threading those down as props would put image generation
// concerns into the signature of every markdown caller, so they travel by context instead.
//
// The provider also owns the Approve all control. Keeping it here rather than in MessageBubble
// means the count of pending cards, the button that acts on them, and the cards themselves all
// live in one place, and the button lands immediately after the message text — the same
// position the classic client appends it to.

import {
    createContext,
    useCallback,
    useContext,
    useMemo,
    useRef,
    useState,
    type ReactNode,
} from 'react';
import { Images } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import type { ChatMessage } from '../../lib/types';

/**
 * Pending cards needed before the bulk control is worth showing.
 *
 * Matches `refreshImageProposalBulkActions` in the classic client: with one or two cards the
 * individual Approve buttons are right there, and a third button that does the same thing is
 * just clutter.
 */
export const APPROVE_ALL_THRESHOLD = 2;

interface ImageProposalContextValue {
    /** Empty while the response is still streaming, because the message is not stored yet. */
    assistantMessageId: string;
    /** Images already generated from this message's proposals. */
    results: ChatMessage[];
    /** Bumped when the user asks for every pending card in this message to be approved. */
    approveAllToken: number;
    /** Cards report whether they are still awaiting a decision. */
    setPending: (cardId: string, pending: boolean) => void;
}

const EMPTY_RESULTS: ChatMessage[] = [];

const ImageProposalContext = createContext<ImageProposalContextValue>({
    assistantMessageId: '',
    results: EMPTY_RESULTS,
    approveAllToken: 0,
    setPending: () => {},
});

export function useImageProposalScope(): ImageProposalContextValue {
    return useContext(ImageProposalContext);
}

/**
 * Scope for every image proposal card in one assistant message.
 *
 * Rendered around the message's markdown. Messages with no proposals cost one context value
 * and nothing else, so this does not need to be conditional on the content.
 */
export function ImageProposalScope({
    assistantMessageId,
    results,
    children,
}: {
    assistantMessageId: string;
    results?: ChatMessage[];
    children: ReactNode;
}) {
    const [pendingIds, setPendingIds] = useState<string[]>([]);
    const [approveAllToken, setApproveAllToken] = useState(0);

    // Held in a ref as well so `setPending` never has to be rebuilt when the set changes.
    // A new `setPending` identity would re-run the effect in every card that reads it, and
    // each of those re-runs would call `setPending` again.
    const pendingRef = useRef<Set<string>>(new Set());

    const setPending = useCallback((cardId: string, pending: boolean) => {
        const current = pendingRef.current;
        if (pending === current.has(cardId)) {
            return;
        }

        if (pending) {
            current.add(cardId);
        } else {
            current.delete(cardId);
        }
        setPendingIds([...current]);
    }, []);

    const value = useMemo<ImageProposalContextValue>(
        () => ({
            assistantMessageId,
            results: results ?? EMPTY_RESULTS,
            approveAllToken,
            setPending,
        }),
        [assistantMessageId, results, approveAllToken, setPending],
    );

    const pendingCount = pendingIds.length;

    return (
        <ImageProposalContext.Provider value={value}>
            {children}
            {pendingCount > APPROVE_ALL_THRESHOLD && (
                <div className="mt-3">
                    <GlassButton
                        size="sm"
                        variant="primary"
                        onClick={() => setApproveAllToken((token) => token + 1)}
                        title="Generate every image still awaiting approval in this message"
                    >
                        <Images size={14} />
                        Approve all {pendingCount} images
                    </GlassButton>
                </div>
            )}
        </ImageProposalContext.Provider>
    );
}
