// workflowSettings.ts
// File Sync, schedule and trigger rules for the native V2 editor, in both workflow scopes. The
// checks mirror the save path of save_personal_workflow and save_group_workflow
// (_normalize_file_sync_config, the trigger rules and _normalize_schedule). They return the
// server's reviewed messages word for word, in the order the server applies them, so the first
// message is the one a refused save returns. Two checks need facts only the server holds: whether
// group File Sync is on for the caller, and whether each sent source still exists. The editor
// supplies both from the group's source list. Without that list, and always for personal
// workflows, they are left to the server's reviewed 400. The schedule rules follow
// functions_workflow_schedules.py; the time zone list and the administrator's minimum interval
// come from the editor options, and without them those two checks are left to the server.
// test_group_workflow_file_sync_client_parity.py pins both scopes against the real save functions,
// and test_workflow_calendar_schedule_client_parity.py pins the calendar and minimum rules.

import { isRecord } from './workspaceAuthoring';
import { pyStrip, pyText } from './workflowAlerts';

export const WORKFLOW_TRIGGER_TYPES = ['manual', 'interval', 'file_sync'] as const;
export const WORKFLOW_SCHEDULED_TRIGGER_TYPES = ['interval', 'file_sync'] as const;
export const WORKFLOW_SCHEDULE_UNITS = ['seconds', 'minutes', 'hours'] as const;
export const WORKFLOW_SCHEDULE_KINDS = ['interval', 'calendar'] as const;
export const WORKFLOW_SCHEDULE_FREQUENCIES = ['daily', 'weekdays', 'weekly', 'monthly'] as const;
export const WORKFLOW_SCHEDULE_DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'] as const;
/** `WORKFLOW_SCHEDULE_TIME_PATTERN` under `fullmatch`: 24-hour HH:MM. */
export const WORKFLOW_SCHEDULE_TIME_PATTERN = /^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/;
export const WORKFLOW_FILE_SYNC_MAX_SOURCES = 10;
export const WORKFLOW_FILE_SYNC_WAIT_MODES = ['complete', 'queued'] as const;
export const WORKFLOW_FILE_SYNC_CONTINUE_MODES = ['always', 'changed'] as const;
export const WORKFLOW_FILE_SYNC_SCOPE_TYPES = ['personal', 'group', 'public'] as const;
export const WORKFLOW_FILE_SYNC_SOURCE_UNAVAILABLE_CODE = 'file_sync_source_unavailable';
export const WORKFLOW_FILE_SYNC_SOURCE_UNAVAILABLE_MESSAGE =
    'A selected File Sync source is no longer available. Remove it and save again.';

export type WorkflowScheduleUnit = typeof WORKFLOW_SCHEDULE_UNITS[number];
export type WorkflowScheduleFrequency = typeof WORKFLOW_SCHEDULE_FREQUENCIES[number];
export type WorkflowScheduleDay = typeof WORKFLOW_SCHEDULE_DAYS[number];

/** An interval schedule, stored exactly as `{unit, value}`. */
export interface WorkflowIntervalSchedule {
    unit: WorkflowScheduleUnit;
    value: number;
}

/** A calendar schedule: a local wall-clock time in an IANA time zone. */
export interface WorkflowCalendarSchedule {
    kind: 'calendar';
    frequency: WorkflowScheduleFrequency;
    /** Weekly schedules only, in Monday-to-Sunday order; empty otherwise. */
    days_of_week: WorkflowScheduleDay[];
    /** Monthly schedules only; a month without this day runs on its last day. */
    day_of_month: number | null;
    time_of_day: string;
    timezone: string;
}

export type WorkflowSchedule = WorkflowIntervalSchedule | WorkflowCalendarSchedule;

const SCHEDULE_KIND_ERROR = 'Schedule kind must be interval or calendar.';
const SCHEDULE_FREQUENCY_ERROR = 'Schedule frequency must be daily, weekdays, weekly or monthly.';
const SCHEDULE_DAYS_ERROR = 'Schedule days of the week must be day names from monday to sunday.';
const SCHEDULE_DAYS_REQUIRED_ERROR = 'Choose at least one day of the week for a weekly schedule.';
const SCHEDULE_DAY_OF_MONTH_TYPE_ERROR = 'Schedule day of the month must be a whole number.';
const SCHEDULE_DAY_OF_MONTH_RANGE_ERROR = 'Schedule day of the month must be between 1 and 31.';
const SCHEDULE_TIME_ERROR = 'Schedule time must use 24-hour HH:MM format, such as 08:00.';
const SCHEDULE_TIMEZONE_ERROR = 'Schedule time zone must be an IANA time zone name, such as America/New_York.';
const UNIT_SECONDS: Record<WorkflowScheduleUnit, number> = { seconds: 1, minutes: 60, hours: 3600 };

