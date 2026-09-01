// citations.ts
// Parse SimpleChat citation markers out of assistant text.
//
// The model emits citations as a trailing marker after the sentence they support:
//
//   (Source: Q3 Risk Register.xlsx, Page: 3, 4) [#docid_3] [#docid_4]
//
// The grammar is taken from chat-citations.js:45 so V2 recognises exactly what the
// existing interface does. Left unparsed, these markers render as literal noise in the
// middle of an answer.

/** How a citation resolves, which determines what clicking it should do. */
export type CitationKind = 'document' | 'web' | 'agent';

export interface ParsedCitation {
    /** Full citation id, conventionally `${documentId}_${pageNumber}`. */
    citationId: string;
    /** The location token this reference is for: a page number, sheet name or label. */
    locationValue: string;
    documentId: string;
    pageNumber: string;
}

export interface CitationGroup {
    /** Stable id used to key the rendered chip. */
    id: string;
    kind: CitationKind;
    /** File name, or the URL itself for a web citation. */
    fileName: string;
    /** 'Page', 'Pages', 'Sheet', 'Location' — as emitted. */
    locationLabel: string;
    citations: ParsedCitation[];
}

/**
 * Matches one citation marker.
 *
 * The inner `(?!\(Source:)` guards stop a single match from swallowing a following
 * citation when two appear back to back.
 */
const CITATION_MARKER =
    /\(Source:\s*((?:(?!\(Source:).)+?),\s*(Page(?:s)?|Sheet(?:s)?|Location):\s*((?:(?!\(Source:).)+?)\)\s*((?:\[#.*?\]\s*)+)/gi;

/** A bare `[#id]` run left over when a marker was emitted without its Source prefix. */
const ORPHAN_BRACKET_RUN = /(?:[ \t]*\[#[^\]]*\])+/g;

function splitCitationId(rawId: string): ParsedCitation {
    const citationId = rawId.startsWith('#') ? rawId.slice(1) : rawId;
    const separator = citationId.lastIndexOf('_');
    return {
        citationId,
        locationValue: '',
        documentId: separator === -1 ? citationId : citationId.slice(0, separator),
        pageNumber: separator === -1 ? '' : citationId.slice(separator + 1),
    };
}

function classify(fileName: string): CitationKind {
    if (/^https?:\/\//i.test(fileName.trim())) {
        return 'web';
    }
    // Agent citations are emitted with an explicit prefix by the agent citation builder.
    if (/^agent:/i.test(fileName.trim())) {
        return 'agent';
    }
    return 'document';
}

export interface ParsedMessage {
    /** Text with markers replaced by placeholders of the form `⟦cite:N⟧`. */
    text: string;
    groups: CitationGroup[];
}

/**
 * Placeholder token substituted for each marker.
 *
 * Uses characters that will not appear in ordinary prose or be transformed by the
 * markdown pipeline, so the chip can be swapped back in after rendering.
 */
export const CITATION_PLACEHOLDER = (index: number) => `\u27E6cite:${index}\u27E7`;

export const CITATION_PLACEHOLDER_PATTERN = /\u27E6cite:(\d+)\u27E7/g;

/**
 * Replace citation markers with placeholders and return the citation groups.
 *
 * Returning placeholders rather than HTML keeps the markdown renderer in charge of the
 * surrounding text and avoids injecting raw HTML into model output.
 */
export function parseCitations(message: string): ParsedMessage {
    const groups: CitationGroup[] = [];

    let text = message.replace(
        CITATION_MARKER,
        (_whole, fileName: string, locationLabel: string, locations: string, brackets: string) => {
            const ids = brackets.match(/\[#.*?\]/g) ?? [];

            const citations: ParsedCitation[] = [];
            for (const bracket of ids) {
                // A single bracket may carry several ids separated by ; or ,
                const inner = bracket.slice(2, -1).trim();
                for (const part of inner.split(/[;,]/)) {
                    const trimmed = part.trim();
                    if (trimmed) {
                        citations.push(splitCitationId(trimmed));
                    }
                }
            }

            if (citations.length === 0) {
                // Nothing resolvable; drop the marker rather than leaving raw text behind.
                return '';
            }

            const normalizedLabel = locationLabel.toLowerCase();
            // Pages come as a comma-separated list that lines up with the ids; sheet and
            // location are single opaque tokens.
            const tokens = normalizedLabel.startsWith('page')
                ? locations.split(',').map((token) => token.trim())
                : [locations.trim()];

            citations.forEach((citation, index) => {
                citation.locationValue = tokens[index] ?? citation.pageNumber ?? '';
            });

            const groupIndex = groups.length;
            groups.push({
                id: `cite-${groupIndex}`,
                kind: classify(fileName),
                fileName: fileName.trim(),
                locationLabel,
                citations,
            });

            return CITATION_PLACEHOLDER(groupIndex);
        },
    );

    // Any bracket run that survives had no Source prefix to give it meaning, so it is
    // removed rather than shown to the user as raw ids.
    text = text.replace(ORPHAN_BRACKET_RUN, '');

    // Collapse runs of blank lines, matching the classic UI's `\n{3,}` -> `\n\n`. With
    // remark-breaks enabled every newline becomes a line break, so an unclipped run of
    // blank lines would otherwise open a large gap in the middle of an answer.
    text = text.replace(/\n{3,}/g, '\n\n');

    return { text, groups };
}
