// FactMemoryBench.tsx
// The signed-in user's saved memories: instructions applied to every reply, and facts recalled
// when they are relevant.
//
// Mirrors the classic profile page's Fact Memory section and its manager dialog, and saves
// through the same routes (/api/profile/fact-memory). The classic page split adding and
// managing across a card and a modal; here they share one bench, a searchable list beside an
// editor, in the style of the workspace benches.
//
// Shown whether or not an administrator turned fact memory on, as the classic page is: saved
// memories stay manageable, they just aren't used while the capability is off.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { Brain, Loader2, Plus, Search, Trash2 } from 'lucide-react';
import { api, ApiError } from '../../lib/apiClient';
import { toast } from '../../stores/toastStore';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { SettingsCard } from './SettingsCard';

export type MemoryType = 'instruction' | 'fact';

export interface FactMemoryItem {
    id: string;
    value: string;
    memory_type: MemoryType;
    created_at?: string;
    updated_at?: string;
}

interface FactMemoryPayload {
    enabled?: boolean;
    facts?: FactMemoryItem[];
}

type TypeFilter = 'all' | MemoryType;

export const MEMORY_TYPE_LABELS: Record<MemoryType, string> = {
    instruction: 'Instruction: always apply to future responses',
    fact: 'Fact: recall only when relevant',
};

const SHORT_TYPE_LABELS: Record<MemoryType, string> = {
    instruction: 'Instruction',
    fact: 'Fact',
};

const FIELD_CLASS =
    'w-full rounded-lg border border-edge bg-surface-solid px-2.5 py-2 text-sm text-text-1';

function normalizeType(value: unknown): MemoryType {
    return value === 'instruction' ? 'instruction' : 'fact';
}

function errorText(error: unknown, fallback: string): string {
    return error instanceof ApiError || error instanceof Error ? error.message : fallback;
}

function formatDate(value?: string): string {
    if (!value) return 'Unknown';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Unknown' : date.toLocaleString();
}

/** Newest change first, the order the classic manager listed them in. */
function byUpdated(left: FactMemoryItem, right: FactMemoryItem): number {
    return (right.updated_at || right.created_at || '').localeCompare(left.updated_at || left.created_at || '');
}

function TypeSelect({
    id,
    value,
    onChange,
    disabled,
}: {
    id: string;
    value: MemoryType;
    onChange: (next: MemoryType) => void;
    disabled?: boolean;
}) {
    return (
        <select
            id={id}
            value={value}
            disabled={disabled}
            onChange={(event) => onChange(normalizeType(event.target.value))}
            className={FIELD_CLASS}
        >
            <option value="instruction">{MEMORY_TYPE_LABELS.instruction}</option>
            <option value="fact">{MEMORY_TYPE_LABELS.fact}</option>
        </select>
    );
}

