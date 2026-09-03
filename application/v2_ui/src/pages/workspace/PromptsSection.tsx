// PromptsSection.tsx
// Saved prompts: create, edit, delete.
//
// The only section with a complete editor in this pass, because a prompt is only a name and
// a body -- there is nothing to defer.

import { useMemo, useState } from 'react';
import { MessageSquareQuote, Pencil, Plus, Trash2 } from 'lucide-react';
import { GlassButton, GlassPanel } from '../../components/ui/primitives';
import {
    ConfirmAction,
    ResourceRow,
    RowAction,
    SectionIntro,
    SectionList,
    SectionSearch,
} from '../../components/workspace/primitives';
import {
    errorMessage,
    useSectionResource,
} from '../../components/workspace/useSectionResource';
import {
    createPrompt,
    deletePrompt,
    fetchPrompts,
    updatePrompt,
} from '../../lib/workspaceApi';
import type { WorkspacePrompt } from '../../lib/types';

interface DraftPrompt {
    id: string | null;
    name: string;
    content: string;
}

const EMPTY_DRAFT: DraftPrompt = { id: null, name: '', content: '' };

function PromptEditor({
    draft,
    saving,
    onChange,
    onSave,
    onCancel,
}: {
    draft: DraftPrompt;
    saving: boolean;
    onChange: (next: DraftPrompt) => void;
    onSave: () => void;
    onCancel: () => void;
}) {
    const canSave = draft.name.trim().length > 0 && draft.content.trim().length > 0;

    return (
        <GlassPanel elevation="flat" className="space-y-3 p-4">
            <div>
                <label
                    htmlFor="prompt-name"
                    className="mb-1 block text-xs font-medium text-text-2"
                >
                    Name
                </label>
                <input
                    id="prompt-name"
                    type="text"
                    value={draft.name}
                    onChange={(event) => onChange({ ...draft, name: event.target.value })}
                    placeholder="Weekly status summary"
                    className="w-full rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                />
            </div>

            <div>
                <label
                    htmlFor="prompt-content"
                    className="mb-1 block text-xs font-medium text-text-2"
                >
                    Prompt
                </label>
                <textarea
                    id="prompt-content"
                    rows={6}
                    value={draft.content}
                    onChange={(event) => onChange({ ...draft, content: event.target.value })}
                    placeholder="Summarise the attached documents as five bullet points, then list any open questions."
                    className="w-full resize-y rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                />
            </div>

            <div className="flex justify-end gap-2">
                <GlassButton size="sm" onClick={onCancel} disabled={saving}>
                    Cancel
                </GlassButton>
                <GlassButton
                    variant="primary"
                    size="sm"
                    onClick={onSave}
                    disabled={!canSave || saving}
                >
                    {saving ? 'Saving' : draft.id ? 'Save changes' : 'Create prompt'}
                </GlassButton>
            </div>
        </GlassPanel>
    );
}

export function PromptsSection() {
    const { items, loading, error, refresh, setItems, setError } =
        useSectionResource<WorkspacePrompt>(
            (signal) => fetchPrompts({}, signal),
            'Failed to load prompts.',
        );

    const [query, setQuery] = useState('');
    const [draft, setDraft] = useState<DraftPrompt | null>(null);
    const [saving, setSaving] = useState(false);
    const [busyId, setBusyId] = useState<string | null>(null);

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) {
            return items;
        }
        return items.filter((prompt) =>
            String(prompt.name ?? '').toLowerCase().includes(needle),
        );
    }, [items, query]);

    const onSave = async () => {
        if (!draft) {
            return;
        }
        setSaving(true);
        setError(null);
        try {
            if (draft.id) {
                await updatePrompt(draft.id, {
                    name: draft.name.trim(),
                    content: draft.content,
                });
            } else {
                await createPrompt(draft.name.trim(), draft.content);
            }
            setDraft(null);
            await refresh();
        } catch (saveError) {
            setError(errorMessage(saveError, 'Could not save the prompt.'));
        } finally {
            setSaving(false);
        }
    };

    const onDelete = async (prompt: WorkspacePrompt) => {
        const previous = items;
        setBusyId(prompt.id);
        setItems(items.filter((item) => item.id !== prompt.id));
        try {
            await deletePrompt(prompt.id);
        } catch (deleteError) {
            setItems(previous);
            setError(errorMessage(deleteError, 'Could not delete the prompt.'));
        } finally {
            setBusyId(null);
        }
    };

    return (
        <div className="space-y-4">
            <SectionIntro
                title="Prompts"
                description="Instructions you reuse. Saved prompts are offered in the chat composer, so a wording you have refined once does not have to be retyped."
                actions={
                    <GlassButton
                        variant="primary"
                        size="sm"
                        onClick={() => setDraft({ ...EMPTY_DRAFT })}
                        disabled={Boolean(draft)}
                    >
                        <Plus size={14} />
                        New prompt
                    </GlassButton>
                }
            />

            {draft ? (
                <PromptEditor
                    draft={draft}
                    saving={saving}
                    onChange={setDraft}
                    onSave={() => void onSave()}
                    onCancel={() => setDraft(null)}
                />
            ) : null}

            <SectionSearch value={query} onChange={setQuery} placeholder="Search prompts" />

            <SectionList
                items={visible}
                loading={loading}
                error={error}
                emptyIcon={<MessageSquareQuote size={28} />}
                emptyTitle={items.length === 0 ? 'No prompts yet' : 'No prompts match your search'}
                emptyDescription={
                    items.length === 0
                        ? 'Save a prompt to reuse it from the chat composer.'
                        : undefined
                }
                getKey={(prompt, index) => String(prompt.id ?? index)}
                renderItem={(prompt) => (
                    <ResourceRow
                        icon={<MessageSquareQuote size={17} />}
                        title={String(prompt.name ?? 'Untitled prompt')}
                        subtitle={String(prompt.content ?? '').slice(0, 140)}
                        actions={
                            <>
                                <RowAction
                                    icon={<Pencil size={15} />}
                                    label={`Edit ${prompt.name ?? 'prompt'}`}
                                    onClick={() =>
                                        setDraft({
                                            id: prompt.id,
                                            name: String(prompt.name ?? ''),
                                            content: String(prompt.content ?? ''),
                                        })
                                    }
                                />
                                <ConfirmAction
                                    icon={<Trash2 size={15} />}
                                    label={`Delete ${prompt.name ?? 'prompt'}`}
                                    confirmLabel="Delete"
                                    busy={busyId === prompt.id}
                                    onConfirm={() => void onDelete(prompt)}
                                />
                            </>
                        }
                    />
                )}
            />
        </div>
    );
}
