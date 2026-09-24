// FileSourceEditorDialog.tsx
// Writing a group file source: a modal for a connection the group syncs from.
//
// This mirrors the classic file source editor's fields and rules so a group source authored here is
// interchangeable with one authored in classic: the source type decides which connection inputs and
// auth methods appear, credentials come from a saved group identity or are entered directly, and a
// schedule and filters shape what is brought in. Secrets are never sent back to the browser, so a
// secret field opens blank and a blank secret on save keeps the stored value.
//
// Test connection and Browse run against the draft as it stands, without saving, so a manager can
// confirm a connection before committing it. Browsing a saved source can also ignore a remote path,
// which the engine then skips on the next run.

import { useEffect, useMemo, useRef, useState } from 'react';
import { FolderOpen, Loader2, PlugZap } from 'lucide-react';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';
import {
    authTypeLabel,
    authUsesClientId,
    authUsesSecret,
    authUsesUsername,
    connectionDescriptor,
    draftBrowseRoot,
    eligibleIdentities,
    secretFieldLabel,
    visibleSourceTypes,
    type FileSourceDraft,
} from '../../lib/fileSourceFields';
import type {
    FileSourceBrowseEntry,
    FileSourceOptions,
    WorkspaceIdentity,
} from '../../lib/types';
import type {
    FileSourceBrowseResult,
    FileSourceConnectionResult,
} from '../../lib/fileSourceWorkbench';

const FIELD_CLASS =
    'w-full rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none';

/**
 * A one-line summary of a successful connection test. A failed test is an HTTP 400 shown verbatim
 * elsewhere, so this only ever describes success, reporting the counts the server actually saw.
 */
function connectionSummary(result: FileSourceConnectionResult): string {
    const checked = Number(result.entries_checked ?? 0);
    const folders = Number(result.folders_seen ?? 0);
    const files = Number(result.files_seen ?? 0);
    return `Connected. Checked ${checked} ${checked === 1 ? 'entry' : 'entries'}: ${folders} ${folders === 1 ? 'folder' : 'folders'}, ${files} ${files === 1 ? 'file' : 'files'}.`;
}

