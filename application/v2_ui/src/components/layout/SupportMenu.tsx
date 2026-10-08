// SupportMenu.tsx
// The Support menu in the rail: Latest Features and Send Feedback.
//
// Administrators configure this menu in Admin Settings, and the classic navigation has long
// offered it to users as a collapsible section. V2 used to carry only a Latest Features link
// that left for the classic page, and no way to send feedback at all. Both destinations are now
// V2 pages, so these are router links rather than plain anchors.
//
// What the deployment offers comes from the bootstrap payload, already narrowed to this user;
// which entries show is decided in lib/supportMenu.ts, which also applies the user's own choice
// to hide Latest Features until the next release. Hiding saves the running version, exactly as
// the classic control does, so the entry stays away until the next release and both interfaces
// agree. Preferences can bring it back.
//
// The heading collapses the group, and that choice is stored in the `support` entry of the
// per-user `sidebarMenuState` setting the classic interface already owns, so putting the menu
// away survives a reload and applies in both interfaces.
//
// `SupportMenuView` draws the menu from plain props; `SupportMenu` reads the stores. The split
// keeps the drawing testable without a running application.

import { useState } from 'react';
import { NavLink } from 'react-router-dom';
import { clsx } from 'clsx';
import { ChevronDown, EyeOff, Mail, Zap } from 'lucide-react';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import { readSidebarMenuExpanded, withSidebarMenuExpanded } from '../../lib/sidebarMenuState';
import {
    resolveSupportMenu,
    SUPPORT_LATEST_FEATURES_PATH,
    SUPPORT_SEND_FEEDBACK_PATH,
    type SupportMenuState,
} from '../../lib/supportMenu';

const MENU_STATE_KEY = 'support';
const LIST_ID = 'support-menu-links';

function entryClass(collapsed: boolean) {
    return ({ isActive }: { isActive: boolean }) =>
        clsx(
            'flex min-w-0 flex-1 items-center gap-2.5 rounded-xl px-3 py-2 text-sm transition-colors',
            collapsed && 'justify-center px-0',
            isActive
                ? 'bg-accent-soft font-medium text-accent'
                : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
        );
}

export function SupportMenuView({
    menu,
    collapsed,
    expanded,
    onToggle,
    onHideLatestFeatures,
}: {
    menu: SupportMenuState;
    /** Whether the rail is the collapsed icon strip. */
    collapsed: boolean;
    /** Whether the user has the menu open. */
    expanded: boolean;
    onToggle: () => void;
    onHideLatestFeatures: () => void;
}) {
    if (!menu.visible) {
        return null;
    }

    // The collapsed rail is an icon strip with no room for a heading, so the entries stay flat
    // there, as the other link groups do.
    if (collapsed) {
        return (
            <ul className="mt-1 space-y-0.5 px-3" data-testid="support-menu">
                {menu.showLatestFeatures && (
                    <li data-tour="latest-features">
                        <NavLink
                            to={SUPPORT_LATEST_FEATURES_PATH}
                            title="Latest Features"
                            aria-label="Latest Features"
                            className={entryClass(true)}
                        >
                            {/* A lightning bolt, as in the classic menu. The sparkle is Agents'. */}
                            <Zap size={15} aria-hidden="true" className="shrink-0" />
                        </NavLink>
                    </li>
                )}
                {menu.showSendFeedback && (
                    <li>
                        <NavLink
                            to={SUPPORT_SEND_FEEDBACK_PATH}
                            title="Send Feedback"
                            aria-label="Send Feedback"
                            className={entryClass(true)}
                        >
                            <Mail size={15} aria-hidden="true" className="shrink-0" />
                        </NavLink>
                    </li>
                )}
            </ul>
        );
    }

    return (
        <div className="mt-3 px-3" data-testid="support-menu">
            <button
                type="button"
                onClick={onToggle}
                aria-expanded={expanded}
                aria-controls={LIST_ID}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-1 text-xs font-semibold tracking-wide text-text-3 uppercase transition-colors hover:text-text-1"
            >
                <span className="min-w-0 flex-1 truncate text-left">{menu.menuName}</span>
                <ChevronDown
                    size={13}
                    aria-hidden="true"
                    className={clsx('shrink-0 transition-transform', !expanded && '-rotate-90')}
                />
            </button>

            {expanded && (
                <ul id={LIST_ID} className="mt-0.5 space-y-0.5">
                    {menu.showLatestFeatures && (
                        <li className="group/latest flex items-center gap-1" data-tour="latest-features">
                            <NavLink to={SUPPORT_LATEST_FEATURES_PATH} className={entryClass(false)}>
                                <Zap size={15} aria-hidden="true" className="shrink-0" />
                                <span className="truncate">Latest Features</span>
                                <span className="rounded-full bg-accent px-1.5 text-[10px] leading-4 font-semibold text-on-accent">
                                    New
                                </span>
                            </NavLink>
                            <button
                                type="button"
                                onClick={onHideLatestFeatures}
                                title="Hide until the next release"
                                aria-label="Hide Latest Features until the next release"
                                className="shrink-0 rounded-lg p-1.5 text-text-3 opacity-0 transition-opacity group-hover/latest:opacity-100 hover:bg-surface-2 hover:text-text-1 focus-visible:opacity-100"
                            >
                                <EyeOff size={14} aria-hidden="true" />
                            </button>
                        </li>
                    )}
                    {menu.showSendFeedback && (
                        <li>
                            <NavLink to={SUPPORT_SEND_FEEDBACK_PATH} className={entryClass(false)}>
                                <Mail size={15} aria-hidden="true" className="shrink-0" />
                                <span className="truncate">Send Feedback</span>
                            </NavLink>
                        </li>
                    )}
                </ul>
            )}
        </div>
    );
}

