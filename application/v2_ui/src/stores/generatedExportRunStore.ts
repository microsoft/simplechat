// generatedExportRunStore.ts
// What the export cards have learned about background export runs, shared with the drawer.
//
// A large export runs in the background. Its card in the thread polls the run and, once the run
// finishes, replaces itself with the files it produced. That happens in the card's own state,
// which the Documents drawer cannot see, so without this the drawer would keep listing a finished
// export as still generating until the conversation was opened again.

import { create } from 'zustand';
import type { GeneratedExportRunState } from '../lib/conversationGeneratedFiles';

interface GeneratedExportRunStore {
    /** Keyed by export run id. */
    runs: Record<string, GeneratedExportRunState>;
    recordRun: (runId: string, patch: GeneratedExportRunState) => void;
}

export const useGeneratedExportRunStore = create<GeneratedExportRunStore>((set) => ({
    runs: {},
    recordRun: (runId, patch) => {
        const key = runId.trim();
        if (!key) {
            return;
        }
        set((state) => ({ runs: { ...state.runs, [key]: { ...state.runs[key], ...patch } } }));
    },
}));
