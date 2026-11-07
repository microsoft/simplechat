// uiStore.ts
// Shell-level UI state: colour theme, left-rail collapse and chat width.
//
// These are preferences rather than session state, so they are stored per user on the server
// and follow someone to another machine. localStorage is still written and is still what the
// first render reads: the settings request has not resolved at that point, and hydrating
// only from the server would flash the wrong theme on every load.
//
// The theme deliberately shares the classic interface's `darkModeEnabled` key, so choosing
// dark in either place applies to both. Rail and width use V2-namespaced keys instead,
// because the classic equivalents describe its own surfaces and writing them from here would
// rearrange that interface as a side effect.

import { create } from 'zustand';
import { useUserSettingsStore } from './userSettingsStore';

export type ThemeMode = 'light' | 'dark';
export type ChatWidth = 'comfortable' | 'wide';

const THEME_STORAGE_KEY = 'simplechat.v2.theme';
const RAIL_STORAGE_KEY = 'simplechat.v2.rail-collapsed';
const WIDTH_STORAGE_KEY = 'simplechat.v2.chat-width';

function readStoredTheme(): ThemeMode {
    try {
        const stored = localStorage.getItem(THEME_STORAGE_KEY);
        if (stored === 'light' || stored === 'dark') {
            return stored;
        }
        return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    } catch {
        return 'light';
    }
}

function readStoredRailCollapsed(): boolean {
    try {
        return localStorage.getItem(RAIL_STORAGE_KEY) === 'true';
    } catch {
        return false;
    }
}

function readStoredChatWidth(): ChatWidth {
    try {
        return localStorage.getItem(WIDTH_STORAGE_KEY) === 'wide' ? 'wide' : 'comfortable';
    } catch {
        return 'comfortable';
    }
}

function applyThemeToDocument(theme: ThemeMode) {
    const root = document.documentElement;
    root.classList.toggle('dark', theme === 'dark');
    // Keeps native form controls and scrollbars in step with the app theme.
    root.style.colorScheme = theme;
}

interface UiState {
    theme: ThemeMode;
    railCollapsed: boolean;
    /** Mobile-only overlay state for the rail; separate from the desktop collapse. */
    mobileNavOpen: boolean;
    /**
     * How wide the message thread is allowed to grow.
     *
     * "comfortable" keeps a fixed reading measure, which is easier to read but leaves the
     * composer controls crowded on a wide screen. "wide" lets the thread and composer fill
     * the pane. It is a preference because neither is right for everyone.
     */
    chatWidth: ChatWidth;
    setTheme: (theme: ThemeMode) => void;
    toggleTheme: () => void;
    toggleRail: () => void;
    toggleChatWidth: () => void;
    setMobileNavOpen: (open: boolean) => void;
}

export const useUiStore = create<UiState>((set, get) => ({
    theme: readStoredTheme(),
    railCollapsed: readStoredRailCollapsed(),
    mobileNavOpen: false,
    chatWidth: readStoredChatWidth(),

    setTheme: (theme) => {
        applyThemeToDocument(theme);
        try {
            localStorage.setItem(THEME_STORAGE_KEY, theme);
        } catch {
            /* Preference is not persisted in private mode; the session still works. */
        }
        useUserSettingsStore.getState().update({ darkModeEnabled: theme === 'dark' });
        set({ theme });
    },

    toggleTheme: () => {
        get().setTheme(get().theme === 'dark' ? 'light' : 'dark');
    },

    toggleRail: () => {
        const railCollapsed = !get().railCollapsed;
        try {
            localStorage.setItem(RAIL_STORAGE_KEY, String(railCollapsed));
        } catch {
            /* Non-fatal. */
        }
        useUserSettingsStore.getState().update({ v2RailCollapsed: railCollapsed });
        set({ railCollapsed });
    },

    toggleChatWidth: () => {
        const chatWidth: ChatWidth = get().chatWidth === 'wide' ? 'comfortable' : 'wide';
        try {
            localStorage.setItem(WIDTH_STORAGE_KEY, chatWidth);
        } catch {
            /* Non-fatal. */
        }
        useUserSettingsStore.getState().update({ v2ChatWidth: chatWidth });
        set({ chatWidth });
    },

    setMobileNavOpen: (mobileNavOpen) => set({ mobileNavOpen }),
}));

/** Re-apply the stored theme on load, in case the inline bootstrap script was skipped. */
export function initializeTheme() {
    applyThemeToDocument(useUiStore.getState().theme);
}

/**
 * Adopt the preferences the server holds, once they have loaded.
 *
 * Called after the settings request resolves. Anything the server has not recorded is left
 * as the local value rather than being reset to a default, so a first-time user does not
 * have their current session rearranged by an empty settings document. Applied without
 * writing back, since this is the server's own value arriving rather than a user choice.
 */
export function hydrateUiPreferences(settings: {
    darkModeEnabled?: unknown;
    v2RailCollapsed?: unknown;
    v2ChatWidth?: unknown;
}) {
    const next: Partial<Pick<UiState, 'theme' | 'railCollapsed' | 'chatWidth'>> = {};

    if (typeof settings.darkModeEnabled === 'boolean') {
        const theme: ThemeMode = settings.darkModeEnabled ? 'dark' : 'light';
        if (theme !== useUiStore.getState().theme) {
            applyThemeToDocument(theme);
            try {
                localStorage.setItem(THEME_STORAGE_KEY, theme);
            } catch {
                /* Non-fatal. */
            }
            next.theme = theme;
        }
    }

    if (typeof settings.v2RailCollapsed === 'boolean') {
        next.railCollapsed = settings.v2RailCollapsed;
    }

    if (settings.v2ChatWidth === 'wide' || settings.v2ChatWidth === 'comfortable') {
        next.chatWidth = settings.v2ChatWidth;
    }

    if (Object.keys(next).length > 0) {
        useUiStore.setState(next);
    }
}
