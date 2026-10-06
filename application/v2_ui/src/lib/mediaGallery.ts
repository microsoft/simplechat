// mediaGallery.ts
// Lays out a run of images and video clips in a reply as a gallery, three to a row.
//
// Agents that pull evidence from a remote service tend to answer with one image or clip per
// line, often under a one-line caption, and sometimes a dozen in a row. Shown one under another
// at full width, they push the rest of the reply far down the thread. This rehype plugin finds
// those runs on the parsed tree and wraps each one in a gallery the renderer shows as tiles.
//
// It works on the parsed tree for the same reason rehypeRichBlockIndex does: whether an image
// sits alone on its line depends on paragraphs, hard and soft line breaks and list items, all of
// which the parser has already decided. Each image and clip keeps its own img or a element
// inside the gallery, so react-markdown's URL transform, which runs after every rehype plugin,
// still applies to it, and the renderer still decides what a source may be.
//
// What becomes a gallery:
//   - In the body of a reply or a block quote, two or more images or clips in a row, each alone
//     on its line. A short line of text directly above a single image or clip, in the same
//     paragraph, becomes that tile's caption. A line ending in a colon that introduces several
//     images or clips stays text above the gallery.
//   - In a list item, the images and clips that end the item: a clip linked after the item's
//     last sentence, and images or clips on the lines below it. One is enough, so every item of
//     an evidence list reads the same way.
//
// A recording never joins a gallery: it plays from its own player bar, beside the text that
// describes it. Nothing is added that the markdown did not already contain.

import type { Element, ElementContent, Properties, Root, RootContent } from 'hast';
import { toText } from 'hast-util-to-text';
import { resolveImageSource } from './images';
import { inlineMediaKind, inlineMediaTitle, safeMediaUrl } from './inlineMedia';

/** Set on a gallery's wrapper. The value is the number of tiles. */
export const MEDIA_GALLERY_PROPERTY = 'dataMediaGallery';
/** Set on each image or link inside a gallery: its position among the gallery's tiles. */
export const MEDIA_TILE_PROPERTY = 'dataMediaTile';

/** The fewest images and clips that make a gallery in a reply's body. A single one keeps its card. */
export const MIN_BODY_GALLERY_ITEMS = 2;
/** The longest line taken as a caption. Anything longer reads as prose and stays text. */
export const CAPTION_MAX_LENGTH = 160;

export type GalleryMediaKind = 'image' | 'video';

export interface MediaGalleryItem {
    kind: GalleryMediaKind;
    /** The image's src or the clip's href, as react-markdown's URL transform left it. */
    src: string;
    /** The tile's caption, else the image's alt text or the clip's link text. */
    title: string;
    /** The alt or link text, when a caption line supplied the title. Empty otherwise. */
    detail: string;
}

/** Elements that end a run of lines: everything markdown renders as a block of its own. */
const BLOCK_TAGS = new Set([
    'blockquote', 'div', 'figure', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'ol', 'p', 'pre', 'section', 'table', 'ul',
]);
/** Elements whose children can hold paragraphs and lists, and so galleries. */
const CONTAINER_TAGS = new Set(['blockquote', 'li', 'ol', 'section', 'ul']);
/** Punctuation ending the sentence that a clip is linked after, at the end of a list item's line. */
const SENTENCE_END = /[.!?:;)\]\u2014\u2013-]$/;
/** Citation, mask and maths placeholders, which a plain-text title must not show raw. */
const PLACEHOLDER_PATTERN = /\u27E6(cite|mask|math):\d+\u27E7/g;

type Content = RootContent | ElementContent;

interface Paragraph {
    /** False for a tight list item's text, which markdown leaves unwrapped. */
    wrapped: boolean;
    properties: Properties;
}

interface Line {
    paragraph: Paragraph;
    nodes: ElementContent[];
}

type Piece = { kind: 'line'; line: Line } | { kind: 'node'; node: Content };

interface GalleryEntry {
    media: Element;
    caption: ElementContent[] | null;
}

function isBlank(node: Content): boolean {
    return node.type === 'comment' || (node.type === 'text' && !node.value.trim());
}

function isInlineContent(node: Content): node is ElementContent {
    return node.type !== 'doctype' && !(node.type === 'element' && BLOCK_TAGS.has(node.tagName));
}

