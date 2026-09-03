// PromptList.tsx
// The left pane: every prompt, as a selectable row.
//
// Rows are buttons rather than list items with a click handler, so the whole list is reachable
// by keyboard and each row announces itself. Selection is owned by the workbench; this
// component only reports it, which is what lets the same list drive the details pane without
// the two disagreeing about what is open.

import { clsx } from 'clsx';
import { MessageSquareQuote } from 'lucide-react';
import type { WorkspacePrompt } from '../../lib/types';
import {
    isFavoritePrompt,
    promptName,
    promptPreview,
    promptUpdatedLabel,
    promptVariableCount,
} from '../../lib/promptLibrary';
import { FavoriteButton, VariableCountPill } from './promptPresentation';

export function PromptList({
    prompts,
    selectedId,
    onSelect,
    onToggleFavorite,
    busyId,
}: {
    prompts: WorkspacePrompt[];
    selectedId: string | null;
    onSelect: (prompt: WorkspacePrompt) => void;
    onToggleFavorite: (prompt: WorkspacePrompt) => void;
    busyId: string | null;
}) {
    return (
        <ul className="space-y-1" role="list">
            {prompts.map((prompt) => {
                const selected = prompt.id === selectedId;
                const name = promptName(prompt);
                const preview = promptPreview(prompt);
                return (
                    <li key={prompt.id}>
                        <div
                            className={clsx(
                                'group flex items-start gap-2 rounded-xl border px-2.5 py-2 transition-colors',
                                selected
                                    ? 'border-accent bg-accent-soft'
                                    : 'border-transparent hover:bg-surface-2',
                                busyId === prompt.id && 'opacity-50',
                            )}
                        >
                            <button
                                type="button"
                                onClick={() => onSelect(prompt)}
                                aria-current={selected ? 'true' : undefined}
                                className="min-w-0 flex-1 text-left"
                            >
                                <span className="flex items-center gap-1.5">
                                    <MessageSquareQuote
                                        size={14}
                                        className={clsx(
                                            'shrink-0',
                                            selected ? 'text-accent' : 'text-text-3',
                                        )}
                                    />
                                    <span
                                        className={clsx(
                                            'truncate text-sm font-medium',
                                            selected ? 'text-accent' : 'text-text-1',
                                        )}
                                    >
                                        {name}
                                    </span>
                                    <VariableCountPill count={promptVariableCount(prompt)} />
                                </span>
                                <span className="mt-0.5 block truncate text-xs text-text-3">
                                    {String(prompt.description ?? '').trim() ||
                                        preview ||
                                        'Empty prompt'}
                                </span>
                                <span className="mt-0.5 block text-[11px] text-text-3">
                                    {promptUpdatedLabel(prompt)}
                                </span>
                            </button>

                            <FavoriteButton
                                active={isFavoritePrompt(prompt)}
                                label={name}
                                onToggle={() => onToggleFavorite(prompt)}
                                className={clsx(
                                    // Always visible once set, so the list still reads as
                                    // ordered by favourite without hovering every row.
                                    !isFavoritePrompt(prompt) &&
                                        'opacity-0 group-hover:opacity-100 focus-visible:opacity-100',
                                )}
                            />
                        </div>
                    </li>
                );
            })}
        </ul>
    );
}
