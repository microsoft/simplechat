// userInputStore.ts

import { create } from 'zustand';
import { createElicitationDraft, type ElicitationDraft } from '../lib/elicitationAnswers';
import type { Elicitation, ElicitationResponse } from '../lib/orchestration';
import type { ConversationKind } from '../lib/endpoints';

export interface UserInputRequest {
    id: string;
    actor_id: string;
    revision: number;
    conversation_id: string;
    conversation_kind: ConversationKind;
    question: Elicitation;
    status: 'pending' | 'answered' | 'continuing' | 'completed' | 'cancelled' | 'superseded' | 'failed';
    agent_name: string;
    run_id?: string;
    turn_id?: string;
    step_id?: string;
    submission_id?: string;
    response?: ElicitationResponse;
    cancel_requested?: boolean;
}

interface UserInputState {
    actorId: string | null;
    records: Record<string, { request: UserInputRequest; draft: ElicitationDraft }>;
    setActor: (actorId: string | null) => void;
    accept: (request: UserInputRequest) => void;
    update: (id: string, update: (draft: ElicitationDraft) => ElicitationDraft) => void;
    remove: (id: string) => void;
}

export const useUserInputStore = create<UserInputState>((set) => ({
    actorId: null,
    records: {},
    setActor: (actorId) => set((state) => state.actorId === actorId ? state : { actorId, records: {} }),
    accept: (request) => {
        if (!request || typeof request.id !== 'string' || typeof request.actor_id !== 'string'
            || typeof request.conversation_id !== 'string'
            || request.question?.elicitation_id !== request.id || request.question.revision !== request.revision
            || !request.question.requested_schema?.properties || !request.question.ui_hints) {
            throw new Error('The question could not be read. Reload this conversation.');
        }
        set((state) => {
            if (!state.actorId || request.actor_id !== state.actorId) return state;
            const previous = state.records[request.id];
            return { records: { ...state.records, [request.id]: {
                request,
                draft: previous?.request.revision === request.revision
                    ? previous.draft : createElicitationDraft(request.question),
            } } };
        });
    },
    update: (id, update) => set((state) => {
        const current = state.records[id];
        return current ? { records: { ...state.records, [id]: { ...current, draft: update(current.draft) } } } : state;
    }),
    remove: (id) => set((state) => {
        const records = { ...state.records };
        delete records[id];
        return { records };
    }),
}));
