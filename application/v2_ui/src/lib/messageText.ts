// messageText.ts
// A message as plain text, for when it leaves the app: the clipboard, a downloaded file, or
// the composer.
//
// What is on screen is not `message.content`. Two transformations sit between them, and both
// matter outside the app:
//
//   - Masked spans are redacted. Copying the raw content would hand back text a reader has
//     deliberately hidden, so the redaction has to survive the copy.
//   - Citation markers are lifted out and shown as chips. Pasted verbatim they are noise:
//
//         ...at full load. (Source: NanoPZ.pdf, Page: 13) [#0d4d4eb0-...-8bbd649be6ef_13]
//
//     which is unreadable in an email or a document, and is what the classic client pastes.
//
// The attribution is still worth having, so it can be appended as a short reference list
// instead of being interleaved with the prose.

import { parseCitations, type CitationGroup } from './citations';
import { applyMasks, MASK_PLACEHOLDER_PATTERN, readMaskState } from './masking';
import type { ChatMessage } from './types';

/** Stands in for a redacted span, matching the `masked` chip shown in the message. */
const MASK_TEXT = '[masked]';

/**
 * A citation placeholder together with the space in front of it.
 *
 * Taking the leading space means a citation at the end of a sentence leaves no trailing
 * space, and one in the middle of a sentence leaves a single space rather than a double.
 * Kept in step with `CITATION_PLACEHOLDER` by a functional test.
 */
const CITATION_PLACEHOLDER_WITH_LEADING_SPACE = /[ \t]*\u27E6cite:\d+\u27E7/g;

export interface PlainTextOptions {
    /** Append the cited sources as a numbered list under a `Sources:` heading. */
    includeSources?: boolean;
}

/** One line of the appended reference list. */
function describeSource(group: CitationGroup): string {
    const locations = group.citations
        .map((citation) => citation.locationValue)
        .filter((value) => value !== '')
        .join(', ');
    return locations ? `${group.fileName} (${group.locationLabel}: ${locations})` : group.fileName;
}

/**
 * Render a message the way a person would want to paste it.
 *
 * Markdown is preserved: the content is already markdown, and bold, lists and headings are
 * what make a pasted answer readable. Only the machine-facing parts are removed.
 */
export function messageToPlainText(
    message: Pick<ChatMessage, 'content' | 'metadata'>,
    options: PlainTextOptions = {},
): string {
    const content = typeof message.content === 'string' ? message.content : '';
    const masks = readMaskState(message as ChatMessage);

    // A wholly masked message is withheld rather than partially cut: there is no visible
    // text to carry out of the app.
    if (masks.fullyMasked) {
        return MASK_TEXT;
    }

    const masked = applyMasks(content, masks.ranges);
    const base = masked.text.replace(MASK_PLACEHOLDER_PATTERN, MASK_TEXT);

    // parseCitations already removes the markers and hands back the groups behind them; the
    // placeholders it leaves are what the renderer swaps for chips, so they go here.
    const { text, groups } = parseCitations(base);

    let plain = text
        .replace(CITATION_PLACEHOLDER_WITH_LEADING_SPACE, '')
        // A citation that occupied a whole line leaves the line's indentation behind.
        .replace(/[ \t]+$/gm, '')
        // ...and an empty line, which would otherwise widen the gap between paragraphs.
        .replace(/\n{3,}/g, '\n\n')
        .trim();

    if (options.includeSources && groups.length > 0) {
        const lines: string[] = [];
        for (const group of groups) {
            const line = describeSource(group);
            // The same page is commonly cited several times in one answer.
            if (!lines.includes(line)) {
                lines.push(line);
            }
        }
        plain += `\n\nSources:\n${lines
            .map((line, index) => `${index + 1}. ${line}`)
            .join('\n')}`;
    }

    return plain;
}
