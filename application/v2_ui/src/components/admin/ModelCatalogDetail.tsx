// ModelCatalogDetail.tsx
// One catalog profile: what it is, what it is good at, and where it is connected.
//
// The classic detail panel printed every fact in one column, which made a single profile
// several screens long. Here the header keeps what an administrator acts on -- the name,
// where the profile comes from, and its routing preferences -- and the rest is split into
// tabs, each short enough to read without scrolling on a wide screen.

import { useId, useRef, type KeyboardEvent, type ReactNode, type RefObject } from 'react';
import { clsx } from 'clsx';
import {
    Archive,
    ArchiveRestore,
    ArrowUpRight,
    CircleCheck,
    CircleHelp,
    CircleX,
    Copy,
    ExternalLink,
    Pencil,
    Server,
    Star,
    TriangleAlert,
} from 'lucide-react';
import {
    CAPABILITY_GROUP_LABELS,
    CATALOG_CAPABILITIES,
    PRIORITY_OPTIONS,
    SUITABILITY_LABELS,
    capabilityLabel,
    evidenceDescription,
    evidenceLabel,
    formatTokenLimit,
    isLifecycleWarning,
    lifecycleLabel,
    linkedModelCount,
    publisherLabel,
    readSuitability,
    safeEvidenceUrl,
    type CapabilityGroup,
    type CatalogConnectionTarget,
    type CatalogPriority,
    type CatalogProfile,
    type TaskSuitability,
} from '../../lib/modelCatalog';
import { GlassButton } from '../ui/primitives';
import { inputClass } from './fields';

export type CatalogDetailTab = 'overview' | 'capabilities' | 'connections' | 'evidence';

const TABS: ReadonlyArray<{ id: CatalogDetailTab; label: string }> = [
    { id: 'overview', label: 'Overview' },
    { id: 'capabilities', label: 'Capabilities' },
    { id: 'connections', label: 'Connections' },
    { id: 'evidence', label: 'Evidence' },
];

/** Technical facts that only make sense as structured data, shown collapsed. */
const ADVANCED_TECHNICAL: ReadonlyArray<[string, string]> = [
    ['tokenLimitEvidence', 'Token capacity evidence'],
    ['tokenLimitProfiles', 'Hosted capacity profiles'],
    ['reasoningPolicy', 'Reasoning policy'],
    ['embeddingPolicy', 'Embedding policy'],
    ['imageProfiles', 'Image operation profiles'],
];

const SUITABILITY_TONE: Readonly<Record<TaskSuitability, string>> = {
    strong: 'bg-ok-soft text-ok',
    suitable: 'bg-accent-soft text-accent',
    unsuitable: 'bg-danger-soft text-danger',
    unknown: 'bg-surface-sunken text-text-3',
};

function Chip({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'warn' }) {
    return (
        <span
            className={clsx(
                'inline-flex items-center rounded-full border px-2 py-0.5 text-xs',
                tone === 'warn'
                    ? 'border-warn/40 bg-warn-soft text-warn'
                    : 'border-edge-strong text-text-2',
            )}
        >
            {children}
        </span>
    );
}

function SectionTitle({ children }: { children: ReactNode }) {
    return <h4 className="text-sm font-semibold text-text-1">{children}</h4>;
}

function TextList({ title, items }: { title: string; items: string[] }) {
    return (
        <section>
            <SectionTitle>{title}</SectionTitle>
            {items.length ? (
                <ul className="mt-2 list-disc space-y-1.5 ps-5 text-sm leading-relaxed text-text-2 marker:text-text-3">
                    {items.map((item, index) => (
                        <li key={`${index}-${item}`}>{item}</li>
                    ))}
                </ul>
            ) : (
                <p className="mt-2 text-sm text-text-3">Not documented.</p>
            )}
        </section>
    );
}

function CapabilityRow({ label, value }: { label: string; value: unknown }) {
    const state = value === true ? 'supported' : value === false ? 'unsupported' : 'unknown';
    const Icon = state === 'supported' ? CircleCheck : state === 'unsupported' ? CircleX : CircleHelp;
    const stateText = state === 'supported' ? 'Supported' : state === 'unsupported' ? 'Not supported' : 'Unknown';
    // The icon's shape carries the state for sighted readers; the text is there for
    // assistive technology and on hover, which keeps three columns readable.
    return (
        <li className="flex items-center gap-2 py-1.5 text-sm" title={stateText}>
            <Icon
                size={15}
                aria-hidden="true"
                className={clsx('shrink-0', state === 'supported' ? 'text-ok' : 'text-text-3')}
            />
            <span className={clsx('min-w-0 flex-1', state === 'supported' ? 'text-text-1' : 'text-text-3')}>
                {label}
                <span className="sr-only">: {stateText}</span>
            </span>
        </li>
    );
}

