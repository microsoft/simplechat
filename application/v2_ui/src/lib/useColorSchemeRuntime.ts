// useColorSchemeRuntime.ts
// Applies the active colors to the whole V2 interface.
//
// Two sources combine: the administrator's light and dark scheme, which arrives in the
// bootstrap settings, and the user's own custom color mode, which is used instead when they
// picked it and an administrator still allows custom modes. The result is one generated
// stylesheet in <style id="sc-color-scheme">, plus the light or dark class the mode resolves
// to.
//
// The stylesheet is cached in localStorage so the inline script in index.html can apply it
// before the first paint, the same way the theme class is applied. Without that, someone with
// custom colors would see the default palette flash on every load.

import { useEffect, useMemo } from 'react';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { useUiStore } from '../stores/uiStore';
import { buildColorSchemeCss, normalizeColorScheme } from './colorScheme';

export const COLOR_SCHEME_STYLE_ID = 'sc-color-scheme';
export const COLOR_SCHEME_CSS_STORAGE_KEY = 'simplechat.v2.color-css';

function writeStylesheet(css: string) {
    let element = document.getElementById(COLOR_SCHEME_STYLE_ID) as HTMLStyleElement | null;
    if (!css) {
        element?.remove();
    } else {
        if (!element) {
            element = document.createElement('style');
            element.id = COLOR_SCHEME_STYLE_ID;
            document.head.appendChild(element);
        }
        // textContent, never innerHTML: the CSS is generated from validated #RRGGBB values only.
        if (element.textContent !== css) {
            element.textContent = css;
        }
    }
    try {
        if (css) {
            localStorage.setItem(COLOR_SCHEME_CSS_STORAGE_KEY, css);
        } else {
            localStorage.removeItem(COLOR_SCHEME_CSS_STORAGE_KEY);
        }
    } catch {
        /* Not cached in private mode; the colors still apply once settings load. */
    }
}

/** Whether an administrator lets users build their own color mode. On unless switched off. */
export function useCustomColorModesAllowed(): { customAllowed: boolean; cardsAllowed: boolean; requireReadable: boolean } {
    const settings = useBootstrapStore((state) => state.data?.settings);
    return useMemo(() => {
        const record = (settings ?? {}) as Record<string, unknown>;
        const customAllowed = record.allow_user_custom_color_modes !== false;
        return {
            customAllowed,
            cardsAllowed: customAllowed && record.allow_user_theme_cards !== false,
            requireReadable: record.require_readable_custom_colors !== false,
        };
    }, [settings]);
}

export function useColorSchemeRuntime() {
    const bootstrapLoaded = useBootstrapStore((state) => Boolean(state.data));
    const rawScheme = useBootstrapStore((state) => (state.data?.settings as Record<string, unknown> | undefined)?.v2_color_scheme);
    const { customAllowed } = useCustomColorModesAllowed();
    const colorMode = useUiStore((state) => state.colorMode);
    const customColorMode = useUiStore((state) => state.customColorMode);
    const applyResolvedTheme = useUiStore((state) => state.applyResolvedTheme);

    useEffect(() => {
        // Until bootstrap arrives the cached stylesheet from index.html stays in place.
        if (!bootstrapLoaded) {
            return;
        }
        const useCustom = colorMode === 'custom' && customAllowed && customColorMode;
        writeStylesheet(
            buildColorSchemeCss({
                scheme: normalizeColorScheme(rawScheme),
                custom: useCustom ? customColorMode : null,
            }),
        );
        applyResolvedTheme(customAllowed);
    }, [bootstrapLoaded, rawScheme, customAllowed, colorMode, customColorMode, applyResolvedTheme]);

    useEffect(() => {
        if (colorMode !== 'system' || !window.matchMedia) {
            return undefined;
        }
        const query = window.matchMedia('(prefers-color-scheme: dark)');
        const onChange = () => applyResolvedTheme(customAllowed);
        query.addEventListener('change', onChange);
        return () => query.removeEventListener('change', onChange);
    }, [colorMode, customAllowed, applyResolvedTheme]);
}
