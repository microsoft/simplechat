// DataManagementReadiness.tsx
// Start Here: readiness evidence and guides.

import { useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, CircleSlash, TriangleAlert } from 'lucide-react';
import { GlassButton, Skeleton } from '../../ui/primitives';
import { buildReadinessChecklist } from '../../../lib/dataManagementLogic';
import { useDataManagementStore } from '../../../stores/dataManagementStore';
import type { DmCardProps } from './DmShared';
import { DmIntro, DmNotice, useVisibleOnce } from './DmShared';
import { DataManagementGuideDialog, GUIDE_TITLES, type GuideId } from './DataManagementGuides';
import { useBackupSummary } from './useBackupSummary';

const GUIDE_ORDER: GuideId[] = ['setup', 'backup', 'migration', 'restore', 'ru-boost'];

const STATE_VIEW = {
    ok: { Icon: CheckCircle2, className: 'text-ok', word: 'Ready' },
    attention: { Icon: TriangleAlert, className: 'text-warn', word: 'Needs attention' },
    off: { Icon: CircleSlash, className: 'text-text-3', word: 'Off' },
} as const;

export function DataManagementReadiness({ help, onNavigate, disabled }: DmCardProps) {
    const rootRef = useRef<HTMLDivElement>(null);
    const visible = useVisibleOnce(rootRef);
    const settings = useDataManagementStore((state) => state.settings);
    const draft = useDataManagementStore((state) => state.draft);
    const status = useDataManagementStore((state) => state.status);
    const loadError = useDataManagementStore((state) => state.loadError);
    const [guide, setGuide] = useState<GuideId | null>(null);
    const { summary, loading, failure } = useBackupSummary(visible);

    useEffect(() => {
        void useDataManagementStore.getState().ensureLoaded();
    }, []);

    const checklist = useMemo(
        () => buildReadinessChecklist(settings, draft, summary),
        [settings, draft, summary],
    );
    const warning =
        typeof settings?.operational_business_hours_warning === 'string'
            ? settings.operational_business_hours_warning
            : '';

    return (
        <div ref={rootRef} data-testid="dm-readiness" className="@container space-y-4">
            <DmIntro>
                {help ??
                    'Use these checkpoints before running backup, migration, restore, or advanced repair actions.'}
            </DmIntro>

            {warning ? (
                <DmNotice tone="warning" title="Operational window">
                    {warning}
                </DmNotice>
            ) : null}

            {loadError ? (
                <DmNotice tone="danger" title="Backup settings could not be loaded" role="alert">
                    {loadError}
                </DmNotice>
            ) : null}

            <div>
                <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
                    <div>
                        <h3 className="text-sm font-semibold text-text-1">Readiness checklist</h3>
                        <p className="mt-0.5 text-xs text-text-3">
                            Open the section named by any item that needs attention.
                        </p>
                    </div>
                    {loading ? (
                        <span role="status" aria-live="polite" className="text-xs text-text-3">
                            Loading backup history…
                        </span>
                    ) : null}
                </div>

                {status === 'loading' && !settings ? (
                    <div className="space-y-2" aria-label="Loading readiness checklist">
                        {[0, 1, 2].map((item) => (
                            <Skeleton key={item} className="h-16 w-full" />
                        ))}
                    </div>
                ) : (
                    <ul
                        aria-label="Backup and recovery readiness checklist"
                        className="divide-y divide-edge rounded-xl border border-edge-strong bg-surface-solid"
                    >
                        {checklist.map((item) => {
                            const view = STATE_VIEW[item.state];
                            return (
                                <li key={item.id} className="flex flex-wrap items-start gap-3 px-3 py-3">
                                    <view.Icon
                                        size={17}
                                        aria-hidden="true"
                                        className={`mt-0.5 shrink-0 ${view.className}`}
                                    />
                                    <span className="sr-only">{view.word}: </span>
                                    <div className="min-w-0 flex-1 basis-56">
                                        <p className="text-sm font-semibold text-text-1">{item.label}</p>
                                        <p className="mt-0.5 text-[0.8125rem] leading-relaxed break-words text-text-3">
                                            {item.detail}
                                        </p>
                                    </div>
                                    <GlassButton
                                        type="button"
                                        variant="subtle"
                                        size="sm"
                                        disabled={disabled}
                                        onClick={() => onNavigate(item.sectionId)}
                                    >
                                        Open
                                    </GlassButton>
                                </li>
                            );
                        })}
                    </ul>
                )}
            </div>

            {failure ? (
                <DmNotice
                    tone={failure.maintenanceRequired ? 'warning' : 'danger'}
                    title="Backup history summary unavailable"
                    role="alert"
                >
                    {failure.message}
                </DmNotice>
            ) : null}

            <div className="rounded-xl border border-edge bg-surface-1 p-3">
                <h3 className="text-sm font-semibold text-text-1">Guides</h3>
                <p className="mt-0.5 text-xs text-text-3">
                    Short operational references for configuring and running Backup & Recovery.
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                    {GUIDE_ORDER.map((id) => (
                        <GlassButton
                            key={id}
                            type="button"
                            variant="subtle"
                            size="sm"
                            onClick={() => setGuide(id)}
                        >
                            {GUIDE_TITLES[id]}
                        </GlassButton>
                    ))}
                </div>
            </div>

            {guide ? <DataManagementGuideDialog guide={guide} onClose={() => setGuide(null)} /> : null}
        </div>
    );
}
