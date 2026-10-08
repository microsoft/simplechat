// CategoryRail.tsx
// The page shell Approvals and the admin Review center share: a page header, a collapsible
// rail of categories on the left, and the chosen category's content beside it.
//
// The rail collapses to icons and remembers that per page, through a user setting each page
// names. Below the lg breakpoint it gives way to a picker above the content, so every
// category stays one choice away on a phone. The active category comes from the page's
// address; the rail only reports a choice.

import type { ReactNode } from 'react';
import clsx from 'clsx';
import { PanelLeftClose, PanelLeftOpen, type LucideIcon } from 'lucide-react';
import { PageHeader } from './PageHeader';

export interface RailItem {
    id: string;
    label: string;
    /**
     * The name read for the entry where its label alone would be ambiguous, such as two
     * sections each with a "Dashboard". It must contain the visible label.
     */
    accessibleLabel?: string;
    description: string;
    Icon: LucideIcon;
}

export interface RailSection {
    id: string;
    /** Shown above the section's entries; omit it for a single unnamed list. */
    label?: string;
    items: RailItem[];
}

export function railItems(sections: readonly RailSection[]): RailItem[] {
    return sections.flatMap((section) => section.items);
}

export function CategoryRailPage({
    testId,
    title,
    description,
    actions,
    railLabel,
    railTestId,
    itemTestIdPrefix,
    collapseNoun,
    listId,
    sections,
    activeId,
    activeCount,
    countTestId,
    collapsed,
    onToggleCollapsed,
    onSelect,
    pickerId,
    pickerLabel,
    pickerTestId,
    showHeading = true,
    children,
}: {
    testId: string;
    title: string;
    description: string;
    actions?: ReactNode;
    /** The rail's accessible name, such as "Approval categories". */
    railLabel: string;
    railTestId: string;
    /** Each entry's test id is this prefix followed by the entry's id. */
    itemTestIdPrefix: string;
    /** What the collapse control names, such as "approval categories". */
    collapseNoun: string;
    listId: string;
    sections: readonly RailSection[];
    activeId: string;
    /** Shown beside the active entry while the rail is expanded. */
    activeCount?: number | null;
    countTestId?: string;
    collapsed: boolean;
    onToggleCollapsed: () => void;
    onSelect: (id: string) => void;
    pickerId: string;
    pickerLabel: string;
    pickerTestId: string;
    /** Whether the active entry's name and description head the content on wide screens. */
    showHeading?: boolean;
    children: ReactNode;
}) {
    const items = railItems(sections);
    const active = items.find((item) => item.id === activeId) ?? items[0];
    const collapseLabel = collapsed ? `Expand ${collapseNoun}` : `Collapse ${collapseNoun}`;

    const renderItem = (item: RailItem) => {
        const isActive = item.id === active?.id;
        return (
            <button
                key={item.id}
                type="button"
                aria-pressed={isActive}
                aria-label={item.accessibleLabel}
                title={collapsed ? item.accessibleLabel ?? item.label : item.description}
                onClick={() => {
                    if (!isActive) onSelect(item.id);
                }}
                data-testid={`${itemTestIdPrefix}${item.id}`}
                className={clsx(
                    'relative flex w-full items-center gap-2.5 rounded-lg py-2.5 text-left text-sm transition-colors',
                    collapsed ? 'justify-center px-2' : 'px-3',
                    isActive
                        ? 'bg-accent-soft font-semibold text-accent'
                        : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
                )}
            >
                <item.Icon
                    size={16}
                    aria-hidden="true"
                    className={clsx('shrink-0', isActive ? 'text-accent' : 'text-text-3')}
                />
                <span className={collapsed ? 'sr-only' : 'min-w-0 flex-1'}>{item.label}</span>
                {isActive && activeCount && !collapsed ? (
                    <span className="rounded-full bg-accent px-1.5 text-[11px] font-semibold text-white" data-testid={countTestId}>
                        {activeCount}
                    </span>
                ) : null}
            </button>
        );
    };

    return (
        <div className="flex h-full min-h-0 flex-col" data-testid={testId}>
            <PageHeader title={title} description={description} actions={actions} />
            <div className="flex min-h-0 flex-1">
                <aside
                    aria-label={railLabel}
                    data-testid={railTestId}
                    className={clsx(
                        'hidden shrink-0 overflow-y-auto border-r border-edge transition-[width] motion-reduce:transition-none lg:block',
                        collapsed ? 'w-16 px-2 py-3' : 'w-56 p-3',
                    )}
                >
                    <button
                        type="button"
                        onClick={onToggleCollapsed}
                        aria-label={collapseLabel}
                        aria-expanded={!collapsed}
                        aria-controls={listId}
                        title={collapseLabel}
                        className={clsx(
                            'mb-2 flex w-full items-center gap-2 rounded-lg py-1.5 text-xs text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1',
                            collapsed ? 'justify-center px-2' : 'px-3',
                        )}
                    >
                        {collapsed ? (
                            <PanelLeftOpen size={15} aria-hidden="true" />
                        ) : (
                            <>
                                <PanelLeftClose size={15} aria-hidden="true" />
                                <span>Collapse</span>
                            </>
                        )}
                    </button>
                    <div id={listId} className="space-y-0.5">
                        {sections.map((section, index) => {
                            if (!section.label) {
                                return <div key={section.id} className="space-y-0.5">{section.items.map(renderItem)}</div>;
                            }
                            const headingId = `${listId}-${section.id}`;
                            return (
                                <div key={section.id} role="group" aria-labelledby={headingId} className="space-y-0.5">
                                    <p
                                        id={headingId}
                                        className={clsx(
                                            collapsed
                                                ? 'sr-only'
                                                : 'px-3 pt-3 pb-1 text-[11px] font-semibold tracking-wide text-text-3 uppercase',
                                            !collapsed && index === 0 && 'pt-1',
                                        )}
                                    >
                                        {section.label}
                                    </p>
                                    {collapsed && index > 0 ? <div aria-hidden="true" className="mx-2 my-2 border-t border-edge" /> : null}
                                    {section.items.map(renderItem)}
                                </div>
                            );
                        })}
                    </div>
                </aside>

                <div className="flex min-w-0 flex-1 flex-col">
                    <div className={clsx('shrink-0 border-b border-edge px-4 py-3 lg:px-6', !showHeading && 'lg:hidden')}>
                        <div className="max-w-md lg:hidden">
                            <label htmlFor={pickerId} className="mb-1 block text-xs text-text-2">{pickerLabel}</label>
                            <select
                                id={pickerId}
                                value={active?.id ?? ''}
                                onChange={(event) => onSelect(event.target.value)}
                                className="w-full rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1"
                                data-testid={pickerTestId}
                            >
                                {sections.map((section) => section.label ? (
                                    <optgroup key={section.id} label={section.label}>
                                        {section.items.map((item) => (
                                            <option key={item.id} value={item.id}>{item.label}</option>
                                        ))}
                                    </optgroup>
                                ) : section.items.map((item) => (
                                    <option key={item.id} value={item.id}>{item.label}</option>
                                )))}
                            </select>
                        </div>
                        {showHeading && active ? (
                            <div className="hidden lg:block">
                                <h2 className="text-sm font-semibold text-text-1">{active.accessibleLabel ?? active.label}</h2>
                                <p className="text-xs text-text-3">{active.description}</p>
                            </div>
                        ) : null}
                    </div>
                    <div className="min-h-0 flex-1">{children}</div>
                </div>
            </div>
        </div>
    );
}
