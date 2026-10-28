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

import { isM365CitationId } from './m365Citations';
import { literalCodeRegions } from './promptVariables';
import type { HybridCitation } from './types';

/** How a citation resolves, which determines what clicking it should do. */
export type CitationKind = 'document' | 'web' | 'agent' | 'm365';

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

const RAW_DOCUMENT_MARKER =
    /\u3010\s*#?([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}_[a-z0-9_.-]{1,128})\s*\u3011/gi;

/** A bare `[#id]` run left over when a marker was emitted without its Source prefix. */
const ORPHAN_BRACKET_RUN = /(?:[ \t]*\[#[^\]]*\])+/g;

/** A bare run of Microsoft 365 ids, which still resolve to a chip because the id names the item. */
const ORPHAN_M365_RUN = /(?:[ \t]*\[#\s*m365-[0-9a-f]{16}\s*\])+/g;

const M365_ID = /m365-[0-9a-f]{16}/g;

function documentFileNames(records: readonly HybridCitation[]): Map<string, string | null> {
    const names = new Map<string, string | null>();
    if (!Array.isArray(records)) {
        return names;
    }
    for (const record of records) {
        if (typeof record?.citation_id !== 'string' || typeof record?.file_name !== 'string') {
            continue;
        }
        const id = record.citation_id.trim().replace(/^#/, '');
        const name = record.file_name.trim();
        if (!id || !name || isM365CitationId(id)) {
            continue;
        }
        // Conflicting records cannot safely identify the source, even if one repeats later.
        names.set(id, names.has(id) && names.get(id) !== name ? null : name);
    }
    return names;
}

function rawDocumentSources(records: readonly HybridCitation[]): Map<string, CitationGroup | null> {
    const sources = new Map<string, CitationGroup | null>();
    for (const record of Array.isArray(records) ? records : []) {
        if (typeof record?.citation_id !== 'string' || typeof record?.file_name !== 'string') continue;
        const id = record.citation_id.trim().replace(/^#/, '');
        const fileName = record.file_name.trim();
        if (!id || !fileName) continue;
        const location = record.location_value ?? record.sheet_name ?? record.page_number;
        const locationValue = typeof location === 'string' || typeof location === 'number' && Number.isFinite(location) ? String(location) : '';
        const source: CitationGroup = {
            id: '',
            kind: 'document',
            fileName,
            locationLabel: typeof record.location_label === 'string' && record.location_label.trim()
                ? record.location_label : typeof record.sheet_name === 'string' ? 'Sheet' : record.page_number != null ? 'Page' : 'Location',
            citations: [{
                citationId: id,
                documentId: typeof record.document_id === 'string' ? record.document_id : splitCitationId(id).documentId,
                pageNumber: typeof record.page_number === 'string' || typeof record.page_number === 'number' ? String(record.page_number) : '',
                locationValue,
            }],
        };
        // A later matching duplicate must not undo an earlier conflicting source.
        sources.set(id, sources.has(id) && JSON.stringify(sources.get(id)) !== JSON.stringify(source) ? null : source);
    }
    return sources;
}

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

function classify(fileName: string, citations: ParsedCitation[]): CitationKind {
    // A Microsoft 365 item is recognised by the id the server minted, never by the label the
    // model copied, because the label is free text and the id is not.
    if (citations.length > 0 && citations.every((citation) => isM365CitationId(citation.citationId))) {
        return 'm365';
    }
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
export function parseCitations(
    message: string,
    documentCitations: readonly HybridCitation[] = [],
): ParsedMessage {
    const groups: CitationGroup[] = [];
    const fileNames = documentFileNames(documentCitations);
    const rawSources = rawDocumentSources(documentCitations);
    const codeRegions = message.includes('\u3010') ? literalCodeRegions(message) : [];
    const markers = new RegExp(`${CITATION_MARKER.source}|${RAW_DOCUMENT_MARKER.source}`, 'gi');

    let text = message.replace(
        markers,
        (whole, fileName: string, locationLabel: string, locations: string, brackets: string, rawId: string | undefined, offset: number) => {
            if (rawId) {
                if (codeRegions.some((region) => offset >= region.start && offset < region.end)) return whole;
                const source = rawSources.get(rawId);
                if (!source) return '[Source unavailable]';
                const index = groups.length;
                groups.push({ ...source, id: `cite-${index}` });
                return CITATION_PLACEHOLDER(index);
            }
            // The bracket group's trailing `\s*` swallows whatever followed the last
            // `[#id]`, which is usually the blank line separating the citation from the
            // next markdown block. Dropping it merges that block into the citation's
            // paragraph, so bullet lists and line breaks after a citation stop working.
            // Captured here and restored below, as chat-citations.js does.
            const trailingWhitespace = /\s*$/.exec(brackets)?.[0] ?? '';
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
                // Nothing resolvable; drop the marker but keep the structure around it.
                return trailingWhitespace;
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

            const kind = classify(fileName, citations);
            let displayName = fileName.trim();
            if (kind === 'document' && /^untitled(?:\s+document)?$/i.test(fileName.trim())) {
                const names = citations.map((citation) => fileNames.get(citation.citationId) || displayName);
                if (new Set(names).size > 1) {
                    const replacements: string[] = [];
                    citations.forEach((citation, index) => {
                        const groupIndex = groups.length;
                        groups.push({
                            id: `cite-${groupIndex}`,
                            kind,
                            fileName: names[index],
                            locationLabel,
                            citations: [citation],
                        });
                        replacements.push(CITATION_PLACEHOLDER(groupIndex));
                    });
                    return `${replacements.join(' ')}${trailingWhitespace}`;
                }
                displayName = names[0];
            }

            const groupIndex = groups.length;
            groups.push({
                id: `cite-${groupIndex}`,
                kind,
                fileName: displayName,
                locationLabel,
                citations,
            });

            return `${CITATION_PLACEHOLDER(groupIndex)}${trailingWhitespace}`;
        },
    );

    // A Microsoft 365 id copied without its Source prefix still names one item exactly, so it
    // becomes a chip rather than being dropped with the other orphaned ids.
    text = text.replace(ORPHAN_M365_RUN, (run: string) => {
        const ids = [...new Set(run.match(M365_ID) ?? [])];
        const groupIndex = groups.length;
        groups.push({
            id: `cite-${groupIndex}`,
            kind: 'm365',
            fileName: '',
            locationLabel: 'Location',
            citations: ids.map((citationId) => ({
                citationId,
                locationValue: '',
                documentId: citationId,
                pageNumber: '',
            })),
        });
        return `${/^[ \t]/.test(run) ? ' ' : ''}${CITATION_PLACEHOLDER(groupIndex)}`;
    });

    // Any bracket run that survives had no Source prefix to give it meaning, so it is
    // removed rather than shown to the user as raw ids.
    text = text.replace(ORPHAN_BRACKET_RUN, '');

    // Collapse runs of blank lines, matching the classic UI's `\n{3,}` -> `\n\n`. With
    // remark-breaks enabled every newline becomes a line break, so an unclipped run of
    // blank lines would otherwise open a large gap in the middle of an answer.
    text = text.replace(/\n{3,}/g, '\n\n');

    return { text, groups };
}
