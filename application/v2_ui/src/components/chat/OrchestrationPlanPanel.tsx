// OrchestrationPlanPanel.tsx
// The drawer's plan mode: the Run view and the Map view, and the rules for moving between runs.
//
// The hard part here is not the two views, it is making sure neither the user's browsing nor the
// system's work ever yanks the other's view away. The shown turn is `pinned?.turnId ?? current`:
// while nothing is pinned the panel follows the live turn, which is what someone watching work in
// progress wants; the moment they pin a run it stays put no matter what new run starts, which is
// what someone reading the past wants. The only way across that line is a button -- "Back to
// current", or the jump bar that appears when a run is live off-screen -- so a switch is always
// something the user chose. This is the same discipline the image-proposal drawer keeps, and it is
// here for the same reason: a panel that reorganises itself under the reader is worse than useless.

import { useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { ArrowDownToLine, ListTree, Map as MapIcon, Undo2 } from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import {
    selectActiveTurn,
    useOrchestrationStore,
    type TrackedRun,
} from '../../stores/orchestrationStore';
import { OrchestrationRunView } from './OrchestrationRunView';
import { OrchestrationMapView } from './OrchestrationMapView';

type PanelView = 'run' | 'map';

interface PinnedRun {
    turnId: string;
    runId: string;
}

/** Scroll a turn's question into view and flash it, matching the contents-drawer jump behaviour. */
function scrollToTurn(turnId: string, messages: ReturnType<typeof useChatStore.getState>['messages']) {
    // The turn id is stamped on the optimistic user bubble at submit and kept across the id
    // reconciliation, so a run always has a question to scroll back to even after it completes.
    const message = messages.find(
        (entry) =>
            entry.role === 'user' &&
            (entry.metadata as { orchestration_turn_id?: string } | undefined)
                ?.orchestration_turn_id === turnId,
    );
    if (!message) {
        return;
    }
    const element = document.getElementById(`message-${message.id}`);
    if (!element) {
        return;
    }
    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    element.classList.add('ring-2', 'ring-accent', 'rounded-2xl');
    window.setTimeout(() => {
        element.classList.remove('ring-2', 'ring-accent', 'rounded-2xl');
    }, 1400);
}

export function OrchestrationPlanPanel() {
    const activeConversationId = useChatStore((state) => state.activeConversationId) ?? '';
    const messages = useChatStore((state) => state.messages);
    const currentTurnId = useOrchestrationStore((state) =>
        selectActiveTurn(state, activeConversationId),
    );
    const inFlightMap = useOrchestrationStore((state) => state.inFlight);
    const pinRun = useOrchestrationStore((state) => state.pinRun);

    const [view, setView] = useState<PanelView>('run');
    const [pinned, setPinned] = useState<PinnedRun | null>(null);
    const headingRef = useRef<HTMLHeadingElement | null>(null);

    // Move focus into the panel when it opens, so a keyboard user is not left back on the toggle
    // that opened it.
    useEffect(() => {
        headingRef.current?.focus();
    }, []);

    const shownTurnId = pinned?.turnId ?? currentTurnId ?? null;

    // The newest run still in flight for this conversation, whichever turn it belongs to. Drives
    // the jump bar: a run is live "off-screen" when it exists and its turn is not the shown one.
    const liveRun = useMemo<TrackedRun | null>(() => {
        let newest: TrackedRun | null = null;
        for (const run of Object.values(inFlightMap)) {
            if (run.conversationId !== activeConversationId) {
                continue;
            }
            if (!newest || run.startedAt > newest.startedAt) {
                newest = run;
            }
        }
        return newest;
    }, [inFlightMap, activeConversationId]);

    const clearPin = () => {
        setPinned(null);
        pinRun(null);
    };

    const selectRun = (turnId: string, runId: string, live: boolean) => {
        setPinned({ turnId, runId });
        // Only a live run can be pinned in the store, whose pin resolves against in-flight records;
        // a settled run is browsed through this component's own pin instead.
        pinRun(live ? runId : null);
        setView('run');
        scrollToTurn(turnId, messages);
    };

    const showJumpBar = Boolean(pinned && liveRun && liveRun.turnId !== shownTurnId);

    return (
        <div className="flex h-full flex-col">
            <div className="flex items-center gap-2 border-b border-edge px-3 py-2">
                <h2
                    ref={headingRef}
                    tabIndex={-1}
                    className="text-sm font-medium text-text-1 focus:outline-none"
                >
                    Plan
                </h2>
                <div
                    role="tablist"
                    aria-label="Plan view"
                    className="ml-auto flex gap-1 rounded-lg bg-surface-sunken p-0.5"
                >
                    <button
                        type="button"
                        role="tab"
                        aria-selected={view === 'run'}
                        onClick={() => setView('run')}
                        className={clsx(
                            'inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs transition-colors',
                            view === 'run'
                                ? 'bg-surface-3 font-medium text-text-1'
                                : 'text-text-3 hover:text-text-1',
                        )}
                    >
                        <ListTree size={13} />
                        Run
                    </button>
                    <button
                        type="button"
                        role="tab"
                        aria-selected={view === 'map'}
                        onClick={() => setView('map')}
                        className={clsx(
                            'inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs transition-colors',
                            view === 'map'
                                ? 'bg-surface-3 font-medium text-text-1'
                                : 'text-text-3 hover:text-text-1',
                        )}
                    >
                        <MapIcon size={13} />
                        Map
                    </button>
                </div>
            </div>

            {pinned ? (
                <button
                    type="button"
                    onClick={clearPin}
                    className="flex items-center gap-1.5 border-b border-edge px-3 py-1.5 text-left text-xs text-text-3 hover:bg-surface-2 hover:text-text-1"
                >
                    <Undo2 size={12} />
                    Back to current
                </button>
            ) : null}

            {showJumpBar ? (
                // Non-silent by design: a live run never drags the view onto itself, it offers.
                <button
                    type="button"
                    onClick={clearPin}
                    className="flex items-center gap-1.5 border-b border-edge bg-accent-soft px-3 py-1.5 text-left text-xs text-accent hover:bg-accent-soft/80"
                >
                    <ArrowDownToLine size={12} />
                    A run is in progress — jump to it
                </button>
            ) : null}

            <div className="min-h-0 flex-1 overflow-y-auto">
                {view === 'run' ? (
                    shownTurnId ? (
                        <OrchestrationRunView
                            conversationId={activeConversationId}
                            turnId={shownTurnId}
                        />
                    ) : (
                        <p className="p-4 text-sm text-text-3">
                            No plan yet. Ask a question with orchestration on and the plan will
                            appear here.
                        </p>
                    )
                ) : (
                    <OrchestrationMapView
                        conversationId={activeConversationId}
                        shownTurnId={shownTurnId}
                        onSelectRun={selectRun}
                    />
                )}
            </div>
        </div>
    );
}
