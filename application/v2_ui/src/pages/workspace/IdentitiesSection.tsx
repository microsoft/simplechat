// IdentitiesSection.tsx
// Saved credentials, used by file sources and actions.
//
// Named "Identities" throughout the application, which reliably reads as user sign-in
// rather than as stored credentials, so the wording here is explicit about what these are
// and what uses them.

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { KeyRound, Trash2 } from 'lucide-react';
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
import { deleteIdentity, fetchIdentities } from '../../lib/workspaceApi';
import type { WorkspaceIdentity } from '../../lib/types';

const AUTH_TYPE_LABELS: Record<string, string> = {
    anonymous: 'Anonymous',
    api_key: 'API key',
    bearer_token: 'Bearer token',
    client_secret: 'Client secret',
    connection_string: 'Connection string',
    managed_identity: 'Managed identity',
    username_password: 'Username and password',
};

export function authTypeLabel(authType: unknown): string {
    const raw = String(authType ?? '').trim();
    return AUTH_TYPE_LABELS[raw] ?? (raw ? raw.replace(/[_-]+/g, ' ') : 'Unknown');
}

export function IdentitiesSection({
    syncEnabled,
    actionsEnabled,
}: {
    syncEnabled: boolean;
    actionsEnabled: boolean;
}) {
    const { items, loading, error, setItems, setError } = useSectionResource<WorkspaceIdentity>(
        fetchIdentities,
        'Failed to load identities.',
    );

    const [query, setQuery] = useState('');
    const [busyId, setBusyId] = useState<string | null>(null);

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) {
            return items;
        }
        return items.filter((identity) =>
            `${identity.name ?? ''} ${identity.username ?? ''}`.toLowerCase().includes(needle),
        );
    }, [items, query]);

    const onDelete = async (identity: WorkspaceIdentity) => {
        const previous = items;
        setBusyId(identity.id);
        setItems(items.filter((item) => item.id !== identity.id));
        try {
            await deleteIdentity(identity.id);
        } catch (deleteError) {
            setItems(previous);
            setError(errorMessage(deleteError, 'Could not delete the identity.'));
        } finally {
            setBusyId(null);
        }
    };

    return (
        <div className="space-y-4">
            <SectionIntro
                title="Identities"
                description="Sign-in details you save once and reuse. These are credentials for the systems you connect to, not your own account. Secrets are held server-side and never sent back to the browser."
            />

            <p className="text-xs text-text-3">
                Used by{' '}
                {syncEnabled ? (
                    <Link to="/workspace/sync" className="text-accent hover:underline">
                        file sources
                    </Link>
                ) : (
                    'file sources'
                )}{' '}
                and{' '}
                {actionsEnabled ? (
                    <Link to="/workspace/actions" className="text-accent hover:underline">
                        actions
                    </Link>
                ) : (
                    'actions'
                )}
                . Adding one is still done in the{' '}
                <a href="/workspace" className="text-accent hover:underline">
                    classic workspace
                </a>
                .
            </p>

            <SectionSearch value={query} onChange={setQuery} placeholder="Search identities" />

            <SectionList
                items={visible}
                loading={loading}
                error={error}
                emptyIcon={<KeyRound size={28} />}
                emptyTitle={
                    items.length === 0 ? 'No identities yet' : 'No identities match your search'
                }
                emptyDescription={
                    items.length === 0
                        ? 'Save a credential here to reuse it across file sources and actions.'
                        : undefined
                }
                getKey={(identity, index) => String(identity.id ?? index)}
                renderItem={(identity) => (
                    <ResourceRow
                        icon={<KeyRound size={17} />}
                        title={String(identity.name ?? 'Untitled identity')}
                        subtitle={
                            String(identity.username ?? '') ||
                            String(identity.description ?? '')
                        }
                        meta={<Pill>{authTypeLabel(identity.auth_type)}</Pill>}
                        actions={
                            <ConfirmAction
                                icon={<Trash2 size={15} />}
                                label={`Delete ${identity.name ?? 'identity'}`}
                                confirmLabel="Delete"
                                busy={busyId === identity.id}
                                onConfirm={() => void onDelete(identity)}
                            />
                        }
                    />
                )}
            />
        </div>
    );
}
