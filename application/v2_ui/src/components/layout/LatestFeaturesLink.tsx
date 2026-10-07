// LatestFeaturesLink.tsx
// The Support menu's Latest Features shortcut, in the rail.
//
// The classic navigation has carried this link for a while; V2 had nothing, so a user of
// the new interface never heard about a release. The destination is the server-rendered
// Support page, so this is a plain anchor rather than a router link.
//
// Hiding saves the running version, exactly as the classic control does, so the link stays
// away until the next release and both interfaces agree. Preferences can bring it back.

import { EyeOff, Sparkles } from 'lucide-react';
import { clsx } from 'clsx';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import { resolveLatestFeaturesNav } from '../../lib/latestFeaturesNav';

export function LatestFeaturesLink({ collapsed }: { collapsed: boolean }) {
    const nav = useBootstrapStore((state) => state.data?.navigation?.latest_features);
    const version = useBootstrapStore((state) => state.data?.version ?? '');
    const hiddenVersion = useUserSettingsStore(
        (state) => state.settings.latestFeaturesHiddenVersion,
    );
    const settingsLoading = useUserSettingsStore((state) => state.loading);
    const update = useUserSettingsStore((state) => state.update);

    const state = resolveLatestFeaturesNav(nav, hiddenVersion, version);
    // Waiting for preferences avoids flashing a link the user already hid.
    if (!nav || !state.showInRail || settingsLoading) {
        return null;
    }

    const link = (
        <a
            href={nav.url}
            title={collapsed ? 'Latest Features' : undefined}
            aria-label={collapsed ? 'Latest Features' : undefined}
            className={clsx(
                'flex min-w-0 flex-1 items-center gap-2.5 rounded-xl px-3 py-2 text-sm transition-colors',
                'text-text-2 hover:bg-surface-2 hover:text-text-1',
                collapsed && 'justify-center px-0',
            )}
        >
            <Sparkles size={15} className="shrink-0" />
            {!collapsed && (
                <>
                    <span className="truncate">Latest Features</span>
                    <span className="rounded-full bg-accent px-1.5 text-[10px] leading-4 font-semibold text-on-accent">
                        New
                    </span>
                </>
            )}
        </a>
    );

    if (collapsed) {
        return <div className="mt-1 px-3" data-tour="latest-features">{link}</div>;
    }

    return (
        <div className="mt-3 px-3" data-tour="latest-features">
            <p className="px-3 py-1 text-xs font-semibold tracking-wide text-text-3 uppercase">
                {nav.menu_name}
            </p>
            <div className="group/latest flex items-center gap-1">
                {link}
                <button
                    type="button"
                    onClick={() => update({ latestFeaturesHiddenVersion: version })}
                    title="Hide until the next release"
                    aria-label="Hide Latest Features until the next release"
                    className="shrink-0 rounded-lg p-1.5 text-text-3 opacity-0 transition-opacity group-hover/latest:opacity-100 hover:bg-surface-2 hover:text-text-1 focus-visible:opacity-100"
                >
                    <EyeOff size={14} />
                </button>
            </div>
        </div>
    );
}