export interface WorkflowSettingsContext {
    scope: { type: 'personal' } | { type: 'group'; groupId: string };
    /** Group only: the source list's `file_sync_enabled`, which is the gate the save applies. Null when unknown. */
    fileSyncEnabled: boolean | null;
    /** `scope_type:scope_id:source_id` of every source the save can still resolve, or null when unknown. */
    availableSourceKeys: ReadonlySet<string> | null;
    /** The time zone names a calendar schedule may use, from the editor options, or null when unknown. */
    scheduleTimezones?: ReadonlySet<string> | null;
    /** The administrator's minimum for a new or changed interval schedule, in seconds, or null when unknown. */
    minScheduleIntervalSeconds?: number | null;
}

/** The File Sync values the trigger rules read once the configuration itself is valid. */
interface NormalizedFileSync {
    enabled: boolean;
    wait_mode: string;
    continue_mode: string;
}

// Personal sources always resolve in the caller's own partition, so any fixed owner keeps keys distinct.
const PERSONAL_OWNER = 'self';

function includes<T extends string>(values: readonly T[], value: string): value is T {
    return (values as readonly string[]).includes(value);
}

/** Python's `_normalize_bool`: booleans as given, None as the default, and a few truthy words. */
function pyBool(value: unknown, fallback: boolean): boolean {
    if (typeof value === 'boolean') return value;
    if (value === null || value === undefined) return fallback;
    if (typeof value === 'string') return ['1', 'true', 'yes', 'on'].includes(pyStrip(value).toLowerCase());
    return pyText(value) !== '';
}

/**
 * Python's `int(value)` for the JSON values a request can carry, or null where it raises. Text is
 * read as ASCII digits; Python also accepts other Unicode digits, but the editor sends a number.
 */
function pyInt(value: unknown): number | null {
    if (typeof value === 'boolean') return value ? 1 : 0;
    if (typeof value === 'number') return Number.isFinite(value) ? Math.trunc(value) : null;
    if (typeof value === 'string') {
        const digits = pyStrip(value);
        return /^[+-]?\d+(?:_\d+)*$/.test(digits) ? Number(digits.replaceAll('_', '')) : null;
    }
    return null;
}

