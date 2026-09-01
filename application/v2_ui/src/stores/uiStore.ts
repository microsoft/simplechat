// uiStore.ts
// Shell-level UI state: colour theme and left-rail collapse.
//
// Both are persisted because they are preferences rather than session state, and both are
// read during the first render, so they hydrate synchronously from localStorage rather
// than through an effect.

import { create } from 'zustand';

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
        set({ railCollapsed });
    },

    toggleChatWidth: () => {
        const chatWidth: ChatWidth = get().chatWidth === 'wide' ? 'comfortable' : 'wide';
        try {
            localStorage.setItem(WIDTH_STORAGE_KEY, chatWidth);
        } catch {
            /* Non-fatal. */
        }
        set({ chatWidth });
    },

    setMobileNavOpen: (mobileNavOpen) => set({ mobileNavOpen }),
}));

/** Re-apply the stored theme on load, in case the inline bootstrap script was skipped. */
export function initializeTheme() {
    applyThemeToDocument(useUiStore.getState().theme);
}
