// DataManagementSchedule.tsx
// Schedule: keeps cadence, retention and scope together because each changes what a future backup contains.

import { useId, useMemo } from 'react';
import { clsx } from 'clsx';
import { type AdminField } from '../../../lib/adminFields';
import { type DmEditableKey } from '../../../lib/dataManagement';
import {
    LINKED_SECTION_IDS,
    asCount,
    asFlag,
    asText,
    computeRetentionDays,
    dmDirtyKeys,
    formatDateTime,
    retentionMaxValue,
} from '../../../lib/dataManagementLogic';
import { useDataManagementStore } from '../../../stores/dataManagementStore';
import { GlassButton } from '../../ui/primitives';
import { FieldShell, inputClass } from '../fields';
import { DmField, useDmValue } from './DmField';
import { DmDisclosure, DmIntro, DmNotice, type DmCardProps } from './DmShared';
import { DmCardSaveError, DmLoadError, DmLoadingRows, useDmConfigCard } from './DataManagementConfigParts';

const SCHEDULE_KEYS: readonly DmEditableKey[] = [
    'enabled',
    'full_backup_frequency',
    'scheduled_time_utc',
    'retention_value',
    'retention_unit',
    'partial_backups_enabled',
    'low_impact_mode',
    'include_cosmos',
    'include_ai_search',
    'include_source_blobs',
];

const NEXT_RUN_KEYS: readonly DmEditableKey[] = [
    'enabled',
    'full_backup_frequency',
    'scheduled_time_utc',
    'partial_backups_enabled',
];

const RETENTION_UNITS = [
    ['days', 'Days'],
    ['weeks', 'Weeks'],
    ['months', 'Months'],
    ['years', 'Years'],
] as const;

const timeField: AdminField = {
    key: 'data_management_scheduled_time_utc',
    type: 'text',
    label: 'Start time (UTC)',
    help: 'Backups start at this time in UTC.',
    default: '03:00',
};

const retentionField: AdminField = {
    key: 'data_management_retention_value',
    type: 'number',
    label: 'Keep backups for',
    help: 'Retention cleanup deletes backups older than this window. The newest successful full backup is kept by default as a safety baseline.',
    default: 30,
};

function StartTimeField({ disabled }: { disabled?: boolean }) {
    const value = asText(useDmValue('scheduled_time_utc'), '03:00');
    const error = useDataManagementStore((state) => state.fieldErrors.scheduled_time_utc);
    const saving = useDataManagementStore((state) => state.saving);
    const setValue = useDataManagementStore((state) => state.setValue);

    return (
        <FieldShell
            field={timeField}
            error={error}
            htmlFor="data-management-scheduled-time-utc"
            width="standard"
        >
            <input
                id="data-management-scheduled-time-utc"
                type="time"
                className={inputClass}
                value={value}
                disabled={disabled || saving}
                onChange={(event) => setValue('scheduled_time_utc', event.target.value || '03:00')}
            />
        </FieldShell>
    );
}

function RetentionField({ disabled }: { disabled?: boolean }) {
    const unitId = useId();
    const value = useDmValue('retention_value');
    const unit = asText(useDmValue('retention_unit'), 'days');
    const error = useDataManagementStore((state) => state.fieldErrors.retention_value);
    const saving = useDataManagementStore((state) => state.saving);
    const setValue = useDataManagementStore((state) => state.setValue);
    const current = Math.trunc(asCount(value, 30));
    const max = retentionMaxValue(unit);
    const locked = disabled || saving;

    const changeUnit = (nextUnit: string) => {
        const nextMax = retentionMaxValue(nextUnit);
        setValue('retention_unit', nextUnit);
        if (current > nextMax) {
            setValue('retention_value', nextMax);
        }
    };

    return (
        <FieldShell
            field={retentionField}
            error={error}
            htmlFor="data-management-retention-value"
            width="wide"
        >
            <div className="grid min-w-0 gap-2 @xl:grid-cols-[minmax(7rem,10rem)_minmax(8rem,12rem)]">
                <input
                    id="data-management-retention-value"
                    type="number"
                    min={1}
                    max={max}
                    step={1}
                    className={inputClass}
                    value={Number.isFinite(current) ? current : 30}
                    disabled={locked}
                    onChange={(event) => setValue('retention_value', Number(event.target.value))}
                />
                <label htmlFor={unitId} className="sr-only">
                    Retention unit
                </label>
                <select
                    id={unitId}
                    className={clsx(inputClass, 'appearance-none pr-8')}
                    value={unit}
                    disabled={locked}
                    onChange={(event) => changeUnit(event.target.value)}
                >
                    {RETENTION_UNITS.map(([optionValue, label]) => (
                        <option key={optionValue} value={optionValue}>
                            {label}
                        </option>
                    ))}
                </select>
            </div>
            <p className="mt-1.5 text-xs text-text-3" aria-live="polite">
                = {computeRetentionDays(value, unit).toLocaleString()} days
            </p>
        </FieldShell>
    );
}

