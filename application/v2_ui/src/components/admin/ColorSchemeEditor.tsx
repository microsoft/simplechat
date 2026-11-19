// ColorSchemeEditor.tsx
// Admin Settings > Appearance: the colors everyone sees in light mode and dark mode.
//
// A table of the eleven palette colors with the light and dark values side by side, a
// contrast badge on every color that carries text, and live previews of both modes. Edits go
// into the page draft like any other field and are saved with the page's Save bar, where the
// server validates them (functions_color_schemes.normalize_color_scheme). A null value means
// the SimpleChat default colors; nothing is injected then.

import { useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { ImageUp, Moon, RotateCcw, Sun } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { ColorField, ColorPreview, ContrastBadge } from '../appearance/ColorControls';
import { ImportThemeCardDialog } from '../appearance/ThemeCardDialogs';
import {
    DEFAULT_DARK,
    DEFAULT_LIGHT,
    PALETTE_TOKEN_INFO,
    contrastPair,
    contrastRatio,
    normalizeColorScheme,
    readabilityProblems,
    suggestReadableColor,
    type ColorBase,
    type ColorScheme,
    type PaletteToken,
} from '../../lib/colorScheme';
import type { AdminField } from '../../lib/adminFields';

const GROUPS = ['Brand', 'Surfaces', 'Text', 'Status'] as const;

export function ColorSchemeEditor({
    field,
    value,
    error,
    disabled,
    onChange,
}: {
    field: AdminField;
    value: unknown;
    error?: string | null;
    disabled?: boolean;
    onChange: (next: ColorScheme | null) => void;
}) {
    const stored = normalizeColorScheme(value);
    const scheme: ColorScheme = useMemo(() => stored ?? { light: DEFAULT_LIGHT, dark: DEFAULT_DARK }, [stored]);
    const [showStatus, setShowStatus] = useState(false);
    const [importing, setImporting] = useState(false);

    const setColor = (base: ColorBase, token: PaletteToken, color: string) => {
        onChange({ ...scheme, [base]: { ...scheme[base], [token]: color } });
    };

    const warnings = (['light', 'dark'] as const).flatMap((base) =>
        readabilityProblems(scheme[base]).map((problem) => ({ base, ...problem })),
    );

    return (
        <div className="min-w-0 py-3">
            <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
                <div>
                    <h4 className="text-sm font-semibold text-text-1">{field.label}</h4>
                    {field.help ? <p className="mt-0.5 max-w-[72ch] text-[0.8125rem] leading-relaxed text-text-3">{field.help}</p> : null}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    {!stored ? (
                        <span className="rounded-full border border-edge-strong bg-surface-2 px-2 py-0.5 text-xs text-text-2">
                            Using SimpleChat default
                        </span>
                    ) : null}
                    <GlassButton variant="subtle" size="sm" disabled={disabled} onClick={() => setImporting(true)}>
                        <ImageUp size={14} aria-hidden="true" /> Import Theme Card
                    </GlassButton>
                    <GlassButton variant="ghost" size="sm" disabled={disabled || !stored} onClick={() => onChange(null)}>
                        <RotateCcw size={14} aria-hidden="true" /> Reset to SimpleChat default
                    </GlassButton>
                </div>
            </div>

            <div className="grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
                <div className="overflow-hidden rounded-xl border border-edge-strong">
                    <div className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)] items-center gap-3 border-b border-edge-strong bg-surface-2 px-4 py-2 text-xs font-semibold tracking-wide text-text-2 uppercase">
                        <span>Color</span>
                        <span className="inline-flex items-center gap-1.5"><Sun size={13} aria-hidden="true" /> Light mode</span>
                        <span className="inline-flex items-center gap-1.5"><Moon size={13} aria-hidden="true" /> Dark mode</span>
                    </div>
                    {GROUPS.map((group) => {
                        const rows = PALETTE_TOKEN_INFO.filter((row) => row.group === group);
                        const collapsed = group === 'Status' && !showStatus;
                        return (
                            <div key={group}>
                                <div className="flex items-center justify-between bg-surface-1 px-4 pt-3 pb-1">
                                    <span className="text-[11px] font-bold tracking-[0.08em] text-accent uppercase">{group}</span>
                                    {group === 'Status' ? (
                                        <button
                                            type="button"
                                            onClick={() => setShowStatus(!showStatus)}
                                            aria-expanded={showStatus}
                                            className="flex items-center gap-1.5 text-xs text-text-3 hover:text-text-1"
                                        >
                                            {collapsed
                                                ? rows.map((row) => (
                                                      <span key={row.token} className="h-4 w-4 rounded border border-edge-strong" style={{ background: scheme.light[row.token] }} />
                                                  ))
                                                : null}
                                            {collapsed ? 'Show 4 status colors' : 'Hide status colors'}
                                        </button>
                                    ) : null}
                                </div>
                                {collapsed
                                    ? null
                                    : rows.map((row) => (
                                          <div
                                              key={row.token}
                                              className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)] items-center gap-3 border-t border-edge px-4 py-2.5"
                                          >
                                              <div className="min-w-0">
                                                  <p className="text-sm font-medium text-text-1">{row.label}</p>
                                                  <p className="truncate text-xs text-text-3">{row.hint}</p>
                                              </div>
                                              {(['light', 'dark'] as const).map((base) => {
                                                  const pair = contrastPair(row.token, scheme[base]);
                                                  return (
                                                      <div key={base} className="flex flex-wrap items-center gap-2">
                                                          <ColorField
                                                              label={`${row.label}, ${base} mode`}
                                                              value={scheme[base][row.token]}
                                                              disabled={disabled}
                                                              onChange={(color) => setColor(base, row.token, color)}
                                                          />
                                                          {pair ? <ContrastBadge foreground={pair[0]} background={pair[1]} /> : null}
                                                      </div>
                                                  );
                                              })}
                                          </div>
                                      ))}
                            </div>
                        );
                    })}
                    {warnings.length ? (
                        <div className="m-3 space-y-1.5 rounded-xl border border-warn/30 bg-warn-soft px-3 py-2 text-xs text-text-1">
                            {warnings.map((warning) => {
                                const info = PALETTE_TOKEN_INFO.find((row) => row.token === warning.token);
                                const pair = contrastPair(warning.token, scheme[warning.base]);
                                const suggestion = pair ? suggestReadableColor(pair[0], pair[1]) : null;
                                return (
                                    <p key={`${warning.base}-${warning.token}`} className="flex flex-wrap items-center gap-x-2">
                                        <span className="font-semibold">
                                            {info?.label} in {warning.base} mode is hard to read ({warning.ratio.toFixed(1)}:1).
                                        </span>
                                        <span className="text-text-2">You can still save, but people with low vision may struggle.</span>
                                        {suggestion && contrastRatio(suggestion, pair![1]) >= 4.5 ? (
                                            <button
                                                type="button"
                                                disabled={disabled}
                                                className="font-semibold text-accent underline"
                                                onClick={() => setColor(warning.base, warning.token, suggestion)}
                                            >
                                                Use {suggestion} instead
                                            </button>
                                        ) : null}
                                    </p>
                                );
                            })}
                        </div>
                    ) : null}
                </div>
                <div className={clsx('space-y-4 xl:sticky xl:top-4 xl:self-start')}>
                    <ColorPreview label="Light mode preview" palette={scheme.light} height={290} />
                    <ColorPreview label="Dark mode preview" palette={scheme.dark} height={290} />
                </div>
            </div>
            {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}

            {importing ? (
                <ImportThemeCardDialog
                    description="The card's colors replace the light or dark column, whichever the card was made for. Nothing is saved until you save the page."
                    importLabel="Use these colors"
                    onClose={() => setImporting(false)}
                    onImport={(mode) => {
                        onChange({ ...scheme, [mode.base]: mode.colors });
                        setImporting(false);
                    }}
                />
            ) : null}
        </div>
    );
}
