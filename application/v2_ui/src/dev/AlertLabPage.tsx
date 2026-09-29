// AlertLabPage.tsx
// The workflow alert lab: sample workflow alerts shown by the real notice and card, inside the
// real application shell, for trying changes to them without a workflow to trigger.
//
// Dev only. App.tsx registers the route only when import.meta.env.DEV, so a production build
// drops this page and its samples entirely (roadmap gotcha 57), and a build check searches
// the bundle for LAB_MARKER to prove it.
//
// While the lab is open it feeds the notice itself: the server feed is paused, and the card's
// read, dismiss and open actions are swapped for ones that only record what they would have
// done. Leaving the page puts both back.

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { Eraser, FlaskConical, RotateCcw, Smartphone } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassButton, GlassPanel, Toggle } from '../components/ui/primitives';
import { Modal } from '../components/ui/Modal';
import type { NotificationTarget } from '../lib/notificationLinks';
import { setWorkflowAlertFeedPaused } from '../lib/useWorkflowAlertRuntime';
import type { WorkflowAlertActions } from '../lib/workflowAlertActions';
import { prefersReducedMotion, setWorkflowAlertMotionOverride } from '../lib/workflowAlertMotion';
import {
    WORKFLOW_ALERT_PRIORITY_LABELS,
    isWorkflowAlertPopupEligible,
    readWorkflowAlert,
    type WorkflowAlert,
} from '../lib/workflowAlertNotices';
import type { WorkflowAlertSeverity } from '../lib/workflowAlerts';
import { toast } from '../stores/toastStore';
import { useUiStore } from '../stores/uiStore';
import {
    resetWorkflowAlertsForLab,
    setWorkflowAlertActions,
    useWorkflowAlertStore,
    type WorkflowAlertNoticeStyle,
} from '../stores/workflowAlertStore';
import {
    alertLabScenarioAlerts,
    alertLabScenarios,
    alertLabSeverities,
    alertLabSingle,
    type AlertLabScenarioId,
} from './alertLabSamples';

/** Marks the lab in the page. The production build check searches the bundle for this text. */
const LAB_MARKER = 'simplechat-dev-alert-lab';

type MotionChoice = 'system' | 'reduce' | 'full';

interface Choice<T extends string> {
    value: T;
    label: string;
}

function Segmented<T extends string>({
    label,
    value,
    choices,
    onChange,
    disabled = false,
}: {
    label: string;
    value: T;
    choices: Choice<T>[];
    onChange: (next: T) => void;
    disabled?: boolean;
}) {
    return (
        <div className="space-y-1.5">
            <span className="block text-xs font-medium text-text-2">{label}</span>
            <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
                {choices.map((choice) => (
                    <button
                        key={choice.value}
                        type="button"
                        role="radio"
                        aria-checked={choice.value === value}
                        disabled={disabled}
                        onClick={() => onChange(choice.value)}
                        className={clsx(
                            'rounded-lg border px-3 py-1.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                            choice.value === value
                                ? 'border-accent bg-accent-soft font-medium text-accent'
                                : 'border-edge text-text-2 hover:bg-surface-2 hover:text-text-1',
                        )}
                    >
                        {choice.label}
                    </button>
                ))}
            </div>
        </div>
    );
}

