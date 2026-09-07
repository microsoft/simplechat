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
import { AlertCircle, ArrowDownToLine, ListTree, Loader2, Map as MapIcon, PenLine, Undo2 } from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import {
    selectActiveTurn,
    selectCanEditPlan,
    selectPlan,
    useOrchestrationStore,
    type StepRuntimeMap,
    type TrackedRun,
} from '../../stores/orchestrationStore';
import { fetchOrchestrationRun, fetchRunSteps, type OrchestrationPlan } from '../../lib/orchestration';
import { normalizePlan } from '../../lib/orchestrationPlan';
import { openOrchestrationPlanEditor } from '../../lib/orchestrationController';
import { GlassButton } from '../ui/primitives';
import { OrchestrationRunView } from './OrchestrationRunView';
import { OrchestrationMapView } from './OrchestrationMapView';

type PanelView = 'run' | 'map';

interface PinnedRun {
    turnId: string;
    runId: string;
}

/** Mirror of the store's private scope key; the NUL separator must match `orchestrationStore`. */
function scopeKey(conversationId: string, turnId: string): string {
    return `${conversationId}\u0000${turnId}`;
}

/**
 * Scroll a turn's question into view and flash it, matching the contents-drawer jump behaviour.
 *
 * Two ways to find the question, because there are two kinds of run. A run this page started
 * stamped its turn id on the user bubble at submit and kept it across the id reconciliation. A run
 * restored from the server has no such stamp on messages written before that stamping existed, so
 * the stored record's own `user_message_id` is used as a fallback -- which is also the only handle
 * available for a run that happened on another device entirely.
 */
function scrollToTurn(
    turnId: string,
    userMessageId: string | null,
    messages: ReturnType<typeof useChatStore.getState>['messages'],
) {
    const message =
        messages.find(
            (entry) =>
                entry.role === 'user' &&
                (entry.metadata as { orchestration_turn_id?: string } | undefined)
                    ?.orchestration_turn_id === turnId,
        ) ??
        (userMessageId
            ? messages.find((entry) => entry.role === 'user' && entry.id === userMessageId)
            : undefined);
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
    /** The archived run currently being fetched, so the Run view can say so instead of sitting empty. */
    const [loadingRunId, setLoadingRunId] = useState<string | null>(null);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [archivedPreview, setArchivedPreview] = useState<{
        runId: string; plan: OrchestrationPlan; runtime: StepRuntimeMap;
    } | null>(null);
    const archiveRequest = useRef<object | null>(null);
    const headingRef = useRef<HTMLHeadingElement | null>(null);

    // Move focus into the panel when it opens, so a keyboard user is not left back on the toggle
    // that opened it.
    useEffect(() => {
        headingRef.current?.focus();
    }, []);

    const shownTurnId = pinned?.turnId ?? currentTurnId ?? null;
    const shownPlan = useOrchestrationStore((state) => selectPlan(state, activeConversationId, shownTurnId ?? ''));
    const canEdit = useOrchestrationStore((state) => selectCanEditPlan(state, activeConversationId, shownTurnId ?? ''));

    useEffect(() => {
        archiveRequest.current = null;
        setPinned(null);
        setArchivedPreview(null);
        setLoadingRunId(null);
        setLoadError(null);
        pinRun(null);
        return () => { archiveRequest.current = null; };
    }, [activeConversationId, pinRun]);

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
        archiveRequest.current = null;
        setPinned(null);
        setArchivedPreview(null);
        setLoadingRunId(null);
        setLoadError(null);
        pinRun(null);
    };

    /**
     * Fetch an archived run's plan and step outcomes, then adopt them for display.
     *
     * Only reached for a run this page never watched, so there is nothing in memory to draw. The
     * plan is adopted read-only: it is a record of what happened, and offering to narrow the steps
     * of a run that already finished would be offering something that cannot be done.
     */
    const loadArchivedRun = (turnId: string, runId: string) => {
        const request = {};
        archiveRequest.current = request;
        const isCurrent = () => archiveRequest.current === request
            && useChatStore.getState().activeConversationId === activeConversationId;
        setLoadingRunId(runId);
        setLoadError(null);
        Promise.all([
            fetchOrchestrationRun(runId, { conversationId: activeConversationId }),
            fetchRunSteps(runId, { conversationId: activeConversationId }),
        ])
            .then(([run, steps]) => {
                if (!isCurrent()) {
                    return;
                }
                const plan = normalizePlan(run?.plan);
                if (!plan) {
                    setLoadError('This run did not keep a plan.');
                    return;
                }
                const store = useOrchestrationStore.getState();
                const current = selectPlan(store, activeConversationId, turnId);
                if (current && (current.run_id !== runId
                    || selectCanEditPlan(store, activeConversationId, turnId))) {
                    const runtime: StepRuntimeMap = {};
                    for (const step of steps) {
                        runtime[step.step_id] = { status: step.status ?? 'pending', summary: step.summary ?? '' };
                    }
                    setArchivedPreview({ runId, plan, runtime });
                } else {
                    store.adoptPersistedPlan(activeConversationId, turnId, run?.plan, steps, {
                        readOnly: true,
                    });
                }
            })
            .catch(() => {
                if (isCurrent()) setLoadError('This run could not be loaded.');
            })
            .finally(() => {
                if (isCurrent()) setLoadingRunId(null);
            });
    };

    const selectRun = (turnId: string, runId: string, live: boolean) => {
        setPinned({ turnId, runId });
        archiveRequest.current = null;
        setArchivedPreview(null);
        setLoadError(null);
        // Only a live run can be pinned in the store, whose pin resolves against in-flight records;
        // a settled run is browsed through this component's own pin instead.
        pinRun(live ? runId : null);
        setView('run');

        const store = useOrchestrationStore.getState();
        const entry = (store.hydratedHistory[activeConversationId] ?? []).find(
            (candidate) => candidate.runId === runId,
        );
        scrollToTurn(turnId, entry?.userMessageId ?? null, messages);

        // A live run is streaming its plan in; anything already in memory is authoritative.
        if (live || store.plans[scopeKey(activeConversationId, turnId)]?.run_id === runId) {
            return;
        }
        loadArchivedRun(turnId, runId);
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

            {view === 'run' && canEdit && shownTurnId && (!pinned || pinned.runId === shownPlan?.run_id) ? (
                <div className="border-b border-edge px-3 py-2">
                    <GlassButton size="sm" variant="subtle" aria-label="Edit the plan"
                        onClick={() => {
                            clearPin();
                            void openOrchestrationPlanEditor({
                                conversationId: activeConversationId, turnId: shownTurnId,
                            });
                        }}>
                        <PenLine size={14} aria-hidden="true" />
                        Edit
                    </GlassButton>
                </div>
            ) : null}
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
                    loadingRunId && loadingRunId === pinned?.runId ? (
                        <p className="flex items-center gap-2 p-4 text-sm text-text-3">
                            <Loader2 size={14} className="animate-spin" />
                            Loading this run&hellip;
                        </p>
                    ) : loadError ? (
                        <p className="flex items-center gap-2 p-4 text-sm text-danger">
                            <AlertCircle size={14} />
                            {loadError}
                        </p>
                    ) : shownTurnId ? (
                        <OrchestrationRunView
                            conversationId={activeConversationId}
                            turnId={shownTurnId}
                            previewPlan={archivedPreview?.runId === pinned?.runId ? archivedPreview?.plan : undefined}
                            previewRuntime={archivedPreview?.runId === pinned?.runId ? archivedPreview?.runtime : undefined}
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
