// PromotedAgentsEditor.tsx
// Agents promoted into the Popular tab before they have any usage behind them.
//
// The Popular tab ranks agents by how often people actually run them, which is a problem
// for a brand new agent: nothing can become popular until it is already popular. A
// promotion places a chosen agent there regardless, so it can be found at all.
//
// Candidates come from the agent catalog rather than being typed in, because the stored
// entry has to carry the catalog key the Agents page ranks on, plus the display name and
// scope used to describe it. `functions_settings.normalize_agents_page_promoted_popular_agents`
// re-normalizes the list on save, so this only has to produce entries of the same shape.

import { useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, Plus, Star, Trash2 } from 'lucide-react';
import { api } from '../../lib/apiClient';
import {
    PROMOTED_WINDOW_OPTIONS,
    promotableAgents,
    readPromotedAgents,
    type CatalogAgent,
    type PromotedAgent,
} from '../../lib/adminAgents';
import type { AdminField } from '../../lib/adminFields';
import { GlassButton } from '../ui/primitives';

const controlClass = clsx(
    'rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5',
    'text-sm text-text-1 focus:border-accent focus:outline-none',
    'disabled:cursor-not-allowed disabled:opacity-60',
);

export function PromotedAgentsEditor({
    field,
    value,
    error,
    disabled,
    onChange,
}: {
    field: AdminField;
    value: unknown;
    error?: string;
    disabled?: boolean;
    onChange: (next: PromotedAgent[]) => void;
}) {
    const promoted = readPromotedAgents(value);

    const [candidates, setCandidates] = useState<CatalogAgent[]>([]);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [choice, setChoice] = useState('');

    useEffect(() => {
        let cancelled = false;
        void (async () => {
            try {
                const payload = await api.get<{ agents?: unknown }>(
                    '/api/agents/catalog?include_usage=true',
                );
                if (!cancelled) {
                    setCandidates(Array.isArray(payload.agents) ? payload.agents : []);
                    setLoadError(null);
                }
            } catch (fetchError) {
                if (!cancelled) {
                    setCandidates([]);
                    setLoadError(
                        fetchError instanceof Error
                            ? fetchError.message
                            : 'Failed to load available agents.',
                    );
                }
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);

    // An agent already promoted is not offered again: the stored list is keyed by
    // catalog key and the server drops duplicates, so a second entry would vanish
    // on save with no explanation.
    const available = useMemo(
        () => promotableAgents(candidates, promoted),
        [candidates, promoted],
    );

    const add = () => {
        const agent = available.find((item) => item.catalog_key === choice);
        if (agent) {
            onChange([...promoted, agent]);
            setChoice('');
        }
    };

    return (
        <div className="py-3">
            <div className="admin-field-heading mb-1.5 flex items-baseline justify-between gap-3">
                <span className="text-sm font-medium text-text-1">{field.label}</span>
                <span className="text-xs text-text-3">
                    {promoted.length} promoted
                </span>
            </div>

            <div className="admin-promoted-agents-picker flex items-center gap-2">
                <select
                    aria-label="Agent to promote"
                    className={clsx(controlClass, 'min-w-0 flex-1 appearance-none pr-8')}
                    value={choice}
                    disabled={disabled || available.length === 0}
                    onChange={(event) => setChoice(event.target.value)}
                >
                    <option value="">
                        {available.length === 0
                            ? 'No agents available to promote'
                            : 'Choose an agent…'}
                    </option>
                    {available.map((agent) => (
                        <option key={agent.catalog_key} value={agent.catalog_key}>
                            {agent.display_name || agent.catalog_key}
                            {agent.scope_label ? ` · ${agent.scope_label}` : ''}
                        </option>
                    ))}
                </select>
                <GlassButton
                    type="button"
                    variant="subtle"
                    size="sm"
                    disabled={disabled || !choice}
                    onClick={add}
                >
                    <Plus size={14} />
                    Promote
                </GlassButton>
            </div>

            {promoted.length === 0 ? (
                <div className="mt-2 flex items-center gap-2 rounded-lg border border-dashed border-edge px-3 py-4 text-sm text-text-3">
                    <Star size={15} aria-hidden="true" />
                    No agents are promoted yet.
                </div>
            ) : (
                <ul className="mt-2 space-y-2">
                    {promoted.map((agent, index) => (
                        <li
                            key={agent.catalog_key}
                            className="admin-promoted-agent-row flex items-center gap-2 rounded-lg border border-edge bg-surface-1 p-2"
                        >
                            <div className="min-w-0 flex-1">
                                <p className="truncate text-sm text-text-1">
                                    {agent.display_name || agent.catalog_key}
                                </p>
                                {agent.scope_label ? (
                                    <p className="truncate text-xs text-text-3">
                                        {agent.scope_label}
                                    </p>
                                ) : null}
                            </div>

                            <select
                                aria-label={`Popular window for ${
                                    agent.display_name || agent.catalog_key
                                }`}
                                className={clsx(controlClass, 'shrink-0 appearance-none pr-7 text-xs')}
                                value={agent.window}
                                disabled={disabled}
                                onChange={(event) =>
                                    onChange(
                                        promoted.map((item, i) =>
                                            i === index
                                                ? { ...item, window: event.target.value }
                                                : item,
                                        ),
                                    )
                                }
                            >
                                {PROMOTED_WINDOW_OPTIONS.map((option) => (
                                    <option key={option.value} value={option.value}>
                                        {option.label}
                                    </option>
                                ))}
                            </select>

                            <button
                                type="button"
                                title="Remove"
                                aria-label={`Stop promoting ${
                                    agent.display_name || agent.catalog_key
                                }`}
                                disabled={disabled}
                                onClick={() =>
                                    onChange(promoted.filter((_, i) => i !== index))
                                }
                                className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-danger-soft hover:text-danger disabled:cursor-not-allowed disabled:opacity-40"
                            >
                                <Trash2 size={14} />
                            </button>
                        </li>
                    ))}
                </ul>
            )}

            {field.help ? (
                <p className="mt-1.5 text-xs leading-relaxed text-text-3">{field.help}</p>
            ) : null}

            {loadError ? (
                <p className="mt-1.5 flex items-start gap-1.5 text-xs text-warn">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    {loadError}
                </p>
            ) : null}

            {error ? (
                <p role="alert" className="mt-1.5 flex items-start gap-1.5 text-xs text-danger">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    {error}
                </p>
            ) : null}
        </div>
    );
}
