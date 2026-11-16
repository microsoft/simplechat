// useSaveFirst.tsx
// Run an action that needs saved backup settings, saving them first when they are not.
//
// Queueing a backup, running retention cleanup, reviewing or queueing a restore and
// starting a migration all act on the *saved* data-management settings: the server reads
// them again, and the review fingerprints are checked against them. The classic page saves
// its settings before each of these, and so does this.
//
// One case needs the administrator: backup storage is validated against the Enhanced
// Citations storage in the saved main settings. When those have unsaved edits, saving only
// the backup settings would check them against values about to change, so the
// administrator is asked to save everything first.

import { useCallback, useRef, useState, type ReactNode } from 'react';
import { Save } from 'lucide-react';
import { ConfirmDialog } from '../../ui/ConfirmDialog';
import { toast } from '../../../stores/toastStore';
import { useDataManagementStore, type ReadinessPurpose } from '../../../stores/dataManagementStore';

export function useSaveFirst(): {
    /** Resolves true when the action may go ahead against saved settings. */
    ensure: (purpose: ReadinessPurpose) => Promise<boolean>;
    /** The confirmation shown when other unsaved settings must be saved first. */
    dialog: ReactNode;
} {
    const [prompt, setPrompt] = useState<{ message: string; purpose: ReadinessPurpose } | null>(null);
    const [busy, setBusy] = useState(false);
    const resolver = useRef<((ready: boolean) => void) | null>(null);

    const settle = (ready: boolean) => {
        resolver.current?.(ready);
        resolver.current = null;
        setPrompt(null);
    };

    const ensure = useCallback(async (purpose: ReadinessPurpose) => {
        const result = await useDataManagementStore.getState().ensureReadyFor(purpose);
        if (result.ok) return true;
        if (result.reason === 'save-all-required') {
            resolver.current?.(false);
            return new Promise<boolean>((resolve) => {
                resolver.current = resolve;
                setPrompt({ message: result.message, purpose });
            });
        }
        toast.error(result.message);
        return false;
    }, []);

    const confirm = async () => {
        if (!prompt) return;
        const handler = useDataManagementStore.getState().saveAllHandler;
        setBusy(true);
        try {
            const saved = handler ? await handler() : false;
            if (!saved) {
                settle(false);
                return;
            }
            const again = await useDataManagementStore.getState().ensureReadyFor(prompt.purpose);
            if (!again.ok) toast.error(again.message);
            settle(again.ok);
        } finally {
            setBusy(false);
        }
    };

    const dialog = prompt ? (
        <ConfirmDialog
            title="Save all changes first?"
            description={prompt.message}
            confirmLabel="Save all and continue"
            confirmIcon={<Save size={14} aria-hidden="true" />}
            tone="primary"
            busy={busy}
            onConfirm={() => void confirm()}
            onClose={() => {
                if (!busy) settle(false);
            }}
        >
            <p className="text-xs text-text-2">
                Everything in the Save bar is saved, then the action continues.
            </p>
        </ConfirmDialog>
    ) : null;

    return { ensure, dialog };
}
