// MediaTiles.tsx
// The tiles an image or a video clip shows as, in a gallery in a reply and in the Media section
// of the conversation drawer.
//
// An image tile is the picture, cropped to the tile. A clip's tile is its first frame with its
// length and a play mark. That frame is fetched only once the tile is on screen, so opening a
// long thread full of clips does not start loading every one of them. A tile whose image or
// clip will not load says so, and still opens the viewer, which explains why and links to it.

import { useEffect, useRef, useState, type RefObject } from 'react';
import { clsx } from 'clsx';
import { ImageOff, Play, VideoOff } from 'lucide-react';
import { resolveImageSource } from '../../lib/images';
import { formatMediaTime, posterFrameUrl, safeMediaUrl } from '../../lib/inlineMedia';

const UNAVAILABLE_HINT = 'This could not be loaded. Its link may have expired, or its host may not be allowed.';

/** True once the element is on screen, and from then on. */
function useSeen(ref: RefObject<Element | null>): boolean {
    const [seen, setSeen] = useState(() => typeof IntersectionObserver === 'undefined');
    useEffect(() => {
        const element = ref.current;
        if (seen || !element) {
            return undefined;
        }
        const observer = new IntersectionObserver((entries) => {
            if (entries.some((entry) => entry.isIntersecting)) {
                setSeen(true);
            }
        }, { rootMargin: '200px' });
        observer.observe(element);
        return () => observer.disconnect();
    }, [ref, seen]);
    return seen;
}

/** What a tile shows when its image or clip will not load. */
export function MediaUnavailable({ kind }: { kind: 'image' | 'video' }) {
    const Icon = kind === 'image' ? ImageOff : VideoOff;
    return (
        <span
            title={UNAVAILABLE_HINT}
            className="flex h-full w-full flex-col items-center justify-center gap-1 bg-surface-sunken p-1 text-center text-[10px] leading-tight text-text-3"
        >
            <Icon size={16} aria-hidden="true" />
            Unavailable
        </span>
    );
}

export function ImageTile({
    src,
    title,
    label,
    onOpen,
    className,
}: {
    src: string;
    title: string;
    /** The button's accessible name, which says what pressing it does. */
    label: string;
    onOpen: () => void;
    /** Sizing, such as the tile's aspect ratio. */
    className?: string;
}) {
    const [failed, setFailed] = useState(false);
    const source = resolveImageSource(src);
    return (
        <button
            type="button"
            onClick={(event) => {
                event.preventDefault();
                onOpen();
            }}
            title={title}
            aria-label={label}
            aria-haspopup="dialog"
            data-media-tile-kind="image"
            className={clsx(
                'group/tile relative block w-full cursor-zoom-in overflow-hidden rounded-lg border border-edge bg-surface-sunken',
                className,
            )}
        >
            {source && !failed ? (
                <img
                    src={source.src}
                    alt=""
                    loading="lazy"
                    onError={() => setFailed(true)}
                    className="h-full w-full object-cover transition-transform duration-200 group-hover/tile:scale-[1.03]"
                />
            ) : (
                <MediaUnavailable kind="image" />
            )}
        </button>
    );
}

export function VideoTile({
    src,
    title,
    label,
    onOpen,
    className,
}: {
    src: string;
    title: string;
    label: string;
    onOpen: () => void;
    className?: string;
}) {
    const ref = useRef<HTMLButtonElement>(null);
    const seen = useSeen(ref);
    const [duration, setDuration] = useState(0);
    const [failed, setFailed] = useState(false);
    return (
        <button
            ref={ref}
            type="button"
            onClick={(event) => {
                event.preventDefault();
                onOpen();
            }}
            title={title}
            aria-label={label}
            data-media-tile-kind="video"
            className={clsx(
                'group/tile relative block w-full overflow-hidden rounded-lg border border-edge bg-black',
                className,
            )}
        >
            {failed ? (
                <MediaUnavailable kind="video" />
            ) : (
                <>
                    {seen && (
                        <video
                            src={posterFrameUrl(safeMediaUrl(src))}
                            preload="metadata"
                            muted
                            playsInline
                            tabIndex={-1}
                            aria-hidden="true"
                            onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
                            onError={() => setFailed(true)}
                            className="pointer-events-none h-full w-full object-cover"
                        />
                    )}
                    <span className="absolute inset-0 flex items-center justify-center" aria-hidden="true">
                        <span className="flex size-9 items-center justify-center rounded-full bg-black/55 text-white ring-1 ring-white/40 transition-transform group-hover/tile:scale-110">
                            <Play size={16} className="translate-x-px" fill="currentColor" />
                        </span>
                    </span>
                    {Number.isFinite(duration) && duration > 0 && (
                        <span
                            aria-hidden="true"
                            className="absolute right-1 bottom-1 rounded bg-black/70 px-1 font-mono text-[10px] text-white tabular-nums"
                        >
                            {formatMediaTime(duration)}
                        </span>
                    )}
                </>
            )}
        </button>
    );
}
