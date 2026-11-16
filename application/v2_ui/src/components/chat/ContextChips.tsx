// ContextChips.tsx
// What the next message is pointed at, shown above the composer.
//
// The row answers one question before the message is sent: which documents is the assistant
// actually going to look at? V2 previously had no answer to that -- the Documents button was
// on or off, and what it searched was whatever the deployment's scope happened to resolve to.
//
// It condenses as it fills, because the two failure modes pull in opposite directions. A
// handful of references shown only as "4 documents" is useless: the whole point is to see that
// the wrong contract is not in the list. Forty of them shown individually is a wall that
// pushes the message box off the screen. So few items render by name, and past a threshold
// each workspace collapses to a count that opens on click.
//
// Grouping appears only when more than one workspace is involved. A single group container
// wrapped around a single personal document is a box drawn for no reason.

import { useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { FileText, FolderOpen, Sparkles, Tag as TagIcon, X } from 'lucide-react';
import {
    describeContextGroup,
    describeContextItem,
    groupContextItems,
    type ContextItem,
    type ContextKind,
} from '../../lib/chatContext';

/**
 * How many references render by name before a workspace collapses to a count.
 *
 * Chosen so the common cases stay legible: picking two documents to compare, or a document
 * and the tag it belongs to, are what this control is mostly used for.
 */
const EXPANDED_LIMIT = 5;

const KIND_ICON: Record<ContextKind, typeof FileText> = {
    document: FileText,
    tag: TagIcon,
    scope: FolderOpen,
};

function ContextChip({
    item,
    onRemove,
}: {
    item: ContextItem;
    onRemove: (item: ContextItem) => void;
}) {
    const Icon = item.origin === 'planner' ? Sparkles : KIND_ICON[item.kind];

    return (
        <span
            title={describeContextItem(item)}
            className={clsx(
                'inline-flex max-w-[16rem] items-center gap-1.5 rounded-lg py-0.5 pl-2 pr-1',
                'text-xs text-accent',
                // The planner's own choices are drawn as provisional, because they are: they
                // arrived from a proposal the reader has not accepted yet.
                item.origin === 'planner'
                    ? 'border border-dashed border-accent-ring bg-accent-soft/60'
                    : 'bg-accent-soft',
            )}
        >
            <Icon size={12} className="shrink-0" aria-hidden="true" />
            <span className="truncate">{item.label}</span>
            <button
                type="button"
                onClick={() => onRemove(item)}
                aria-label={`Remove ${item.label}`}
                className="shrink-0 rounded p-0.5 text-accent/70 hover:bg-accent-soft hover:text-accent"
            >
                <X size={11} />
            </button>
        </span>
    );
}

/**
 * A workspace's references, collapsed to a count until asked for.
 *
 * The popover is anchored above rather than below: the row sits directly on top of the
 * message box, and opening downwards would cover the thing being written.
 */
function CollapsedGroup({
    label,
    items,
    onRemove,
    onRemoveAll,
}: {
    label: string;
    items: ContextItem[];
    onRemove: (item: ContextItem) => void;
    onRemoveAll: (items: ContextItem[]) => void;
}) {
    const [open, setOpen] = useState(false);
    const holder = useRef<HTMLSpanElement>(null);

    useEffect(() => {
        if (!open) {
            return;
        }
        const onPointerDown = (event: MouseEvent) => {
            if (!holder.current?.contains(event.target as Node)) {
                setOpen(false);
            }
        };
        const onEscape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setOpen(false);
            }
        };
        document.addEventListener('mousedown', onPointerDown);
        document.addEventListener('keydown', onEscape);
        return () => {
            document.removeEventListener('mousedown', onPointerDown);
            document.removeEventListener('keydown', onEscape);
        };
    }, [open]);

    return (
        <span ref={holder} className="relative inline-flex">
            <button
                type="button"
                onClick={() => setOpen((current) => !current)}
                aria-expanded={open}
                className={clsx(
                    'inline-flex items-center gap-1.5 rounded-lg bg-accent-soft py-0.5 pl-2 pr-2',
                    'text-xs text-accent hover:bg-accent-soft/80',
                )}
            >
                <FolderOpen size={12} className="shrink-0" aria-hidden="true" />
                <span className="font-medium">{label}</span>
                <span className="text-accent/75">{describeContextGroup(items)}</span>
            </button>

            {open && (
                <div className="glass-modal absolute bottom-full left-0 z-50 mb-1.5 max-h-64 w-72 overflow-y-auto rounded-xl p-1.5">
                    <div className="flex items-center justify-between gap-2 px-1.5 pb-1.5">
                        <span className="text-[11px] font-medium text-text-2">{label}</span>
                        <button
                            type="button"
                            onClick={() => {
                                onRemoveAll(items);
                                setOpen(false);
                            }}
                            className="rounded px-1 text-[11px] text-text-3 hover:text-text-1"
                        >
                            Remove all
                        </button>
                    </div>
                    <ul className="space-y-0.5">
                        {items.map((item) => {
                            const Icon =
                                item.origin === 'planner' ? Sparkles : KIND_ICON[item.kind];
                            return (
                                <li key={item.key}>
                                    <div className="flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-surface-2">
                                        <Icon
                                            size={12}
                                            className="shrink-0 text-text-3"
                                            aria-hidden="true"
                                        />
                                        <span className="min-w-0 flex-1">
                                            <span className="block truncate text-xs text-text-1">
                                                {item.label}
                                            </span>
                                            {item.meta?.fileName && (
                                                <span className="block truncate text-[10px] text-text-3">
                                                    {item.meta.fileName}
                                                </span>
                                            )}
                                        </span>
                                        <button
                                            type="button"
                                            onClick={() => onRemove(item)}
                                            aria-label={`Remove ${item.label}`}
                                            className="shrink-0 rounded p-0.5 text-text-3 hover:bg-surface-3 hover:text-text-1"
                                        >
                                            <X size={11} />
                                        </button>
                                    </div>
                                </li>
                            );
                        })}
                    </ul>
                </div>
            )}
        </span>
    );
}

