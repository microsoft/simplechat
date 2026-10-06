// mediaDownload.ts
// Saving an image, clip or recording a conversation shows, and opening one in a new tab.
//
// Media in a reply is often a signed link to another host. The page can save it directly only
// when that host lets the page read it (CORS). When it does not, the file is opened in a new tab
// instead, where the browser's own viewer can save it. A host refuses quickly, so the new tab
// usually still counts as part of the click; when the browser blocks it anyway, the caller is
// told, so it can offer a link to open it by hand.

import { CREDENTIALS_MODE } from './apiClient';
import { saveBlob } from './endpoints';
import { decodeImageDataUri, openImageInNewTab, resolveImageSource } from './images';
import { safeMediaUrl } from './inlineMedia';

export type MediaKind = 'image' | 'video' | 'audio';

/** Saved to downloads, opened in a new tab instead, or refused a new tab by the browser. */
export type MediaDownloadOutcome = 'saved' | 'opened' | 'blocked';

/** How long the host has to start answering before the file is opened in a new tab instead. */
const RESPONSE_TIMEOUT_MS = 4000;

/** Characters a file name cannot contain on Windows, plus path separators and controls. */
// eslint-disable-next-line no-control-regex
const UNSAFE_FILENAME_CHARS = /[<>:"/\\|?*\u0000-\u001f]/g;
const HAS_EXTENSION = /\.[a-z0-9]{2,5}$/i;

const MIME_EXTENSIONS: Record<string, string> = {
    'audio/aac': 'aac',
    'audio/flac': 'flac',
    'audio/mp4': 'm4a',
    'audio/mpeg': 'mp3',
    'audio/ogg': 'ogg',
    'audio/wav': 'wav',
    'audio/wave': 'wav',
    'audio/webm': 'weba',
    'audio/x-wav': 'wav',
    'image/gif': 'gif',
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/svg+xml': 'svg',
    'image/webp': 'webp',
    'video/mp4': 'mp4',
    'video/ogg': 'ogv',
    'video/quicktime': 'mov',
    'video/webm': 'webm',
};
const DEFAULT_EXTENSIONS: Record<MediaKind, string> = { image: 'png', video: 'mp4', audio: 'mp3' };

/** The file is not there to save: the host answered without it, or its data could not be read. */
class MediaUnavailableError extends Error {
    constructor(message: string) {
        super(message);
        this.name = 'MediaUnavailableError';
    }
}

function cleanFileName(value: string): string {
    return value
        .replace(UNSAFE_FILENAME_CHARS, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/^[. ]+/, '')
        .slice(0, 80)
        .replace(/[. ]+$/, '');
}

/**
 * The name a file is saved under: the file name at the end of its URL when that has an
 * extension, otherwise its title with an extension for its type.
 */
export function mediaFileName(src: string, title: string, kind: MediaKind, blobType = ''): string {
    const url = safeMediaUrl(src);
    let fromUrl = '';
    if (url) {
        try {
            fromUrl = cleanFileName(decodeURIComponent(new URL(url).pathname.split('/').pop() ?? ''));
        } catch {
            fromUrl = '';
        }
    }
    if (fromUrl && HAS_EXTENSION.test(fromUrl)) {
        return fromUrl;
    }
    const base = cleanFileName(title) || fromUrl || kind;
    const extension = MIME_EXTENSIONS[blobType.split(';')[0].trim().toLowerCase()] ?? DEFAULT_EXTENSIONS[kind];
    return `${base}.${extension}`;
}

/** The address to fetch a file from, and whether it is the app's own authenticated endpoint. */
function fetchTarget(kind: MediaKind, src: string): { url: string; credentials: RequestCredentials } | null {
    if (kind === 'image') {
        const source = resolveImageSource(src);
        if (!source || source.kind === 'data-uri') {
            return null;
        }
        if (source.kind === 'endpoint') {
            return { url: source.src, credentials: CREDENTIALS_MODE };
        }
    }
    const url = safeMediaUrl(src);
    if (!url) {
        return null;
    }
    // Another host gets no cookies: a signed link carries its own authority.
    const sameOrigin = new URL(url).origin === window.location.origin;
    return { url, credentials: sameOrigin ? 'same-origin' : 'omit' };
}

async function fetchMediaBlob(kind: MediaKind, src: string): Promise<Blob> {
    if (kind === 'image') {
        const source = resolveImageSource(src);
        if (source?.kind === 'data-uri') {
            const blob = decodeImageDataUri(source.src);
            if (!blob) {
                throw new MediaUnavailableError('The image data could not be read.');
            }
            return blob;
        }
    }
    const target = fetchTarget(kind, src);
    if (!target) {
        throw new TypeError('The file has no address the browser can fetch.');
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), RESPONSE_TIMEOUT_MS);
    let response: Response;
    try {
        response = await fetch(target.url, { credentials: target.credentials, signal: controller.signal });
    } finally {
        // Only the wait for an answer is limited. A large clip may take longer to arrive.
        window.clearTimeout(timer);
    }
    if (!response.ok) {
        throw new MediaUnavailableError(
            `The file could not be fetched (${response.status}). Its link may have expired.`,
        );
    }
    return response.blob();
}

/** Open a file in a new browser tab. False when the browser blocked the tab. */
export function openMediaInNewTab(kind: MediaKind, src: string): boolean {
    if (kind === 'image') {
        const source = resolveImageSource(src);
        return source ? openImageInNewTab(source) : false;
    }
    const url = safeMediaUrl(src);
    if (!url) {
        return false;
    }
    // Severed by hand: passing `noopener` makes window.open return null even when it succeeds.
    const opened = window.open(url, '_blank');
    if (opened) {
        opened.opener = null;
    }
    return Boolean(opened);
}

/**
 * Save a file to the user's downloads, or open it in a new tab when its host will not let the
 * page read it.
 *
 * Throws when the host answered but had no file to give, as when a signed link has expired:
 * a new tab would only show the same error.
 */
export async function downloadMedia(kind: MediaKind, src: string, title: string): Promise<MediaDownloadOutcome> {
    let blob: Blob;
    try {
        blob = await fetchMediaBlob(kind, src);
    } catch (error) {
        if (error instanceof MediaUnavailableError) {
            throw error;
        }
        // Refused by CORS, unreachable, or too slow to answer.
        return openMediaInNewTab(kind, src) ? 'opened' : 'blocked';
    }
    saveBlob(blob, mediaFileName(src, title, kind, blob.type));
    return 'saved';
}
