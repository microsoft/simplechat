// visualPalettes.ts
// The colour vocabulary shared by rendered diagrams and charts, and the rules that decide
// which colours a given block ends up with.
//
// Three layers are resolved in order: the built-in default, the user's own default from their
// settings document, and an override saved against one block of one message. The last one to
// specify something wins, so changing a single chart never disturbs its siblings.
//
// The five presets are the classic interface's CHART_COLOR_PRESETS, reused verbatim
// (static/js/chat/chat-inline-charts.js) so a palette called "Vivid" means the same colours in
// both clients. Nothing here trusts a stored value: everything is normalised to #rrggbb or the
// literal 'theme' sentinel, because these strings are written into style attributes and into
// mermaid's theme configuration.

export const PALETTE_IDS = ['default', 'calm', 'vivid', 'warm', 'contrast'] as const;

export type PaletteId = (typeof PALETTE_IDS)[number];

export interface PalettePreset {
    id: PaletteId;
    name: string;
    colors: string[];
}

export const PALETTE_PRESETS: readonly PalettePreset[] = Object.freeze([
    {
        id: 'default',
        name: 'Default',
        colors: [
            '#1c6ea4',
            '#d75b35',
            '#277b54',
            '#995c20',
            '#7e4d8c',
            '#bf4270',
            '#3a8d79',
            '#657830',
        ],
    },
    {
        id: 'calm',
        name: 'Calm',
        colors: [
            '#2563eb',
            '#0f766e',
            '#65a30d',
            '#0891b2',
            '#7c3aed',
            '#4b5563',
            '#ca8a04',
            '#be123c',
        ],
    },
    {
        id: 'vivid',
        name: 'Vivid',
        colors: [
            '#dc2626',
            '#ea580c',
            '#ca8a04',
            '#16a34a',
            '#0891b2',
            '#2563eb',
            '#9333ea',
            '#db2777',
        ],
    },
    {
        id: 'warm',
        name: 'Warm',
        colors: [
            '#b91c1c',
            '#c2410c',
            '#ca8a04',
            '#a16207',
            '#92400e',
            '#be123c',
            '#9f1239',
            '#7f1d1d',
        ],
    },
    {
        id: 'contrast',
        name: 'Contrast',
        colors: [
            '#111827',
            '#2563eb',
            '#dc2626',
            '#16a34a',
            '#ca8a04',
            '#7c3aed',
            '#0891b2',
            '#db2777',
        ],
    },
]);

/**
 * Background sentinel meaning "whatever the app theme is showing".
 *
 * Stored rather than resolved to a hex, so a block saved in light mode still follows the theme
 * after switching to dark instead of being pinned to white.
 */
export const THEME_BACKGROUND = 'theme';

/** Series fill opacity, matching CHART_COLOR_BACKGROUND_ALPHA in the classic client. */
export const SERIES_FILL_ALPHA = 0.18;

/** How much of a palette colour is mixed into the background to fill a diagram node. */
const NODE_FILL_RATIO = 0.18;

/** Bounds the stored override, and mirrors the server-side cap. */
export const MAX_SERIES_COLOR_OVERRIDES = 24;

/** The fence languages a style can be saved against. */
export const VISUAL_STYLE_KINDS = ['mermaid', 'simplechart'] as const;

export type VisualStyleKind = (typeof VISUAL_STYLE_KINDS)[number];

export interface VisualStyle {
    palette: PaletteId;
    /** '#rrggbb', or THEME_BACKGROUND to follow the app theme. */
    background: string;
    /**
     * Individual series or slice colours, keyed by index as a string.
     *
     * An object rather than a sparse array because it is stored as JSON: recolouring the fifth
     * series should not persist four nulls, and Cosmos keys are strings either way.
     */
    colors: Record<string, string>;
}

export const DEFAULT_VISUAL_STYLE: VisualStyle = Object.freeze({
    palette: 'default' as PaletteId,
    background: THEME_BACKGROUND,
    colors: Object.freeze({}) as Record<string, string>,
});

const HEX_PATTERN = /^#[0-9a-f]{6}$/;
const SHORT_HEX_PATTERN = /^#[0-9a-f]{3}$/;

/** True when nothing has been chosen, so rendering can take the untouched path. */
export function isDefaultVisualStyle(style: VisualStyle | null | undefined): boolean {
    if (!style) {
        return true;
    }
    return (
        style.palette === 'default' &&
        style.background === THEME_BACKGROUND &&
        Object.keys(style.colors).length === 0
    );
}

export function isPaletteId(value: unknown): value is PaletteId {
    return typeof value === 'string' && (PALETTE_IDS as readonly string[]).includes(value);
}

export function paletteName(id: PaletteId): string {
    return PALETTE_PRESETS.find((preset) => preset.id === id)?.name ?? 'Default';
}

export function paletteColors(id: PaletteId): string[] {
    return (PALETTE_PRESETS.find((preset) => preset.id === id) ?? PALETTE_PRESETS[0]).colors;
}

