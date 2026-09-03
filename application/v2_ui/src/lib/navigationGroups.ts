// navigationGroups.ts
// Rules for the administrator-configured navigation groups in the rail.
//
// Kept out of the component so the decisions can be executed by a test. Whether a group
// appears at all is configuration behaviour rather than presentation, and getting it wrong
// is invisible in review: a group that never renders looks exactly like one nobody
// configured.
//
// The classic navigation additionally decides between an inline heading and a named menu
// from the entry count, with "Force Menu Display" overriding it. V2 has no equivalent rule
// because every group is a menu here: a heading that collapses only past some threshold
// means the same control behaves differently for two deployments that differ by one link.

import type { CustomPageNavItem, ExternalLinkNavItem, NavGroup } from './types';

/**
 * Whether a group has anything to show.
 *
 * A group that is switched on but empty would render as a heading with nothing under it,
 * which reads as a broken menu rather than as an unused capability.
 */
export function isGroupVisible<TItem>(group: NavGroup<TItem> | undefined | null): boolean {
    return Boolean(group?.enabled && group.items?.length);
}

/** One rendered rail entry, flattened from either group. */
export interface NavExtraLink {
    key: string;
    label: string;
    href: string;
    /** Opens away from the SPA. Always true for external links. */
    newTab: boolean;
}

export function toCustomPageLinks(
    group: NavGroup<CustomPageNavItem> | undefined | null,
): NavExtraLink[] {
    return (group?.items ?? []).map((page) => ({
        key: `custom-page:${page.slug}`,
        label: page.label || page.slug,
        href: page.url,
        newTab: Boolean(page.open_in_new_tab),
    }));
}

export function toExternalLinks(
    group: NavGroup<ExternalLinkNavItem> | undefined | null,
): NavExtraLink[] {
    return (group?.items ?? []).map((link, index) => ({
        // Labels and URLs are both administrator-supplied and may repeat, so the position
        // is the only identity guaranteed to be unique.
        key: `external-link:${index}:${link.url}`,
        label: link.label,
        href: link.url,
        // External destinations always open in a new tab, matching the classic rail: they
        // leave the application, and losing an in-progress conversation to a policy link
        // would be a poor trade.
        newTab: true,
    }));
}
