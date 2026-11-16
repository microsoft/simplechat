// reviewSelection.ts
// Which records a Review center workbench has checked for a bulk action.
//
// A workbench checks records in one of two ways. Rows checked on the page follow the same
// click and Shift+click rules as every other list (lib/listSelection.ts), and are pruned to
// the rows still shown after each reload, so a bulk action never reaches a record the
// reviewer can no longer see. "Every record matching these filters" is resolved by the
// server, up to its cap, and belongs to the filters it was resolved for: changing a filter
// drops it rather than applying an old answer to a new question.

import {
    applySelection,
    EMPTY_SELECTION,
    pruneSelection,
    toggleSelectAll,
    type SelectionState,
} from './listSelection';

export interface MatchingSelection {
    ids: string[];
    /** How many records match, which can be more than `ids` holds. */
    total: number;
    /** True when more records match than one selection may hold. */
    capped: boolean;
    cap: number;
    /** The filters the ids were resolved for, as their query string. */
    filterKey: string;
}

export interface ReviewSelection {
    page: SelectionState;
    matching: MatchingSelection | null;
}

export const EMPTY_REVIEW_SELECTION: ReviewSelection = { page: EMPTY_SELECTION, matching: null };

function activeMatching(selection: ReviewSelection, filterKey: string): MatchingSelection | null {
    return selection.matching && selection.matching.filterKey === filterKey ? selection.matching : null;
}

/** The records a bulk action would apply to under the current filters. */
export function checkedIds(selection: ReviewSelection, filterKey: string): string[] {
    return activeMatching(selection, filterKey)?.ids ?? selection.page.ids;
}

/** The "every matching record" selection, when it is the one in use for these filters. */
export function matchingSelection(selection: ReviewSelection, filterKey: string): MatchingSelection | null {
    return activeMatching(selection, filterKey);
}

/**
 * A row's checkbox clicked, with Shift for a range. From an "every matching" selection
 * this keeps the rows of the page that were part of it and continues from there, so a
 * click never silently widens or empties what the reviewer chose.
 */
export function toggleChecked(
    selection: ReviewSelection,
    id: string,
    range: boolean,
    orderedIds: readonly string[],
    filterKey: string,
): ReviewSelection {
    let page = selection.page;
    const matching = activeMatching(selection, filterKey);
    if (matching) {
        const matched = new Set(matching.ids);
        const ids = orderedIds.filter((rowId) => matched.has(rowId));
        page = { ids, anchorId: ids[0] ?? null };
    }
    return { page: applySelection(page, id, range ? 'range' : 'toggle', orderedIds), matching: null };
}

/** The header checkbox: check every row on the page, or clear when they all are. */
export function togglePageChecked(
    selection: ReviewSelection,
    orderedIds: readonly string[],
    filterKey: string,
): ReviewSelection {
    if (activeMatching(selection, filterKey)) return EMPTY_REVIEW_SELECTION;
    return { page: toggleSelectAll(selection.page, orderedIds), matching: null };
}

/** Every record the server found for the current filters, up to its cap. */
export function selectMatching(
    result: { ids: string[]; total: number; capped: boolean; cap: number },
    filterKey: string,
): ReviewSelection {
    return {
        page: EMPTY_SELECTION,
        matching: {
            ids: [...result.ids],
            total: result.total,
            capped: result.capped,
            cap: result.cap,
            filterKey,
        },
    };
}

/**
 * After a reload: checked rows are kept only while they are still shown, and an "every
 * matching" selection only while the filters it was resolved for still apply.
 */
export function pruneReviewSelection(
    selection: ReviewSelection,
    orderedIds: readonly string[],
    filterKey: string,
): ReviewSelection {
    const matching = activeMatching(selection, filterKey);
    const page = pruneSelection(selection.page, orderedIds);
    if (matching === selection.matching && page === selection.page) return selection;
    return { page, matching };
}

/**
 * After a bulk action, only the records it could not change stay checked, so the reviewer
 * can see why and try again. The next reload prunes any that are no longer shown.
 */
export function keepFailures(failedIds: readonly string[]): ReviewSelection {
    return failedIds.length
        ? { page: { ids: [...failedIds], anchorId: failedIds[0] ?? null }, matching: null }
        : EMPTY_REVIEW_SELECTION;
}

/** What the bulk bar says is selected. */
export function selectionSummary(
    selection: ReviewSelection,
    filterKey: string,
    noun: { singular: string; plural: string },
): string {
    const matching = activeMatching(selection, filterKey);
    const count = matching ? matching.ids.length : selection.page.ids.length;
    const label = `${count.toLocaleString()} ${count === 1 ? noun.singular : noun.plural}`;
    if (!matching) return `${label} selected`;
    if (matching.capped) {
        return `${label} selected, the first ${matching.cap.toLocaleString()} of ${matching.total.toLocaleString()} matching`;
    }
    return `All ${label} matching these filters selected`;
}
