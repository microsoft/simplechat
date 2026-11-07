// webCitations.ts
// Persisted, answer-selected web sources; never configuration or raw retrieval runs.

import type { WebCitation } from './types';
import type { Root, RootContent } from 'hast';

export function safeWebSourceUrl(value: unknown): string {
    if (typeof value !== 'string' || /[\u0000-\u0020\\]/.test(value)) return '';
    try {
        const url = new URL(value);
        return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : '';
    } catch {
        return '';
    }
}

export function webSourceProviderLabel(citation: WebCitation): string {
    return citation.provider === 'web_iq' && citation.source_type !== 'source_review'
        ? 'Web IQ' : '';
}

export function citedWebMedia(citations: readonly WebCitation[] | undefined): WebCitation[] {
    const seen = new Set<string>();
    return (Array.isArray(citations) ? citations : []).filter((citation) => {
        if (!citation || citation.provider !== 'web_iq' || citation.cited === false
            || !['image', 'video'].includes(citation.source_kind ?? '')
            || citation.delivery_mode !== 'with_media'
            || !safeWebSourceUrl(citation.url)) return false;
        const key = `${citation.source_kind}:${citation.url}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}

export function webSourcePreview(citation: WebCitation): string {
    if (citation.delivery_mode !== 'with_media') return '';
    if (citation.source_kind === 'image') {
        return safeWebPreviewUrl(citation.image_url) || safeWebPreviewUrl(citation.thumbnail_url);
    }
    if (citation.source_kind === 'video') return safeWebPreviewUrl(citation.thumbnail_url);
    return '';
}

export function safeWebPreviewUrl(value: unknown): string {
    const source = safeWebSourceUrl(value);
    if (!source) return '';
    const url = new URL(source);
    const host = url.hostname.toLowerCase().replace(/\.+$/, '');
    if (url.protocol !== 'https:' || host.startsWith('[') || /^\d+\.\d+\.\d+\.\d+$/.test(host)
        || !host.includes('.') || host === 'localhost' || host.endsWith('.localhost')
        || host.endsWith('.local') || host.endsWith('.internal')) return '';
    return source;
}

export const WEB_SOURCE_LINK_PROPERTY = 'dataWebSourceLink';

export function rehypeWebCitationMedia(options: { citations: readonly WebCitation[] }) {
    return (tree: Root) => {
        const sources = new Map<string, WebCitation>();
        for (const citation of options.citations) {
            if (citation.provider !== 'web_iq' || !['image', 'video'].includes(citation.source_kind ?? '')
                || !['text_only', 'with_media'].includes(citation.delivery_mode ?? '')) continue;
            for (const value of [citation.url, citation.image_url, citation.thumbnail_url, citation.video_url]) {
                const url = safeWebSourceUrl(value);
                if (url) sources.set(url, citation);
            }
        }
        function visit(nodes: RootContent[]) {
            for (const node of nodes) {
                if (node.type !== 'element') continue;
                if (node.tagName === 'img' || node.tagName === 'a') {
                    const value = node.properties[node.tagName === 'img' ? 'src' : 'href'];
                    const citation = sources.get(safeWebSourceUrl(value));
                    const source = safeWebSourceUrl(citation?.url);
                    if (citation && source) {
                        if (node.tagName === 'img') {
                            node.tagName = 'a';
                            node.children = [{ type: 'text', value: citation.title || String(node.properties.alt || 'Image source') }];
                        }
                        node.properties = { href: source, [WEB_SOURCE_LINK_PROPERTY]: true };
                    }
                }
                visit(node.children);
            }
        }
        visit(tree.children);
    };
}
