// IdentityWorkbenchSection.tsx
// Scope-aware credential authoring. Each adapter supplies its authorization gates and transport.

import { useCallback, useMemo, useRef, useState } from 'react';
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
    authTypeLabel,
    GROUP_IDENTITY_CAPABILITIES,
    IDENTITY_REBASE_FIELDS,
    type IdentityDraft,
} from '../../lib/identityFields';
import { rebaseDraft, rebaseNotice, REBASE_DELETED_NOTICE } from '../../lib/rebaseDraft';
import { ApiError } from '../../lib/apiClient';
import { toast } from '../../stores/toastStore';
import type { WorkspaceIdentity } from '../../lib/types';

interface DeleteBlock {
    name: string;
    references: IdentityReference[];
}

export function IdentityWorkbenchSection({
    adapter,
    syncEnabled,
    actionsEnabled,
    scopeNoun = 'group',
    connectorSurfaces = 'file sources and actions',
    identityCapabilities = GROUP_IDENTITY_CAPABILITIES,
}: {
    adapter: IdentityWorkbenchAdapter;
    syncEnabled: boolean;
    actionsEnabled: boolean;
    // Scope-specific copy so a public workspace reuses this section verbatim: 'group' keeps the
    // shipped group wording byte-identical, while a public workspace passes 'workspace' and the
    // narrower connector surface it actually feeds. Everything else -- reads, gates, dialogs and
    // conflict handling -- is scope-agnostic and comes from the adapter.
    scopeNoun?: string;
    connectorSurfaces?: string;
    // Which capabilities the editor's "Used for" picker offers. Defaults to the full group set so
    // the group editor stays byte-identical; a public workspace passes only 'file_sync' because it
    // has no actions surface, so the picker never offers a capability the workspace cannot feed.
    identityCapabilities?: readonly (typeof GROUP_IDENTITY_CAPABILITIES)[number][];
}) {
    const load = useCallback((signal: AbortSignal) => adapter.list(signal), [adapter]);
    const { items, loading, error, loadFailed, refresh, setItems, setError } =
        useSectionResource<WorkspaceIdentity>(load, 'Failed to load identities.');

    const [query, setQuery] = useState('');
    const [busyId, setBusyId] = useState<string | null>(null);
    const [draft, setDraft] = useState<IdentityDraft | null>(null);
    // Keep both the draft baseline and its version until an explicit conflict rebase.
    const [baseline, setBaseline] = useState<IdentityDraft | null>(null);
    const [editingIdentity, setEditingIdentity] = useState<WorkspaceIdentity | null>(null);
    const [deleted, setDeleted] = useState(false);
    const [saving, setSaving] = useState(false);
    const savingRef = useRef(false);
    const [saveError, setSaveError] = useState<string | null>(null);
    // A conditional-write conflict on a shared identity: the draft stays open and a refresh is
    // offered rather than the edit being lost.
    const [saveConflict, setSaveConflict] = useState(false);
    const [deleteBlock, setDeleteBlock] = useState<DeleteBlock | null>(null);

    const canCreate = adapter.allows('create');
    const personal = adapter.scope.kind === 'personal';

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
            return `Saved for this ${scopeNoun}’s connectors.`;
        }
        return `Used by ${surfaces.join(' and ')} in this ${scopeNoun}.`;
    }, [syncEnabled, actionsEnabled, scopeNoun]);

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
        if (savingRef.current) return;
        setSaveError(null);
        setSaveConflict(false);
        const next = identity ? draftFromIdentity(identity) : emptyIdentityDraft();
        if (!identity) {
            // Constrain a new draft to the capabilities this workspace actually feeds. The group set
            // keeps the shipped 'action' default; a public workspace's 'file_sync'-only set replaces
            // it so the create never proposes a capability the workspace has no surface for.
            const allowed = next.capabilities.filter((capability) =>
                (identityCapabilities as readonly string[]).includes(capability),
            );
            next.capabilities = allowed.length ? allowed : [...identityCapabilities];
        }
        setDraft(next);
        setBaseline(identity ? draftFromIdentity(identity) : null);
        setEditingIdentity(identity);
        setDeleted(false);
    };

    const resetEditor = () => {
        setDraft(null);
        setBaseline(null);
        setSaveError(null);
        setSaveConflict(false);
        setEditingIdentity(null);
        setDeleted(false);
    };
    const closeEditor = () => {
        if (!savingRef.current) resetEditor();
    };

    const onSave = async () => {
        if (!draft || savingRef.current || deleted) {
            return;
        }
        savingRef.current = true;
        setSaving(true);
        setSaveError(null);
        setSaveConflict(false);
        try {
            const write = buildIdentityWrite(draft);
            let saved: WorkspaceIdentity;
            if (draft.id) {
                // Use the version the editor opened, not a separately refreshed list's token.
                if (!editingIdentity) {
                    throw new Error('This identity is no longer available. Refresh and try again.');
                }
                saved = await adapter.update(editingIdentity, write);
            } else {
                saved = await adapter.create(write);
            }
            setItems(draft.id ? items.map((item) => item.id === saved.id ? saved : item) : [...items, saved]);
            resetEditor();
            await refresh();
            toast.success(draft.id ? 'Identity saved' : 'Identity created');
        } catch (writeError) {
            if (writeError instanceof IdentityConflictError) {
                // Only an explicit refresh/rebase adopts the other writer's version.
                setSaveConflict(true);
                setSaveError(writeError.message);
            } else if (writeError instanceof ApiError && writeError.status === 404 && draft.id) {
                setDeleted(true);
                setSaveError(REBASE_DELETED_NOTICE);
            } else {
                // Any other failure, including the server's reviewed 400 validation messages, is
                // shown verbatim and the draft is kept so the fields are not lost.
                setSaveError(errorMessage(writeError, 'Could not save the identity.'));
            }
        } finally {
            savingRef.current = false;
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
                setDeleted(true);
                setSaveConflict(false);
                setSaveError(REBASE_DELETED_NOTICE);
                return;
            }
            const freshDraft = draftFromIdentity(current);
            const { draft: rebased, conflicts } = rebaseDraft(baseline, freshDraft, draft, IDENTITY_REBASE_FIELDS);
            setDraft(rebased);
            setBaseline(freshDraft);
            setEditingIdentity(current);
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
                    description={personal
                        ? 'Sign-in details you save once and reuse. These are credentials for the systems you connect to, not your own account. Secrets are held server-side and never sent back to the browser.'
                        : `Sign-in details this ${scopeNoun} saves once and reuses. These are credentials for the systems the ${scopeNoun} connects to, not a member's own account. Secrets are held server-side and never sent back to the browser.`}
                />
                {canCreate ? (
                    <GlassButton variant="primary" size="sm" disabled={saving} onClick={() => openEditor(null)}>
                        <Plus size={14} />
                        New identity
                    </GlassButton>
                ) : null}
            </div>

            <p className="text-xs text-text-3">
                {usedByText}
                {canCreate
                    ? ` Create one here to reuse it across the ${scopeNoun}’s ${connectorSurfaces}.`
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
                loadFailed={loadFailed}
                onRetry={() => void refresh()}
                retryLabel="Retry identities"
                emptyIcon={<KeyRound size={28} />}
                emptyTitle={items.length === 0 ? 'No identities yet' : 'No identities match your search'}
                emptyDescription={
                    items.length === 0
                        ? canCreate
                            ? `Save a credential here to reuse it across the ${scopeNoun}’s ${connectorSurfaces}.`
                            : `This ${scopeNoun} has no shared identities yet. A workspace manager can add one.`
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
                    capabilities={identityCapabilities}
                    scopeDescription={personal ? 'your workspace' : `this ${scopeNoun}`}
                    saveDisabled={deleted}
                />
            ) : null}
        </div>
    );
}
