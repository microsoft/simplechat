// chat-math-segments.js
// Adapted from V2's mathSegments.ts. Extract TeX before Markdown consumes its escapes.

export const MAX_MATH_LENGTH = 2000;
const MAX_MATH_SEGMENTS = 100;
const FENCE_OPEN = /^ {0,3}(`{3,}|~{3,})/;

function skipFencedBlock(input, index, fence) {
    let cursor = input.indexOf('\n', index);
    if (cursor === -1) return input.length;
    const closing = new RegExp(`^ {0,3}${fence[0]}{${fence.length},}\\s*$`);
    cursor += 1;
    while (cursor < input.length) {
        const lineEnd = input.indexOf('\n', cursor);
        const end = lineEnd === -1 ? input.length : lineEnd;
        if (closing.test(input.slice(cursor, end))) return end === input.length ? end : end + 1;
        cursor = end + 1;
    }
    return input.length;
}

function skipInlineCode(input, index) {
    let length = 1;
    while (input[index + length] === '`') length += 1;
    let cursor = index + length;
    while (cursor < input.length) {
        if (input[cursor] !== '`') {
            cursor += 1;
            continue;
        }
        let run = 1;
        while (input[cursor + run] === '`') run += 1;
        if (run === length) return cursor + run;
        cursor += run;
    }
    return index + length;
}

function skipLinkDestination(input, index) {
    let depth = 1;
    for (let cursor = index + 2; cursor < input.length; cursor += 1) {
        if (input[cursor] === '\\') {
            cursor += 1;
        } else if (input[cursor] === '(') {
            depth += 1;
        } else if (input[cursor] === ')' && --depth === 0) {
            return cursor + 1;
        }
    }
    return index + 2;
}

function occupiesOwnLines(input, start, end) {
    const lineStart = input.lastIndexOf('\n', start - 1) + 1;
    const lineEnd = input.indexOf('\n', end);
    return !input.slice(lineStart, start).trim()
        && !input.slice(end, lineEnd === -1 ? input.length : lineEnd).trim();
}

export function parseMath(input) {
    let namespace = 0;
    while (input.includes(`\u27e6scmath:${namespace}:`)) namespace += 1;
    const prefix = `\u27e6scmath:${namespace}:`;
    const pattern = new RegExp(`${prefix}(\\d+)\u27e7`, 'g');
    const segments = [];
    if (!input.includes('$$') && !input.includes('\\(') && !input.includes('\\[')) {
        return { text: input, segments, pattern };
    }
    const out = [];
    let index = 0;

    while (index < input.length) {
        if (segments.length === MAX_MATH_SEGMENTS) {
            out.push(input.slice(index));
            break;
        }
        if (index === 0 || input[index - 1] === '\n') {
            const end = input.indexOf('\n', index);
            const line = input.slice(index, end === -1 ? input.length : end);
            const fence = FENCE_OPEN.exec(line);
            if (fence) {
                const next = skipFencedBlock(input, index, fence[1]);
                out.push(input.slice(index, next));
                index = next;
                continue;
            }
            if (/^ {0,3}\[[^\]\n]+\]:/.test(line)) {
                out.push(line);
                index += line.length;
                continue;
            }
        }
        if (input[index] === '`') {
            const next = skipInlineCode(input, index);
            out.push(input.slice(index, next));
            index = next;
            continue;
        }
        if (input.startsWith('](', index)) {
            const next = skipLinkDestination(input, index);
            out.push(input.slice(index, next));
            index = next;
            continue;
        }
        if (input[index] === '<') {
            const tag = /^(?:<!--[\s\S]*?-->|<\/?[A-Za-z][^>]*>)/.exec(input.slice(index));
            if (tag) {
                out.push(tag[0]);
                index += tag[0].length;
                continue;
            }
        }

        const opener = input.slice(index, index + 2);
        const closing = opener === '\\[' ? '\\]' : opener === '\\(' ? '\\)' : opener === '$$' ? '$$' : null;
        if (closing) {
            const contentStart = index + 2;
            const remaining = input.slice(contentStart, contentStart + MAX_MATH_LENGTH + 2);
            const closeOffset = remaining.indexOf(closing);
            if (closeOffset !== -1 && remaining.slice(0, closeOffset).trim()) {
                const end = contentStart + closeOffset + 2;
                const source = input.slice(index, end);
                segments.push({
                    source,
                    tex: remaining.slice(0, closeOffset).trim(),
                    display: opener === '\\[' || (opener === '$$' && occupiesOwnLines(input, index, end)),
                });
                out.push(`${prefix}${segments.length - 1}\u27e7`);
                index = end;
                continue;
            }
        }
        // Consume escaped punctuation together, including literal \\( and \$.
        const length = input[index] === '\\' && index + 1 < input.length ? 2 : 1;
        out.push(input.slice(index, index + length));
        index += length;
    }
    return { text: out.join(''), segments, pattern };
}

export function restoreMathSource(text, parsed) {
    return text.replace(parsed.pattern, (token, index) => parsed.segments[Number(index)]?.source ?? token);
}