/** `_normalize_file_sync_config`: its first failure, and the values the trigger rules read. */
function fileSyncFailure(
    payload: Record<string, unknown>,
    existing: Record<string, unknown> | null,
    context: WorkflowSettingsContext,
): { error: string; config: NormalizedFileSync } {
    const stored = isRecord(existing?.file_sync) ? existing.file_sync : {};
    const sent = isRecord(payload.file_sync) ? payload.file_sync : stored;
    const read = (key: string, fallback: unknown) => Object.hasOwn(sent, key) ? sent[key]
        : Object.hasOwn(stored, key) ? stored[key] : fallback;
    const config = {
        enabled: pyBool(read('enabled', false), false),
        wait_mode: pyStrip(pyText(read('wait_mode', 'complete'))).toLowerCase() || 'complete',
        continue_mode: pyStrip(pyText(read('continue_mode', 'always'))).toLowerCase() || 'always',
    };
    const fail = (error: string) => ({ error, config });
    if (!includes(WORKFLOW_FILE_SYNC_WAIT_MODES, config.wait_mode)) {
        return fail('File Sync wait mode must be complete or queued.');
    }
    if (!includes(WORKFLOW_FILE_SYNC_CONTINUE_MODES, config.continue_mode)) {
        return fail('File Sync continue mode must be always or changed.');
    }
    if (config.wait_mode === 'queued' && config.continue_mode === 'changed') {
        return fail('To continue only when changes are found, File Sync must wait for the sync to complete.');
    }
    const groupId = context.scope.type === 'group' ? context.scope.groupId : '';
    if (context.scope.type === 'group' && config.enabled && context.fileSyncEnabled === false) {
        return fail('Group File Sync must be enabled before a group workflow can use File Sync sources.');
    }
    const seen = new Set<string>();
    for (const source of (Array.isArray(sent.sources) ? sent.sources : []).slice(0, WORKFLOW_FILE_SYNC_MAX_SOURCES)) {
        if (!isRecord(source)) continue;
        const sourceId = pyStrip(pyText(source.source_id) || pyText(source.id));
        let key: string;
        if (context.scope.type === 'group') {
            const scopeType = pyStrip(pyText(source.scope_type, 'group')).toLowerCase();
            const scopeId = pyStrip(pyText(source.scope_id, groupId));
            if (scopeType !== 'group' || scopeId !== groupId) {
                return fail('Group workflows can only use File Sync sources from this group.');
            }
            if (!sourceId) continue;
            key = `${scopeType}:${scopeId}:${sourceId}`;
        } else {
            const scopeType = pyStrip(pyText(source.scope_type)).toLowerCase();
            if (!includes(WORKFLOW_FILE_SYNC_SCOPE_TYPES, scopeType) || !sourceId) continue;
            const scopeId = scopeType === 'personal' ? PERSONAL_OWNER : pyStrip(pyText(source.scope_id));
            key = `${scopeType}:${scopeId}:${sourceId}`;
        }
        if (seen.has(key)) continue;
        if (context.availableSourceKeys && !context.availableSourceKeys.has(key)) {
            return fail(WORKFLOW_FILE_SYNC_SOURCE_UNAVAILABLE_MESSAGE);
        }
        seen.add(key);
    }
    if (config.enabled && !seen.size) {
        return fail(context.scope.type === 'group'
            ? 'Select at least one group File Sync source for this workflow.'
            : 'Select at least one File Sync source for this workflow.');
    }
    return { error: '', config };
}

type ScheduleResult = { schedule: WorkflowSchedule; error: '' } | { schedule: null; error: string };

function scheduleError(error: string): ScheduleResult {
    return { schedule: null, error };
}

/** `_normalize_interval_schedule`: the original interval rules, unchanged. */
function intervalSchedule(schedule: Record<string, unknown>): ScheduleResult {
    const unit = pyStrip(pyText(schedule.unit)).toLowerCase();
    if (!includes(WORKFLOW_SCHEDULE_UNITS, unit)) return scheduleError('Schedule unit must be seconds, minutes or hours.');
    const value = pyInt(schedule.value);
    if (value === null) return scheduleError('Schedule value must be a whole number.');
    const maximum = unit === 'hours' ? 24 : 59;
    if (value < 1 || value > maximum) return scheduleError(`Schedule value for ${unit} must be between 1 and ${maximum}.`);
    return { schedule: { unit, value }, error: '' };
}

/** `_normalize_calendar_schedule`, which checks frequency, days, time and time zone in that order. */
function calendarSchedule(schedule: Record<string, unknown>, timezones: ReadonlySet<string> | null): ScheduleResult {
    const frequency = pyStrip(pyText(schedule.frequency)).toLowerCase();
    if (!includes(WORKFLOW_SCHEDULE_FREQUENCIES, frequency)) return scheduleError(SCHEDULE_FREQUENCY_ERROR);
    let days: WorkflowScheduleDay[] = [];
    let dayOfMonth: number | null = null;
    if (frequency === 'weekly') {
        const sent = schedule.days_of_week ?? [];
        if (!Array.isArray(sent)) return scheduleError(SCHEDULE_DAYS_ERROR);
        const selected = new Set<string>();
        for (const day of sent) {
            const name = typeof day === 'string' ? pyStrip(day).toLowerCase() : '';
            if (!includes(WORKFLOW_SCHEDULE_DAYS, name)) return scheduleError(SCHEDULE_DAYS_ERROR);
            selected.add(name);
        }
        if (!selected.size) return scheduleError(SCHEDULE_DAYS_REQUIRED_ERROR);
        days = WORKFLOW_SCHEDULE_DAYS.filter((day) => selected.has(day));
    } else if (frequency === 'monthly') {
        // JSON booleans are not numbers here, as Python refuses them; 31.0 is a whole number in both.
        const day = schedule.day_of_month;
        if (typeof day !== 'number' || !Number.isInteger(day)) return scheduleError(SCHEDULE_DAY_OF_MONTH_TYPE_ERROR);
        if (day < 1 || day > 31) return scheduleError(SCHEDULE_DAY_OF_MONTH_RANGE_ERROR);
        dayOfMonth = day;
    }
    const time = typeof schedule.time_of_day === 'string' ? pyStrip(schedule.time_of_day) : '';
    if (!WORKFLOW_SCHEDULE_TIME_PATTERN.test(time)) return scheduleError(SCHEDULE_TIME_ERROR);
    const zone = typeof schedule.timezone === 'string' ? pyStrip(schedule.timezone) : '';
    // No list names an empty zone; without the list, any other name is left to the server.
    if (!zone || timezones && !timezones.has(zone)) return scheduleError(SCHEDULE_TIMEZONE_ERROR);
    return {
        schedule: {
            kind: 'calendar', frequency, days_of_week: days, day_of_month: dayOfMonth, time_of_day: time, timezone: zone,
        },
        error: '',
    };
}

