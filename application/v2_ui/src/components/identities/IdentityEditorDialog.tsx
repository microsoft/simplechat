// IdentityEditorDialog.tsx
// Writing a group identity: a modal for a saved credential.
//
// This mirrors the classic identity editor's fields and rules so a group identity authored here is
// interchangeable with one authored in classic: the "Used For" capabilities decide which auth
// methods are offered and what provider and source types the write carries, and each auth method
// shows only the credential inputs it needs. Secrets are never sent back to the browser, so the
// secret field opens blank and, on an edit, its placeholder says the stored value is kept. A blank
// secret on save keeps the stored value -- the form cannot blank a stored secret out, only replace
// it or change the auth method.

import { useEffect, useMemo, useRef, useState } from 'react';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';
import {
    CAPABILITY_CONFIGS,
    GROUP_IDENTITY_CAPABILITIES,
    allowedAuthTypes,
    authTypeLabel,
    authUsesClientId,
    authUsesSecret,
    authUsesUsername,
    secretFieldLabel,
    type IdentityDraft,
} from '../../lib/identityFields';

const FIELD_CLASS =
    'w-full rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none';

export function IdentityEditorDialog({
    draft,
    saving,
    error,
    onChange,
    onSave,
    onCancel,
    onRefresh,
}: {
    draft: IdentityDraft;
    saving: boolean;
    error: string | null;
    onChange: (next: IdentityDraft) => void;
    onSave: () => void;
    onCancel: () => void;
    /**
     * Present only after a conditional-write conflict on a shared group identity. Reloads the list
     * so the editor's next save carries the latest etag, without discarding the open draft.
     */
    onRefresh?: () => void;
}) {
    const nameRef = useRef<HTMLInputElement>(null);
    const [confirmingDiscard, setConfirmingDiscard] = useState(false);
    const [original] = useState(() => JSON.stringify(draft));
    const dirty = JSON.stringify(draft) !== original;

    const authTypes = useMemo(() => allowedAuthTypes(draft.capabilities), [draft.capabilities]);
    const canSave = draft.name.trim().length > 0;

    useEffect(() => {
        nameRef.current?.focus();
    }, []);

    // Keep the selected auth type valid for the current capabilities: a capability change can
    // remove the method that was selected, exactly as the classic editor re-picks the first allowed
    // type. Done as an effect so the write never carries a method the capabilities do not allow.
    useEffect(() => {
        if (!authTypes.includes(draft.credentials.authType)) {
            onChange({ ...draft, credentials: { ...draft.credentials, authType: authTypes[0] } });
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [authTypes]);

    const requestClose = () => {
        if (dirty && !confirmingDiscard) {
            setConfirmingDiscard(true);
            return;
        }
        onCancel();
    };

    const toggleCapability = (value: string) => {
        const selected = draft.capabilities.includes(value)
            ? draft.capabilities.filter((capability) => capability !== value)
            : [...draft.capabilities, value];
        // At least one capability stays selected, matching the classic editor's guard.
        onChange({ ...draft, capabilities: selected.length ? selected : draft.capabilities });
    };

    const setCredential = (patch: Partial<IdentityDraft['credentials']>) =>
        onChange({ ...draft, credentials: { ...draft.credentials, ...patch } });

    const authType = draft.credentials.authType;
    const showSecret = authUsesSecret(authType);

    return (
        <Modal
            title={draft.id ? 'Edit identity' : 'New identity'}
            description="A reusable credential for the systems this group connects to. Secrets are held server-side and never shown here."
            onClose={requestClose}
            size="lg"
            footer={
                confirmingDiscard ? (
                    <>
                        <span className="mr-auto text-xs text-text-3">Discard your unsaved changes?</span>
                        <GlassButton size="sm" onClick={() => setConfirmingDiscard(false)}>
                            Keep editing
                        </GlassButton>
                        <GlassButton variant="danger" size="sm" onClick={onCancel}>
                            Discard
                        </GlassButton>
                    </>
                ) : (
                    <>
                        {error ? <span className="mr-auto text-xs text-danger">{error}</span> : null}
                        <GlassButton size="sm" onClick={requestClose} disabled={saving}>
                            Cancel
                        </GlassButton>
                        {onRefresh ? (
                            <GlassButton size="sm" onClick={onRefresh} disabled={saving}>
                                Refresh
                            </GlassButton>
                        ) : null}
                        <GlassButton variant="primary" size="sm" onClick={onSave} disabled={!canSave || saving}>
                            {saving ? 'Saving' : draft.id ? 'Save changes' : 'Create identity'}
                        </GlassButton>
                    </>
                )
            }
        >
            <div className="space-y-5">
                <div className="grid gap-3 sm:grid-cols-2">
                    <label className="block">
                        <span className="mb-1 block text-xs font-medium text-text-2">Name</span>
                        <input
                            ref={nameRef}
                            type="text"
                            value={draft.name}
                            onChange={(event) => onChange({ ...draft, name: event.target.value })}
                            placeholder="Reporting service account"
                            className={FIELD_CLASS}
                        />
                    </label>
                    <label className="block">
                        <span className="mb-1 block text-xs font-medium text-text-2">
                            Description <span className="text-text-3">(optional)</span>
                        </span>
                        <input
                            type="text"
                            maxLength={200}
                            value={draft.description}
                            onChange={(event) => onChange({ ...draft, description: event.target.value })}
                            placeholder="What this credential is for"
                            className={FIELD_CLASS}
                        />
                    </label>
                </div>

                <fieldset className="space-y-2">
                    <legend className="text-xs font-medium text-text-2">Used for</legend>
                    <p className="text-xs text-text-3">
                        Choose the SimpleChat capabilities that may use this identity.
                    </p>
                    <div className="flex flex-wrap gap-3">
                        {GROUP_IDENTITY_CAPABILITIES.map((value) => {
                            const config = CAPABILITY_CONFIGS[value];
                            const checked = draft.capabilities.includes(value);
                            return (
                                <label
                                    key={value}
                                    className="flex max-w-xs items-start gap-2 rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm"
                                    title={config.help}
                                >
                                    <input
                                        type="checkbox"
                                        checked={checked}
                                        onChange={() => toggleCapability(value)}
                                        className="mt-0.5"
                                    />
                                    <span>
                                        <span className="block text-text-1">{config.label}</span>
                                        <span className="block text-xs text-text-3">{config.help}</span>
                                    </span>
                                </label>
                            );
                        })}
                    </div>
                </fieldset>

                <div className="space-y-3">
                    <label className="block sm:max-w-xs">
                        <span className="mb-1 block text-xs font-medium text-text-2">Authentication method</span>
                        <select
                            value={authType}
                            onChange={(event) => setCredential({ authType: event.target.value })}
                            className={FIELD_CLASS}
                        >
                            {authTypes.map((value) => (
                                <option key={value} value={value}>
                                    {authTypeLabel(value)}
                                </option>
                            ))}
                        </select>
                    </label>

                    {authUsesUsername(authType) ? (
                        <div className="grid gap-3 sm:grid-cols-2">
                            <label className="block">
                                <span className="mb-1 block text-xs font-medium text-text-2">Username</span>
                                <input
                                    type="text"
                                    value={draft.credentials.username}
                                    onChange={(event) => setCredential({ username: event.target.value })}
                                    className={FIELD_CLASS}
                                />
                            </label>
                            <label className="block">
                                <span className="mb-1 block text-xs font-medium text-text-2">
                                    Domain <span className="text-text-3">(optional)</span>
                                </span>
                                <input
                                    type="text"
                                    value={draft.credentials.domain}
                                    onChange={(event) => setCredential({ domain: event.target.value })}
                                    placeholder="Leave blank when no domain is required"
                                    className={FIELD_CLASS}
                                />
                            </label>
                        </div>
                    ) : null}

                    {authUsesClientId(authType) ? (
                        <label className="block sm:max-w-md">
                            <span className="mb-1 block text-xs font-medium text-text-2">Client ID</span>
                            <input
                                type="text"
                                value={draft.credentials.clientId}
                                onChange={(event) => setCredential({ clientId: event.target.value })}
                                placeholder="Application or service principal client ID"
                                className={FIELD_CLASS}
                            />
                        </label>
                    ) : null}

                    {showSecret ? (
                        <label className="block sm:max-w-md">
                            <span className="mb-1 block text-xs font-medium text-text-2">
                                {secretFieldLabel(authType, draft.secretStored)}
                            </span>
                            <input
                                type="password"
                                autoComplete="new-password"
                                value={draft.credentials.secret}
                                onChange={(event) => setCredential({ secret: event.target.value })}
                                placeholder={draft.secretStored ? 'Stored value unchanged' : ''}
                                className={FIELD_CLASS}
                            />
                            {draft.secretStored ? (
                                <span className="mt-1 block text-xs text-text-3">
                                    A secret is already stored. Leave this blank to keep it, or enter a new value to
                                    replace it. It cannot be cleared here — change the authentication method instead.
                                </span>
                            ) : null}
                        </label>
                    ) : null}
                </div>
            </div>
        </Modal>
    );
}
