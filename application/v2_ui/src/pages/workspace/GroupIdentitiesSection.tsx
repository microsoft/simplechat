// GroupIdentitiesSection.tsx
// The group workspace identities section: shared saved credentials a group reuses across its file
// sources and actions.
//
// This mirrors the personal IdentitiesSection's list, but adds the writes a group manager can make
// natively -- create, edit and delete -- through the scope-aware identityWorkbench adapter. Reading
// and every gate come from that adapter: the New control appears only when the workspace advertises
// creation, and a row's Edit and Delete appear only when the row itself carries the operation, so a
// member sees a read-only list. Writing happens in a dialog. Two conflicts are handled honestly: a
// stale-etag save keeps the draft open and offers a refresh rather than losing the edit, and a
// delete refused because the identity is still referenced names what still uses it instead of
// failing silently.

import { useCallback, useMemo, useState } from 'react';
import { KeyRound, Pencil, Plus, Trash2 } from 'lucide-react';
import {
    ConfirmAction,
    Pill,
    ResourceRow,
    RowAction,
    SectionIntro,
    SectionList,
    SectionSearch,
} from '../../components/workspace/primitives';
import { GlassButton } from '../../components/ui/primitives';
import { errorMessage, useSectionResource } from '../../components/workspace/useSectionResource';
import { IdentityEditorDialog } from '../../components/identities/IdentityEditorDialog';
import {
    IdentityConflictError,
    IdentityInUseError,
    type IdentityReference,
    type IdentityWorkbenchAdapter,
} from '../../lib/identityWorkbench';
import {
    buildIdentityWrite,
    draftFromIdentity,
    emptyIdentityDraft,
    identityAuthType,
    identityCapabilityLabels,
    identityPrincipalText,
    IDENTITY_REBASE_FIELDS,
    type IdentityDraft,
} from '../../lib/identityFields';
import { rebaseDraft, rebaseNotice, REBASE_DELETED_NOTICE } from '../../lib/rebaseDraft';
import { authTypeLabel } from './IdentitiesSection';
import { toast } from '../../stores/toastStore';
import type { WorkspaceIdentity } from '../../lib/types';

interface DeleteBlock {
    name: string;
    references: IdentityReference[];
}

