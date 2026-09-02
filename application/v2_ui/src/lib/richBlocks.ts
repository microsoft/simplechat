// richBlocks.ts
// Fence languages that render as something other than code, and the streaming guard for them.
//
// While a reply streams, `AssistantMarkdown` re-runs on every token and markdown treats an
// unclosed fence as a code block running to the end of the input. A diagram or chart would
// therefore be handed half of its own source, repeatedly, and fail to parse each time. The
// classic client has the same problem and solves it the same way, with a pending state — see
// `INLINE_CHART_PENDING_REGEX` in chat-inline-charts.js.

import { INLINE_CHART_LANGUAGE } from './inlineChartSpec';

export const MERMAID_LANGUAGE = 'mermaid';

export { INLINE_CHART_LANGUAGE };

/**
 * Info strings substituted for a fence that has not finished arriving.
 *
 * They are namespaced so they cannot collide with a real language a model might use, and
 * they carry the original kind so the skeleton can say what is coming.
 */
export const PENDING_LANGUAGE_PREFIX = 'simplechat-pending-';

export const PENDING_LANGUAGES: Record<string, string> = {
    [MERMAID_LANGUAGE]: `${PENDING_LANGUAGE_PREFIX}${MERMAID_LANGUAGE}`,
    [INLINE_CHART_LANGUAGE]: `${PENDING_LANGUAGE_PREFIX}${INLINE_CHART_LANGUAGE}`,
};

/** The kind behind a pending info string, or null when it is not one. */
export function readPendingKind(language: string): string | null {
    if (!language.startsWith(PENDING_LANGUAGE_PREFIX)) {
        return null;
    }
    return language.slice(PENDING_LANGUAGE_PREFIX.length) || null;
}

const FENCE_LINE = /^([ \t]{0,3})(`{3,}|~{3,})[ \t]*(\S*)/;

/**
 * Replace a still-arriving mermaid or chart fence with a closed placeholder fence.
 *
 * Only the final, unterminated fence is affected: anything already closed earlier in the
 * message is complete and renders normally, so a chart at the top of a long answer is drawn
 * while the prose beneath it is still being written.
 */
export function markPendingFences(text: string): string {
    if (!text) {
        return text;
    }

    const lines = text.split('\n');
    let openIndex = -1;
    let openMarker = '';
    let openLength = 0;
    let openLanguage = '';

    for (let index = 0; index < lines.length; index += 1) {
        const match = FENCE_LINE.exec(lines[index]);
        if (!match) {
            continue;
        }

        const marker = match[2][0];
        const length = match[2].length;

        if (openIndex === -1) {
            openIndex = index;
            openMarker = marker;
            openLength = length;
            openLanguage = match[3].toLowerCase();
            continue;
        }

        // A closing fence uses the same character, is at least as long, and carries no
        // info string of its own.
        if (marker === openMarker && length >= openLength && match[3] === '') {
            openIndex = -1;
            openMarker = '';
            openLength = 0;
            openLanguage = '';
        }
    }

    if (openIndex === -1) {
        return text;
    }

    const pending = PENDING_LANGUAGES[openLanguage];
    if (!pending) {
        return text;
    }

    const fence = openMarker.repeat(openLength);
    return [...lines.slice(0, openIndex), `${fence}${pending}`, fence].join('\n');
}
