// StatsExportDialog.tsx
// Downloads the user's own activity as a CSV file.
//
// The export has its own window rather than reusing whatever the tab is showing. Looking at
// the last 7 days and exporting the last 90 is a perfectly ordinary thing to want, and tying
// the two together would force a detour through the chart controls to get it.
//
// The file is assembled in the browser from the two responses the tab already reads. There is
// no export endpoint, and adding one would mean maintaining a second implementation of totals
// that are on screen at the time.
//
// Dialog conventions match ImageLightbox: a click-to-close backdrop, Escape to dismiss, focus
// moved in on open and handed back on close, and no focus-trap utility, since no other dialog
// in this interface uses one.

import { useCallback, useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Download, Loader2, X } from 'lucide-react';
import { api } from '../../lib/apiClient';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { toast } from '../../stores/toastStore';
import {
    DEFAULT_EXPORT_SECTIONS,
    STATS_WINDOWS,
    activityCsvFileName,
    buildActivityCsv,
    statsWindowLabel,
    statsWindowQuery,
    validateCustomRange,
    type ActivityTrends,
    type ExportSections,
    type StatsWindow,
    type UserSettingsWithMetrics,
} from '../../lib/userStats';

const SECTION_LABELS: { key: keyof ExportSections; label: string; hint: string }[] = [
    { key: 'metrics', label: 'Summary totals', hint: 'Lifetime counts and storage sizes' },
    { key: 'logins', label: 'Sign-ins', hint: 'One row per day' },
    { key: 'conversations', label: 'Conversations', hint: 'Created and deleted per day' },
    { key: 'documents', label: 'Documents', hint: 'Uploaded and deleted per day' },
    { key: 'tokens', label: 'Token usage', hint: 'Total tokens per day' },
];

