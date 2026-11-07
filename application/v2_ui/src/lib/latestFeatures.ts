// latestFeatures.ts
// The Latest Features catalogues the V2 Help group draws, and the rules applied to them.
//
// `GET /api/v2/admin/latest-features` serves two release catalogues the server has
// already resolved (`functions_support_latest_features.py`): what administrators read on
// Admin Latest Features, and what end users see on the Support menu's Latest Features page.
// `GET /api/v2/support/latest-features` serves end users the same announcement shape, but
// only what an administrator shared, with each shortcut already filtered by the server.
// The decisions kept here are the ones worth testing rather than reading by eye: which
// announcements are shared, which shortcuts a user would really see given the settings
// being edited, and where an admin shortcut lands in V2.

import { apiUrl } from './apiClient';
import { asBoolean } from './adminFields';
import type { AdminNavGroup } from './types';

export interface LatestFeatureImage {
    url: string;
    alt: string;
    title: string;
    caption: string;
    label: string;
}

/** How a shortcut is followed. Mirrors `ACTION_KIND_*` in the payload builder. */
export type LatestFeatureActionKind = 'admin' | 'page' | 'external';

export interface LatestFeatureAction {
    label: string;
    description: string;
    icon: string;
    kind: LatestFeatureActionKind;
    /** The server-rendered destination; for `admin`, the classic tab. */
    href: string;
    /** `admin` only: the live tab id, legacy aliases already resolved by the server. */
    admin_tab?: string;
    /** `admin` only: a section or element id on that tab, when the shortcut names one. */
    admin_section?: string | null;
    /** Settings that must all be on for a user to see this shortcut. */
    requires_settings: string[];
}

export interface LatestFeature {
    id: string;
    title: string;
    icon: string;
    summary: string;
    details: string;
    why: string;
    guidance: string[];
    images: LatestFeatureImage[];
    actions: LatestFeatureAction[];
    /** User catalogue only: whether the announcement is shared before anyone chooses. */
    default_visible?: boolean;
}

export interface LatestFeatureGroup {
    id: string;
    label: string;
    description: string;
    release_version: string;
    default_expanded: boolean;
    features: LatestFeature[];
}

export interface LatestFeaturesPayload {
    version: string;
    admin: LatestFeatureGroup[];
    user: LatestFeatureGroup[];
}

/** Where the Support menu's Latest Features page reads what users were given. */
export const USER_LATEST_FEATURES_ENDPOINT = '/api/v2/support/latest-features';

/**
 * `GET /api/v2/support/latest-features`: only the shared announcements, and only the
 * shortcuts the stored settings allow. A release group with nothing shared is absent.
 */
export interface UserLatestFeaturesPayload {
    version: string;
    groups: LatestFeatureGroup[];
}

/** The settings key the user-facing choices are saved under. */
export const LATEST_FEATURES_VISIBILITY_KEY = 'support_latest_features_visibility';

/** The `render` value of the Admin Latest Features navigation tab. */
export const LATEST_FEATURES_RENDER = 'latest_features';

/** Every announcement in a set of release groups, in order. */
export function allFeatures(groups: LatestFeatureGroup[]): LatestFeature[] {
    return groups.flatMap((group) => group.features);
}

/**
 * Read the stored choices the way the user Latest Features page does.
 *
 * An announcement the stored map does not mention -- one added by a later release -- is
 * shared or not by its catalogue default, exactly as `normalize_support_latest_features_
 * visibility` decides on the server. The result names every announcement in the catalogue,
 * which is also the shape written back, so a save never depends on what the stored map
 * happened to contain.
 */
export function readVisibility(
    value: unknown,
    groups: LatestFeatureGroup[],
): Record<string, boolean> {
    const stored =
        value && typeof value === 'object' && !Array.isArray(value)
            ? (value as Record<string, unknown>)
            : {};
    const visibility: Record<string, boolean> = {};
    for (const feature of allFeatures(groups)) {
        visibility[feature.id] = Object.prototype.hasOwnProperty.call(stored, feature.id)
            ? asBoolean(stored[feature.id])
            : feature.default_visible ?? true;
    }
    return visibility;
}

/** How many of the given announcements are shared. */
export function countShared(
    visibility: Record<string, boolean>,
    features: LatestFeature[],
): number {
    return features.filter((feature) => visibility[feature.id]).length;
}

/**
 * Whether a user would see a shortcut, judged against the settings being edited.
 *
 * The server filters shortcuts against the stored settings when it renders the user
 * page. The preview filters against the draft instead, so the documentation guide buttons
 * appear the moment their switch is flipped rather than after a save.
 */