/**
 * Reduce any accepted colour form to `#rrggbb`.
 *
 * Deliberately narrow: only hex is accepted, because the result is written into inline styles
 * and into mermaid's configuration, and a single accepted form removes the question of what
 * else a stored string might be.
 */
export function normalizeHexColor(value: unknown, fallback = '#000000'): string {
    if (typeof value !== 'string') {
        return fallback;
    }

    const trimmed = value.trim().toLowerCase();
    if (HEX_PATTERN.test(trimmed)) {
        return trimmed;
    }
    if (SHORT_HEX_PATTERN.test(trimmed)) {
        return `#${trimmed[1]}${trimmed[1]}${trimmed[2]}${trimmed[2]}${trimmed[3]}${trimmed[3]}`;
    }
    return fallback;
}

/** A background value: either a hex colour or the theme sentinel. */
export function normalizeBackground(value: unknown): string {
    if (value === THEME_BACKGROUND) {
        return THEME_BACKGROUND;
    }
    const hex = normalizeHexColor(value, '');
    return hex || THEME_BACKGROUND;
}

function channels(hex: string): [number, number, number] {
    const normalized = normalizeHexColor(hex, '#000000');
    return [
        parseInt(normalized.slice(1, 3), 16),
        parseInt(normalized.slice(3, 5), 16),
        parseInt(normalized.slice(5, 7), 16),
    ];
}

function toHex(red: number, green: number, blue: number): string {
    const clamp = (value: number) => Math.max(0, Math.min(255, Math.round(value)));
    return `#${[clamp(red), clamp(green), clamp(blue)]
        .map((channel) => channel.toString(16).padStart(2, '0'))
        .join('')}`;
}