function Section({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
    return (
        <GlassPanel elevation="flat" className={clsx('space-y-3 p-4', className)}>
            <h2 className="text-sm font-semibold text-text-1">{title}</h2>
            {children}
        </GlassPanel>
    );
}

function describeTarget(target: NotificationTarget): string {
    if (target.kind === 'conversation') {
        return `the conversation ${target.conversationId}`;
    }
    if (target.kind === 'route') {
        return `/v2${target.path}`;
    }
    return target.href;
}

export function AlertLabPage() {
    const style = useWorkflowAlertStore((state) => state.style);
    const setStyle = useWorkflowAlertStore((state) => state.setStyle);
    const phase = useWorkflowAlertStore((state) => state.phase);
    const entryCount = useWorkflowAlertStore((state) => state.entries.length);
    const alertCount = useWorkflowAlertStore((state) => state.entries.reduce((total, entry) => total + entry.count, 0));
    const waiting = useWorkflowAlertStore((state) => state.queue.length);
    const suspended = useWorkflowAlertStore((state) => state.suspended);
    const theme = useUiStore((state) => state.theme);
    const setTheme = useUiStore((state) => state.setTheme);
    const railCollapsed = useUiStore((state) => state.railCollapsed);
    const toggleRail = useUiStore((state) => state.toggleRail);
    const [motion, setMotion] = useState<MotionChoice>('system');
    const [failActions, setFailActions] = useState(false);
    const [dialogOpen, setDialogOpen] = useState(false);
    const [log, setLog] = useState<string[]>([]);
    const [phone] = useState(() => window.matchMedia('(max-width: 767px)').matches);
    const failRef = useRef(false);
    const counter = useRef(0);
    const lastFeed = useRef<(() => void) | null>(null);
    const dialogTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

    const note = useCallback((line: string) => {
        setLog((lines) => [line, ...lines].slice(0, 10));
    }, []);

    useEffect(() => {
        failRef.current = failActions;
    }, [failActions]);

    // Take the notice over while the lab is open, and hand it back on the way out.
    useEffect(() => {
        const styleBefore = useWorkflowAlertStore.getState().style;
        const refuse = (verb: string): string[] => {
            toast.error(`Lab: the server refused to ${verb} the alert.`);
            note(`Refused to ${verb}.`);
            return [];
        };
        const labActions: WorkflowAlertActions = {
            markRead: async (ids) => {
                if (failRef.current) {
                    return refuse('mark read');
                }
                note(`Marked read: ${ids.length} alert${ids.length === 1 ? '' : 's'}.`);
                return ids;
            },
            dismiss: async (ids) => {
                if (failRef.current) {
                    return refuse('dismiss');
                }
                note(`Dismissed: ${ids.length} alert${ids.length === 1 ? '' : 's'}.`);
                return ids;
            },
            open: async (target) => {
                const where = describeTarget(target);
                note(`Would open ${where}.`);
                toast.info(`Lab: would open ${where}.`);
            },
        };
        setWorkflowAlertFeedPaused(true);
        setWorkflowAlertActions(labActions);
        resetWorkflowAlertsForLab();
        return () => {
            if (dialogTimer.current !== null) {
                clearTimeout(dialogTimer.current);
            }
            resetWorkflowAlertsForLab();
            setWorkflowAlertActions(null);
            setWorkflowAlertMotionOverride(null);
            setWorkflowAlertFeedPaused(false);
            useWorkflowAlertStore.getState().setStyle(styleBefore);
        };
    }, [note]);

    const chooseMotion = (next: MotionChoice) => {
        setMotion(next);
        setWorkflowAlertMotionOverride(next === 'system' ? null : next === 'reduce');
    };

    const send = useCallback((label: string, build: (stamp: string, now: number) => Record<string, unknown>[]) => {
        const run = () => {
            counter.current += 1;
            const now = Date.now();
            const stamp = `${now.toString(36)}${counter.current.toString(36)}`;
            const alerts = build(stamp, now)
                .map(readWorkflowAlert)
                .filter((alert): alert is WorkflowAlert => alert !== null);
            const held = alerts.filter((alert) => !isWorkflowAlertPopupEligible(alert, now)).length;
            note(`${label}: ${alerts.length} sent${held ? `, ${held} left in the bell` : ''}.`);
            useWorkflowAlertStore.getState().receiveAlerts(alerts);
        };
        lastFeed.current = run;
        run();
    }, [note]);

    const runScenario = (id: AlertLabScenarioId, label: string) => {
        if (id !== 'dialog') {
            send(label, (stamp, now) => alertLabScenarioAlerts(id, stamp, now));
            return;
        }
        setDialogOpen(true);
        // Sent once the dialog is on screen, so the alert has something to wait for.
        dialogTimer.current = setTimeout(() => {
            dialogTimer.current = null;
            send(label, (stamp, now) => alertLabScenarioAlerts(id, stamp, now));
        }, 400);
    };

    const runSingle = (priority: WorkflowAlertSeverity, category: 'alert' | 'failure') => {
        const label = `${WORKFLOW_ALERT_PRIORITY_LABELS[priority]} ${category === 'failure' ? 'run failed' : 'alert'}`;
        send(label, (stamp, now) => alertLabSingle(stamp, now, priority, category));
    };

    const clear = () => {
        resetWorkflowAlertsForLab();
        note('Cleared.');
    };

    const openPhoneWindow = () => {
        window.open(window.location.href, 'simplechat-alert-lab-phone', 'popup=yes,width=360,height=760');
    };

    const systemReduced = motion === 'system' ? prefersReducedMotion() : null;

    return (
        <div data-dev-lab={LAB_MARKER} className="flex min-h-0 flex-1 flex-col">
            <PageHeader
                title="Alert lab"
                description="Dev only. Sample workflow alerts in the real shell; nothing reaches the server."
                leading={<FlaskConical size={18} className="text-accent" aria-hidden="true" />}
                actions={(
                    <>
                        <GlassButton type="button" size="sm" variant="subtle" onClick={() => lastFeed.current?.()} disabled={!lastFeed.current}>
                            <RotateCcw size={14} aria-hidden="true" />
                            Replay
                        </GlassButton>
                        <GlassButton type="button" size="sm" variant="subtle" onClick={clear}>
                            <Eraser size={14} aria-hidden="true" />
                            Clear
                        </GlassButton>
                    </>
                )}
            />
            <div className="min-h-0 flex-1 overflow-y-auto p-4 md:p-5">
                <div className="mx-auto grid max-w-5xl gap-4 lg:grid-cols-2">
                    <Section title="Notice">
                        <Segmented<WorkflowAlertNoticeStyle>
                            label="Entrance style"
                            value={style}
                            onChange={setStyle}
                            choices={[
                                { value: 'callout', label: 'A · Sidebar callout' },
                                { value: 'pill', label: 'B · Top-center pill' },
                            ]}
                        />
                        <Segmented<'light' | 'dark'>
                            label="Theme"
                            value={theme}
                            onChange={setTheme}
                            choices={[{ value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }]}
                        />
                        <Segmented<'expanded' | 'collapsed'>
                            label={phone ? 'Rail (a phone always shows the icon strip)' : 'Rail'}
                            value={railCollapsed ? 'collapsed' : 'expanded'}
                            disabled={phone}
                            onChange={(next) => {
                                if ((next === 'collapsed') !== railCollapsed) {
                                    toggleRail();
                                }
                            }}
                            choices={[{ value: 'expanded', label: 'Expanded' }, { value: 'collapsed', label: 'Collapsed' }]}
                        />
                        <Segmented<MotionChoice>
                            label={systemReduced === null ? 'Motion' : `Motion (system: ${systemReduced ? 'reduced' : 'full'})`}
                            value={motion}
                            onChange={chooseMotion}
                            choices={[
                                { value: 'system', label: 'System' },
                                { value: 'reduce', label: 'Reduced' },
                                { value: 'full', label: 'Full' },
                            ]}
                        />
                        <div className="space-y-1.5">
                            <span className="block text-xs font-medium text-text-2">Viewport</span>
                            <GlassButton type="button" size="sm" variant="subtle" onClick={openPhoneWindow}>
                                <Smartphone size={14} aria-hidden="true" />
                                Open a 360 px window
                            </GlassButton>
                            <p className="text-xs text-text-3">
                                A browser may keep a pop-up wider than asked; its device toolbar gives an exact size.
                            </p>
                        </div>
                    </Section>

                    <Section title="State">
                        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                            <dt className="text-text-3">Phase</dt>
                            <dd data-lab-phase={phase} className="font-medium text-text-1">{phase}</dd>
                            <dt className="text-text-3">Showing</dt>
                            <dd className="text-text-1">
                                {entryCount} {entryCount === 1 ? 'entry' : 'entries'}, {alertCount} {alertCount === 1 ? 'alert' : 'alerts'}
                            </dd>
                            <dt className="text-text-3">Waiting to be claimed</dt>
                            <dd className="text-text-1">{waiting}</dd>
                            <dt className="text-text-3">Held back</dt>
                            <dd className="text-text-1">{suspended ? 'Yes: a dialog, the mobile menu or a hidden tab' : 'No'}</dd>
                        </dl>
                        <Toggle
                            checked={failActions}
                            onChange={setFailActions}
                            label="Refuse read and dismiss"
                            description="The card's actions fail, as they would if the server refused them."
                        />
                        <div>
                            <h3 className="text-xs font-medium text-text-2">What happened</h3>
                            {log.length ? (
                                <ol className="mt-1.5 space-y-1 text-xs text-text-2" aria-live="polite">
                                    {log.map((line, index) => (
                                        <li key={`${index}-${line}`} className="break-words">{line}</li>
                                    ))}
                                </ol>
                            ) : (
                                <p className="mt-1.5 text-xs text-text-3">Send a sample to begin.</p>
                            )}
                        </div>
                    </Section>

                    <Section title="Scenarios" className="lg:col-span-2">
                        <ul className="grid gap-2 sm:grid-cols-2">
                            {alertLabScenarios().map((scenario) => (
                                <li key={scenario.id} className="flex items-start gap-3">
                                    <GlassButton
                                        type="button"
                                        size="sm"
                                        variant="subtle"
                                        className="shrink-0"
                                        data-lab-scenario={scenario.id}
                                        onClick={() => runScenario(scenario.id, scenario.label)}
                                    >
                                        {scenario.label}
                                    </GlassButton>
                                    <span className="pt-1.5 text-xs text-text-3">{scenario.expect}</span>
                                </li>
                            ))}
                        </ul>
                    </Section>

                    <Section title="One alert at each priority" className="lg:col-span-2">
                        <table className="w-full max-w-md text-sm">
                            <thead>
                                <tr className="text-left text-xs text-text-3">
                                    <th scope="col" className="pb-1.5 font-medium">Priority</th>
                                    <th scope="col" className="pb-1.5 font-medium">Alert</th>
                                    <th scope="col" className="pb-1.5 font-medium">Run failed</th>
                                </tr>
                            </thead>
                            <tbody>
                                {alertLabSeverities().map((priority) => (
                                    <tr key={priority}>
                                        <th scope="row" className="py-1 pr-3 text-left font-medium text-text-1">
                                            {WORKFLOW_ALERT_PRIORITY_LABELS[priority]}
                                        </th>
                                        {(['alert', 'failure'] as const).map((category) => (
                                            <td key={category} className="py-1 pr-3">
                                                <GlassButton
                                                    type="button"
                                                    size="sm"
                                                    variant="ghost"
                                                    data-lab-single={`${priority}-${category}`}
                                                    aria-label={`Show a ${priority} priority ${category === 'failure' ? 'failed run' : 'alert'}`}
                                                    onClick={() => runSingle(priority, category)}
                                                >
                                                    Show
                                                </GlassButton>
                                            </td>
                                        ))}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </Section>
                </div>
            </div>
            {dialogOpen && (
                <Modal
                    title="A dialog is open"
                    onClose={() => setDialogOpen(false)}
                    footer={(
                        <GlassButton type="button" variant="primary" size="sm" onClick={() => setDialogOpen(false)}>
                            Close dialog
                        </GlassButton>
                    )}
                >
                    <p className="text-sm text-text-2">
                        An alert was sent while this dialog is open. It waits, and the notice arrives once the dialog closes.
                    </p>
                </Modal>
            )}
        </div>
    );
}
