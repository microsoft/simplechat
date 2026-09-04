// chatContextTokens.ts
// The `#[…]` grammar that keeps the composer's context chips and its message text in step.
//
// A context reference exists in two places at once: as a chip above the input, and as literal
// text inside it. That is deliberate -- the reference stays in the message the user actually
// sends, so "compare #[Q3 Contract.pdf] against #[Q2 Contract.pdf]" still reads as a sentence
// after it has been sent, and still reads as one to the model. Only the message text survives
// into every downstream view; per-message metadata keeps `requested_document_ids` but nothing
// renders it in prose.
//
// Holding the same fact twice means they can disagree, so the rules below are written around a
// single principle: THE TEXT IS AUTHORITATIVE FOR REMOVAL, THE CHIP LIST IS AUTHORITATIVE FOR
// IDENTITY. A token that has been edited or deleted drops its chip (`reconcileContextItems`),
// but a token typed by hand never creates one -- there is no id behind it, and inventing a
// document from a string the user typed is exactly the kind of guess that produces a request
// citing something they never chose.
//
// Shaped after lib/promptSlash.ts and lib/mentions.ts, which do the equivalent job for `/` and
// `@`. Nothing here touches the DOM: the caller reads `selectionStart` and writes the result
// back, so every rule is testable without a textarea.

/** Longest query the menu stays open for, past which this is prose rather than a search. */
export const MAX_CONTEXT_QUERY_LENGTH = 60;

/**
 * Longest label carried inside a token.
 *
 * Document titles run to sentence length, and an untruncated one turns the message box into a
 * wall of brackets. The chip keeps the full title; only the token is shortened.
 */
export const MAX_CONTEXT_LABEL_LENGTH = 80;

/**
 * Matches one complete token.
 *
 * `[^\]\n]+` rather than `.+?` so a token can never span a line or swallow the next one: an
 * unclosed `#[` stays inert text instead of eating the rest of the paragraph the moment a
 * later token closes it.
 */
const CONTEXT_TOKEN_PATTERN = /#\[([^\]\n]+)\]/g;

export interface ContextQuery {
    /** What has been typed after the `#`. */
    query: string;
    /** Index of the `#`. */
    start: number;
    /** Index just past the query, which is the caret. */
    end: number;
}

export interface ParsedContextToken {
    /** The text between the brackets. */
    label: string;
    /** The whole token including `#[` and `]`. */
    token: string;
    start: number;
    end: number;
}

/**
 * Make a label safe to carry inside a token.
 *
 * Brackets are the delimiters, so a title containing one would truncate its own token and
 * leave the remainder as loose text. They are replaced rather than escaped because the token
 * is read by people as much as by `parseContextTokens`, and `#[Report (final)]` reads better
 * than `#[Report \]final\[]`.
 */
export function sanitizeContextLabel(label: string): string {
    const collapsed = String(label ?? '')
        .replace(/[\r\n\t]+/g, ' ')
        .replace(/\[/g, '(')
        .replace(/\]/g, ')')
        .replace(/\s{2,}/g, ' ')
        .trim();

    if (collapsed.length <= MAX_CONTEXT_LABEL_LENGTH) {
        return collapsed;
    }
    return `${collapsed.slice(0, MAX_CONTEXT_LABEL_LENGTH).trimEnd()}…`;
}

/**
 * A label that no existing token is already using.
 *
 * Two documents may share a title, and two identical tokens could not be told apart when one
 * of them is removed. The suffix is applied to the sanitized label so the cap above is not
 * quietly exceeded by the disambiguator.
 */
export function uniqueContextLabel(label: string, taken: Iterable<string>): string {
    const base = sanitizeContextLabel(label) || 'Untitled';
    const used = new Set(taken);
    if (!used.has(base)) {
        return base;
    }

    for (let suffix = 2; suffix < 1000; suffix += 1) {
        const candidate = sanitizeContextLabel(`${base} (${suffix})`);
        if (!used.has(candidate)) {
            return candidate;
        }
    }
    return base;
}

/** Wrap a label that has already been sanitized and de-duplicated. */
export function buildContextToken(label: string): string {
    return `#[${label}]`;
}

/** Every complete token in the text, in the order they appear. */
export function parseContextTokens(text: string): ParsedContextToken[] {
    const value = String(text ?? '');
    const found: ParsedContextToken[] = [];

    // A fresh regex per call: CONTEXT_TOKEN_PATTERN is global, and sharing `lastIndex` across
    // calls makes results depend on who parsed last.
    const pattern = new RegExp(CONTEXT_TOKEN_PATTERN.source, 'g');
    let match = pattern.exec(value);
    while (match !== null) {
        found.push({
            label: match[1],
            token: match[0],
            start: match.index,
            end: match.index + match[0].length,
        });
        match = pattern.exec(value);
    }
    return found;
}

