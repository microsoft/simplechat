// ActivityPendingAction.tsx
// The saved Microsoft 365 email or invitation an activity stands for, beside the run that saved it.
//
// A workflow that prepares a message for review saves it as a pending action that waits for its
// owner to send or cancel it. The activity timeline lists that wait as an activity, and the server
// sends the action itself with it. It is drawn with the card the chat draws under the reply that
// saved an action, and Approvals draws for one, so Send and Cancel carry the version that was
// reviewed, the server's answer is the one that counts, and nothing is ever sent by the browser on
// its own. Opening this page never sends anything.
//
// The card keeps its own store, as Approvals' detail does, because this page shows one action at a
// time and the chat's shared store belongs to the chat. Each snapshot is handed to it as the
// snapshot it is, not as a server-confirmed read, so the store still checks anything it is about
// to send against the server. When the card learns something newer than the snapshot, the page is
// told, so the timeline and the card never disagree for long.

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { PendingAction } from '../../lib/approvalsApi';
import { createPendingActionsStore, PendingActionsProvider } from '../../stores/m365PendingActionsStore';
import { PendingActionCard } from '../approvals/PendingActionCard';

export function ActivityPendingAction({
    action,
    onChanged,
}: {
    action: PendingAction;
    /** The card holds an action that differs from the one in the snapshot. */
    onChanged: (action: PendingAction) => void;
}) {
    const changed = useRef(onChanged);
    changed.current = onChanged;
    const [store] = useState(() =>
        createPendingActionsStore({ scope: 'detail', onUpdated: (next) => changed.current(next) }),
    );

    // Before paint, so the card never flashes in empty.
    useLayoutEffect(() => {
        store.getState().remember(action);
    }, [action, store]);

    // The owner may have sent or cancelled it from another window while this one was in the back.
    useEffect(() => {
        const refresh = () => {
            void store.getState().refresh(action.id);
        };
        window.addEventListener('focus', refresh);
        window.addEventListener('online', refresh);
        return () => {
            window.removeEventListener('focus', refresh);
            window.removeEventListener('online', refresh);
        };
    }, [action.id, store]);

    useEffect(() => () => store.getState().reset(), [store]);

    return (
        <PendingActionsProvider store={store}>
            <PendingActionCard id={action.id} variant="inline" />
        </PendingActionsProvider>
    );
}