/** Plain text for a title: placeholders stood in for and whitespace collapsed. */
function plainText(value: string): string {
    return value
        .replace(PLACEHOLDER_PATTERN, (_match, kind: string) => (kind === 'mask' ? '[masked]' : ''))
        .replace(/\s+/g, ' ')
        .replace(/ ([.,;:!?])/g, '$1')
        .trim();
}

function lineText(nodes: readonly ElementContent[]): string {
    return plainText(toText({ type: 'root', children: [...nodes] }));
}

/** Whether a node is an image or clip a gallery can hold, and which. */
export function galleryMediaKind(node: Content | undefined): GalleryMediaKind | null {
    if (node?.type !== 'element') {
        return null;
    }
    if (node.tagName === 'img') {
        const src = node.properties?.src;
        // A data URI is emptied by react-markdown's URL transform after this plugin runs, and a
        // path the app does not serve images from never loads: both keep their usual rendering.
        return typeof src === 'string' && !/^\s*data:/i.test(src) && resolveImageSource(src) ? 'image' : null;
    }
    if (node.tagName === 'a') {
        return inlineMediaKind(node.properties?.href) === 'video' ? 'video' : null;
    }
    return null;
}

/** Whether any image, or any link to audio or video, appears among the nodes. */
function containsMedia(nodes: readonly Content[]): boolean {
    return nodes.some((node) => node.type === 'element' && (
        node.tagName === 'img'
        || (node.tagName === 'a' && inlineMediaKind(node.properties?.href) !== null)
        || containsMedia(node.children)
    ));
}

function splitLines(nodes: readonly ElementContent[]): ElementContent[][] {
    const lines: ElementContent[][] = [[]];
    for (const node of nodes) {
        if (node.type === 'element' && node.tagName === 'br') {
            lines.push([]);
        } else {
            lines[lines.length - 1].push(node);
        }
    }
    return lines;
}

/** A line's nodes without the blank space at either end. */
function trimLine(nodes: readonly ElementContent[]): ElementContent[] {
    let start = 0;
    let end = nodes.length;
    while (start < end && isBlank(nodes[start])) {
        start += 1;
    }
    while (end > start && isBlank(nodes[end - 1])) {
        end -= 1;
    }
    const trimmed = nodes.slice(start, end);
    const first = trimmed[0];
    if (first?.type === 'text') {
        trimmed[0] = { ...first, value: first.value.replace(/^\s+/, '') };
    }
    const last = trimmed[trimmed.length - 1];
    if (last?.type === 'text') {
        trimmed[trimmed.length - 1] = { ...last, value: last.value.replace(/\s+$/, '') };
    }
    return trimmed;
}

/** The images and clips of a line that holds nothing else, or null. */
function lineMedia(nodes: readonly ElementContent[]): Element[] | null {
    const media: Element[] = [];
    for (const node of nodes) {
        if (isBlank(node)) {
            continue;
        }
        if (node.type !== 'element' || !galleryMediaKind(node)) {
            return null;
        }
        media.push(node);
    }
    return media.length > 0 ? media : null;
}

/** Whether a line could caption the single image or clip on the line below it. */
function isCaptionLine(nodes: readonly ElementContent[]): boolean {
    if (containsMedia(nodes)) {
        return false;
    }
    const text = lineText(nodes);
    return text.length > 0 && text.length <= CAPTION_MAX_LENGTH;
}

function endsWithColon(nodes: readonly ElementContent[]): boolean {
    return lineText(nodes).endsWith(':');
}

/** A caption line's nodes, trimmed, without the colon that labelled the image below it. */
function captionContent(nodes: readonly ElementContent[]): ElementContent[] {
    const trimmed = trimLine(nodes);
    const last = trimmed[trimmed.length - 1];
    if (last?.type === 'text' && last.value.endsWith(':')) {
        trimmed[trimmed.length - 1] = { ...last, value: last.value.slice(0, -1).replace(/\s+$/, '') };
    }
    return trimmed;
}

/** A list item line's text, and the images or clips linked after its last sentence, or null. */
function splitTrailingMedia(nodes: readonly ElementContent[]): { text: ElementContent[]; media: Element[] } | null {
    let start = nodes.length;
    for (let index = nodes.length - 1; index >= 0; index -= 1) {
        const node = nodes[index];
        if (isBlank(node)) {
            continue;
        }
        if (!galleryMediaKind(node)) {
            break;
        }
        start = index;
    }
    const media: Element[] = [];
    for (const node of nodes.slice(start)) {
        if (node.type === 'element') {
            media.push(node);
        }
    }
    const text = nodes.slice(0, start);
    // Linked mid-sentence ("compare [this clip](a.mp4) with [that one](b.mp4)") stays where it is.
    if (media.length === 0 || !SENTENCE_END.test(lineText(text))) {
        return null;
    }
    return { text: trimLine(text), media };
}

