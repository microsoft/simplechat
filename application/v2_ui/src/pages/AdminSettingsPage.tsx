// AdminSettingsPage.tsx
// Admin settings, reimagined as a search-first surface.
//
// The server-rendered page nests 14 groups -> 46 tabs -> 96 sections, which means finding
// one toggle can take several clicks through two levels of tabs. Here the same structure
// (still sourced from admin_settings_nav.py, so it cannot drift) is flattened: a slim
// category rail, a single scrollable pane, and a search box that matches across every
// section and every capability key at once.

import { useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Loader2, Search, ShieldAlert, TriangleAlert, Check } from 'lucide-react';
import { api } from '../lib/apiClient';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassPanel, Skeleton, Toggle } from '../components/ui/primitives';
import type { AdminNavGroup, Json } from '../lib/types';

interface AdminSettingsResponse {
    settings: Json;
    admin_nav: AdminNavGroup[];
    version: string;
}

/** One searchable row: a capability key rendered under its section and tab. */
interface CapabilityRow {
    key: string;
    label: string;
    groupId: string;
    groupLabel: string;
    tabLabel: string;
    sectionId: string;
    sectionLabel: string;
}

/** Turn `enable_document_classification` into `Document classification`. */
function humanizeKey(key: string): string {
    const withoutPrefix = key.replace(/^enable_/, '').replace(/_/g, ' ').trim();
    return withoutPrefix.charAt(0).toUpperCase() + withoutPrefix.slice(1);
}

/**
 * Associate each `enable_*` setting with a section.
 *
 * The navigation definition names sections but does not enumerate which settings keys
 * belong to them, so keys are matched to the section whose id shares the most leading
 * word stems. Anything with no reasonable match is collected under "Other capabilities"
 * rather than being hidden, because a silently missing toggle is worse than a misfiled one.
 */
function buildCapabilityIndex(
    nav: AdminNavGroup[],
    settings: Json,
): { rows: CapabilityRow[]; unmatched: CapabilityRow[] } {
    const capabilityKeys = Object.keys(settings)
        .filter((key) => key.startsWith('enable_') && typeof settings[key] === 'boolean')
        .sort();

    const sections = nav.flatMap((group) =>
        group.tabs.flatMap((tab) =>
            tab.sections.map((section) => ({
                groupId: group.id,
                groupLabel: group.label,
                tabLabel: tab.label,
                sectionId: section.id,
                sectionLabel: section.label,
                tokens: new Set(
                    section.id
                        .replace(/-section$/, '')
                        .split('-')
                        .filter((token) => token.length > 2),
                ),
            })),
        ),
    );

    const rows: CapabilityRow[] = [];
    const unmatched: CapabilityRow[] = [];

    for (const key of capabilityKeys) {
        const keyTokens = key
            .replace(/^enable_/, '')
            .split('_')
            .filter((token) => token.length > 2);

        let best: (typeof sections)[number] | null = null;
        let bestScore = 0;

        for (const section of sections) {
            let score = 0;
            for (const token of keyTokens) {
                if (section.tokens.has(token)) {
                    score += 1;
                }
            }
            if (score > bestScore) {
                bestScore = score;
                best = section;
            }
        }

        const row: CapabilityRow = {
            key,
            label: humanizeKey(key),
            groupId: best?.groupId ?? '__other',
            groupLabel: best?.groupLabel ?? 'Other',
            tabLabel: best?.tabLabel ?? '',
            sectionId: best?.sectionId ?? '__other',
            sectionLabel: best?.sectionLabel ?? 'Other capabilities',
        };

        if (best) {
            rows.push(row);
        } else {
            unmatched.push(row);
        }
    }

    return { rows, unmatched };
}

