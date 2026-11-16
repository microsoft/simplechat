// SaveBar.tsx
// Sticky bar summarising unsaved edits, with save and discard.
//
// The V2 admin surface buffers edits rather than saving each keystroke. That is not only a
// UI preference: Terms of Use and the AI notice derive a content version from their text
// and frequency, and every new version re-prompts every user. Saving per keystroke would
// mint a version per character.
//
// The unload guard covers the other half of buffering: edits that only exist in memory
// have to be defended when the tab is closed.

import { useEffect } from 'react';
import { clsx } from 'clsx';
import { Loader2, RotateCcw, Save } from 'lucide-react';
import { GlassButton } from '../ui/primitives';

export function SaveBar({
    dirtyCount,
    saving,
    onSave,
    onDiscard,
}: {
    dirtyCount: number;
    saving: boolean;
    onSave: () => void;
    onDiscard: () => void;
}) {
    const hasChanges = dirtyCount > 0;

    useEffect(() => {
        if (!hasChanges) {
            return;
        }
        const onBeforeUnload = (event: BeforeUnloadEvent) => {
            event.preventDefault();
            // Browsers ignore custom text now, but returnValue still triggers the prompt.
            event.returnValue = '';
        };
        window.addEventListener('beforeunload', onBeforeUnload);
        return () => window.removeEventListener('beforeunload', onBeforeUnload);
    }, [hasChanges]);

    // Ctrl/Cmd+S is what an administrator editing a form will reach for.
    useEffect(() => {
        if (!hasChanges || saving) {
            return;
        }
        const onKeyDown = (event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
                event.preventDefault();
                onSave();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [hasChanges, saving, onSave]);

    if (!hasChanges) {
        return null;
    }

    return (
        <div
            role="status"
            className={clsx(
                'sticky bottom-0 z-10 mt-4 flex items-center gap-3 rounded-xl',
                'glass-raised glass-edge border border-edge px-4 py-3',
            )}
        >
            <p className="min-w-0 flex-1 text-sm text-text-2">
                <span className="font-medium text-text-1">
                    {dirtyCount} unsaved change{dirtyCount === 1 ? '' : 's'}
                </span>
            </p>

            <GlassButton
                type="button"
                variant="ghost"
                size="sm"
                disabled={saving}
                onClick={onDiscard}
            >
                <RotateCcw size={14} />
                Discard
            </GlassButton>

            <GlassButton
                type="button"
                variant="primary"
                size="sm"
                disabled={saving}
                onClick={onSave}
            >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                {saving ? 'Saving…' : 'Save changes'}
            </GlassButton>
        </div>
    );
}