/** A hex colour as `rgba(...)`, used for chart series fills. */
export function hexToRgba(hex: string, alpha = SERIES_FILL_ALPHA): string {
    const [red, green, blue] = channels(hex);
    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

/** Blend `color` into `onto`, where ratio 0 is all `onto` and 1 is all `color`. */
export function mixHex(color: string, onto: string, ratio: number): string {
    const bounded = Math.max(0, Math.min(1, ratio));
    const [red, green, blue] = channels(color);
    const [baseRed, baseGreen, baseBlue] = channels(onto);
    return toHex(
        baseRed + (red - baseRed) * bounded,
        baseGreen + (green - baseGreen) * bounded,
        baseBlue + (blue - baseBlue) * bounded,
    );
}

/**
 * Relative luminance, per WCAG 2.1.
 *
 * Used to choose label colours, so text stays legible on a background the user picked rather
 * than one the theme controls.
 */
export function relativeLuminance(hex: string): number {
    const [red, green, blue] = channels(hex).map((channel) => {
        const proportion = channel / 255;
        return proportion <= 0.03928
            ? proportion / 12.92
            : ((proportion + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

/** A dark or light text colour, whichever reads on the given background. */
export function readableTextColor(backgroundHex: string): string {
    return relativeLuminance(backgroundHex) > 0.45 ? '#111827' : '#f8fafc';
}

/** The colour for one series or slice: an explicit override, else the palette's own. */
export function seriesColor(style: VisualStyle, index: number): string {
    const override = style.colors[String(index)];
    if (override) {
        return normalizeHexColor(override, paletteColorAt(style.palette, index));
    }
    return paletteColorAt(style.palette, index);
}

export function paletteColorAt(id: PaletteId, index: number): string {
    const colors = paletteColors(id);
    return colors[((index % colors.length) + colors.length) % colors.length];
}

/**
 * Accept a style from anywhere untrusted: the settings document, a message, or a request.
 *
 * Returns null when the value is not a style at all, so a caller can tell "nothing stored"
 * from "stored, but all defaults".
 */
export function sanitizeVisualStyle(value: unknown): VisualStyle | null {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return null;
    }

    const source = value as Record<string, unknown>;
    const palette: PaletteId = isPaletteId(source.palette) ? source.palette : 'default';
    const background = normalizeBackground(source.background);

    const colors: Record<string, string> = {};
    const rawColors = source.colors;
    if (rawColors && typeof rawColors === 'object' && !Array.isArray(rawColors)) {
        for (const [key, entry] of Object.entries(rawColors as Record<string, unknown>)) {
            if (Object.keys(colors).length >= MAX_SERIES_COLOR_OVERRIDES) {
                break;
            }
            const index = Number(key);
            if (!Number.isInteger(index) || index < 0 || index >= MAX_SERIES_COLOR_OVERRIDES) {
                continue;
            }
            const hex = normalizeHexColor(entry, '');
            if (hex) {
                colors[String(index)] = hex;
            }
        }
    }

    return { palette, background, colors };
}

/**
 * Layer a message-level override over the user's default.
 *
 * The override replaces rather than merges. A block someone has explicitly recoloured should
 * keep looking the way they left it, even after they later change their global default.
 */
export function resolveVisualStyle(
    userDefault: VisualStyle | null | undefined,
    override: VisualStyle | null | undefined,
): VisualStyle {
    if (override) {
        return override;
    }
    if (userDefault) {
        return userDefault;
    }
    return { ...DEFAULT_VISUAL_STYLE, colors: {} };
}

/**
 * A short, stable fingerprint of a block's source (FNV-1a, 32-bit).
 *
 * Stored alongside an override so a saved colour is not applied to different content: blocks
 * are addressed by their position in the message, and an edit or a mask can shift that
 * position. A mismatch falls back to the default rather than mis-colouring a diagram.
 */
export function fingerprintSource(source: string): string {
    let hash = 0x811c9dc5;
    const normalized = source.replace(/\r\n/g, '\n').trim();
    for (let index = 0; index < normalized.length; index += 1) {
        hash ^= normalized.charCodeAt(index);
        hash = Math.imul(hash, 0x01000193);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
}

/**
 * Mermaid `themeVariables` for a style, against an already-resolved background.
 *
 * Node fills are the palette colour mixed into the background rather than the colour itself,
 * so a diagram reads as tinted boxes with strong borders instead of solid blocks of colour, and
 * so the same palette works on a light or a dark background. Line and label colours come from
 * the background's luminance rather than the palette, because an arrow that cannot be seen is
 * worse than one that is not on-palette.
 */
export function mermaidThemeVariables(
    style: VisualStyle,
    background: string,
): Record<string, string> {
    const text = readableTextColor(background);
    const primary = seriesColor(style, 0);
    const secondary = seriesColor(style, 1);
    const tertiary = seriesColor(style, 2);

    const fill = (color: string) => mixHex(color, background, NODE_FILL_RATIO);
    const primaryFill = fill(primary);
    const secondaryFill = fill(secondary);
    const tertiaryFill = fill(tertiary);

    return {
        background,
        // Flowchart and generic node surfaces.
        primaryColor: primaryFill,
        primaryBorderColor: primary,
        primaryTextColor: readableTextColor(primaryFill),
        secondaryColor: secondaryFill,
        secondaryBorderColor: secondary,
        secondaryTextColor: readableTextColor(secondaryFill),
        tertiaryColor: tertiaryFill,
        tertiaryBorderColor: tertiary,
        tertiaryTextColor: readableTextColor(tertiaryFill),
        mainBkg: primaryFill,
        nodeBorder: primary,
        clusterBkg: mixHex(tertiary, background, NODE_FILL_RATIO / 2),
        clusterBorder: tertiary,
        // Connectors and labels.
        lineColor: mixHex(text, background, 0.7),
        textColor: text,
        titleColor: text,
        edgeLabelBackground: background,
        // Sequence diagrams draw their own actors and notes.
        actorBkg: primaryFill,
        actorBorder: primary,
        actorTextColor: readableTextColor(primaryFill),
        signalColor: mixHex(text, background, 0.7),
        signalTextColor: text,
        labelBoxBkgColor: secondaryFill,
        labelBoxBorderColor: secondary,
        labelTextColor: readableTextColor(secondaryFill),
        noteBkgColor: tertiaryFill,
        noteBorderColor: tertiary,
        noteTextColor: readableTextColor(tertiaryFill),
    };
}

/**
 * A stable string for a style, used as a cache and configuration key.
 *
 * The "stock" / "styled" prefix is not redundant with the rest. A block left on the Default
 * palette with the theme background resolves to the same palette and the same colour as one
 * explicitly set to that colour, but the two are rendered by different means — mermaid's stock
 * theme against `base` plus theme variables — so a key that could not tell them apart would let
 * one be drawn with the other's configuration.
 */
export function visualStyleSignature(style: VisualStyle, resolvedBackground: string): string {
    const colors = Object.keys(style.colors)
        .sort((left, right) => Number(left) - Number(right))
        .map((key) => `${key}:${style.colors[key]}`)
        .join(',');
    const kind = isDefaultVisualStyle(style) ? 'stock' : 'styled';
    return `${kind}|${style.palette}|${resolvedBackground}|${colors}`;
}

/**
 * The opaque colour the app theme is currently showing.
 *
 * `--surface-solid` rather than `--surface-sunken`, which is translucent: a rasterized PNG and
 * a mermaid theme variable both need a real colour, not one that assumes a page behind it.
 */
export function themeSurfaceColor(fallback = '#ffffff'): string {
    if (typeof window === 'undefined') {
        return fallback;
    }
    const value = window
        .getComputedStyle(document.documentElement)
        .getPropertyValue('--surface-solid')
        .trim();
    return normalizeHexColor(value, fallback);
}

/** The background a style asks for, with the theme sentinel resolved to a real colour. */
export function resolveBackgroundColor(style: VisualStyle, themeFallback?: string): string {
    if (style.background === THEME_BACKGROUND) {
        return themeFallback ?? themeSurfaceColor();
    }
    return normalizeHexColor(style.background, themeFallback ?? themeSurfaceColor());
}
