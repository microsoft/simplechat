// InlineVideoCard.tsx
// A video clip linked in a chat message, played in place.
//
// The browser's own controls are used (play, seek, volume, fullscreen and picture-in-picture):
// they are accessible and familiar, and a clip needs nothing they lack. The card adds the
// clip's title and a way to open it in a new tab. Starting a clip pauses any other inline
// recording or clip, so two never play at once.

import { useState } from 'react';
import { ExternalLink, Film } from 'lucide-react';
import { claimPlayback, safeMediaUrl } from '../../lib/inlineMedia';
import { InlineMediaFallback } from './InlineMediaFallback';

export function InlineVideoCard({ src, title }: { src: string; title: string }) {
    const [failed, setFailed] = useState(false);

    if (failed) {
        return <InlineMediaFallback kind="video" src={src} title={title} />;
    }

    return (
        <span className="my-2 block w-full max-w-2xl overflow-hidden rounded-xl border border-edge bg-black">
            <video
                src={safeMediaUrl(src) ?? undefined}
                controls
                preload="metadata"
                playsInline
                aria-label={title}
                onPlay={(event) => claimPlayback(event.currentTarget)}
                onError={() => setFailed(true)}
                className="block max-h-[26rem] w-full bg-black"
            />
            <span className="flex items-center gap-2 bg-surface-sunken px-3 py-1.5 text-xs text-text-2">
                <Film size={13} className="shrink-0 text-text-3" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate" title={title}>
                    {title}
                </span>
                <a
                    href={safeMediaUrl(src) ?? undefined}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`Open ${title} in a new tab`}
                    title="Open in a new tab"
                    className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                >
                    <ExternalLink size={12} aria-hidden="true" />
                    Open
                </a>
            </span>
        </span>
    );
}
