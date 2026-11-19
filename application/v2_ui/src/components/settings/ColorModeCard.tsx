// ColorModeCard.tsx
// Settings > Preferences > Appearance: how SimpleChat looks for this user.
//
// Light, Dark and Match system are always offered. Custom is offered while an administrator
// allows custom color modes (on by default): it opens a one-column color table with contrast
// badges and a live preview. A custom mode can be shared as a Theme Card image and one can be
// imported, when the administrator allows Theme Cards.
//
// The colors are saved through the user settings API, where the server validates every value
// again (functions_color_schemes.normalize_custom_color_mode) and enforces the administrator's
// contrast rule. A refused save is rolled back here and reported.

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { ImageDown, ImageUp, Monitor, Moon, Palette as PaletteIcon, Sun } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { SettingsCard } from './SettingsCard';
import { ChoiceRow, ColorField, ColorPreview, ContrastBadge } from '../appearance/ColorControls';
import { ImportThemeCardDialog, ShareThemeCardDialog } from '../appearance/ThemeCardDialogs';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useUiStore } from '../../stores/uiStore';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import { toast } from '../../stores/toastStore';
import { useCustomColorModesAllowed } from '../../lib/useColorSchemeRuntime';
import {
    COLOR_MODE_NAME_MAX,
    DEFAULT_DARK,
    DEFAULT_LIGHT,
    PALETTE_TOKEN_INFO,
    contrastPair,
    normalizeColorScheme,
    readabilityProblems,
    type ColorBase,
    type ColorMode,
    type CustomColorMode,
    type Palette,
} from '../../lib/colorScheme';

function sameMode(a: CustomColorMode | null, b: CustomColorMode | null): boolean {
    return JSON.stringify(a) === JSON.stringify(b);
}

