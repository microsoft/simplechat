// ImageReferenceThumbnail.tsx

import { useState } from 'react';
import { clsx } from 'clsx';
import { Image as ImageIcon } from 'lucide-react';
import {
    imageReferencePreviewUrl,
    type ImageReferenceProvenance,
    type ImageReferenceRequest,
} from '../../lib/imageReferences';

/**
 * A small preview of a reference image, for composer chips, sent messages and plan cards.
 *
 * The preview endpoints authorize every request, so a reference the reader can no longer see
 * simply fails to load and falls back to the icon rather than showing anything.
 */
export function ImageReferenceThumbnail({
    reference,
    label,
    className,
}: {
    reference: ImageReferenceRequest | ImageReferenceProvenance;
    label?: string;
    className?: string;
}) {
    const [failed, setFailed] = useState(false);
    const url = imageReferencePreviewUrl(reference, 'thumbnail');
    const sizing = clsx('h-9 w-9 shrink-0 rounded-md border border-edge', className);

    if (!url || failed) {
        return (
            <span aria-hidden="true" className={clsx(sizing, 'flex items-center justify-center bg-surface-sunken text-text-3')}>
                <ImageIcon size={14} />
            </span>
        );
    }
    return (
        <img
            src={url}
            alt={label ? `Reference image: ${label}` : 'Reference image'}
            loading="lazy"
            onError={() => setFailed(true)}
            className={clsx(sizing, 'object-cover')}
        />
    );
}
