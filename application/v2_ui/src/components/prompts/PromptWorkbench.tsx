// PromptWorkbench.tsx
// The prompts section: a list beside a rendered preview, with writing done in a dialog.
//
// This component owns the query, the selection, the loading and every write. The pieces around
// it are presentational, and the collection rules they share -- what a search matches, what
// order rows come in, what a duplicate is called -- live in lib/promptLibrary.ts so they can be
// tested without a renderer, the same split the documents explorer uses.
//
// Selection survives a refresh by id rather than by index: a prompt renamed to sort differently
// should stay open, and an id that no longer exists should close the pane rather than open
// whatever has taken its place in the list.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { MessageSquareQuote, Plus, Search, X } from 'lucide-react';
import type { WorkspacePrompt } from '../../lib/types';
import {
    createPrompt,
    deletePrompt,
    fetchPrompts,
    updatePrompt,
} from '../../lib/workspaceApi';
import {
    duplicatePromptName,
    isFavoritePrompt,
    promptName,
    visiblePrompts,
    type PromptSort,
} from '../../lib/promptLibrary';
import { errorMessage, useSectionResource } from '../workspace/useSectionResource';
import { toast } from '../../stores/toastStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { EmptyState, GlassButton, Skeleton } from '../ui/primitives';
import { PromptList } from './PromptList';
import { PromptDetailsPane } from './PromptDetailsPane';
import { EMPTY_PROMPT_DRAFT, PromptEditorDialog, type PromptDraft } from './PromptEditorDialog';

