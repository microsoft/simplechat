// SettingsSection.tsx
// One Admin Settings section, laid out so it can be read rather than scanned.
//
// The V2 surface used to render a section as a flat run of controls in declaration order.
// That works for Appearance, which is a handful of fields. It does not work for
// Knowledge: Document Intelligence alone is around forty controls, and the credential
// that makes the other thirty-nine work was simply the last one in the list.
//
// What this does:
//
// Every section is a distinct card: a header band with the section's icon, a title large
// enough to find while scrolling, its place in the navigation, and a status chip. The
// Agents cards were drawn this way first; it now applies everywhere, with the icon taken
// from the navigation definition rather than declared per section.
//
// The switch a section hangs off stands out, and the settings that only mean something
// while it is on sit indented beneath it. That relationship is read from the schema's
// `depends_on` (see `deriveFieldHierarchy`), so it holds for every section without a
// hand-maintained list. Runs of independent switches flow into two columns on wide cards.
//
// Fields cluster into declared groups that collapse. A group opens when it is the one an
// administrator needs next -- an empty connection on an enabled capability -- and stays
// shut otherwise, so a configured section is a summary rather than a wall.
//
// A prerequisite owned by another section is stated where it is felt. Previously an
// administrator could turn File Sync on and have nothing happen, because Redis Cache was
// off two groups away and nothing said so until a flash message after saving.

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { AlertTriangle, ChevronRight, type LucideIcon } from 'lucide-react';
import {
    asBoolean,
    groupFields,
    isFieldVisible,
    type AdminField,
    type AdminSectionStatusRule,
    type RenderedFieldGroup,
} from '../../lib/adminFields';
import {
    collectRequirements,
    computeSectionStatus,
    deriveFieldHierarchy,
    findCapabilityField,
    readSectionValue,
    shouldGroupStartOpen,
    type FieldEmphasis,
    type SectionStatus,
} from '../../lib/adminSections';
import { GlassPanel } from '../ui/primitives';
import { FALLBACK_SECTION_ICON } from './adminSectionIcons';
import { presentSectionStatus } from './sectionStatusPresentation';
import type { Json } from '../../lib/types';

/**
 * Presentation overrides for one section.
 *
 * Optional everywhere: the icon comes from the navigation and the field hierarchy from the
 * schema. An override exists for a cue the schema cannot express -- the person and group
 * icons on workspace permissions -- or to opt a field out of a derived emphasis with
 * `'none'` when the derived reading turns out to be wrong for that section.
 */
export interface SettingsSectionAppearance {
    Icon?: LucideIcon;
    fields?: Readonly<Partial<Record<string, {
        emphasis?: FieldEmphasis | 'none';
        Icon?: LucideIcon;
    }>>>;
}

export interface SettingsSectionProps {
    sectionId: string;
    label: string;
    groupLabel: string;
    tabLabel: string;
    fields: AdminField[];
    settings: Json;
    draft: Json;
    /** Renders one field. Owned by the page, which holds the API-backed controls. */
    renderField: (field: AdminField) => ReactNode;
    /** Renders the capability toggle, so switch acknowledgements keep working. */
    renderCapability: (field: AdminField) => ReactNode;
    /**
     * A server-declared status rule, used in preference to deriving one.
     *
     * Sections that describe `required` fields have their status derived from those.
     * A declared rule exists for sections where "configured" depends on a combination
     * the field metadata cannot express on its own.
     */
    statusRule?: AdminSectionStatusRule;
    /**
     * The status computed by the page from the whole section.
     *
     * Passed in so the card and the page index read the same value, and so a search that
     * narrows `fields` cannot change what the chip says. Derived here when absent.
     */
    status?: SectionStatus;
    /** The section's icon, resolved from the navigation definition. */
    icon?: LucideIcon;
    /**
     * Every visible field of the section, for working out which switch leads which
     * settings while a search narrows `fields` to the matches.
     */
    hierarchyFields?: AdminField[];
    /** Force every group open, used while a search is filtering the page. */
    forceExpanded?: boolean;
    /** Opt-in presentation overrides; never changes the schema's behavior. */
    appearance?: SettingsSectionAppearance;
    /**
     * Flags the server resolves outside the settings document, such as whether inbound MCP
     * is enabled for the deployment. A field gated on one is hidden without them.
     */
    runtimeFlags?: Record<string, boolean>;
    /**
     * Move the page to another section, for prerequisite links. Without it those links
     * open the classic page.
     */
    onNavigate?: (sectionId: string) => void;
    children?: ReactNode;
}

