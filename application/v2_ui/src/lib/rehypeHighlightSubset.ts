// rehypeHighlightSubset.ts
// Syntax highlighting for fenced code blocks, restricted to a curated language set.
//
// This exists instead of `rehype-highlight` because that package statically imports
// lowlight's `common` bundle (~37 grammars) as its default, so the grammars end up in the
// bundle even when a smaller `languages` option is passed. Building the lowlight instance
// directly keeps only the languages listed in ./highlight.

import { createLowlight } from 'lowlight';
import { toText } from 'hast-util-to-text';
import { visit } from 'unist-util-visit';
import type { Element, ElementContent, Root } from 'hast';
import { highlightLanguages } from './highlight';

const lowlight = createLowlight(highlightLanguages);
const registeredLanguages = new Set(Object.keys(highlightLanguages));

/** Read the language from a `language-xxx` class, as produced by fenced code blocks. */
function readLanguage(node: Element): string | undefined {
    const className = node.properties?.className;
    const classes = Array.isArray(className) ? className : [];

    for (const entry of classes) {
        const value = String(entry);
        if (value.startsWith('language-')) {
            return value.slice('language-'.length).toLowerCase();
        }
        if (value.startsWith('lang-')) {
            return value.slice('lang-'.length).toLowerCase();
        }
    }

    return undefined;
}

export function rehypeHighlightSubset() {
    return function transform(tree: Root) {
        visit(tree, 'element', (node: Element, _index, parent) => {
            if (
                node.tagName !== 'code' ||
                !parent ||
                parent.type !== 'element' ||
                (parent as Element).tagName !== 'pre'
            ) {
                return;
            }

            const language = readLanguage(node);

            // Unlabelled or unsupported blocks render as plain preformatted text rather
            // than being auto-detected, which avoids mislabelled highlighting on prose.
            if (!language || !registeredLanguages.has(language)) {
                return;
            }

            if (!Array.isArray(node.properties.className)) {
                node.properties.className = [];
            }
            if (!node.properties.className.includes('hljs')) {
                node.properties.className.unshift('hljs');
            }

            try {
                const result = lowlight.highlight(language, toText(node, { whitespace: 'pre' }));
                if (result.children.length > 0) {
                    node.children = result.children as ElementContent[];
                }
            } catch {
                // Highlighting is cosmetic: a grammar failure must never blank out the
                // code the user is trying to read.
            }
        });
    };
}
