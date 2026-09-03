// images.ts
// Resolving an image message's content into something an <img> can display, and taking that
// image back out of the app as a download or a new tab.
//
// Image messages do not carry a dedicated URL field. `hydrate_image_messages`
// (functions_image_messages.py) writes the image into `content` in one of three forms, and
// the client has to recognise all of them:
//
//   - `data:image/...;base64,...`  a small image inlined directly
//   - `/api/image/<message_id>`    blob-backed, or larger than the inline limit
//   - `https://...`                an externally hosted image
//
// A shared conversation adds a fourth. `serialize_collaboration_message` writes
// `/api/collaboration/conversations/<id>/images/<message_id>`, because a shared message is a
// mirror and its bytes are reached through the collaboration route rather than the personal
// one.
//
// Either served path may carry a `?rev=` parameter naming which stored version to serve, which
// is what makes an edited image's URL change so a cached copy is not shown in place of it.
//
// Anything else is not an image we can render, and is better shown as text than as a broken
// image element.

import { apiUrl, CREDENTIALS_MODE } from './apiClient';
import { saveBlob } from './endpoints';

/** Where an image message's bytes actually live. */
export type ImageSourceKind = 'data-uri' | 'endpoint' | 'external';

export interface ResolvedImageSource {
    kind: ImageSourceKind;
    /** Ready to place in an `<img src>`. */
    src: string;
}

/**
 * The served paths that return image bytes, personal and shared.
 *
 * Matched precisely rather than by an `/api/` prefix: this decides what gets rendered as an
 * image, and a loose match would emit an `<img>` pointed at a JSON endpoint.
 */
const IMAGE_ENDPOINT_PATTERN =
    /^\/api\/(?:image\/|collaboration\/conversations\/[^/]+\/images\/)/;

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
    if (IMAGE_ENDPOINT_PATTERN.test(value)) {
        return { kind: 'endpoint', src: apiUrl(value) };
    }

    return null;
}

/**
 * The served path without its revision parameter.
 *
 * The version history needs to address each stored version separately, and they would otherwise
 * all resolve to the same URL and therefore to the same cached image. Returns an empty string
 * for an inline or external image, which has no endpoint to address versions through — and no
 * history either, until it has been edited once.
 */
export function imageEndpointBase(source: ResolvedImageSource | null): string {
    if (!source || source.kind !== 'endpoint') {
        return '';
    }
    return source.src.split('?')[0];
}

/* -------------------------------------------------------------------------- */
/* Taking an image out of the app                                              */
/* -------------------------------------------------------------------------- */

/** Extension to use for a blob whose type we recognise. */
const MIME_EXTENSIONS: Record<string, string> = {
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/jpg': 'jpg',
    'image/gif': 'gif',
    'image/webp': 'webp',
    'image/bmp': 'bmp',
    'image/svg+xml': 'svg',
    'image/tiff': 'tiff',
};

/** A name that already ends in an image extension does not need another one. */
const IMAGE_EXTENSION_PATTERN = /\.(png|jpe?g|gif|webp|bmp|svg|tiff?)$/i;

/** Characters a file name cannot contain on Windows, plus path separators and controls. */
// eslint-disable-next-line no-control-regex
const UNSAFE_FILENAME_CHARS = /[<>:"/\\|?*\u0000-\u001f]/g;

/**
 * Decode a `data:image/...;base64,...` URI to a blob, synchronously.
 *
 * Kept synchronous on purpose: `openImageInNewTab` calls it inside the click handler, and
 * awaiting anything first would spend the user activation that lets `window.open` through
 * the popup blocker.
 *
 * Returns null for a malformed URI rather than throwing, so callers can report one message
 * for "cannot read this image" regardless of which step failed.
 */
export function decodeImageDataUri(value: string): Blob | null {
    const separator = value.indexOf(',');
    if (!value.startsWith('data:image/') || separator === -1) {
        return null;
    }

    const header = value.slice(5, separator);
    const type = header.split(';', 1)[0] || 'image/png';
    const payload = value.slice(separator + 1);

    try {
        const binary = atob(payload);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i += 1) {
            bytes[i] = binary.charCodeAt(i);
        }
        return new Blob([bytes], { type });
    } catch {
        return null;
    }
}