function OverviewPanel({ profile, tasks }: { profile: CatalogProfile; tasks: Record<string, string> }) {
    // Every declared task is listed, so "Unknown" reads as a rating rather than an omission.
    const taskEntries: [string, string][] = [
        ...Object.entries(tasks),
        ...Object.keys(profile.tasks ?? {})
            .filter((key) => !(key in tasks))
            .map((key): [string, string] => [key, key]),
    ];
    return (
        <div className="space-y-6">
            {profile.chatCompletions === false ? (
                <p className="flex items-start gap-2 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-sm text-warn">
                    <TriangleAlert size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
                    This model requires a different API and is not eligible for Auto orchestration.
                </p>
            ) : null}

            <div className="grid gap-6 @2xl:grid-cols-2">
                <TextList title="Strengths" items={profile.strengths ?? []} />
                <TextList title="Limitations" items={profile.limitations ?? []} />
            </div>

            <section>
                <SectionTitle>Task suitability</SectionTitle>
                <ul className="mt-2 grid gap-x-8 @xl:grid-cols-2 @4xl:grid-cols-3">
                    {taskEntries.map(([key, label]) => {
                        const rating = readSuitability(profile.tasks?.[key]);
                        return (
                            <li
                                key={key}
                                className="flex items-center justify-between gap-3 border-b border-edge-strong py-2 text-sm text-text-2"
                            >
                                <span className="min-w-0">{label}</span>
                                <span
                                    className={clsx(
                                        'shrink-0 rounded-full px-2 py-0.5 text-xs font-medium',
                                        SUITABILITY_TONE[rating],
                                    )}
                                >
                                    {SUITABILITY_LABELS[rating]}
                                </span>
                            </li>
                        );
                    })}
                </ul>
            </section>

            <section>
                <SectionTitle>Routing</SectionTitle>
                <p className="mt-2 max-w-[72ch] text-[0.8125rem] leading-relaxed text-text-3">
                    Auto ranks eligible models by task suitability first, then priority, then
                    favorite. Preferences do not change access or chat defaults.
                </p>
            </section>
        </div>
    );
}

function CapabilitiesPanel({ profile }: { profile: CatalogProfile }) {
    const technical = profile.technical ?? {};
    const known = new Set(CATALOG_CAPABILITIES.map((item) => item.key));
    const others = Object.keys(profile.capabilities ?? {}).filter((key) => !known.has(key)).sort();
    const lifecycle = lifecycleLabel(technical.lifecycle);
    const advanced = ADVANCED_TECHNICAL.filter(([key]) => technical[key] != null);

    return (
        <div className="space-y-6">
            <div className="grid gap-6 @2xl:grid-cols-3">
                {(['input', 'output', 'feature'] as CapabilityGroup[]).map((group) => (
                    <section key={group}>
                        <SectionTitle>{CAPABILITY_GROUP_LABELS[group]}</SectionTitle>
                        <ul className="mt-1 divide-y divide-edge-strong">
                            {CATALOG_CAPABILITIES.filter((item) => item.group === group).map((item) => (
                                <CapabilityRow
                                    key={item.key}
                                    label={item.label}
                                    value={profile.capabilities?.[item.key]}
                                />
                            ))}
                        </ul>
                    </section>
                ))}
            </div>

            {others.length ? (
                <section>
                    <SectionTitle>Other operations</SectionTitle>
                    <ul className="mt-1 grid gap-x-8 divide-y divide-edge-strong @2xl:grid-cols-3">
                        {others.map((key) => (
                            <CapabilityRow key={key} label={capabilityLabel(key)} value={profile.capabilities[key]} />
                        ))}
                    </ul>
                </section>
            ) : null}

            <section>
                <SectionTitle>Limits and lifecycle</SectionTitle>
                <dl className="mt-2 grid gap-x-8 gap-y-3 @xl:grid-cols-2 @4xl:grid-cols-4">
                    {([
                        ['Context window', formatTokenLimit(technical.contextWindow)],
                        ['Input token limit', formatTokenLimit(technical.inputTokenLimit)],
                        ['Output token limit', formatTokenLimit(technical.outputTokenLimit)],
                        ['Lifecycle', lifecycle ?? 'Not documented'],
                    ] as [string, string][]).map(([label, value]) => (
                        <div key={label}>
                            <dt className="text-xs text-text-3">{label}</dt>
                            <dd className="mt-0.5 text-sm font-medium tabular-nums text-text-1">{value}</dd>
                        </div>
                    ))}
                </dl>
                <p className="mt-3 max-w-[72ch] text-xs leading-relaxed text-text-3">
                    Capacity and operation support remain provider-qualified. Connection
                    overrides and access still apply.
                </p>
            </section>

            {advanced.length ? (
                <section className="space-y-2">
                    <SectionTitle>Technical detail</SectionTitle>
                    {advanced.map(([key, label]) => (
                        <details key={key} className="rounded-lg border border-edge-strong">
                            <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-text-1">
                                {label}
                            </summary>
                            <pre className="overflow-x-auto border-t border-edge-strong px-3 py-2 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap text-text-2">
                                {JSON.stringify(technical[key], null, 2)}
                            </pre>
                        </details>
                    ))}
                </section>
            ) : null}
        </div>
    );
}

