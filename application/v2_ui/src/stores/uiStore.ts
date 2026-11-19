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
import {
    normalizeColorMode,
    normalizeCustomColorMode,
    type ColorMode,
    type CustomColorMode,
} from '../lib/colorScheme';

export type ThemeMode = 'light' | 'dark';
export type ChatWidth = 'comfortable' | 'wide';

const THEME_STORAGE_KEY = 'simplechat.v2.theme';
const RAIL_STORAGE_KEY = 'simplechat.v2.rail-collapsed';
const WIDTH_STORAGE_KEY = 'simplechat.v2.chat-width';
// The color mode (light, dark, system or custom) and the user's custom colors. Cached locally
// for the same reason as the theme: the first paint happens before settings load.
const COLOR_MODE_STORAGE_KEY = 'simplechat.v2.color-mode';
const CUSTOM_COLORS_STORAGE_KEY = 'simplechat.v2.custom-colors';

function prefersDark(): boolean {
    try {
        return Boolean(window.matchMedia?.('(prefers-color-scheme: dark)').matches);
    } catch {
        return false;
    }
}

function readStoredColorMode(fallback: ThemeMode): ColorMode {
    try {
        return normalizeColorMode(localStorage.getItem(COLOR_MODE_STORAGE_KEY)) ?? fallback;
    } catch {
        return fallback;
    }
}

function readStoredCustomColorMode(): CustomColorMode | null {
    try {
        const raw = localStorage.getItem(CUSTOM_COLORS_STORAGE_KEY);
        return raw ? normalizeCustomColorMode(JSON.parse(raw)) : null;
    } catch {
        return null;
    }
}

function writeLocal(key: string, value: string | null) {
    try {
        if (value === null) {
            localStorage.removeItem(key);
        } else {
            localStorage.setItem(key, value);
        }
    } catch {
        /* Preference is not persisted in private mode; the session still works. */
    }
}

/**
 * The light or dark base a color mode resolves to.
 *
 * `custom` falls back to the current theme when there is no custom mode to use, or when an
 * administrator has turned custom modes off, so the document is never left without a base.
 */
export function resolveTheme(
    colorMode: ColorMode,
    custom: CustomColorMode | null,
    fallback: ThemeMode,
    customAllowed = true,
): ThemeMode {
    if (colorMode === 'light' || colorMode === 'dark') {
        return colorMode;
    }
    if (colorMode === 'system') {
        return prefersDark() ? 'dark' : 'light';
    }
    return customAllowed && custom ? custom.base : fallback;
}

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
    /** What the user picked: a fixed light or dark, follow the system, or their custom colors. */
    colorMode: ColorMode;
    /** The user's own color mode, used when `colorMode` is `custom`. */
    customColorMode: CustomColorMode | null;
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
    setColorMode: (colorMode: ColorMode) => void;
    /** Saves the user's custom colors; resolves false when the server refused them. */
    saveCustomColorMode: (custom: CustomColorMode | null) => Promise<boolean>;
    /** Applies the base a mode resolves to, without saving anything. */
    applyResolvedTheme: (customAllowed: boolean) => void;
    toggleRail: () => void;
    toggleChatWidth: () => void;
    setMobileNavOpen: (open: boolean) => void;
}

const initialTheme = readStoredTheme();

export const useUiStore = create<UiState>((set, get) => ({
    theme: initialTheme,
    colorMode: readStoredColorMode(initialTheme),
    customColorMode: readStoredCustomColorMode(),
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
        writeLocal(COLOR_MODE_STORAGE_KEY, theme);
        useUserSettingsStore.getState().update({ darkModeEnabled: theme === 'dark', v2ColorMode: theme });
        set({ theme, colorMode: theme });
    },

    toggleTheme: () => {
        get().setTheme(get().theme === 'dark' ? 'light' : 'dark');
    },

    setColorMode: (colorMode) => {
        const theme = resolveTheme(colorMode, get().customColorMode, get().theme);
        applyThemeToDocument(theme);
        writeLocal(THEME_STORAGE_KEY, theme);
        writeLocal(COLOR_MODE_STORAGE_KEY, colorMode);
        // darkModeEnabled still follows the resolved base, so the classic interface matches.
        useUserSettingsStore.getState().update({ darkModeEnabled: theme === 'dark', v2ColorMode: colorMode });
        set({ theme, colorMode });
    },

    saveCustomColorMode: async (custom) => {
        const previous = get().customColorMode;
        set({ customColorMode: custom });
        writeLocal(CUSTOM_COLORS_STORAGE_KEY, custom ? JSON.stringify(custom) : null);
        const settingsStore = useUserSettingsStore.getState();
        settingsStore.update({ v2CustomColorMode: custom });
        await settingsStore.flush();
        if (useUserSettingsStore.getState().saveError) {
            set({ customColorMode: previous });
            writeLocal(CUSTOM_COLORS_STORAGE_KEY, previous ? JSON.stringify(previous) : null);
            return false;
        }
        return true;
    },

    applyResolvedTheme: (customAllowed) => {
        const { colorMode, customColorMode, theme } = get();
        const next = resolveTheme(colorMode, customColorMode, theme, customAllowed);
        applyThemeToDocument(next);
        if (next !== theme) {
            writeLocal(THEME_STORAGE_KEY, next);
            set({ theme: next });
        }
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
    v2ColorMode?: unknown;
    v2CustomColorMode?: unknown;
    v2RailCollapsed?: unknown;
    v2ChatWidth?: unknown;
}) {
    const next: Partial<Pick<UiState, 'theme' | 'railCollapsed' | 'chatWidth' | 'colorMode' | 'customColorMode'>> = {};

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

    // darkModeEnabled is shared with the classic interface and stays the authority for a plain
    // light or dark choice, so switching there is honoured here. v2ColorMode only adds what
    // classic has no way to express: following the system, or a custom mode.
    const storedMode = normalizeColorMode(settings.v2ColorMode);
    const colorMode =
        storedMode === 'system' || storedMode === 'custom'
            ? storedMode
            : typeof settings.darkModeEnabled === 'boolean'
              ? settings.darkModeEnabled
                  ? 'dark'
                  : 'light'
              : storedMode;
    if (colorMode) {
        writeLocal(COLOR_MODE_STORAGE_KEY, colorMode);
        next.colorMode = colorMode;
    }
    if ('v2CustomColorMode' in settings) {
        const custom = normalizeCustomColorMode(settings.v2CustomColorMode);
        writeLocal(CUSTOM_COLORS_STORAGE_KEY, custom ? JSON.stringify(custom) : null);
        next.customColorMode = custom;
    }

    if (Object.keys(next).length > 0) {
        useUiStore.setState(next);
    }
}
