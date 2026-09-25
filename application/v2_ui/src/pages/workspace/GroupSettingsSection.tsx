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
import { ArrowUpRight, Image as ImageIcon, Loader2, Trash2, Upload, Users } from 'lucide-react';
import { EmptyState, GlassButton, GlassPanel, Skeleton } from '../../components/ui/primitives';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { SectionIntro } from '../../components/workspace/primitives';
import { codePointLength } from '../../lib/groupDirectory';
import { rebaseDraft, rebaseNotice, type RebaseField } from '../../lib/rebaseDraft';
import { ApiError } from '../../lib/apiClient';
import {
    GroupLogoMissingError, GroupSettingsChangedError, GroupSettingsWriteConflictError,
    groupSettingsReasonText,
    type GroupProfileChanges, type GroupRetentionBounds, type GroupRetentionValue,
    type GroupSettings, type GroupSettingsAdapter, type GroupSettingsManagement,
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

/** A retention value shown in a select: a number of days, or the words the server accepts. */
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

/** Turn a chosen select value back into the value the server stores. */
function retentionFromSelect(raw: string): GroupRetentionValue {
    if (raw === 'none' || raw === 'default') {
        return raw;
    }
    return Number(raw);
}

// The classic day choices (group_workspaces.html), so the native control offers exactly the same
// periods rather than a free-text field the server would then reject.
const RETENTION_DAY_OPTIONS = [7, 14, 30, 60, 90, 180, 365, 730, 1095, 3650] as const;
const RETENTION_DAY_LABELS: Record<number, string> = {
    7: '7 days (1 week)',
    14: '14 days (2 weeks)',
    30: '30 days (1 month)',
    60: '60 days (2 months)',
    90: '90 days (3 months)',
    180: '180 days (6 months)',
    365: '365 days (1 year)',
    730: '730 days (2 years)',
    1095: '1095 days (3 years)',
    3650: '3650 days (10 years)',
};

/** The label for one day choice, reusing the classic wording where it exists. */
function retentionDayLabel(days: number): string {
    return RETENTION_DAY_LABELS[days] || `${days} days`;
}

/** The label for an organization default, which the server reports as days or "none". */
function orgDefaultLabel(value: number | 'none'): string {
    return value === 'none' ? 'no automatic deletion' : retentionDayLabel(value);
}

/**
 * The choices one retention select offers: the two policy words, then the classic day options that
 * fall within the server's bounds. The currently stored value is always kept selectable, even when
 * it now sits outside the bounds, so opening the editor never silently rewrites it.
 */
function retentionChoices(current: string, stored: string, bounds: GroupRetentionBounds): { value: string; label: string }[] {
    const choices = [
        { value: 'default', label: 'Using organization default' },
        { value: 'none', label: 'No automatic deletion' },
    ];
    const days = RETENTION_DAY_OPTIONS.filter((option) => option >= bounds.min_days && option <= bounds.max_days) as number[];
    // Keep both the open draft value and the stored value selectable, even when either now sits
    // outside the bounds, so editing the other field never drops a value the server still holds.
    for (const value of [current, stored]) {
        const numeric = Number(value);
        if (value !== 'default' && value !== 'none' && Number.isInteger(numeric) && !days.includes(numeric)) {
            days.push(numeric);
        }
    }
    days.sort((left, right) => left - right);
    for (const option of days) {
        choices.push({ value: String(option), label: retentionDayLabel(option) });
    }
    return choices;
}

const FIELD_CLASS =
    'mt-1 w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60';

export function GroupSettingsSection({
    adapter, management, interactionDisabled, onBusyChange, onDirtyChange, onAccessChanged, onSaved, onOpenClassic,
}: {
    adapter: GroupSettingsAdapter;
    /**
     * The latest `settings_management` hint from the workspace context. The section gates its controls
     * from the freshest hint it holds -- the last read or write when one has landed, otherwise this --
     * so a refused or re-read context re-gates without the adapter (kept stable per group) rebuilding
     * and discarding the open drafts.
     */
    management: GroupSettingsManagement | undefined;
    /** True while the workspace context is being re-confirmed; every write waits for it. */
    interactionDisabled: boolean;
    onBusyChange: (busy: boolean) => void;
    onDirtyChange: (dirty: boolean) => void;
    /** Re-read the workspace context after a refusal that means the caller's own standing changed. */
    onAccessChanged: () => void;
    /** Re-read the workspace context after a successful profile or logo save, so the header follows. */
    onSaved: () => void;
    /** Open the classic group page for the delete flow classic still owns. */
    onOpenClassic: () => void;
}) {
    const [settings, setSettings] = useState<GroupSettings | null>(null);
    // The freshest settings_management hint the section holds: the last read or write when one has
    // landed, otherwise the context's, adopted whenever the context revalidates. Gating reads this,
    // never the adapter (which stays stable per group), so a re-read re-gates without touching drafts.
    const [gate, setGate] = useState<GroupSettingsManagement | undefined>(management);
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
    const onSavedRef = useRef(onSaved);
    onSavedRef.current = onSaved;

    // Adopt the context's hint whenever it revalidates. On a plain refocus the new hint is content-equal
    // and this is a no-op for the controls; after a refused write re-reads the context it carries the
    // caller's changed standing, which re-gates the controls read-only. Either way the drafts are untouched.
    useEffect(() => { if (management) setGate(management); }, [management]);

    // Replace the section's settings and adopt the fresher hint that every read and write carries.
    const applySettings = useCallback((next: GroupSettings) => {
        setSettings(next);
        setGate(next.settings_management);
    }, []);

    const gateOperations = useMemo(() => new Set(gate?.operations ?? []), [gate]);
    const allows = useCallback((operation: string) => gateOperations.has(operation), [gateOperations]);
    const reason = useCallback((operation: string) => (gate?.reasons ?? {})[operation], [gate]);

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
                setGate(next.settings_management);
                setDraft(profileDraftOf(next));
                setRetentionDraft(retentionDraftOf(next));
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
        if (!settings || !allows('view_file_count')) {
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
    }, [adapter, settings, allows]);

    const profileDirty = useMemo(() => {
        if (!settings || !draft) return false;
        const base = profileDraftOf(settings);
        return draft.name !== base.name || draft.description !== base.description || draft.hero_color !== base.hero_color;
    }, [settings, draft]);
    const retentionDirty = useMemo(() => {
        if (!settings || !retentionDraft) return false;
        const base = retentionDraftOf(settings);
        return !!base && (retentionDraft.conversation !== base.conversation || retentionDraft.document !== base.document);
    }, [settings, retentionDraft]);

    const reload = useCallback(() => setReloadToken((value) => value + 1), []);

    const canEditName = allows('edit_name');
    const canEditDescription = allows('edit_description');
    const canEditColor = allows('edit_color');
    const canEditLogo = allows('edit_logo');
    const canEditProfile = canEditName || canEditDescription || canEditColor;
    const canEditDownloads = allows('edit_downloads');
    const canEditRetention = allows('edit_retention');

    // Only a draft the viewer can still save counts toward the leave guard and the downloads freeze.
    // When a lock or a demotion withdraws an editor's operations its now read-only draft is dropped
    // from the guard, so the picker frees and the downloads switch follows only its own gate; a Discard
    // control stays available to clear the stranded draft.
    const editorDirty = (canEditProfile && profileDirty) || (canEditRetention && retentionDirty);
    useEffect(() => { onDirtyChangeRef.current(editorDirty); }, [editorDirty]);

    const profileReason = groupSettingsReasonText(
        reason('edit_name') || reason('edit_description') || reason('edit_color'),
    );
    const logoReason = groupSettingsReasonText(reason('edit_logo'));
    const downloadsReason = groupSettingsReasonText(reason('edit_downloads'));
    const retentionReason = groupSettingsReasonText(reason('edit_retention'));

    /**
     * Bring a refusal or conflict to the state the server holds, per the code it carries, and report
     * whether the caller must re-read the workspace context. A write-guard exhaustion keeps the draft
     * for a plain retry; a stale section revision rebases the draft over a fresh read; a 400 validation
     * error, a 5xx or a network failure keeps every field and just shows the message; only a 403 (the
     * caller's standing changed) or a 404 (the group is gone) asks for a context re-read, and even then
     * the open section's drafts are kept so a re-gate disables the controls without discarding edits.
     */
    const settleWrite = useCallback(async (
        cause: unknown, setError: (message: string) => void, baseline: GroupSettings,
    ): Promise<boolean> => {
        const message = cause instanceof Error ? cause.message : 'The change could not be saved. Please retry.';
        setError(message);
        if (cause instanceof GroupSettingsWriteConflictError) {
            // Nothing changed: the state is kept so the same action can simply be retried.
            return false;
        }
        if (cause instanceof GroupSettingsChangedError) {
            // A stale section revision: reload the settings and rebase the drafts over the fresh copy,
            // so a concurrent change to another field never discards the user's in-progress edits.
            try {
                const fresh = await adapter.readSettings();
                applySettings(fresh);
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
            return false;
        }
        // A 403 (standing changed) or 404 (group gone) re-reads the context; every other failure --
        // a 400 validation error, a 5xx, or a network error -- keeps all state and only shows the message.
        const status = cause instanceof ApiError ? cause.status : 0;
        return status === 403 || status === 404;
    }, [adapter, applySettings, reload]);

    /**
     * Settle a logo write, which is never auto-retried, and report whether the context must be re-read.
     * A stale-revision or already-gone conflict reloads the settings so the fresh logo shows, and a
     * write-guard exhaustion keeps the state as it is; a 400, 5xx or network error keeps everything and
     * shows the message; only a 403 or 404 asks for a context re-read. The chosen file is kept for an
     * explicit retry except when access is refused. The profile draft is untouched throughout, because
     * a logo write carries none of its fields.
     */
    const settleLogoWrite = useCallback(async (cause: unknown, file: File | null): Promise<boolean> => {
        const message = cause instanceof Error ? cause.message : 'The logo could not be saved. Please retry.';
        setLogoError(message);
        if (cause instanceof GroupSettingsWriteConflictError) {
            setPendingLogo(file);
            return false;
        }
        if (cause instanceof GroupSettingsChangedError || cause instanceof GroupLogoMissingError) {
            setPendingLogo(file);
            try {
                applySettings(await adapter.readSettings());
            } catch {
                reload();
            }
            return false;
        }
        const status = cause instanceof ApiError ? cause.status : 0;
        if (status === 403 || status === 404) {
            setPendingLogo(null);
            return true;
        }
        // A 400, 5xx or network error: keep the chosen file so the upload can be retried explicitly.
        setPendingLogo(file);
        return false;
    }, [adapter, applySettings, reload]);

    // Re-read the workspace context after a refusal, clearing the page-facing busy flag first. The
    // busy state only reaches the page through an effect a render later, and the page gates its
    // revalidate on that flag; clearing it synchronously here (as the Members section does before it
    // refuses) is what lets the re-read actually run so the controls re-gate.
    const reReadContext = useCallback(() => {
        onBusyChangeRef.current(false);
        onAccessChangedRef.current();
    }, []);

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
        let refused = false;
        try {
            const next = await adapter.updateProfile(changes, settings.profile.revision);
            applySettings(next);
            setDraft(profileDraftOf(next));
            setNotice({ tone: 'status', text: 'Group profile saved.' });
            onSavedRef.current();
        } catch (cause) {
            refused = await settleWrite(cause, setProfileError, settings);
        } finally {
            setProfileBusy(false);
        }
        if (refused) reReadContext();
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
        let refused = false;
        try {
            const next = await adapter.replaceLogo(file, settings.logo.revision);
            applySettings(next);
            setPendingLogo(null);
            setNotice({ tone: 'status', text: 'Group logo updated.' });
            onSavedRef.current();
        } catch (cause) {
            refused = await settleLogoWrite(cause, file);
        } finally {
            setLogoBusy(false);
        }
        if (refused) reReadContext();
    };

    const removeLogo = async () => {
        if (!settings) return;
        setLogoBusy(true);
        setLogoError('');
        setNotice(null);
        let refused = false;
        try {
            const next = await adapter.removeLogo(settings.logo.revision);
            applySettings(next);
            setPendingLogo(null);
            setNotice({ tone: 'status', text: 'Group logo removed.' });
            onSavedRef.current();
        } catch (cause) {
            refused = await settleLogoWrite(cause, null);
        } finally {
            setLogoBusy(false);
        }
        if (refused) reReadContext();
    };

    const saveDownloads = async (disable: boolean) => {
        if (!settings?.downloads) return;
        setDownloadsBusy(true);
        setDownloadsError('');
        setNotice(null);
        let refused = false;
        try {
            const next = await adapter.updateDownloads(disable, settings.downloads.revision);
            applySettings(next);
            setNotice({ tone: 'status', text: 'File download policy saved.' });
            onSavedRef.current();
        } catch (cause) {
            refused = await settleWrite(cause, setDownloadsError, settings);
        } finally {
            setDownloadsBusy(false);
        }
        if (refused) reReadContext();
    };

    const saveRetention = async () => {
        if (!settings?.retention || !retentionDraft) return;
        const base = retentionDraftOf(settings);
        if (!base) return;
        // Only the changed period is sent: the other field may hold a stored value now outside the
        // bounds, which the server would reject if it were echoed back on an unrelated save.
        const changes: { conversation_retention_days?: GroupRetentionValue; document_retention_days?: GroupRetentionValue } = {};
        if (retentionDraft.conversation !== base.conversation) {
            changes.conversation_retention_days = retentionFromSelect(retentionDraft.conversation);
        }
        if (retentionDraft.document !== base.document) {
            changes.document_retention_days = retentionFromSelect(retentionDraft.document);
        }
        if (Object.keys(changes).length === 0) return;
        setRetentionBusy(true);
        setRetentionError('');
        setNotice(null);
        let refused = false;
        try {
            const next = await adapter.updateRetention(changes, settings.retention.revision);
            applySettings(next);
            setRetentionDraft(retentionDraftOf(next));
            setNotice({ tone: 'status', text: 'Retention policy saved.' });
        } catch (cause) {
            refused = await settleWrite(cause, setRetentionError, settings);
        } finally {
            setRetentionBusy(false);
        }
        if (refused) reReadContext();
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
    const retentionStored = retentionDraftOf(settings);
    // Discard clears a stranded draft -- including one a lock or demotion has just re-gated read-only,
    // where Save is no longer rendered -- by resetting the editor to the stored settings.
    const discardProfile = () => { setProfileError(''); setDraft(profileDraftOf(settings)); };
    const discardRetention = () => { setRetentionError(''); setRetentionDraft(retentionDraftOf(settings)); };

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
                    </div>
                    <div className="rounded-lg border border-edge bg-surface-1 p-3" data-testid="group-settings-preview"
                        aria-label="Group header preview">
                        <p className="mb-2 text-[0.65rem] font-medium uppercase tracking-wide text-text-3">Header preview</p>
                        <div className="flex min-w-0 items-center gap-3">
                            <span className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-lg border bg-surface-1"
                                style={{ borderColor: draft.hero_color }}>
                                {logo.has_logo && logo.logo_url ? (
                                    <img src={logo.logo_url} alt="" className="h-full w-full object-contain" />
                                ) : <Users size={18} className="text-text-2" />}
                            </span>
                            <div className="min-w-0 flex-1">
                                <p className="break-words text-sm font-semibold text-text-1" data-testid="group-settings-preview-name">
                                    {draft.name || 'Group name'}
                                </p>
                                {draft.description.trim()
                                    ? <p className="mt-0.5 line-clamp-2 break-words text-xs text-text-3">{draft.description}</p>
                                    : null}
                            </div>
                        </div>
                    </div>
                    {profileError ? <p role="alert" className="text-xs text-danger">{profileError}</p> : null}
                    {(canEditProfile || profileDirty) ? (
                        <div className="flex justify-end gap-2">
                            {profileDirty ? (
                                <GlassButton variant="ghost" size="sm" disabled={disabled}
                                    onClick={discardProfile} data-testid="group-settings-discard-profile">
                                    Discard changes
                                </GlassButton>
                            ) : null}
                            {canEditProfile ? (
                                <GlassButton variant="primary" size="sm" disabled={disabled || !profileDirty}
                                    onClick={() => void saveProfile()} data-testid="group-settings-save-profile">
                                    {profileBusy ? <Loader2 size={14} className="animate-spin" /> : null}
                                    Save profile
                                </GlassButton>
                            ) : null}
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
                            checked={settings.downloads.disable_file_downloads} disabled={disabled || !canEditDownloads || editorDirty}
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
                        Choose how long conversations and documents are kept. "Using organization default" follows the
                        organization policy ({orgDefaultLabel(settings.retention.organization_defaults.conversation_retention_days)} /
                        {' '}{orgDefaultLabel(settings.retention.organization_defaults.document_retention_days)}); "No automatic
                        deletion" keeps them indefinitely.
                    </p>
                    <fieldset disabled={disabled || !canEditRetention} className="min-w-0 grid gap-3 sm:grid-cols-2">
                        <label className="block text-xs font-medium text-text-2">
                            Conversations
                            <select value={retentionDraft.conversation} className={FIELD_CLASS}
                                data-testid="group-settings-retention-conversation"
                                onChange={(event) => { setRetentionError(''); setRetentionDraft((current) => current && { ...current, conversation: event.target.value }); }}>
                                {retentionChoices(retentionDraft.conversation, retentionStored?.conversation ?? retentionDraft.conversation, settings.retention.bounds.conversation).map((choice) => (
                                    <option key={choice.value} value={choice.value}>{choice.label}</option>
                                ))}
                            </select>
                        </label>
                        <label className="block text-xs font-medium text-text-2">
                            Documents
                            <select value={retentionDraft.document} className={FIELD_CLASS}
                                data-testid="group-settings-retention-document"
                                onChange={(event) => { setRetentionError(''); setRetentionDraft((current) => current && { ...current, document: event.target.value }); }}>
                                {retentionChoices(retentionDraft.document, retentionStored?.document ?? retentionDraft.document, settings.retention.bounds.document).map((choice) => (
                                    <option key={choice.value} value={choice.value}>{choice.label}</option>
                                ))}
                            </select>
                        </label>
                    </fieldset>
                    {retentionError ? <p role="alert" className="text-xs text-danger">{retentionError}</p> : null}
                    {(canEditRetention || retentionDirty) ? (
                        <div className="flex justify-end gap-2">
                            {retentionDirty ? (
                                <GlassButton variant="ghost" size="sm" disabled={disabled}
                                    onClick={discardRetention} data-testid="group-settings-discard-retention">
                                    Discard changes
                                </GlassButton>
                            ) : null}
                            {canEditRetention ? (
                                <GlassButton variant="primary" size="sm" disabled={disabled}
                                    onClick={() => void saveRetention()} data-testid="group-settings-save-retention">
                                    {retentionBusy ? <Loader2 size={14} className="animate-spin" /> : null}
                                    Save retention
                                </GlassButton>
                            ) : null}
                        </div>
                    ) : null}
                </GlassPanel>
            ) : null}

            {allows('view_file_count') ? (
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