export function ContextChips({
    items,
    onRemove,
    onRemoveAll,
    onClear,
}: {
    items: ContextItem[];
    onRemove: (item: ContextItem) => void;
    onRemoveAll: (items: ContextItem[]) => void;
    onClear: () => void;
}) {
    if (items.length === 0) {
        return null;
    }

    const groups = groupContextItems(items);
    // Condensing is decided on the whole row, not per workspace, so two workspaces holding
    // three references each do not render one expanded and one collapsed.
    const collapse = items.length > EXPANDED_LIMIT;
    const showGroupLabels = groups.length > 1;

    return (
        <div className="mb-1.5 flex flex-wrap items-center gap-1.5 px-1">
            {groups.map((group) =>
                collapse ? (
                    <CollapsedGroup
                        key={group.key}
                        label={group.scope.name}
                        items={group.items}
                        onRemove={onRemove}
                        onRemoveAll={onRemoveAll}
                    />
                ) : (
                    <span
                        key={group.key}
                        className={clsx(
                            'inline-flex flex-wrap items-center gap-1.5',
                            showGroupLabels && 'rounded-xl border border-edge bg-surface-1 px-1.5 py-1',
                        )}
                    >
                        {showGroupLabels && (
                            <span className="pl-0.5 text-[10px] font-medium uppercase tracking-wide text-text-3">
                                {group.scope.name}
                            </span>
                        )}
                        {group.items.map((item) => (
                            <ContextChip key={item.key} item={item} onRemove={onRemove} />
                        ))}
                    </span>
                ),
            )}

            {items.length > 1 && (
                <button
                    type="button"
                    onClick={onClear}
                    className="rounded-lg px-1.5 py-0.5 text-[11px] text-text-3 hover:bg-surface-2 hover:text-text-1"
                >
                    Clear all
                </button>
            )}
        </div>
    );
}
