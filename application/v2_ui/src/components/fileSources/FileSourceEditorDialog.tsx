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
// confirm a connection before committing it. Browse lists what is under the configured root, as the
// server resolves every browse path relative to it: a folder opens, and any folder or file can be
// selected so the source syncs only the selection, as in the classic editor. Browsing never changes
// the root itself. Browsing a saved source can also ignore a file, by the canonical remote path the
// server gives each browsed file -- the path the engine keys the file's item by -- so the engine
// skips it on the next run. Folders offer no Ignore: the engine keeps items only for files.
//
// The fixed tags, folder tags and remote delete policy are shown with the values the server will
// store, so a manager sees how synced files will be tagged and what happens to them when their source
// file is deleted, and an edit that changes something else saves them back untouched.

import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { ArrowUp, FolderOpen, Loader2, PlugZap, X } from 'lucide-react';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';
import {
    authTypeLabel,
    authUsesClientId,
    authUsesSecret,
    authUsesUsername,
    connectionDescriptor,
    eligibleIdentities,
    isPathSelected,
    normalizeFixedTag,
    parentBrowsePath,
    secretFieldLabel,
    visibleSourceTypes,
    withFixedTag,
    withSelectedPath,
    withoutSelectedPath,
    FOLDER_TAG_MODES,
    REMOTE_DELETE_POLICIES,
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

/** What each folder tag mode adds, from `_derive_tags_for_remote_file`, with a worked example. */
const FOLDER_TAG_HINTS: Record<string, string> = {
    none: 'Files get only the fixed tags.',
    parent: 'A file in Reports/2024 also gets the tag \u201c2024\u201d.',
    full_path: 'A file in Reports/2024 also gets the tags \u201creports\u201d and \u201c2024\u201d.',
};

/** What each remote delete policy does to a synced document when its source file is deleted. */
const REMOTE_DELETE_HINTS: Record<string, string> = {
    ignore: 'The document stays in this group when its source file is deleted.',
    hard_delete: 'The next sync deletes the document from this group when its source file is deleted.',
};

/** At most this many existing tags are offered at once, filtered by what has been typed. */
const TAG_SUGGESTION_LIMIT = 12;

export function FileSourceEditorDialog({
    draft,
    options,
    identities,
    tagSuggestions = [],
    tagSuggestionsFailed = false,
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
    /** The workspace's existing tag names, most used first, offered as fixed tags. */
    tagSuggestions?: string[];
    /** The existing tags could not be read, so none are offered; a tag can still be typed. */
    tagSuggestionsFailed?: boolean;
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
    const folderTagsId = useId();
    const deletePolicyId = useId();
    const [confirmingDiscard, setConfirmingDiscard] = useState(false);
    const [original] = useState(() => JSON.stringify(draft));
    // A path or tag typed but not yet added is unsaved work too: closing asks before discarding it,
    // and saving asks for it to be added or cleared rather than silently dropping it.
    const [pathInput, setPathInput] = useState('');
    const [pathError, setPathError] = useState<string | null>(null);
    const [tagInput, setTagInput] = useState('');
    const [tagError, setTagError] = useState<string | null>(null);
    const dirty = JSON.stringify(draft) !== original || pathInput.trim() !== '' || tagInput.trim() !== '';

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

    // A listing belongs to the source type it was browsed with; another type has another root.
    useEffect(() => {
        setBrowseResult(null);
        setBrowseError(null);
    }, [draft.sourceType]);

    const requestClose = () => {
        if (dirty && !confirmingDiscard) {
            setConfirmingDiscard(true);
            return;
        }
        onCancel();
    };

    const requestSave = () => {
        if (pathInput.trim()) {
            setPathError('Add the path you typed, or clear it, before saving.');
            return;
        }
        if (tagInput.trim()) {
            setTagError('Add the tag you typed, or clear it, before saving.');
            return;
        }
        onSave();
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

    const toggleSelected = (path: string) => {
        if (isPathSelected(draft.selectedPaths, path)) {
            onChange({ ...draft, selectedPaths: withoutSelectedPath(draft.selectedPaths, path) });
            return;
        }
        const result = withSelectedPath(draft.selectedPaths, path);
        if ('paths' in result) {
            onChange({ ...draft, selectedPaths: result.paths });
        }
    };

    const addTypedPath = () => {
        const result = withSelectedPath(draft.selectedPaths, pathInput);
        if ('error' in result) {
            setPathError(result.error);
            return;
        }
        setPathError(null);
        setPathInput('');
        onChange({ ...draft, selectedPaths: result.paths });
    };

    const addTag = (value: string) => {
        const result = withFixedTag(draft.fixedTags, value);
        if ('error' in result) {
            setTagError(result.error);
            return;
        }
        setTagError(null);
        setTagInput('');
        onChange({ ...draft, fixedTags: result.tags });
    };

    const onEnter = (action: () => void) => (event: KeyboardEvent<HTMLInputElement>) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            action();
        }
    };

    const typedTag = normalizeFixedTag(tagInput);
    const suggestions = useMemo(() => {
        const needle = tagInput.trim().toLowerCase();
        return tagSuggestions
            .filter((name) => !draft.fixedTags.includes(normalizeFixedTag(name)))
            .filter((name) => !needle || name.toLowerCase().includes(needle) || (typedTag !== '' && name.includes(typedTag)))
            .slice(0, TAG_SUGGESTION_LIMIT);
    }, [tagSuggestions, draft.fixedTags, tagInput, typedTag]);

    /** A browsed file's canonical remote path, or '' for a folder or an entry the server sent without one. */
    const ignorablePath = (entry: FileSourceBrowseEntry): string =>
        typeof entry.remote_path === 'string' ? entry.remote_path.trim() : '';

    const toggleIgnore = async (entry: FileSourceBrowseEntry) => {
        const remotePath = ignorablePath(entry);
        if (!onIgnore || !remotePath) {
            return;
        }
        const next = !ignoredPaths[remotePath];
        setIgnoreError(null);
        try {
            // Ignore by the path the engine keys the file's item by, which only the server can build:
            // the root-relative `path` would store an item the engine never reads. The returned item
            // is authoritative; browse can't reflect the change, so the per-path map is updated from
            // the response rather than by re-browsing.
            const applied = await onIgnore(remotePath, next);
            setIgnoredPaths((current) => ({ ...current, [remotePath]: applied }));
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
                        <GlassButton variant="primary" size="sm" onClick={requestSave} disabled={!canSave || saving}>
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
                            <span className="mb-1 block text-xs font-medium text-text-2">{field.label}</span>
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
                    <legend className="text-xs font-medium text-text-2">What to sync</legend>
                    <p className="text-xs text-text-3">
                        Choose folders and files to sync only those. Leave the list empty to sync everything under the
                        source root.
                    </p>
                    {draft.selectedPaths.length === 0 ? (
                        <p className="text-sm text-text-2">Syncing everything under the source root.</p>
                    ) : (
                        <div className="space-y-1.5">
                            <ul aria-label="Selected folders and files" className="space-y-1">
                                {draft.selectedPaths.map((path) => (
                                    <li
                                        key={path}
                                        className="flex items-center justify-between gap-2 rounded-lg border border-edge bg-surface-1 px-2.5 py-1"
                                    >
                                        <span className="min-w-0 truncate font-mono text-xs text-text-1" title={path}>
                                            {path}
                                        </span>
                                        <button
                                            type="button"
                                            aria-label={`Stop syncing ${path}`}
                                            title="Remove from the selection"
                                            onClick={() => onChange({ ...draft, selectedPaths: withoutSelectedPath(draft.selectedPaths, path) })}
                                            className="shrink-0 rounded p-1 text-text-3 hover:bg-surface-2 hover:text-danger"
                                        >
                                            <X size={13} />
                                        </button>
                                    </li>
                                ))}
                            </ul>
                            <button
                                type="button"
                                onClick={() => onChange({ ...draft, selectedPaths: [] })}
                                className="text-xs text-accent hover:underline"
                            >
                                Sync everything under the root instead
                            </button>
                        </div>
                    )}

                    <div className="flex flex-wrap items-end gap-2">
                        <label className="block min-w-0 flex-1 basis-56">
                            <span className="mb-1 block text-xs font-medium text-text-2">Add a folder or file</span>
                            <input
                                type="text"
                                value={pathInput}
                                onChange={(event) => {
                                    setPathInput(event.target.value);
                                    setPathError(null);
                                }}
                                onKeyDown={onEnter(addTypedPath)}
                                placeholder="Reports/2024 or Reports/summary.pdf"
                                aria-invalid={pathError ? true : undefined}
                                className={FIELD_CLASS}
                            />
                        </label>
                        <GlassButton size="sm" onClick={addTypedPath} disabled={!pathInput.trim()}>
                            Add path
                        </GlassButton>
                        <GlassButton size="sm" onClick={() => void runBrowse('')} disabled={browsing}>
                            {browsing ? <Loader2 size={14} className="animate-spin" /> : <FolderOpen size={14} />}
                            Browse the source
                        </GlassButton>
                    </div>
                    {pathError ? <p role="alert" className="text-xs text-danger">{pathError}</p> : null}

                    {browseError ? <p role="alert" className="text-xs text-danger">{browseError}</p> : null}
                    {ignoreError ? <p role="alert" className="text-xs text-danger">{ignoreError}</p> : null}
                    {browseResult ? (
                        <div className="rounded-lg border border-edge bg-surface-1 p-2">
                            <div className="mb-1 flex items-center justify-between gap-2">
                                <p className="min-w-0 truncate text-xs text-text-3">
                                    {browseResult.path ? `Browsing ${browseResult.path}` : 'Browsing the source root'}
                                </p>
                                {browseResult.path ? (
                                    <button
                                        type="button"
                                        onClick={() => void runBrowse(parentBrowsePath(browseResult.path))}
                                        disabled={browsing}
                                        className="inline-flex shrink-0 items-center gap-1 text-xs text-accent hover:underline disabled:opacity-50"
                                    >
                                        <ArrowUp size={12} />
                                        Up one folder
                                    </button>
                                ) : null}
                            </div>
                            {browseResult.entries.length === 0 ? (
                                <p className="text-xs text-text-3">No items here.</p>
                            ) : (
                                <ul className="max-h-48 space-y-0.5 overflow-y-auto text-sm">
                                    {browseResult.entries.map((entry, index) => {
                                        const entryPath = String(entry.path ?? entry.name ?? index);
                                        const entryName = String(entry.name ?? entry.path ?? 'item');
                                        const isFolder = entry.type === 'folder';
                                        const remotePath = ignorablePath(entry);
                                        const isIgnored = Boolean(remotePath && ignoredPaths[remotePath]);
                                        const selected = isPathSelected(draft.selectedPaths, entryPath);
                                        return (
                                            <li
                                                key={entryPath}
                                                className="flex items-center justify-between gap-2"
                                            >
                                                {isFolder ? (
                                                    <button
                                                        type="button"
                                                        onClick={() => void runBrowse(entryPath)}
                                                        disabled={browsing}
                                                        title={`Open ${entryPath}`}
                                                        className="min-w-0 flex-1 truncate text-left text-text-1 hover:text-accent"
                                                    >
                                                        Folder: {entryName}
                                                    </button>
                                                ) : (
                                                    <span className="min-w-0 flex-1 truncate text-text-1" title={entryPath}>
                                                        File: {entryName}
                                                    </span>
                                                )}
                                                <button
                                                    type="button"
                                                    aria-pressed={selected}
                                                    aria-label={`Select ${entryPath}`}
                                                    onClick={() => toggleSelected(entryPath)}
                                                    className={
                                                        selected
                                                            ? 'shrink-0 text-xs font-medium text-accent hover:underline'
                                                            : 'shrink-0 text-xs text-text-3 hover:text-text-1'
                                                    }
                                                >
                                                    {selected ? 'Selected' : 'Select'}
                                                </button>
                                                {onIgnore && remotePath ? (
                                                    <button
                                                        type="button"
                                                        aria-label={`${isIgnored ? 'Restore' : 'Ignore'} ${entryPath}`}
                                                        onClick={() => void toggleIgnore(entry)}
                                                        className="shrink-0 text-xs text-text-3 hover:text-text-1"
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

                <fieldset className="space-y-3">
                    <legend className="text-xs font-medium text-text-2">Tags and deletions</legend>
                    <div className="space-y-2">
                        <div>
                            <p className="text-xs font-medium text-text-2">Fixed tags</p>
                            <p className="text-xs text-text-3">Every file this source brings in gets these tags.</p>
                        </div>
                        {draft.fixedTags.length === 0 ? (
                            <p className="text-sm text-text-2">No fixed tags.</p>
                        ) : (
                            <ul aria-label="Fixed tags" className="flex flex-wrap gap-1.5">
                                {draft.fixedTags.map((tag) => (
                                    <li
                                        key={tag}
                                        className="inline-flex items-center gap-1 rounded-full border border-edge bg-surface-1 py-0.5 pl-2.5 pr-1 text-xs text-text-1"
                                    >
                                        {tag}
                                        <button
                                            type="button"
                                            aria-label={`Remove the fixed tag ${tag}`}
                                            onClick={() => onChange({ ...draft, fixedTags: draft.fixedTags.filter((current) => current !== tag) })}
                                            className="rounded-full p-0.5 text-text-3 hover:bg-surface-2 hover:text-danger"
                                        >
                                            <X size={12} />
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        )}
                        <div className="flex flex-wrap items-end gap-2">
                            <label className="block min-w-0 flex-1 basis-48 sm:max-w-xs">
                                <span className="mb-1 block text-xs font-medium text-text-2">Add a fixed tag</span>
                                <input
                                    type="text"
                                    value={tagInput}
                                    onChange={(event) => {
                                        setTagInput(event.target.value);
                                        setTagError(null);
                                    }}
                                    onKeyDown={onEnter(() => addTag(tagInput))}
                                    placeholder="finance"
                                    aria-invalid={tagError ? true : undefined}
                                    className={FIELD_CLASS}
                                />
                            </label>
                            <GlassButton size="sm" onClick={() => addTag(tagInput)} disabled={!tagInput.trim()}>
                                Add tag
                            </GlassButton>
                        </div>
                        {tagError ? (
                            <p role="alert" className="text-xs text-danger">{tagError}</p>
                        ) : typedTag && typedTag !== tagInput.trim() ? (
                            <p className="text-xs text-text-3">Saved as “{typedTag}”.</p>
                        ) : null}
                        {suggestions.length > 0 ? (
                            <div className="flex flex-wrap items-center gap-1.5">
                                <span className="text-xs text-text-3">This group’s tags:</span>
                                {suggestions.map((name) => (
                                    <button
                                        key={name}
                                        type="button"
                                        aria-label={`Add the existing tag ${name}`}
                                        onClick={() => addTag(name)}
                                        className="rounded-full border border-dashed border-edge px-2 py-0.5 text-xs text-text-2 hover:border-accent hover:text-accent"
                                    >
                                        + {name}
                                    </button>
                                ))}
                            </div>
                        ) : null}
                        {tagSuggestionsFailed ? (
                            <p className="text-xs text-text-3">
                                This group’s existing tags couldn’t be loaded. You can still type a tag.
                            </p>
                        ) : null}
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                        <div>
                            <label htmlFor={folderTagsId} className="mb-1 block text-xs font-medium text-text-2">
                                Folder tags
                            </label>
                            <select
                                id={folderTagsId}
                                value={draft.folderTagMode}
                                onChange={(event) => onChange({ ...draft, folderTagMode: event.target.value })}
                                aria-describedby={`${folderTagsId}-hint`}
                                className={FIELD_CLASS}
                            >
                                {FOLDER_TAG_MODES.map((mode) => (
                                    <option key={mode.value} value={mode.value}>
                                        {mode.label}
                                    </option>
                                ))}
                            </select>
                            <p id={`${folderTagsId}-hint`} className="mt-1 text-xs text-text-3">
                                {FOLDER_TAG_HINTS[draft.folderTagMode]}
                            </p>
                        </div>
                        <div>
                            <label htmlFor={deletePolicyId} className="mb-1 block text-xs font-medium text-text-2">
                                When a source file is deleted
                            </label>
                            <select
                                id={deletePolicyId}
                                value={draft.remoteDeletePolicy}
                                onChange={(event) => onChange({ ...draft, remoteDeletePolicy: event.target.value })}
                                aria-describedby={`${deletePolicyId}-hint`}
                                className={FIELD_CLASS}
                            >
                                {REMOTE_DELETE_POLICIES.map((policy) => (
                                    <option key={policy.value} value={policy.value}>
                                        {policy.label}
                                    </option>
                                ))}
                            </select>
                            <p id={`${deletePolicyId}-hint`} className="mt-1 text-xs text-text-3">
                                {REMOTE_DELETE_HINTS[draft.remoteDeletePolicy]}
                            </p>
                        </div>
                    </div>
                </fieldset>
            </div>
        </Modal>
    );
}
