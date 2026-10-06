// MediaViewer.tsx
// A large view of one image or clip from a set, stepping to the others with the arrow keys or
// the buttons at either side.
//
// Opened from a gallery in a reply, where the set is that gallery, and from the Media section of
// the conversation drawer, where it is every image and clip in the conversation. A clip starts
// playing when it opens, and stepping away stops it. An image can be viewed at its actual size.
// Download saves the file when its host lets the page read it and opens it in a new tab when it
// does not. From the drawer, Show in conversation closes the viewer and scrolls to the message.
//
// Built on Modal, so Escape and a click outside close it, Tab stays inside it, and focus returns
// to the tile that opened it.

import { useCallback, useEffect, useState } from 'react';
import { clsx } from 'clsx';
import {
    ChevronLeft,
    ChevronRight,
    Download,
    ExternalLink,
    Loader2,
    LocateFixed,
    Maximize2,
    Minimize2,
    X,
} from 'lucide-react';
import { resolveImageSource } from '../../lib/images';
import { claimPlayback, safeMediaUrl } from '../../lib/inlineMedia';
import { openMediaInNewTab } from '../../lib/mediaDownload';
import { toast } from '../../stores/toastStore';
import { Modal } from '../ui/Modal';
import { InlineMediaFallback } from './InlineMediaFallback';
import { useMediaDownload } from './useMediaDownload';

export interface MediaViewerItem {
    kind: 'image' | 'video';
    /** An image source as resolveImageSource accepts it, or a clip's URL. */
    src: string;
    title: string;
    /** A second line, such as an image's alt text when a caption gave the title. */
    detail?: string;
    /** The message the item appears in, for Show in conversation. */
    messageId?: string;
}

const HEADER_BUTTON =
    'inline-flex shrink-0 items-center justify-center rounded-lg p-1.5 text-text-3 transition-colors ' +
    'hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50';
const SIDE_BUTTON =
    'absolute top-1/2 z-10 flex size-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/55 ' +
    'text-white ring-1 ring-white/30 transition-colors hover:bg-black/75 aria-disabled:cursor-default ' +
    'aria-disabled:opacity-30 aria-disabled:hover:bg-black/55';

function ViewerStage({
    item,
    actualSize,
    onToggleZoom,
    startAt,
}: {
    item: MediaViewerItem;
    actualSize: boolean;
    onToggleZoom: () => void;
    startAt?: number;
}) {
    const [failed, setFailed] = useState(false);

    if (item.kind === 'image') {
        const source = resolveImageSource(item.src);
        if (!source || failed) {
            return <InlineMediaFallback kind="image" src={item.src} title={item.title} />;
        }
        return (
            <img
                src={source.src}
                alt={item.detail || item.title}
                onClick={onToggleZoom}
                onError={() => setFailed(true)}
                className={clsx(
                    'rounded-lg',
                    actualSize ? 'max-w-none cursor-zoom-out' : 'max-h-full max-w-full cursor-zoom-in object-contain',
                )}
            />
        );
    }

    if (failed) {
        return <InlineMediaFallback kind="video" src={item.src} title={item.title} />;
    }
    return (
        <video
            src={safeMediaUrl(item.src) ?? undefined}
            controls
            autoPlay
            playsInline
            aria-label={item.title}
            onPlay={(event) => claimPlayback(event.currentTarget)}
            onLoadedMetadata={(event) => {
                if (startAt && startAt > 0) {
                    event.currentTarget.currentTime = startAt;
                }
            }}
            onError={() => setFailed(true)}
            className="h-full w-full rounded-lg bg-black object-contain"
        />
    );
}

