// adminSections.ts
// Decisions about how one Admin Settings section presents itself.
//
// Kept apart from `SettingsSection.tsx` because these are the parts worth executing in a
// test rather than reviewing by eye: whether a capability reads as configured, and which
// of its groups an administrator should be shown first. Both are easy to get subtly
// wrong, and both are invisible in a screenshot.

import {
    asBoolean,
    asString,
    evaluateDependency,
    type AdminField,
    type AdminFieldRequirement,
    type RenderedFieldGroup,
} from './adminFields';
import type { Json } from './types';

/**
 * How a section reads at a glance.
 *
 * `none` is for sections with nothing to be configured -- a run of plain toggles has no
 * configured/unconfigured distinction, and claiming one would be noise.
 */
export type SectionStatus = 'off' | 'blocked' | 'incomplete' | 'ready' | 'none';

/** Read a field's current value, preferring an unsaved edit over the stored one. */
export function readSectionValue(settings: Json, draft: Json, key: string): unknown {
    return Object.prototype.hasOwnProperty.call(draft, key) ? draft[key] : settings[key];
}

/**
 * Whether a required field currently holds something.
 *
 * A secret counts as filled while it holds the redaction placeholder, which is the point:
 * a stored credential the administrator has not touched is still configured, and reading
 * it as missing would tell them to re-enter a key that is already there.
 */
export function hasValue(value: unknown): boolean {
    if (Array.isArray(value)) {
        return value.length > 0;
    }
    if (typeof value === 'boolean') {
        return value;
    }
    if (typeof value === 'number') {
        return true;
    }
    return asString(value).trim().length > 0;
}

/**
 * Find the switch that turns a whole section on, if it declares one.
 *
 * The renderer lifts this into the section header, so the control that decides whether
 * anything else in the section matters is never found by scrolling past it.
 */
export function findCapabilityField(fields: AdminField[]): AdminField | undefined {
    return fields.find((field) => field.role === 'capability');
}

/**
 * Each distinct cross-section prerequisite the section depends on.
 *
 * Deduplicated by key, because a prerequisite usually applies to several fields and
 * stating it once at the top reads better than repeating it on each.
 */
export function collectRequirements(fields: AdminField[]): AdminFieldRequirement[] {
    const seen = new Map<string, AdminFieldRequirement>();
    for (const field of fields) {
        if (field.requires && !seen.has(field.requires.key)) {
            seen.set(field.requires.key, field.requires);
        }
    }
    return [...seen.values()];
}

/**
 * Summarise a section as a single status.
 *
 * Precedence matters and is deliberate. An unmet prerequisite outranks everything, because
 * nothing else the administrator does in the section will take effect until it is met.
 * Being switched off outranks being incomplete, because blank fields under a disabled
 * capability are not a problem to solve.
 */
export function deriveSectionStatus(
    fields: AdminField[],
    settings: Json,
    draft: Json,
): SectionStatus {
    const read = (key: string) => readSectionValue(settings, draft, key);
    const capability = findCapabilityField(fields);

    const unmet = collectRequirements(fields).some(
        (requirement) => !asBoolean(read(requirement.key)),
    );
    if (unmet) {
        return 'blocked';
    }

    if (capability?.key && !asBoolean(read(capability.key))) {
        return 'off';
    }

    // Only fields the administrator can currently see can be judged missing. A hidden
    // field belongs to a branch that is not in use -- the APIM endpoint while direct
    // access is selected -- and demanding a value for it would be permanently unmeetable.
    const required = fields.filter(
        (field) => field.required && field.key && evaluateDependency(field.depends_on, read),
    );

    if (!required.length) {
        return capability?.key ? 'ready' : 'none';
    }

    return required.every((field) => hasValue(read(field.key as string)))
        ? 'ready'
        : 'incomplete';
}

/**
 * Decide whether a group starts expanded.
 *
 * The rule is "open the thing that needs attention next". A connection group opens while
 * the capability is on and something required is still blank; everything else stays shut.
 * Turning a capability on therefore reveals the next step rather than forty controls, and
 * a section that is already working stays a summary.
 */
export function shouldGroupStartOpen(
    group: RenderedFieldGroup,
    status: SectionStatus,
    capabilityOn: boolean,
): boolean {
    if (!group.id) {
        // Ungrouped fields are the section's own preamble; collapsing them would hide
        // the controls that explain what the groups below are for.
        return true;
    }
    if (!capabilityOn) {
        return false;
    }
    return group.variant === 'connection' && status === 'incomplete';
}
