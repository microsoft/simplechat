// AgentsSection.tsx
// Personal agents: list, create, edit and delete.
//
// Identity, instructions and Call agent bindings are native. Model, knowledge and other
// action types retain their existing classic editors.

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Pencil, Plus, Shield, Sparkles, Trash2 } from 'lucide-react';
import { GlassButton, GlassPanel } from '../../components/ui/primitives';
import {
    ConfirmAction,
    Pill,
    ResourceRow,
    RowAction,
    SectionIntro,
    SectionList,
    SectionSearch,
} from '../../components/workspace/primitives';
import {
    errorMessage,
    useSectionResource,
} from '../../components/workspace/useSectionResource';
import {
    createAgent,
    deleteAgent,
    fetchAgents,
    generateAgentId,
    updateAgent,
} from '../../lib/workspaceApi';
import type { WorkspaceAgent } from '../../lib/types';
import { PERSONAL_DELEGATION_SCOPE } from '../../lib/agentDelegation';
import { AgentDelegationManager } from '../../components/agents/AgentDelegationManager';

interface DraftAgent {
    id: string | null;
    displayName: string;
    description: string;
    instructions: string;
}

const EMPTY_DRAFT: DraftAgent = {
    id: null,
    displayName: '',
    description: '',
    instructions: '',
};

/**
 * Derive the stored `name` from what the user typed.
 *
 * The agent schema constrains `name` to letters, digits, underscore and dash, while the
 * display name is free text. Rather than ask for both, the machine-readable one is derived
 * and only the display name is edited.
 */
export function agentNameFromDisplayName(displayName: string): string {
    const slug = displayName
        .trim()
        .replace(/[^A-Za-z0-9_-]+/g, '-')
        .replace(/^-+|-+$/g, '');
    return slug || 'agent';
}

function AgentEditor({
    draft,
    saving,
    onChange,
    onSave,
    onCancel,
}: {
    draft: DraftAgent;
    saving: boolean;
    onChange: (next: DraftAgent) => void;
    onSave: () => void;
    onCancel: () => void;
}) {
    const canSave = draft.displayName.trim().length > 0;

    return (
        <GlassPanel elevation="flat" className="space-y-3 p-4">
            <div>
                <label
                    htmlFor="agent-display-name"
                    className="mb-1 block text-xs font-medium text-text-2"
                >
                    Name
                </label>
                <input
                    id="agent-display-name"
                    type="text"
                    value={draft.displayName}
                    onChange={(event) =>
                        onChange({ ...draft, displayName: event.target.value })
                    }
                    placeholder="Contract reviewer"
                    className="w-full rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                />
                {draft.id === null && draft.displayName.trim() ? (
                    <p className="mt-1 text-[11px] text-text-3">
                        Stored as{' '}
                        <code className="text-text-2">
                            {agentNameFromDisplayName(draft.displayName)}
                        </code>
                    </p>
                ) : null}
            </div>

            <div>
                <label
                    htmlFor="agent-description"
                    className="mb-1 block text-xs font-medium text-text-2"
                >
                    Description
                </label>
                <input
                    id="agent-description"
                    type="text"
                    value={draft.description}
                    onChange={(event) =>
                        onChange({ ...draft, description: event.target.value })
                    }
                    placeholder="Reviews contracts against our standard terms."
                    className="w-full rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                />
            </div>

            <div>
                <label
                    htmlFor="agent-instructions"
                    className="mb-1 block text-xs font-medium text-text-2"
                >
                    Instructions
                </label>
                <textarea
                    id="agent-instructions"
                    rows={6}
                    value={draft.instructions}
                    onChange={(event) =>
                        onChange({ ...draft, instructions: event.target.value })
                    }
                    placeholder="You are a careful contract reviewer. Quote the clause you are referring to before commenting on it."
                    className="w-full resize-y rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                />
            </div>

            <div className="flex justify-end gap-2">
                <GlassButton size="sm" onClick={onCancel} disabled={saving}>
                    Cancel
                </GlassButton>
                <GlassButton
                    variant="primary"
                    size="sm"
                    onClick={onSave}
                    disabled={!canSave || saving}
                >
                    {saving ? 'Saving' : draft.id ? 'Save changes' : 'Create agent'}
                </GlassButton>
            </div>
        </GlassPanel>
    );
}