function RequirementNotice({
    requirement,
    satisfied,
    onNavigate,
}: {
    requirement: NonNullable<AdminField['requires']>;
    satisfied: boolean;
    onNavigate?: (sectionId: string) => void;
}) {
    if (satisfied) {
        return null;
    }

    const blocking = (requirement.mode ?? 'block') === 'block';
    const targetSection = requirement.target_section;

    return (
        <div
            className={clsx(
                'mb-3 flex items-start gap-2 rounded-lg border px-3 py-2 text-xs',
                blocking
                    ? 'border-danger/40 bg-danger/5 text-text-2'
                    : 'border-warn/40 bg-warn/5 text-text-2',
            )}
        >
            <AlertTriangle
                size={13}
                className={clsx('mt-0.5 shrink-0', blocking ? 'text-danger' : 'text-warn')}
            />
            <div>
                <p>
                    <span className="font-medium">{requirement.label}</span>{' '}
                    {blocking
                        ? 'must be enabled before these settings take effect.'
                        : 'is not enabled yet.'}
                </p>
                {requirement.description ? (
                    <p className="mt-0.5 text-text-3">{requirement.description}</p>
                ) : null}
                {/* Within the page when the page can take the reader there; the classic
                    page otherwise, which is where these links always used to lead. */}
                {targetSection && onNavigate ? (
                    <button
                        type="button"
                        onClick={() => onNavigate(targetSection)}
                        className="mt-1 inline-block text-accent underline"
                    >
                        Configure {requirement.label}
                    </button>
                ) : targetSection ? (
                    <a
                        href={`/admin/settings#${encodeURIComponent(targetSection)}`}
                        className="mt-1 inline-block text-accent underline"
                    >
                        Configure {requirement.label}
                    </a>
                ) : null}
            </div>
        </div>
    );
}

/**
 * Lay out a run of fields, flowing consecutive independent switches into a grid.
 *
 * Built-in Actions alone is ten switches, each a single row; on a wide card they read
 * just as well side by side. A switch that leads other settings, or sits beneath one,
 * keeps its own row so that relationship stays visible.
 */
function layoutFields(
    fields: AdminField[],
    renderOne: (field: AdminField) => ReactNode,
    flowsInGrid: (field: AdminField) => boolean,
): ReactNode[] {
    const blocks: ReactNode[] = [];
    let run: AdminField[] = [];

    const flush = () => {
        if (run.length >= 2) {
            blocks.push(
                <div
                    key={`switch-grid-${run[0].key}`}
                    className="admin-switch-grid"
                    data-testid="admin-switch-grid"
                >
                    {run.map(renderOne)}
                </div>,
            );
        } else {
            blocks.push(...run.map(renderOne));
        }
        run = [];
    };

    for (const field of fields) {
        if (flowsInGrid(field)) {
            run.push(field);
            continue;
        }
        flush();
        blocks.push(renderOne(field));
    }
    flush();
    return blocks;
}

