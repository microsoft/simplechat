// DataManagementMigration.tsx
// Migration keeps the rail and step selection outside the panels so the wizard survives card unmounts while every high-risk action stays in its focused step.

import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, ChevronLeft, ChevronRight, HelpCircle, Lock, TriangleAlert } from 'lucide-react';
import { clsx } from 'clsx';
import { GlassButton } from '../../ui/primitives';
import { listJobs } from '../../../lib/dataManagement';
import {
    DM_SECTION_IDS,
    MIGRATION_STEP_LABELS,
    MIGRATION_STEPS,
    furthestOpenStep,
    isMigrationReviewCurrent,
    migrationStepIssue,
    type MigrationStep,
} from '../../../lib/dataManagementLogic';
import {
    currentEpoch,
    isCurrentEpoch,
    useDataManagementStore,
    useDmValues,
} from '../../../stores/dataManagementStore';
import { DataManagementGuideDialog, type GuideId } from './DataManagementGuides';
import { DmIntro, DmNotice, useVisibleOnce, type DmCardProps } from './DmShared';
import { MigrationStepPanel } from './DataManagementMigrationSteps';

function stepIndex(step: MigrationStep): number {
    return MIGRATION_STEPS.indexOf(step);
}

function progressIsReachable(jobId: string | null): boolean {
    return Boolean(jobId);
}

