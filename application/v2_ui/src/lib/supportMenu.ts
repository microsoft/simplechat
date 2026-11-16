// supportMenu.ts
// The Support menu in the V2 rail: which destinations it offers this user, and where they are.
//
// Mirrors the gate in the classic `_sidebar_nav.html`. The server decides what the deployment
// offers -- `navigation.latest_features` and `navigation.send_feedback` in the bootstrap
// payload, already narrowed to this user's roles -- and the user's own "hide until the next
// release" choice for Latest Features is applied here, through the resolver the Preferences
// card uses, so the rail and that card cannot disagree. The menu is drawn whenever at least
// one destination is, as the classic one is.
//
// Kept free of store and React imports so it can be tested directly.

import { resolveLatestFeaturesNav, type LatestFeaturesNavInput } from './latestFeaturesNav';

/** The V2 Latest Features page, relative to the router's `/v2` base. */
export const SUPPORT_LATEST_FEATURES_PATH = '/support/latest-features';

/** The V2 Send Feedback page, relative to the router's `/v2` base. */
export const SUPPORT_SEND_FEEDBACK_PATH = '/support/send-feedback';

/** The heading the classic templates fall back to when none is stored. */
export const DEFAULT_SUPPORT_MENU_NAME = 'Support';

export interface SupportNavigationInput {
    latest_features?: (LatestFeaturesNavInput & { menu_name?: string }) | null;
    send_feedback?: { available: boolean; menu_name?: string } | null;
}

export interface SupportMenuState {
    /** The heading an administrator chose for the menu. */
    menuName: string;
    /** Whether the rail offers Latest Features. */
    showLatestFeatures: boolean;
    /** Whether the rail offers Send Feedback. */
    showSendFeedback: boolean;
    /** Whether the menu is drawn at all. */
    visible: boolean;
}

function menuNameFrom(...candidates: unknown[]): string {
    for (const candidate of candidates) {
        if (typeof candidate === 'string' && candidate.trim()) {
            return candidate.trim();
        }
    }
    return DEFAULT_SUPPORT_MENU_NAME;
}

/** Whether this deployment lets the user send feedback, whatever the rail is showing. */
export function isSendFeedbackAvailable(navigation: SupportNavigationInput | null | undefined): boolean {
    return navigation?.send_feedback?.available === true;
}

export function resolveSupportMenu(
    navigation: SupportNavigationInput | null | undefined,
    hiddenVersion: unknown,
    currentVersion: string,
): SupportMenuState {
    const latestFeatures = navigation?.latest_features ?? null;
    const sendFeedback = navigation?.send_feedback ?? null;

    const showLatestFeatures = resolveLatestFeaturesNav(
        latestFeatures,
        hiddenVersion,
        currentVersion,
    ).showInRail;
    const showSendFeedback = isSendFeedbackAvailable(navigation);

    return {
        menuName: menuNameFrom(latestFeatures?.menu_name, sendFeedback?.menu_name),
        showLatestFeatures,
        showSendFeedback,
        visible: showLatestFeatures || showSendFeedback,
    };
}