function FieldGroup({
    group,
    startOpen,
    forceExpanded,
    renderFields,
}: {
    group: RenderedFieldGroup;
    startOpen: boolean;
    forceExpanded?: boolean;
    renderFields: (fields: AdminField[]) => ReactNode[];
}) {
    const [open, setOpen] = useState(startOpen);

    // A search match inside a collapsed group has to become visible, otherwise filtering
    // the page would show a card with nothing in it.
    useEffect(() => {
        if (forceExpanded) {
            setOpen(true);
        }
    }, [forceExpanded]);

    if (!group.id) {
        return <div className="divide-y divide-edge-strong">{renderFields(group.fields)}</div>;
    }

    return (
        <div className="admin-field-group mt-3 rounded-xl border border-edge-strong bg-surface-solid">
            <button
                type="button"
                aria-expanded={open}
                className={clsx(
                    'flex min-h-11 w-full items-center gap-2 rounded-xl px-3 py-2 text-left',
                    'hover:bg-surface-sunken',
                    open && 'rounded-b-none bg-surface-sunken',
                )}
                onClick={() => setOpen((previous) => !previous)}
            >
                <ChevronRight
                    size={14}
                    className={clsx(
                        'shrink-0 text-text-2 transition-transform',
                        open && 'rotate-90',
                    )}
                />
                <span className="min-w-0 text-sm font-semibold text-text-1">
                    {group.label ?? group.id}
                </span>
                {!open ? (
                    <span className="ml-auto shrink-0 text-xs text-text-3">
                        {group.fields.length}{' '}
                        {group.fields.length === 1 ? 'setting' : 'settings'}
                    </span>
                ) : null}
            </button>

            {open ? (
                <div className="border-t border-edge-strong px-3 pb-1 sm:px-4">
                    {group.help ? (
                        <p className="max-w-[72ch] pt-2 text-[0.8125rem] leading-relaxed text-text-3">
                            {group.help}
                        </p>
                    ) : null}
                    <div className="divide-y divide-edge-strong">{renderFields(group.fields)}</div>
                </div>
            ) : null}
        </div>
    );
}

