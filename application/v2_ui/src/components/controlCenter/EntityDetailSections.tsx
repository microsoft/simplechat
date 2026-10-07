// EntityDetailSections.tsx
// Shared detail navigation and activity presentation for administrative workspace drawers.

import { useState, type ReactNode } from 'react';
import { ExportButton } from './ControlCenterPrimitives';

export function entityDate(value: string | null | undefined) {
    if (!value) return 'Not recorded';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function EntityDetailTabs<T extends string>({
    tabs, selected, onSelect, children,
}: {
    tabs: readonly T[];
    selected: T;
    onSelect: (tab: T) => void;
    children: ReactNode;
}) {
    return <>
        <div role="tablist" aria-label="Detail sections" className="flex flex-wrap gap-1 border-b border-edge">
            {tabs.map((tab, index) => <button key={tab} type="button" role="tab"
                id={`entity-tab-${tab}`} aria-selected={selected === tab} aria-controls="entity-detail-panel"
                tabIndex={selected === tab ? 0 : -1} onClick={() => onSelect(tab)}
                onKeyDown={(event) => {
                    const offset = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
                    if (!offset && event.key !== 'Home' && event.key !== 'End') return;
                    event.preventDefault();
                    const next = event.key === 'Home' ? tabs[0] : event.key === 'End'
                        ? tabs[tabs.length - 1] : tabs[(index + offset + tabs.length) % tabs.length];
                    onSelect(next);
                    document.getElementById(`entity-tab-${next}`)?.focus();
                }}
                className={`px-3 py-2 text-sm capitalize focus-visible:outline-2 focus-visible:outline-accent ${selected === tab ? 'border-b-2 border-accent font-semibold text-accent' : 'text-text-3 hover:text-text-1'}`}>
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>)}
        </div>
        <div id="entity-detail-panel" role="tabpanel" aria-labelledby={`entity-tab-${selected}`} className="space-y-4">
            {children}
        </div>
    </>;
}

export interface EntityActivityItem extends Record<string, unknown> {
    id: string;
    timestamp?: string;
    activity_type: string;
    description?: string;
}

export function EntityActivity({ items }: { items: EntityActivityItem[] }) {
    const [expanded, setExpanded] = useState<string | null>(null);
    return <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-text-3">Most recent {items.length} records. Export includes these records only.</p>
            <ExportButton filename="workspace-recent-activity.csv" rows={items} />
        </div>
        {!items.length ? <p className="text-sm text-text-3">No group activity recorded.</p> : null}
        <ol className="space-y-3">
            {items.map((item) => <li key={item.id} className="space-y-1 border-b border-edge pb-3">
                <p className="text-sm font-medium text-text-1">{item.activity_type.replaceAll('_', ' ')}</p>
                <p className="text-xs text-text-3">{entityDate(item.timestamp)}</p>
                {item.description ? <p className="break-words text-sm text-text-2">{item.description}</p> : null}
                <button type="button" className="text-xs text-accent underline"
                    aria-expanded={expanded === item.id} aria-controls={`activity-json-${item.id}`}
                    onClick={() => setExpanded(expanded === item.id ? null : item.id)}>Raw JSON</button>
                {expanded === item.id ? <pre id={`activity-json-${item.id}`}
                    className="max-h-72 overflow-auto rounded-lg bg-surface-2 p-3 text-xs text-text-2">{JSON.stringify(item, null, 2)}</pre> : null}
            </li>)}
        </ol>
    </div>;
}
