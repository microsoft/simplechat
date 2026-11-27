// contextUsageStore.ts
// The model the composer has selected, with the limits the server resolved for it.
//
// The composer owns its model selection as local state, but the context ring in the chat header
// and the drawer's Context tab need it too: the moment someone picks another model, the same
// conversation fills a different share of a different window. The composer publishes its choice
// here. It publishes null while an agent is selected, because an agent runs on its own model.

import { create } from 'zustand';
import type { SelectedContextModel } from '../lib/contextUsage';

interface ContextUsageState {
    selectedModel: SelectedContextModel | null;
    setSelectedModel: (selectedModel: SelectedContextModel | null) => void;
}

export const useContextUsageStore = create<ContextUsageState>((set) => ({
    selectedModel: null,
    setSelectedModel: (selectedModel) => set({ selectedModel }),
}));
