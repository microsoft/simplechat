// colorScheme.ts
// Custom color schemes for V2: the palette an administrator or user can set, the CSS it
// becomes, and the Theme Card code a palette is shared as.
//
// A palette is deliberately small: eleven named colors, each a plain #RRGGBB value. The rest of
// the design tokens in theme.css (hover shades, translucent glass surfaces, soft status fills)
// are derived from those eleven here, so what a person can set stays small enough for the
// server to validate completely. functions_color_schemes.py holds the matching server rules
// and documents the Theme Card format; the two must agree.
//
// Theme Card code: SCTHEME1.<payload>.<checksum>
//   payload  = base64url(JSON {v: 1, n: name, b: 'light'|'dark', c: {token: 'RRGGBB'}})
//   checksum = base64url(first 16 bytes of SHA-256('SCTHEME1.' + payload))
// The checksum is unkeyed on purpose so a card works on any SimpleChat site. It catches a card
// edited after it was made; the server still validates every value before saving it.

export const PALETTE_TOKENS = [
    'accent',
    'onAccent',
    'backdrop',
    'panel',
    'border',
    'text1',
    'text2',
    'ok',
    'warn',
    'danger',
    'info',
] as const;

export type PaletteToken = (typeof PALETTE_TOKENS)[number];
export type Palette = Record<PaletteToken, string>;
export type ColorBase = 'light' | 'dark';
export type ColorMode = 'light' | 'dark' | 'system' | 'custom';

export interface ColorScheme {
    light: Palette;
    dark: Palette;
}

export interface CustomColorMode {
    name: string;
    base: ColorBase;
    colors: Palette;
}

export interface PaletteTokenInfo {
    token: PaletteToken;
    label: string;
    hint: string;
    group: 'Brand' | 'Surfaces' | 'Text' | 'Status';
}

export const PALETTE_TOKEN_INFO: PaletteTokenInfo[] = [
    { token: 'accent', label: 'Accent', hint: 'Buttons, links, your messages', group: 'Brand' },
    { token: 'onAccent', label: 'Text on accent', hint: 'Labels on accent buttons', group: 'Brand' },
    { token: 'backdrop', label: 'Page background', hint: 'Behind every panel', group: 'Surfaces' },
    { token: 'panel', label: 'Panels', hint: 'Cards, sidebar, composer', group: 'Surfaces' },
    { token: 'border', label: 'Borders', hint: 'Lines between areas', group: 'Surfaces' },
    { token: 'text1', label: 'Primary text', hint: 'Headings and messages', group: 'Text' },
    { token: 'text2', label: 'Secondary text', hint: 'Help text and timestamps', group: 'Text' },
    { token: 'ok', label: 'Success', hint: 'Saved, passed', group: 'Status' },
    { token: 'warn', label: 'Warning', hint: 'Needs attention', group: 'Status' },
    { token: 'danger', label: 'Error', hint: 'Failed, delete', group: 'Status' },
    { token: 'info', label: 'Info', hint: 'Notices, tips', group: 'Status' },
];

/** The colors theme.css ships with, expressed as palettes. */
export const DEFAULT_LIGHT: Palette = {
    accent: '#3B6EF0',
    onAccent: '#FFFFFF',
    backdrop: '#EEF2FB',
    panel: '#FFFFFF',
    border: '#DCE3EE',
    text1: '#0F172A',
    text2: '#475569',
    ok: '#059669',
    warn: '#D97706',
    danger: '#DC2626',
    info: '#0E7490',
};

export const DEFAULT_DARK: Palette = {
    accent: '#7EA0FF',
    onAccent: '#0B1020',
    backdrop: '#070B18',
    panel: '#101728',
    border: '#2B3550',
    text1: '#F1F5F9',
    text2: '#B3C0D4',
    ok: '#34D399',
    warn: '#FBBF24',
    danger: '#F87171',
    info: '#22D3EE',
};

export const READABLE_CONTRAST_MIN = 4.5;
export const COLOR_MODE_NAME_MAX = 40;

const HEX_COLOR = /^#?([0-9a-f]{6})$/i;