/**
 * `normalize_workflow_schedule`: the schedule the save stores, or its first reviewed message. A
 * schedule without `kind`, or with `kind: 'interval'`, is an interval schedule. `timezones` is the
 * editor options' list; without it, only an empty time zone is refused here.
 */
export function workflowScheduleForSave(raw: unknown, timezones: ReadonlySet<string> | null = null): ScheduleResult {
    const schedule = isRecord(raw) ? raw : {};
    const kind = pyStrip(pyText(schedule.kind, 'interval')).toLowerCase();
    if (kind === 'interval') return intervalSchedule(schedule);
    if (kind === 'calendar') return calendarSchedule(schedule, timezones);
    return scheduleError(SCHEDULE_KIND_ERROR);
}

export function isWorkflowCalendarSchedule(schedule: unknown): schedule is WorkflowCalendarSchedule {
    return isRecord(schedule) && schedule.kind === 'calendar';
}

/** `workflow_schedule_interval_seconds`: the length of a normalized interval schedule, else null. */
function intervalSeconds(schedule: WorkflowSchedule): number | null {
    return isWorkflowCalendarSchedule(schedule) ? null : schedule.value * UNIT_SECONDS[schedule.unit];
}

function sameSchedule(left: WorkflowSchedule, right: WorkflowSchedule): boolean {
    if (isWorkflowCalendarSchedule(left) || isWorkflowCalendarSchedule(right)) {
        return isWorkflowCalendarSchedule(left) && isWorkflowCalendarSchedule(right) &&
            left.frequency === right.frequency && left.day_of_month === right.day_of_month &&
            left.time_of_day === right.time_of_day && left.timezone === right.timezone &&
            left.days_of_week.join() === right.days_of_week.join();
    }
    return left.unit === right.unit && left.value === right.value;
}

/**
 * `workflow_schedule_minimum_applies`: only a new or changed interval schedule is held to the
 * administrator's minimum, so a raised minimum never blocks re-saving a workflow on the interval it
 * already runs on. Switching between Interval and Monitor File Sync keeps the same schedule.
 */
export function workflowScheduleMinimumApplies(schedule: WorkflowSchedule, existing: Record<string, unknown> | null): boolean {
    if (intervalSeconds(schedule) === null) return false;
    const trigger = pyStrip(pyText(existing?.trigger_type)).toLowerCase();
    if (!includes(WORKFLOW_SCHEDULED_TRIGGER_TYPES, trigger)) return true;
    const previous = workflowScheduleForSave(existing?.schedule).schedule;
    return !previous || !sameSchedule(previous, schedule);
}

/** `format_workflow_schedule_duration`: a whole number of seconds in the largest unit that divides it. */
export function formatWorkflowScheduleDuration(seconds: number): string {
    for (const [unit, size] of [['hour', 3600], ['minute', 60]] as const) {
        if (seconds % size === 0) {
            const count = seconds / size;
            return count === 1 ? `${count} ${unit}` : `${count} ${unit}s`;
        }
    }
    return seconds === 1 ? '1 second' : `${seconds} seconds`;
}

export function workflowScheduleMinimumMessage(minimumSeconds: number): string {
    return 'This schedule runs more often than the administrator allows. ' +
        `Choose an interval of at least ${formatWorkflowScheduleDuration(minimumSeconds)}.`;
}

