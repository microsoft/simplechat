// SettingsSection.tsx
// One Admin Settings section, laid out so it can be read rather than scanned.
//
// The V2 surface used to render a section as a flat run of controls in declaration order.
// That works for Appearance, which is a handful of fields. It does not work for
// Knowledge: Document Intelligence alone is around forty controls, and the credential
// that makes the other thirty-nine work was simply the last one in the list.
//
// Three things change here:
//
// The capability toggle moves into the header, beside a status chip. The one control that
// decides whether the rest of the section matters should not be found by scrolling.
//
// Fields cluster into declared groups that collapse. A group opens when it is the one an
// administrator needs next -- an empty connection on an enabled capability -- and stays
// shut otherwise, so a configured section is a summary rather than a wall.
//
// A prerequisite owned by another section is stated where it is felt. Previously an
// administrator could turn File Sync on and have nothing happen, because Redis Cache was
// off two groups away and nothing said so until a flash message after saving.

import { useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import {
    AlertTriangle,
    ChevronRight,
    CircleDashed,
    CircleCheck,
    CircleSlash,
    type LucideIcon,
} from 'lucide-react';
import {
    asBoolean,
    groupFields,
    isFieldVisible,
    type AdminField,
    type RenderedFieldGroup,
} from '../../lib/adminFields';
import {
    collectRequirements,
    deriveSectionStatus,
    findCapabilityField,
    readSectionValue,
    shouldGroupStartOpen,
    type SectionStatus,
} from '../../lib/adminSections';
import { evaluateSectionStatus, type AdminSectionStatusRule } from '../../lib/adminFields';
import { GlassPanel } from '../ui/primitives';
import type { Json } from '../../lib/types';

const STATUS_PRESENTATION: Record<
    Exclude<SectionStatus, 'none'>,
    { label: string; className: string; Icon: typeof CircleCheck }
> = {
    off: {
        label: 'Off',
        className: 'text-text-3 border-edge',
        Icon: CircleSlash,
    },
    blocked: {
        label: 'Prerequisite missing',
        className: 'text-warn border-warn/40 bg-warn/5',
        Icon: AlertTriangle,
    },
    incomplete: {
        label: 'Needs configuration',
        className: 'text-warn border-warn/40 bg-warn/5',
        Icon: CircleDashed,
    },
    ready: {
        label: 'Configured',
        className: 'text-ok border-ok/40 bg-ok/5',
        Icon: CircleCheck,
    },
};

/** A declared status uses different words for the same three states. */
const DECLARED_STATUS_MAP: Record<'off' | 'unconfigured' | 'on', SectionStatus> = {
    off: 'off',
    unconfigured: 'incomplete',
    on: 'ready',
};

export interface SettingsSectionAppearance {
    Icon: LucideIcon;
    fields?: Readonly<Partial<Record<string, {
        emphasis?: 'primary' | 'dependent';
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
    renderField: (field: AdminField) => React.ReactNode;
    /** Renders the capability toggle, so switch acknowledgements keep working. */
    renderCapability: (field: AdminField) => React.ReactNode;
    /**
     * A server-declared status rule, used in preference to deriving one.
     *
     * Sections that describe `required` fields have their status derived from those.
     * A declared rule exists for sections where "configured" depends on a combination
     * the field metadata cannot express on its own.
     */
    statusRule?: AdminSectionStatusRule;
    /** Force every group open, used while a search is filtering the page. */
    forceExpanded?: boolean;
    /** Opt-in visual hierarchy; does not change the schema's behavior. */
    appearance?: SettingsSectionAppearance;
    children?: React.ReactNode;
}

function RequirementNotice({
    requirement,
    satisfied,
}: {
    requirement: NonNullable<AdminField['requires']>;
    satisfied: boolean;
}) {
    if (satisfied) {
        return null;
    }

    const blocking = (requirement.mode ?? 'block') === 'block';

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
                {requirement.target_section ? (
                    <a
                        href={`/admin/settings#${requirement.target_section}`}
                        className="mt-1 inline-block text-accent underline"
                    >
                        Configure {requirement.label}
                    </a>
                ) : null}
            </div>
        </div>
    );
}

function FieldGroup({
    group,
    startOpen,
    forceExpanded,
    renderField,
    distinct = false,
}: {
    group: RenderedFieldGroup;
    startOpen: boolean;
    forceExpanded?: boolean;
    renderField: (field: AdminField) => React.ReactNode;
    distinct?: boolean;
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
        return (
            <div className={clsx('divide-y', distinct ? 'divide-edge-strong' : 'divide-edge')}>
                {group.fields.map(renderField)}
            </div>
        );
    }

    return (
        <div
            className={clsx(
                'border',
                distinct
                    ? 'mt-3 rounded-xl border-edge-strong bg-surface-solid'
                    : 'mt-2 rounded-lg border-edge',
            )}
        >
            <button
                type="button"
                aria-expanded={open}
                className={clsx(
                    'flex w-full items-center gap-2 px-3 py-2 text-left',
                    distinct
                        ? 'min-h-11 rounded-xl hover:bg-surface-sunken'
                        : 'hover:bg-surface-2',
                    distinct && open && 'rounded-b-none bg-surface-sunken',
                )}
                onClick={() => setOpen((previous) => !previous)}
            >
                <ChevronRight
                    size={14}
                    className={clsx(
                        'shrink-0 transition-transform',
                        distinct ? 'text-text-2' : 'text-text-3',
                        open && 'rotate-90',
                    )}
                />
                <span
                    className={distinct
                        ? 'min-w-0 text-sm font-semibold text-text-1'
                        : 'text-xs font-medium text-text-2'}
                >
                    {group.label ?? group.id}
                </span>
                {!open ? (
                    <span className={clsx('ml-auto text-xs text-text-3', distinct && 'shrink-0')}>
                        {group.fields.length}{' '}
                        {group.fields.length === 1 ? 'setting' : 'settings'}
                    </span>
                ) : null}
            </button>

            {open ? (
                <div
                    className={clsx(
                        'border-t px-3 pb-1',
                        distinct ? 'border-edge-strong' : 'border-edge',
                    )}
                >
                    {group.help ? (
                        <p className="pt-2 text-xs leading-relaxed text-text-3">{group.help}</p>
                    ) : null}
                    <div className={clsx('divide-y', distinct ? 'divide-edge-strong' : 'divide-edge')}>
                        {group.fields.map(renderField)}
                    </div>
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
    renderField,
    renderCapability,
    forceExpanded,
    appearance,
    children,
}: SettingsSectionProps) {
    const capability = useMemo(() => findCapabilityField(fields), [fields]);

    const bodyFields = useMemo(
        () => fields.filter((field) => field !== capability),
        [fields, capability],
    );

    const status = useMemo(() => {
        // A declared rule wins: it exists precisely for sections whose "configured"
        // state the field metadata cannot express.
        const declared = evaluateSectionStatus(statusRule, settings, draft);
        if (declared) {
            return DECLARED_STATUS_MAP[declared];
        }
        return deriveSectionStatus(fields, settings, draft);
    }, [statusRule, fields, settings, draft]);

    const capabilityOn = capability?.key
        ? asBoolean(readSectionValue(settings, draft, capability.key))
        : true;

    // A section states each distinct prerequisite once, at the top, rather than repeating
    // it on every field that carries it.
    const requirements = useMemo(() => collectRequirements(fields), [fields]);

    const groups = useMemo(
        () => groupFields(bodyFields.filter((field) => isFieldVisible(field, settings, draft))),
        [bodyFields, settings, draft],
    );

    const presentation = status === 'none' ? null : STATUS_PRESENTATION[status];

    const decorateField = (
        field: AdminField,
        renderer: SettingsSectionProps['renderField'],
    ) => {
        const fieldAppearance = appearance?.fields?.[field.key ?? ''];
        const control = renderer(field);
        if (!fieldAppearance || control == null) {
            return control;
        }
        return (
            <div
                key={field.key}
                data-setting-emphasis={fieldAppearance.emphasis}
                className={clsx(
                    'flex min-w-0 items-start gap-2.5',
                    fieldAppearance.emphasis === 'primary' &&
                        'mb-3 rounded-xl border border-accent/40 bg-accent-soft px-3 py-1',
                    fieldAppearance.emphasis === 'dependent' &&
                        'ms-3 border-s-2 border-edge-strong ps-3',
                )}
            >
                {fieldAppearance.Icon ? (
                    <span
                        aria-hidden="true"
                        className="mt-3 shrink-0 rounded-lg bg-surface-sunken p-1.5 text-text-2"
                    >
                        <fieldAppearance.Icon size={16} />
                    </span>
                ) : null}
                <div className="min-w-0 flex-1">{control}</div>
            </div>
        );
    };

    const body = (
        <>
            {requirements.map((requirement) => (
                <RequirementNotice
                    key={requirement.key}
                    requirement={requirement}
                    satisfied={asBoolean(readSectionValue(settings, draft, requirement.key))}
                />
            ))}

            {capability ? (
                <div className="mb-1 border-b border-edge pb-2">
                    {decorateField(capability, renderCapability)}
                </div>
            ) : null}

            {groups.map((group) => (
                <FieldGroup
                    key={group.id || '__ungrouped'}
                    group={group}
                    startOpen={shouldGroupStartOpen(group, status, capabilityOn)}
                    forceExpanded={forceExpanded}
                    renderField={(field) => decorateField(field, renderField)}
                    distinct={Boolean(appearance)}
                />
            ))}

            {children}
        </>
    );

    return (
        <GlassPanel
            id={sectionId}
            edge
            role={appearance ? 'region' : undefined}
            aria-labelledby={appearance ? `${sectionId}-title` : undefined}
            className={appearance ? 'admin-settings-distinct border-edge-strong' : 'p-4'}
        >
            <div
                className={clsx(
                    'flex items-start justify-between gap-3',
                    appearance
                        ? 'flex-wrap rounded-t-2xl border-b border-edge-strong bg-surface-2 p-4 sm:px-5'
                        : 'mb-2',
                )}
            >
                <div className={clsx('min-w-0', appearance && 'flex flex-1 flex-wrap items-start gap-3')}>
                    {appearance ? (
                        <span
                            aria-hidden="true"
                            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-edge-strong bg-surface-solid text-text-2"
                        >
                            <appearance.Icon size={20} />
                        </span>
                    ) : null}
                    <div className={clsx('min-w-0', appearance && 'flex-1 basis-40')}>
                        <h2
                            id={appearance ? `${sectionId}-title` : undefined}
                            className={clsx(
                                'font-semibold text-text-1',
                                appearance ? 'text-lg leading-snug' : 'text-sm',
                            )}
                        >
                            {label}
                        </h2>
                        <p className={clsx('text-xs text-text-3', appearance && 'mt-1')}>
                            {groupLabel}
                            {tabLabel ? ` · ${tabLabel}` : ''}
                        </p>
                    </div>
                </div>

                {presentation ? (
                    <span
                        className={clsx(
                            'flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs',
                            presentation.className,
                        )}
                    >
                        <presentation.Icon size={11} />
                        {presentation.label}
                    </span>
                ) : null}
            </div>

            {appearance ? <div className="admin-section-body p-4 sm:p-5">{body}</div> : body}
        </GlassPanel>
    );
}