function ConnectionsPanel({
    profile,
    onOpenConnection,
}: {
    profile: CatalogProfile;
    onOpenConnection?: (target?: CatalogConnectionTarget) => void;
}) {
    const links = profile.linked_models ?? [];
    return (
        <div className="space-y-3">
            {links.length === 0 ? (
                <div className="rounded-xl border border-dashed border-edge-strong px-4 py-6">
                    <p className="text-sm font-medium text-text-1">
                        No global AI Connection uses this profile yet.
                    </p>
                    <p className="mt-1 max-w-[72ch] text-[0.8125rem] leading-relaxed text-text-3">
                        To link one, edit a model in AI Connections and choose this profile as
                        its Catalog profile. One profile can describe several deployments.
                    </p>
                    {onOpenConnection ? (
                        <GlassButton
                            type="button"
                            variant="subtle"
                            size="sm"
                            className="mt-3"
                            onClick={() => onOpenConnection()}
                        >
                            Go to AI Connections
                            <ArrowUpRight size={14} aria-hidden="true" />
                        </GlassButton>
                    ) : null}
                </div>
            ) : (
                <ul className="divide-y divide-edge-strong rounded-xl border border-edge-strong">
                    {links.map((link, index) => {
                        const support = Object.entries(link.capabilities ?? {})
                            .filter(([, value]) => value)
                            .map(([key]) => capabilityLabel(key));
                        return (
                            <li
                                key={`${link.connection_id ?? link.connection}-${link.model_id ?? link.model}-${index}`}
                                data-testid="catalog-linked-model"
                                className="flex flex-wrap items-start gap-3 p-3"
                            >
                                <Server size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-text-3" />
                                <div className="min-w-0 flex-1 basis-48">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <span className="font-mono text-sm font-semibold break-all text-text-1">
                                            {link.model}
                                        </span>
                                        <span
                                            className={clsx(
                                                'rounded-full px-2 py-0.5 text-xs font-medium',
                                                link.enabled ? 'bg-ok-soft text-ok' : 'bg-surface-sunken text-text-3',
                                            )}
                                        >
                                            {link.enabled ? 'Enabled' : 'Disabled'}
                                        </span>
                                    </div>
                                    <p className="mt-0.5 text-xs text-text-3">{link.connection}</p>
                                    <p className="mt-2 text-xs text-text-3">
                                        <span className="font-medium text-text-2">Effective support: </span>
                                        {support.length ? support.join(', ') : 'Not declared'}
                                    </p>
                                </div>
                                {onOpenConnection && link.connection_id ? (
                                    <GlassButton
                                        type="button"
                                        variant="subtle"
                                        size="sm"
                                        aria-label={`Open in AI Connections: ${link.model}`}
                                        onClick={() =>
                                            onOpenConnection({
                                                connectionId: link.connection_id as string,
                                                modelId: link.model_id || undefined,
                                                modelName: link.model,
                                            })
                                        }
                                    >
                                        Open in AI Connections
                                        <ArrowUpRight size={14} aria-hidden="true" />
                                    </GlassButton>
                                ) : null}
                            </li>
                        );
                    })}
                </ul>
            )}
            <p className="text-xs text-text-3">
                Personal and group connections are managed in their own workspaces. A profile
                never publishes a deployment.
            </p>
        </div>
    );
}