export function AgentsSection({ actionsEnabled }: { actionsEnabled: boolean }) {
    const { items, loading, error, refresh, setItems, setError } =
        useSectionResource<WorkspaceAgent>(fetchAgents, 'Failed to load agents.');

    const [query, setQuery] = useState('');
    const [draft, setDraft] = useState<DraftAgent | null>(null);
    const [saving, setSaving] = useState(false);
    const [busyId, setBusyId] = useState<string | null>(null);
    const [delegationRevision, setDelegationRevision] = useState(0);
    const [delegationDirty, setDelegationDirty] = useState(false);

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) {
            return items;
        }
        return items.filter((agent) =>
            `${agent.display_name ?? ''} ${agent.name ?? ''}`.toLowerCase().includes(needle),
        );
    }, [items, query]);

    const onSave = async () => {
        if (!draft) {
            return;
        }
        setSaving(true);
        setError(null);
        try {
            if (draft.id) {
                await updateAgent(draft.id, {
                    display_name: draft.displayName.trim(),
                    description: draft.description,
                    instructions: draft.instructions,
                });
            } else {
                const id = await generateAgentId();
                // Every one of these is required by the agent schema, which is checked
                // before the record is stored, so a partial object is rejected outright.
                await createAgent({
                    id,
                    name: agentNameFromDisplayName(draft.displayName),
                    display_name: draft.displayName.trim(),
                    description: draft.description,
                    instructions: draft.instructions,
                    is_global: false,
                    is_group: false,
                    actions_to_load: [],
                    other_settings: {},
                    max_completion_tokens: -1,
                    agent_type: 'local',
                });
            }
            setDraft(null);
            await refresh();
            setDelegationRevision((value) => value + 1);
        } catch (saveError) {
            setError(errorMessage(saveError, 'Could not save the agent.'));
        } finally {
            setSaving(false);
        }
    };

    const onDelete = async (agent: WorkspaceAgent) => {
        const previous = items;
        setBusyId(agent.id);
        setItems(items.filter((item) => item.id !== agent.id));
        try {
            await deleteAgent(agent.id);
            setDelegationRevision((value) => value + 1);
        } catch (deleteError) {
            setItems(previous);
            setError(errorMessage(deleteError, 'Could not delete the agent.'));
        } finally {
            setBusyId(null);
        }
    };

    return (
        <div className="space-y-4">
            <SectionIntro
                title="Agents"
                description="Assistants you configure once and reuse, with instructions and approved actions. Agents you build here appear in the chat agent picker."
                actions={
                    <GlassButton
                        variant="primary"
                        size="sm"
                        onClick={() => setDraft({ ...EMPTY_DRAFT })}
                        disabled={Boolean(draft) || delegationDirty}
                    >
                        <Plus size={14} />
                        New agent
                    </GlassButton>
                }
            />

            <p className="text-xs text-text-3">
                Create an agent here, then attach Call agent actions below. Create those{' '}
                {actionsEnabled ? (
                    <Link to="/workspace/actions" className="text-accent hover:underline">
                        actions
                    </Link>
                ) : (
                    'actions'
                )}{' '}
                in your Actions section. Model, knowledge and other connector bindings remain in the{' '}
                <a href="/workspace" className="text-accent hover:underline">
                    classic workspace
                </a>
                .
            </p>

            {draft ? (
                <AgentEditor
                    draft={draft}
                    saving={saving}
                    onChange={setDraft}
                    onSave={() => void onSave()}
                    onCancel={() => setDraft(null)}
                />
            ) : null}

            <SectionSearch value={query} onChange={setQuery} placeholder="Search agents" />

            <SectionList
                items={visible}
                loading={loading}
                error={error}
                emptyIcon={<Sparkles size={28} />}
                emptyTitle={items.length === 0 ? 'No agents yet' : 'No agents match your search'}
                emptyDescription={
                    items.length === 0
                        ? 'Create an agent to reuse a set of instructions across conversations.'
                        : undefined
                }
                getKey={(agent, index) => String(agent.id ?? agent.name ?? index)}
                renderItem={(agent) => {
                    // Administrator-supplied agents are listed because they are selectable in
                    // chat, but they are not this user's to change.
                    const managed = Boolean(agent.is_global);
                    return (
                        <ResourceRow
                            icon={<Sparkles size={17} />}
                            title={String(agent.display_name || agent.name || 'Untitled agent')}
                            subtitle={String(agent.description || agent.name || '')}
                            meta={
                                managed ? (
                                    <Pill tone="accent">
                                        <span className="flex items-center gap-1">
                                            <Shield size={10} />
                                            Provided
                                        </span>
                                    </Pill>
                                ) : undefined
                            }
                            actions={
                                managed ? undefined : (
                                    <>
                                        <RowAction
                                            icon={<Pencil size={15} />}
                                            label={`Edit ${agent.display_name ?? agent.name ?? 'agent'}`}
                                            disabled={delegationDirty}
                                            onClick={() =>
                                                setDraft({
                                                    id: agent.id,
                                                    displayName: String(
                                                        agent.display_name || agent.name || '',
                                                    ),
                                                    description: String(agent.description ?? ''),
                                                    instructions: String(
                                                        agent.instructions ?? '',
                                                    ),
                                                })
                                            }
                                        />
                                        <ConfirmAction
                                            icon={<Trash2 size={15} />}
                                            label={`Delete ${agent.display_name ?? agent.name ?? 'agent'}`}
                                            confirmLabel="Delete"
                                            busy={busyId === agent.id}
                                            disabled={delegationDirty}
                                            onConfirm={() => void onDelete(agent)}
                                        />
                                    </>
                                )
                            }
                        />
                    );
                }}
            />
            {actionsEnabled && !draft ? (
                <AgentDelegationManager scope={PERSONAL_DELEGATION_SCOPE} mode="bindings"
                    revision={delegationRevision} onDirtyChange={setDelegationDirty} />
            ) : null}
        </div>
    );
}
