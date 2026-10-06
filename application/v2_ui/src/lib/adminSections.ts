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
    evaluateSectionStatus,
    readFieldGroup,
    readSettingValue,
    type AdminField,
    type AdminFieldDependency,
    type AdminFieldRequirement,
    type AdminSectionStatusRule,
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

/**
 * Read a field's current value, preferring an unsaved edit over the stored one.
 *
 * Given the field index, a value saved at a nested path is found where its field
 * declares it, so a configured Web Search connection does not read as blank.
 */
export function readSectionValue(
    settings: Json,
    draft: Json,
    key: string,
    fieldsByKey?: Map<string, AdminField>,
): unknown {
    return readSettingValue(key, settings, draft, fieldsByKey);
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
export function collectRequirements(
    fields: AdminField[],
    settings?: Json,
    draft: Json = {},
    fieldsByKey?: Map<string, AdminField>,
): AdminFieldRequirement[] {
    const seen = new Map<string, AdminFieldRequirement>();
    for (const field of fields) {
        if (settings && field.role !== 'capability') {
            const read = (key: string) => readSectionValue(settings, draft, key, fieldsByKey);
            if (!evaluateDependency(field.depends_on, read)) continue;
            if (field.type === 'switch' && field.key && !asBoolean(read(field.key) ?? field.default)) continue;
        }
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
    fieldsByKey?: Map<string, AdminField>,
): SectionStatus {
    const read = (key: string) => readSectionValue(settings, draft, key, fieldsByKey);
    const capability = findCapabilityField(fields);

    const unmet = collectRequirements(fields, settings, draft, fieldsByKey).some(
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

/** A declared status uses different words for the same three states. */
const DECLARED_STATUS_MAP: Record<'off' | 'unconfigured' | 'on', SectionStatus> = {
    off: 'off',
    unconfigured: 'incomplete',
    on: 'ready',
};

/**
 * The status a section card and the page index both show.
 *
 * A server-declared rule wins: it exists precisely for sections whose "configured" state
 * the field metadata cannot express. Everything else is derived from the fields. One
 * function serves both places, so the card chip and the index can never disagree.
 */
export function computeSectionStatus(
    fields: AdminField[],
    settings: Json,
    draft: Json,
    statusRule?: AdminSectionStatusRule,
    fieldsByKey?: Map<string, AdminField>,
): SectionStatus {
    const declared = evaluateSectionStatus(statusRule, settings, draft);
    if (declared) {
        return DECLARED_STATUS_MAP[declared];
    }
    return deriveSectionStatus(fields, settings, draft, fieldsByKey);
}

/** How a field sits relative to the switch that governs it. */
export type FieldEmphasis = 'primary' | 'dependent';

export interface FieldHierarchy {
    /** Presentation by field key. A field missing from the map renders plainly. */
    emphasis: ReadonlyMap<string, FieldEmphasis>;
    /** Switches that another field in the section depends on. */
    leads: ReadonlySet<string>;
}

/**
 * Field types that can sit under a switch as one of its settings.
 *
 * Read-only mirrors, status readouts, and bespoke components are left out: a mirror
 * reports a value configured elsewhere, and a component is a workbench of its own, so
 * neither reads as a sub-setting of the switch above it.
 */
const NESTABLE_TYPES: ReadonlySet<AdminField['type']> = new Set<AdminField['type']>([
    'switch',
    'text',
    'textarea',
    'secret',
    'select',
    'number',
    'color',
    'range',
    'string_list',
    'checkbox_set',
    'entry_list',
    'id_list',
    'link_list',
    'group_picker',
    'image',
]);

/** Every settings key a dependency tree reads, in any of its declared shapes. */
export function dependencyKeys(dependency: AdminFieldDependency | undefined): string[] {
    if (!dependency) {
        return [];
    }
    if (Array.isArray(dependency)) {
        return dependency.flatMap((condition) => dependencyKeys(condition));
    }
    if ('any_of' in dependency) {
        return dependency.any_of.flatMap((child) => dependencyKeys(child));
    }
    if ('all_of' in dependency) {
        return dependency.all_of.flatMap((child) => dependencyKeys(child));
    }
    return dependency.key ? [dependency.key] : [];
}

function isEditableSwitch(field: AdminField): boolean {
    return field.type === 'switch' && Boolean(field.key) && !field.readonly;
}

function groupIdOf(field: AdminField): string {
    return readFieldGroup(field.group)?.id ?? '';
}

/**
 * Work out which switch leads a section and which settings belong to it.
 *
 * The Agents cards were the first to show this by hand: Enable Agents stands out as the
 * switch the card is about, and Workspace Mode and its global-agent option sit indented
 * beneath it. The schema already says the same thing through `depends_on`, so the
 * relationship is read from there instead of being declared again for every section.
 *
 * - A *lead* is an editable switch that a later field in the section depends on.
 * - The *primary* field is the section's capability toggle, or failing that, its first
 *   field when that field is an ungrouped lead.
 * - A *dependent* is an editable field that depends on a lead, or on another member of the
 *   lead's run, and follows it without interruption inside the same group. The run ends
 *   at the first field that does not, so a setting further down the card is never drawn
 *   as nested under a switch it merely shares a condition with.
 *
 * Nesting is one level deep. Order, visibility, and saving are untouched.
 */
export function deriveFieldHierarchy(fields: AdminField[]): FieldHierarchy {
    const emphasis = new Map<string, FieldEmphasis>();
    const leads = new Set<string>();

    fields.forEach((field, index) => {
        if (!isEditableSwitch(field)) {
            return;
        }
        const key = field.key as string;
        const governs = fields
            .slice(index + 1)
            .some((later) => dependencyKeys(later.depends_on).includes(key));
        if (governs) {
            leads.add(key);
        }
    });

    const capability = findCapabilityField(fields);
    // A leading switch inside a group is a mode for that group (APIM routing, say), not
    // the switch the card is about, so only an ungrouped one is promoted.
    const first = fields[0];
    const primary = capability?.key && isEditableSwitch(capability)
        ? capability
        : first?.key && leads.has(first.key) && !groupIdOf(first)
            ? first
            : undefined;
    if (primary?.key) {
        emphasis.set(primary.key, 'primary');
    }

    let run: { group: string; members: Set<string> } | null = null;
    for (const field of fields) {
        const key = field.key;
        const nestable = Boolean(key) && !field.readonly && NESTABLE_TYPES.has(field.type);
        const continuesRun = Boolean(
            run &&
            nestable &&
            groupIdOf(field) === run.group &&
            dependencyKeys(field.depends_on).some((dependency) => run?.members.has(dependency)),
        );

        if (continuesRun && run && key) {
            if (emphasis.get(key) !== 'primary') {
                emphasis.set(key, 'dependent');
            }
            run.members.add(key);
            continue;
        }

        run = key && leads.has(key)
            ? { group: groupIdOf(field), members: new Set([key]) }
            : null;
    }

    return { emphasis, leads };
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
    if (group.collapsed) {
        // The schema asked for this one closed. Built-in actions that are always on
        // are the case: worth listing, not worth reading past every time.
        return false;
    }
    if (!capabilityOn) {
        return false;
    }
    return group.variant === 'connection' && status === 'incomplete';
}