/** Returns `#RRGGBB` in upper case, or null when the value is not a six-digit hex color. */
export function normalizeHexColor(value: unknown): string | null {
    if (typeof value !== 'string') {
        return null;
    }
    const match = HEX_COLOR.exec(value.trim());
    return match ? `#${match[1].toUpperCase()}` : null;
}

/** Returns a palette with exactly the known tokens, or null if anything is missing or invalid. */
export function normalizePalette(value: unknown): Palette | null {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return null;
    }
    const record = value as Record<string, unknown>;
    if (Object.keys(record).some((key) => !(PALETTE_TOKENS as readonly string[]).includes(key))) {
        return null;
    }
    const palette = {} as Palette;
    for (const token of PALETTE_TOKENS) {
        const color = normalizeHexColor(record[token]);
        if (!color) {
            return null;
        }
        palette[token] = color;
    }
    return palette;
}

export function normalizeColorScheme(value: unknown): ColorScheme | null {
    if (!value || typeof value !== 'object') {
        return null;
    }
    const record = value as Record<string, unknown>;
    const light = normalizePalette(record.light);
    const dark = normalizePalette(record.dark);
    return light && dark ? { light, dark } : null;
}

export function normalizeColorModeName(value: unknown): string {
    if (typeof value !== 'string') {
        return '';
    }
    // eslint-disable-next-line no-control-regex
    return value.replace(/[\u0000-\u001f\u007f-\u009f]/g, '').trim().slice(0, COLOR_MODE_NAME_MAX);
}

export function normalizeCustomColorMode(value: unknown): CustomColorMode | null {
    if (!value || typeof value !== 'object') {
        return null;
    }
    const record = value as Record<string, unknown>;
    const base = record.base === 'dark' ? 'dark' : record.base === 'light' ? 'light' : null;
    const colors = normalizePalette(record.colors);
    if (!base || !colors) {
        return null;
    }
    return { name: normalizeColorModeName(record.name) || 'My color mode', base, colors };
}

export function normalizeColorMode(value: unknown): ColorMode | null {
    return value === 'light' || value === 'dark' || value === 'system' || value === 'custom' ? value : null;
}

/* -------------------------------------------------------------------------- */
/* Color math                                                                  */
/* -------------------------------------------------------------------------- */

function channels(hex: string): [number, number, number] {
    const clean = hex.replace('#', '');
    return [0, 2, 4].map((offset) => parseInt(clean.slice(offset, offset + 2), 16)) as [number, number, number];
}

function toHex(values: number[]): string {
    return `#${values.map((value) => Math.round(Math.min(255, Math.max(0, value))).toString(16).padStart(2, '0')).join('').toUpperCase()}`;
}

/** Mixes two colors; amount 0 keeps `from`, 1 gives `to`. */
export function mixColors(from: string, to: string, amount: number): string {
    const a = channels(from);
    const b = channels(to);
    return toHex(a.map((value, index) => value + (b[index] - value) * amount));
}

function rgba(hex: string, alpha: number): string {
    const [r, g, b] = channels(hex);
    return `rgb(${r} ${g} ${b} / ${alpha})`;
}

