// latestFeatureShortcuts.ts
// Where a Latest Features shortcut leads from the V2 Support page.
//
// The catalogue in `support_menu_config.py` is written for the classic interface, so its
// shortcuts name classic pages: `/chats#chatbox`, `/workspace#documents-tab`,
// `/profile?tab=stats`. Followed as written, every one of them would drop a V2 reader into the
// classic interface. Where V2 has rebuilt the page, the shortcut is translated to the V2 route;
// where it has not -- workflow activity -- the page opens as written, the
// same choice notificationLinks.ts makes for a notification. Documentation links leave the site
// and open in a new tab.
//
// Every V2 destination is a constant from the tables below, never assembled from the link, so a
// router target can only ever be one of these paths relative to the `/v2` base (#1698). Page and
// external destinations go through `safeLatestFeatureHref`, which refuses anything but a path on
// this site or an http(s) address.
//
// Classic-only behaviour carried in the link -- `feature_action=` opening a dialog, a fragment
// scrolling to a control -- has no V2 counterpart and is dropped. The two tutorial launchers are
// the exception: V2 has guided tours for both pages, so those shortcuts start the matching tour.
//
// Kept free of store and React imports so it can be tested directly.

import { safeLatestFeatureHref } from './latestFeatures';
import { SUPPORT_LATEST_FEATURES_PATH, SUPPORT_SEND_FEEDBACK_PATH } from './supportMenu';

/** A V2 guided tour a shortcut asks the destination page to start. Ids match lib/tours.ts. */
export type LatestFeatureShortcutTour = 'chat' | 'workspace';

/** A shortcut translated to a V2 page, followed by the router. */
export interface LatestFeatureShortcutRoute {
    kind: 'route';
    path: string;
    /** A guided tour to start on arrival. */
    tour?: LatestFeatureShortcutTour;
    /** Arrive at an empty chat rather than the conversation last read, as the rail does. */
    freshChat?: boolean;
}

export type LatestFeatureShortcutTarget =
    | LatestFeatureShortcutRoute
    /** A page on this site V2 has not rebuilt, opened with a full navigation. */
    | { kind: 'page'; href: string }
    /** Another site, opened in a new tab. */
    | { kind: 'external'; href: string };

const CHAT_PATH = '/chat';
const AGENTS_PATH = '/agents';
const WORKSPACE_PATH = '/workspace';
const SETTINGS_PATH = '/settings';
const SETTINGS_STATS_PATH = '/settings?tab=stats';
const SETTINGS_VIOLATIONS_PATH = '/settings?tab=violations';
const GROUPS_PATH = '/groups';
const PUBLIC_PATH = '/public';
const PUBLIC_DIRECTORY_PATH = '/public/directory';
const APPROVALS_PATH = '/approvals';

/** Classic workspace tabs and controls, by fragment, and the V2 section each lives in now. */
const WORKSPACE_FRAGMENT_SECTIONS: Readonly<Record<string, string>> = {
    'documents-tab': '/workspace/documents',
    'documents-table': '/workspace/documents',
    'upload-area': '/workspace/documents',
    'prompts-tab': '/workspace/prompts',
    'agents-tab': '/workspace/agents',
    'plugins-tab': '/workspace/actions',
    'workflows-tab': '/workspace/workflows',
    'identities-tab': '/workspace/identities',
    'endpoints-tab': '/workspace/endpoints',
    'sync-tab': '/workspace/sync',
};

/** Classic workspace `feature_action` values, and the V2 section that does the same job. */
const WORKSPACE_FEATURE_ACTION_SECTIONS: Readonly<Record<string, string>> = {
    document_tag_system: '/workspace/tags',
    workspace_folder_view: '/workspace/documents',
    file_sync: '/workspace/sync',
};

/** Every router path a shortcut may produce. */
const V2_SHORTCUT_PATHS: ReadonlySet<string> = new Set([
    CHAT_PATH,
    AGENTS_PATH,
    WORKSPACE_PATH,
    SETTINGS_PATH,
    SETTINGS_STATS_PATH,
    SETTINGS_VIOLATIONS_PATH,
    GROUPS_PATH,
    PUBLIC_PATH,
    PUBLIC_DIRECTORY_PATH,
    APPROVALS_PATH,
    SUPPORT_LATEST_FEATURES_PATH,
    SUPPORT_SEND_FEEDBACK_PATH,
    ...Object.values(WORKSPACE_FRAGMENT_SECTIONS),
    ...Object.values(WORKSPACE_FEATURE_ACTION_SECTIONS),
]);