export function PromptWorkbench() {
    const { items, loading, error, refresh, setItems, setError } =
        useSectionResource<WorkspacePrompt>(
            (signal) => fetchPrompts({}, signal),
            'Failed to load prompts.',
        );

    const [query, setQuery] = useState('');
    const [sort] = useState<PromptSort>('recent');
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [draft, setDraft] = useState<PromptDraft | null>(null);
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState<string | null>(null);
    const [busyId, setBusyId] = useState<string | null>(null);

    const refreshBootstrap = useBootstrapStore((state) => state.refresh);

    // The composer's prompt picker reads from the bootstrap catalog, which the server rebuilds
    // once its cache version is bumped by the write. Refreshing here is what makes a prompt
    // created in the workspace selectable in chat without a reload.
    const syncCatalog = useCallback(() => {
        void refreshBootstrap();
    }, [refreshBootstrap]);

    const visible = useMemo(() => visiblePrompts(items, query, sort), [items, query, sort]);

    const selected = useMemo(
        () => items.find((prompt) => prompt.id === selectedId) ?? null,
        [items, selectedId],
    );

    // Open the first row once, when the list first arrives. Re-selecting on every change would
    // fight a deliberate selection, and clearing on every change would close the pane whenever
    // a favourite was toggled.
    const autoSelected = useRef(false);
    useEffect(() => {
        if (autoSelected.current || loading || visible.length === 0) {
            return;
        }
        autoSelected.current = true;
        setSelectedId(visible[0].id);
    }, [loading, visible]);

    useEffect(() => {
        // A selection that has been deleted, or filtered out by a search, should not leave the
        // pane showing something the list no longer contains.
        if (selectedId && !items.some((prompt) => prompt.id === selectedId)) {
            setSelectedId(null);
        }
    }, [items, selectedId]);

    const openEditor = (prompt: WorkspacePrompt | null) => {
        setSaveError(null);
        setDraft(
            prompt
                ? {
                      id: prompt.id,
                      name: String(prompt.name ?? ''),
                      description: String(prompt.description ?? ''),
                      content: String(prompt.content ?? ''),
                  }
                : { ...EMPTY_PROMPT_DRAFT },
        );
    };

    const onSave = async () => {
        if (!draft) {
            return;
        }
        setSaving(true);
        setSaveError(null);
        try {
            const payload = {
                name: draft.name.trim(),
                content: draft.content,
                description: draft.description.trim(),
            };
            if (draft.id) {
                await updatePrompt(draft.id, payload);
                setDraft(null);
                await refresh();
            } else {
                const created = await createPrompt(payload.name, payload.content, {
                    description: payload.description,
                });
                setDraft(null);
                // Selected only after the refetch has landed. `refresh` sets loading and then
                // awaits the network, so a selection made before it is applied against the old
                // list -- and the guard effect below, seeing an id the list does not contain,
                // clears it again. The pane would land on "Nothing selected" instead of on the
                // prompt just written.
                await refresh();
                if (created?.id) {
                    setSelectedId(created.id);
                }
            }
            syncCatalog();
            toast.success(draft.id ? 'Prompt saved' : 'Prompt created');
        } catch (writeError) {
            setSaveError(errorMessage(writeError, 'Could not save the prompt.'));
        } finally {
            setSaving(false);
        }
    };

    const onToggleFavorite = async (prompt: WorkspacePrompt) => {
        const next = !isFavoritePrompt(prompt);
        const previous = items;
        // Applied locally first: the star is a one-click control and waiting for a round trip
        // before it moves makes it feel unresponsive.
        setItems(
            items.map((item) =>
                item.id === prompt.id ? { ...item, is_favorite: next } : item,
            ),
        );
        try {
            await updatePrompt(prompt.id, { is_favorite: next });
            syncCatalog();
        } catch (favoriteError) {
            setItems(previous);
            setError(errorMessage(favoriteError, 'Could not update the prompt.'));
        }
    };

    const onDuplicate = async (prompt: WorkspacePrompt) => {
        setBusyId(prompt.id);
        try {
            const created = await createPrompt(
                duplicatePromptName(
                    promptName(prompt),
                    items.map((item) => String(item.name ?? '')),
                ),
                String(prompt.content ?? ''),
                { description: String(prompt.description ?? '') },
            );
            await refresh();
            syncCatalog();
            if (created?.id) {
                setSelectedId(created.id);
            }
            toast.success('Prompt duplicated');
        } catch (duplicateError) {
            setError(errorMessage(duplicateError, 'Could not duplicate the prompt.'));
        } finally {
            setBusyId(null);
        }
    };

    const onDelete = async (prompt: WorkspacePrompt) => {
        const previous = items;
        setBusyId(prompt.id);
        setItems(items.filter((item) => item.id !== prompt.id));
        try {
            await deletePrompt(prompt.id);
            syncCatalog();
            toast.success('Prompt deleted');
        } catch (deleteError) {
            setItems(previous);
            setError(errorMessage(deleteError, 'Could not delete the prompt.'));
        } finally {
            setBusyId(null);
        }
    };

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-edge px-4 py-2.5">
                <div className="relative min-w-0 flex-1 sm:max-w-xs">
                    <Search
                        size={14}
                        className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-3"
                    />
                    <input
                        type="search"
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="Search name, description or body"
                        aria-label="Search prompts"
                        className="w-full rounded-xl border border-edge bg-surface-1 py-1.5 pr-2.5 pl-8 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                    />
                    {query ? (
                        <button
                            type="button"
                            onClick={() => setQuery('')}
                            aria-label="Clear search"
                            className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-0.5 text-text-3 hover:text-text-1"
                        >
                            <X size={13} />
                        </button>
                    ) : null}
                </div>

                <p className="hidden text-xs text-text-3 md:block">
                    {items.length === 0
                        ? 'No prompts yet'
                        : `${visible.length} of ${items.length}`}
                </p>

                <GlassButton
                    variant="primary"
                    size="sm"
                    className="ml-auto"
                    onClick={() => openEditor(null)}
                >
                    <Plus size={14} />
                    New prompt
                </GlassButton>
            </div>

            {error ? (
                <p className="shrink-0 border-b border-edge bg-danger-soft px-4 py-2 text-xs text-danger">
                    {error}
                </p>
            ) : null}

            <div className="flex min-h-0 flex-1 overflow-hidden">
                {/* On a narrow screen the two panes take turns: showing an 80-character-wide
                    list beside a rendered prompt would leave neither readable. */}
                <div
                    className={clsx(
                        'min-h-0 w-full shrink-0 overflow-y-auto border-edge p-2 md:w-80 md:border-r lg:w-96',
                        selected && 'hidden md:block',
                    )}
                >
                    {loading ? (
                        <div className="space-y-2 p-1">
                            {Array.from({ length: 5 }).map((_, index) => (
                                <Skeleton key={index} className="h-14 w-full" />
                            ))}
                        </div>
                    ) : visible.length === 0 ? (
                        <EmptyState
                            icon={<MessageSquareQuote size={24} />}
                            title={
                                items.length === 0
                                    ? 'No prompts yet'
                                    : 'Nothing matches your search'
                            }
                            description={
                                items.length === 0
                                    ? 'Save wording you have refined once and reuse it from the chat composer.'
                                    : undefined
                            }
                            action={
                                items.length === 0 ? (
                                    <GlassButton
                                        variant="primary"
                                        size="sm"
                                        onClick={() => openEditor(null)}
                                    >
                                        <Plus size={14} />
                                        New prompt
                                    </GlassButton>
                                ) : undefined
                            }
                        />
                    ) : (
                        <PromptList
                            prompts={visible}
                            selectedId={selectedId}
                            busyId={busyId}
                            onSelect={(prompt) => setSelectedId(prompt.id)}
                            onToggleFavorite={(prompt) => void onToggleFavorite(prompt)}
                        />
                    )}
                </div>

                <div
                    className={clsx(
                        'min-w-0 flex-1',
                        selected ? 'block' : 'hidden md:block',
                    )}
                >
                    {selected ? (
                        <PromptDetailsPane
                            key={selected.id}
                            prompt={selected}
                            busy={busyId === selected.id}
                            onBack={() => setSelectedId(null)}
                            onEdit={() => openEditor(selected)}
                            onDuplicate={() => void onDuplicate(selected)}
                            onDelete={() => void onDelete(selected)}
                            onToggleFavorite={() => void onToggleFavorite(selected)}
                        />
                    ) : (
                        <EmptyState
                            icon={<MessageSquareQuote size={28} />}
                            title="Nothing selected"
                            description="Choose a prompt to read it, or create one to reuse in chat."
                        />
                    )}
                </div>
            </div>

            {draft ? (
                <PromptEditorDialog
                    draft={draft}
                    saving={saving}
                    error={saveError}
                    onChange={setDraft}
                    onSave={() => void onSave()}
                    onCancel={() => {
                        setDraft(null);
                        setSaveError(null);
                    }}
                />
            ) : null}
        </div>
    );
}