export function MediaViewer({
    items,
    index,
    onIndexChange,
    onClose,
    onLocate,
    startAt,
}: {
    items: readonly MediaViewerItem[];
    index: number;
    onIndexChange: (index: number) => void;
    onClose: () => void;
    /** Offered for an item that names its message. The viewer closes first. */
    onLocate?: (item: MediaViewerItem) => void;
    /** Where the clip it opened on starts, in seconds: how far it had played in its tile. */
    startAt?: number;
}) {
    const count = items.length;
    const position = Math.min(Math.max(index, 0), Math.max(count - 1, 0));
    const item = items[position];
    const [openedAt] = useState(position);
    const [actualSize, setActualSize] = useState(false);
    const { download, busy } = useMediaDownload();

    const step = useCallback((delta: number) => {
        const next = position + delta;
        if (next >= 0 && next < count) {
            setActualSize(false);
            onIndexChange(next);
        }
    }, [count, onIndexChange, position]);

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if ((event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') || event.defaultPrevented
                || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
                return;
            }
            // In a field, a slider or a clip's own controls, the arrow keys keep their usual job.
            const target = event.target instanceof Element ? event.target : null;
            if (target?.closest('input, textarea, select, video, audio, [contenteditable="true"]')) {
                return;
            }
            event.preventDefault();
            step(event.key === 'ArrowLeft' ? -1 : 1);
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [step]);

    if (!item) {
        return null;
    }

    const kindLabel = item.kind === 'image' ? 'Image' : 'Video';
    const atStart = position === 0;
    const atEnd = position === count - 1;

    const banner = (
        <div className="flex shrink-0 items-center gap-1.5 border-b border-edge px-4 py-2.5">
            <div className="min-w-0 flex-1">
                <h2 className="truncate text-sm font-semibold text-text-1" title={item.title}>
                    {item.title}
                </h2>
                <p className="text-xs text-text-3" aria-live="polite" data-media-viewer-position="">
                    {kindLabel}
                    {count > 1 && ` \u00b7 ${position + 1} of ${count}`}
                </p>
            </div>
            {item.kind === 'image' && (
                <button
                    type="button"
                    onClick={() => setActualSize((value) => !value)}
                    aria-pressed={actualSize}
                    aria-label={actualSize ? 'Fit to the window' : 'View at actual size'}
                    title={actualSize ? 'Fit to the window' : 'View at actual size'}
                    className={HEADER_BUTTON}
                >
                    {actualSize ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
                </button>
            )}
            <button
                type="button"
                onClick={() => void download(item.kind, item.src, item.title)}
                disabled={busy}
                aria-label={`Download ${item.title}`}
                title="Download"
                className={HEADER_BUTTON}
            >
                {busy ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
            </button>
            {item.kind === 'video' ? (
                <a
                    href={safeMediaUrl(item.src) ?? undefined}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`Open ${item.title} in a new tab`}
                    title="Open in a new tab"
                    className={HEADER_BUTTON}
                >
                    <ExternalLink size={16} />
                </a>
            ) : (
                <button
                    type="button"
                    onClick={() => {
                        if (!openMediaInNewTab('image', item.src)) {
                            toast.error('The browser blocked the new tab.');
                        }
                    }}
                    aria-label={`Open ${item.title} in a new tab`}
                    title="Open in a new tab"
                    className={HEADER_BUTTON}
                >
                    <ExternalLink size={16} />
                </button>
            )}
            {onLocate && item.messageId && (
                <button
                    type="button"
                    onClick={() => {
                        onClose();
                        onLocate(item);
                    }}
                    aria-label="Show in conversation"
                    title="Show in conversation"
                    className={HEADER_BUTTON}
                >
                    <LocateFixed size={16} />
                </button>
            )}
            <button type="button" onClick={onClose} aria-label="Close" title="Close" className={HEADER_BUTTON}>
                <X size={17} />
            </button>
        </div>
    );

    return (
        <Modal title={item.title} onClose={onClose} size="2xl" tall banner={banner} bodyClassName="flex min-h-0 flex-col">
            <div className="relative min-h-0 flex-1 bg-black/90" data-media-viewer="">
                <div
                    className={clsx(
                        'absolute inset-0',
                        actualSize && item.kind === 'image'
                            ? 'overflow-auto p-3'
                            : 'flex items-center justify-center overflow-hidden p-3',
                    )}
                >
                    <ViewerStage
                        key={`${position}:${item.src}`}
                        item={item}
                        actualSize={actualSize}
                        onToggleZoom={() => setActualSize((value) => !value)}
                        startAt={position === openedAt ? startAt : undefined}
                    />
                </div>
                {count > 1 && (
                    <>
                        <button
                            type="button"
                            onClick={() => step(-1)}
                            aria-disabled={atStart}
                            aria-label="Previous"
                            title="Previous (Left arrow)"
                            className={clsx(SIDE_BUTTON, 'left-3')}
                        >
                            <ChevronLeft size={20} />
                        </button>
                        <button
                            type="button"
                            onClick={() => step(1)}
                            aria-disabled={atEnd}
                            aria-label="Next"
                            title="Next (Right arrow)"
                            className={clsx(SIDE_BUTTON, 'right-3')}
                        >
                            <ChevronRight size={20} />
                        </button>
                    </>
                )}
            </div>
            {item.detail && (
                <p className="shrink-0 border-t border-edge px-4 py-2 text-xs text-text-2">{item.detail}</p>
            )}
        </Modal>
    );
}