/** The text a tile is called by when no caption line names it: alt text, or the link's text. */
function ownTitle(media: Element, kind: GalleryMediaKind): string {
    if (kind === 'image') {
        return plainText(String(media.properties?.alt ?? ''));
    }
    const href = String(media.properties?.href ?? '');
    return plainText(inlineMediaTitle(toText(media), safeMediaUrl(href) ?? href));
}

function buildGallery(entries: readonly GalleryEntry[]): Element {
    return {
        type: 'element',
        tagName: 'div',
        properties: { [MEDIA_GALLERY_PROPERTY]: entries.length },
        children: entries.map(({ media, caption }, index): Element => {
            const kind = galleryMediaKind(media) ?? 'image';
            media.properties = { ...media.properties, [MEDIA_TILE_PROPERTY]: index };
            const captionNodes: ElementContent[] = caption
                ? captionContent(caption)
                : [{ type: 'text', value: ownTitle(media, kind) }];
            const hasCaption = captionNodes.some((node) => !isBlank(node));
            return {
                type: 'element',
                tagName: 'figure',
                properties: { dataMediaKind: kind },
                children: hasCaption
                    ? [media, { type: 'element', tagName: 'figcaption', properties: {}, children: captionNodes }]
                    : [media],
            };
        }),
    };
}

/** A container's children as lines of its paragraphs, and every other node as it is. */
function readPieces(children: readonly Content[], listItem: boolean): Piece[] {
    const pieces: Piece[] = [];
    let inline: ElementContent[] = [];
    const addLines = (nodes: readonly ElementContent[], paragraph: Paragraph) => {
        for (const line of splitLines(nodes)) {
            pieces.push({ kind: 'line', line: { paragraph, nodes: line } });
        }
    };
    const flushInline = () => {
        // A tight list item's text is not wrapped in a paragraph; it is read as one all the same.
        if (inline.some((node) => !isBlank(node))) {
            addLines(inline, { wrapped: false, properties: {} });
        } else {
            pieces.push(...inline.map((node): Piece => ({ kind: 'node', node })));
        }
        inline = [];
    };
    for (const child of children) {
        if (child.type === 'element' && child.tagName === 'p') {
            flushInline();
            addLines(child.children, { wrapped: true, properties: child.properties });
        } else if (listItem && isInlineContent(child)) {
            inline.push(child);
        } else {
            flushInline();
            pieces.push({ kind: 'node', node: child });
        }
    }
    flushInline();
    return pieces;
}

/** Put the pieces back together, rebuilding each paragraph from the lines it still has. */
function rebuild(pieces: readonly Piece[]): Content[] {
    const children: Content[] = [];
    let index = 0;
    while (index < pieces.length) {
        const piece = pieces[index];
        if (piece.kind === 'node') {
            children.push(piece.node);
            index += 1;
            continue;
        }
        const { paragraph } = piece.line;
        const joined: ElementContent[] = [];
        while (index < pieces.length) {
            const current = pieces[index];
            if (current.kind !== 'line' || current.line.paragraph !== paragraph) {
                break;
            }
            if (joined.length > 0) {
                joined.push({ type: 'element', tagName: 'br', properties: {}, children: [] });
            }
            joined.push(...current.line.nodes);
            index += 1;
        }
        const content = trimLine(joined);
        if (!content.some((node) => !isBlank(node))) {
            continue;
        }
        if (paragraph.wrapped) {
            children.push({ type: 'element', tagName: 'p', properties: paragraph.properties, children: content });
        } else {
            children.push(...content);
        }
    }
    return children;
}

