// RetentionSchedule.tsx
// The daily retention run: when it happens, when it last happened, and when it next will.
//
// The classic pane shows the hour as a select and the last and next run as raw ISO
// strings. Here the hour reads as UTC with the administrator's own clock beside it, and
// both timestamps read as a date plus how far away they are, because "next run in 3
// hours" is what someone checking the schedule actually wants to know.
//
// The hour is stored as an int -- execute_retention_policy hands it to
// datetime.replace(hour=...) -- which is why this is a component rather than a generic
// select, whose options are strings.

import { useState, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react';
import { api } from '../../lib/apiClient';
import type { AdminField } from '../../lib/adminFields';
import {
    RETENTION_LAST_RUN_KEY,
    RETENTION_NEXT_RUN_KEY,
    describeRunTime,
    localTimeForUtcHour,
    projectNextRun,
    readExecutionHour,
    utcHourLabel,
    willReschedule,
} from '../../lib/retentionPolicy';
import type { Json } from '../../lib/types';
import { FieldShell, inputClass } from './fields';

const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

interface ScheduleResponse {
    settings?: Json;
}

export function RetentionSchedule({
    field,
    value,
    settings,
    draft,
    error,
    disabled,
    onChange,
    onStoredSettingsChange,
}: {
    field: AdminField;
    value: unknown;
    /** The saved settings, which hold the last and next run. */
    settings: Json;
    draft: Json;
    error?: string;
    disabled?: boolean;
    onChange: (hour: number) => void;
    /** Merge freshly read schedule values into the page's copy of the saved settings. */
    onStoredSettingsChange: (partial: Json) => void;
}) {
    const [checking, setChecking] = useState(false);
    const [checkFailed, setCheckFailed] = useState(false);

    const id = `admin-field-${field.key ?? 'retention-schedule'}`;
    const hour = readExecutionHour(value);
    const now = new Date();
    const local = localTimeForUtcHour(hour, now);
    const last = describeRunTime(settings[RETENTION_LAST_RUN_KEY], now);
    const next = describeRunTime(settings[RETENTION_NEXT_RUN_KEY], now);
    const projected = willReschedule(settings, draft)
        ? describeRunTime(projectNextRun(hour, now), now)
        : null;

    const check = async () => {
        setChecking(true);
        setCheckFailed(false);
        try {
            const response = await api.get<ScheduleResponse>('/api/admin/retention-policy/settings');
            const stored = response.settings ?? {};
            onStoredSettingsChange({
                [RETENTION_LAST_RUN_KEY]: stored[RETENTION_LAST_RUN_KEY] ?? null,
                [RETENTION_NEXT_RUN_KEY]: stored[RETENTION_NEXT_RUN_KEY] ?? null,
            });
        } catch {
            setCheckFailed(true);
        } finally {
            setChecking(false);
        }
    };

    let nextRun: ReactNode;
    if (projected) {
        nextRun = (
            <>
                <time dateTime={projected.iso}>{projected.absolute}</time>
                <span className="text-text-3"> · {projected.relative}, once you save</span>
            </>
        );
    } else if (next && next.past) {
        nextRun = (
            <>
                <time dateTime={next.iso}>{next.absolute}</time>
                <span className="text-text-3"> · due now; the scheduler checks every 5 minutes</span>
            </>
        );
    } else if (next) {
        nextRun = (
            <>
                <time dateTime={next.iso}>{next.absolute}</time>
                <span className="text-text-3"> · {next.relative}</span>
            </>
        );
    } else {
        nextRun = (
            <span className="text-text-3">
                Not set yet. It is worked out when a run time is saved or the next run finishes.
            </span>
        );
    }

    return (
        <FieldShell field={field} error={error} htmlFor={id}>
            <div className="max-w-[26rem]">
                <select
                    id={id}
                    className={clsx(inputClass, 'appearance-none pr-8')}
                    value={hour}
                    disabled={disabled}
                    onChange={(event) => onChange(Number(event.target.value))}
                >
                    {HOURS.map((option) => (
                        <option key={option} value={option}>
                            {utcHourLabel(option)}
                        </option>
                    ))}
                </select>
                {local ? (
                    <p className="mt-1.5 text-xs text-text-3">That is {local} on your clock.</p>
                ) : null}
            </div>

            <dl
                aria-label="Retention schedule"
                className="mt-3 space-y-1.5 text-sm"
                data-testid="retention-schedule-readout"
            >
                {/* Each pair wraps its value below the term once the card is too narrow to
                    hold both on one line, rather than squeezing the value into a sliver. */}
                <div className="flex flex-wrap items-baseline gap-x-3">
                    <dt className="w-[4.5rem] shrink-0 text-xs font-medium text-text-3">Last run</dt>
                    <dd className="min-w-0 flex-[1_1_12rem] tabular-nums text-text-1">
                        {last ? (
                            <>
                                <time dateTime={last.iso}>{last.absolute}</time>
                                <span className="text-text-3"> · {last.relative}</span>
                            </>
                        ) : (
                            <span className="text-text-3">Never run</span>
                        )}
                    </dd>
                </div>
                <div className="flex flex-wrap items-baseline gap-x-3">
                    <dt className="w-[4.5rem] shrink-0 text-xs font-medium text-text-3">Next run</dt>
                    <dd className="min-w-0 flex-[1_1_12rem] tabular-nums text-text-1">{nextRun}</dd>
                </div>
            </dl>

            <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                    type="button"
                    disabled={checking}
                    onClick={() => void check()}
                    className={clsx(
                        'inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-text-2 transition-colors',
                        'hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-60',
                    )}
                >
                    {checking ? (
                        <Loader2 size={12} className="animate-spin" aria-hidden="true" />
                    ) : (
                        <RefreshCw size={12} aria-hidden="true" />
                    )}
                    Check again
                </button>
                {checkFailed ? (
                    <span role="alert" className="flex items-center gap-1 text-xs text-danger">
                        <AlertCircle size={12} aria-hidden="true" />
                        The schedule could not be read. Try again in a moment.
                    </span>
                ) : null}
            </div>
        </FieldShell>
    );
}
