// customPageEmbed.ts
// Rules for showing a custom page inside V2, kept out of the component so they can be run.
//
// A custom page is a trusted, server-rendered document: static HTML, CSS and JavaScript, or a
// Python-backed template. It cannot be written again as a React page, so V2 shows the copy the
// server renders without the classic navigation, `/custom/<slug>?embed=1`, in a frame of its
// own content pane. The rail stays on screen and the page runs exactly as it does in the classic
// shell. Everything that can go wrong sits between those two documents: which pages may be
// framed, how the host learns the page really rendered, and how the page learns the theme.
//
// The two documents are the same origin, so the conversation is two messages and both ends
// check the origin and the sender. `simplechat-custom-page-ready` is sent by the page once it
// has been parsed. The frame's own `load` event cannot say that, because the browser fires it
// for a 403, a 404 and a server error page as well, so the host would otherwise show an error
// page as if it were the content.

import { SLUG_PATTERN } from './customPages';
import type { CustomPageNavItem, NavGroup } from './types';

/** Longest slug the server accepts (`SLUG_PATTERN` in `functions_custom_pages.py`). */
export const CUSTOM_PAGE_SLUG_MAX_LENGTH = 64;

/** Sent by the embedded page to its parent once it has been parsed. */
export const CUSTOM_PAGE_READY_MESSAGE = 'simplechat-custom-page-ready';
/** Sent by the host to the embedded page when the theme changes. */
export const CUSTOM_PAGE_THEME_MESSAGE = 'simplechat-theme';

/**
 * How long a page that has finished loading may stay silent before it counts as not rendered.
 *
 * The page sends its message while it is still being parsed, long before the frame's `load`
 * event, so a healthy page is never close to this. The margin covers a main thread that is
 * busy when the message is queued.
 */
export const CUSTOM_PAGE_READY_GRACE_MS = 3_000;
/** How long a frame may go without firing `load` at all, for a server that never answers. */
export const CUSTOM_PAGE_LOAD_TIMEOUT_MS = 30_000;

export type CustomPageTheme = 'light' | 'dark';

export function isValidCustomPageSlug(value: unknown): value is string {
    return (
        typeof value === 'string' &&
        value.length <= CUSTOM_PAGE_SLUG_MAX_LENGTH &&
        SLUG_PATTERN.test(value)
    );
}

/**
 * The page's V2 route, relative to the router's `/v2` base. Falls back to the home page.
 *
 * Named `safe...Href` so a router link built from it passes the XSS sink check: the value is a
 * path from a literal prefix and one encoded segment, never a full URL.
 */
export function safeCustomPageHref(slug: string): string {
    return isValidCustomPageSlug(slug) ? `/custom/${encodeURIComponent(slug)}` : '/';
}

/** What the frame loads: the chrome-less copy, from the site root. Empty for an invalid slug. */
export function safeCustomPageEmbedSrc(slug: string): string {
    return isValidCustomPageSlug(slug) ? `/custom/${encodeURIComponent(slug)}?embed=1` : '';
}

/**
 * Where "Open in a new tab" goes for a page V2 frames: the same chrome-less document the frame
 * loads, on its own. Empty for an invalid slug.
 *
 * It is not the page's classic address. When the modern interface is selected the server sends
 * `/custom/<slug>` for a page V2 can host to this page's V2 route, so that link would open the
 * host a second time, and from the failure panel it would only load the failing frame again.
 * `embed=1` is the one query the redirect never touches (`classic_only_query` in the route
 * registry), so the new tab shows the page by itself, with the slim bar that links back, or the
 * real error when the page cannot be shown. It reuses the frame's address so the two cannot drift.
 */
export function safeCustomPageStandaloneHref(slug: string): string {
    return safeCustomPageEmbedSrc(slug);
}

/**
 * The page's classic address, for the pages V2 does not frame: one that asks for its own tab, one
 * the server did not mark embeddable, and any page when V2 is hosted on another origin. Empty for
 * an invalid slug.
 */
