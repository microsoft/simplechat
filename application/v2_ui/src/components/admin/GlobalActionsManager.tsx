// GlobalActionsManager.tsx
// The organisation's global actions, listed and managed from Admin Settings.
//
// Actions are edited in the same V2 action editor workspaces use, at /admin/actions/<id>,
// which carries the connector catalogue, MCP preconfigurations and presets, connection
// tests and Key Vault handling. This list adds what the classic admin table offered around
// it: creating one, enabling or disabling one, and deleting one. Each change saves on its
// own rather than through the settings save bar, because these are records, not settings.

import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AlertCircle, Loader2, Plug, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { api } from '../../lib/apiClient';
import { fetchGlobalActions, GLOBAL_ACTION_WORKBENCH } from '../../lib/actionWorkbench';
import { actionTypeLabel } from '../../lib/workspaceActionLogic';
import { GLOBAL_ACTIONS_BASE_PATH, type ActionConfiguration } from '../../lib/workspaceAuthoring';
import { toast } from '../../stores/toastStore';
import { GlassButton } from '../ui/primitives';
import { ConfirmAction, Pill, SectionSearch } from '../workspace/primitives';

/** Search appears once a list is long enough to need it. */
const SEARCH_THRESHOLD = 6;

function actionLabel(action: ActionConfiguration): string {
    return action.displayName || action.name || 'Untitled action';
}

function failure(cause: unknown, fallback: string): string {
    return cause instanceof Error && cause.message ? cause.message : fallback;
}

export function GlobalActionsManager({ help }: { help?: string }) {
    const navigate = useNavigate();
    const [actions, setActions] = useState<ActionConfiguration[] | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState<string | null>(null);
    const [query, setQuery] = useState('');
    const [revision, setRevision] = useState(0);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError(null);
        void fetchGlobalActions(controller.signal).then((items) => {
            if (!controller.signal.aborted) setActions(items);
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) setError(failure(cause, 'Could not load the global actions.'));
        }).finally(() => {
            if (!controller.signal.aborted) setLoading(false);
        });
        return () => controller.abort();
    }, [revision]);

    const reload = () => setRevision((value) => value + 1);

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        return [...(actions ?? [])]
            .filter((action) => !needle || `${actionLabel(action)} ${action.name} ${action.description} ${actionTypeLabel(action.type)}`
                .toLowerCase().includes(needle))
            .sort((left, right) => actionLabel(left).localeCompare(actionLabel(right)));
    }, [actions, query]);

    /** Run one change, report it, and re-read the list so every row shows the stored state. */
    const change = async (key: string, work: () => Promise<string>) => {
        setBusy(key);
        setError(null);
        try {
            toast.success(await work());
            reload();
        } catch (cause) {
            setError(failure(cause, 'The change could not be saved.'));
        } finally {
            setBusy(null);
        }
    };

    const toggleEnabled = (action: ActionConfiguration) => change(`enabled:${action.id}`, async () => {
        const enable = action.is_enabled === false;
        await api.patch(`/api/admin/plugins/${encodeURIComponent(action.name)}/enabled`, { is_enabled: enable });
        return `${actionLabel(action)} ${enable ? 'enabled' : 'disabled'}.`;
    });

    const remove = (action: ActionConfiguration) => change(`delete:${action.id}`, async () => {
        await GLOBAL_ACTION_WORKBENCH.deleteAction(action);
        return `${actionLabel(action)} deleted.`;
    });

    return (
        <div className="min-w-0 space-y-3 py-3" data-testid="global-actions-manager">
            {help ? <p className="text-xs leading-relaxed text-text-3">{help}</p> : null}

            <div className="flex flex-wrap items-center gap-2">
                <GlassButton type="button" variant="primary" size="sm"
                    onClick={() => navigate(`${GLOBAL_ACTIONS_BASE_PATH}/new`)}>
                    <Plus size={14} aria-hidden="true" />New action
                </GlassButton>
                <GlassButton type="button" size="sm" disabled={loading} onClick={reload}>
                    <RefreshCw size={14} aria-hidden="true" />Refresh
                </GlassButton>
            </div>

            {(actions?.length ?? 0) >= SEARCH_THRESHOLD ? (
                <SectionSearch value={query} onChange={setQuery} placeholder="Search global actions" />
            ) : null}

            {error ? (
                <p role="alert" className="flex items-start gap-1.5 rounded-lg bg-danger-soft px-3 py-2 text-xs text-danger">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                    {error}
                </p>
            ) : null}

            {loading && actions === null ? (
                <p role="status" className="flex items-center gap-2 py-4 text-sm text-text-3">
                    <Loader2 size={15} className="animate-spin" aria-hidden="true" />
                    Loading global actions…
                </p>
            ) : null}

            {actions !== null && actions.length === 0 ? (
                <p className="py-4 text-sm text-text-3">
                    No global actions yet. Create one to connect global agents to an API, a database, an
                    MCP server or another agent.
                </p>
            ) : null}
            {actions !== null && actions.length > 0 && visible.length === 0 ? (
                <p role="status" className="py-2 text-sm text-text-3">No global actions match “{query}”.</p>
            ) : null}

            {visible.length ? (
                <ul className="space-y-2" aria-label="Global actions">
                    {visible.map((action) => {
                        const label = actionLabel(action);
                        const enabled = action.is_enabled !== false;
                        const editorPath = `${GLOBAL_ACTIONS_BASE_PATH}/${encodeURIComponent(action.id)}`;
                        return (
                            <li key={action.id} data-testid="global-action-row"
                                className="flex flex-wrap items-start gap-3 rounded-xl border border-edge bg-surface-1 p-3">
                                <div className="flex min-w-0 flex-[1_1_16rem] items-start gap-3">
                                    <Plug size={20} aria-hidden="true" className="mt-0.5 shrink-0 text-accent" />
                                    <div className="min-w-0 flex-1">
                                        <h3 className="break-words text-sm font-semibold text-text-1">
                                            <Link to={editorPath} className="hover:text-accent hover:underline">{label}</Link>
                                        </h3>
                                        {action.description ? (
                                            <p className="mt-0.5 break-words text-xs text-text-3">{action.description}</p>
                                        ) : null}
                                        <div className="mt-2 flex flex-wrap items-center gap-1.5">
                                            <Pill>{actionTypeLabel(action.type)}</Pill>
                                            {!enabled ? <Pill tone="warn">Disabled</Pill> : null}
                                        </div>
                                        <p className="mt-1.5 break-all text-[11px] text-text-3">{action.name}</p>
                                    </div>
                                </div>
                                <div className="flex flex-wrap items-center gap-1.5">
                                    <GlassButton type="button" size="sm" variant="subtle" onClick={() => navigate(editorPath)}>
                                        Edit
                                    </GlassButton>
                                    <GlassButton type="button" size="sm" disabled={busy !== null}
                                        aria-label={`${enabled ? 'Disable' : 'Enable'} ${label}`}
                                        onClick={() => void toggleEnabled(action)}>
                                        {busy === `enabled:${action.id}` ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : null}
                                        {enabled ? 'Disable' : 'Enable'}
                                    </GlassButton>
                                    <ConfirmAction icon={<Trash2 size={15} />} label={`Delete ${label}`} confirmLabel="Delete action"
                                        busy={busy === `delete:${action.id}`} disabled={busy !== null}
                                        onConfirm={() => void remove(action)} />
                                </div>
                            </li>
                        );
                    })}
                </ul>
            ) : null}
        </div>
    );
}
