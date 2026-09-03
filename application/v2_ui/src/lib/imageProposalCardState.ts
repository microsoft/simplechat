// imageProposalCardState.ts
// The state of one image proposal approval card.
//
// This lives apart from the card that displays it, because it has to outlive that card. A card
// is rendered from inside react-markdown's output, and react-markdown builds its elements from
// the component map it is handed; React rebuilds that whole subtree whenever the map's
// identity changes, and rebuilt it on every render of the message before `AssistantMarkdown`
// began memoising it. Approving three images then reset the second and third cards the instant
// the first image arrived: no progress shown, Approve enabled again, and an invitation to pay
// for an image that was already being generated.
//
// Keeping the state here, in a plain record the message's proposal scope owns, makes that
// class of bug unreachable rather than merely unlikely: whatever causes a card to be rebuilt,
// it reads the same entry back and carries on reporting the approval that is still running.

/**
 * Where an approval has got to.
 *
 * `generated` means the server reported success but the stored image could not be matched
 * back to the card. The image exists either way, so the card says so rather than sitting on a
 * spinner that will never resolve.
 */
export type ApprovalStatus =
    | 'idle'
    | 'queued'
    | 'generating'
    | 'generated'
    | 'error'
    | 'cancelled';

export interface ProposalCardState {
    status: ApprovalStatus;
    /** How many approvals are ahead of this one, while it is queued. */
    queuePosition: number;
    /** Why the approval failed. Shown only in the `error` status. */
    failure: string;
    /** The prompt as edited; absent means the proposal's own prompt is still in use. */
    prompt?: string;
    /** Whether the prompt editor is open. */
    editing: boolean;
}

/** What an untouched card reads. Frozen and shared, so it is one stable object. */
export const IDLE_CARD_STATE: ProposalCardState = Object.freeze({
    status: 'idle' as ApprovalStatus,
    queuePosition: 0,
    failure: '',
    editing: false,
});

/** Every card in one message, keyed by `proposalCardKey`. */
export type ProposalCardStates = Record<string, ProposalCardState>;

/**
 * Apply a patch to one card, returning the record to store.
 *
 * A patch that changes nothing returns the record it was given, unchanged and identical. That
 * is not a micro-optimisation: the approval queue reports its position to every waiting card
 * each time it moves, and most of those reports leave a given card exactly where it was.
 * Returning a new record for each would re-render every card in the message, repeatedly, for
 * no visible change.
 *
 * A key with no entry yet starts from `IDLE_CARD_STATE`, so a caller never has to seed one.
 */
export function applyCardStatePatch(
    states: ProposalCardStates,
    cardKey: string,
    patch: Partial<ProposalCardState>,
): ProposalCardStates {
    const previous = states[cardKey];
    const base = previous ?? IDLE_CARD_STATE;
    const next: ProposalCardState = { ...base, ...patch };

    const changed = (Object.keys(patch) as (keyof ProposalCardState)[]).some(
        (key) => base[key] !== next[key],
    );
    if (previous && !changed) {
        return states;
    }

    return { ...states, [cardKey]: next };
}
