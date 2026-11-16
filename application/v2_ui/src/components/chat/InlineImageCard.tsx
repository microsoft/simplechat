// InlineImageCard.tsx
// An image placed in a chat message with markdown, shown as a captioned card.
//
// Agents put photographs, document scans and maps into their replies with `![caption](url)`.
// Rendered bare, a large image fills the thread and its alt text, which is usually the only
// description of what it shows, is invisible. The card bounds the height, shows the alt text as
// a caption, and opens the existing lightbox on click for the full-size view, saving and opening
// in a new tab.
//
// Built from <span> and <button>: an image sits inside a <p>, where block elements would be
// invalid HTML.

import { useState } from 'react';
import { createPortal } from 'react-dom';
import { resolveImageSource } from '../../lib/images';
import { ImageLightbox } from './ImageLightbox';

export function InlineImageCard({ src, alt }: { src?: string; alt?: string }) {
    const [open, setOpen] = useState(false);
    const [failed, setFailed] = useState(false);
    const source = resolveImageSource(src);
    const caption = (alt ?? '').trim();

    // A form we do not recognise, or an image that failed to load, keeps the plain alt text so
    // the message still says what was meant to be there.
    if (!source || failed) {
        return caption ? <span className="text-text-3 italic">[{caption}]</span> : null;
    }

    return (
        <span className="my-2 block w-full max-w-2xl overflow-hidden rounded-xl border border-edge bg-surface-sunken">
            <button
                type="button"
                onClick={(event) => {
                    // Also keeps a surrounding markdown link from navigating away.
                    event.preventDefault();
                    setOpen(true);
                }}
                title="View the full-size image"
                aria-label={caption ? `View the full-size image: ${caption}` : 'View the full-size image'}
                aria-haspopup="dialog"
                className="block w-full cursor-zoom-in bg-black/5"
            >
                <img
                    src={source.src}
                    alt={caption}
                    loading="lazy"
                    onError={() => setFailed(true)}
                    className="mx-auto block max-h-[28rem] w-auto max-w-full object-contain"
                />
            </button>
            {caption && <span className="block px-3 py-1.5 text-xs text-text-2">{caption}</span>}
            {/* Portalled: the dialog is block markup, and this card sits inside a paragraph. */}
            {open &&
                createPortal(
                    <ImageLightbox source={source} title={caption || 'Image'} naming={{ prompt: caption }} onClose={() => setOpen(false)} />,
                    document.body,
                )}
        </span>
    );
}
