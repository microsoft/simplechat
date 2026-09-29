// WorkflowScheduleFields.tsx
// Schedule fields for the native V2 workflow editor, in both workflow scopes: a fixed interval, or a
// calendar schedule that runs at a local time in an IANA time zone, daily, on weekdays, on chosen
// days of the week or on a day of the month. The server works out each run's UTC instant, so a
// calendar schedule keeps its local time across daylight saving changes.

import { useId, useRef, useState, type ReactNode } from 'react';
import {
    isWorkflowCalendarSchedule,
    workflowCalendarSchedulesOffered,
    workflowScheduleKindSupported,
    workflowScheduleLabel,
    workflowScheduleTimezones,
    WORKFLOW_SCHEDULE_DAYS,
    type WorkflowCalendarSchedule,
    type WorkflowEditorOptions,
    type WorkflowIntervalSchedule,
    type WorkflowSchedule,
    type WorkflowScheduleDay,
    type WorkflowScheduleFrequency,
    type WorkflowScheduleUnit,
} from '../../lib/workflowEditor';

const inputClass = 'w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none';

type Repeats = 'interval' | WorkflowScheduleFrequency;

const REPEAT_OPTIONS: ReadonlyArray<{ value: Repeats; label: string }> = [
    { value: 'interval', label: 'At an interval' },
    { value: 'daily', label: 'Daily' },
    { value: 'weekdays', label: 'Weekdays (Monday to Friday)' },
    { value: 'weekly', label: 'Weekly on chosen days' },
    { value: 'monthly', label: 'Monthly on a day of the month' },
];
const DEFAULT_TIME = '09:00';
const FALLBACK_TIMEZONE = 'UTC';

function dayName(day: WorkflowScheduleDay): string {
    return `${day[0].toUpperCase()}${day.slice(1)}`;
}

/** The browser's IANA time zone, or '' when it cannot say. */
export function browserTimeZone(): string {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone ?? '';
    } catch {
        return '';
    }
}

/** A new calendar schedule starts in the browser's time zone when the server lists it, else in UTC. */
export function defaultWorkflowScheduleTimezone(zones: ReadonlySet<string> | null): { zone: string; browser: string; fallback: boolean } {
    const browser = browserTimeZone();
    return browser && zones?.has(browser)
        ? { zone: browser, browser, fallback: false }
        : { zone: FALLBACK_TIMEZONE, browser, fallback: true };
}

interface ScheduleMemory {
    interval: WorkflowIntervalSchedule;
    calendar: WorkflowCalendarSchedule | null;
    days: WorkflowScheduleDay[];
    dayOfMonth: number;
}

