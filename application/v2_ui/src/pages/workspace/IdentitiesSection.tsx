// IdentitiesSection.tsx
// Saved credentials, used by file sources and actions.
//
// Named "Identities" throughout the application, which reliably reads as user sign-in
// rather than as stored credentials, so the wording here is explicit about what these are
// and what uses them.

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { KeyRound, Pencil, Plus, Trash2 } from 'lucide-react';
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
import { AdminModal } from '../../components/admin/AdminModal';
import { GlassButton } from '../../components/ui/primitives';
import { ActionIdentityCredentialForm } from '../../components/workspaceActions/ActionIdentityCredentialForm';
import { ActionField, ACTION_INPUT_CLASS } from '../../components/workspaceActions/ActionFields';
import { actionAuthErrorMessage, isActionIdentityAuthType, type ActionCredentialValues, type ActionIdentityAuthType } from '../../lib/actionAuth';
import { actionIdentityDetails, savePersonalActionIdentity } from '../../lib/workspaceActionIdentity';

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
    const [editing, setEditing] = useState<WorkspaceIdentity | null | undefined>(undefined);

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) {
            return items;
        }
        return items.filter((identity) =>
            `${identity.name ?? ''} ${actionIdentityDetails(identity).username}`.toLowerCase().includes(needle),
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
            <GlassButton type="button" size="sm" variant="primary" onClick={() => setEditing(null)}>
                <Plus size={15} aria-hidden="true" /> Add action identity
            </GlassButton>

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
                . Add or edit action usernames/passwords, API keys, and bearer tokens here, even if personal action authoring is disabled. Other identity types are managed in the{' '}
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
                            actionIdentityDetails(identity).username ||
                            String(identity.description ?? '')
                        }
                        meta={<Pill>{authTypeLabel(actionIdentityDetails(identity).authType)}</Pill>}
                        actions={
                            <div className="flex items-center gap-1">
                            {actionIdentityDetails(identity).supported ? <GlassButton type="button" size="sm"
                                aria-label={`Edit ${identity.name ?? 'identity'}`} onClick={() => setEditing(identity)}>
                                <Pencil size={15} aria-hidden="true" /> Edit
                            </GlassButton> : <a href="/workspace" className="px-2 text-xs text-accent underline">Edit in classic</a>}
                            <ConfirmAction
                                icon={<Trash2 size={15} />}
                                label={`Delete ${identity.name ?? 'identity'}`}
                                confirmLabel="Delete"
                                busy={busyId === identity.id}
                                onConfirm={() => void onDelete(identity)}
                            />
                            </div>
                        }
                    />
                )}
            />
            {editing !== undefined ? <PersonalActionIdentityEditor key={editing?.id || 'new'}
                original={editing} onClose={() => setEditing(undefined)}
                onSaved={(identity) => {
                    setItems([...items.filter((item) => item.id !== identity.id), identity]);
                    setEditing(undefined);
                }} /> : null}
        </div>
    );
}

function PersonalActionIdentityEditor({
    original, onClose, onSaved,
}: {
    original: WorkspaceIdentity | null;
    onClose: () => void;
    onSaved: (identity: WorkspaceIdentity) => void;
}) {
    const id = useId();
    const details = original ? actionIdentityDetails(original) : null;
    const [name, setName] = useState(original?.name ?? 'Yamcs');
    const [description, setDescription] = useState(original?.description ?? '');
    const [authType, setAuthType] = useState<ActionIdentityAuthType>(
        isActionIdentityAuthType(details?.authType) ? details.authType : 'username_password',
    );
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const controller = useRef<AbortController | null>(null);
    useEffect(() => () => controller.current?.abort(), []);
    const close = () => { controller.current?.abort(); onClose(); };
    const save = async (credentials: ActionCredentialValues | undefined) => {
        if (saving) return;
        const request = new AbortController();
        controller.current = request;
        setSaving(true); setError(null);
        try {
            const identity = await savePersonalActionIdentity(name, description, authType, credentials, original, request.signal);
            if (!request.signal.aborted) onSaved(identity);
        } catch (cause) {
            if (!request.signal.aborted) setError(actionAuthErrorMessage(cause));
        } finally {
            if (!request.signal.aborted) setSaving(false);
        }
    };
    return (
        <AdminModal title={original ? 'Edit action identity' : 'Add action identity'}
            description="Private credentials for Actions usage. Creating an identity does not grant access to an action or approve a destination."
            onClose={close}>
            <ActionIdentityCredentialForm key={authType} authType={authType} busy={saving} error={error}
                initialUsername={details?.authType === authType ? details.username : ''}
                keepStoredSecret={details?.authType === authType && details.stored}
                onSubmit={save} onCancel={close}>
                <ActionField id={`${id}-name`} label="Identity name" required
                    help="Use Yamcs, or the name supplied by the action administrator. Names help discovery; ownership and destination approval are checked separately.">
                    <input id={`${id}-name`} className={ACTION_INPUT_CLASS} value={name} required maxLength={120}
                        disabled={saving} onChange={(event) => setName(event.target.value)} />
                </ActionField>
                <ActionField id={`${id}-description`} label="Description">
                    <textarea id={`${id}-description`} className={ACTION_INPUT_CLASS} value={description} rows={2}
                        maxLength={500} disabled={saving} onChange={(event) => setDescription(event.target.value)} />
                </ActionField>
                <ActionField id={`${id}-type`} label="Credential type" required>
                    <select id={`${id}-type`} className={ACTION_INPUT_CLASS} value={authType} disabled={saving}
                        onChange={(event) => { if (isActionIdentityAuthType(event.target.value)) setAuthType(event.target.value); }}>
                        <option value="username_password">Username and password</option>
                        <option value="api_key">API key</option>
                        <option value="bearer_token">Bearer token</option>
                    </select>
                </ActionField>
                <p className="text-xs text-text-3">Usage: Actions{original && Array.isArray(original.usage_contexts) && original.usage_contexts.includes('file_sync') ? ' and existing file sources' : ''}. Stored secrets are never returned to this form.</p>
            </ActionIdentityCredentialForm>
        </AdminModal>
    );
}
