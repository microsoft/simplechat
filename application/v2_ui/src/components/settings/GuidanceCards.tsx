// GuidanceCards.tsx
// Preferences for the help this interface offers: the Latest Features shortcut and the
// guided tours.
//
// Both mirror classic profile controls and share their settings, so a choice made in one
// interface holds in the other. The tours add a per-tour choice the classic page does not
// have; its master switch, `showTutorialButtons`, still turns every tour off at once.

import { Link, useNavigate } from 'react-router-dom';
import { CircleHelp, Play, Zap } from 'lucide-react';
import { clsx } from 'clsx';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import type { UserSettings } from '../../lib/userSettings';
import {
    describeLatestFeaturesNav,
    resolveLatestFeaturesNav,
    type LatestFeaturesStatus,
} from '../../lib/latestFeaturesNav';
import { SUPPORT_LATEST_FEATURES_PATH } from '../../lib/supportMenu';
import { isTourEnabled, requestTour, TOURS, withTourVisibility } from '../../lib/tours';
import { Toggle } from '../ui/primitives';
import { SettingsCard } from './SettingsCard';

const STATUS_BADGE: Record<LatestFeaturesStatus, { label: string; tone: string }> = {
    visible: { label: 'Visible', tone: 'bg-ok-soft text-ok' },
    hidden: { label: 'Hidden', tone: 'bg-surface-2 text-text-2' },
    development: { label: 'Hidden in development', tone: 'bg-warn-soft text-text-1' },
    unavailable: { label: 'Not offered', tone: 'bg-surface-2 text-text-3' },
};

export function LatestFeaturesCard({
    settings,
    update,
}: {
    settings: UserSettings;
    update: (partial: UserSettings) => void;
}) {
    const nav = useBootstrapStore((state) => state.data?.navigation?.latest_features);
    const version = useBootstrapStore((state) => state.data?.version ?? '');
    const state = resolveLatestFeaturesNav(nav, settings.latestFeaturesHiddenVersion, version);
    const badge = STATUS_BADGE[state.status];

    return (
        <SettingsCard
            title="Latest Features"
            Icon={Zap}
            description="A shortcut in the navigation rail to what changed in recent releases. Hiding it lasts until the next release, so you still hear about new features. Shared with the classic interface."
        >
            <div className="flex flex-wrap items-center gap-3">
                <span className={clsx('rounded-full px-2.5 py-0.5 text-xs font-medium', badge.tone)}>
                    {badge.label}
                </span>
                <p className="min-w-0 flex-1 text-xs text-text-3">
                    {describeLatestFeaturesNav(state, version)}
                </p>
                {state.status === 'visible' && (
                    <button
                        type="button"
                        onClick={() => update({ latestFeaturesHiddenVersion: version })}
                        className="rounded-lg border border-edge px-3 py-1.5 text-xs font-medium text-text-2 hover:bg-surface-2 hover:text-text-1"
                    >
                        Hide for this version
                    </button>
                )}
                {state.status === 'hidden' && (
                    <button
                        type="button"
                        onClick={() => update({ latestFeaturesHiddenVersion: null })}
                        className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-on-accent hover:bg-accent-hover"
                    >
                        Show again
                    </button>
                )}
            </div>
            {nav?.available && state.status !== 'development' && (
                <Link
                    to={SUPPORT_LATEST_FEATURES_PATH}
                    className="mt-3 inline-block text-xs font-medium text-accent hover:underline"
                >
                    Open Latest Features
                </Link>
            )}
        </SettingsCard>
    );
}

export function TutorialsCard({
    settings,
    update,
}: {
    settings: UserSettings;
    update: (partial: UserSettings) => void;
}) {
    const navigate = useNavigate();
    const allOn = settings.showTutorialButtons !== false;

    return (
        <SettingsCard
            title="Guided tours"
            Icon={CircleHelp}
            description="Step-by-step tours that point out the controls on a page. Each page with a tour has a help button in its header that starts it."
        >
            <Toggle
                checked={allOn}
                onChange={(next) => update({ showTutorialButtons: next })}
                label="Show tour buttons"
                description="Turns every tour button off at once. Shared with the classic interface's tutorial buttons."
            />

            <ul className="mt-3 divide-y divide-edge rounded-xl border border-edge">
                {TOURS.map((tour) => {
                    const tourOn = isTourEnabled(tour.id, true, settings.tutorialVisibility);
                    return (
                        <li key={tour.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                            <div className={clsx('min-w-0 flex-1', !allOn && 'opacity-60')}>
                                <Toggle
                                    checked={allOn && tourOn}
                                    disabled={!allOn}
                                    onChange={(next) =>
                                        update({
                                            tutorialVisibility: withTourVisibility(
                                                settings.tutorialVisibility,
                                                tour.id,
                                                next,
                                            ),
                                        })
                                    }
                                    label={tour.title}
                                    description={tour.description}
                                />
                            </div>
                            <button
                                type="button"
                                onClick={() => {
                                    requestTour(tour.id);
                                    navigate(tour.path);
                                }}
                                className="flex shrink-0 items-center gap-1.5 rounded-lg border border-edge px-3 py-1.5 text-xs font-medium text-text-2 hover:bg-surface-2 hover:text-text-1"
                            >
                                <Play size={12} />
                                Start now
                            </button>
                        </li>
                    );
                })}
            </ul>
        </SettingsCard>
    );
}
