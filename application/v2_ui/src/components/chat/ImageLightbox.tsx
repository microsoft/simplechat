// ImageLightbox.tsx
// Full-screen viewer for an image message, opened by clicking the image in the thread.
//
// This replaces what used to be a `target="_blank"` anchor around the thumbnail. Leaving the
// app to look at an image the app already has is a poor trade, and for the small inline
// images that arrive as `data:` URIs it did not even work, because browsers block top-level
// navigation to a data URL. The actions the new tab used to provide -- see it full size, save
// it, open the raw file -- are offered here instead.
//
// The dialog conventions match CitationChip and EnhancedCitationViewer: a click-to-close
// backdrop, Escape to dismiss, and no focus-trap utility, since none of the other dialogs in
// this UI use one.

import { useCallback, useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Download, ExternalLink, Maximize2, Minimize2, PenLine, X } from 'lucide-react';
import { GlassPanel } from '../ui/primitives';
import { toast } from '../../stores/toastStore';
import {
    downloadImageSource,
    openImageInNewTab,
    type ResolvedImageSource,
} from '../../lib/images';

/** Fit shrinks the image to the panel; actual renders it at natural size and scrolls. */
type ZoomMode = 'fit' | 'actual';

export function ImageLightbox({
    source,
    title,
    naming,
    onEdit,
    onClose,
}: {
    source: ResolvedImageSource;
    /** Shown in the header and used as the image's accessible name. */
    title: string;
    /** Fields the download name is derived from. */
    naming: { filename?: unknown; prompt?: unknown; id?: unknown };
    /** Offered only for a generated image the deployment can rework. */
    onEdit?: () => void;
    onClose: () => void;
}) {
    const [zoom, setZoom] = useState<ZoomMode>('fit');
    const [saving, setSaving] = useState(false);
    const closeRef = useRef<HTMLButtonElement>(null);

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onClose();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [onClose]);

    // Opening a dialog should move the keyboard focus into it, and closing should hand it
    // back to whatever had it before, which is the thumbnail that was clicked.
    useEffect(() => {
        const previous = document.activeElement as HTMLElement | null;
        closeRef.current?.focus();
        return () => previous?.focus?.();
    }, []);

    const handleDownload = useCallback(async () => {
        setSaving(true);
        try {
            await downloadImageSource(source, naming);
            toast.success('Image saved.');
        } catch (error) {
            toast.error(
                error instanceof Error && error.message
                    ? `Download failed. ${error.message}`
                    : 'Download failed.',
            );
        } finally {
            setSaving(false);
        }
    }, [source, naming]);

    const handleOpenInNewTab = useCallback(() => {
        if (!openImageInNewTab(source)) {
            toast.error('The browser blocked the new tab.');
        }
    }, [source]);

    const fit = zoom === 'fit';

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label="Image"
        >
            <div className="absolute inset-0 bg-black/60" aria-hidden="true" onClick={onClose} />

            <GlassPanel
                elevation="modal"
                edge
                className="relative flex h-[88vh] w-full max-w-6xl flex-col overflow-hidden"
            >
                <div className="flex shrink-0 items-center gap-3 border-b border-edge px-5 py-3">
                    <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-text-1">
                        {title}
                    </h2>

                    {onEdit && (
                        <button
                            type="button"
                            onClick={() => {
                                // Closed first: the editor is its own dialog, and leaving two
                                // stacked modals open would trap focus behind the one on top.
                                onClose();
                                onEdit();
                            }}
                            title="Change this image"
                            aria-label="Change this image"
                            aria-haspopup="dialog"
                            className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                        >
                            <PenLine size={16} />
                        </button>
                    )}
                    <button
                        type="button"
                        onClick={() => setZoom(fit ? 'actual' : 'fit')}
                        title={fit ? 'View at actual size' : 'Fit to the window'}
                        aria-label={fit ? 'View at actual size' : 'Fit to the window'}
                        aria-pressed={!fit}
                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        {fit ? <Maximize2 size={16} /> : <Minimize2 size={16} />}
                    </button>
                    <button
                        type="button"
                        onClick={() => void handleDownload()}
                        disabled={saving}
                        title="Save the image"
                        aria-label="Save the image"
                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        <Download size={16} />
                    </button>
                    <button
                        type="button"
                        onClick={handleOpenInNewTab}
                        title="Open the image in a new tab"
                        aria-label="Open the image in a new tab"
                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <ExternalLink size={16} />
                    </button>
                    <button
                        ref={closeRef}
                        type="button"
                        onClick={onClose}
                        title="Close"
                        aria-label="Close the image"
                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={17} />
                    </button>
                </div>

                <div
                    className={clsx(
                        'min-h-0 flex-1 p-4',
                        // Fit centres the whole image; actual size needs to scroll in both
                        // directions so a large image can be panned around.
                        fit ? 'flex items-center justify-center overflow-hidden' : 'overflow-auto',
                    )}
                >
                    <img
                        src={source.src}
                        alt={title}
                        onClick={() => setZoom(fit ? 'actual' : 'fit')}
                        className={clsx(
                            'rounded-xl',
                            fit
                                ? 'max-h-full max-w-full cursor-zoom-in object-contain'
                                : 'max-w-none cursor-zoom-out',
                        )}
                    />
                </div>
            </GlassPanel>
        </div>
    );
}
