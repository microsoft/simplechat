// latestFeaturesNav.ts
// Whether the Support menu's Latest Features shortcut shows for this user, and why.
//
// Mirrors should_hide_latest_features_nav() in functions_latest_features_nav.py and the
// status text in static/js/latest-features-nav.js. The server says whether the deployment
// offers the shortcut at all; the user's own choice is a saved version string, compared
// with the running version here so hiding and showing take effect without a reload. A
// hide saved for an older version lapses on upgrade, which is the point: a new release
// has new features to show.
//
// Kept free of store and React imports so it can be tested directly.

export interface LatestFeaturesNavInput {
    available: boolean;
    hidden_by_development: boolean;
}

export type LatestFeaturesStatus = 'unavailable' | 'development' | 'hidden' | 'visible';

export interface LatestFeaturesNavState {
    status: LatestFeaturesStatus;
    /** Whether the rail should draw the shortcut. */
    showInRail: boolean;
    /** A hide saved for a different version, which therefore no longer applies. */
    staleHiddenVersion: string | null;
}

export function normalizeHiddenVersion(value: unknown): string | null {
    if (typeof value !== 'string') {
        return null;
    }
    const trimmed = value.trim();
    return trimmed ? trimmed : null;
}

export function resolveLatestFeaturesNav(
    nav: LatestFeaturesNavInput | null | undefined,
    hiddenVersion: unknown,
    currentVersion: string,
): LatestFeaturesNavState {
    const saved = normalizeHiddenVersion(hiddenVersion);
    const version = String(currentVersion || '').trim();

    if (!nav?.available) {
        return { status: 'unavailable', showInRail: false, staleHiddenVersion: null };
    }
    if (nav.hidden_by_development) {
        return { status: 'development', showInRail: false, staleHiddenVersion: null };
    }
    if (saved && saved === version) {
        return { status: 'hidden', showInRail: false, staleHiddenVersion: null };
    }
    return { status: 'visible', showInRail: true, staleHiddenVersion: saved };
}

export function describeLatestFeaturesNav(
    state: LatestFeaturesNavState,
    currentVersion: string,
): string {
    switch (state.status) {
        case 'unavailable':
            return 'Your administrator has not turned on the Latest Features page.';
        case 'development':
            return 'Hidden for everyone while the application runs in development mode.';
        case 'hidden':
            return `Hidden for version ${currentVersion}. It comes back when the application is updated.`;
        case 'visible':
            return state.staleHiddenVersion
                ? `Visible: you hid it for version ${state.staleHiddenVersion}, and this is version ${currentVersion}.`
                : 'Visible in the navigation rail.';
    }
}
