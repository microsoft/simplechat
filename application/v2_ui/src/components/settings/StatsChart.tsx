// StatsChart.tsx
// A Chart.js canvas for the settings stats tab.
//
// The chart is rebuilt rather than mutated whenever its data, kind or the theme changes.
// Chart.js can update an existing instance in place, but the instance also owns the canvas'
// resize observer and animation state, and the charts here change shape entirely when the
// window is switched — a 90-day range replacing a 7-day one is a different chart, not the
// same chart with more points.
//
// A failure to load the vendored script is shown, not swallowed. A blank rectangle where a
// chart should be reads as "you have no activity", which is a different and much worse
// statement than "the chart could not be drawn".

import { useEffect, useRef, useState } from 'react';
import { TriangleAlert } from 'lucide-react';
import { loadChartRuntime, readThemeColors, type ChartThemeColors } from '../../lib/chartRuntime';
import type { ChartJsInstance } from '../../lib/vendor';
import { useUiStore } from '../../stores/uiStore';

export type StatsChartConfigBuilder = (theme: ChartThemeColors) => Record<string, unknown>;

export function StatsChart({
    buildConfig,
    /** Describes the chart for anyone who cannot see it; a canvas has no content of its own. */
    ariaLabel,
    /** Rebuild when this changes. Keeps the effect off object identity. */
    signature,
    className = 'h-56',
}: {
    buildConfig: StatsChartConfigBuilder;
    ariaLabel: string;
    signature: string;
    className?: string;
}) {
    const theme = useUiStore((state) => state.theme);
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const instanceRef = useRef<ChartJsInstance | null>(null);
    const configRef = useRef(buildConfig);
    const [failed, setFailed] = useState(false);

    // Read through a ref so a new closure on every render does not retrigger the effect;
    // `signature` is what decides when the chart is stale.
    configRef.current = buildConfig;

    useEffect(() => {
        let cancelled = false;

        loadChartRuntime()
            .then((Chart) => {
                const canvas = canvasRef.current;
                if (cancelled || !canvas) {
                    return;
                }
                instanceRef.current?.destroy();
                instanceRef.current = new Chart(canvas, configRef.current(readThemeColors()));
                setFailed(false);
            })
            .catch(() => {
                if (!cancelled) {
                    setFailed(true);
                }
            });

        return () => {
            cancelled = true;
            instanceRef.current?.destroy();
            instanceRef.current = null;
        };
    }, [signature, theme]);

    if (failed) {
        return (
            <p className="flex items-start gap-2 py-6 text-xs text-warn">
                <TriangleAlert size={14} className="mt-0.5 shrink-0" />
                This chart could not be drawn. Reload the page to try again.
            </p>
        );
    }

    return (
        <div className={className}>
            <canvas ref={canvasRef} role="img" aria-label={ariaLabel} />
        </div>
    );
}

/**
 * Axis and legend styling shared by the cartesian charts.
 *
 * Kept in one place so the four of them cannot drift apart, which is what happened on the
 * classic page where each chart re-declared its own options.
 */
export function cartesianOptions(theme: ChartThemeColors, showLegend: boolean) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
            legend: {
                display: showLegend,
                position: 'bottom',
                labels: { color: theme.text, boxWidth: 10, boxHeight: 10, usePointStyle: true },
            },
        },
        scales: {
            x: {
                grid: { color: theme.grid },
                ticks: { color: theme.text, maxRotation: 0, autoSkipPadding: 16 },
            },
            y: {
                beginAtZero: true,
                grid: { color: theme.grid },
                ticks: { color: theme.text, precision: 0 },
            },
        },
    };
}

/** A filled line series, used where the classic page uses one. */
export function lineDataset(label: string, data: number[], color: string, fill: string) {
    return {
        label,
        data,
        borderColor: color,
        backgroundColor: fill,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 3,
        tension: 0.4,
        fill: true,
    };
}

/** One bar series of a grouped pair. */
export function barDataset(label: string, data: number[], color: string, fill: string) {
    return {
        label,
        data,
        backgroundColor: fill,
        borderColor: color,
        borderWidth: 1,
        borderRadius: 2,
    };
}

/**
 * Series colours.
 *
 * Deliberately the same hues the classic stats page uses, so someone comparing the two
 * interfaces is looking at the same chart rather than working out which line is which
 * again. They are fixed rather than theme-derived for the same reason: created-versus-
 * deleted has to stay blue-versus-red in both light and dark.
 */
export const SERIES_COLORS = {
    logins: { line: '#ffc107', fill: 'rgba(255, 193, 7, 0.18)' },
    created: { line: '#0d6efd', fill: 'rgba(13, 110, 253, 0.75)' },
    deleted: { line: '#dc3545', fill: 'rgba(220, 53, 69, 0.75)' },
    uploaded: { line: '#0dcaf0', fill: 'rgba(13, 202, 240, 0.75)' },
    tokens: { line: '#198754', fill: 'rgba(25, 135, 84, 0.18)' },
    aiSearch: '#0d6efd',
    blobStorage: '#17a2b8',
} as const;
