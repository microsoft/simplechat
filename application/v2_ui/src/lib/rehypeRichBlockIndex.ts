// rehypeRichBlockIndex.ts
// Numbers the diagram and chart fences in a message, in document order.
//
// The number is what a saved colour choice is filed under, so getting it wrong means showing
// one block in another block's colours, or overwriting one block's saved entry with another's.
//
// It is stamped onto the parsed tree rather than derived by scanning the markdown text.
// Scanning looked simpler, but a fence's *textual* position does not identify it: CommonMark
// admits fences nested in list items at four or more spaces of indentation and fences behind a
// blockquote's `>` prefix, and a scanner recognising neither would leave those blocks
// unnumbered and colliding with block zero. Walking the tree the renderer is about to render
// has no such gaps, because it is the parser's own answer to what a code block is.

import { visit } from 'unist-util-visit';
import type { Element, Root } from 'hast';
import {
    IMAGE_PROPOSAL_LANGUAGE,
    INLINE_CHART_LANGUAGE,
    MERMAID_LANGUAGE,
    readPendingKind,
} from './richBlocks';

/**
 * The hast property the index is stamped on.
 *
 * A `data-` property, so that in the event a rich fence is ever rendered as an ordinary code
 * block it degrades to a harmless attribute rather than a React warning.
 */
export const RICH_BLOCK_INDEX_PROPERTY = 'dataScBlockIndex';

/**
 * Fences that render as something other than a code block.
 *
 * Every one is numbered, even though only diagrams and charts currently have colours saved
 * against them: the numbering is per kind, so an image proposal costs nothing and the same
 * function answers both "is this a rich fence" and "which one is it".
 */
const RICH_LANGUAGES = new Set<string>([
    MERMAID_LANGUAGE,
    INLINE_CHART_LANGUAGE,
    IMAGE_PROPOSAL_LANGUAGE,
]);

/** Read the `language-xxx` class a fenced code block carries. */
export function readFenceLanguage(className: unknown): string {
    const classes = Array.isArray(className) ? className.join(' ') : String(className ?? '');
    for (const entry of classes.split(/\s+/)) {
        if (entry.startsWith('language-')) {
            return entry.slice('language-'.length).toLowerCase();
        }
    }
    return '';
}

/**
 * The rich kind a code element holds, or null when it is an ordinary code block.
 *
 * A placeholder standing in for a fence that is still streaming reports the kind it will
 * become, so numbering does not shift when the fence completes.
 */
export function richFenceKind(node: Element | undefined): string | null {
    if (!node || node.tagName !== 'code') {
        return null;
    }
    const language = readFenceLanguage(node.properties?.className);
    const kind = readPendingKind(language) ?? language;
    return RICH_LANGUAGES.has(kind) ? kind : null;
}

/** Read the index stamped by the plugin, or null when there is none. */
export function readRichBlockIndex(node: Element | undefined): number | null {
    const value = node?.properties?.[RICH_BLOCK_INDEX_PROPERTY];
    return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null;
}

/** Stamp each diagram and chart fence with its position among fences of the same kind. */
export function rehypeRichBlockIndex() {
    return (tree: Root) => {
        const counts = new Map<string, number>();

        visit(tree, 'element', (node: Element) => {
            const kind = richFenceKind(node);
            if (kind === null) {
                return;
            }
            const next = counts.get(kind) ?? 0;
            counts.set(kind, next + 1);
            node.properties = {
                ...(node.properties ?? {}),
                [RICH_BLOCK_INDEX_PROPERTY]: next,
            };
        });
    };
}