export function FactMemoryBench() {
    const [enabled, setEnabled] = useState<boolean | null>(null);
    const [items, setItems] = useState<FactMemoryItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);

    const [newValue, setNewValue] = useState('');
    const [newType, setNewType] = useState<MemoryType>('fact');
    const [adding, setAdding] = useState(false);

    const [query, setQuery] = useState('');
    const [typeFilter, setTypeFilter] = useState<TypeFilter>('all');
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [draftValue, setDraftValue] = useState('');
    const [draftType, setDraftType] = useState<MemoryType>('fact');
    const [saving, setSaving] = useState(false);
    const [confirmDelete, setConfirmDelete] = useState(false);
    const [deleting, setDeleting] = useState(false);

    const load = useCallback(async (signal?: AbortSignal) => {
        setLoading(true);
        try {
            const payload = await api.get<FactMemoryPayload>('/api/profile/fact-memory', signal);
            setEnabled(payload.enabled === true);
            setItems((payload.facts ?? []).map((item) => ({ ...item, memory_type: normalizeType(item.memory_type) })));
            setLoadError(null);
        } catch (error) {
            if (signal?.aborted) return;
            setLoadError(errorText(error, 'Your memories could not be loaded.'));
        } finally {
            if (!signal?.aborted) setLoading(false);
        }
    }, []);

    useEffect(() => {
        const controller = new AbortController();
        void load(controller.signal);
        return () => controller.abort();
    }, [load]);

    const sorted = useMemo(() => [...items].sort(byUpdated), [items]);
    const instructionCount = items.filter((item) => item.memory_type === 'instruction').length;
    const factCount = items.length - instructionCount;
    const lastUpdated = sorted[0]?.updated_at || sorted[0]?.created_at;

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        return sorted.filter((item) => (
            (typeFilter === 'all' || item.memory_type === typeFilter)
            && (!needle || item.value.toLowerCase().includes(needle))
        ));
    }, [sorted, query, typeFilter]);

    const selected = items.find((item) => item.id === selectedId) ?? null;

    useEffect(() => {
        if (selected) {
            setDraftValue(selected.value);
            setDraftType(selected.memory_type);
        }
        // Only reset the draft when a different memory is opened, not on every list change.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedId]);

    const replaceItem = (next: FactMemoryItem) => {
        const normalized = { ...next, memory_type: normalizeType(next.memory_type) };
        setItems((current) => {
            const index = current.findIndex((item) => item.id === normalized.id);
            if (index === -1) return [normalized, ...current];
            const copy = [...current];
            copy[index] = normalized;
            return copy;
        });
    };

    const add = async () => {
        const value = newValue.trim();
        if (!value) return;
        setAdding(true);
        try {
            const response = await api.post<{ fact?: FactMemoryItem }>('/api/profile/fact-memory', {
                value,
                memory_type: newType,
            });
            if (response.fact) {
                replaceItem(response.fact);
                setSelectedId(response.fact.id);
                setDraftValue(response.fact.value);
                setDraftType(normalizeType(response.fact.memory_type));
            } else {
                await load();
            }
            setNewValue('');
            toast.success('Memory saved.');
        } catch (error) {
            toast.error(errorText(error, 'The memory could not be saved.'));
        } finally {
            setAdding(false);
        }
    };

    const save = async () => {
        if (!selected) return;
        const value = draftValue.trim();
        if (!value) return;
        setSaving(true);
        try {
            const response = await api.put<{ fact?: FactMemoryItem }>(
                `/api/profile/fact-memory/${encodeURIComponent(selected.id)}`,
                { value, memory_type: draftType },
            );
            if (response.fact) replaceItem(response.fact);
            toast.success('Memory updated.');
        } catch (error) {
            toast.error(errorText(error, 'The memory could not be updated.'));
        } finally {
            setSaving(false);
        }
    };

    const remove = async () => {
        if (!selected) return;
        setDeleting(true);
        try {
            await api.delete(`/api/profile/fact-memory/${encodeURIComponent(selected.id)}`);
            setItems((current) => current.filter((item) => item.id !== selected.id));
            setSelectedId(null);
            setConfirmDelete(false);
            toast.success('Memory deleted.');
        } catch (error) {
            toast.error(errorText(error, 'The memory could not be deleted.'));
        } finally {
            setDeleting(false);
        }
    };

    const dirty = selected !== null
        && (draftValue.trim() !== selected.value || draftType !== selected.memory_type);

    const badge = enabled === null ? null : (
        <span
            className={clsx(
                'rounded-full border px-2 py-0.5 text-xs',
                enabled ? 'border-ok/30 bg-ok-soft text-ok' : 'border-warn/30 bg-warn-soft text-text-2',
            )}
        >
            {enabled ? 'Enabled by admin' : 'Disabled by admin'}
        </span>
    );

    return (
        <SettingsCard
            title="Fact memory"
            Icon={Brain}
            description="Things the assistant should know about you. Instructions shape every reply; facts are recalled only when they are relevant to what you ask."
            actions={badge}
        >
            {enabled === false && (
                <p className="mb-4 rounded-lg border border-warn/30 bg-warn-soft px-3 py-2 text-xs text-text-2">
                    Fact memory is turned off for your organization. You can still review and tidy your saved
                    memories, but they are not used in replies until an administrator turns it back on.
                </p>
            )}

            {loadError ? (
                <p className="rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
                    {loadError}
                </p>
            ) : (
                <>
                    <p className="text-xs text-text-3" aria-live="polite">
                        {loading
                            ? 'Loading your memories…'
                            : `${items.length} saved · ${instructionCount} ${instructionCount === 1 ? 'instruction' : 'instructions'}, ${factCount} ${factCount === 1 ? 'fact' : 'facts'}${lastUpdated ? ` · last updated ${formatDate(lastUpdated)}` : ''}`}
                    </p>

                    <form
                        className="mt-3 grid gap-3 rounded-xl border border-edge p-3 lg:grid-cols-[minmax(0,1fr)_16rem]"
                        onSubmit={(event) => {
                            event.preventDefault();
                            void add();
                        }}
                    >
                        <label className="block">
                            <span className="block text-sm font-medium text-text-1">Add a memory</span>
                            <textarea
                                value={newValue}
                                onChange={(event) => setNewValue(event.target.value)}
                                rows={2}
                                placeholder="I prefer concise responses with explicit next steps when there are options."
                                className={clsx(FIELD_CLASS, 'mt-1.5 resize-y')}
                            />
                        </label>
                        <div className="flex flex-col gap-2">
                            <label htmlFor="fact-memory-new-type" className="text-sm font-medium text-text-1">
                                Type
                            </label>
                            <TypeSelect id="fact-memory-new-type" value={newType} onChange={setNewType} />
                            <button
                                type="submit"
                                disabled={!newValue.trim() || adding}
                                className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-on-accent hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                {adding ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                                Add memory
                            </button>
                        </div>
                    </form>

                    <div className="mt-4 grid min-h-[18rem] gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
                        <div className="flex min-w-0 flex-col rounded-xl border border-edge">
                            <div className="flex flex-wrap gap-2 border-b border-edge p-2">
                                <label className="relative min-w-0 flex-1 basis-40">
                                    <span className="sr-only">Search memories</span>
                                    <Search
                                        size={14}
                                        aria-hidden="true"
                                        className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-3"
                                    />
                                    <input
                                        type="search"
                                        value={query}
                                        onChange={(event) => setQuery(event.target.value)}
                                        placeholder="Search memories"
                                        className={clsx(FIELD_CLASS, 'pl-8')}
                                    />
                                </label>
                                <label className="shrink-0">
                                    <span className="sr-only">Filter by type</span>
                                    <select
                                        value={typeFilter}
                                        onChange={(event) => setTypeFilter(event.target.value as TypeFilter)}
                                        className={FIELD_CLASS}
                                    >
                                        <option value="all">All types</option>
                                        <option value="instruction">Instructions</option>
                                        <option value="fact">Facts</option>
                                    </select>
                                </label>
                            </div>
                            <ul className="max-h-80 min-h-0 flex-1 overflow-y-auto p-1" aria-label="Saved memories">
                                {!loading && visible.length === 0 && (
                                    <li className="px-3 py-6 text-center text-xs text-text-3">
                                        {items.length === 0 ? 'No memories saved yet.' : 'No memories match.'}
                                    </li>
                                )}
                                {visible.map((item) => (
                                    <li key={item.id}>
                                        <button
                                            type="button"
                                            onClick={() => setSelectedId(item.id)}
                                            aria-current={item.id === selectedId ? 'true' : undefined}
                                            className={clsx(
                                                'w-full rounded-lg px-3 py-2 text-left',
                                                item.id === selectedId ? 'bg-surface-2' : 'hover:bg-surface-2/60',
                                            )}
                                        >
                                            <span className="line-clamp-2 text-sm text-text-1">{item.value}</span>
                                            <span className="mt-0.5 block text-[11px] text-text-3">
                                                {SHORT_TYPE_LABELS[item.memory_type]} · {formatDate(item.updated_at || item.created_at)}
                                            </span>
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        </div>

                        <div className="min-w-0 rounded-xl border border-edge p-3">
                            {selected ? (
                                <form
                                    className="flex h-full flex-col gap-3"
                                    onSubmit={(event) => {
                                        event.preventDefault();
                                        void save();
                                    }}
                                >
                                    <label className="block">
                                        <span className="block text-sm font-medium text-text-1">Memory</span>
                                        <textarea
                                            value={draftValue}
                                            onChange={(event) => setDraftValue(event.target.value)}
                                            rows={5}
                                            className={clsx(FIELD_CLASS, 'mt-1.5 resize-y')}
                                        />
                                    </label>
                                    <div>
                                        <label htmlFor="fact-memory-edit-type" className="block text-sm font-medium text-text-1">
                                            Type
                                        </label>
                                        <div className="mt-1.5">
                                            <TypeSelect id="fact-memory-edit-type" value={draftType} onChange={setDraftType} />
                                        </div>
                                    </div>
                                    <p className="text-xs text-text-3">
                                        Created {formatDate(selected.created_at)} · updated {formatDate(selected.updated_at)}
                                    </p>
                                    <div className="mt-auto flex flex-wrap justify-end gap-2">
                                        <button
                                            type="button"
                                            onClick={() => setConfirmDelete(true)}
                                            className="inline-flex items-center gap-1.5 rounded-lg border border-danger/40 px-3 py-1.5 text-sm text-danger hover:bg-danger-soft"
                                        >
                                            <Trash2 size={14} />
                                            Delete
                                        </button>
                                        <button
                                            type="submit"
                                            disabled={!dirty || !draftValue.trim() || saving}
                                            className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-on-accent hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                                        >
                                            {saving ? 'Saving…' : 'Save changes'}
                                        </button>
                                    </div>
                                </form>
                            ) : (
                                <div className="flex h-full items-center justify-center px-4 text-center text-xs text-text-3">
                                    Select a memory to edit its wording or type, or to delete it.
                                </div>
                            )}
                        </div>
                    </div>
                </>
            )}

            {confirmDelete && selected && (
                <ConfirmDialog
                    title="Delete this memory?"
                    confirmLabel="Delete"
                    confirmIcon={<Trash2 size={14} />}
                    busy={deleting}
                    onConfirm={() => void remove()}
                    onClose={() => setConfirmDelete(false)}
                >
                    <p className="text-xs text-text-2">
                        The assistant stops using it in future replies. This cannot be undone.
                    </p>
                    <p className="mt-2 line-clamp-4 rounded-lg border border-edge px-3 py-2 text-xs text-text-1">
                        {selected.value}
                    </p>
                </ConfirmDialog>
            )}
        </SettingsCard>
    );
}