/** Parses only to read the parts; the origin is a placeholder no target is built from. */
const PARSE_BASE = 'https://simplechat.invalid';

function route(
    path: string,
    extra: Omit<LatestFeatureShortcutRoute, 'kind' | 'path'> = {},
): LatestFeatureShortcutRoute {
    return { kind: 'route', path, ...extra };
}

function chatTarget(fragment: string): LatestFeatureShortcutRoute {
    return fragment === 'chat-tutorial-launch'
        ? route(CHAT_PATH, { tour: 'chat', freshChat: true })
        : route(CHAT_PATH, { freshChat: true });
}

function workspaceTarget(fragment: string, featureAction: string): LatestFeatureShortcutRoute {
    if (fragment === 'workspace-tutorial-launch') {
        return route(WORKSPACE_PATH, { tour: 'workspace' });
    }
    const section = WORKSPACE_FEATURE_ACTION_SECTIONS[featureAction] ?? WORKSPACE_FRAGMENT_SECTIONS[fragment];
    return route(section ?? WORKSPACE_PATH);
}

function settingsTarget(tab: string): LatestFeatureShortcutRoute {
    if (tab === 'stats') {
        return route(SETTINGS_STATS_PATH);
    }
    if (tab === 'violations') {
        return route(SETTINGS_VIOLATIONS_PATH);
    }
    return route(SETTINGS_PATH);
}

/** The V2 route for a classic path, or null when V2 has not rebuilt that page. */
function v2RouteFor(url: URL): LatestFeatureShortcutRoute | null {
    const path = url.pathname.replace(/(.)\/$/, '$1');
    const fragment = url.hash.replace(/^#/, '');
    const featureAction = url.searchParams.get('feature_action') ?? '';

    switch (path) {
        case '/agents':
            return route(AGENTS_PATH);
        case '/chats':
        case '/chat':
        case '/conversations':
            return chatTarget(fragment);
        case '/workspace':
            return workspaceTarget(fragment, featureAction);
        case '/profile':
            return settingsTarget(url.searchParams.get('tab') ?? '');
        case '/group_workspaces':
            return route(GROUPS_PATH);
        case '/public_workspaces':
            return route(PUBLIC_PATH);
        case '/public_directory':
            return route(PUBLIC_DIRECTORY_PATH);
        case '/approvals':
            return route(APPROVALS_PATH);
        case '/support/latest-features':
            return route(SUPPORT_LATEST_FEATURES_PATH);
        case '/support/send-feedback':
            return route(SUPPORT_SEND_FEEDBACK_PATH);
        default:
            return null;
    }
}

/**
 * Where a shortcut leads from the V2 page, or null when it cannot be followed safely.
 *
 * The server has already dropped shortcuts with no usable destination; this is the browser's
 * own check, because a catalogue entry is data and the page must not trust it into an href.
 */
export function resolveLatestFeatureShortcut(href: unknown): LatestFeatureShortcutTarget | null {
    const safe = safeLatestFeatureHref(href);
    if (!safe) {
        return null;
    }
    if (!safe.startsWith('/')) {
        return { kind: 'external', href: safe };
    }

    let url: URL;
    try {
        url = new URL(safe, PARSE_BASE);
    } catch {
        return null;
    }
    if (url.origin !== PARSE_BASE) {
        return null;
    }
    return v2RouteFor(url) ?? { kind: 'page', href: safe };
}

/**
 * The router path for a translated shortcut: always one of the allowlisted V2 destinations.
 *
 * A path that is not on the list -- which only a caller bypassing the resolver could hand in --
 * falls back to the Latest Features page itself rather than reaching the router.
 */
export function safeShortcutRouteHref(path: string): string {
    return V2_SHORTCUT_PATHS.has(path) ? path : SUPPORT_LATEST_FEATURES_PATH;
}
