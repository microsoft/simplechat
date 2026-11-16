// WebCitationCards.tsx
// Web IQ media is linked to its source, never played as an arbitrary hosted page.

import { createContext, useContext, useState } from 'react';
import { ExternalLink, Image, Video } from 'lucide-react';
import { citedWebMedia, safeWebSourceUrl, webSourcePreview, webSourceProviderLabel } from '../../lib/webCitations';
import type { WebCitation } from '../../lib/types';

const WebSources = createContext<readonly WebCitation[]>([]);

export function WebCitationProvider({ citations, children }: {
    citations?: WebCitation[];
    children: React.ReactNode;
}) {
    return <WebSources.Provider value={citations ?? []}>{children}</WebSources.Provider>;
}

export function useWebCitation(url: string): WebCitation | undefined {
    const citations = useContext(WebSources);
    return citations.find((citation) => safeWebSourceUrl(citation.url) === safeWebSourceUrl(url));
}

export function useWebCitations(): readonly WebCitation[] {
    return useContext(WebSources);
}

export function WebProviderBadge({ citation }: { citation: WebCitation }) {
    const label = webSourceProviderLabel(citation);
    if (!label) return null;
    return <span className="shrink-0 rounded border border-edge px-1 py-0.5 text-[10px] font-medium text-text-3">{label}</span>;
}

function WebMediaCard({ citation }: { citation: WebCitation }) {
    const [failed, setFailed] = useState(false);
    const preview = webSourcePreview(citation);
    const title = citation.title?.trim() || citation.url || 'Web source';
    const video = citation.source_kind === 'video';
    const Icon = video ? Video : Image;
    const publisher = typeof citation.publisher === 'string' ? citation.publisher.trim().slice(0, 200) : '';
    const duration = typeof citation.duration === 'string' ? citation.duration.trim().slice(0, 40) : '';
    const moments = video && Array.isArray(citation.moments)
        ? citation.moments.filter((moment) => moment && safeWebSourceUrl(moment.url)).slice(0, 5) : [];
    return (
        <article className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-edge bg-surface-1">
            <a href={safeWebSourceUrl(citation.url)} target="_blank" rel="noopener noreferrer"
                className="min-w-0 flex-1 transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent"
                aria-label={`${title} — open ${video ? 'video' : 'image'} source in a new tab`}>
            {preview && !failed && (
                <img src={preview} alt="" loading="lazy" referrerPolicy="no-referrer"
                    onError={() => setFailed(true)} className="aspect-video w-full object-cover" />
            )}
            <div className="space-y-2 p-3">
                <div className="flex items-center gap-1.5 text-[11px] text-text-3">
                    <Icon size={13} aria-hidden="true" />
                    <span>{video ? 'Video' : 'Image'} source</span>
                    <WebProviderBadge citation={citation} />
                </div>
                <p className="line-clamp-2 text-sm font-medium text-text-1">{title}</p>
                {(publisher || duration) && <p className="text-[11px] text-text-3">{[publisher, duration].filter(Boolean).join(' · ')}</p>}
                {citation.description && <p className="line-clamp-3 text-xs leading-relaxed text-text-2">{citation.description}</p>}
                <span className="flex items-center gap-1 text-xs text-accent">Open source <ExternalLink size={12} aria-hidden="true" /></span>
            </div>
            </a>
            {moments.length > 0 && (
                <ul aria-label="Video moments" className="space-y-1 border-t border-edge px-3 py-2">
                    {moments.map((moment, index) => (
                        <li key={`${moment.url}:${index}`}>
                            <a href={safeWebSourceUrl(moment.url)} target="_blank" rel="noopener noreferrer"
                                className="text-xs text-accent hover:underline">
                                {typeof moment.start_time === 'string' && <span className="mr-1 text-text-3">{moment.start_time.slice(0, 30)}</span>}
                                {typeof moment.title === 'string' ? moment.title.slice(0, 200) : `Moment ${index + 1}`}
                            </a>
                        </li>
                    ))}
                </ul>
            )}
        </article>
    );
}

export function WebCitationCards({ citations }: { citations?: WebCitation[] }) {
    const media = citedWebMedia(citations);
    if (!media.length) return null;
    return (
        <section aria-label="Cited web media" className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {media.map((citation) => <WebMediaCard key={`${citation.source_kind}:${citation.url}`} citation={citation} />)}
        </section>
    );
}

export function WebCitationLinks({ citations }: { citations?: WebCitation[] }) {
    const sources = (citations ?? []).filter((citation) => citation.provider === 'web_iq'
        && citation.delivery_mode === 'text_only' && citation.cited !== false
        && ['image', 'video'].includes(citation.source_kind ?? '') && safeWebSourceUrl(citation.url));
    if (!sources.length) return null;
    return (
        <section aria-label="Cited web source links" className="mt-3">
            <ul className="space-y-2">
                {sources.map((citation, index) => (
                    <li key={`${citation.url}:${index}`} className="text-sm">
                        <a href={safeWebSourceUrl(citation.url)} target="_blank" rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 text-accent hover:underline">
                            {citation.title || citation.url}
                            <ExternalLink size={12} aria-hidden="true" />
                            <WebProviderBadge citation={citation} />
                        </a>
                        {citation.description && <p className="mt-1 text-xs text-text-2">{citation.description}</p>}
                    </li>
                ))}
            </ul>
        </section>
    );
}
