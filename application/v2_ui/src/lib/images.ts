// images.ts
// Resolving an image message's content into something an <img> can display.
//
// Image messages do not carry a dedicated URL field. `hydrate_image_messages`
// (functions_image_messages.py) writes the image into `content` in one of three forms, and
// the client has to recognise all of them:
//
//   - `data:image/...;base64,...`  a small image inlined directly
//   - `/api/image/<message_id>`    blob-backed, or larger than the inline limit
//   - `https://...`                an externally hosted image
//
// Anything else is not an image we can render, and is better shown as text than as a broken
// image element.

import { apiUrl } from './apiClient';

/** Where an image message's bytes actually live. */
export type ImageSourceKind = 'data-uri' | 'endpoint' | 'external';

export interface ResolvedImageSource {
    kind: ImageSourceKind;
    /** Ready to place in an `<img src>`. */
    src: string;
}

/**
 * Resolve an image message's `content` to a displayable source.
 *
 * Returns null when the content is not a form we recognise, so the caller can fall back to
 * rendering it as text rather than emitting an image that will never load.
 */
export function resolveImageSource(content: string | undefined): ResolvedImageSource | null {
    const value = (content ?? '').trim();
    if (!value) {
        return null;
    }

    if (value.startsWith('data:image/')) {
        return { kind: 'data-uri', src: value };
    }

    // Matches is_external_image_url in functions_image_messages.py.
    if (/^https?:\/\//i.test(value)) {
        return { kind: 'external', src: value };
    }

    // The served path is root-relative, so it needs the same base treatment as any other
    // API call for the split-origin deployment to keep working.
    if (value.startsWith('/api/image/')) {
        return { kind: 'endpoint', src: apiUrl(value) };
    }

    return null;
}
