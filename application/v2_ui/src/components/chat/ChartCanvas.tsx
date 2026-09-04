// ChartCanvas.tsx
// Draws one chart, and is the only place a Chart.js instance is created.
//
// Split out of InlineChart so the chart in a reply and the preview in the editor are the same
// drawing code. They have to be: a preview that renders a chart differently from the message it
// belongs to is worse than no preview, because it is confidently wrong about what saving will
// produce.
//
// Chart.js is loaded from the vendored copy on first use rather than bundled — most
// conversations contain no chart — and the loader in lib/chartRuntime.ts is shared, so whichever
// canvas draws first pays for the script and the rest reuse it.

import { useEffect, useMemo, useRef, useState } from 'react';
import { useUiStore } from '../../stores/uiStore';
import { buildChartConfig, type ChartSpec } from '../../lib/inlineChartSpec';
import { loadChartRuntime, readThemeColors } from '../../lib/chartRuntime';
import type { ChartJsInstance } from '../../lib/vendor';
import {
    THEME_BACKGROUND,
    resolveBackgroundColor,
    visualStyleSignature,
    type VisualStyle,
} from '../../lib/visualPalettes';

/**
 * The colour to paint behind a chart, or null to leave the canvas transparent.
 *
 * Null while the background is left on "match theme", because the canvas has always been
 * transparent over the surrounding panel and filling it would visibly change every chart nobody
 * has touched.
 */
export function resolveChartBackground(style: VisualStyle): string | null {
    return style.background === THEME_BACKGROUND ? null : resolveBackgroundColor(style);
}

export function ChartCanvas({
    spec,
    style,
    label,
    canvasRef,
}: {
    spec: ChartSpec;
    style: VisualStyle;
    /** What a screen reader announces the chart as. */
    label: string;
    /** Supplied when the caller needs the pixels, such as for a PNG download. */
    canvasRef?: React.RefObject<HTMLCanvasElement>;
}) {
    const theme = useUiStore((state) => state.theme);
    const internalRef = useRef<HTMLCanvasElement>(null);
    const elementRef = canvasRef ?? internalRef;
    const instanceRef = useRef<ChartJsInstance | null>(null);
    const [failed, setFailed] = useState(false);

    const background = useMemo(() => resolveChartBackground(style), [style]);
    const signature = useMemo(
        () => visualStyleSignature(style, background ?? THEME_BACKGROUND),
        [style, background],
    );

    useEffect(() => {
        let cancelled = false;

        loadChartRuntime()
            .then((Chart) => {
                if (cancelled || !elementRef.current) {
                    return;
                }
                instanceRef.current?.destroy();
                instanceRef.current = new Chart(
                    elementRef.current,
                    buildChartConfig(spec, readThemeColors(), style, background),
                );
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
        // `theme` is a dependency because the axis, tick and legend colours are baked into the
        // configuration when the chart is built, and `signature` because the series and
        // background colours are too.
    }, [spec, theme, style, background, signature, elementRef]);

    if (failed) {
        return (
            <div className="flex h-full items-center justify-center text-xs text-text-3">
                Chart could not be displayed
            </div>
        );
    }

    return <canvas ref={elementRef} role="img" aria-label={label} />;
}
