// workflowSettings.ts
// File Sync, schedule and trigger rules for the native V2 editor, in both workflow scopes. The
// checks mirror the save path of save_personal_workflow and save_group_workflow
// (_normalize_file_sync_config, the trigger rules and _normalize_schedule). They return the
// server's reviewed messages word for word, in the order the server applies them, so the first
// message is the one a refused save returns. Two checks need facts only the server holds: whether
// group File Sync is on for the caller, and whether each sent source still exists. The editor
// supplies both from the group's source list. Without that list, and always for personal
// workflows, they are left to the server's reviewed 400.
// test_group_workflow_file_sync_client_parity.py pins both scopes against the real save functions.

import { isRecord } from './workspaceAuthoring';
import { pyStrip, pyText } from './workflowAlerts';

export const WORKFLOW_TRIGGER_TYPES = ['manual', 'interval', 'file_sync'] as const;
export const WORKFLOW_SCHEDULE_UNITS = ['seconds', 'minutes', 'hours'] as const;
export const WORKFLOW_FILE_SYNC_MAX_SOURCES = 10;
export const WORKFLOW_FILE_SYNC_WAIT_MODES = ['complete', 'queued'] as const;
export const WORKFLOW_FILE_SYNC_CONTINUE_MODES = ['always', 'changed'] as const;
export const WORKFLOW_FILE_SYNC_SCOPE_TYPES = ['personal', 'group', 'public'] as const;
export const WORKFLOW_FILE_SYNC_SOURCE_UNAVAILABLE_CODE = 'file_sync_source_unavailable';
export const WORKFLOW_FILE_SYNC_SOURCE_UNAVAILABLE_MESSAGE =
    'A selected File Sync source is no longer available. Remove it and save again.';

export interface WorkflowSettingsContext {
    scope: { type: 'personal' } | { type: 'group'; groupId: string };
    /** Group only: the source list's `file_sync_enabled`, which is the gate the save applies. Null when unknown. */
    fileSyncEnabled: boolean | null;
    /** `scope_type:scope_id:source_id` of every source the save can still resolve, or null when unknown. */
    availableSourceKeys: ReadonlySet<string> | null;
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

/** `_normalize_schedule`, which the save applies to interval and Monitor File Sync workflows. */
function scheduleFailure(raw: unknown): string {
    const schedule = isRecord(raw) ? raw : {};
    const unit = pyStrip(pyText(schedule.unit)).toLowerCase();
    if (!includes(WORKFLOW_SCHEDULE_UNITS, unit)) return 'Schedule unit must be seconds, minutes or hours.';
    const value = pyInt(schedule.value);
    if (value === null) return 'Schedule value must be a whole number.';
    const maximum = unit === 'hours' ? 24 : 59;
    return value < 1 || value > maximum ? `Schedule value for ${unit} must be between 1 and ${maximum}.` : '';
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
        const schedule = scheduleFailure(payload.schedule);
        if (schedule) errors.push(schedule);
    }
    return errors;
}