export function ColorModeCard() {
    const { customAllowed, cardsAllowed, requireReadable } = useCustomColorModesAllowed();
    const rawScheme = useBootstrapStore((state) => (state.data?.settings as Record<string, unknown> | undefined)?.v2_color_scheme);
    const colorMode = useUiStore((state) => state.colorMode);
    const saved = useUiStore((state) => state.customColorMode);
    const setColorMode = useUiStore((state) => state.setColorMode);
    const saveCustomColorMode = useUiStore((state) => state.saveCustomColorMode);
    const theme = useUiStore((state) => state.theme);

    const orgPalettes = useMemo(() => normalizeColorScheme(rawScheme) ?? { light: DEFAULT_LIGHT, dark: DEFAULT_DARK }, [rawScheme]);
    const startingPoint = (base: ColorBase): CustomColorMode => ({ name: 'My color mode', base, colors: orgPalettes[base] });

    // Picking Custom with nothing saved yet shows the editor without switching modes; the
    // interface changes once the colors are saved.
    const [editing, setEditing] = useState(colorMode === 'custom');
    const [draft, setDraft] = useState<CustomColorMode>(saved ?? startingPoint(theme));
    const [showStatus, setShowStatus] = useState(false);
    const [saving, setSaving] = useState(false);
    const [sharing, setSharing] = useState<CustomColorMode | null>(null);
    const [importing, setImporting] = useState(false);

    useEffect(() => {
        if (saved) {
            setDraft(saved);
        }
    }, [saved]);

    const selected: ColorMode = editing && customAllowed ? 'custom' : colorMode === 'custom' && !customAllowed ? theme : colorMode;
    const problems = readabilityProblems(draft.colors);
    const blocked = requireReadable && problems.length > 0;
    const dirty = !sameMode(draft, saved);

    const choose = (next: ColorMode) => {
        if (next === 'custom') {
            setEditing(true);
            if (saved) {
                setColorMode('custom');
            }
            return;
        }
        setEditing(false);
        setColorMode(next);
    };

    const setColor = (token: keyof Palette, color: string) => setDraft({ ...draft, colors: { ...draft.colors, [token]: color } });

    const save = async () => {
        setSaving(true);
        const ok = await saveCustomColorMode(draft);
        setSaving(false);
        if (ok) {
            setColorMode('custom');
            toast.success(`“${draft.name}” is now your color mode.`);
        } else {
            toast.error(useUserSettingsStore.getState().saveError ?? "Your colors couldn't be saved.");
        }
    };

    const choices: Array<{ value: ColorMode; label: string; icon: ReactNode }> = [
        { value: 'light', label: 'Light', icon: <Sun size={14} aria-hidden="true" /> },
        { value: 'dark', label: 'Dark', icon: <Moon size={14} aria-hidden="true" /> },
        { value: 'system', label: 'Match system', icon: <Monitor size={14} aria-hidden="true" /> },
    ];
    if (customAllowed) {
        choices.push({ value: 'custom', label: 'Custom', icon: <PaletteIcon size={14} aria-hidden="true" /> });
    }

    const rows = PALETTE_TOKEN_INFO.filter((row) => showStatus || row.group !== 'Status');

    return (
        <SettingsCard
            title="Color mode"
            Icon={PaletteIcon}
            description={
                customAllowed
                    ? 'Choose how SimpleChat looks for you, or build your own colors.'
                    : 'Choose how SimpleChat looks for you.'
            }
        >
            <ChoiceRow label="Color mode" value={selected} onChange={choose} choices={choices} />

            {selected === 'custom' ? (
                <>
                    <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
                        <div className="min-w-0">
                            <div className="mb-3 flex flex-wrap items-center gap-3">
                                <input
                                    aria-label="Color mode name"
                                    value={draft.name}
                                    maxLength={COLOR_MODE_NAME_MAX}
                                    onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                                    className="h-9 min-w-0 flex-1 rounded-lg border border-edge-strong bg-surface-solid px-3 text-sm text-text-1"
                                />
                                <span className="text-xs text-text-3">Start from</span>
                                <ChoiceRow
                                    label="Start from"
                                    value={draft.base}
                                    onChange={(base) => setDraft({ ...startingPoint(base), name: draft.name })}
                                    choices={[
                                        { value: 'light', label: 'Light' },
                                        { value: 'dark', label: 'Dark' },
                                    ]}
                                />
                            </div>
                            <div className="overflow-hidden rounded-xl border border-edge-strong">
                                {rows.map((row, index) => {
                                    const pair = contrastPair(row.token, draft.colors);
                                    return (
                                        <div key={row.token} className={clsx('flex items-center justify-between gap-3 px-3 py-2', index > 0 && 'border-t border-edge')}>
                                            <div className="min-w-0">
                                                <p className="text-sm font-medium text-text-1">{row.label}</p>
                                                <p className="truncate text-xs text-text-3">{row.hint}</p>
                                            </div>
                                            <div className="flex shrink-0 items-center gap-2">
                                                {pair ? <ContrastBadge foreground={pair[0]} background={pair[1]} /> : null}
                                                <ColorField label={row.label} value={draft.colors[row.token]} onChange={(color) => setColor(row.token, color)} />
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                            <button
                                type="button"
                                aria-expanded={showStatus}
                                onClick={() => setShowStatus(!showStatus)}
                                className="mt-2 text-xs font-medium text-accent hover:underline"
                            >
                                {showStatus ? 'Hide status colors' : 'Show status colors (4)'}
                            </button>
                            {blocked ? (
                                <p role="status" className="mt-2 rounded-lg border border-warn/30 bg-warn-soft px-3 py-2 text-xs text-text-1">
                                    Some text would be hard to read. Your administrator requires readable colors, so fix the colors marked Low before saving.
                                </p>
                            ) : null}
                        </div>
                        <ColorPreview label="Preview" palette={draft.colors} height={340} compact />
                    </div>
                    <div className="mt-5 flex flex-wrap items-center justify-between gap-2 border-t border-edge-strong pt-4">
                        <div className="flex flex-wrap gap-2">
                            {cardsAllowed ? (
                                <>
                                    <GlassButton variant="subtle" size="sm" onClick={() => setSharing({ ...draft, name: draft.name.trim() || 'My color mode' })}>
                                        <ImageDown size={14} aria-hidden="true" /> Share as Theme Card
                                    </GlassButton>
                                    <GlassButton variant="subtle" size="sm" onClick={() => setImporting(true)}>
                                        <ImageUp size={14} aria-hidden="true" /> Import Theme Card
                                    </GlassButton>
                                </>
                            ) : null}
                        </div>
                        <div className="flex gap-2">
                            <GlassButton variant="ghost" size="sm" disabled={!dirty} onClick={() => setDraft(saved ?? startingPoint(theme))}>
                                Reset
                            </GlassButton>
                            <GlassButton variant="primary" size="sm" disabled={saving || blocked || (!dirty && colorMode === 'custom')} onClick={save}>
                                Save my color mode
                            </GlassButton>
                        </div>
                    </div>
                </>
            ) : null}

            {sharing ? <ShareThemeCardDialog mode={sharing} onClose={() => setSharing(null)} /> : null}
            {importing ? (
                <ImportThemeCardDialog
                    requireReadable={requireReadable}
                    importLabel="Use these colors"
                    description="Drop a Theme Card image someone shared with you. Its colors fill in below, and nothing changes until you save."
                    onClose={() => setImporting(false)}
                    onImport={(mode) => {
                        setDraft(mode);
                        setImporting(false);
                    }}
                />
            ) : null}
        </SettingsCard>
    );
}
