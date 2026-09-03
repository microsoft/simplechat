// PromptDetailsPane.tsx
// The right pane: a prompt as it will read, without opening a form.
//
// This is the part the section was missing. Previously the only way to see more than the first
// 140 characters of a prompt was to click Edit, which put the page into a state that had to be
// cancelled out of -- so browsing your own prompts meant repeatedly entering and leaving an
// editor. Here the body is rendered, the variables are listed, and editing is a deliberate act.
//
// Rendering goes through PlainMarkdown, which does not enable `rehype-raw`, so a prompt cannot
// inject script or event handlers into this pane.

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
    ChevronLeft,
    Copy,
    CopyPlus,
    Eraser,
    MessageSquarePlus,
    Pencil,
    Trash2,
} from 'lucide-react';
import type { WorkspacePrompt } from '../../lib/types';
import {
    chatHrefForPrompt,
    isFavoritePrompt,
    promptName,
    promptUpdatedLabel,
} from '../../lib/promptLibrary';
import { parsePromptVariables } from '../../lib/promptVariables';
import { forgetPromptValues, hasRememberedPromptValues } from '../../lib/promptVariableMemory';
import { toast } from '../../stores/toastStore';
import { GlassButton } from '../ui/primitives';
import { PlainMarkdown } from '../ui/PlainMarkdown';
import { DetailField, FavoriteButton, VariableChip } from './promptPresentation';

export function PromptDetailsPane({
    prompt,
    onEdit,
    onDuplicate,
    onDelete,
    onToggleFavorite,
    onBack,
    busy,
}: {
    prompt: WorkspacePrompt;
    onEdit: () => void;
    onDuplicate: () => void;
    onDelete: () => void;
    onToggleFavorite: () => void;
    /** Returns to the list on a narrow screen, where the two panes take turns. */
    onBack?: () => void;
    busy: boolean;
}) {
    const [confirmingDelete, setConfirmingDelete] = useState(false);
    // The memory lives in localStorage, which React cannot subscribe to. The tick is an
    // explicit invalidation key, bumped by the Forget button below, so the control disappears
    // once it has been used rather than after some later unrelated render.
    const [forgetTick, setForgetTick] = useState(0);
    const remembered = useMemo(
        () => hasRememberedPromptValues(prompt.id),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [prompt.id, forgetTick],
    );

    const content = String(prompt.content ?? '');
    const variables = parsePromptVariables(content);
    const name = promptName(prompt);
    const description = String(prompt.description ?? '').trim();

    const copyBody = () => {
        void navigator.clipboard
            .writeText(content)
            .then(() => toast.success('Prompt copied'))
            .catch(() => {
                // Clipboard access can be denied, and there is nothing useful to do about it.
            });
    };

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="flex items-start justify-between gap-2 border-b border-edge px-4 py-3">
                <div className="flex min-w-0 items-start gap-2">
                    {onBack ? (
                        <button
                            type="button"
                            onClick={onBack}
                            aria-label="Back to all prompts"
                            className="-ml-1 rounded-lg p-1 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 md:hidden"
                        >
                            <ChevronLeft size={16} />
                        </button>
                    ) : null}
                    <div className="min-w-0">
                        <h3 className="truncate text-sm font-semibold text-text-1">{name}</h3>
                        <p className="mt-0.5 text-xs text-text-3">
                            Updated {promptUpdatedLabel(prompt)}
                        </p>
                    </div>
                </div>
                <FavoriteButton
                    active={isFavoritePrompt(prompt)}
                    label={name}
                    onToggle={onToggleFavorite}
                />
            </div>

            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
                {description ? (
                    <p className="text-sm leading-relaxed text-text-2">{description}</p>
                ) : null}

                {variables.length > 0 ? (
                    <DetailField label="Variables">
                        <div className="flex flex-wrap gap-1.5">
                            {variables.map((variable) => (
                                <VariableChip
                                    key={variable.key}
                                    name={variable.name}
                                    builtIn={variable.builtIn}
                                    hasDefault={Boolean(variable.defaultValue)}
                                />
                            ))}
                        </div>
                        <p className="mt-1.5 text-[11px] leading-relaxed text-text-3">
                            You will be asked for these when the prompt is used. Highlighted ones
                            are filled in from the conversation.
                        </p>
                    </DetailField>
                ) : null}

                <DetailField label="Prompt">
                    <PlainMarkdown content={content} emptyLabel="This prompt has no content." />
                </DetailField>

                {remembered ? (
                    <DetailField label="Saved on this device">
                        <p className="text-xs leading-relaxed text-text-3">
                            The values you last entered for this prompt are remembered in this
                            browser so you do not retype them. They are never sent to the server.
                        </p>
                        <button
                            type="button"
                            onClick={() => {
                                forgetPromptValues(prompt.id);
                                setForgetTick((count) => count + 1);
                                toast.success('Saved values forgotten');
                            }}
                            className="mt-1.5 inline-flex items-center gap-1.5 text-xs text-text-2 underline underline-offset-2 hover:text-text-1"
                        >
                            <Eraser size={12} />
                            Forget saved values
                        </button>
                    </DetailField>
                ) : null}
            </div>

            <div className="flex flex-wrap items-center gap-2 border-t border-edge px-4 py-3">
                <GlassButton variant="primary" size="sm" onClick={onEdit} disabled={busy}>
                    <Pencil size={14} />
                    Edit
                </GlassButton>

                <Link
                    to={chatHrefForPrompt(prompt.id)}
                    className="inline-flex h-8 items-center gap-1.5 rounded-xl px-3 text-sm font-medium text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1"
                >
                    <MessageSquarePlus size={14} />
                    Use in chat
                </Link>

                <GlassButton size="sm" onClick={copyBody} disabled={busy}>
                    <Copy size={14} />
                    Copy
                </GlassButton>

                <GlassButton size="sm" onClick={onDuplicate} disabled={busy}>
                    <CopyPlus size={14} />
                    Duplicate
                </GlassButton>

                <div className="ml-auto">
                    {confirmingDelete ? (
                        <div className="flex items-center gap-2">
                            <span className="text-xs text-text-3">Delete this prompt?</span>
                            <GlassButton
                                size="sm"
                                onClick={() => setConfirmingDelete(false)}
                                disabled={busy}
                            >
                                Cancel
                            </GlassButton>
                            <GlassButton
                                variant="danger"
                                size="sm"
                                onClick={() => {
                                    setConfirmingDelete(false);
                                    onDelete();
                                }}
                                disabled={busy}
                            >
                                Delete
                            </GlassButton>
                        </div>
                    ) : (
                        <GlassButton
                            size="sm"
                            onClick={() => setConfirmingDelete(true)}
                            disabled={busy}
                            className="text-danger hover:bg-danger-soft"
                        >
                            <Trash2 size={14} />
                            Delete
                        </GlassButton>
                    )}
                </div>
            </div>
        </div>
    );
}