function NextRunReadout() {
    const settings = useDataManagementStore((state) => state.settings);
    const draft = useDataManagementStore((state) => state.draft);
    const scheduled = asFlag(useDmValue('enabled'));
    const dirtyKeys = useMemo(() => dmDirtyKeys(settings, draft), [draft, settings]);
    const scheduleDirty = dirtyKeys.some((key) => NEXT_RUN_KEYS.includes(key));

    if (!scheduled) return null;
    const items = [
        ['Next full backup', settings?.next_full_backup_run_at],
        ['Next partial backup', settings?.next_partial_backup_run_at],
    ].filter((item): item is [string, string] => typeof item[1] === 'string' && item[1].trim().length > 0);
    if (!items.length) return null;

    return (
        <div className="rounded-xl border border-edge bg-surface-solid p-3">
            <dl className="grid gap-2 @xl:grid-cols-2">
                {items.map(([label, value]) => (
                    <div key={label} className="min-w-0">
                        <dt className="text-xs font-medium text-text-3">{label}</dt>
                        <dd className="text-sm font-semibold text-text-1">{formatDateTime(value)}</dd>
                    </div>
                ))}
            </dl>
            {scheduleDirty ? (
                <p className="mt-2 text-xs text-text-3">
                    Run times update after these schedule changes are saved.
                </p>
            ) : null}
        </div>
    );
}

export function DataManagementSchedule({ help, onNavigate, disabled }: DmCardProps) {
    const { status, loadError, settings, saveError } = useDmConfigCard(SCHEDULE_KEYS, true);
    const includeCosmos = asFlag(useDmValue('include_cosmos'));
    const includeSearch = asFlag(useDmValue('include_ai_search'));
    const sourceBlobsLocked = settings?.include_source_blobs_manageable === false;
    const includeSource = !sourceBlobsLocked && asFlag(useDmValue('include_source_blobs'));
    const includedCount = [includeCosmos, includeSearch, includeSource].filter(Boolean).length;

    return (
        <div data-testid="dm-schedule" className="@container min-w-0 py-1">
            {help ? <DmIntro>{help}</DmIntro> : null}
            {status === 'error' ? (
                <DmLoadError message={loadError} />
            ) : status !== 'ready' ? (
                <DmLoadingRows rows={6} />
            ) : (
                <div className="space-y-3">
                    <DmCardSaveError message={saveError} />
                    <DmField dmKey="enabled" emphasis="primary" disabled={disabled} />
                    <div className="divide-y divide-edge-strong">
                        <DmField dmKey="full_backup_frequency" disabled={disabled} />
                        <StartTimeField disabled={disabled} />
                        <RetentionField disabled={disabled} />
                    </div>
                    <div className="admin-switch-grid">
                        <DmField dmKey="partial_backups_enabled" disabled={disabled} />
                        <DmField dmKey="low_impact_mode" disabled={disabled} />
                    </div>
                    <NextRunReadout />
                    <DmDisclosure title="Backup scope (advanced)" summary={`${includedCount} of 3 included`}>
                        <div className="space-y-2 py-3">
                            <DmNotice tone="warning" role="note" title="Incomplete scope limits recovery">
                                Leaving a surface out creates backups that are incomplete for restore or
                                migration.
                            </DmNotice>
                            <div className="admin-switch-grid">
                                <DmField dmKey="include_cosmos" disabled={disabled} />
                                <DmField dmKey="include_ai_search" disabled={disabled} />
                                <DmField
                                    dmKey="include_source_blobs"
                                    disabled={disabled || sourceBlobsLocked}
                                    after={
                                        sourceBlobsLocked ? (
                                            <div className="ml-14 mt-1.5 flex flex-wrap items-center gap-2 text-xs text-text-3">
                                                <span>
                                                    Source files can be included once Enhanced Citations is
                                                    on.
                                                </span>
                                                <GlassButton
                                                    type="button"
                                                    variant="subtle"
                                                    size="sm"
                                                    onClick={() =>
                                                        onNavigate(LINKED_SECTION_IDS.enhancedCitations)
                                                    }
                                                >
                                                    Open Enhanced Citations
                                                </GlassButton>
                                            </div>
                                        ) : null
                                    }
                                />
                            </div>
                        </div>
                    </DmDisclosure>
                </div>
            )}
        </div>
    );
}
