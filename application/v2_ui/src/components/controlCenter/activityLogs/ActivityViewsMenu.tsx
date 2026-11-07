// ActivityViewsMenu.tsx
// Quick views for the questions administrators ask most, and the administrator's own saved
// views, stored on their account so they follow them to any browser.

import { useState } from 'react';
import { clsx } from 'clsx';
import { Bookmark, Check, ChevronDown, Pencil, Trash2, X } from 'lucide-react';
import type { ActivityLogSavedView } from '../../../lib/activityLogs';
import { MAX_ACTIVITY_SAVED_VIEWS, MAX_ACTIVITY_VIEW_NAME_LENGTH } from '../../../lib/activityLogSavedViews';
import { GlassButton } from '../../ui/primitives';
import { AnchoredPopover, usePopover } from './FilterPill';

export interface QuickView {
    id: string;
    name: string;
    description: string;
    query: string;
}

export const QUICK_VIEWS: QuickView[] = [
    { id: 'sign-ins', name: 'Recent sign-ins', description: 'User logins in the last 7 days', query: 'range=7&activity_type=user_login' },
    { id: 'tokens', name: 'Token usage', description: 'Token usage in the last 7 days', query: 'range=7&activity_type=token_usage' },
    {
        id: 'failures', name: 'Document processing failures', description: 'Documents that failed or errored in the last 30 days',
        query: 'activity_type=document_creation&status=failed',
    },
];

const ROW = 'flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm transition-colors focus-visible:outline-2 focus-visible:outline-accent';
const ICON_BUTTON = 'inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-text-3 hover:bg-surface-2 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-accent';