/** Hand the assembled text to the browser as a file. */
function downloadCsv(contents: string, fileName: string) {
    // The BOM is what makes Excel open a UTF-8 CSV without mangling non-ASCII names.
    const blob = new Blob([`\ufeff${contents}`], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

export function StatsExportDialog({
    initialWindow,
    userName,
    userEmail,
    onClose,
}: {
    /** The tab's current window, offered as the starting point. */
    initialWindow: StatsWindow;
    userName: string;
    userEmail: string;
    onClose: () => void;
}) {
    const [sections, setSections] = useState<ExportSections>(DEFAULT_EXPORT_SECTIONS);
    const [days, setDays] = useState<number | 'custom'>(
        initialWindow.startDate && initialWindow.endDate ? 'custom' : initialWindow.days,
    );
    const [startDate, setStartDate] = useState(initialWindow.startDate);
    const [endDate, setEndDate] = useState(initialWindow.endDate);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const closeRef = useRef<HTMLButtonElement>(null);

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onClose();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [onClose]);

    useEffect(() => {
        const previous = document.activeElement as HTMLElement | null;
        closeRef.current?.focus();
        return () => previous?.focus?.();
    }, []);

    const anySelected = Object.values(sections).some(Boolean);

    const handleExport = useCallback(async () => {
        if (!anySelected) {
            setError('Choose at least one thing to export.');
            return;
        }

        let selected: StatsWindow;
        if (days === 'custom') {
            const validation = validateCustomRange(startDate, endDate);
            if (!validation.ok) {
                setError(validation.error);
                return;
            }
            selected = validation.window;
        } else {
            selected = { days, startDate: '', endDate: '' };
        }

        setBusy(true);
        setError(null);
        try {
            const [trends, settings] = await Promise.all([
                api.get<ActivityTrends>(`/api/user/activity-trends?${statsWindowQuery(selected)}`),
                api.get<UserSettingsWithMetrics>('/api/user/settings'),
            ]);

            const csv = buildActivityCsv({
                trends,
                metrics: settings?.settings?.metrics ?? {},
                sections,
                userName,
                userEmail,
                // Prefer the window the server resolved: for a custom range it is the
                // authoritative statement of what the rows actually cover.
                windowLabel: trends?.window?.label || statsWindowLabel(selected),
            });

            downloadCsv(csv, activityCsvFileName());
            toast.success('Activity exported.');
            onClose();
        } catch (caught) {
            setError(
                caught instanceof Error ? caught.message : 'The export could not be prepared.',
            );
        } finally {
            setBusy(false);
        }
    }, [anySelected, days, startDate, endDate, sections, userName, userEmail, onClose]);

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
            role="presentation"
            onClick={(event) => {
                if (event.target === event.currentTarget) {
                    onClose();
                }
            }}
        >
            <GlassPanel
                elevation="modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="stats-export-title"
                className="max-h-full w-full max-w-md overflow-y-auto p-5"
            >
                <div className="flex items-start justify-between gap-3">
                    <div>
                        <h2 id="stats-export-title" className="text-sm font-semibold text-text-1">
                            Export activity
                        </h2>
                        <p className="mt-1 text-xs text-text-3">
                            Downloads a CSV of your own activity. Nothing is shared.
                        </p>
                    </div>
                    <button
                        ref={closeRef}
                        type="button"
                        onClick={onClose}
                        aria-label="Close"
                        className="rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={16} />
                    </button>
                </div>

                <fieldset className="mt-4">
                    <legend className="text-xs font-semibold text-text-2">Include</legend>
                    <div className="mt-2 space-y-1.5">
                        {SECTION_LABELS.map(({ key, label, hint }) => (
                            <label
                                key={key}
                                className="flex cursor-pointer items-start gap-2.5 rounded-lg px-1 py-1"
                            >
                                <input
                                    type="checkbox"
                                    checked={sections[key]}
                                    onChange={(event) => {
                                        setError(null);
                                        setSections((current) => ({
                                            ...current,
                                            [key]: event.target.checked,
                                        }));
                                    }}
                                    className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--accent)]"
                                />
                                <span className="min-w-0">
                                    <span className="block text-sm text-text-1">{label}</span>
                                    <span className="block text-xs text-text-3">{hint}</span>
                                </span>
                            </label>
                        ))}
                    </div>
                </fieldset>

                <fieldset className="mt-4">
                    <legend className="text-xs font-semibold text-text-2">Period</legend>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                        {STATS_WINDOWS.map((preset) => (
                            <button
                                key={preset.days}
                                type="button"
                                aria-pressed={days === preset.days}
                                onClick={() => {
                                    setError(null);
                                    setDays(preset.days);
                                }}
                                className={clsx(
                                    'rounded-lg border px-3 py-1.5 text-xs transition-colors',
                                    days === preset.days
                                        ? 'border-accent bg-accent-soft font-medium text-accent'
                                        : 'border-edge text-text-2 hover:bg-surface-2',
                                )}
                            >
                                {preset.label}
                            </button>
                        ))}
                        <button
                            type="button"
                            aria-pressed={days === 'custom'}
                            onClick={() => {
                                setError(null);
                                setDays('custom');
                            }}
                            className={clsx(
                                'rounded-lg border px-3 py-1.5 text-xs transition-colors',
                                days === 'custom'
                                    ? 'border-accent bg-accent-soft font-medium text-accent'
                                    : 'border-edge text-text-2 hover:bg-surface-2',
                            )}
                        >
                            Custom
                        </button>
                    </div>

                    {days === 'custom' && (
                        <div className="mt-3 grid grid-cols-2 gap-2">
                            <label className="text-xs text-text-2">
                                Start
                                <input
                                    type="date"
                                    value={startDate}
                                    onChange={(event) => {
                                        setError(null);
                                        setStartDate(event.target.value);
                                    }}
                                    className="mt-1 w-full rounded-lg border border-edge bg-surface-sunken px-2 py-1.5 text-sm text-text-1"
                                />
                            </label>
                            <label className="text-xs text-text-2">
                                End
                                <input
                                    type="date"
                                    value={endDate}
                                    onChange={(event) => {
                                        setError(null);
                                        setEndDate(event.target.value);
                                    }}
                                    className="mt-1 w-full rounded-lg border border-edge bg-surface-sunken px-2 py-1.5 text-sm text-text-1"
                                />
                            </label>
                        </div>
                    )}
                </fieldset>

                {error && (
                    <p role="alert" className="mt-3 text-xs text-danger">
                        {error}
                    </p>
                )}

                <div className="mt-5 flex justify-end gap-2">
                    <GlassButton type="button" size="sm" onClick={onClose}>
                        Cancel
                    </GlassButton>
                    <GlassButton
                        type="button"
                        variant="primary"
                        size="sm"
                        disabled={busy}
                        onClick={() => void handleExport()}
                    >
                        {busy ? (
                            <Loader2 size={14} className="animate-spin" />
                        ) : (
                            <Download size={14} />
                        )}
                        {busy ? 'Preparing' : 'Download CSV'}
                    </GlassButton>
                </div>
            </GlassPanel>
        </div>
    );
}
