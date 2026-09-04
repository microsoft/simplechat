// GlobalIdentitiesList.tsx
// Read-only inventory of the deployment-wide saved credentials.
//
// "Identity" reliably reads as a user sign-in rather than as a stored credential, so the
// copy here is explicit about what these are and what consumes them. Creating and editing
// one is still done on the server-rendered admin page: the editor there handles Key Vault
// round-tripping and per-auth-type field sets, and rebuilding it would be a large amount
// of work for a surface almost nobody reaches. Listing what exists, and saying plainly
// where to go to change it, is more useful than the blank tab this replaces.

import { useEffect, useState } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, KeyRound, Loader2 } from 'lucide-react';
import { api } from '../../lib/apiClient';
import { authTypeLabel } from '../../pages/workspace/IdentitiesSection';
import type { WorkspaceIdentity } from '../../lib/types';

const GLOBAL_IDENTITIES_ENDPOINT = '/api/admin/workspace-identities/global/identities';

interface IdentitiesResponse {
    identities: WorkspaceIdentity[];
}

export function GlobalIdentitiesList({ help }: { help?: string }) {
    const [identities, setIdentities] = useState<WorkspaceIdentity[] | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        void (async () => {
            try {
                const response = await api.get<IdentitiesResponse>(GLOBAL_IDENTITIES_ENDPOINT);
                if (!cancelled) {
                    setIdentities(response.identities ?? []);
                }
            } catch (fetchError) {
                if (!cancelled) {
                    setError(
                        fetchError instanceof Error
                            ? fetchError.message
                            : 'Failed to load global identities.',
                    );
                }
            }
        })();

        return () => {
            cancelled = true;
        };
    }, []);

    return (
        <div className="py-3">
            {help ? (
                <p className="mb-3 text-xs leading-relaxed text-text-3">{help}</p>
            ) : null}

            <p className="mb-3 text-xs leading-relaxed text-text-3">
                Adding, editing and deleting an identity is done on the{' '}
                <a
                    href="/admin_settings#workspace-identities"
                    className="text-accent hover:underline"
                >
                    classic admin settings page
                </a>
                .
            </p>

            {error ? (
                <p
                    role="alert"
                    className="flex items-start gap-1.5 rounded-lg bg-danger-soft px-3 py-2 text-xs text-danger"
                >
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    {error}
                </p>
            ) : identities === null ? (
                <p className="flex items-center gap-2 py-4 text-sm text-text-3">
                    <Loader2 size={15} className="animate-spin" />
                    Loading identities…
                </p>
            ) : identities.length === 0 ? (
                <p className="py-4 text-sm text-text-3">
                    No global identities are saved. File Sync sources and actions that need
                    credentials can define their own within a workspace instead.
                </p>
            ) : (
                <ul className="space-y-1">
                    {identities.map((identity, index) => (
                        <li
                            key={String(identity.id ?? index)}
                            className={clsx(
                                'flex items-start gap-3 rounded-lg border border-edge px-3 py-2',
                            )}
                        >
                            <KeyRound size={16} className="mt-0.5 shrink-0 text-text-3" />
                            <span className="min-w-0 flex-1">
                                <span className="block truncate text-sm text-text-1">
                                    {String(identity.name ?? 'Untitled identity')}
                                </span>
                                {identity.username || identity.description ? (
                                    <span className="block truncate text-xs text-text-3">
                                        {String(identity.username ?? identity.description ?? '')}
                                    </span>
                                ) : null}
                            </span>
                            <span className="shrink-0 rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-text-3">
                                {authTypeLabel(identity.auth_type)}
                            </span>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}