export function SettingsSection({
    sectionId,
    label,
    groupLabel,
    tabLabel,
    fields,
    settings,
    draft,
    statusRule,
    status: statusProp,
    icon,
    hierarchyFields,
    renderField,
    renderCapability,
    forceExpanded,
    appearance,
    runtimeFlags,
    onNavigate,
    children,
}: SettingsSectionProps) {
    const capability = useMemo(() => findCapabilityField(fields), [fields]);

    const bodyFields = useMemo(
        () => fields.filter((field) => field !== capability),
        [fields, capability],
    );

    const derivedStatus = useMemo(
        () => computeSectionStatus(fields, settings, draft, statusRule),
        [statusRule, fields, settings, draft],
    );
    const status = statusProp ?? derivedStatus;

    const hierarchy = useMemo(
        () => deriveFieldHierarchy(hierarchyFields ?? fields),
        [hierarchyFields, fields],
    );

    const capabilityOn = capability?.key
        ? asBoolean(readSectionValue(settings, draft, capability.key))
        : true;

    // A section states each distinct prerequisite once, at the top, rather than repeating
    // it on every field that carries it.
    const requirements = useMemo(() => collectRequirements(fields, settings, draft), [fields, settings, draft]);

    const groups = useMemo(
        () => groupFields(bodyFields.filter((field) => isFieldVisible(field, settings, draft, undefined, runtimeFlags))),
        [bodyFields, settings, draft, runtimeFlags],
    );

    const presentation = presentSectionStatus(status);
    const SectionIcon = appearance?.Icon ?? icon ?? FALLBACK_SECTION_ICON;

    /** An explicit override wins; `'none'` removes a derived emphasis. */
    const emphasisOf = (field: AdminField): FieldEmphasis | undefined => {
        const declared = appearance?.fields?.[field.key ?? '']?.emphasis;
        if (declared) {
            return declared === 'none' ? undefined : declared;
        }
        return field.key ? hierarchy.emphasis.get(field.key) : undefined;
    };

    const flowsInGrid = (field: AdminField) =>
        field.type === 'switch' &&
        !field.readonly &&
        Boolean(field.key) &&
        !hierarchy.leads.has(field.key as string) &&
        !emphasisOf(field);

    const decorateField = (
        field: AdminField,
        renderer: SettingsSectionProps['renderField'],
    ) => {
        const emphasis = emphasisOf(field);
        const FieldIcon = appearance?.fields?.[field.key ?? '']?.Icon;
        const control = renderer(field);
        if ((!emphasis && !FieldIcon) || control == null) {
            return control;
        }
        return (
            <div
                key={field.key}
                data-setting-emphasis={emphasis}
                className={clsx(
                    'flex min-w-0 items-start gap-2.5',
                    emphasis === 'primary' &&
                        'mb-3 rounded-xl border border-accent/40 bg-accent-soft px-3 py-1',
                    emphasis === 'dependent' &&
                        'ms-3 border-s-2 border-edge-strong ps-3',
                )}
            >
                {FieldIcon ? (
                    <span
                        aria-hidden="true"
                        className="mt-3 shrink-0 rounded-lg bg-surface-sunken p-1.5 text-text-2"
                    >
                        <FieldIcon size={16} />
                    </span>
                ) : null}
                <div className="min-w-0 flex-1">{control}</div>
            </div>
        );
    };

    const renderFields = (groupFieldList: AdminField[]) =>
        layoutFields(
            groupFieldList,
            (field) => decorateField(field, renderField),
            flowsInGrid,
        );

    return (
        <GlassPanel
            id={sectionId}
            edge
            role="region"
            aria-labelledby={`${sectionId}-title`}
            className="admin-settings-distinct scroll-mt-4 border-edge-strong"
        >
            <div className="flex flex-wrap items-start justify-between gap-3 rounded-t-2xl border-b border-edge-strong bg-surface-2 p-4 sm:px-5">
                <div className="flex min-w-0 flex-1 flex-wrap items-start gap-3">
                    <span
                        aria-hidden="true"
                        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-edge-strong bg-surface-solid text-text-2"
                    >
                        <SectionIcon size={20} />
                    </span>
                    <div className="min-w-0 flex-1 basis-40">
                        <h2
                            id={`${sectionId}-title`}
                            tabIndex={-1}
                            className="text-lg leading-snug font-semibold text-text-1"
                        >
                            {label}
                        </h2>
                        <p className="mt-1 text-xs text-text-3">
                            {groupLabel}
                            {tabLabel ? ` · ${tabLabel}` : ''}
                        </p>
                    </div>
                </div>

                {presentation ? (
                    // Free to shrink once it has wrapped onto its own line, so a long
                    // status at a large text size wraps inside the card instead of past it.
                    <span
                        className={clsx(
                            'flex max-w-full min-w-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs',
                            presentation.className,
                        )}
                    >
                        <presentation.Icon size={11} className="shrink-0" />
                        {presentation.label}
                    </span>
                ) : null}
            </div>

            <div className="admin-section-body p-4 sm:p-5">
                {requirements.map((requirement) => (
                    <RequirementNotice
                        key={requirement.key}
                        requirement={requirement}
                        satisfied={asBoolean(readSectionValue(settings, draft, requirement.key))}
                        onNavigate={onNavigate}
                    />
                ))}

                {capability ? (
                    <div className={clsx(emphasisOf(capability) ? 'mb-1' : 'mb-1 border-b border-edge-strong pb-2')}>
                        {decorateField(capability, renderCapability)}
                    </div>
                ) : null}

                {groups.map((group) => (
                    <FieldGroup
                        key={group.id || '__ungrouped'}
                        group={group}
                        startOpen={shouldGroupStartOpen(group, status, capabilityOn)}
                        forceExpanded={forceExpanded}
                        renderFields={renderFields}
                    />
                ))}

                {children}
            </div>
        </GlassPanel>
    );
}
