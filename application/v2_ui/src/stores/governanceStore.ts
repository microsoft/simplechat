// governanceStore.ts
// Which governance dialog is open, and a revision bumped whenever a policy is saved.
//
// Delegated item policies are edited from several places on the Admin Settings page: the
// Delegated Item Policies list, the MCP destination and Inbound MCP cards, the Inbound MCP
// shortcut, and an AI connection's Manage access action. Those are siblings drawn from a
// declarative schema, so no shared parent owns the editor. They leave a request here, one
// dialog host renders it, and every policy list refetches when the revision moves.

import { create } from 'zustand';
import type { GovernanceEntityType, ItemPolicyDraft } from '../lib/governance';

/** One resource whose access policies are listed together, such as one AI connection. */
export interface GovernanceResourceTarget {
    entityType: GovernanceEntityType;
    itemId: string;
    label: string;
}

export interface GovernanceEditorRequest {
    draft: ItemPolicyDraft;
    /** Entity types the editor may offer. Absent means every type. */
    entityTypes?: readonly GovernanceEntityType[];
    /** Reopen this resource's access list when the editor closes. */
    returnTo?: GovernanceResourceTarget;
}

export type GovernanceDialog =
    | { kind: 'editor'; id: number; request: GovernanceEditorRequest }
    | { kind: 'access'; id: number; target: GovernanceResourceTarget }
    | null;

interface GovernanceState {
    dialog: GovernanceDialog;
    /** Increments with every dialog opened, so each one mounts with fresh state. */
    sequence: number;
    revision: number;
    openEditor: (request: GovernanceEditorRequest) => void;
    openResourceAccess: (target: GovernanceResourceTarget) => void;
    /**
     * Close the dialog with this id.
     *
     * A dialog closes only itself, so a save that finishes after its dialog was replaced
     * cannot close whatever is open by then. An editor opened from a resource's access list
     * hands back to that list rather than closing outright, so only one dialog is ever on
     * screen: stacked dialogs would both answer Escape and close together.
     */
    close: (id: number) => void;
    markChanged: () => void;
}

export const useGovernanceStore = create<GovernanceState>((set) => ({
    dialog: null,
    sequence: 0,
    revision: 0,
    openEditor: (request) => set((state) => ({
        sequence: state.sequence + 1,
        dialog: { kind: 'editor', id: state.sequence + 1, request },
    })),
    openResourceAccess: (target) => set((state) => ({
        sequence: state.sequence + 1,
        dialog: { kind: 'access', id: state.sequence + 1, target },
    })),
    close: (id) => set((state) => {
        const dialog = state.dialog;
        if (!dialog || dialog.id !== id) {
            return state;
        }
        return dialog.kind === 'editor' && dialog.request.returnTo
            ? {
                sequence: state.sequence + 1,
                dialog: { kind: 'access', id: state.sequence + 1, target: dialog.request.returnTo },
            }
            : { dialog: null };
    }),
    markChanged: () => set((state) => ({ revision: state.revision + 1 })),
}));

/** Open the item policy editor. Safe to call from any handler. */
export const openGovernanceEditor = (request: GovernanceEditorRequest) =>
    useGovernanceStore.getState().openEditor(request);

/** List and manage the policies governing one resource. */
export const openGovernanceResourceAccess = (target: GovernanceResourceTarget) =>
    useGovernanceStore.getState().openResourceAccess(target);

/** Announce that stored policies changed, so every list refetches. */
export const governancePoliciesChanged = () => useGovernanceStore.getState().markChanged();
