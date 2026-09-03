// NavExtras.tsx
// Administrator-configured navigation groups in the rail: custom pages and external links.
//
// Both exist in the classic navigation and neither had reached V2, so a deployment that
// had configured either saw a rail with none of its own links in it. The entries come from
// the bootstrap payload, already filtered for the signed-in user, and the rules deciding
// what renders live in lib/navigationGroups so they can be tested directly.
//
// Each group's heading collapses it, and that choice is remembered per user in the
// `sidebarMenuState` setting the classic interface already owns, so putting a group away
// survives a reload and applies in both interfaces.
//
// Destinations are server-rendered pages and third-party sites, not client-side routes, so
// these are plain anchors rather than react-router links. A NavLink would try to resolve
// them inside the SPA and land on the home page.

import { useState } from 'react';
import { clsx } from 'clsx';
import { ChevronDown, ExternalLink, FileText } from 'lucide-react';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import {
    isGroupVisible,
    toCustomPageLinks,
    toExternalLinks,
    type NavExtraLink,
} from '../../lib/navigationGroups';
import {
    readSidebarMenuExpanded,
    withSidebarMenuExpanded,
    type SidebarMenuKey,
} from '../../lib/sidebarMenuState';

function NavAnchor({ link, collapsed }: { link: NavExtraLink; collapsed: boolean }) {
    return (
        <a
            href={link.href}
            title={link.label}
            {...(link.newTab ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
            className={clsx(
                'flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm transition-colors',
                'text-text-2 hover:bg-surface-2 hover:text-text-1',
                collapsed && 'justify-center px-0',
            )}
        >
            {link.newTab ? (
                <ExternalLink size={15} className="shrink-0" />
            ) : (
                <FileText size={15} className="shrink-0" />
            )}
            {!collapsed && <span className="truncate">{link.label}</span>}
        </a>
    );
}

function NavExtraGroup({
    menuName,
    links,
    stateKey,
    collapsed,
}: {
    menuName: string;
    links: NavExtraLink[];
    /** Where this group's expanded state is stored, shared with the classic interface. */
    stateKey: SidebarMenuKey;
    collapsed: boolean;
}) {
    const storedState = useUserSettingsStore((state) => state.settings.sidebarMenuState);
    const settingsLoading = useUserSettingsStore((state) => state.loading);
    /**
     * The state of a toggle made before preferences finished loading.
     *
     * Null means "no local opinion", so the stored value governs — which is the normal case.
     * It is only set while the settings request is still in flight, and cleared as soon as a
     * toggle is actually written, so a save that fails rolls the heading back with the rest
     * of the store rather than leaving it showing a state nobody kept.
     */
    const [pendingExpanded, setPendingExpanded] = useState<boolean | null>(null);

    if (!links.length) {
        return null;
    }

    // The collapsed rail is an icon strip with no room for a heading, so a menu there
    // would hide its contents behind a label nobody can read, with no visible control to
    // get them back. Entries stay flat instead.
    if (collapsed) {
        return (
            <ul className="mt-1 space-y-0.5 px-3">
                {links.map((link) => (
                    <li key={link.key}>
                        <NavAnchor link={link} collapsed />
                    </li>
                ))}
            </ul>
        );
    }

    const expanded = pendingExpanded ?? readSidebarMenuExpanded(storedState, stateKey);
    const listId = `nav-extra-${menuName.replace(/\W+/g, '-').toLowerCase()}`;

    const toggle = () => {
        const next = !expanded;

        // Preferences resolve moments after the rail mounts, and merging into an object that
        // has not arrived yet would post a state missing the classic interface's own menus.
        // The toggle still takes effect locally; only the write waits for a click made
        // afterwards.
        if (settingsLoading) {
            setPendingExpanded(next);
            return;
        }

        const settingsStore = useUserSettingsStore.getState();
        settingsStore.update({
            sidebarMenuState: withSidebarMenuExpanded(
                settingsStore.settings.sidebarMenuState,
                stateKey,
                next,
            ),
        });
        // The store applies the change immediately, so it is now the value on screen.
        setPendingExpanded(null);
    };

    return (
        <div className="mt-3 px-3">
            <button
                type="button"
                onClick={toggle}
                aria-expanded={expanded}
                aria-controls={listId}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-1 text-xs font-semibold tracking-wide text-text-3 uppercase transition-colors hover:text-text-1"
            >
                <span className="min-w-0 flex-1 truncate text-left">{menuName}</span>
                <span className="rounded-full bg-surface-sunken px-1.5 text-[10px] leading-4 font-semibold text-text-3">
                    {links.length}
                </span>
                <ChevronDown
                    size={13}
                    className={clsx('shrink-0 transition-transform', !expanded && '-rotate-90')}
                />
            </button>

            {expanded && (
                <ul id={listId} className="mt-0.5 space-y-0.5">
                    {links.map((link) => (
                        <li key={link.key}>
                            <NavAnchor link={link} collapsed={false} />
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}

export function NavExtras({ collapsed }: { collapsed: boolean }) {
    const navigation = useBootstrapStore((state) => state.data?.navigation);

    const customPages = navigation?.custom_pages;
    const externalLinks = navigation?.external_links;

    const showCustomPages = isGroupVisible(customPages);
    const showExternalLinks = isGroupVisible(externalLinks);

    if (!showCustomPages && !showExternalLinks) {
        return null;
    }

    return (
        <>
            {showCustomPages && customPages ? (
                <NavExtraGroup
                    menuName={customPages.menu_name}
                    links={toCustomPageLinks(customPages)}
                    stateKey="customPages"
                    collapsed={collapsed}
                />
            ) : null}

            {showExternalLinks && externalLinks ? (
                <NavExtraGroup
                    menuName={externalLinks.menu_name}
                    links={toExternalLinks(externalLinks)}
                    stateKey="externalLinks"
                    collapsed={collapsed}
                />
            ) : null}
        </>
    );
}
