// PromptCard.tsx

import { useId, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { ChevronDown, Lightbulb } from 'lucide-react';

export function PromptCard({
    name, scopeLabel, edited = false, summary, content, open, onToggle,
    onAccent = false, actions, children, footer, className,
}: {
    name: string;
    scopeLabel?: string;
    edited?: boolean;
    summary?: string | null;
    content: string;
    open: boolean;
    onToggle: () => void;
    onAccent?: boolean;
    actions?: ReactNode;
    children?: ReactNode;
    footer?: ReactNode;
    className?: string;
}) {
    const id = useId();
    return (
        <div className={clsx(
            'mb-2 min-w-0 rounded-xl border',
            onAccent ? 'border-on-accent/25 bg-on-accent/10' : 'border-edge glass-flat',
            className,
        )}>
            <div className="flex items-center gap-1 px-2 py-1.5">
                <button
                    type="button"
                    onClick={onToggle}
                    aria-expanded={open}
                    aria-controls={open ? id : undefined}
                    aria-label={`${open ? 'Collapse' : 'Expand'} prompt ${name}`}
                    aria-describedby={scopeLabel || summary ? `${id}-summary` : undefined}
                    className={clsx(
                        'flex min-w-0 flex-1 items-center gap-1.5 rounded-lg px-1 py-1 text-left text-xs',
                        onAccent ? 'text-on-accent hover:bg-on-accent/10' : 'text-text-1 hover:bg-surface-2',
                    )}
                >
                    <Lightbulb size={13} className="shrink-0" aria-hidden="true" />
                    <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{name}</span>
                        {(scopeLabel || summary) && (
                            <span id={`${id}-summary`} aria-live="polite"
                                className={clsx('block truncate text-[11px]', onAccent ? 'text-on-accent/80' : 'text-text-3')}>
                                {[scopeLabel, summary].filter(Boolean).join(' | ')}
                            </span>
                        )}
                    </span>
                    {edited && <span className="shrink-0 rounded border border-current/20 px-1 text-[10px]">Edited</span>}
                    <ChevronDown size={12} aria-hidden="true"
                        className={clsx('shrink-0 transition-transform', open && 'rotate-180')} />
                </button>
                {actions}
            </div>
            {open && (
                <div id={id} className={clsx('border-t px-3 py-2.5', onAccent ? 'border-on-accent/20' : 'border-edge')}>
                    {children ?? (
                        <pre
                            tabIndex={0}
                            aria-label={`Prompt preview: ${name}`}
                            className={clsx(
                                'max-h-48 overflow-y-auto rounded-lg px-2.5 py-2 text-xs whitespace-pre-wrap break-words',
                                onAccent ? 'bg-on-accent/10 text-on-accent' : 'bg-surface-sunken text-text-2',
                            )}
                        >
                            {content}
                        </pre>
                    )}
                </div>
            )}
            {footer}
        </div>
    );
}
