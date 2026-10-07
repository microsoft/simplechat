// WorkflowScheduleFields.tsx
// Schedule fields for the native V2 workflow editor, in both workflow scopes: a fixed interval, or a
// calendar schedule that runs at a local time in an IANA time zone, daily, on weekdays, on chosen
// days of the week or on a day of the month. The server works out each run's UTC instant, so a
// calendar schedule keeps its local time across daylight saving changes.

import { useId, useRef, useState, type ReactNode } from 'react';
import {
    isWorkflowCalendarSchedule,
    workflowCalendarSchedulesOffered,
    workflowScheduleLabel,
    workflowScheduleSupported,
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
import { WorkflowChangedField } from './WorkflowChangeTracking';
import {
    WorkflowField,
    WorkflowFieldEmphasis,
    WorkflowFieldList,
    workflowFieldInputClass,
} from './WorkflowField';

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
    /** The Trigger row, drawn first; the schedule's rows nest beneath it. */
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
    // A stored schedule this editor can't show exactly is shown as neither kind, with no label; the
    // editor keeps it as stored and opens the workflow read-only.
    const supported = workflowScheduleSupported(schedule);
    const calendar = supported && isWorkflowCalendarSchedule(schedule) ? schedule : null;
    const interval = calendar || !supported ? null : schedule as WorkflowIntervalSchedule;
    const calendarOffered = supported && (workflowCalendarSchedulesOffered(options) || Boolean(calendar));
    const [zoneDefault] = useState(() => defaultWorkflowScheduleTimezone(zones));
    const [zoneNote, setZoneNote] = useState(false);
    // What each kind last held, so switching to another cadence and back keeps the earlier values.
    const memory = useRef<ScheduleMemory>({
        interval: { unit: 'minutes', value: 15 }, calendar: null, days: ['monday'], dayOfMonth: 1,
    });
    const label = scheduled && supported ? workflowScheduleLabel('interval', schedule, zones) : '';

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
        <WorkflowChangedField changeKey="schedule" className="min-w-0">
            {triggerField}
            {/* The schedule belongs to the trigger, so it sits beneath it. It stays visible, though
                disabled, while the trigger is Manual, so a schedule is never silently lost. */}
            <WorkflowFieldEmphasis emphasis="dependent">
                <WorkflowFieldList>
                    {calendarOffered ? (
                        <WorkflowField label="Repeats" htmlFor={`${baseId}-repeats`} width="standard">
                            <select
                                id={`${baseId}-repeats`}
                                className={workflowFieldInputClass}
                                aria-label="Repeats"
                                value={calendar ? calendar.frequency : 'interval'}
                                disabled={!scheduled}
                                onChange={(event) => changeRepeats(event.target.value as Repeats)}
                            >
                                {REPEAT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                            </select>
                        </WorkflowField>
                    ) : null}
                    {interval ? (
                        <WorkflowField label="Interval value" htmlFor={`${baseId}-interval-value`} width="compact">
                            <input
                                id={`${baseId}-interval-value`}
                                className={workflowFieldInputClass}
                                type="number"
                                min={1}
                                aria-label="Interval value"
                                value={interval.value}
                                disabled={!scheduled}
                                onChange={(event) => updateInterval({ value: Math.max(1, Math.trunc(Number(event.target.value) || 1)) })}
                            />
                        </WorkflowField>
                    ) : null}
                    {interval ? (
                        <WorkflowField label="Interval unit" htmlFor={`${baseId}-interval-unit`} width="standard">
                            <select
                                id={`${baseId}-interval-unit`}
                                className={workflowFieldInputClass}
                                aria-label="Interval unit"
                                value={interval.unit}
                                disabled={!scheduled}
                                onChange={(event) => updateInterval({ unit: event.target.value as WorkflowScheduleUnit })}
                            >
                                <option value="seconds">Seconds</option>
                                <option value="minutes">Minutes</option>
                                <option value="hours">Hours</option>
                            </select>
                        </WorkflowField>
                    ) : null}
                    {calendar?.frequency === 'weekly' ? (
                        <WorkflowField label="Days of the week" labelId={`${baseId}-days`} group width="full">
                            <div className="flex min-h-10 flex-wrap items-center gap-x-4 gap-y-2">
                                {WORKFLOW_SCHEDULE_DAYS.map((day) => (
                                    <label key={day} className="flex items-center gap-2 text-sm text-text-1">
                                        <input
                                            type="checkbox"
                                            className="accent-[var(--accent)]"
                                            checked={calendar.days_of_week.includes(day)}
                                            disabled={!scheduled}
                                            onChange={(event) => toggleDay(day, event.target.checked)}
                                        />
                                        {dayName(day)}
                                    </label>
                                ))}
                            </div>
                        </WorkflowField>
                    ) : null}
                    {calendar?.frequency === 'monthly' ? (
                        <WorkflowField label="Day of the month" htmlFor={`${baseId}-month-day`} width="compact"
                            help="Months without this day run on their last day." helpId={`${baseId}-month-help`}>
                            <input
                                id={`${baseId}-month-day`}
                                className={workflowFieldInputClass}
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
                        </WorkflowField>
                    ) : null}
                    {calendar ? (
                        <WorkflowField label="Time" htmlFor={`${baseId}-time`} width="compact">
                            <input
                                id={`${baseId}-time`}
                                className={workflowFieldInputClass}
                                type="time"
                                step={60}
                                aria-label="Time"
                                value={calendar.time_of_day}
                                disabled={!scheduled}
                                onChange={(event) => updateCalendar({ time_of_day: event.target.value })}
                            />
                        </WorkflowField>
                    ) : null}
                    {calendar ? (
                        <WorkflowField label="Time zone" htmlFor={`${baseId}-zone`} width="standard"
                            help="An IANA time zone, such as America/New_York.">
                            <input
                                id={`${baseId}-zone`}
                                className={workflowFieldInputClass}
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
                        </WorkflowField>
                    ) : null}
                </WorkflowFieldList>
                {calendar && zoneNote ? (
                    <p id={`${baseId}-zone-note`} role="status" className="mb-2 rounded-lg border border-warn/40 bg-warn/5 px-3 py-2 text-xs text-warn">
                        {zoneDefault.browser
                            ? `Your browser's time zone, ${zoneDefault.browser}, isn't available, so this schedule starts in UTC.`
                            : "Your browser didn't report a time zone, so this schedule starts in UTC."}
                        {' '}Choose the time zone it should follow.
                    </p>
                ) : null}
                {!supported ? (
                    <p role="status" className="py-2 text-xs text-text-3">
                        This workflow&apos;s schedule can&apos;t be shown or changed in this editor.
                    </p>
                ) : null}
                {label ? (
                    <p className="border-t border-edge-strong py-2.5 text-xs text-text-3">
                        Schedule: {label}
                        {calendar ? '. Runs follow local time in this zone, including daylight saving changes.' : null}
                    </p>
                ) : null}
            </WorkflowFieldEmphasis>
        </WorkflowChangedField>
    );
}
