// PublicDirectoryVisibilityTools.tsx
//
// The curation controls that sit above the public directory list: the bulk "show/hide every
// workspace in chat" actions, the two chat entry points, and saved visibility lists. These are
// the V2 port of the classic directory's bulk and saved-list buttons (static/js/public/
// public_directory.js), rebuilt on V2's visibility model where an empty map means every
// workspace is visible.
//
// This component is presentational: every write and every navigation is a handler the page owns,
// because only the page holds the settings store, the directory adapter and the bounded
// enumeration those actions need. It keeps just the two text fields a curator types into -- the
// new list's name and the chosen saved list -- and never touches settings itself.

import { useEffect, useState } from 'react';
import { ArrowUpRight, Eye, EyeOff, ListChecks, Loader2, Save, Trash2 } from 'lucide-react';
import { GlassButton, GlassPanel } from '../ui/primitives';

const FIELD_CLASS = 'min-w-0 flex-1 rounded-xl border border-edge bg-surface-solid px-3 py-2 text-sm text-text-1 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60';

interface PublicDirectoryVisibilityToolsProps {
    lowerSingular: string;
    lowerPlural: string;
    /** True once the user keeps a custom list rather than the "everything is visible" default. */
    customVisibility: boolean;
    savedListNames: string[];
    /** A bulk action or its directory enumeration is in flight; controls that write are held. */
    busy: boolean;
    /** The directory is still loading or empty, so there is nothing to act on yet. */
    disabled: boolean;
    onAllVisible: () => void;
    onAllHidden: () => void;
    onChatWithVisible: () => void;
    onSaveList: (name: string) => void;
    onUseList: (name: string) => void;
    onDeleteList: (name: string) => void;
}

export function PublicDirectoryVisibilityTools({
    lowerSingular, lowerPlural, customVisibility, savedListNames, busy, disabled,
    onAllVisible, onAllHidden, onChatWithVisible, onSaveList, onUseList, onDeleteList,
}: PublicDirectoryVisibilityToolsProps) {
    const [listName, setListName] = useState('');
    const [selected, setSelected] = useState('');

    // Keep the selection valid as lists are added or deleted: default to the first saved list, and
    // never leave a deleted name selected.
    useEffect(() => {
        setSelected((current) => (current && savedListNames.includes(current) ? current : (savedListNames[0] ?? '')));
    }, [savedListNames]);

    const acting = busy || disabled;
    const trimmedName = listName.trim();
    const canSave = !acting && trimmedName.length > 0;

    const saveList = () => {
        if (!canSave) return;
        onSaveList(trimmedName);
        setListName('');
    };

    return (
        <GlassPanel role="group" aria-label={`Chat visibility for ${lowerPlural}`} className="space-y-4 p-4">
            <div className="space-y-1">
                <h2 className="text-sm font-semibold text-text-1">Chat visibility</h2>
                <p className="text-xs text-text-3">
                    Choose which {lowerPlural} appear in the public chat. These actions cover every {lowerSingular}
                    {' '}in the directory, not just this page.
                </p>
            </div>

            <div className="space-y-2">
                <div className="flex flex-wrap gap-2">
                    <GlassButton size="sm" disabled={acting} onClick={onAllVisible}>
                        {busy ? <Loader2 size={14} className="animate-spin" /> : <Eye size={14} />}Show all in chat
                    </GlassButton>
                    <GlassButton size="sm" disabled={acting} onClick={onAllHidden}>
                        {busy ? <Loader2 size={14} className="animate-spin" /> : <EyeOff size={14} />}Hide all from chat
                    </GlassButton>
                </div>
                {customVisibility ? (
                    <p className="text-xs text-text-3">You keep a custom list. Only the {lowerPlural} left visible appear in chat.</p>
                ) : (
                    <p className="text-xs text-text-3">Every {lowerSingular} appears in chat by default.</p>
                )}
            </div>

            <div className="space-y-2 border-t border-edge pt-4">
                <GlassButton size="sm" disabled={disabled} onClick={onChatWithVisible}
                    aria-describedby="public-chat-actions-help">
                    Chat with visible (classic)<ArrowUpRight size={14} />
                </GlassButton>
                <p id="public-chat-actions-help" className="text-xs text-text-3">
                    Opens classic chat, searching the {lowerPlural} that are visible now. It changes nothing.
                    {' '}To chat with every {lowerSingular}, choose Show all in chat first.
                </p>
            </div>

            <div className="space-y-3 border-t border-edge pt-4">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-text-3">Saved lists</h3>
                <div className="flex flex-wrap items-center gap-2">
                    <label className="sr-only" htmlFor="public-saved-list-name">New saved list name</label>
                    <input id="public-saved-list-name" className={FIELD_CLASS} value={listName} disabled={acting}
                        placeholder="Name this visible set"
                        onChange={(event) => setListName(event.target.value)}
                        onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); saveList(); } }} />
                    <GlassButton size="sm" disabled={!canSave} onClick={saveList}>
                        <Save size={14} />Save current
                    </GlassButton>
                </div>
                {savedListNames.length > 0 ? (
                    <div className="flex flex-wrap items-center gap-2">
                        <label className="sr-only" htmlFor="public-saved-list-select">Saved list</label>
                        <select id="public-saved-list-select" className={FIELD_CLASS} value={selected} disabled={acting}
                            onChange={(event) => setSelected(event.target.value)}>
                            {savedListNames.map((name) => <option key={name} value={name}>{name}</option>)}
                        </select>
                        <GlassButton size="sm" disabled={acting || !selected} onClick={() => onUseList(selected)}>
                            <ListChecks size={14} />Use this list
                        </GlassButton>
                        <GlassButton size="sm" disabled={acting || !selected} onClick={() => onDeleteList(selected)}
                            aria-label={selected ? `Delete saved list ${selected}` : 'Delete saved list'}>
                            <Trash2 size={14} />Delete
                        </GlassButton>
                    </div>
                ) : (
                    <p className="text-xs text-text-3">No saved lists yet. Save the {lowerPlural} you have visible to reuse the set later.</p>
                )}
                {savedListNames.length > 0 ? (
                    <p className="text-xs text-text-3">Using a list makes only its {lowerPlural} visible and hides the rest.</p>
                ) : null}
            </div>
        </GlassPanel>
    );
}