export function WorkflowScheduleFields({
    triggerField,
    schedule,
    options,
    scheduled,
    onChange,
}: {
    /** The trigger select, laid out beside Repeats. */
    triggerField: ReactNode;
    schedule: WorkflowSchedule;
    options: WorkflowEditorOptions;
    /** Whether this trigger runs on the schedule; the fields stay visible, but disabled, when it does not. */
    scheduled: boolean;
    /** Receives an updater so consecutive edits apply to the latest draft, not this render's copy. */
    onChange: (update: (schedule: WorkflowSchedule) => WorkflowSchedule) => void;
}) {
    const baseId = useId();
    const zones = workflowScheduleTimezones(options);
    // A stored schedule of a kind this editor does not support is shown as neither kind; the
    // editor keeps it as stored and opens the workflow read-only.
    const supported = workflowScheduleKindSupported(schedule);
    const calendar = isWorkflowCalendarSchedule(schedule) ? schedule : null;
    const interval = calendar || !supported ? null : schedule as WorkflowIntervalSchedule;
    const calendarOffered = supported && (workflowCalendarSchedulesOffered(options) || Boolean(calendar));
    const [zoneDefault] = useState(() => defaultWorkflowScheduleTimezone(zones));
    const [zoneNote, setZoneNote] = useState(false);
    // What each kind last held, so switching to another cadence and back keeps the earlier values.
    const memory = useRef<ScheduleMemory>({
        interval: { unit: 'minutes', value: 15 }, calendar: null, days: ['monday'], dayOfMonth: 1,
    });
    const label = scheduled ? workflowScheduleLabel('interval', schedule, zones) : '';

    const updateCalendar = (changes: Partial<WorkflowCalendarSchedule>) => onChange((current) => (
        isWorkflowCalendarSchedule(current) ? { ...current, ...changes } : current
    ));
    const updateInterval = (changes: Partial<WorkflowIntervalSchedule>) => onChange((current) => (
        isWorkflowCalendarSchedule(current) ? current : { ...current, ...changes }
    ));
    const changeRepeats = (next: Repeats) => {
        const saved = memory.current;
        if (calendar) {
            saved.calendar = calendar;
            if (calendar.days_of_week.length) saved.days = calendar.days_of_week;
            if (calendar.day_of_month) saved.dayOfMonth = calendar.day_of_month;
        } else if (interval) {
            saved.interval = interval;
        }
        const base = calendar ?? saved.calendar;
        if (next === 'interval') {
            setZoneNote(false);
            onChange((current) => isWorkflowCalendarSchedule(current) ? saved.interval : current);
            return;
        }
        if (!base) setZoneNote(zoneDefault.fallback);
        onChange(() => ({
            kind: 'calendar',
            frequency: next,
            days_of_week: next === 'weekly' ? base?.days_of_week.length ? base.days_of_week : saved.days : [],
            day_of_month: next === 'monthly' ? base?.day_of_month ?? saved.dayOfMonth : null,
            time_of_day: base?.time_of_day ?? DEFAULT_TIME,
            timezone: base?.timezone ?? zoneDefault.zone,
        }));
    };
    const toggleDay = (day: WorkflowScheduleDay, checked: boolean) => onChange((current) => (
        isWorkflowCalendarSchedule(current) ? {
            ...current,
            days_of_week: WORKFLOW_SCHEDULE_DAYS.filter((item) => item === day ? checked : current.days_of_week.includes(item)),
        } : current
    ));

    return (
        <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-3">
                {triggerField}
                {calendarOffered ? (
                    <label className="text-sm text-text-2">
                        Repeats
                        <select
                            className={`${inputClass} mt-1`}
                            aria-label="Repeats"
                            value={calendar ? calendar.frequency : 'interval'}
                            disabled={!scheduled}
                            onChange={(event) => changeRepeats(event.target.value as Repeats)}
                        >
                            {REPEAT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                        </select>
                    </label>
                ) : null}
            </div>
            {interval ? (
                <div className="grid gap-3 md:grid-cols-3">
                    <label className="text-sm text-text-2">
                        Interval value
                        <input
                            className={`${inputClass} mt-1`}
                            type="number"
                            min={1}
                            aria-label="Interval value"
                            value={interval.value}
                            disabled={!scheduled}
                            onChange={(event) => updateInterval({ value: Math.max(1, Math.trunc(Number(event.target.value) || 1)) })}
                        />
                    </label>
                    <label className="text-sm text-text-2">
                        Interval unit
                        <select
                            className={`${inputClass} mt-1`}
                            aria-label="Interval unit"
                            value={interval.unit}
                            disabled={!scheduled}
                            onChange={(event) => updateInterval({ unit: event.target.value as WorkflowScheduleUnit })}
                        >
                            <option value="seconds">Seconds</option>
                            <option value="minutes">Minutes</option>
                            <option value="hours">Hours</option>
                        </select>
                    </label>
                </div>
            ) : null}
            {calendar?.frequency === 'weekly' ? (
                <fieldset disabled={!scheduled} className="min-w-0">
                    <legend className="text-sm text-text-2">Days of the week</legend>
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
                        {WORKFLOW_SCHEDULE_DAYS.map((day) => (
                            <label key={day} className="flex items-center gap-2 text-sm text-text-1">
                                <input
                                    type="checkbox"
                                    className="accent-[var(--accent)]"
                                    checked={calendar.days_of_week.includes(day)}
                                    onChange={(event) => toggleDay(day, event.target.checked)}
                                />
                                {dayName(day)}
                            </label>
                        ))}
                    </div>
                </fieldset>
            ) : null}
            {calendar ? (
                <div className="grid gap-3 md:grid-cols-3">
                    {calendar.frequency === 'monthly' ? (
                        <label className="text-sm text-text-2">
                            Day of the month
                            <input
                                className={`${inputClass} mt-1`}
                                type="number"
                                min={1}
                                max={31}
                                aria-label="Day of the month"
                                aria-describedby={`${baseId}-month-help`}
                                value={calendar.day_of_month ?? ''}
                                disabled={!scheduled}
                                onChange={(event) => updateCalendar({
                                    day_of_month: Math.max(1, Math.trunc(Number(event.target.value) || 1)),
                                })}
                            />
                            <span id={`${baseId}-month-help`} className="mt-1 block text-xs text-text-3">
                                Months without this day run on their last day.
                            </span>
                        </label>
                    ) : null}
                    <label className="text-sm text-text-2">
                        Time
                        <input
                            className={`${inputClass} mt-1`}
                            type="time"
                            step={60}
                            aria-label="Time"
                            value={calendar.time_of_day}
                            disabled={!scheduled}
                            onChange={(event) => updateCalendar({ time_of_day: event.target.value })}
                        />
                    </label>
                    <label className="text-sm text-text-2">
                        Time zone
                        <input
                            className={`${inputClass} mt-1`}
                            type="text"
                            list={`${baseId}-zones`}
                            aria-label="Time zone"
                            aria-describedby={zoneNote ? `${baseId}-zone-note` : undefined}
                            autoComplete="off"
                            spellCheck={false}
                            value={calendar.timezone}
                            disabled={!scheduled}
                            onChange={(event) => {
                                setZoneNote(false);
                                updateCalendar({ timezone: event.target.value });
                            }}
                        />
                        <datalist id={`${baseId}-zones`}>
                            {(options.schedule?.timezones ?? []).map((zone) => <option key={zone} value={zone} />)}
                        </datalist>
                    </label>
                </div>
            ) : null}
            {calendar && zoneNote ? (
                <p id={`${baseId}-zone-note`} role="status" className="rounded-lg bg-warn-soft p-2 text-xs text-warn">
                    {zoneDefault.browser
                        ? `Your browser's time zone, ${zoneDefault.browser}, isn't available, so this schedule starts in UTC.`
                        : "Your browser didn't report a time zone, so this schedule starts in UTC."}
                    {' '}Choose the time zone it should follow.
                </p>
            ) : null}
            {!supported ? (
                <p role="status" className="text-xs text-text-3">
                    This workflow&apos;s schedule can&apos;t be shown or changed in this editor.
                </p>
            ) : null}
            {label ? (
                <p className="text-xs text-text-3">
                    Schedule: {label}
                    {calendar ? '. Runs follow local time in this zone, including daylight saving changes.' : null}
                </p>
            ) : null}
        </div>
    );
}
