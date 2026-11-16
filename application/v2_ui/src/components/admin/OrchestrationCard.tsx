// OrchestrationCard.tsx
// Agent orchestration: how a chat is routed across agents.
//
// Two things make this different from every other Admin Settings control, and both are
// why it is a component rather than a declared field.
//
// It does not save through the settings PATCH. `POST /api/orchestration_settings` also
// derives `enable_multi_agent_orchestration` from the chosen type and forces
// `max_rounds_per_agent` back to 1 for single-agent modes, so routing the value through
// the settings document would drop those two rules on the floor.
//
// And the set of orchestration types is a server-side list, not a fixed enum. Today
// `get_agent_orchestration_types()` returns a single entry, `default_agent`, because the
// multi-agent modes are commented out. A select with one option is not a choice, so this
// renders nothing at all until the deployment offers more than one type — and starts
// rendering again by itself if the multi-agent modes come back.

import { useCallback, useEffect, useState } from 'react';
import { clsx } from 'clsx';
import { Loader2, Workflow } from 'lucide-react';
import { api } from '../../lib/apiClient';
import {
    orchestrationIsSelectable,
    readOrchestrationTypes,
    roundsApply,
    type OrchestrationType,
} from '../../lib/adminAgents';
import { GlassButton } from '../ui/primitives';
import { toast } from '../../stores/toastStore';

interface OrchestrationSettings {
    orchestration_type?: string | null;
    max_rounds_per_agent?: number | null;
}

const inputClass = clsx(
    'w-full rounded-lg border border-edge bg-surface-1 px-3 py-2',
    'text-sm text-text-1 focus:border-accent focus:outline-none',
    'disabled:cursor-not-allowed disabled:opacity-60',
);

export function OrchestrationCard({ help }: { help?: string }) {
    const [types, setTypes] = useState<OrchestrationType[]>([]);
    const [selected, setSelected] = useState('');
    const [rounds, setRounds] = useState(1);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [dirty, setDirty] = useState(false);

    useEffect(() => {
        let cancelled = false;
        void (async () => {
            try {
                const [typePayload, current] = await Promise.all([
                    api.get<unknown>('/api/orchestration_types'),
                    api.get<OrchestrationSettings>('/api/orchestration_settings'),
                ]);
                if (cancelled) {
                    return;
                }
                const available = readOrchestrationTypes(typePayload);
                setTypes(available);
                setSelected(
                    current.orchestration_type || available[0]?.value || '',
                );
                setRounds(
                    typeof current.max_rounds_per_agent === 'number'
                        ? current.max_rounds_per_agent
                        : 1,
                );
            } catch {
                // A failure here means the card cannot be trusted to describe the
                // runtime, so it stays hidden rather than showing a stale choice.
                if (!cancelled) {
                    setTypes([]);
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);

    const save = useCallback(async () => {
        setSaving(true);
        try {
            await api.post('/api/orchestration_settings', {
                orchestration_type: selected,
                max_rounds_per_agent: roundsApply(types, selected) ? rounds : 1,
            });
            setDirty(false);
            toast.success('Orchestration settings saved.');
        } catch (error) {
            toast.error(
                error instanceof Error
                    ? error.message
                    : 'Failed to save orchestration settings.',
            );
        } finally {
            setSaving(false);
        }
    }, [selected, rounds, types]);

    if (loading || !orchestrationIsSelectable(types)) {
        return null;
    }

    const showRounds = roundsApply(types, selected);
    const description = types.find((type) => type.value === selected)?.description;

    return (
        <div className="py-3">
            <div className="mb-1.5 flex items-center gap-2">
                <Workflow size={15} className="shrink-0 text-text-3" aria-hidden="true" />
                <span className="text-sm font-medium text-text-1">Agent Orchestration</span>
            </div>

            <label
                htmlFor="admin-orchestration-type"
                className="mb-1 block text-xs text-text-3"
            >
                Orchestration type
            </label>
            <select
                id="admin-orchestration-type"
                className={clsx(inputClass, 'appearance-none pr-8')}
                value={selected}
                disabled={saving}
                onChange={(event) => {
                    setSelected(event.target.value);
                    setDirty(true);
                }}
            >
                {types.map((type) => (
                    <option key={type.value} value={type.value}>
                        {type.label}
                    </option>
                ))}
            </select>

            {description ? (
                <p className="mt-1.5 text-xs leading-relaxed text-text-3">{description}</p>
            ) : null}

            {showRounds ? (
                <div className="mt-3">
                    <label
                        htmlFor="admin-orchestration-rounds"
                        className="mb-1 block text-xs text-text-3"
                    >
                        Max rounds per agent
                    </label>
                    <input
                        id="admin-orchestration-rounds"
                        type="number"
                        min={1}
                        className={inputClass}
                        value={rounds}
                        disabled={saving}
                        onChange={(event) => {
                            setRounds(Number(event.target.value));
                            setDirty(true);
                        }}
                    />
                    <p className="mt-1.5 text-xs leading-relaxed text-text-3">
                        How many turns each agent may take before the conversation is
                        handed back. Raising it costs proportionally more model calls.
                    </p>
                </div>
            ) : null}

            {help ? (
                <p className="mt-1.5 text-xs leading-relaxed text-text-3">{help}</p>
            ) : null}

            {/* Saved separately from the page's save bar, so the button says so. */}
            <GlassButton
                type="button"
                variant="subtle"
                size="sm"
                className="mt-2"
                disabled={!dirty || saving}
                onClick={() => void save()}
            >
                {saving ? <Loader2 size={14} className="animate-spin" /> : null}
                Save orchestration
            </GlassButton>
        </div>
    );
}