function luminance(hex: string): number {
    const linear = channels(hex).map((value) => {
        const channel = value / 255;
        return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

/** A ratio as people see it, to one decimal place. Readability is judged on this value. */
export function displayedRatio(ratio: number): number {
    return Math.round(ratio * 10) / 10;
}

export function contrastRatio(foreground: string, background: string): number {
    const a = luminance(foreground);
    const b = luminance(background);
    const [hi, lo] = a > b ? [a, b] : [b, a];
    return (hi + 0.05) / (lo + 0.05);
}

/** The color a token is read against, or null when contrast does not apply to it. */
export function contrastPair(token: PaletteToken, palette: Palette): [string, string] | null {
    switch (token) {
        case 'onAccent':
            return [palette.onAccent, palette.accent];
        case 'accent':
        case 'text1':
        case 'text2':
        case 'ok':
        case 'warn':
        case 'danger':
        case 'info':
            return [palette[token], palette.panel];
        default:
            return null;
    }
}

/** Text pairs below the readable minimum. Matches readability_problems on the server. */
export function readabilityProblems(palette: Palette): Array<{ token: PaletteToken; ratio: number }> {
    const checked: PaletteToken[] = ['text1', 'text2', 'accent', 'onAccent'];
    return checked
        .map((token) => {
            const pair = contrastPair(token, palette);
            return { token, ratio: pair ? displayedRatio(contrastRatio(pair[0], pair[1])) : 21 };
        })
        .filter((entry) => entry.ratio < READABLE_CONTRAST_MIN);
}

/**
 * The nearest readable version of a color against a background: it is darkened or lightened
 * toward whichever extreme raises contrast, in small steps, until it passes.
 */
export function suggestReadableColor(color: string, background: string): string {
    const target = luminance(background) > 0.4 ? '#000000' : '#FFFFFF';
    for (let step = 1; step <= 20; step += 1) {
        const candidate = mixColors(color, target, step / 20);
        if (displayedRatio(contrastRatio(candidate, background)) >= READABLE_CONTRAST_MIN) {
            return candidate;
        }
    }
    return target;
}

/* -------------------------------------------------------------------------- */
/* CSS                                                                         */
/* -------------------------------------------------------------------------- */

/** The theme.css custom properties a palette sets, for one base. */
export function paletteDeclarations(palette: Palette, base: ColorBase): Record<string, string> {
    const dark = base === 'dark';
    const soft = dark ? 0.16 : 0.12;
    return {
        '--backdrop-base': palette.backdrop,
        '--backdrop-tint-a': rgba(palette.accent, dark ? 0.26 : 0.28),
        '--backdrop-tint-b': rgba(mixColors(palette.accent, '#A078FF', 0.5), dark ? 0.2 : 0.22),
        '--backdrop-tint-c': rgba(mixColors(palette.accent, '#56C4FF', 0.5), dark ? 0.18 : 0.2),
        '--surface-1': rgba(palette.panel, dark ? 0.55 : 0.62),
        '--surface-2': rgba(palette.panel, dark ? 0.7 : 0.74),
        '--surface-3': rgba(palette.panel, dark ? 0.85 : 0.86),
        '--surface-modal': rgba(palette.panel, 0.97),
        '--surface-solid': palette.panel,
        '--surface-sunken': dark ? 'rgb(0 0 0 / 0.25)' : rgba(palette.text1, 0.04),
        '--edge': dark ? rgba(palette.border, 0.6) : 'rgb(255 255 255 / 0.70)',
        '--edge-strong': palette.border,
        '--text-1': palette.text1,
        '--text-2': palette.text2,
        '--text-3': mixColors(palette.text2, palette.backdrop, 0.22),
        '--accent': palette.accent,
        '--accent-hover': mixColors(palette.accent, dark ? '#FFFFFF' : '#000000', dark ? 0.15 : 0.12),
        '--accent-soft': rgba(palette.accent, soft),
        '--accent-ring': rgba(palette.accent, dark ? 0.55 : 0.45),
        '--on-accent': palette.onAccent,
        '--danger': palette.danger,
        '--danger-soft': rgba(palette.danger, soft),
        '--warn': palette.warn,
        '--warn-soft': rgba(palette.warn, soft),
        '--ok': palette.ok,
        '--ok-soft': rgba(palette.ok, soft),
        '--ok-strong': palette.ok,
        '--ok-strong-hover': mixColors(palette.ok, dark ? '#FFFFFF' : '#000000', 0.15),
        '--info': palette.info,
        '--info-soft': rgba(palette.info, soft),
    };
}

function block(selector: string, declarations: Record<string, string>): string {
    const body = Object.entries(declarations)
        .map(([name, value]) => `${name}:${value};`)
        .join('');
    return `${selector}{${body}}`;
}

/**
 * The stylesheet for the active colors, or an empty string for the shipped defaults.
 *
 * `html:root` and `html.dark` outrank the `:root` and `.dark` rules in theme.css whatever
 * order the two stylesheets load in. A custom user mode is a single palette, so it applies
 * to both selectors and the document is put in that mode's base by the caller.
 */
export function buildColorSchemeCss(options: {
    scheme: ColorScheme | null;
    custom: CustomColorMode | null;
}): string {
    if (options.custom) {
        return block('html:root,html.dark', paletteDeclarations(options.custom.colors, options.custom.base));
    }
    if (options.scheme) {
        return (
            block('html:root', paletteDeclarations(options.scheme.light, 'light')) +
            block('html.dark', paletteDeclarations(options.scheme.dark, 'dark'))
        );
    }
    return '';
}

/* -------------------------------------------------------------------------- */
/* Theme Card code                                                             */
/* -------------------------------------------------------------------------- */

export const THEME_CARD_PREFIX = 'SCTHEME1';
const THEME_CARD_VERSION = 1;
const THEME_CARD_CODE_MAX = 2048;
const THEME_CARD_CHECKSUM_BYTES = 16;

export type ThemeCardError = 'not-a-card' | 'changed' | 'newer-version' | 'invalid-colors';

export const THEME_CARD_ERROR_MESSAGES: Record<ThemeCardError, string> = {
    'not-a-card': "This isn't a SimpleChat Theme Card.",
    changed: 'This card was changed after it was made, so it can’t be trusted. Ask the sender for a new one.',
    'newer-version': 'This card was made by a newer version of SimpleChat.',
    'invalid-colors': 'This card’s colors aren’t valid.',
};

function base64UrlEncode(bytes: Uint8Array): string {
    let binary = '';
    bytes.forEach((byte) => {
        binary += String.fromCharCode(byte);
    });
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function base64UrlDecode(text: string): Uint8Array | null {
    if (!/^[A-Za-z0-9_-]*$/.test(text)) {
        return null;
    }
    try {
        const padded = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4);
        const binary = atob(padded);
        return Uint8Array.from(binary, (character) => character.charCodeAt(0));
    } catch {
        return null;
    }
}

async function checksum(payload: string): Promise<string> {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${THEME_CARD_PREFIX}.${payload}`));
    return base64UrlEncode(new Uint8Array(digest).slice(0, THEME_CARD_CHECKSUM_BYTES));
}

export async function encodeThemeCardCode(mode: CustomColorMode): Promise<string> {
    const body = {
        v: THEME_CARD_VERSION,
        n: normalizeColorModeName(mode.name) || 'My color mode',
        b: mode.base,
        c: Object.fromEntries(PALETTE_TOKENS.map((token) => [token, mode.colors[token].slice(1).toUpperCase()])),
    };
    const payload = base64UrlEncode(new TextEncoder().encode(JSON.stringify(body)));
    return `${THEME_CARD_PREFIX}.${payload}.${await checksum(payload)}`;
}

export async function decodeThemeCardCode(
    code: string,
): Promise<{ ok: true; mode: CustomColorMode } | { ok: false; error: ThemeCardError }> {
    const trimmed = code.trim();
    const parts = trimmed.split('.');
    if (trimmed.length > THEME_CARD_CODE_MAX || parts.length !== 3 || parts[0] !== THEME_CARD_PREFIX) {
        return { ok: false, error: 'not-a-card' };
    }
    if ((await checksum(parts[1])) !== parts[2]) {
        return { ok: false, error: 'changed' };
    }
    const bytes = base64UrlDecode(parts[1]);
    let body: unknown;
    try {
        body = bytes ? JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) : null;
    } catch {
        body = null;
    }
    if (!body || typeof body !== 'object') {
        return { ok: false, error: 'not-a-card' };
    }
    const record = body as Record<string, unknown>;
    if (record.v !== THEME_CARD_VERSION) {
        return { ok: false, error: 'newer-version' };
    }
    const rawColors = record.c && typeof record.c === 'object' ? (record.c as Record<string, unknown>) : null;
    const mode = normalizeCustomColorMode({
        name: record.n,
        base: record.b,
        colors: rawColors
            ? Object.fromEntries(Object.entries(rawColors).map(([token, value]) => [token, typeof value === 'string' ? `#${value}` : value]))
            : null,
    });
    return mode ? { ok: true, mode } : { ok: false, error: 'invalid-colors' };
}
