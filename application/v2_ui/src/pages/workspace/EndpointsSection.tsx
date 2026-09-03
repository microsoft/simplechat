// EndpointsSection.tsx
// Personal model endpoints: list, enable or disable, and delete.
//
// The connection editor -- provider, API versions, authentication and the model list --
// stays in the classic interface. What is here is the part that is safe to change without
// a form: whether an endpoint is in play, and whether it should exist at all.

import { useMemo, useState } from 'react';
import { Power, Server, Trash2 } from 'lucide-react';
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
    deleteModelEndpoint,
    fetchModelEndpoints,
    updateModelEndpoint,
} from '../../lib/workspaceApi';
import type { WorkspaceModelEndpoint } from '../../lib/types';

const PROVIDER_LABELS: Record<string, string> = {
    aoai: 'Azure OpenAI',
    aifoundry: 'AI Foundry',
    new_foundry: 'Foundry',
};

export function providerLabel(provider: unknown): string {
    const raw = String(provider ?? '').trim();
    return PROVIDER_LABELS[raw] ?? (raw || 'Endpoint');
}

export function EndpointsSection() {
    const { items, loading, error, setItems, setError } =
        useSectionResource<WorkspaceModelEndpoint>(
            fetchModelEndpoints,
            'Failed to load model endpoints.',
        );

    const [query, setQuery] = useState('');
    const [busyId, setBusyId] = useState<string | null>(null);

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) {
            return items;
        }
        return items.filter((endpoint) =>
            `${endpoint.name ?? ''} ${endpoint.provider ?? ''}`.toLowerCase().includes(needle),
        );
    }, [items, query]);

    const onToggle = async (endpoint: WorkspaceModelEndpoint) => {
        const previous = items;
        const next = !endpoint.enabled;
        setBusyId(endpoint.id);
        setItems(
            items.map((item) =>
                item.id === endpoint.id ? { ...item, enabled: next } : item,
            ),
        );
        try {
            // A partial update, so the stripped secrets in the copy this page holds are
            // never sent back and cannot overwrite what is stored.
            await updateModelEndpoint(endpoint.id, { enabled: next });
        } catch (toggleError) {
            setItems(previous);
            setError(errorMessage(toggleError, 'Could not update the endpoint.'));
        } finally {
            setBusyId(null);
        }
    };

    const onDelete = async (endpoint: WorkspaceModelEndpoint) => {
        const previous = items;
        setBusyId(endpoint.id);
        setItems(items.filter((item) => item.id !== endpoint.id));
        try {
            await deleteModelEndpoint(endpoint.id);
        } catch (deleteError) {
            setItems(previous);
            setError(errorMessage(deleteError, 'Could not delete the endpoint.'));
        } finally {
            setBusyId(null);
        }
    };

    return (
        <div className="space-y-4">
            <SectionIntro
                title="Endpoints"
                description="Model endpoints of your own, used alongside the ones your administrator provides. Agents and workflows can be pointed at these."
            />

            <p className="text-xs text-text-3">
                Adding an endpoint and editing its connection details are still done in the{' '}
                <a href="/workspace" className="text-accent hover:underline">
                    classic workspace
                </a>
                .
            </p>

            <SectionSearch value={query} onChange={setQuery} placeholder="Search endpoints" />

            <SectionList
                items={visible}
                loading={loading}
                error={error}
                emptyIcon={<Server size={28} />}
                emptyTitle={
                    items.length === 0 ? 'No endpoints yet' : 'No endpoints match your search'
                }
                emptyDescription={
                    items.length === 0
                        ? 'Add an endpoint to use a model your administrator has not published.'
                        : undefined
                }
                getKey={(endpoint, index) => String(endpoint.id ?? index)}
                renderItem={(endpoint) => {
                    const modelCount = Array.isArray(endpoint.models)
                        ? endpoint.models.length
                        : 0;
                    return (
                        <ResourceRow
                            icon={<Server size={17} />}
                            title={String(endpoint.name ?? 'Untitled endpoint')}
                            subtitle={`${providerLabel(endpoint.provider)}${
                                modelCount
                                    ? ` · ${modelCount} model${modelCount === 1 ? '' : 's'}`
                                    : ''
                            }`}
                            meta={
                                <Pill tone={endpoint.enabled ? 'ok' : 'neutral'}>
                                    {endpoint.enabled ? 'Enabled' : 'Disabled'}
                                </Pill>
                            }
                            actions={
                                <>
                                    <RowAction
                                        icon={<Power size={15} />}
                                        label={
                                            endpoint.enabled
                                                ? `Disable ${endpoint.name ?? 'endpoint'}`
                                                : `Enable ${endpoint.name ?? 'endpoint'}`
                                        }
                                        busy={busyId === endpoint.id}
                                        onClick={() => void onToggle(endpoint)}
                                    />
                                    <ConfirmAction
                                        icon={<Trash2 size={15} />}
                                        label={`Delete ${endpoint.name ?? 'endpoint'}`}
                                        confirmLabel="Delete"
                                        busy={busyId === endpoint.id}
                                        onConfirm={() => void onDelete(endpoint)}
                                    />
                                </>
                            }
                        />
                    );
                }}
            />
        </div>
    );
}
