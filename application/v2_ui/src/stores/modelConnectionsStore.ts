// modelConnectionsStore.ts
// A revision counter bumped whenever the global model connection list is written.
//
// Connections and the settings that depend on them are edited side by side in one Admin
// Settings view, so a component that loads the connection list once goes stale as soon as
// the list next to it changes: adding a connection, enabling a model, or deleting one all
// alter what the default model picker may offer, and deleting one also makes the server
// clear a default that named it.
//
// The two components are siblings rendered from a declarative field schema rather than
// parent and child, so there is no prop to pass between them. A revision is enough --
// readers refetch rather than being handed data, which keeps the sanitized fetch as the
// single source of what a connection looks like.

import { create } from 'zustand';

interface ModelConnectionsState {
    revision: number;
    markChanged: () => void;
}

export const useModelConnectionsStore = create<ModelConnectionsState>((set) => ({
    revision: 0,
    markChanged: () => set((state) => ({ revision: state.revision + 1 })),
}));

/** Announce that the stored connection list has changed. Safe to call from any handler. */
export const modelConnectionsChanged = () => useModelConnectionsStore.getState().markChanged();
