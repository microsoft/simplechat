// chartRuntime.ts
// Access to the vendored Chart.js build, shared by everything in this interface that draws
// a chart.
//
// The library is loaded on first use rather than bundled. It is large, and most of the app
// never draws anything: a conversation with no ```simplechart fence and a user who never
// opens Settings download none of it. Because the loader is a module singleton, the second
// caller — the settings stats tab, say, after an inline chat chart — reuses the script that
// is already parsed rather than fetching it again.
//
// The bytes come from `public/vendor/chartjs-<version>/`, which is committed to this
// repository and served from the app's own origin. See vendorAssets.ts for why nothing here
// is fetched from the public Internet.

import type { ChartJsConstructor } from './vendor';
import { VENDOR_PATHS, loadVendorScript } from './vendorAssets';

let chartRuntime: ChartJsConstructor | null = null;
let chartRuntimeLoad: Promise<ChartJsConstructor> | null = null;

/** Load Chart.js once per session. The UMD build self-registers every controller and scale. */
export function loadChartRuntime(): Promise<ChartJsConstructor> {
    if (chartRuntime) {
        return Promise.resolve(chartRuntime);
    }
    if (!chartRuntimeLoad) {
        chartRuntimeLoad = loadVendorScript(VENDOR_PATHS.chartJs)
            .then(() => {
                if (!window.Chart) {
                    throw new Error('Chart.js did not register a global after loading');
                }
                chartRuntime = window.Chart;
                return chartRuntime;
            })
            .catch((error) => {
                // Clearing the memo lets a later render retry. A failure here is usually a
                // deployment problem, and caching the rejection would make it permanent.
                chartRuntimeLoad = null;
                throw error;
            });
    }
    return chartRuntimeLoad;
}

export interface ChartThemeColors {
    text: string;
    grid: string;
    surface: string;
}

/**
 * Chart colours taken from the live theme.
 *
 * Read from the custom properties rather than hard-coded, so a chart follows the light/dark
 * switch without a second definition of the palette drifting out of step with `theme.css`.
 */
export function readThemeColors(): ChartThemeColors {
    const fallback = { text: '#475569', grid: 'rgba(15, 23, 42, 0.10)', surface: '#ffffff' };
    if (typeof window === 'undefined') {
        return fallback;
    }

    const styles = window.getComputedStyle(document.documentElement);
    const read = (name: string, backup: string) => styles.getPropertyValue(name).trim() || backup;

    return {
        text: read('--text-2', fallback.text),
        grid: read('--edge-strong', fallback.grid),
        surface: read('--surface-solid', fallback.surface),
    };
}
