// inlineMedia.ts
// Recognising audio and video links in rendered markdown, so the chat can play them in place.
//
// Agents and actions return recordings and camera clips as ordinary markdown links, for example
// `[Open audio: Call audio REC-1](https://media.example.com/media/rec-1.wav?exp=...&sig=...)`.
// A link is treated as playable only by the file extension at the end of its URL *path*, so a
// signed query string does not get in the way, and a page that merely mentions ".mp4" in its
// query does not turn into a player.

export type InlineMediaKind = 'audio' | 'video';

const AUDIO_EXTENSIONS = new Set(['mp3', 'wav', 'm4a', 'aac', 'oga', 'ogg', 'opus', 'flac', 'weba']);
const VIDEO_EXTENSIONS = new Set(['mp4', 'm4v', 'webm', 'mov', 'ogv']);

/** Schemes a markdown link may keep, matching react-markdown's default URL transform. */
const LINK_SCHEMES = new Set(['http:', 'https:', 'mailto:', 'tel:', 'irc:', 'ircs:', 'xmpp:']);

/** Link text that describes the action ("Open audio: ...") rather than naming the media. */
const ACTION_PREFIX = /^\s*(?:open|play|listen to|watch)\s+(?:the\s+)?(?:audio|video|recording|clip)\s*[:\-\u2013]\s*/i;

/** Speeds the audio player cycles through. */
export const PLAYBACK_RATES = [1, 1.25, 1.5, 2] as const;

/**
 * An absolute http(s) URL a media element can load, or null.
 *
 * react-markdown's default URL transform has already dropped script URLs. This narrows that to
 * the two schemes a media element can actually load, and resolves a root-relative path against
 * the page so the result is always absolute.
 */
export function safeMediaUrl(value: unknown): string | null {
    if (typeof value !== 'string' || !value.trim()) {
        return null;
    }
    try {
        const parsed = new URL(value.trim(), window.location.href);
        return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : null;
    } catch {
        return null;
    }
}

/**
 * The href a markdown link may keep, or undefined.
 *
 * The same allow list react-markdown applies by default (web, mail, phone and chat schemes, plus
 * relative and fragment links), restated here because a component that renders its own anchor
 * should not depend on an upstream transform having run.
 */
export function safeMarkdownHref(value: unknown): string | undefined {
    if (typeof value !== 'string') {
        return undefined;
    }
    const trimmed = value.trim();
    const colon = trimmed.indexOf(':');
    const boundary = trimmed.search(/[/?#]/);
    // No scheme before the first path, query or fragment character: a relative link.
    if (colon === -1 || (boundary !== -1 && boundary < colon)) {
        return trimmed;
    }
    return LINK_SCHEMES.has(trimmed.slice(0, colon + 1).toLowerCase()) ? trimmed : undefined;
}

/** Whether a URL points at an audio or video file, judged by the extension of its path. */
export function inlineMediaKind(value: unknown): InlineMediaKind | null {
    const url = safeMediaUrl(value);
    if (!url) {
        return null;
    }
    const path = new URL(url).pathname.toLowerCase();
    const dot = path.lastIndexOf('.');
    if (dot === -1 || dot < path.lastIndexOf('/')) {
        return null;
    }
    const extension = path.slice(dot + 1);
    if (AUDIO_EXTENSIONS.has(extension)) {
        return 'audio';
    }
    return VIDEO_EXTENSIONS.has(extension) ? 'video' : null;
}

/** The link text without an "Open audio:" style prefix, or the file name when the text is just the URL. */
export function inlineMediaTitle(text: string, url: string): string {
    const cleaned = text.replace(ACTION_PREFIX, '').trim();
    if (cleaned && cleaned !== url) {
        return cleaned;
    }
    try {
        return decodeURIComponent(new URL(url).pathname.split('/').pop() || '') || 'Media';
    } catch {
        return 'Media';
    }
}

/** `m:ss`, or `h:mm:ss` past an hour, for a playback position in seconds. */
export function formatMediaTime(seconds: number): string {
    if (!Number.isFinite(seconds) || seconds < 0) {
        return '0:00';
    }
    const whole = Math.floor(seconds);
    const hours = Math.floor(whole / 3600);
    const minutes = Math.floor((whole % 3600) / 60);
    const secs = String(whole % 60).padStart(2, '0');
    return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${secs}` : `${minutes}:${secs}`;
}

let activeMedia: HTMLMediaElement | null = null;

/**
 * Make `element` the one piece of media playing, pausing whichever was playing before it.
 *
 * Two recordings talking over each other is never what someone wants when they press play on a
 * second one, and the same goes for a clip started while a recording runs.
 */
export function claimPlayback(element: HTMLMediaElement): void {
    if (activeMedia && activeMedia !== element && !activeMedia.paused) {
        activeMedia.pause();
    }
    activeMedia = element;
}