export function isActionShown(
    action: LatestFeatureAction,
    read: (key: string) => unknown,
): boolean {
    return action.requires_settings.every((key) => asBoolean(read(key)));
}

/** Everything about an announcement a page search can match. */
export function featureSearchText(feature: LatestFeature): string {
    return [feature.title, feature.summary, feature.details, feature.why, ...feature.guidance]
        .join(' ')
        .toLowerCase();
}

/** Search text for whole catalogues, so the page search finds a card by its content. */
export function catalogueSearchText(groups: LatestFeatureGroup[]): string {
    return allFeatures(groups).map(featureSearchText).join(' ');
}

/**
 * Narrow release groups to the announcements matching a search.
 *
 * An empty search returns the groups unchanged. A group left with nothing to show is
 * dropped, so a search never draws an empty release heading.
 */
export function filterGroups(groups: LatestFeatureGroup[], query: string): LatestFeatureGroup[] {
    const needle = query.trim().toLowerCase();
    if (!needle) {
        return groups;
    }
    return groups
        .map((group) => ({
            ...group,
            features: group.features.filter((feature) =>
                featureSearchText(feature).includes(needle),
            ),
        }))
        .filter((group) => group.features.length > 0);
}

/** The element id the classic page gives an announcement card, reused so links line up. */
export function latestFeatureCardId(featureId: string): string {
    return `latest-features-${featureId.replace(/_/g, '-')}-card`;
}

/** Where an admin shortcut lands. */
export type AdminActionTarget =
    | { kind: 'section'; sectionId: string }
    | { kind: 'classic'; tab: string };

/**
 * Resolve an admin shortcut to a card V2 draws, or to the classic tab when it draws none.
 *
 * A named section wins when V2 renders it. Shortcuts often name an element inside a classic
 * pane rather than a navigation section -- `plugins-table`, `model-endpoints-wrapper` -- so
 * those fall through to the first card V2 draws for the tab. A tab V2 does not draw at all,
 * such as Backup, opens on the classic page, which is where that work still lives.
 */
export function resolveAdminActionTarget(
    action: Pick<LatestFeatureAction, 'admin_tab' | 'admin_section'>,
    nav: AdminNavGroup[],
    renderedSectionIds: ReadonlySet<string>,
): AdminActionTarget {
    const tabId = action.admin_tab ?? '';
    if (action.admin_section && renderedSectionIds.has(action.admin_section)) {
        return { kind: 'section', sectionId: action.admin_section };
    }

    for (const group of nav) {
        const tab = group.tabs.find((candidate) => candidate.id === tabId);
        if (!tab) {
            continue;
        }
        if (tab.render === LATEST_FEATURES_RENDER && renderedSectionIds.has(tab.id)) {
            return { kind: 'section', sectionId: tab.id };
        }
        const section = tab.sections.find((candidate) => renderedSectionIds.has(candidate.id));
        if (section) {
            return { kind: 'section', sectionId: section.id };
        }
        break;
    }

    return { kind: 'classic', tab: tabId };
}

/** Browsers resolve `.`/`..` segments, including percent-encoded dots, and read `\` as `/`. */
const DOT_SEGMENT = /\/(?:\.|%2e){1,2}(?:[/?#]|$)/i;

/**
 * A shortcut destination the browser may follow: a path on this application, or an
 * absolute http(s) address. Anything else, including a script URL, is refused.
 */
export function safeLatestFeatureHref(href: unknown): string | undefined {
    if (typeof href !== 'string' || href.includes('\\')) {
        return undefined;
    }
    if (/^https?:\/\/[^\s/]/i.test(href)) {
        return href;
    }
    if (href.startsWith('/') && !href.startsWith('//') && !DOT_SEGMENT.test(href)) {
        return href;
    }
    return undefined;
}

/** A screenshot served from the application's static files, or undefined. */
export function safeLatestFeatureImageUrl(url: unknown): string | undefined {
    if (
        typeof url !== 'string' ||
        !url.startsWith('/static/') ||
        url.includes('\\') ||
        DOT_SEGMENT.test(url)
    ) {
        return undefined;
    }
    return apiUrl(url);
}

/** The classic Admin Settings tab, for a shortcut V2 cannot follow in place. */
export function safeClassicAdminTabHref(tab: string): string {
    return `/admin/settings#${encodeURIComponent(tab)}`;
}
