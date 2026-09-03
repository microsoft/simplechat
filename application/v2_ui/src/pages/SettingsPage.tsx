// SettingsPage.tsx
// Personal settings: the user's own preferences, workspaces, feedback and violations.
//
// The classic profile page nests these behind six Bootstrap tabs. The structure is kept —
// people know where things are — but the tabs become a slim vertical rail, matching the
// left-rail-only shape of the rest of this interface and leaving the content pane free.
//
// The active tab lives in the query string so a particular tab can be linked to and
// survives a reload, which the classic page also supports via ?tab=.
//
// The title says "User Settings" rather than "Settings" because the account menu it is
// reached from offers Admin Settings directly beneath it, and two entries a line apart
// called Settings and Admin Settings would not say which one you had landed on.

import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { clsx } from 'clsx';
import { Loader2 } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { UserAvatar } from '../components/layout/UserAvatar';
import { SETTINGS_TABS } from '../components/settings/tabs';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { useUserSettingsStore } from '../stores/userSettingsStore';

export function SettingsPage() {
    const [searchParams, setSearchParams] = useSearchParams();
    const features = useBootstrapStore((state) => state.data?.features ?? {});
    const saving = useUserSettingsStore((state) => state.saving);

    // A tab whose capability is off is hidden rather than shown empty: its endpoints fail
    // in that state, so it could only ever display an error.
    const tabs = useMemo(
        () => SETTINGS_TABS.filter((tab) => !tab.feature || features[tab.feature] === true),
        [features],
    );

    const requested = searchParams.get('tab');
    const active = tabs.find((tab) => tab.id === requested) ?? tabs[0];

    if (!active) {
        return null;
    }

    const { Component } = active;

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

            <div className="flex min-h-0 flex-1 gap-4 overflow-hidden p-4">
                <nav
                    aria-label="Settings sections"
                    className="flex w-44 shrink-0 flex-col gap-0.5 overflow-y-auto"
                >
                    {tabs.map((tab) => {
                        const Icon = tab.icon;
                        const isActive = tab.id === active.id;
                        return (
                            <button
                                key={tab.id}
                                type="button"
                                aria-current={isActive ? 'page' : undefined}
                                onClick={() => setSearchParams({ tab: tab.id })}
                                className={clsx(
                                    'flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition-colors',
                                    isActive
                                        ? 'bg-accent-soft font-medium text-accent'
                                        : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
                                )}
                            >
                                <Icon size={15} className="shrink-0" />
                                <span className="truncate">{tab.label}</span>
                            </button>
                        );
                    })}
                </nav>

                <div className="min-w-0 flex-1 overflow-y-auto">
                    <div className="mx-auto max-w-3xl pb-8">
                        <Component />
                    </div>
                </div>
            </div>
        </div>
    );
}
