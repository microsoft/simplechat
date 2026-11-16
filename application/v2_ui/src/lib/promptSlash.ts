// promptSlash.ts
// The composer's `/` prompt search, and the rules for putting text into a textarea.
//
// Two things live here because they are the same problem seen twice: deciding what region of
// the composer a piece of text replaces. The slash menu replaces the token being typed; the
// prompt picker replaces the selection, or nothing at all. Both were previously done by
// assigning the whole value, which is what made picking a prompt discard everything already
// written.
//
// Shaped after lib/mentions.ts, which does the equivalent job for `@`. Nothing here touches the
// DOM: the caller reads `selectionStart` and writes the result back, so the rules can be tested
// without a textarea.

import type { PromptOption } from './types';

/** Longest query the menu stays open for, past which this is prose rather than a search. */
export const MAX_SLASH_QUERY_LENGTH = 40;

/** How many prompts the menu offers at once. */
export const SLASH_RESULT_LIMIT = 8;

export interface SlashQuery {
    /** What has been typed after the slash. */
    query: string;
    /** Index of the `/`. */
    start: number;
    /** Index just past the query, which is the caret. */
    end: number;
}

/**
 * The slash token the caret is currently inside, if any.
 *
 * The slash must open a word: at the very start of the text, or straight after whitespace.
 * Without that rule `https://example.com` and `and/or` both open the menu mid-word, which is
 * the reason a naive implementation of this feels broken rather than helpful.
 *
 * A newline between the slash and the caret ends the token: the menu should not still be open
 * two paragraphs later.
 */
export function readSlashQuery(text: string, caret: number): SlashQuery | null {
    const value = String(text ?? '');
    const position = Math.max(0, Math.min(caret, value.length));

    const slashIndex = value.lastIndexOf('/', position - 1);
    if (slashIndex === -1) {
        return null;
    }

    const preceding = slashIndex === 0 ? '' : value[slashIndex - 1];
    if (preceding && !/\s/.test(preceding)) {
        return null;
    }

    const query = value.slice(slashIndex + 1, position);
    if (query.includes('\n') || query.length > MAX_SLASH_QUERY_LENGTH) {
        return null;
    }
    // `/ ` is a slash in prose, not a command. Without this the query trims to empty, which
    // `filterPromptsForSlash` reads as "offer everything" -- so the menu stays open over an
    // ordinary sentence and swallows the Enter that was meant to send it.
    if (/^\s/.test(query)) {
        return null;
    }

    return { query, start: slashIndex, end: position };
}

function haystack(prompt: PromptOption): string {
    return [prompt.name, prompt.description, prompt.scope_name]
        .map((part) => String(part ?? ''))
        .join(' ')
        .toLowerCase();
}

function promptSortKey(prompt: PromptOption): string {
    return String(prompt.name ?? '').toLowerCase();
}

/**
 * The prompts a slash query offers, favourites first.
 *
 * Ordering is stable and does not depend on the query, so the row under the pointer does not
 * move as another character is typed. Matching is a plain substring over name, description and
 * scope: a fuzzy match would put a surprising row first, and this list is short enough that it
 * would buy nothing.
 */
export function filterPromptsForSlash(
    prompts: PromptOption[] | undefined,
    query: string,
    limit: number = SLASH_RESULT_LIMIT,
): PromptOption[] {
    const raw = String(query ?? '');
    const needle = raw.trim().toLowerCase();

    // "Nothing typed yet" offers everything; "typed only whitespace" offers nothing. Collapsing
    // the two is what let `/ ` match every prompt and hold the menu open over prose.
    if (raw.length > 0 && needle.length === 0) {
        return [];
    }

    const matched = (prompts ?? []).filter((prompt) => {
        if (!prompt?.id) {
            return false;
        }
        return needle ? haystack(prompt).includes(needle) : true;
    });

    return matched
        .slice()
        .sort((left, right) => {
            const leftFavourite = left.is_favorite === true;
            const rightFavourite = right.is_favorite === true;
            if (leftFavourite !== rightFavourite) {
                return leftFavourite ? -1 : 1;
            }
            return promptSortKey(left).localeCompare(promptSortKey(right));
        })
        .slice(0, Math.max(0, limit));
}

/**
 * Splice text into a value at the caret or over the selection.
 *
 * The separator rules exist because a prompt is usually a paragraph, and dropping one straight
 * onto the end of a half-written sentence produces a run-on that has to be repaired by hand.
 * A multi-line prompt gets a blank line, a single-line one gets a space, and neither is added
 * when the neighbouring text already provides its own whitespace.
 */
export function insertPromptText(
    text: string,
    selectionStart: number,
    selectionEnd: number,
    insertion: string,
): { text: string; caret: number } {
    const value = String(text ?? '');
    const addition = String(insertion ?? '');

    const start = Math.max(0, Math.min(selectionStart, value.length));
    const end = Math.max(start, Math.min(selectionEnd, value.length));

    const before = value.slice(0, start);
    const after = value.slice(end);

    const gap = addition.includes('\n') ? '\n\n' : ' ';
    const lead = before && !/\s$/.test(before) ? gap : '';
    const trail = after && !/^\s/.test(after) ? gap : '';

    const middle = `${lead}${addition}${trail}`;
    return {
        text: `${before}${middle}${after}`,
        // Just past the inserted text, before any trailing separator, so typing continues where
        // the prompt ended rather than after a blank line the user did not ask for.
        caret: before.length + lead.length + addition.length,
    };
}

/**
 * A name suggested for a prompt saved from chat.
 *
 * The first meaningful line, stripped of markdown heading and list markers and shortened to
 * something that fits a list row. Returns an empty string when there is nothing to work with,
 * so the caller decides on the fallback rather than being handed "Untitled" it has to detect.
 */
export function suggestPromptName(text: string, maxLength = 60): string {
    const firstLine = String(text ?? '')
        .split('\n')
        .map((line) => line.replace(/^\s*(?:[#>*+-]+\s*|\d+[.)]\s*)/, '').trim())
        .find((line) => line.length > 0);

    if (!firstLine) {
        return '';
    }

    // Strip the markdown emphasis that would otherwise show up as literal asterisks in a list.
    const cleaned = firstLine.replace(/[*_`]+/g, '').trim();
    if (cleaned.length <= maxLength) {
        return cleaned;
    }

    // Cut on a word boundary when there is one reasonably close to the limit, so the name does
    // not end mid-word.
    const clipped = cleaned.slice(0, maxLength);
    const lastSpace = clipped.lastIndexOf(' ');
    return `${(lastSpace > maxLength * 0.6 ? clipped.slice(0, lastSpace) : clipped).trimEnd()}…`;
}
