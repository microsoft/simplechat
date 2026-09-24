// GroupSettingsSection.tsx
// The group workspace Settings section (M7C): the group's profile, logo, download and retention
// policy, and the delete danger zone, managed natively through the /api/groups/<g>/settings routes.
//
// Every control comes from the server's settings_management hint, with no fallback: a withheld edit
// is disabled and explained by the server's own reason, never guessed. Nothing is kept optimistically
// -- each write answers with the fresh settings read, which the section replaces its state from
// wholesale, so a field, a revision and the offered controls always show what the server holds. A
// stale section revision (group_settings_changed) reloads that section and rebases the draft over it;
// a write-guard exhaustion (group_write_conflict) keeps the draft for a plain retry; a 400 shows the
// server's verbatim message. The downloads and retention cards render only when the server includes
// their block, so an unavailable capability is absent rather than shown disabled.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUpRight, Image as ImageIcon, Loader2, Trash2, Upload } from 'lucide-react';
import { EmptyState, GlassButton, GlassPanel, Skeleton } from '../../components/ui/primitives';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { SectionIntro } from '../../components/workspace/primitives';
import { codePointLength } from '../../lib/groupDirectory';
import { rebaseDraft, rebaseNotice, type RebaseField } from '../../lib/rebaseDraft';
import {
    GroupLogoMissingError, GroupSettingsChangedError, GroupSettingsWriteConflictError,
    groupSettingsReasonText,
    type GroupProfileChanges, type GroupRetentionValue, type GroupSettings, type GroupSettingsAdapter,
} from '../../lib/groupSettings';

const NAME_MAX = 80;
const DESCRIPTION_MAX = 500;
const HERO_COLOR_FALLBACK = '#4f46e5';
const LOGO_TYPES = ['image/png', 'image/jpeg'];

const PROFILE_REBASE_FIELDS: RebaseField[] = [
    { path: 'name', label: 'Name' },
    { path: 'description', label: 'Description' },
    { path: 'hero_color', label: 'Colour' },
];

const RETENTION_REBASE_FIELDS: RebaseField[] = [
    { path: 'conversation', label: 'Conversation retention' },
    { path: 'document', label: 'Document retention' },
];

interface ProfileDraft {
    name: string;
    description: string;
    hero_color: string;
}

interface Notice {
    tone: 'status' | 'alert';
    text: string;
}

function profileDraftOf(settings: GroupSettings): ProfileDraft {
    return {
        name: settings.profile.name,
        description: settings.profile.description,
        hero_color: settings.profile.hero_color || HERO_COLOR_FALLBACK,
    };
}

/** A retention value shown in a text field: a number of days, or the words the server accepts. */
function retentionToInput(value: GroupRetentionValue): string {
    if (value === 'none' || value === 'default') {
        return value;
    }
    return String(value);
}

/** The retention draft for a settings read, or null when the group has no retention card. */
function retentionDraftOf(settings: GroupSettings): { conversation: string; document: string } | null {
    return settings.retention ? {
        conversation: retentionToInput(settings.retention.conversation_retention_days),
        document: retentionToInput(settings.retention.document_retention_days),
    } : null;
}

/** Read a retention field back: blank keeps the stored value out of the request entirely. */
function retentionFromInput(raw: string): GroupRetentionValue | undefined {
    const trimmed = raw.trim().toLowerCase();
    if (!trimmed) {
        return undefined;
    }
    if (trimmed === 'none' || trimmed === 'default') {
        return trimmed;
    }
    const days = Number(trimmed);
    if (!Number.isInteger(days) || days < 0) {
        return undefined;
    }
    return days;
}

const FIELD_CLASS =
    'mt-1 w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60';

