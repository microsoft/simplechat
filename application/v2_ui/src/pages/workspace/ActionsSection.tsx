// ActionsSection.tsx
// Personal actions: the tools an agent is allowed to call.
//
// Call agent authoring is native; unrelated connector editors remain in classic.

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Plug, Shield, Trash2 } from 'lucide-react';
import {
    ConfirmAction,
    Pill,
    ResourceRow,
    SectionIntro,
    SectionList,
    SectionSearch,
} from '../../components/workspace/primitives';
import {
    errorMessage,
    useSectionResource,
} from '../../components/workspace/useSectionResource';
import { deleteAction, fetchActions } from '../../lib/workspaceApi';
import { PERSONAL_DELEGATION_SCOPE } from '../../lib/agentDelegation';
import { AgentDelegationManager } from '../../components/agents/AgentDelegationManager';
import type { WorkspaceAction } from '../../lib/types';

/** Render a connector type as something readable: `document_search` -> `Document search`. */
export function actionTypeLabel(type: unknown): string {
    const raw = String(type ?? '').trim();
    if (!raw) {
        return 'Unknown';
    }
    if (raw === 'agent') {
        return 'Call agent';
    }
    const spaced = raw.replace(/[_-]+/g, ' ');
    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function ActionsSection({ agentsEnabled }: { agentsEnabled: boolean }) {
    const { items, loading, error, setItems, setError } = useSectionResource<WorkspaceAction>(
        fetchActions,
        'Failed to load actions.',
    );

    const [query, setQuery] = useState('');
    const [busyId, setBusyId] = useState<string | null>(null);
    const hasOtherActions = items.some((action) => action.type !== 'agent');

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) {
            return items.filter((action) => action.type !== 'agent');
        }
        return items.filter((action) => action.type !== 'agent' &&
            `${action.displayName ?? ''} ${action.name ?? ''} ${action.type ?? ''}`
                .toLowerCase()
                .includes(needle),
        );
    }, [items, query]);

    const onDelete = async (action: WorkspaceAction) => {
        const previous = items;
        const identifier = action.id || String(action.name ?? '');
        setBusyId(identifier);
        setItems(items.filter((item) => (item.id || item.name) !== (action.id || action.name)));
        try {
            await deleteAction(identifier);
        } catch (deleteError) {
            setItems(previous);
            setError(errorMessage(deleteError, 'Could not delete the action.'));
        } finally {
            setBusyId(null);
        }
    };

    return (
        <div className="space-y-4">
            <SectionIntro
                title="Actions"
                description="Tools an agent may call on your behalf, such as an API, a database or an MCP server. An action does nothing until an agent is given permission to use it."
            />

            <p className="text-xs text-text-3">
                Create and edit Call agent actions below. Other connectors are configured in the{' '}
                <a href="/workspace" className="text-accent hover:underline">
                    classic workspace
                </a>
                .{' '}
                {agentsEnabled ? (
                    <>
                        Attach them to an{' '}
                        <Link to="/workspace/agents" className="text-accent hover:underline">
                            agent
                        </Link>{' '}
                        to put them to use.
                    </>
                ) : null}
            </p>

            <AgentDelegationManager scope={PERSONAL_DELEGATION_SCOPE} mode="actions" />

            <h2 className="text-base font-semibold text-text-1">Other actions</h2>
            <SectionSearch value={query} onChange={setQuery} placeholder="Search actions" />

            <SectionList
                items={visible}
                loading={loading}
                error={error}
                emptyIcon={<Plug size={28} />}
                emptyTitle={
                    !hasOtherActions ? 'No other actions yet' : 'No actions match your search'
                }
                emptyDescription={
                    !hasOtherActions
                        ? 'Actions let an agent reach a system outside this chat.'
                        : undefined
                }
                getKey={(action, index) => String(action.id ?? action.name ?? index)}
                renderItem={(action) => {
                    const managed = Boolean(action.is_global);
                    const identifier = action.id || String(action.name ?? '');
                    return (
                        <ResourceRow
                            icon={<Plug size={17} />}
                            title={String(action.displayName || action.name || 'Untitled action')}
                            subtitle={
                                String(action.description || '') ||
                                String(action.endpoint || '')
                            }
                            meta={
                                <>
                                    <Pill>{actionTypeLabel(action.type)}</Pill>
                                    {managed ? (
                                        <Pill tone="accent">
                                            <span className="flex items-center gap-1">
                                                <Shield size={10} />
                                                Provided
                                            </span>
                                        </Pill>
                                    ) : null}
                                </>
                            }
                            actions={
                                managed ? undefined : (
                                    <ConfirmAction
                                        icon={<Trash2 size={15} />}
                                        label={`Delete ${action.displayName ?? action.name ?? 'action'}`}
                                        confirmLabel="Delete"
                                        busy={busyId === identifier}
                                        onConfirm={() => void onDelete(action)}
                                    />
                                )
                            }
                        />
                    );
                }}
            />
        </div>
    );
}
