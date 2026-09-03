// NavExtras.tsx
// Administrator-configured navigation groups in the rail: custom pages and external links.
//
// Both exist in the classic navigation and neither had reached V2, so a deployment that
// had configured either saw a rail with none of its own links in it. The entries come from
// the bootstrap payload, already filtered for the signed-in user, and the rules deciding
// what renders live in lib/navigationGroups so they can be tested directly.
//
// Destinations are server-rendered pages and third-party sites, not client-side routes, so
// these are plain anchors rather than react-router links. A NavLink would try to resolve
// them inside the SPA and land on the home page.

import { useState } from 'react';
import { clsx } from 'clsx';
import { ChevronDown, ExternalLink, FileText } from 'lucide-react';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import {
    isGroupVisible,
    shouldRenderAsMenu,
    toCustomPageLinks,
    toExternalLinks,
    type NavExtraLink,
} from '../../lib/navigationGroups';

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
    forceMenu,
    collapsed,
}: {
    menuName: string;
    links: NavExtraLink[];
    forceMenu: boolean;
    collapsed: boolean;
}) {
    const asMenu = shouldRenderAsMenu(links.length, forceMenu);
    const [open, setOpen] = useState(true);

    if (!links.length) {
        return null;
    }

    // The collapsed rail is an icon strip with no room for a heading, so a menu there
    // would hide its contents behind a label nobody can read. Entries stay flat instead.
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

    const listId = `nav-extra-${menuName.replace(/\W+/g, '-').toLowerCase()}`;

    return (
        <div className="mt-3 px-3">
            {asMenu ? (
                <button
                    type="button"
                    onClick={() => setOpen((isOpen) => !isOpen)}
                    aria-expanded={open}
                    aria-controls={listId}
                    className="flex w-full items-center gap-2 rounded-lg px-3 py-1 text-xs font-semibold tracking-wide text-text-3 uppercase transition-colors hover:text-text-1"
                >
                    <span className="min-w-0 flex-1 truncate text-left">{menuName}</span>
                    <span className="rounded-full bg-surface-sunken px-1.5 text-[10px] leading-4 font-semibold text-text-3">
                        {links.length}
                    </span>
                    <ChevronDown
                        size={13}
                        className={clsx('shrink-0 transition-transform', !open && '-rotate-90')}
                    />
                </button>
            ) : (
                <p className="px-3 py-1 text-xs font-semibold tracking-wide text-text-3 uppercase">
                    {menuName}
                </p>
            )}

            {(!asMenu || open) && (
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
                    forceMenu={customPages.force_menu}
                    collapsed={collapsed}
                />
            ) : null}

            {showExternalLinks && externalLinks ? (
                <NavExtraGroup
                    menuName={externalLinks.menu_name}
                    links={toExternalLinks(externalLinks)}
                    forceMenu={externalLinks.force_menu}
                    collapsed={collapsed}
                />
            ) : null}
        </>
    );
}
