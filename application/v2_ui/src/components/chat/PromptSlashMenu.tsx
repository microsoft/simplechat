// PromptSlashMenu.tsx
// The `/` prompt search offered while writing.
//
// A sibling of MentionMenu, and deliberately built the same way: pointer-down rather than
// click, because the textarea loses focus on mouse-up and a blur handler would remove the row
// before the click landed.
//
// The menu closes itself by having nothing to show. A slash query is allowed to contain spaces
// -- "/weekly status" should find "Weekly status summary" -- and the price of that is that an
// ordinary sentence beginning with a slash would otherwise keep the menu open indefinitely.
// Rendering nothing when nothing matches is what makes the permissive query safe.

import { clsx } from 'clsx';
import { MessageSquareQuote, Star } from 'lucide-react';
import type { PromptOption } from '../../lib/types';
import { countPromptVariables } from '../../lib/promptVariables';
import { VariableCountPill } from '../prompts/promptPresentation';

export function PromptSlashMenu({
    prompts,
    activeIndex,
    onSelect,
}: {
    prompts: PromptOption[];
    activeIndex: number;
    onSelect: (prompt: PromptOption) => void;
}) {
    if (prompts.length === 0) {
        return null;
    }

    return (
        <div
            role="listbox"
            aria-label="Prompt suggestions"
            className="glass-modal absolute bottom-full left-2 z-50 mb-2 max-h-64 w-80 overflow-y-auto rounded-xl p-1"
        >
            {prompts.map((prompt, index) => (
                <button
                    key={prompt.id}
                    type="button"
                    role="option"
                    aria-selected={index === activeIndex}
                    onMouseDown={(event) => {
                        event.preventDefault();
                        onSelect(prompt);
                    }}
                    className={clsx(
                        'flex w-full items-start gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm',
                        index === activeIndex
                            ? 'bg-accent-soft text-accent'
                            : 'text-text-1 hover:bg-surface-2',
                    )}
                >
                    <span className="mt-0.5 shrink-0 text-text-3">
                        {prompt.is_favorite ? (
                            <Star size={14} fill="currentColor" className="text-warn" />
                        ) : (
                            <MessageSquareQuote size={14} />
                        )}
                    </span>
                    <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-1.5">
                            <span className="truncate">{prompt.name || 'Prompt'}</span>
                            <VariableCountPill
                                count={countPromptVariables(String(prompt.content ?? ''))}
                            />
                        </span>
                        {prompt.description || prompt.scope_name ? (
                            <span className="block truncate text-[11px] text-text-3">
                                {prompt.description || prompt.scope_name}
                            </span>
                        ) : null}
                    </span>
                </button>
            ))}
        </div>
    );
}