/**
 * The `#` query the caret is currently inside, if any.
 *
 * The `#` must open a word -- at the very start, or straight after whitespace -- so a markdown
 * heading is unaffected and `C#` mid-sentence does not open the menu.
 *
 * A `#` immediately followed by `[` is a token, not a query. Without that rule, clicking just
 * after the hash of an existing `#[Contract.pdf]` reopens the menu over a reference that has
 * already been resolved.
 */
export function readContextQuery(text: string, caret: number): ContextQuery | null {
    const value = String(text ?? '');
    const position = Math.max(0, Math.min(caret, value.length));

    const hashIndex = value.lastIndexOf('#', position - 1);
    if (hashIndex === -1) {
        return null;
    }

    const preceding = hashIndex === 0 ? '' : value[hashIndex - 1];
    if (preceding && !/\s/.test(preceding)) {
        return null;
    }

    if (value[hashIndex + 1] === '[') {
        return null;
    }

    const query = value.slice(hashIndex + 1, position);
    if (query.includes('\n') || query.length > MAX_CONTEXT_QUERY_LENGTH) {
        return null;
    }
    // `# ` is a hash in prose. Left alone it trims to empty, which the suggestion builder
    // reads as "offer everything", holding the menu open over an ordinary sentence and
    // swallowing the Enter meant to send it. `]` and `[` end it for the same reason.
    if (/^\s/.test(query) || /[[\]]/.test(query)) {
        return null;
    }

    return { query, start: hashIndex, end: position };
}

/**
 * Replace the `#` query under the caret with a finished token.
 *
 * A trailing space is added so the next word does not run into the closing bracket, but only
 * when the following text does not already begin with whitespace -- otherwise picking two
 * references in a row leaves a widening gap between them.
 */
export function insertContextToken(
    text: string,
    start: number,
    end: number,
    token: string,
): { text: string; caret: number } {
    const value = String(text ?? '');
    const from = Math.max(0, Math.min(start, value.length));
    const to = Math.max(from, Math.min(end, value.length));

    const before = value.slice(0, from);
    const after = value.slice(to);

    const lead = before && !/\s$/.test(before) ? ' ' : '';
    const trail = /^\s/.test(after) ? '' : ' ';

    return {
        text: `${before}${lead}${token}${trail}${after}`,
        caret: before.length + lead.length + token.length + trail.length,
    };
}

/**
 * Append a token to the end of the text.
 *
 * Used by the picker popover and by the workspace hand-off, neither of which has a `#` query
 * to replace. The hand-off arrives with an empty composer, so the leading separator rule keeps
 * it from opening on a stray space.
 */
export function appendContextToken(text: string, token: string): string {
    const value = String(text ?? '');
    const lead = value && !/\s$/.test(value) ? ' ' : '';
    return `${value}${lead}${token} `;
}

/**
 * Remove every occurrence of a token.
 *
 * Removal has to tidy after itself: deleting the token from `compare #[A] with #[B]` by simple
 * excision leaves a double space, and doing that a few times leaves a line of them. When the
 * token had whitespace on both sides, one space is kept.
 */
export function removeContextToken(text: string, token: string): string {
    const value = String(text ?? '');
    if (!token || !value.includes(token)) {
        return value;
    }

    let result = '';
    let cursor = 0;
    for (;;) {
        const at = value.indexOf(token, cursor);
        if (at === -1) {
            result += value.slice(cursor);
            break;
        }

        const before = value.slice(cursor, at);
        const afterIndex = at + token.length;
        const followedBySpace = /^[^\S\n]/.test(value.slice(afterIndex));
        const precededBySpace = /[^\S\n]$/.test(before);
        // End of the text, or end of the line, is a seam too: a token removed from there
        // would otherwise leave the space that used to separate it dangling.
        const atEdge = afterIndex >= value.length || value[afterIndex] === '\n';

        // Drop one side of the gap the token used to sit in, so the join reads as a single
        // space rather than the two that surrounded it.
        result += precededBySpace && (followedBySpace || atEdge) ? before.slice(0, -1) : before;
        cursor = followedBySpace && !precededBySpace ? afterIndex + 1 : afterIndex;
    }

    return result;
}

/**
 * Drop the items whose token is no longer in the text.
 *
 * This is what makes editing the sentence a supported way of removing a reference: backspacing
 * through `#[Q3 Contract.pdf]` retires the chip, rather than leaving a chip that still puts the
 * document in the request while the message no longer mentions it.
 *
 * Order follows the chip list, not the text, so removing one reference does not reshuffle the
 * row underneath the pointer.
 */
export function reconcileContextItems<T extends { token: string }>(
    text: string,
    items: readonly T[],
): T[] {
    if (items.length === 0) {
        return [];
    }

    const present = new Set(parseContextTokens(text).map((entry) => entry.token));
    return items.filter((item) => present.has(item.token));
}
