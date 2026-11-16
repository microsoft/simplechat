// mathSegments.ts
// Lift TeX expressions out of assistant text so they can be rendered as maths.
//
// This follows the same shape as `citations.ts` and `masking.ts`: the expression is replaced
// by an inert `⟦math:N⟧` token that survives the markdown pipeline untouched, and the
// renderer swaps a component back in afterwards. Nothing here produces HTML, so model output
// never reaches a markup sink through this path.
//
// Why a raw-string pass rather than a remark plugin: CommonMark treats a backslash before
// ASCII punctuation as an escape, so by the time an mdast text node exists `\(x\)` has
// already become the literal text `(x)` and the delimiters are simply gone. They have to be
// recognised before the markdown parser runs.
//
// Recognised delimiters are `$$…$$`, `\[…\]` and `\(…\)`. A single `$…$` is deliberately
// **not** recognised: it is ordinary in prose about money, and treating "costs $5 to $10 per
// user" as an equation is a worse failure than leaving a rare inline expression unrendered.

export interface MathSegment {
    /** Stable key for the rendered component. */
    id: string;
    /** TeX source, trimmed, exactly as it will be handed to KaTeX. */
    tex: string;
    /** Centred block rather than inline with the surrounding sentence. */
    display: boolean;
}

export interface ParsedMath {
    /** Text with each expression replaced by a placeholder of the form `⟦math:N⟧`. */
    text: string;
    segments: MathSegment[];
}

export const MATH_PLACEHOLDER = (index: number) => `\u27E6math:${index}\u27E7`;

export const MATH_PLACEHOLDER_PATTERN = /\u27E6math:(\d+)\u27E7/g;

/**
 * Cap on how far a scan will look for a closing delimiter.
 *
 * An unpaired `$$` would otherwise swallow the remainder of a long answer and render it as
 * one broken equation. Past this distance the opening delimiter is treated as ordinary text,
 * which leaves the message readable.
 */
const MAX_MATH_LENGTH = 2000;

/** Matches an opening code fence, allowing CommonMark's three spaces of indentation. */
const FENCE_OPEN = /^ {0,3}(`{3,}|~{3,})/;

interface Fence {
    marker: string;
    length: number;
}

function matchFenceOpen(input: string, index: number): Fence | null {
    const lineEnd = input.indexOf('\n', index);
    const line = input.slice(index, lineEnd === -1 ? input.length : lineEnd);
    const match = FENCE_OPEN.exec(line);
    if (!match) {
        return null;
    }
    return { marker: match[1][0], length: match[1].length };
}

/**
 * Return the index just past a fenced code block, so its contents are copied verbatim.
 *
 * A ```` ```simplechart ```` or ```` ```mermaid ```` block is exactly the kind of place a
 * stray `$$` or `\[` shows up without meaning maths.
 */
function skipFencedBlock(input: string, index: number, fence: Fence): number {
    let cursor = input.indexOf('\n', index);
    if (cursor === -1) {
        return input.length;
    }
    cursor += 1;

    while (cursor < input.length) {
        const lineEnd = input.indexOf('\n', cursor);
        const line = input.slice(cursor, lineEnd === -1 ? input.length : lineEnd);
        const closing = new RegExp(`^ {0,3}\\${fence.marker}{${fence.length},}\\s*$`);
        if (closing.test(line)) {
            return lineEnd === -1 ? input.length : lineEnd + 1;
        }
        if (lineEnd === -1) {
            return input.length;
        }
        cursor = lineEnd + 1;
    }

    return input.length;
}

/**
 * Return the index just past an inline code span.
 *
 * CommonMark closes a span with a backtick run of exactly the opening length, which is what
 * keeps `` `$$` `` from being read as a delimiter.
 */
function skipInlineCode(input: string, index: number): number {
    let openLength = 0;
    while (input[index + openLength] === '`') {
        openLength += 1;
    }

    let cursor = index + openLength;
    while (cursor < input.length) {
        if (input[cursor] !== '`') {
            cursor += 1;
            continue;
        }
        let runLength = 0;
        while (input[cursor + runLength] === '`') {
            runLength += 1;
        }
        if (runLength === openLength) {
            return cursor + runLength;
        }
        cursor += runLength;
    }

    // Unclosed run: treat the backticks themselves as literal text.
    return index + openLength;
}

/** True when nothing but whitespace shares the expression's lines. */
function occupiesOwnLines(input: string, start: number, end: number): boolean {
    const lineStart = input.lastIndexOf('\n', start - 1) + 1;
    if (input.slice(lineStart, start).trim() !== '') {
        return false;
    }

    const lineEnd = input.indexOf('\n', end);
    const trailing = input.slice(end, lineEnd === -1 ? input.length : lineEnd);
    return trailing.trim() === '';
}

/**
 * Replace TeX expressions with placeholders and return the expressions behind them.
 *
 * Fenced code blocks and inline code spans are copied through untouched, so a code sample
 * containing `\[` or `$$` is left exactly as written.
 */
export function parseMath(input: string): ParsedMath {
    if (!input || (!input.includes('$$') && !input.includes('\\(') && !input.includes('\\['))) {
        return { text: input, segments: [] };
    }

    const segments: MathSegment[] = [];
    const out: string[] = [];
    let index = 0;
    let atLineStart = true;

    const take = (tex: string, display: boolean): string => {
        const placeholder = MATH_PLACEHOLDER(segments.length);
        segments.push({ id: `math-${segments.length}`, tex: tex.trim(), display });
        return placeholder;
    };

    while (index < input.length) {
        if (atLineStart) {
            const fence = matchFenceOpen(input, index);
            if (fence) {
                const end = skipFencedBlock(input, index, fence);
                out.push(input.slice(index, end));
                index = end;
                atLineStart = true;
                continue;
            }
        }

        const character = input[index];

        if (character === '\n') {
            out.push(character);
            index += 1;
            atLineStart = true;
            continue;
        }

        atLineStart = false;

        if (character === '`') {
            const end = skipInlineCode(input, index);
            out.push(input.slice(index, end));
            index = end;
            continue;
        }

        if (character === '\\') {
            const next = input[index + 1];

            // An escaped backslash is consumed whole so `\\(` is not read as `\(`.
            if (next === '\\') {
                out.push('\\\\');
                index += 2;
                continue;
            }

            if (next === '[' || next === '(') {
                const closing = next === '[' ? '\\]' : '\\)';
                const contentStart = index + 2;
                const closeIndex = input.indexOf(closing, contentStart);
                if (closeIndex !== -1 && closeIndex - contentStart <= MAX_MATH_LENGTH) {
                    const tex = input.slice(contentStart, closeIndex);
                    if (tex.trim() !== '') {
                        out.push(take(tex, next === '['));
                        index = closeIndex + 2;
                        continue;
                    }
                }
            }

            out.push(character);
            index += 1;
            continue;
        }

        if (character === '$' && input[index + 1] === '$') {
            const contentStart = index + 2;
            const closeIndex = input.indexOf('$$', contentStart);
            if (closeIndex !== -1 && closeIndex - contentStart <= MAX_MATH_LENGTH) {
                const tex = input.slice(contentStart, closeIndex);
                if (tex.trim() !== '') {
                    out.push(take(tex, occupiesOwnLines(input, index, closeIndex + 2)));
                    index = closeIndex + 2;
                    continue;
                }
            }

            out.push('$$');
            index += 2;
            continue;
        }

        out.push(character);
        index += 1;
    }

    return { text: out.join(''), segments };
}