export function safeCustomPageUrl(slug: string): string {
    return isValidCustomPageSlug(slug) ? `/custom/${encodeURIComponent(slug)}` : '';
}

/**
 * Whether a navigation entry opens inside V2 rather than leaving it.
 *
 * The page has to be embeddable and not ask for its own tab, and the slug has to be one V2 can
 * put in an address. `embedAvailable` is false when the interface is served from a different
 * origin than the API: the frame would then be cross-origin, which the server refuses to frame
 * and the page's session cookie would not reach.
 */
export function opensInsideV2(page: CustomPageNavItem, embedAvailable = true): boolean {
    return (
        embedAvailable &&
        page.embeddable === true &&
        !page.open_in_new_tab &&
        isValidCustomPageSlug(page.slug)
    );
}

/** The navigation block of the bootstrap payload, as far as custom pages are concerned. */
interface CustomPageNavigation {
    custom_pages?: NavGroup<CustomPageNavItem> | null;
}

export type CustomPageHostView =
    | { kind: 'unavailable' }
    | { kind: 'new-tab'; page: CustomPageNavItem; reason: 'not-embeddable' | 'own-tab' | 'cross-origin' }
    | { kind: 'frame'; page: CustomPageNavItem };

/**
 * Decide what the host page shows for a slug.
 *
 * A page that is not in the signed-in user's navigation is unavailable, whatever the reason:
 * the navigation list is already filtered per page against the caller's roles and against the
 * page being enabled, so a slug missing from it is not one this user can open. The server still
 * answers 403 or 404 for the address itself, and the frame reports that case separately.
 */
export function resolveCustomPageHost(
    slug: string | undefined,
    navigation: CustomPageNavigation | null | undefined,
    embedAvailable = true,
): CustomPageHostView {
    if (!isValidCustomPageSlug(slug)) {
        return { kind: 'unavailable' };
    }

    const group = navigation?.custom_pages;
    const page = group?.enabled ? group.items?.find((item) => item.slug === slug) : undefined;
    if (!page) {
        return { kind: 'unavailable' };
    }

    if (page.open_in_new_tab) {
        return { kind: 'new-tab', page, reason: 'own-tab' };
    }
    if (page.embeddable !== true) {
        return { kind: 'new-tab', page, reason: 'not-embeddable' };
    }
    if (!embedAvailable) {
        return { kind: 'new-tab', page, reason: 'cross-origin' };
    }
    return { kind: 'frame', page };
}

/** The message that tells the page which theme to draw. */
export function customPageThemeMessage(theme: CustomPageTheme): { type: string; theme: CustomPageTheme } {
    return { type: CUSTOM_PAGE_THEME_MESSAGE, theme };
}

/**
 * Whether a window message is the embedded page reporting that it rendered.
 *
 * It must come from this site and from the frame the host created. A message from any other
 * window, including another frame on the page, is not the page's.
 */
export function isCustomPageReadyMessage(
    event: { origin: string; source: unknown; data: unknown },
    frameWindow: unknown,
    origin: string,
): boolean {
    if (!frameWindow || event.source !== frameWindow || event.origin !== origin) {
        return false;
    }
    const data = event.data as { type?: unknown } | null;
    return typeof data === 'object' && data !== null && data.type === CUSTOM_PAGE_READY_MESSAGE;
}

/**
 * Where a framed page stands.
 *
 * `loading` until the page reports it rendered. `failed` once it has not, and a page that
 * reports late recovers, because a slow server is not a broken one.
 */
export type CustomPageFrameStatus = 'loading' | 'ready' | 'failed';
export type CustomPageFrameEvent = 'ready' | 'timeout' | 'retry';

export function nextCustomPageFrameStatus(
    status: CustomPageFrameStatus,
    event: CustomPageFrameEvent,
): CustomPageFrameStatus {
    switch (event) {
        case 'ready':
            return 'ready';
        case 'timeout':
            // A page that is already showing is never taken down by a stale timer.
            return status === 'loading' ? 'failed' : status;
        case 'retry':
            return 'loading';
        default:
            return status;
    }
}