export function FileSourceEditorDialog({
    draft,
    options,
    identities,
    saving,
    error,
    onChange,
    onSave,
    onCancel,
    onRefresh,
    onTest,
    onBrowse,
    onIgnore,
}: {
    draft: FileSourceDraft;
    options: FileSourceOptions | null;
    identities: WorkspaceIdentity[];
    saving: boolean;
    error: string | null;
    onChange: (next: FileSourceDraft) => void;
    onSave: () => void;
    onCancel: () => void;
    /** Present only after a conditional-write conflict; reloads so the next save carries the latest revision. */
    onRefresh?: () => void;
    onTest: () => Promise<FileSourceConnectionResult>;
    onBrowse: (browsePath: string) => Promise<FileSourceBrowseResult>;
    /**
     * Present only for a saved source; ignoring a browsed path skips it on the next run. Browse
     * cannot report ignore state, so this returns the item's resulting `ignored` flag and the dialog
     * tracks it per path for the session.
     */
    onIgnore?: (remotePath: string, ignored: boolean) => Promise<boolean>;
}) {
    const nameRef = useRef<HTMLInputElement>(null);
    const [confirmingDiscard, setConfirmingDiscard] = useState(false);
    const [original] = useState(() => JSON.stringify(draft));
    const dirty = JSON.stringify(draft) !== original;

    const [testing, setTesting] = useState(false);
    const [testResult, setTestResult] = useState<FileSourceConnectionResult | null>(null);
    const [testError, setTestError] = useState<string | null>(null);
    const [browsing, setBrowsing] = useState(false);
    const [browseResult, setBrowseResult] = useState<FileSourceBrowseResult | null>(null);
    const [browseError, setBrowseError] = useState<string | null>(null);
    // Browse carries no ignore state, so each ignored/restored path is tracked for the session from
    // the ignore response's returned item, defaulting an unseen path to not-ignored.
    const [ignoredPaths, setIgnoredPaths] = useState<Record<string, boolean>>({});
    const [ignoreError, setIgnoreError] = useState<string | null>(null);

    const descriptor = useMemo(() => connectionDescriptor(draft.sourceType), [draft.sourceType]);
    const typeOptions = useMemo(() => visibleSourceTypes(options), [options]);
    const eligible = useMemo(
        () => eligibleIdentities(identities, options, draft.sourceType),
        [identities, options, draft.sourceType],
    );
    const authTypes = descriptor.authTypes;
    const canSave = draft.name.trim().length > 0
        && (draft.credentialMode === 'inline' || draft.identityId.trim().length > 0);
    const scheduleRange = options?.schedule ?? { min_interval_minutes: 1, max_interval_minutes: 10080 };
    const recursiveAllowed = options?.recursive_allowed !== false;

    useEffect(() => {
        nameRef.current?.focus();
    }, []);

    // Keep the inline auth type valid for the current source type: a type change can drop the
    // selected method, so re-pick the first the type allows, exactly as the classic editor does.
    useEffect(() => {
        if (!authTypes.includes(draft.credentials.authType)) {
            onChange({ ...draft, credentials: { ...draft.credentials, authType: authTypes[0] ?? '' } });
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

    const setConnection = (patch: Partial<FileSourceDraft['connection']>) =>
        onChange({ ...draft, connection: { ...draft.connection, ...patch } });

    const setCredential = (patch: Partial<FileSourceDraft['credentials']>) =>
        onChange({ ...draft, credentials: { ...draft.credentials, ...patch } });

    const runTest = async () => {
        setTesting(true);
        setTestError(null);
        setTestResult(null);
        try {
            setTestResult(await onTest());
        } catch (cause) {
            setTestError(cause instanceof Error ? cause.message : 'The connection test failed.');
        } finally {
            setTesting(false);
        }
    };

    const runBrowse = async (browsePath: string) => {
        setBrowsing(true);
        setBrowseError(null);
        try {
            setBrowseResult(await onBrowse(browsePath));
        } catch (cause) {
            setBrowseError(cause instanceof Error ? cause.message : 'Could not browse this location.');
        } finally {
            setBrowsing(false);
        }
    };

    const chooseEntry = (entry: FileSourceBrowseEntry) => {
        const path = String(entry.path ?? entry.name ?? '');
        const field = descriptor.fields.find((candidate) => candidate.browseRoot);
        if (field) {
            setConnection({ [field.key]: path } as Partial<FileSourceDraft['connection']>);
        }
        if (entry.type === 'folder') {
            void runBrowse(path);
        }
    };

    const toggleIgnore = async (entry: FileSourceBrowseEntry) => {
        if (!onIgnore) {
            return;
        }
        const path = String(entry.path ?? entry.name ?? '');
        const next = !ignoredPaths[path];
        setIgnoreError(null);
        try {
            // The server's returned item is authoritative; browse can't reflect the change, so the
            // per-path map is updated from the response rather than by re-browsing.
            const applied = await onIgnore(path, next);
            setIgnoredPaths((current) => ({ ...current, [path]: applied }));
        } catch (cause) {
            setIgnoreError(cause instanceof Error ? cause.message : 'Could not update the ignore list.');
        }
    };

    const authType = draft.credentials.authType;

    return (
        <Modal
            title={draft.id ? 'Edit file source' : 'New file source'}
            description="A connection this group syncs documents from. Secrets are held server-side and never shown here."
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
                                Reload
                            </GlassButton>
                        ) : null}
                        <GlassButton variant="primary" size="sm" onClick={onSave} disabled={!canSave || saving}>
                            {saving ? 'Saving' : draft.id ? 'Save changes' : 'Create source'}
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
                            placeholder="Quarterly reports share"
                            className={FIELD_CLASS}
                        />
                    </label>
                    <label className="block">
                        <span className="mb-1 block text-xs font-medium text-text-2">Source type</span>
                        {draft.id ? (
                            <input type="text" value={draft.sourceType} disabled className={FIELD_CLASS} />
                        ) : (
                            <select
                                value={draft.sourceType}
                                onChange={(event) => onChange({ ...draft, sourceType: event.target.value })}
                                className={FIELD_CLASS}
                            >
                                {typeOptions.map((type) => (
                                    <option key={type.value} value={type.value}>
                                        {type.label}
                                    </option>
                                ))}
                            </select>
                        )}
                    </label>
                </div>

                <fieldset className="space-y-3">
                    <legend className="text-xs font-medium text-text-2">Connection</legend>
                    {descriptor.fields.map((field) => (
                        <label key={String(field.key)} className="block">
                            <span className="mb-1 flex items-center justify-between text-xs font-medium text-text-2">
                                <span>{field.label}</span>
                                {field.browseRoot ? (
                                    <button
                                        type="button"
                                        onClick={() => void runBrowse(draftBrowseRoot(draft))}
                                        disabled={browsing}
                                        className="inline-flex items-center gap-1 text-accent hover:underline disabled:opacity-50"
                                    >
                                        {browsing ? <Loader2 size={12} className="animate-spin" /> : <FolderOpen size={12} />}
                                        Browse
                                    </button>
                                ) : null}
                            </span>
                            <input
                                type="text"
                                value={draft.connection[field.key]}
                                onChange={(event) =>
                                    setConnection({ [field.key]: event.target.value } as Partial<FileSourceDraft['connection']>)
                                }
                                placeholder={field.placeholder}
                                className={FIELD_CLASS}
                            />
                        </label>
                    ))}

                    {browseError ? <p className="text-xs text-danger">{browseError}</p> : null}
                    {ignoreError ? <p className="text-xs text-danger">{ignoreError}</p> : null}
                    {browseResult ? (
                        <div className="rounded-lg border border-edge bg-surface-1 p-2">
                            <p className="mb-1 text-xs text-text-3">
                                {browseResult.path ? `Browsing ${browseResult.path}` : 'Browsing root'}
                            </p>
                            {browseResult.entries.length === 0 ? (
                                <p className="text-xs text-text-3">No items here.</p>
                            ) : (
                                <ul className="max-h-40 space-y-0.5 overflow-y-auto text-sm">
                                    {browseResult.entries.map((entry, index) => {
                                        const entryPath = String(entry.path ?? entry.name ?? index);
                                        const isFolder = entry.type === 'folder';
                                        const isIgnored = Boolean(ignoredPaths[entryPath]);
                                        return (
                                            <li
                                                key={entryPath}
                                                className="flex items-center justify-between gap-2"
                                            >
                                                <button
                                                    type="button"
                                                    onClick={() => chooseEntry(entry)}
                                                    className="flex-1 truncate text-left text-text-1 hover:text-accent"
                                                >
                                                    {isFolder ? 'Folder: ' : 'File: '}
                                                    {String(entry.name ?? entry.path ?? 'item')}
                                                </button>
                                                {onIgnore ? (
                                                    <button
                                                        type="button"
                                                        onClick={() => void toggleIgnore(entry)}
                                                        className="text-xs text-text-3 hover:text-text-1"
                                                    >
                                                        {isIgnored ? 'Restore' : 'Ignore'}
                                                    </button>
                                                ) : null}
                                            </li>
                                        );
                                    })}
                                </ul>
                            )}
                        </div>
                    ) : null}
                </fieldset>

                <fieldset className="space-y-3">
                    <legend className="text-xs font-medium text-text-2">Authentication</legend>
                    <div className="flex flex-wrap gap-3">
                        <label className="flex items-center gap-2 text-sm text-text-1">
                            <input
                                type="radio"
                                name="credential-mode"
                                checked={draft.credentialMode === 'identity'}
                                onChange={() => onChange({ ...draft, credentialMode: 'identity' })}
                            />
                            Use a saved group identity
                        </label>
                        <label className="flex items-center gap-2 text-sm text-text-1">
                            <input
                                type="radio"
                                name="credential-mode"
                                checked={draft.credentialMode === 'inline'}
                                onChange={() => onChange({ ...draft, credentialMode: 'inline' })}
                            />
                            Enter credentials directly
                        </label>
                    </div>

                    {draft.credentialMode === 'identity' ? (
                        <label className="block sm:max-w-md">
                            <span className="mb-1 block text-xs font-medium text-text-2">Identity</span>
                            <select
                                value={draft.identityId}
                                onChange={(event) => onChange({ ...draft, identityId: event.target.value })}
                                className={FIELD_CLASS}
                            >
                                <option value="">Select an identity…</option>
                                {eligible.map((identity) => (
                                    <option key={String(identity.id)} value={String(identity.id)}>
                                        {String(identity.name ?? identity.id)}
                                    </option>
                                ))}
                            </select>
                            {eligible.length === 0 ? (
                                <span className="mt-1 block text-xs text-text-3">
                                    No group identity is eligible for this source type. Add one in Identities, or enter
                                    credentials directly.
                                </span>
                            ) : null}
                        </label>
                    ) : (
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
                                            className={FIELD_CLASS}
                                        />
                                    </label>
                                </div>
                            ) : null}

                            {authUsesClientId(authType) ? (
                                <div className="grid gap-3 sm:grid-cols-2">
                                    <label className="block">
                                        <span className="mb-1 block text-xs font-medium text-text-2">Client ID</span>
                                        <input
                                            type="text"
                                            value={draft.credentials.clientId}
                                            onChange={(event) => setCredential({ clientId: event.target.value })}
                                            className={FIELD_CLASS}
                                        />
                                    </label>
                                    <label className="block">
                                        <span className="mb-1 block text-xs font-medium text-text-2">
                                            Tenant ID <span className="text-text-3">(optional)</span>
                                        </span>
                                        <input
                                            type="text"
                                            value={draft.credentials.tenantId}
                                            onChange={(event) => setCredential({ tenantId: event.target.value })}
                                            className={FIELD_CLASS}
                                        />
                                    </label>
                                </div>
                            ) : null}

                            {authType === 'managed_identity' ? (
                                <label className="block sm:max-w-md">
                                    <span className="mb-1 block text-xs font-medium text-text-2">
                                        Managed identity client ID <span className="text-text-3">(optional)</span>
                                    </span>
                                    <input
                                        type="text"
                                        value={draft.credentials.clientId}
                                        onChange={(event) => setCredential({ clientId: event.target.value })}
                                        placeholder="Leave blank for the system-assigned identity"
                                        className={FIELD_CLASS}
                                    />
                                </label>
                            ) : null}

                            {authUsesSecret(authType) ? (
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
                                            A secret is already stored. Leave this blank to keep it, or enter a new value
                                            to replace it.
                                        </span>
                                    ) : null}
                                </label>
                            ) : null}
                        </div>
                    )}

                    <div>
                        <GlassButton size="sm" onClick={() => void runTest()} disabled={testing}>
                            {testing ? <Loader2 size={14} className="animate-spin" /> : <PlugZap size={14} />}
                            Test connection
                        </GlassButton>
                        {testError ? <p className="mt-1 text-xs text-danger">{testError}</p> : null}
                        {testResult ? (
                            <p className="mt-1 text-xs text-ok">{connectionSummary(testResult)}</p>
                        ) : null}
                    </div>
                </fieldset>

                <fieldset className="space-y-3">
                    <legend className="text-xs font-medium text-text-2">Schedule and scope</legend>
                    <div className="flex flex-wrap items-center gap-4">
                        <label className="flex items-center gap-2 text-sm text-text-1">
                            <input
                                type="checkbox"
                                checked={draft.enabled}
                                onChange={(event) => onChange({ ...draft, enabled: event.target.checked })}
                            />
                            Enabled
                        </label>
                        {recursiveAllowed ? (
                            <label className="flex items-center gap-2 text-sm text-text-1">
                                <input
                                    type="checkbox"
                                    checked={draft.recursive}
                                    onChange={(event) => onChange({ ...draft, recursive: event.target.checked })}
                                />
                                Include subfolders
                            </label>
                        ) : null}
                        <label className="flex items-center gap-2 text-sm text-text-1">
                            <input
                                type="checkbox"
                                checked={draft.scheduleEnabled}
                                onChange={(event) => onChange({ ...draft, scheduleEnabled: event.target.checked })}
                            />
                            Sync on a schedule
                        </label>
                    </div>
                    {draft.scheduleEnabled ? (
                        <label className="block sm:max-w-xs">
                            <span className="mb-1 block text-xs font-medium text-text-2">
                                Every (minutes), {scheduleRange.min_interval_minutes}–{scheduleRange.max_interval_minutes}
                            </span>
                            <input
                                type="number"
                                min={scheduleRange.min_interval_minutes}
                                max={scheduleRange.max_interval_minutes}
                                value={draft.intervalMinutes}
                                onChange={(event) =>
                                    onChange({ ...draft, intervalMinutes: Number(event.target.value) || scheduleRange.min_interval_minutes })
                                }
                                className={FIELD_CLASS}
                            />
                        </label>
                    ) : null}
                </fieldset>

                <fieldset className="space-y-3">
                    <legend className="text-xs font-medium text-text-2">Filters <span className="text-text-3">(optional)</span></legend>
                    <label className="block">
                        <span className="mb-1 block text-xs font-medium text-text-2">Include patterns</span>
                        <input
                            type="text"
                            value={draft.includePatterns}
                            onChange={(event) => onChange({ ...draft, includePatterns: event.target.value })}
                            placeholder="*.pdf, reports/*"
                            className={FIELD_CLASS}
                        />
                    </label>
                    <label className="block">
                        <span className="mb-1 block text-xs font-medium text-text-2">Exclude patterns</span>
                        <input
                            type="text"
                            value={draft.excludePatterns}
                            onChange={(event) => onChange({ ...draft, excludePatterns: event.target.value })}
                            placeholder="drafts/*, *.tmp"
                            className={FIELD_CLASS}
                        />
                    </label>
                    <label className="block">
                        <span className="mb-1 block text-xs font-medium text-text-2">Allowed file types</span>
                        <input
                            type="text"
                            value={draft.allowedExtensions}
                            onChange={(event) => onChange({ ...draft, allowedExtensions: event.target.value })}
                            placeholder="pdf, docx, txt"
                            className={FIELD_CLASS}
                        />
                    </label>
                </fieldset>
            </div>
        </Modal>
    );
}