export function AdminSettingsPage() {
    const isAdmin = useBootstrapStore((state) => Boolean(state.data?.user?.is_admin));

    const [data, setData] = useState<AdminSettingsResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [query, setQuery] = useState('');
    const [activeGroup, setActiveGroup] = useState<string | null>(null);
    const [savingKey, setSavingKey] = useState<string | null>(null);
    const [savedKey, setSavedKey] = useState<string | null>(null);

    const searchRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        if (!isAdmin) {
            setLoading(false);
            return;
        }

        let cancelled = false;
        void (async () => {
            try {
                const response = await api.get<AdminSettingsResponse>('/api/v2/admin/settings');
                if (!cancelled) {
                    setData(response);
                    setLoading(false);
                }
            } catch (fetchError) {
                if (!cancelled) {
                    setError(
                        fetchError instanceof Error
                            ? fetchError.message
                            : 'Failed to load settings.',
                    );
                    setLoading(false);
                }
            }
        })();

        return () => {
            cancelled = true;
        };
    }, [isAdmin]);

    // "/" focuses search from anywhere on the page, which is the whole point of a
    // search-first surface.
    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            const target = event.target as HTMLElement | null;
            const typingInField =
                target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA';
            if (event.key === '/' && !typingInField) {
                event.preventDefault();
                searchRef.current?.focus();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, []);

    const { rows, unmatched } = useMemo(() => {
        if (!data) {
            return { rows: [] as CapabilityRow[], unmatched: [] as CapabilityRow[] };
        }
        return buildCapabilityIndex(data.admin_nav, data.settings);
    }, [data]);

    const allRows = useMemo(() => [...rows, ...unmatched], [rows, unmatched]);

    const visibleRows = useMemo(() => {
        const needle = query.trim().toLowerCase();

        return allRows.filter((row) => {
            if (needle) {
                // Search spans the key, its readable label and its location, so both
                // "retention" and "data lifecycle" find the same setting.
                const haystack =
                    `${row.key} ${row.label} ${row.sectionLabel} ${row.tabLabel} ${row.groupLabel}`.toLowerCase();
                return haystack.includes(needle);
            }
            if (activeGroup) {
                return row.groupId === activeGroup;
            }
            return true;
        });
    }, [allRows, query, activeGroup]);

    // Group the visible rows by section, preserving the order they were indexed in.
    const grouped = useMemo(() => {
        const bySection = new Map<string, { label: string; group: string; rows: CapabilityRow[] }>();
        for (const row of visibleRows) {
            const existing = bySection.get(row.sectionId);
            if (existing) {
                existing.rows.push(row);
            } else {
                bySection.set(row.sectionId, {
                    label: row.sectionLabel,
                    group: row.groupLabel,
                    rows: [row],
                });
            }
        }
        return [...bySection.entries()];
    }, [visibleRows]);

    const onToggle = async (key: string, next: boolean) => {
        if (!data) {
            return;
        }

        const previous = data.settings[key];
        setSavingKey(key);
        setSavedKey(null);
        setData({ ...data, settings: { ...data.settings, [key]: next } });

        try {
            await api.patch('/api/v2/admin/settings', { settings: { [key]: next } });
            setSavedKey(key);
            window.setTimeout(
                () => setSavedKey((current) => (current === key ? null : current)),
                1800,
            );
        } catch (patchError) {
            // Roll the switch back so the UI never claims a change that did not persist.
            setData((current) =>
                current ? { ...current, settings: { ...current.settings, [key]: previous } } : current,
            );
            setError(
                patchError instanceof Error ? patchError.message : `Could not update ${key}.`,
            );
        } finally {
            setSavingKey(null);
        }
    };

    if (!isAdmin) {
        return (
            <>
                <PageHeader title="Admin settings" />
                <div className="flex flex-1 items-center justify-center p-6">
                    <GlassPanel className="flex max-w-md items-start gap-3 p-5">
                        <ShieldAlert size={20} className="mt-0.5 shrink-0 text-warn" />
                        <div>
                            <p className="font-medium text-text-1">Administrator access required</p>
                            <p className="mt-1 text-sm text-text-3">
                                Your account does not hold the Admin role.
                            </p>
                        </div>
                    </GlassPanel>
                </div>
            </>
        );
    }

    return (
        <>
            <PageHeader
                title="Admin settings"
                description={
                    data
                        ? `${allRows.length} capabilities across ${data.admin_nav.length} groups`
                        : undefined
                }
            />

            <div className="flex min-h-0 flex-1">
                <aside className="hidden w-56 shrink-0 overflow-y-auto border-r border-edge p-3 lg:block">
                    <button
                        type="button"
                        onClick={() => setActiveGroup(null)}
                        className={clsx(
                            'w-full rounded-lg px-3 py-2 text-left text-sm transition-colors',
                            activeGroup === null
                                ? 'bg-accent-soft font-medium text-accent'
                                : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
                        )}
                    >
                        All settings
                    </button>
                    {(data?.admin_nav ?? []).map((group) => (
                        <button
                            key={group.id}
                            type="button"
                            onClick={() => setActiveGroup(group.id)}
                            className={clsx(
                                'w-full rounded-lg px-3 py-2 text-left text-sm transition-colors',
                                activeGroup === group.id
                                    ? 'bg-accent-soft font-medium text-accent'
                                    : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
                            )}
                        >
                            {group.label}
                        </button>
                    ))}
                </aside>

                <div className="flex min-w-0 flex-1 flex-col">
                    <div className="shrink-0 border-b border-edge p-4">
                        <div className="relative mx-auto max-w-2xl">
                            <Search
                                size={16}
                                className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3"
                            />
                            <input
                                ref={searchRef}
                                type="search"
                                value={query}
                                onChange={(event) => setQuery(event.target.value)}
                                placeholder="Search every setting…  (press / to focus)"
                                aria-label="Search settings"
                                className={clsx(
                                    'w-full rounded-xl border border-edge bg-surface-1 py-2.5 pr-3 pl-9',
                                    'text-sm text-text-1 placeholder:text-text-3',
                                    'focus:border-accent focus:outline-none',
                                )}
                            />
                        </div>
                    </div>

                    <div className="min-h-0 flex-1 overflow-y-auto p-4">
                        <div className="mx-auto max-w-3xl space-y-4">
                            {error && (
                                <GlassPanel
                                    elevation="flat"
                                    className="flex items-start gap-2 p-3 text-sm text-danger"
                                >
                                    <TriangleAlert size={16} className="mt-0.5 shrink-0" />
                                    {error}
                                </GlassPanel>
                            )}

                            {loading && (
                                <div className="space-y-3">
                                    {Array.from({ length: 5 }).map((_, index) => (
                                        <Skeleton key={index} className="h-24 w-full" />
                                    ))}
                                </div>
                            )}

                            {!loading && grouped.length === 0 && (
                                <p className="py-12 text-center text-sm text-text-3">
                                    No settings match “{query}”.
                                </p>
                            )}

                            {grouped.map(([sectionId, section]) => (
                                <GlassPanel key={sectionId} edge className="p-4">
                                    <div className="mb-2">
                                        <h2 className="text-sm font-semibold text-text-1">
                                            {section.label}
                                        </h2>
                                        <p className="text-xs text-text-3">{section.group}</p>
                                    </div>
                                    <div className="divide-y divide-edge">
                                        {section.rows.map((row) => (
                                            <div
                                                key={row.key}
                                                className="flex items-center gap-3 py-1"
                                            >
                                                <div className="min-w-0 flex-1">
                                                    <Toggle
                                                        label={row.label}
                                                        description={row.key}
                                                        checked={Boolean(
                                                            data?.settings[row.key],
                                                        )}
                                                        disabled={savingKey === row.key}
                                                        onChange={(next) =>
                                                            void onToggle(row.key, next)
                                                        }
                                                    />
                                                </div>
                                                {savingKey === row.key && (
                                                    <Loader2
                                                        size={14}
                                                        className="shrink-0 animate-spin text-text-3"
                                                    />
                                                )}
                                                {savedKey === row.key && (
                                                    <Check
                                                        size={14}
                                                        className="shrink-0 text-ok"
                                                        aria-label="Saved"
                                                    />
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                </GlassPanel>
                            ))}

                            {!loading && (
                                <p className="pb-6 text-center text-xs text-text-3">
                                    Settings that need more than a switch — endpoints, keys,
                                    prompts and connection tests — remain on the{' '}
                                    <a href="/admin/settings" className="text-accent underline">
                                        classic admin page
                                    </a>
                                    .
                                </p>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </>
    );
}
