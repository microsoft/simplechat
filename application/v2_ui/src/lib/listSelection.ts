// listSelection.ts
// The selection algebra behind click / Ctrl+click / Shift+click, over any ordered list of ids.
//
// Kept free of React and of any particular item shape: every function here takes the ids as
// currently displayed and returns a new selection. That is what lets the awkward parts --
// a range that must follow a re-sorted list, a selection that outlives the rows it named --
// be exercised directly in a test rather than through a renderer.
//
// Shared by the workspace documents explorer and the chat conversation rail so the two
// behave identically under the same modifier keys.

export interface SelectionState {
    /** Selected ids, in the order they appear in the list. */
    ids: string[];
    /** Where a Shift+click range starts. Null when there is nothing to extend from. */
    anchorId: string | null;
}

export const EMPTY_SELECTION: SelectionState = { ids: [], anchorId: null };

export type SelectionIntent = 'replace' | 'toggle' | 'range';

/**
 * Read the intent out of a click's modifier keys.
 *
 * Ctrl and Cmd are treated the same so the behaviour matches the platform the user is on
 * without the caller having to know which that is.
 */
export function selectionIntentFromEvent(event: {
    shiftKey?: boolean;
    ctrlKey?: boolean;
    metaKey?: boolean;
}): SelectionIntent {
    if (event.shiftKey) {
        return 'range';
    }
    if (event.ctrlKey || event.metaKey) {
        return 'toggle';
    }
    return 'replace';
}

/**
 * Apply a click to the selection.
 *
 * `orderedIds` is the list as currently displayed, which is what makes a Shift+click range
 * mean what the user sees: re-sorting the list changes which items lie between the anchor
 * and the click, and reading the order from the rendered list rather than from the
 * selection is what keeps the two in step.
 *
 * A range extends from the anchor and *replaces* the selection rather than adding to it,
 * which is what lets a user correct an over-long range by Shift+clicking a nearer row
 * instead of having to start again.
 */
export function applySelection(
    selection: SelectionState,
    identifier: string,
    intent: SelectionIntent,
    orderedIds: readonly string[],
): SelectionState {
    if (!identifier) {
        return selection;
    }

    if (intent === 'range' && selection.anchorId) {
        const anchorIndex = orderedIds.indexOf(selection.anchorId);
        const targetIndex = orderedIds.indexOf(identifier);
        if (anchorIndex !== -1 && targetIndex !== -1) {
            const [start, end] =
                anchorIndex <= targetIndex
                    ? [anchorIndex, targetIndex]
                    : [targetIndex, anchorIndex];
            return {
                ids: orderedIds.slice(start, end + 1),
                anchorId: selection.anchorId,
            };
        }
    }

    if (intent === 'toggle') {
        const selected = new Set(selection.ids);
        if (selected.has(identifier)) {
            selected.delete(identifier);
        } else {
            selected.add(identifier);
        }
        return {
            ids: orderedIds.filter((id) => selected.has(id)),
            anchorId: identifier,
        };
    }

    return { ids: [identifier], anchorId: identifier };
}

/** Select every row on the page, or clear when they are all selected already. */
export function toggleSelectAll(
    selection: SelectionState,
    orderedIds: readonly string[],
): SelectionState {
    const allSelected =
        orderedIds.length > 0 && orderedIds.every((id) => selection.ids.includes(id));
    if (allSelected) {
        return EMPTY_SELECTION;
    }
    return { ids: [...orderedIds], anchorId: orderedIds[0] ?? null };
}

/**
 * Drop ids that are no longer on the page.
 *
 * Called after every reload. Without it a bulk action taken after paging would apply to
 * items the user can no longer see, which is the kind of surprise a delete button must
 * never produce.
 */
export function pruneSelection(
    selection: SelectionState,
    orderedIds: readonly string[],
): SelectionState {
    const visible = new Set(orderedIds);
    const ids = selection.ids.filter((id) => visible.has(id));
    if (ids.length === selection.ids.length) {
        return selection;
    }
    return {
        ids,
        anchorId:
            selection.anchorId && visible.has(selection.anchorId)
                ? selection.anchorId
                : (ids[0] ?? null),
    };
}

/** Move the selection by one row, optionally extending it, for arrow-key navigation. */
export function moveSelection(
    selection: SelectionState,
    orderedIds: readonly string[],
    delta: number,
    extend: boolean,
): SelectionState {
    if (orderedIds.length === 0) {
        return selection;
    }

    const current = selection.ids[selection.ids.length - 1];
    const currentIndex = current ? orderedIds.indexOf(current) : -1;
    const nextIndex = Math.max(
        0,
        Math.min(orderedIds.length - 1, currentIndex === -1 ? 0 : currentIndex + delta),
    );
    const nextId = orderedIds[nextIndex];

    if (extend && selection.anchorId) {
        return applySelection(selection, nextId, 'range', orderedIds);
    }
    return { ids: [nextId], anchorId: nextId };
}

/**
 * Whether every visible row is selected, used to drive a select-all control.
 *
 * An empty list is not "all selected": a header checkbox that ticks itself when there is
 * nothing to tick reads as a bug.
 */
export function isEverythingSelected(
    selectedIds: readonly string[],
    orderedIds: readonly string[],
): boolean {
    return orderedIds.length > 0 && orderedIds.every((id) => selectedIds.includes(id));
}