export function ActivityViewsMenu({ views, currentQuery, unavailable, onApply, onSave, onRename, onDelete }: {
    views: ActivityLogSavedView[];
    currentQuery: string;
    /**
     * Why saved views cannot be changed right now. Set while the account's settings are
     * loading or failed to load, so a save cannot replace views it never read.
     */
    unavailable?: string;
    onApply: (query: string) => void;
    onSave: (name: string) => void;
    onRename: (id: string, name: string) => void;
    onDelete: (view: ActivityLogSavedView) => void;
}) {
    const popover = usePopover();
    const [name, setName] = useState('');
    const [editing, setEditing] = useState<{ id: string; name: string } | null>(null);
    const replaces = views.some((view) => view.name.toLowerCase() === name.trim().toLowerCase());
    const apply = (query: string) => {
        popover.close(true);
        onApply(query);
    };

    return (
        <div ref={popover.anchorRef} className="inline-flex">
            <button ref={popover.triggerRef} type="button" aria-haspopup="dialog" aria-expanded={popover.open}
                onClick={popover.toggle}
                className="glass-flat inline-flex h-8 items-center gap-1.5 rounded-xl px-3 text-sm font-medium text-text-1 transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent">
                <Bookmark size={14} aria-hidden="true" />Views<ChevronDown size={13} aria-hidden="true" />
            </button>
            {popover.open ? (
                <AnchoredPopover anchorRef={popover.anchorRef} label="Activity views" width={340} align="right"
                    onClose={(restoreFocus) => { setEditing(null); popover.close(restoreFocus); }}>
                    <div className="space-y-4">
                        <section>
                            <h3 className="mb-1 text-sm font-semibold text-text-1">Quick views</h3>
                            <ul className="space-y-0.5">
                                {QUICK_VIEWS.map((view) => (
                                    <li key={view.id}>
                                        <button type="button" className={clsx(ROW, 'flex-col items-start gap-0 hover:bg-surface-2',
                                            currentQuery === view.query && 'bg-accent-soft')}
                                            aria-current={currentQuery === view.query ? 'true' : undefined}
                                            onClick={() => apply(view.query)}>
                                            <span className="font-medium text-text-1">{view.name}</span>
                                            <span className="text-xs text-text-3">{view.description}</span>
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        </section>
                        <section className="border-t border-edge pt-3">
                            <h3 className="text-sm font-semibold text-text-1">Your saved views</h3>
                            <p className="mb-1 text-xs text-text-3">Saved to your account, so they are here on any browser.</p>
                            {unavailable ? (
                                <p role="status" className="py-1 text-sm text-text-2">{unavailable}</p>
                            ) : views.length ? (
                                <ul className="space-y-0.5">
                                    {views.map((view) => editing?.id === view.id ? (
                                        <li key={view.id}>
                                            <form className="flex items-center gap-1 px-1 py-1" onSubmit={(event) => {
                                                event.preventDefault();
                                                onRename(view.id, editing.name);
                                                setEditing(null);
                                            }}>
                                                <label className="sr-only" htmlFor={`rename-${view.id}`}>New name for {view.name}</label>
                                                <input id={`rename-${view.id}`} data-autofocus autoFocus value={editing.name} maxLength={MAX_ACTIVITY_VIEW_NAME_LENGTH}
                                                    onChange={(event) => setEditing({ id: view.id, name: event.target.value })}
                                                    className="h-8 min-w-0 flex-1 rounded-lg border border-edge bg-surface-1 px-2 text-sm text-text-1 focus:border-accent focus:outline-none" />
                                                <button type="submit" className={ICON_BUTTON} aria-label={`Save the new name for ${view.name}`}
                                                    disabled={!editing.name.trim()}><Check size={14} aria-hidden="true" /></button>
                                                <button type="button" className={ICON_BUTTON} aria-label="Cancel renaming"
                                                    onClick={() => setEditing(null)}><X size={14} aria-hidden="true" /></button>
                                            </form>
                                        </li>
                                    ) : (
                                        <li key={view.id} className="flex items-center gap-1">
                                            <button type="button" className={clsx(ROW, 'min-w-0 flex-1 hover:bg-surface-2',
                                                currentQuery === view.query && 'bg-accent-soft')}
                                                aria-current={currentQuery === view.query ? 'true' : undefined}
                                                onClick={() => apply(view.query)}>
                                                <span className="truncate text-text-1">{view.name}</span>
                                            </button>
                                            <button type="button" className={ICON_BUTTON} aria-label={`Rename saved view ${view.name}`}
                                                onClick={() => setEditing({ id: view.id, name: view.name })}><Pencil size={13} aria-hidden="true" /></button>
                                            <button type="button" className={ICON_BUTTON} aria-label={`Delete saved view ${view.name}`}
                                                onClick={() => onDelete(view)}><Trash2 size={13} aria-hidden="true" /></button>
                                        </li>
                                    ))}
                                </ul>
                            ) : <p className="py-1 text-sm text-text-3">No saved views yet. Save the current filters to reopen them later.</p>}
                        </section>
                        {unavailable ? null : <form className="space-y-2 border-t border-edge pt-3" onSubmit={(event) => {
                            event.preventDefault();
                            if (!name.trim()) return;
                            onSave(name);
                            setName('');
                        }}>
                            <label className="block text-xs font-medium text-text-2" htmlFor="activity-view-name">Save the current filters as</label>
                            <div className="flex gap-2">
                                <input id="activity-view-name" value={name} maxLength={MAX_ACTIVITY_VIEW_NAME_LENGTH} placeholder="View name"
                                    onChange={(event) => setName(event.target.value)}
                                    className="h-8 min-w-0 flex-1 rounded-lg border border-edge bg-surface-1 px-2 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none" />
                                <GlassButton type="submit" size="sm" variant="primary" disabled={!name.trim()}>Save view</GlassButton>
                            </div>
                            <p className="text-xs text-text-3">
                                {replaces ? 'Replaces the saved view with this name.'
                                    : `Relative ranges such as “Last 7 days” stay relative. Up to ${MAX_ACTIVITY_SAVED_VIEWS} views.`}
                            </p>
                        </form>}
                    </div>
                </AnchoredPopover>
            ) : null}
        </div>
    );
}