/**
 * Fetch the bytes behind a resolved image source.
 *
 * Every kind has to be handled separately. A data URI is decoded locally with no request at
 * all. `/api/image/<id>` is authenticated, so it needs the same credentials mode as the rest
 * of the client or the split-origin deployment gets a 401. An externally hosted image is
 * fetched without credentials and may be refused by CORS, which is reported rather than
 * papered over.
 */
export async function resolveImageBlob(source: ResolvedImageSource): Promise<Blob> {
    if (source.kind === 'data-uri') {
        const blob = decodeImageDataUri(source.src);
        if (!blob) {
            throw new Error('The image data could not be read.');
        }
        return blob;
    }

    let response: Response;
    try {
        response = await fetch(
            source.src,
            source.kind === 'endpoint' ? { credentials: CREDENTIALS_MODE } : {},
        );
    } catch {
        // A cross-origin host that sends no CORS headers rejects the read here. The image
        // still displays, because <img> is not subject to the same restriction.
        throw new Error('The image is hosted elsewhere and would not allow a download.');
    }

    if (!response.ok) {
        throw new Error(`The image could not be fetched (${response.status}).`);
    }

    return response.blob();
}

/** Strip anything that cannot appear in a file name, and keep it a sensible length. */
function sanitizeFileName(value: string): string {
    return value
        .replace(UNSAFE_FILENAME_CHARS, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .slice(0, 80)
        .replace(/[. ]+$/, '');
}

/**
 * Build a download name for an image message.
 *
 * A server-supplied file name wins when there is one. Otherwise the prompt makes a far more
 * recognisable name in a downloads folder than an opaque message id, so it is used when it
 * is short enough to read, with the id as the last resort.
 */
export function imageFileName(
    { filename, prompt, id }: { filename?: unknown; prompt?: unknown; id?: unknown },
    blobType?: string,
): string {
    const fromServer = sanitizeFileName(String(filename ?? ''));
    const fromPrompt = sanitizeFileName(String(prompt ?? ''));
    const fromId = sanitizeFileName(String(id ?? ''));

    const base =
        fromServer || (fromPrompt && fromPrompt.length <= 60 ? fromPrompt : '') || fromId || 'image';

    if (IMAGE_EXTENSION_PATTERN.test(base)) {
        return base;
    }

    const extension = MIME_EXTENSIONS[(blobType || '').toLowerCase()] || 'png';
    return `${base}.${extension}`;
}

/**
 * Open an image in a new browser tab.
 *
 * A data URI cannot simply be handed to `window.open`: browsers block top-level navigation
 * to `data:` URLs, so it is republished as an object URL first. That URL is revoked on a
 * timer because revoking it immediately would break the tab that is still loading it, and
 * never revoking it would hold the bytes for the life of the page.
 *
 * The opener is severed by hand rather than by passing `noopener` in the feature string,
 * because that feature makes `window.open` return null even when it succeeds, which would
 * leave no way to tell a blocked popup from an opened one.
 *
 * Returns false when the browser refused to open the tab, so the caller can say so.
 */
export function openImageInNewTab(source: ResolvedImageSource): boolean {
    const url =
        source.kind === 'data-uri' ? objectUrlForDataUri(source.src) : source.src;
    if (!url) {
        return false;
    }

    const opened = window.open(url, '_blank');
    if (opened) {
        opened.opener = null;
    }
    return Boolean(opened);
}

/** Republish a data URI as a revocable object URL, or null if it cannot be decoded. */
function objectUrlForDataUri(value: string): string | null {
    const blob = decodeImageDataUri(value);
    if (!blob) {
        return null;
    }

    const objectUrl = URL.createObjectURL(blob);
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    return objectUrl;
}

/**
 * Save an image to the user's downloads.
 *
 * The bytes are fetched and saved as a blob rather than pointed at with an `<a download>`,
 * because that attribute is ignored for a cross-origin URL — which is exactly what
 * `/api/image/<id>` becomes in the split-origin deployment.
 */
export async function downloadImageSource(
    source: ResolvedImageSource,
    naming: { filename?: unknown; prompt?: unknown; id?: unknown },
): Promise<void> {
    const blob = await resolveImageBlob(source);
    saveBlob(blob, imageFileName(naming, blob.type));
}