/** `_normalize_schedule`, which the save applies to interval and Monitor File Sync workflows. */
function scheduleFailure(raw: unknown, existing: Record<string, unknown> | null, context: WorkflowSettingsContext): string {
    const { schedule, error } = workflowScheduleForSave(raw, context.scheduleTimezones ?? null);
    if (!schedule) return error;
    const minimum = context.minScheduleIntervalSeconds;
    if (minimum && workflowScheduleMinimumApplies(schedule, existing)) {
        const seconds = intervalSeconds(schedule);
        if (seconds !== null && seconds < minimum) return workflowScheduleMinimumMessage(minimum);
    }
    return '';
}

function joinLabels(labels: string[]): string {
    return labels.length === 1 ? labels[0] : `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`;
}

function calendarLabel(schedule: WorkflowCalendarSchedule): string {
    const at = `${schedule.time_of_day} ${schedule.timezone}`;
    if (schedule.frequency === 'daily') return `Daily ${at}`;
    if (schedule.frequency === 'weekdays') return `Weekdays ${at}`;
    if (schedule.frequency === 'weekly') {
        return `${joinLabels(schedule.days_of_week.map((day) => `${day[0].toUpperCase()}${day.slice(1)}s`))} ${at}`;
    }
    const day = schedule.day_of_month ?? 1;
    return `Monthly on day ${day}${day > 28 ? ' (or last day)' : ''}, ${at}`;
}

/**
 * `workflow_schedule_label`: when a scheduled workflow runs, such as "Mondays 08:00
 * America/New_York" or "Every 30 minutes", or '' for a manual workflow or an unreadable schedule.
 */
export function workflowScheduleLabel(triggerType: unknown, raw: unknown, timezones: ReadonlySet<string> | null = null): string {
    const trigger = pyStrip(pyText(triggerType)).toLowerCase();
    if (!includes(WORKFLOW_SCHEDULED_TRIGGER_TYPES, trigger)) return '';
    const { schedule } = workflowScheduleForSave(raw, timezones);
    if (!schedule) return '';
    if (isWorkflowCalendarSchedule(schedule)) {
        const cadence = calendarLabel(schedule);
        return trigger === 'file_sync' ? `Monitor File Sync: ${cadence}` : cadence;
    }
    const cadence = schedule.value === 1 ? `Every ${schedule.unit.slice(0, -1)}` : `Every ${schedule.value} ${schedule.unit}`;
    return trigger === 'file_sync' ? `Monitor File Sync ${cadence[0].toLowerCase()}${cadence.slice(1)}` : cadence;
}

/**
 * What the server would refuse in this save payload, for the File Sync, trigger and schedule
 * rules only, given the stored record it falls back to. The first entry is the message the
 * server returns. Each rule family reports at most its first failure, as the server raises it;
 * the Monitor rules are skipped when the File Sync configuration itself already failed.
 */
export function workflowSettingsErrors(
    payload: Record<string, unknown>,
    existing: Record<string, unknown> | null,
    context: WorkflowSettingsContext,
): string[] {
    const errors: string[] = [];
    const fileSync = fileSyncFailure(payload, existing, context);
    if (fileSync.error) errors.push(fileSync.error);
    const trigger = pyStrip(pyText(payload.trigger_type)).toLowerCase();
    if (!trigger) {
        errors.push('Trigger type is required.');
    } else if (!includes(WORKFLOW_TRIGGER_TYPES, trigger)) {
        errors.push('Trigger type must be manual, interval or file_sync.');
    }
    if (trigger === 'file_sync' && !fileSync.error) {
        if (!fileSync.config.enabled) {
            errors.push('Monitor File Sync Changes workflows require File Sync before run.');
        } else if (fileSync.config.wait_mode !== 'complete') {
            errors.push('Monitor File Sync Changes workflows must wait for sync completion.');
        } else if (fileSync.config.continue_mode !== 'changed') {
            errors.push('Monitor File Sync Changes workflows must continue only when changes are found.');
        }
    }
    if (trigger === 'interval' || trigger === 'file_sync') {
        const schedule = scheduleFailure(payload.schedule, existing, context);
        if (schedule) errors.push(schedule);
    }
    return errors;
}