export function SupportMenu({ collapsed }: { collapsed: boolean }) {
    const navigation = useBootstrapStore((state) => state.data?.navigation);
    const version = useBootstrapStore((state) => state.data?.version ?? '');
    const hiddenVersion = useUserSettingsStore(
        (state) => state.settings.latestFeaturesHiddenVersion,
    );
    const storedState = useUserSettingsStore((state) => state.settings.sidebarMenuState);
    const settingsLoading = useUserSettingsStore((state) => state.loading);
    // Set only when the startup read of preferences failed, which leaves the store holding none.
    const settingsLoadFailed = useUserSettingsStore((state) => state.error !== null);
    const update = useUserSettingsStore((state) => state.update);
    /**
     * The menu's state when it cannot be saved. Null means the stored value governs.
     *
     * With no preferences loaded, a write would carry a `sidebarMenuState` holding only this
     * entry, and the server merges top-level keys only, so it would replace the stored object
     * and erase every other menu's choice in both interfaces. The heading still works; the
     * choice just lasts until the page reloads.
     */
    const [localExpanded, setLocalExpanded] = useState<boolean | null>(null);

    // Waiting for preferences avoids flashing a Latest Features entry the user already hid.
    if (settingsLoading) {
        return null;
    }

    const expanded = localExpanded ?? readSidebarMenuExpanded(storedState, MENU_STATE_KEY);

    const toggle = () => {
        const next = !expanded;
        if (settingsLoadFailed) {
            setLocalExpanded(next);
            return;
        }
        // The whole stored object is written back with only this entry changed, read from the
        // store at the moment of the click, which keeps the classic interface's menus intact
        // (lib/sidebarMenuState.ts).
        const current = useUserSettingsStore.getState().settings.sidebarMenuState;
        update({ sidebarMenuState: withSidebarMenuExpanded(current, MENU_STATE_KEY, next) });
        setLocalExpanded(null);
    };

    return (
        <SupportMenuView
            menu={resolveSupportMenu(navigation, hiddenVersion, version)}
            collapsed={collapsed}
            expanded={expanded}
            onToggle={toggle}
            onHideLatestFeatures={() => update({ latestFeaturesHiddenVersion: version })}
        />
    );
}