function EvidencePanel({ profile }: { profile: CatalogProfile }) {
    const sources = (profile.sources ?? [])
        .map((source) => ({ source, href: safeEvidenceUrl(source) }))
        .filter((entry) => entry.href);
    return (
        <div className="space-y-6">
            <dl className="grid gap-x-8 gap-y-4 @xl:grid-cols-2">
                <div>
                    <dt className="text-xs text-text-3">Evidence</dt>
                    <dd className="mt-0.5 text-sm font-medium text-text-1">{evidenceLabel(profile.evidence)}</dd>
                    <dd className="mt-1 max-w-[60ch] text-[0.8125rem] leading-relaxed text-text-3">
                        {evidenceDescription(profile.evidence)}
                    </dd>
                </div>
                <div>
                    <dt className="text-xs text-text-3">Profile ID</dt>
                    <dd className="mt-0.5 font-mono text-sm break-all text-text-1">{profile.id}</dd>
                    {profile.verifiedAt ? (
                        <dd className="mt-1 text-[0.8125rem] text-text-3">Reviewed {profile.verifiedAt}</dd>
                    ) : null}
                </div>
            </dl>

            <section>
                <SectionTitle>Sources</SectionTitle>
                {sources.length ? (
                    <ul className="mt-2 space-y-1.5">
                        {sources.map(({ source, href }) => (
                            <li key={source}>
                                <a
                                    href={safeEvidenceUrl(href) ?? undefined}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex max-w-full items-start gap-1.5 text-sm break-all text-accent underline"
                                >
                                    <ExternalLink size={13} aria-hidden="true" className="mt-1 shrink-0" />
                                    {source}
                                </a>
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p className="mt-2 text-sm text-text-3">No sources recorded.</p>
                )}
            </section>

            <section>
                <SectionTitle>Aliases</SectionTitle>
                {profile.aliases?.length ? (
                    <ul className="mt-2 flex flex-wrap gap-1.5">
                        {profile.aliases.map((alias) => (
                            <li key={alias} className="rounded-md bg-surface-sunken px-2 py-0.5 font-mono text-xs text-text-2">
                                {alias}
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p className="mt-2 text-sm text-text-3">None.</p>
                )}
            </section>
        </div>
    );
}

export function ModelCatalogDetail({
    profile,
    tasks,
    tab,
    onTabChange,
    onToggleFavorite,
    onPriorityChange,
    onDuplicate,
    onEdit,
    onToggleArchive,
    onOpenConnection,
    headingRef,
}: {
    profile: CatalogProfile;
    tasks: Record<string, string>;
    tab: CatalogDetailTab;
    onTabChange: (tab: CatalogDetailTab) => void;
    onToggleFavorite: () => void;
    onPriorityChange: (priority: CatalogPriority) => void;
    onDuplicate: () => void;
    onEdit: () => void;
    onToggleArchive: () => void;
    onOpenConnection?: (target?: CatalogConnectionTarget) => void;
    headingRef?: RefObject<HTMLHeadingElement>;
}) {
    const baseId = useId();
    const tabRefs = useRef<Partial<Record<CatalogDetailTab, HTMLButtonElement | null>>>({});
    const favorite = Boolean(profile.preferences?.favorite);
    const lifecycle = profile.technical?.lifecycle;
    const lifecycleText = lifecycleLabel(lifecycle);
    const custom = profile.origin === 'custom';
    const connected = linkedModelCount(profile);

    // Arrow keys move between tabs and select as they go, the usual tablist behaviour.
    const onTabKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
        const index = TABS.findIndex((item) => item.id === tab);
        let next = index;
        if (event.key === 'ArrowRight') next = (index + 1) % TABS.length;
        else if (event.key === 'ArrowLeft') next = (index - 1 + TABS.length) % TABS.length;
        else if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = TABS.length - 1;
        else return;
        event.preventDefault();
        const nextTab = TABS[next].id;
        onTabChange(nextTab);
        tabRefs.current[nextTab]?.focus();
    };

    return (
        <article aria-labelledby={`${baseId}-title`} className="flex min-h-full flex-col">
            <header className="px-4 pt-4 sm:px-5">
                <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
                    <div className="min-w-0 flex-1 basis-64">
                        <h3
                            id={`${baseId}-title`}
                            ref={headingRef}
                            tabIndex={-1}
                            className="text-xl leading-snug font-semibold break-words text-text-1"
                        >
                            {profile.displayName}
                        </h3>
                        <div className="mt-2 flex flex-wrap items-center gap-1.5">
                            <Chip>{publisherLabel(profile.publisher)}</Chip>
                            <Chip>{custom ? 'Custom' : 'Built-in'}</Chip>
                            <Chip>{evidenceLabel(profile.evidence)}</Chip>
                            {lifecycleText ? (
                                <Chip tone={isLifecycleWarning(lifecycle) ? 'warn' : 'neutral'}>{lifecycleText}</Chip>
                            ) : null}
                            {profile.archived ? <Chip tone="warn">Archived</Chip> : null}
                        </div>
                    </div>

                    <div className="flex flex-wrap items-end gap-2">
                        <GlassButton
                            id={`${baseId}-favorite`}
                            type="button"
                            variant="subtle"
                            size="md"
                            onClick={onToggleFavorite}
                        >
                            <Star
                                size={15}
                                aria-hidden="true"
                                className={clsx(favorite ? 'fill-current text-warn' : 'text-text-3')}
                            />
                            {favorite ? 'Remove favorite' : 'Favorite'}
                        </GlassButton>
                        <div className="flex flex-col gap-1">
                            <label htmlFor={`${baseId}-priority`} className="text-xs font-medium text-text-2">
                                Priority
                            </label>
                            <select
                                id={`${baseId}-priority`}
                                className={clsx(inputClass, 'w-auto min-w-[9rem]')}
                                value={profile.preferences?.priority ?? 'standard'}
                                onChange={(event) => onPriorityChange(event.target.value as CatalogPriority)}
                            >
                                {PRIORITY_OPTIONS.map((option) => (
                                    <option key={option.value} value={option.value}>
                                        {option.label}
                                    </option>
                                ))}
                            </select>
                        </div>
                    </div>
                </div>

                {profile.summary ? (
                    <p className="mt-3 max-w-[80ch] text-sm leading-relaxed text-text-2">{profile.summary}</p>
                ) : null}

                <div className="mt-3 flex flex-wrap gap-2">
                    <GlassButton type="button" variant="subtle" size="sm" onClick={onDuplicate}>
                        <Copy size={14} aria-hidden="true" />
                        Duplicate as custom
                    </GlassButton>
                    {custom ? (
                        <>
                            <GlassButton type="button" variant="subtle" size="sm" onClick={onEdit}>
                                <Pencil size={14} aria-hidden="true" />
                                Edit profile
                            </GlassButton>
                            <GlassButton type="button" variant="subtle" size="sm" onClick={onToggleArchive}>
                                {profile.archived ? (
                                    <ArchiveRestore size={14} aria-hidden="true" />
                                ) : (
                                    <Archive size={14} aria-hidden="true" />
                                )}
                                {profile.archived ? 'Unarchive profile' : 'Archive profile'}
                            </GlassButton>
                        </>
                    ) : null}
                </div>
            </header>

            <div
                role="tablist"
                aria-label="Profile details"
                onKeyDown={onTabKeyDown}
                className="sticky top-0 z-10 mt-4 flex gap-1 overflow-x-auto border-b border-edge-strong bg-surface-solid px-4 sm:px-5"
            >
                {TABS.map((item) => {
                    const selected = item.id === tab;
                    return (
                        <button
                            key={item.id}
                            ref={(element) => {
                                tabRefs.current[item.id] = element;
                            }}
                            id={`${baseId}-tab-${item.id}`}
                            type="button"
                            role="tab"
                            aria-selected={selected}
                            aria-controls={`${baseId}-panel`}
                            tabIndex={selected ? 0 : -1}
                            onClick={() => onTabChange(item.id)}
                            className={clsx(
                                '-mb-px flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm transition-colors',
                                selected
                                    ? 'border-accent font-semibold text-accent'
                                    : 'border-transparent text-text-2 hover:text-text-1',
                            )}
                        >
                            {item.label}
                            {item.id === 'connections' ? (
                                <span
                                    className={clsx(
                                        'rounded-full px-1.5 text-xs tabular-nums',
                                        connected ? 'bg-accent-soft text-accent' : 'bg-surface-sunken text-text-3',
                                    )}
                                >
                                    {connected}
                                </span>
                            ) : null}
                        </button>
                    );
                })}
            </div>

            <div
                id={`${baseId}-panel`}
                role="tabpanel"
                aria-labelledby={`${baseId}-tab-${tab}`}
                tabIndex={0}
                className="flex-1 px-4 py-5 sm:px-5"
            >
                {tab === 'overview' ? <OverviewPanel profile={profile} tasks={tasks} /> : null}
                {tab === 'capabilities' ? <CapabilitiesPanel profile={profile} /> : null}
                {tab === 'connections' ? (
                    <ConnectionsPanel profile={profile} onOpenConnection={onOpenConnection} />
                ) : null}
                {tab === 'evidence' ? <EvidencePanel profile={profile} /> : null}
            </div>
        </article>
    );
}