export function GroupSettingsSection({
    adapter, interactionDisabled, onBusyChange, onDirtyChange, onAccessChanged, onOpenClassic,
}: {
    adapter: GroupSettingsAdapter;
    /** True while the workspace context is being re-confirmed; every write waits for it. */
    interactionDisabled: boolean;
    onBusyChange: (busy: boolean) => void;
    onDirtyChange: (dirty: boolean) => void;
    /** Re-read the workspace context after a refusal that means the caller's own standing changed. */
    onAccessChanged: () => void;
    /** Open the classic group page for the delete flow classic still owns. */
    onOpenClassic: () => void;
}) {
    const [settings, setSettings] = useState<GroupSettings | null>(null);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState('');
    const [reloadToken, setReloadToken] = useState(0);

    const [draft, setDraft] = useState<ProfileDraft | null>(null);
    const [profileBusy, setProfileBusy] = useState(false);
    const [profileError, setProfileError] = useState('');
    const [notice, setNotice] = useState<Notice | null>(null);

    const [logoBusy, setLogoBusy] = useState(false);
    const [logoError, setLogoError] = useState('');
    // A logo write is never auto-retried: a stale-revision or write-guard conflict keeps the chosen
    // file here so the user can retry explicitly after seeing the fresh logo, rather than the editor
    // silently overwriting a change it hasn't shown them.
    const [pendingLogo, setPendingLogo] = useState<File | null>(null);

    const [downloadsBusy, setDownloadsBusy] = useState(false);
    const [downloadsError, setDownloadsError] = useState('');

    const [retentionDraft, setRetentionDraft] = useState<{ conversation: string; document: string } | null>(null);
    const [retentionBusy, setRetentionBusy] = useState(false);
    const [retentionError, setRetentionError] = useState('');

    const [fileCount, setFileCount] = useState<number | null>(null);
    const [fileCountError, setFileCountError] = useState('');
    const [deleteOpen, setDeleteOpen] = useState(false);

    const fileInputRef = useRef<HTMLInputElement>(null);
    const onBusyChangeRef = useRef(onBusyChange);
    onBusyChangeRef.current = onBusyChange;
    const onDirtyChangeRef = useRef(onDirtyChange);
    onDirtyChangeRef.current = onDirtyChange;
    const onAccessChangedRef = useRef(onAccessChanged);
    onAccessChangedRef.current = onAccessChanged;

    const busy = profileBusy || logoBusy || downloadsBusy || retentionBusy;
    useEffect(() => { onBusyChangeRef.current(busy); }, [busy]);
    useEffect(() => () => { onBusyChangeRef.current(false); onDirtyChangeRef.current(false); }, []);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setLoadError('');
        void adapter.readSettings(controller.signal)
            .then((next) => {
                if (controller.signal.aborted) return;
                setSettings(next);
                setDraft(profileDraftOf(next));
                setRetentionDraft(next.retention ? {
                    conversation: retentionToInput(next.retention.conversation_retention_days),
                    document: retentionToInput(next.retention.document_retention_days),
                } : null);
            })
            .catch((cause: unknown) => {
                if (controller.signal.aborted) return;
                setSettings(null);
                setLoadError(cause instanceof Error ? cause.message : 'The group settings could not be loaded. Please retry.');
            })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [adapter, reloadToken]);

    // The document count for the danger zone is read on its own so a slow or unavailable count never
    // blocks the settings from rendering. It is offered only when the viewer may see it.
    useEffect(() => {
        if (!settings || !adapter.allows('view_file_count')) {
            setFileCount(null);
            setFileCountError('');
            return undefined;
        }
        const controller = new AbortController();
        setFileCountError('');
        void adapter.readFileCount(controller.signal)
            .then((count) => { if (!controller.signal.aborted) setFileCount(count); })
            .catch((cause: unknown) => {
                if (controller.signal.aborted) return;
                setFileCount(null);
                setFileCountError(cause instanceof Error ? cause.message : 'The document count could not be loaded.');
            });
        return () => controller.abort();
    }, [adapter, settings]);

    const profileDirty = useMemo(() => {
        if (!settings || !draft) return false;
        const base = profileDraftOf(settings);
        return draft.name !== base.name || draft.description !== base.description || draft.hero_color !== base.hero_color;
    }, [settings, draft]);
    useEffect(() => { onDirtyChangeRef.current(profileDirty); }, [profileDirty]);

    const reload = useCallback(() => setReloadToken((value) => value + 1), []);

    const canEditName = adapter.allows('edit_name');
    const canEditDescription = adapter.allows('edit_description');
    const canEditColor = adapter.allows('edit_color');
    const canEditLogo = adapter.allows('edit_logo');
    const canEditProfile = canEditName || canEditDescription || canEditColor;
    const canEditDownloads = adapter.allows('edit_downloads');
    const canEditRetention = adapter.allows('edit_retention');

    const profileReason = groupSettingsReasonText(
        adapter.reason('edit_name') || adapter.reason('edit_description') || adapter.reason('edit_color'),
    );
    const logoReason = groupSettingsReasonText(adapter.reason('edit_logo'));
    const downloadsReason = groupSettingsReasonText(adapter.reason('edit_downloads'));
    const retentionReason = groupSettingsReasonText(adapter.reason('edit_retention'));

    /** Bring a refusal or conflict to the state the server holds, per the code it carries. */
    const settleWrite = useCallback(async (
        cause: unknown, setError: (message: string) => void, baseline: GroupSettings,
    ): Promise<void> => {
        const message = cause instanceof Error ? cause.message : 'The change could not be saved. Please retry.';
        setError(message);
        if (cause instanceof GroupSettingsWriteConflictError) {
            // Nothing changed: the state is kept so the same action can simply be retried.
            return;
        }
        if (cause instanceof GroupSettingsChangedError) {
            // A stale section revision: reload the settings and rebase the drafts over the fresh copy,
            // so a concurrent change to another field never discards the user's in-progress edits.
            try {
                const fresh = await adapter.readSettings();
                setSettings(fresh);
                setRetentionDraft((current) => {
                    const freshDraft = retentionDraftOf(fresh);
                    if (!current || !freshDraft) return freshDraft;
                    const baseDraft = retentionDraftOf(baseline) ?? freshDraft;
                    return rebaseDraft(baseDraft, freshDraft, current, RETENTION_REBASE_FIELDS).draft;
                });
                setDraft((current) => {
                    if (!current) return profileDraftOf(fresh);
                    const result = rebaseDraft(profileDraftOf(baseline), profileDraftOf(fresh), current, PROFILE_REBASE_FIELDS);
                    const rebased = rebaseNotice(result.conflicts);
                    if (rebased) setNotice({ tone: 'alert', text: rebased });
                    return result.draft;
                });
            } catch {
                reload();
            }
            return;
        }
        if (cause instanceof GroupLogoMissingError) {
            reload();
            return;
        }
        // A 403 refusal that changed the caller's standing re-reads the whole context.
        reload();
        onAccessChangedRef.current();
    }, [adapter, reload]);

    /**
     * Settle a logo write, which is never auto-retried. A stale-revision or already-gone conflict
     * reloads the settings so the fresh logo shows, and a write-guard exhaustion keeps the state as
     * it is; either way the chosen file is kept so the user can retry explicitly. The profile draft
     * is untouched, because a logo write carries none of its fields.
     */
    const settleLogoWrite = useCallback(async (cause: unknown, file: File | null): Promise<void> => {
        const message = cause instanceof Error ? cause.message : 'The logo could not be saved. Please retry.';
        setLogoError(message);
        if (cause instanceof GroupSettingsWriteConflictError) {
            setPendingLogo(file);
            return;
        }
        if (cause instanceof GroupSettingsChangedError || cause instanceof GroupLogoMissingError) {
            setPendingLogo(file);
            try {
                setSettings(await adapter.readSettings());
            } catch {
                reload();
            }
            return;
        }
        setPendingLogo(null);
        reload();
        onAccessChangedRef.current();
    }, [adapter, reload]);

    const saveProfile = async () => {
        if (!settings || !draft) return;
        const base = profileDraftOf(settings);
        const changes: GroupProfileChanges = {};
        if (canEditName && draft.name !== base.name) changes.name = draft.name;
        if (canEditDescription && draft.description !== base.description) changes.description = draft.description;
        if (canEditColor && draft.hero_color !== base.hero_color) changes.hero_color = draft.hero_color;
        if (Object.keys(changes).length === 0) return;
        if (changes.name !== undefined && codePointLength(changes.name.trim()) > NAME_MAX) {
            setProfileError(`Group names can be at most ${NAME_MAX} characters.`);
            return;
        }
        if (changes.description !== undefined && codePointLength(changes.description) > DESCRIPTION_MAX) {
            setProfileError(`Descriptions can be at most ${DESCRIPTION_MAX} characters.`);
            return;
        }
        setProfileBusy(true);
        setProfileError('');
        setNotice(null);
        try {
            const next = await adapter.updateProfile(changes, settings.profile.revision);
            setSettings(next);
            setDraft(profileDraftOf(next));
            setNotice({ tone: 'status', text: 'Group profile saved.' });
        } catch (cause) {
            await settleWrite(cause, setProfileError, settings);
        } finally {
            setProfileBusy(false);
        }
    };

    const uploadLogo = async (file: File) => {
        if (!settings) return;
        if (!LOGO_TYPES.includes(file.type)) {
            setLogoError('Choose a PNG or JPEG image.');
            return;
        }
        setLogoBusy(true);
        setLogoError('');
        setNotice(null);
        try {
            const next = await adapter.replaceLogo(file, settings.logo.revision);
            setSettings(next);
            setPendingLogo(null);
            setNotice({ tone: 'status', text: 'Group logo updated.' });
        } catch (cause) {
            await settleLogoWrite(cause, file);
        } finally {
            setLogoBusy(false);
        }
    };

    const removeLogo = async () => {
        if (!settings) return;
        setLogoBusy(true);
        setLogoError('');
        setNotice(null);
        try {
            const next = await adapter.removeLogo(settings.logo.revision);
            setSettings(next);
            setPendingLogo(null);
            setNotice({ tone: 'status', text: 'Group logo removed.' });
        } catch (cause) {
            await settleLogoWrite(cause, null);
        } finally {
            setLogoBusy(false);
        }
    };

    const saveDownloads = async (disable: boolean) => {
        if (!settings?.downloads) return;
        setDownloadsBusy(true);
        setDownloadsError('');
        setNotice(null);
        try {
            const next = await adapter.updateDownloads(disable, settings.downloads.revision);
            setSettings(next);
            setNotice({ tone: 'status', text: 'File download policy saved.' });
        } catch (cause) {
            await settleWrite(cause, setDownloadsError, settings);
        } finally {
            setDownloadsBusy(false);
        }
    };

    const saveRetention = async () => {
        if (!settings?.retention || !retentionDraft) return;
        const changes: { conversation_retention_days?: GroupRetentionValue; document_retention_days?: GroupRetentionValue } = {};
        const conversation = retentionFromInput(retentionDraft.conversation);
        const document = retentionFromInput(retentionDraft.document);
        if (retentionDraft.conversation.trim() && conversation === undefined) {
            setRetentionError('Enter a whole number of days, or "none" or "default".');
            return;
        }
        if (retentionDraft.document.trim() && document === undefined) {
            setRetentionError('Enter a whole number of days, or "none" or "default".');
            return;
        }
        if (conversation !== undefined) changes.conversation_retention_days = conversation;
        if (document !== undefined) changes.document_retention_days = document;
        if (Object.keys(changes).length === 0) return;
        setRetentionBusy(true);
        setRetentionError('');
        setNotice(null);
        try {
            const next = await adapter.updateRetention(changes, settings.retention.revision);
            setSettings(next);
            setRetentionDraft(next.retention ? {
                conversation: retentionToInput(next.retention.conversation_retention_days),
                document: retentionToInput(next.retention.document_retention_days),
            } : null);
            setNotice({ tone: 'status', text: 'Retention policy saved.' });
        } catch (cause) {
            await settleWrite(cause, setRetentionError, settings);
        } finally {
            setRetentionBusy(false);
        }
    };

    if (loading) {
        return (
            <div className="space-y-3" aria-busy="true">
                <Skeleton className="h-8 w-56" />
                <Skeleton className="h-40 w-full" />
                <Skeleton className="h-32 w-full" />
            </div>
        );
    }

    if (loadError || !settings || !draft) {
        return (
            <EmptyState icon={<ImageIcon size={28} />} title="Settings unavailable"
                description={loadError || 'The group settings could not be loaded.'}
                action={<GlassButton size="sm" onClick={reload}>Retry</GlassButton>} />
        );
    }

    const disabled = interactionDisabled || busy;
    const logo = settings.logo;

    return (
        <div className="space-y-4" data-testid="group-settings-section">
            <SectionIntro title="Group settings"
                description="The group's profile, logo and policies. A locked control shows why it's unavailable to you." />

            {notice ? (
                <p role={notice.tone === 'alert' ? 'alert' : 'status'}
                    className={notice.tone === 'alert' ? 'text-xs text-danger' : 'text-xs text-ok'}>
                    {notice.text}
                </p>
            ) : null}

            <GlassPanel className="space-y-4 p-4">
                <div className="flex items-baseline justify-between gap-3">
                    <h3 className="text-sm font-semibold text-text-1">Profile</h3>
                    {!canEditProfile && profileReason ? <span className="text-xs text-text-3">{profileReason}</span> : null}
                </div>
                <fieldset disabled={disabled} className="min-w-0 space-y-3">
                    <label className="block text-xs font-medium text-text-2">
                        Name
                        <input type="text" value={draft.name} disabled={!canEditName} maxLength={NAME_MAX * 2}
                            className={FIELD_CLASS} data-testid="group-settings-name"
                            onChange={(event) => { setProfileError(''); setDraft((current) => current && { ...current, name: event.target.value }); }} />
                    </label>
                    <label className="block text-xs font-medium text-text-2">
                        Description
                        <textarea value={draft.description} disabled={!canEditDescription} rows={3}
                            className={FIELD_CLASS} data-testid="group-settings-description"
                            onChange={(event) => { setProfileError(''); setDraft((current) => current && { ...current, description: event.target.value }); }} />
                    </label>
                    <div className="flex flex-wrap items-center gap-3">
                        <label className="flex items-center gap-2 text-xs font-medium text-text-2">
                            Colour
                            <input type="color" value={draft.hero_color} disabled={!canEditColor} aria-label="Group colour"
                                className="h-8 w-12 cursor-pointer rounded border border-edge bg-surface-1 disabled:opacity-60"
                                data-testid="group-settings-color"
                                onChange={(event) => { setProfileError(''); setDraft((current) => current && { ...current, hero_color: event.target.value }); }} />
                        </label>
                        <span className="inline-flex items-center gap-2 rounded-lg border border-edge px-3 py-1.5 text-xs text-text-2"
                            data-testid="group-settings-preview">
                            <span aria-hidden="true" className="h-4 w-4 rounded-full" style={{ backgroundColor: draft.hero_color }} />
                            <span className="min-w-0 break-words">{draft.name || 'Group name'}</span>
                        </span>
                    </div>
                    {profileError ? <p role="alert" className="text-xs text-danger">{profileError}</p> : null}
                    {canEditProfile ? (
                        <div className="flex justify-end">
                            <GlassButton variant="primary" size="sm" disabled={disabled || !profileDirty}
                                onClick={() => void saveProfile()} data-testid="group-settings-save-profile">
                                {profileBusy ? <Loader2 size={14} className="animate-spin" /> : null}
                                Save profile
                            </GlassButton>
                        </div>
                    ) : null}
                </fieldset>
            </GlassPanel>

            <GlassPanel className="space-y-3 p-4">
                <div className="flex items-baseline justify-between gap-3">
                    <h3 className="text-sm font-semibold text-text-1">Logo</h3>
                    {!canEditLogo && logoReason ? <span className="text-xs text-text-3">{logoReason}</span> : null}
                </div>
                <div className="flex flex-wrap items-center gap-3">
                    <span className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-lg border bg-surface-1"
                        style={{ borderColor: draft.hero_color }}>
                        {logo.has_logo && logo.logo_url ? (
                            <img src={logo.logo_url} alt="" className="h-full w-full object-contain" />
                        ) : <ImageIcon size={20} className="text-text-2" />}
                    </span>
                    {canEditLogo ? (
                        <div className="flex flex-wrap items-center gap-2">
                            <input ref={fileInputRef} type="file" accept="image/png,image/jpeg" className="hidden"
                                data-testid="group-settings-logo-input"
                                onChange={(event) => {
                                    const file = event.target.files?.[0];
                                    if (file) void uploadLogo(file);
                                    event.target.value = '';
                                }} />
                            <GlassButton size="sm" disabled={disabled} onClick={() => fileInputRef.current?.click()}
                                data-testid="group-settings-logo-upload">
                                {logoBusy ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
                                {logo.has_logo ? 'Replace logo' : 'Upload logo'}
                            </GlassButton>
                            {logo.has_logo ? (
                                <GlassButton size="sm" variant="ghost" disabled={disabled} onClick={() => void removeLogo()}
                                    data-testid="group-settings-logo-remove">
                                    <Trash2 size={14} />Remove
                                </GlassButton>
                            ) : null}
                            {pendingLogo ? (
                                <GlassButton size="sm" variant="primary" disabled={disabled}
                                    onClick={() => void uploadLogo(pendingLogo)}
                                    data-testid="group-settings-logo-retry">
                                    Retry upload
                                </GlassButton>
                            ) : null}
                        </div>
                    ) : <span className="text-xs text-text-3">PNG or JPEG, set by a group manager.</span>}
                </div>
                {logoError ? <p role="alert" className="text-xs text-danger">{logoError}</p> : null}
            </GlassPanel>

            {settings.downloads ? (
                <GlassPanel className="space-y-3 p-4" data-testid="group-settings-downloads">
                    <h3 className="text-sm font-semibold text-text-1">File downloads</h3>
                    <label className="flex items-start gap-2.5">
                        <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--accent)]"
                            checked={settings.downloads.disable_file_downloads} disabled={disabled || !canEditDownloads}
                            data-testid="group-settings-downloads-toggle"
                            onChange={(event) => void saveDownloads(event.target.checked)} />
                        <span className="min-w-0">
                            <span className="block text-sm text-text-1">Turn off file downloads for this group</span>
                            <span className="block text-xs text-text-3">
                                Members can still read documents in chat; they cannot download the original files.
                            </span>
                        </span>
                    </label>
                    {!canEditDownloads && downloadsReason ? <p className="text-xs text-text-3">{downloadsReason}</p> : null}
                    {downloadsBusy ? <p role="status" className="text-xs text-text-3">Saving...</p> : null}
                    {downloadsError ? <p role="alert" className="text-xs text-danger">{downloadsError}</p> : null}
                </GlassPanel>
            ) : null}

            {settings.retention && retentionDraft ? (
                <GlassPanel className="space-y-3 p-4" data-testid="group-settings-retention">
                    <div className="flex items-baseline justify-between gap-3">
                        <h3 className="text-sm font-semibold text-text-1">Retention</h3>
                        {!canEditRetention && retentionReason ? <span className="text-xs text-text-3">{retentionReason}</span> : null}
                    </div>
                    <p className="text-xs text-text-3">
                        Days to keep conversations and documents. Use "none" to keep them indefinitely, or "default" to
                        follow the organization policy ({settings.retention.organization_defaults.conversation_retention_days} /
                        {' '}{settings.retention.organization_defaults.document_retention_days} days).
                    </p>
                    <fieldset disabled={disabled || !canEditRetention} className="min-w-0 grid gap-3 sm:grid-cols-2">
                        <label className="block text-xs font-medium text-text-2">
                            Conversations
                            <input type="text" value={retentionDraft.conversation} className={FIELD_CLASS}
                                data-testid="group-settings-retention-conversation"
                                onChange={(event) => { setRetentionError(''); setRetentionDraft((current) => current && { ...current, conversation: event.target.value }); }} />
                        </label>
                        <label className="block text-xs font-medium text-text-2">
                            Documents
                            <input type="text" value={retentionDraft.document} className={FIELD_CLASS}
                                data-testid="group-settings-retention-document"
                                onChange={(event) => { setRetentionError(''); setRetentionDraft((current) => current && { ...current, document: event.target.value }); }} />
                        </label>
                    </fieldset>
                    {retentionError ? <p role="alert" className="text-xs text-danger">{retentionError}</p> : null}
                    {canEditRetention ? (
                        <div className="flex justify-end">
                            <GlassButton variant="primary" size="sm" disabled={disabled}
                                onClick={() => void saveRetention()} data-testid="group-settings-save-retention">
                                {retentionBusy ? <Loader2 size={14} className="animate-spin" /> : null}
                                Save retention
                            </GlassButton>
                        </div>
                    ) : null}
                </GlassPanel>
            ) : null}

            {adapter.allows('view_file_count') ? (
                <GlassPanel elevation="flat" className="space-y-3 border border-danger/30 p-4" data-testid="group-settings-danger">
                    <h3 className="text-sm font-semibold text-danger">Delete this group</h3>
                    <p className="text-xs text-text-3">
                        Deleting a group removes its members' access and its shared workspace. This still happens on the
                        classic group page, where the prerequisites are checked.
                    </p>
                    <p className="text-xs text-text-2" data-testid="group-settings-file-count">
                        {fileCountError
                            ? fileCountError
                            : fileCount === null
                                ? 'Counting the group\u2019s documents...'
                                : `This group holds ${fileCount} document${fileCount === 1 ? '' : 's'}. Remove them before deleting the group.`}
                    </p>
                    <GlassButton size="sm" variant="ghost" disabled={disabled}
                        onClick={() => setDeleteOpen(true)} data-testid="group-settings-delete">
                        Delete group (classic)<ArrowUpRight size={14} />
                    </GlassButton>
                </GlassPanel>
            ) : null}

            {deleteOpen ? (
                <ConfirmDialog title="Delete this group in classic?"
                    description="Deleting a group is permanent and is completed on the classic group page. You'll be taken there to confirm the prerequisites."
                    confirmLabel="Open classic" tone="danger"
                    onConfirm={() => { setDeleteOpen(false); onOpenClassic(); }}
                    onClose={() => setDeleteOpen(false)} />
            ) : null}
        </div>
    );
}
