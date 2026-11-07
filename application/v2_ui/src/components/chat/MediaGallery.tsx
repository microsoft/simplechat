// MediaGallery.tsx
// A run of images and clips in a reply, three to a row, each opening a viewer that steps
// through the gallery.
//
// rehypeMediaGallery (lib/mediaGallery.ts) finds the run and wraps it. The renderer hands that
// wrapper to MediaGallery, and each image or clip inside it to MediaGalleryTile, which reads its
// item from the gallery. An image opens the viewer. A clip plays in its tile, at the size the
// gallery gives it, and the corner button opens it in the viewer, carrying on from where it is.

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';
import { Maximize2 } from 'lucide-react';
import { claimPlayback, safeMediaUrl } from '../../lib/inlineMedia';
import type { MediaGalleryItem } from '../../lib/mediaGallery';
import { MediaViewer, type MediaViewerItem } from './MediaViewer';
import { ImageTile, MediaUnavailable, VideoTile } from './MediaTiles';

interface GalleryState {
    items: readonly MediaGalleryItem[];
    open: (index: number, startAt?: number) => void;
}

const GalleryContext = createContext<GalleryState | null>(null);

function describe(items: readonly MediaGalleryItem[]): string {
    const images = items.filter((item) => item.kind === 'image').length;
    const clips = items.length - images;
    const parts = [
        images > 0 ? `${images} ${images === 1 ? 'image' : 'images'}` : '',
        clips > 0 ? `${clips} ${clips === 1 ? 'video' : 'videos'}` : '',
    ].filter(Boolean);
    return `Gallery: ${parts.join(' and ')}`;
}

export function MediaGallery({ items, children }: { items: readonly MediaGalleryItem[]; children: ReactNode }) {
    const [viewing, setViewing] = useState<{ index: number; startAt?: number } | null>(null);
    const open = useCallback((index: number, startAt?: number) => setViewing({ index, startAt }), []);
    const state = useMemo(() => ({ items, open }), [items, open]);
    const viewerItems = useMemo<MediaViewerItem[]>(
        () => items.map(({ kind, src, title, detail }) => ({ kind, src, title, detail })),
        [items],
    );

    return (
        <GalleryContext.Provider value={state}>
            <div
                role="group"
                aria-label={describe(items)}
                data-media-gallery=""
                className="my-3 grid grid-cols-[repeat(3,minmax(0,13rem))] items-start gap-x-2 gap-y-3"
            >
                {children}
            </div>
            {viewing && (
                <MediaViewer
                    items={viewerItems}
                    index={viewing.index}
                    startAt={viewing.startAt}
                    onIndexChange={(index) => setViewing({ index })}
                    onClose={() => setViewing(null)}
                />
            )}
        </GalleryContext.Provider>
    );
}

function GalleryClip({ item, onExpand }: { item: MediaGalleryItem; onExpand: (startAt?: number) => void }) {
    const videoRef = useRef<HTMLVideoElement>(null);
    const [playing, setPlaying] = useState(false);
    const [failed, setFailed] = useState(false);

    const expand = () => {
        const video = videoRef.current;
        const reached = video?.currentTime ?? 0;
        video?.pause();
        onExpand(reached > 0 ? reached : undefined);
    };

    return (
        <span className="relative block">
            {failed ? (
                <span className="block aspect-[4/3] overflow-hidden rounded-lg border border-edge">
                    <MediaUnavailable kind="video" />
                </span>
            ) : playing ? (
                <span className="block aspect-[4/3] overflow-hidden rounded-lg border border-edge bg-black">
                    <video
                        ref={videoRef}
                        src={safeMediaUrl(item.src) ?? undefined}
                        controls
                        autoPlay
                        playsInline
                        aria-label={item.title}
                        onPlay={(event) => claimPlayback(event.currentTarget)}
                        onError={() => setFailed(true)}
                        className="h-full w-full object-contain"
                    />
                </span>
            ) : (
                <VideoTile
                    src={item.src}
                    title={item.title}
                    label={`Play video: ${item.title}`}
                    onOpen={() => setPlaying(true)}
                    className="aspect-[4/3]"
                />
            )}
            <button
                type="button"
                onClick={expand}
                aria-label={`View larger: ${item.title}`}
                aria-haspopup="dialog"
                title="View larger"
                className="absolute top-1.5 right-1.5 flex size-7 items-center justify-center rounded-md bg-black/60 text-white ring-1 ring-white/30 transition-colors hover:bg-black/80"
            >
                <Maximize2 size={13} />
            </button>
        </span>
    );
}

/** One tile of the gallery around it, by its position there. */
export function MediaGalleryTile({ index }: { index: number }) {
    const gallery = useContext(GalleryContext);
    const item = gallery?.items[index];
    if (!gallery || !item) {
        return null;
    }
    if (item.kind === 'image') {
        return (
            <ImageTile
                src={item.src}
                title={item.title}
                label={`View image: ${item.title}`}
                onOpen={() => gallery.open(index)}
                className="aspect-[4/3]"
            />
        );
    }
    return <GalleryClip item={item} onExpand={(startAt) => gallery.open(index, startAt)} />;
}
