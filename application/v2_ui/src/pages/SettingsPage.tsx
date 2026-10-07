// SettingsPage.tsx
// Personal settings: the user's own preferences, activity, workspaces, feedback and violations.
//
// Laid out like Admin Settings so the two read as one design: a left rail of tabs that
// collapses to icons, cards that fill the width of the page, and an "On this page" index on
// the right that lists the cards on the current tab and marks the one in view. Below the
// lg breakpoint the rail becomes a select, as it does on Admin Settings.
//
// The active tab lives in the query string so a particular tab can be linked to and
// survives a reload, which the classic page also supports via ?tab=.
//
// The title says "User Settings" rather than "Settings" because the account menu it is
// reached from offers Admin Settings directly beneath it, and two entries a line apart
// called Settings and Admin Settings would not say which one you had landed on.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { clsx } from 'clsx';
import { Loader2, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { UserAvatar } from '../components/layout/UserAvatar';
import { SettingsIndex } from '../components/admin/SettingsIndex';
import {
    SettingsSectionRegistryContext,
    type SettingsSectionEntry,
} from '../components/settings/SettingsCard';
import { SETTINGS_TABS } from '../components/settings/tabs';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { useUserSettingsStore } from '../stores/userSettingsStore';

/** Orders index entries the way their cards appear on the page. */
function byDocumentPosition(a: SettingsSectionEntry, b: SettingsSectionEntry): number {
    const first = document.getElementById(a.sectionId);
    const second = document.getElementById(b.sectionId);
    if (!first || !second) {
        return 0;
    }
    return first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
}

export function SettingsPage() {
    const [searchParams, setSearchParams] = useSearchParams();
    const features = useBootstrapStore((state) => state.data?.features ?? {});
    const saving = useUserSettingsStore((state) => state.saving);
    const updateUserSettings = useUserSettingsStore((state) => state.update);
    const railCollapsed = useUserSettingsStore(
        (state) => state.settings.v2UserSettingsRailCollapsed === true,
    );
    const scrollRef = useRef<HTMLDivElement>(null);
    const [sections, setSections] = useState<Record<string, SettingsSectionEntry>>({});

    // A tab whose capability is off is hidden rather than shown empty: its endpoints fail
    // in that state, so it could only ever display an error.
    const tabs = useMemo(
        () => SETTINGS_TABS.filter((tab) => !tab.feature || features[tab.feature] === true),
        [features],
    );

    const requested = searchParams.get('tab');
    const active = tabs.find((tab) => tab.id === requested) ?? tabs[0];
    const activeId = active?.id;

    const registry = useMemo(
        () => ({
            register: (entry: SettingsSectionEntry) =>
                setSections((current) => ({ ...current, [entry.sectionId]: entry })),
            unregister: (sectionId: string) =>
                setSections((current) => {
                    if (!(sectionId in current)) {
                        return current;
                    }
                    const next = { ...current };
                    delete next[sectionId];
                    return next;
                }),
        }),
        [],
    );

    const entries = useMemo(
        () => Object.values(sections).sort(byDocumentPosition),
        [sections],
    );
    const grouped = entries.some((entry) => entry.groupId);

    // A new tab starts at its top rather than at the scroll position of the last one.
    useEffect(() => {
        scrollRef.current?.scrollTo({ top: 0 });
    }, [activeId]);

    const jumpToSection = useCallback((sectionId: string) => {
        const card = document.getElementById(sectionId);
        if (!card) {
            return;
        }
        const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
        card.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
        document.getElementById(`${sectionId}-title`)?.focus({ preventScroll: true });
    }, []);

    if (!active) {
        return null;
    }

    const { Component } = active;
    const selectTab = (tabId: string) => setSearchParams({ tab: tabId });

    return (
        <div className="flex h-full min-h-0 flex-col">
            <PageHeader
                leading={<UserAvatar size={36} />}
                title="User Settings"
                description="Preferences for your account in this interface."
                actions={
                    saving ? (
                        <span className="flex items-center gap-1.5 text-xs text-text-3">
                            <Loader2 size={13} className="animate-spin" />
                            Saving
                        </span>
                    ) : undefined
                }
            />

            <div className="flex min-h-0 flex-1">
                <aside
                    aria-label="User settings sections"
                    className={clsx(
                        'hidden shrink-0 overflow-y-auto border-r border-edge transition-[width] motion-reduce:transition-none lg:block',
                        railCollapsed ? 'w-16 px-2 py-3' : 'w-56 p-3',
                    )}
                >
                    <button
                        type="button"
                        onClick={() => updateUserSettings({ v2UserSettingsRailCollapsed: !railCollapsed })}
                        aria-label={railCollapsed ? 'Expand user settings sections' : 'Collapse user settings sections'}
                        aria-expanded={!railCollapsed}
                        aria-controls="user-settings-tab-list"
                        title={railCollapsed ? 'Expand user settings sections' : 'Collapse user settings sections'}
                        className={clsx(
                            'mb-2 flex w-full items-center gap-2 rounded-lg py-1.5 text-xs text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1',
                            railCollapsed ? 'justify-center px-2' : 'px-3',
                        )}
                    >
                        {railCollapsed ? <PanelLeftOpen size={15} aria-hidden="true" /> : (
                            <><PanelLeftClose size={15} aria-hidden="true" /><span>Collapse</span></>
                        )}
                    </button>
                    <nav id="user-settings-tab-list" aria-label="Settings sections" className="space-y-0.5">
                        {tabs.map((tab) => {
                            const Icon = tab.icon;
                            const isActive = tab.id === active.id;
                            return (
                                <button
                                    key={tab.id}
                                    type="button"
                                    aria-current={isActive ? 'page' : undefined}
                                    title={railCollapsed ? tab.label : undefined}
                                    onClick={() => selectTab(tab.id)}
                                    className={clsx(
                                        'flex w-full items-center gap-2.5 rounded-lg py-2.5 text-left text-sm transition-colors',
                                        railCollapsed ? 'justify-center px-2' : 'px-3',
                                        isActive
                                            ? 'bg-accent-soft font-semibold text-accent'
                                            : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
                                    )}
                                >
                                    <Icon
                                        size={16}
                                        aria-hidden="true"
                                        className={clsx('shrink-0', isActive ? 'text-accent' : 'text-text-3')}
                                    />
                                    {/* Collapsed, the label stays as the button's accessible name. */}
                                    <span className={railCollapsed ? 'sr-only' : 'min-w-0 flex-1 truncate'}>{tab.label}</span>
                                </button>
                            );
                        })}
                    </nav>
                </aside>

                <div className="flex min-w-0 flex-1 flex-col">
                    <div className="shrink-0 border-b border-edge px-4 py-3 lg:hidden">
                        <label htmlFor="user-settings-tab" className="mb-1 block text-xs text-text-2">Settings section</label>
                        <select
                            id="user-settings-tab"
                            value={active.id}
                            onChange={(event) => selectTab(event.target.value)}
                            className="w-full max-w-md rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1"
                        >
                            {tabs.map((tab) => (
                                <option key={tab.id} value={tab.id}>{tab.label}</option>
                            ))}
                        </select>
                    </div>

                    <div
                        ref={scrollRef}
                        data-testid="user-settings-scroll"
                        className="@container min-h-0 flex-1 overflow-y-auto px-4 py-4 lg:px-6"
                    >
                        <div className="mx-auto grid w-full max-w-[112rem] items-start gap-6 @min-[76rem]:grid-cols-[minmax(0,1fr)_15rem]">
                            <div data-testid="user-settings-content" className="min-w-0 space-y-4 pb-8">
                                <SettingsSectionRegistryContext.Provider value={registry}>
                                    <Component />
                                </SettingsSectionRegistryContext.Provider>
                            </div>
                            {entries.length > 1 ? (
                                <SettingsIndex
                                    entries={entries}
                                    grouped={grouped}
                                    scrollRoot={scrollRef}
                                    onJump={jumpToSection}
                                    className="hidden @min-[76rem]:block"
                                />
                            ) : null}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}