export function DataManagementMigration({ help, onNavigate, disabled }: DmCardProps) {
    const rootRef = useRef<HTMLDivElement>(null);
    const visible = useVisibleOnce(rootRef);
    const values = useDmValues();
    const migration = useDataManagementStore((state) => state.migration);
    const focusStep = useDataManagementStore((state) => state.migrationFocusStep);
    const warning = useDataManagementStore((state) => state.settings?.operational_business_hours_warning);
    const updateMigration = useDataManagementStore((state) => state.updateMigration);
    const requestMigrationStep = useDataManagementStore((state) => state.requestMigrationStep);
    const [guide, setGuide] = useState<GuideId | null>(null);

    const currentIndex = stepIndex(migration.step);
    const furthest = useMemo(() => furthestOpenStep(migration, values), [migration, values]);
    const openLimit = Math.max(migration.reached, furthest);
    const currentIssue = migrationStepIssue(migration.step, migration, values);

    const isReachable = (step: MigrationStep) => {
        const index = stepIndex(step);
        if (step === 'target') return true;
        if (step === 'progress') return progressIsReachable(migration.jobId);
        if (migration.submission === 'accepted') return false;
        return index <= openLimit;
    };

    const goToStep = (step: MigrationStep) => {
        if (!isReachable(step)) return;
        updateMigration({ step });
    };

    useEffect(() => {
        if (!focusStep) return;
        if (focusStep === 'target' || isReachable(focusStep)) {
            updateMigration({ step: focusStep });
        }
        requestMigrationStep(null);
    }, [
        focusStep,
        migration.jobId,
        migration.reached,
        migration.submission,
        openLimit,
        requestMigrationStep,
        updateMigration,
    ]);

    useEffect(() => {
        if (!migration.review || isMigrationReviewCurrent(migration, values)) return;
        if (!migration.acknowledged && !migration.mirrorPhrase) return;
        updateMigration({ acknowledged: false, mirrorPhrase: '' });
    }, [migration, updateMigration, values]);

    const reattachLatestMigration = async () => {
        if (useDataManagementStore.getState().migration.jobId) return;
        const token = currentEpoch();
        try {
            for (const status of ['running', 'queued']) {
                const page = await listJobs(
                    { operation: 'migration', status, pageSize: 1, scheduled: 'all' },
                    null,
                );
                if (!isCurrentEpoch(token) || useDataManagementStore.getState().migration.jobId) return;
                const job = page.jobs[0];
                if (job?.id) {
                    updateMigration({ jobId: job.id, step: 'progress', submission: 'accepted', reached: 5 });
                    return;
                }
            }
        } catch {
            // Manual reattach is opportunistic; Job history remains the source of truth.
        }
    };

    useEffect(() => {
        if (!visible || migration.jobId) return;
        let cancelled = false;
        const token = currentEpoch();
        void (async () => {
            try {
                for (const status of ['running', 'queued']) {
                    const page = await listJobs(
                        { operation: 'migration', status, pageSize: 1, scheduled: 'all' },
                        null,
                    );
                    if (
                        cancelled ||
                        !isCurrentEpoch(token) ||
                        useDataManagementStore.getState().migration.jobId
                    )
                        return;
                    const job = page.jobs[0];
                    if (job?.id) {
                        updateMigration({
                            jobId: job.id,
                            step: 'progress',
                            submission: 'accepted',
                            reached: 5,
                        });
                        return;
                    }
                }
            } catch {
                // The explicit progress step and Job history remain available; a failed background reattach should not block setup.
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [visible, migration.jobId, updateMigration]);

    const continueToNext = () => {
        if (currentIssue || currentIndex >= MIGRATION_STEPS.length - 1) return;
        const next = MIGRATION_STEPS[currentIndex + 1];
        updateMigration({ step: next, reached: Math.max(migration.reached, currentIndex + 1) });
    };

    const backToPrevious = () => {
        if (currentIndex <= 0) return;
        updateMigration({ step: MIGRATION_STEPS[currentIndex - 1] });
    };

    return (
        <div ref={rootRef} data-testid="dm-migration" className="@container min-w-0 py-1">
            <DmIntro>
                {help ||
                    'Move SimpleChat data through a reviewed, recoverable migration with server-side preflight evidence before anything runs.'}
            </DmIntro>
            <div className="mb-4 flex flex-wrap items-start gap-2">
                {typeof warning === 'string' && warning.trim() ? (
                    <DmNotice tone="warning" className="min-w-0 flex-1 basis-72">
                        {warning}
                    </DmNotice>
                ) : null}
                <GlassButton type="button" variant="subtle" size="sm" onClick={() => setGuide('migration')}>
                    <HelpCircle size={14} aria-hidden="true" />
                    How migration works
                </GlassButton>
            </div>

            <nav aria-label="Migration steps" className="mb-4">
                <ol className="grid min-w-0 grid-cols-2 gap-2 @xl:grid-cols-3 @4xl:grid-cols-6">
                    {MIGRATION_STEPS.map((step, index) => {
                        const reachable = isReachable(step);
                        const issue = migrationStepIssue(step, migration, values);
                        const current = migration.step === step;
                        const done = !current && index < currentIndex && !issue;
                        const blocked = !current && reachable && Boolean(issue) && index <= openLimit;
                        return (
                            <li key={step} className="min-w-0">
                                <button
                                    type="button"
                                    aria-current={current ? 'step' : undefined}
                                    disabled={!reachable || disabled}
                                    className={clsx(
                                        'flex min-h-16 w-full min-w-0 items-center gap-2 rounded-xl border px-3 py-2 text-left text-sm transition-colors',
                                        current && 'border-accent bg-accent-soft text-accent',
                                        !current &&
                                            reachable &&
                                            'border-edge-strong bg-surface-solid text-text-1 hover:bg-surface-2',
                                        !reachable &&
                                            'cursor-not-allowed border-edge bg-surface-1 text-text-3 opacity-70',
                                        blocked && 'border-warn/40 bg-warn-soft text-warn',
                                    )}
                                    onClick={() => goToStep(step)}
                                >
                                    <span
                                        className={clsx(
                                            'grid h-7 w-7 shrink-0 place-items-center rounded-full border text-xs font-semibold',
                                            current && 'border-accent bg-surface-solid',
                                            done && 'border-ok/40 bg-ok-soft text-ok',
                                            blocked && 'border-warn/50 bg-surface-solid text-warn',
                                            !current &&
                                                !done &&
                                                !blocked &&
                                                'border-edge bg-surface-2 text-text-2',
                                        )}
                                        aria-hidden="true"
                                    >
                                        {done ? (
                                            <Check size={14} />
                                        ) : blocked ? (
                                            <TriangleAlert size={14} />
                                        ) : !reachable ? (
                                            <Lock size={13} />
                                        ) : (
                                            index + 1
                                        )}
                                    </span>
                                    <span className="min-w-0">
                                        <span className="block truncate font-semibold">
                                            {MIGRATION_STEP_LABELS[step]}
                                        </span>
                                        <span className="block truncate text-xs opacity-80">
                                            {current
                                                ? 'Current'
                                                : done
                                                  ? 'Done'
                                                  : blocked
                                                    ? 'Blocked'
                                                    : reachable
                                                      ? 'Open'
                                                      : 'Locked'}
                                        </span>
                                    </span>
                                </button>
                            </li>
                        );
                    })}
                </ol>
            </nav>

            <section
                className="min-w-0 rounded-2xl border border-edge-strong bg-surface-solid p-3 @2xl:p-4"
                aria-labelledby="dm-migration-step-heading"
            >
                <MigrationStepPanel
                    step={migration.step}
                    state={migration}
                    values={values}
                    disabled={disabled}
                    onNavigate={onNavigate}
                    onStep={goToStep}
                    onGuide={setGuide}
                    onReattach={() => void reattachLatestMigration()}
                />
                {migration.step !== 'progress' ? (
                    <footer className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-edge pt-3">
                        <GlassButton
                            type="button"
                            variant="ghost"
                            size="sm"
                            disabled={currentIndex === 0 || disabled}
                            onClick={backToPrevious}
                        >
                            <ChevronLeft size={14} aria-hidden="true" />
                            Back
                        </GlassButton>
                        <p className="min-w-0 flex-1 text-center text-xs text-text-3">
                            Step {currentIndex + 1} of {MIGRATION_STEPS.length}
                        </p>
                        <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
                            <span aria-live="polite" className="max-w-[22rem] text-xs text-warn">
                                {currentIssue ?? ''}
                            </span>
                            <GlassButton
                                type="button"
                                variant="primary"
                                size="sm"
                                disabled={
                                    Boolean(currentIssue) ||
                                    currentIndex >= MIGRATION_STEPS.length - 1 ||
                                    disabled
                                }
                                onClick={continueToNext}
                            >
                                Continue to{' '}
                                {
                                    MIGRATION_STEP_LABELS[
                                        MIGRATION_STEPS[
                                            Math.min(currentIndex + 1, MIGRATION_STEPS.length - 1)
                                        ]
                                    ]
                                }
                                <ChevronRight size={14} aria-hidden="true" />
                            </GlassButton>
                        </div>
                    </footer>
                ) : (
                    <footer className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-edge pt-3">
                        <GlassButton
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => onNavigate(DM_SECTION_IDS.jobs)}
                        >
                            Open Job history
                        </GlassButton>
                        <p className="text-xs text-text-3">
                            Step {currentIndex + 1} of {MIGRATION_STEPS.length}
                        </p>
                    </footer>
                )}
            </section>
            {guide ? <DataManagementGuideDialog guide={guide} onClose={() => setGuide(null)} /> : null}
        </div>
    );
}