export function GroupIdentitiesSection({
    adapter,
    syncEnabled,
    actionsEnabled,
}: {
    adapter: IdentityWorkbenchAdapter;
    syncEnabled: boolean;
    actionsEnabled: boolean;
}) {
    const load = useCallback((signal: AbortSignal) => adapter.list(signal), [adapter]);
    const { items, loading, error, refresh, setItems, setError } =
        useSectionResource<WorkspaceIdentity>(load, 'Failed to load identities.');

    const [query, setQuery] = useState('');
    const [busyId, setBusyId] = useState<string | null>(null);
    const [draft, setDraft] = useState<IdentityDraft | null>(null);
    // The identity as the editor loaded it, so a conflict reload can tell the user's edits from the
    // other writer's. Set only for an edit; a new identity cannot conflict.
    const [baseline, setBaseline] = useState<IdentityDraft | null>(null);
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState<string | null>(null);
    // A conditional-write conflict on a shared identity: the draft stays open and a refresh is
    // offered rather than the edit being lost.
    const [saveConflict, setSaveConflict] = useState(false);
    const [deleteBlock, setDeleteBlock] = useState<DeleteBlock | null>(null);

    const canCreate = adapter.allows('create');

    // Which SimpleChat capabilities this group's identities feed, named honestly from the two
    // section flags rather than a decorative constant, so the copy reflects what is actually enabled.
    const usedByText = useMemo(() => {
        const surfaces: string[] = [];
        if (syncEnabled) {
            surfaces.push('file sources');
        }
        if (actionsEnabled) {
            surfaces.push('actions');
        }
        if (surfaces.length === 0) {
            return 'Saved for this group’s connectors.';
        }
        return `Used by ${surfaces.join(' and ')} in this group.`;
    }, [syncEnabled, actionsEnabled]);

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) {
            return items;
        }
        return items.filter((identity) =>
            `${identity.name ?? ''} ${identityPrincipalText(identity)}`.toLowerCase().includes(needle),
        );
    }, [items, query]);

    const openEditor = (identity: WorkspaceIdentity | null) => {
        setSaveError(null);
        setSaveConflict(false);
        setDraft(identity ? draftFromIdentity(identity) : emptyIdentityDraft());
        setBaseline(identity ? draftFromIdentity(identity) : null);
    };

    const closeEditor = () => {
        setDraft(null);
        setBaseline(null);
        setSaveError(null);
        setSaveConflict(false);
    };

    const onSave = async () => {
        if (!draft) {
            return;
        }
        setSaving(true);
        setSaveError(null);
        setSaveConflict(false);
        try {
            const write = buildIdentityWrite(draft);
            if (draft.id) {
                // The etag rides on the current list row, so a save retried after a refresh picks
                // up the fresh marker without the draft having to carry it.
                const current = items.find((identity) => identity.id === draft.id);
                if (!current) {
                    throw new Error('This identity is no longer available. Refresh and try again.');
                }
                await adapter.update(current, write);
            } else {
                await adapter.create(write);
            }
            closeEditor();
            await refresh();
            toast.success(draft.id ? 'Identity saved' : 'Identity created');
        } catch (writeError) {
            if (writeError instanceof IdentityConflictError) {
                // Keep the draft open. The refresh button reloads the list, which brings the new
                // etag, and saving again applies the edit on top of it.
                setSaveConflict(true);
                setSaveError(writeError.message);
            } else {
                // Any other failure, including the server's reviewed 400 validation messages, is
                // shown verbatim and the draft is kept so the fields are not lost.
                setSaveError(errorMessage(writeError, 'Could not save the identity.'));
            }
        } finally {
            setSaving(false);
        }
    };

    const onConflictRefresh = async () => {
        if (!draft?.id || !baseline) {
            setSaveConflict(false);
            setSaveError(null);
            await refresh();
            return;
        }
        try {
            const fresh = await adapter.list(new AbortController().signal);
            setItems(fresh);
            const current = fresh.find((identity) => identity.id === draft.id) ?? null;
            if (!current) {
                setSaveConflict(false);
                setSaveError(REBASE_DELETED_NOTICE);
                return;
            }
            const freshDraft = draftFromIdentity(current);
            const { draft: rebased, conflicts } = rebaseDraft(baseline, freshDraft, draft, IDENTITY_REBASE_FIELDS);
            setDraft(rebased);
            setBaseline(freshDraft);
            setSaveConflict(false);
            setSaveError(rebaseNotice(conflicts));
        } catch (reloadError) {
            setSaveError(errorMessage(reloadError, 'Could not reload the latest version.'));
        }
    };

    const onDelete = async (identity: WorkspaceIdentity) => {
        const previous = items;
        setBusyId(identity.id);
        setError(null);
        setDeleteBlock(null);
        setItems(items.filter((item) => item.id !== identity.id));
        try {
            await adapter.remove(identity);
            toast.success('Identity deleted');
        } catch (deleteError) {
            setItems(previous);
            if (deleteError instanceof IdentityInUseError) {
                // Name what still uses the identity instead of failing silently.
                setDeleteBlock({
                    name: String(identity.name ?? 'identity'),
                    references: deleteError.references,
                });
                setError(deleteError.message);
            } else {
                setError(errorMessage(deleteError, 'Could not delete the identity.'));
            }
        } finally {
            setBusyId(null);
        }
    };

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <SectionIntro
                    title="Identities"
                    description="Sign-in details this group saves once and reuses. These are credentials for the systems the group connects to, not a member's own account. Secrets are held server-side and never sent back to the browser."
                />
                {canCreate ? (
                    <GlassButton variant="primary" size="sm" onClick={() => openEditor(null)}>
                        <Plus size={14} />
                        New identity
                    </GlassButton>
                ) : null}
            </div>

            <p className="text-xs text-text-3">
                {usedByText}
                {canCreate
                    ? ' Create one here to reuse it across the group’s file sources and actions.'
                    : ' A workspace manager can add one.'}
            </p>

            {deleteBlock ? (
                <div className="alert alert-warning space-y-1 rounded-xl bg-warn-soft p-3 text-sm text-warn" role="alert">
                    <p className="font-medium">
                        “{deleteBlock.name}” is still in use, so it was not deleted.
                    </p>
                    {deleteBlock.references.length ? (
                        <ul className="list-disc space-y-0.5 pl-5 text-xs">
                            {deleteBlock.references.map((reference) => (
                                <li key={`${reference.kind}:${reference.id}`}>
                                    {reference.name || reference.id}
                                    <span className="text-text-3"> ({reference.kind})</span>
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p className="text-xs">Remove the references, then delete it again.</p>
                    )}
                </div>
            ) : null}

            <SectionSearch value={query} onChange={setQuery} placeholder="Search identities" />

            <SectionList
                items={visible}
                loading={loading}
                error={deleteBlock ? null : error}
                emptyIcon={<KeyRound size={28} />}
                emptyTitle={items.length === 0 ? 'No identities yet' : 'No identities match your search'}
                emptyDescription={
                    items.length === 0
                        ? canCreate
                            ? 'Save a credential here to reuse it across the group’s file sources and actions.'
                            : 'This group has no shared identities yet. A workspace manager can add one.'
                        : undefined
                }
                getKey={(identity, index) => String(identity.id ?? index)}
                renderItem={(identity) => {
                    const canEdit = adapter.allows('edit', identity);
                    const canDelete = adapter.allows('delete', identity);
                    return (
                        <ResourceRow
                            icon={<KeyRound size={17} />}
                            title={String(identity.name ?? 'Untitled identity')}
                            subtitle={identityPrincipalText(identity) || String(identity.description ?? '')}
                            meta={
                                <>
                                    <Pill>{authTypeLabel(identityAuthType(identity))}</Pill>
                                    {identityCapabilityLabels(identity).map((label) => (
                                        <Pill key={label} tone="accent">
                                            {label}
                                        </Pill>
                                    ))}
                                </>
                            }
                            actions={
                                <>
                                    {canEdit ? (
                                        <RowAction
                                            icon={<Pencil size={15} />}
                                            label={`Edit ${identity.name ?? 'identity'}`}
                                            onClick={() => openEditor(identity)}
                                        />
                                    ) : null}
                                    {canDelete ? (
                                        <ConfirmAction
                                            icon={<Trash2 size={15} />}
                                            label={`Delete ${identity.name ?? 'identity'}`}
                                            confirmLabel="Delete"
                                            busy={busyId === identity.id}
                                            onConfirm={() => void onDelete(identity)}
                                        />
                                    ) : null}
                                </>
                            }
                        />
                    );
                }}
            />

            {draft ? (
                <IdentityEditorDialog
                    draft={draft}
                    saving={saving}
                    error={saveError}
                    onChange={setDraft}
                    onSave={() => void onSave()}
                    onRefresh={saveConflict ? () => void onConflictRefresh() : undefined}
                    onCancel={closeEditor}
                />
            ) : null}
        </div>
    );
}