/** Wrap the container's runs of images and clips in galleries. Leaves it untouched if there are none. */
function regroup(parent: Root | Element, listItem: boolean): void {
    const minimum = listItem ? 1 : MIN_BODY_GALLERY_ITEMS;
    const sequence = readPieces(parent.children, listItem);
    const pieces: Piece[] = [];
    let entries: GalleryEntry[] = [];
    let consumed: Piece[] = [];
    let grouped = false;

    const flush = (): boolean => {
        const formed = entries.length >= minimum;
        if (formed) {
            pieces.push({ kind: 'node', node: buildGallery(entries) });
        } else {
            pieces.push(...consumed);
        }
        entries = [];
        consumed = [];
        return formed;
    };

    for (let index = 0; index < sequence.length; index += 1) {
        const piece = sequence[index];
        if (piece.kind === 'node') {
            if (isBlank(piece.node)) {
                // Space between blocks neither ends a run nor shows once a run becomes a gallery.
                (entries.length > 0 ? consumed : pieces).push(piece);
                continue;
            }
            grouped = flush() || grouped;
            pieces.push(piece);
            continue;
        }

        const { line } = piece;
        const media = lineMedia(line.nodes);
        if (media) {
            entries.push(...media.map((node) => ({ media: node, caption: null })));
            consumed.push(piece);
            continue;
        }

        // A list item's text describes the item, so it is never taken as one tile's caption.
        const next = sequence[index + 1];
        if (!listItem && next?.kind === 'line' && next.line.paragraph === line.paragraph && isCaptionLine(line.nodes)) {
            const captioned = lineMedia(next.line.nodes);
            // "Stills from both cameras:" over two images introduces them; over one, it labels it.
            const after = sequence[index + 2];
            const introducesMore = endsWithColon(line.nodes) && after?.kind === 'line'
                && after.line.paragraph === line.paragraph && lineMedia(after.line.nodes) !== null;
            if (captioned?.length === 1 && !introducesMore) {
                entries.push({ media: captioned[0], caption: line.nodes });
                consumed.push(piece, next);
                index += 1;
                continue;
            }
        }

        grouped = flush() || grouped;
        const trailing = listItem ? splitTrailingMedia(line.nodes) : null;
        if (trailing) {
            pieces.push({ kind: 'line', line: { paragraph: line.paragraph, nodes: trailing.text } });
            entries.push(...trailing.media.map((node) => ({ media: node, caption: null })));
            consumed.push({ kind: 'line', line: { paragraph: line.paragraph, nodes: trailing.media } });
            continue;
        }
        pieces.push(piece);
    }
    grouped = flush() || grouped;

    if (grouped) {
        parent.children = rebuild(pieces) as typeof parent.children;
    }
}

function regroupTree(parent: Root | Element): void {
    for (const child of parent.children) {
        if (child.type === 'element' && CONTAINER_TAGS.has(child.tagName)) {
            regroupTree(child);
        }
    }
    if (parent.type === 'root' || parent.tagName === 'blockquote') {
        regroup(parent, false);
    } else if (parent.tagName === 'li') {
        regroup(parent, true);
    }
}

/** Wrap each run of images and clips in a gallery. */
export function rehypeMediaGallery() {
    return (tree: Root) => {
        regroupTree(tree);
    };
}

/** A media element's position in its gallery, or null when it is not in one. */
export function readMediaTileIndex(node: Element | undefined): number | null {
    const value = node?.properties?.[MEDIA_TILE_PROPERTY];
    return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null;
}

/** The tiles of a gallery this plugin built, in order, or null for any other element. */
export function readMediaGallery(node: Element | undefined): MediaGalleryItem[] | null {
    if (node?.tagName !== 'div' || node.properties?.[MEDIA_GALLERY_PROPERTY] === undefined) {
        return null;
    }
    const items: MediaGalleryItem[] = [];
    for (const figure of node.children) {
        if (figure.type !== 'element' || figure.tagName !== 'figure') {
            continue;
        }
        const media = figure.children.find(
            (child): child is Element => child.type === 'element' && readMediaTileIndex(child) !== null,
        );
        if (!media) {
            continue;
        }
        const caption = figure.children.find(
            (child): child is Element => child.type === 'element' && child.tagName === 'figcaption',
        );
        const kind: GalleryMediaKind = media.tagName === 'img' ? 'image' : 'video';
        const own = ownTitle(media, kind);
        const title = (caption ? plainText(toText(caption)) : '') || own || (kind === 'image' ? 'Image' : 'Video');
        items.push({
            kind,
            src: String((kind === 'image' ? media.properties?.src : media.properties?.href) ?? ''),
            title,
            detail: own && own !== title ? own : '',
        });
    }
    return items;
}
