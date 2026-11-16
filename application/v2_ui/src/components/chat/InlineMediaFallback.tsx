// InlineMediaFallback.tsx
// What an inline audio or video player, or the media viewer, turns into when its media cannot
// be played or shown here.
//
// A signed link that has expired, a host the page's content security policy does not allow, or
// a format the browser cannot decode all end the same way: the link is still useful, so it is
// shown as a link with a short reason rather than as a broken player.

import { ExternalLink } from 'lucide-react';
import { safeMediaUrl } from '../../lib/inlineMedia';

const WHAT: Record<'audio' | 'video' | 'image', string> = {
    audio: 'This recording can\u2019t be played here.',
    video: 'This video can\u2019t be played here.',
    image: 'This image can\u2019t be shown here.',
};

export function InlineMediaFallback({ kind, src, title }: { kind: 'audio' | 'video' | 'image'; src: string; title: string }) {
    return (
        <span className="my-2 block max-w-xl rounded-xl border border-edge bg-surface-sunken px-3 py-2 text-sm text-text-2">
            <span className="block">
                {WHAT[kind]} The link may have expired or its host may not be allowed.
            </span>
            <a
                href={safeMediaUrl(src) ?? undefined}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1 inline-flex items-center gap-1.5 font-medium text-accent underline"
            >
                <ExternalLink size={13} aria-hidden="true" />
                {title}
            </a>
        </span>
    );
}
