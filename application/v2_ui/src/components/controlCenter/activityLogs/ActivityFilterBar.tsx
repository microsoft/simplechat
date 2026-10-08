// ActivityFilterBar.tsx
// One toolbar row that is also the investigation's state: a search field plus Azure-portal
// style pills. Each pill shows its value in human terms (names, not IDs) and applies as soon
// as it changes, so there is no separate Apply step.

import { useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react';
import { clsx } from 'clsx';
import { Plus, Search, X } from 'lucide-react';
import {
    DEFAULT_RANGE, RANGE_PRESETS, TOKEN_TYPES, dateRangeLabel, humanize, isDefaultFilters, looksLikeId,
    presetDates, rangeValidationError, shortId,
    type ActivityFilterLabels, type ActivityFilters, type ActivityPersonOption, type ActivityTypeOption,
    type ActivityWorkspaceOption, type WorkspaceType,
} from '../../../lib/activityLogs';
import { GlassButton } from '../../ui/primitives';
import { EntityCombobox, type EntityResult } from './EntityCombobox';
import { AnchoredPopover, FilterPill, usePopover } from './FilterPill';

const SEARCH_DEBOUNCE_MS = 400;
const FIELD = 'h-9 w-full rounded-lg border border-edge bg-surface-1 px-2.5 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none';
const OPTION = 'flex w-full items-center justify-between gap-3 rounded-lg px-2.5 py-2 text-left text-sm transition-colors focus-visible:outline-2 focus-visible:outline-accent';

type ExtraFilter = 'model' | 'token_type' | 'status';
const EXTRA_FILTERS: { key: ExtraFilter; label: string }[] = [
    { key: 'model', label: 'Model' },
    { key: 'token_type', label: 'Token type' },
    { key: 'status', label: 'Recorded status' },
];

export interface FilterChangeOptions {
    replace?: boolean;
}

function optionClass(selected: boolean) {
    return clsx(OPTION, selected ? 'bg-accent-soft font-medium text-accent' : 'text-text-1 hover:bg-surface-2');
}

function PopoverHeading({ children }: { children: string }) {
    return <h3 className="mb-2 text-sm font-semibold text-text-1">{children}</h3>;
}

function DatePopover({ filters, onChange, close }: {
    filters: ActivityFilters;
    onChange: (next: ActivityFilters) => void;
    close: () => void;
}) {
    const [custom, setCustom] = useState(!filters.range);
    const [start, setStart] = useState(filters.start_date);
    const [end, setEnd] = useState(filters.end_date);
    const [error, setError] = useState('');
    return (
        <div>
            <PopoverHeading>Date range</PopoverHeading>
            <div className="space-y-0.5">
                {RANGE_PRESETS.map((preset) => (
                    <button key={preset.id} type="button" aria-pressed={filters.range === preset.id}
                        className={optionClass(filters.range === preset.id)}
                        onClick={() => { onChange({ ...filters, range: preset.id, ...presetDates(preset.id) }); close(); }}>
                        {preset.label}
                    </button>
                ))}
                <button type="button" aria-pressed={custom} aria-expanded={custom} className={optionClass(custom)}
                    onClick={() => setCustom(true)}>
                    Custom range
                </button>
            </div>
            {custom ? (
                <form className="mt-3 space-y-2 border-t border-edge pt-3" onSubmit={(event) => {
                    event.preventDefault();
                    const problem = rangeValidationError(start, end);
                    setError(problem);
                    if (problem) return;
                    onChange({ ...filters, range: '', start_date: start, end_date: end });
                    close();
                }}>
                    <div className="grid grid-cols-2 gap-2">
                        <label className="text-xs text-text-2">Start date (UTC)
                            <input type="date" className={clsx(FIELD, 'mt-1')} value={start} required
                                onChange={(event) => setStart(event.target.value)} />
                        </label>
                        <label className="text-xs text-text-2">End date (UTC)
                            <input type="date" className={clsx(FIELD, 'mt-1')} value={end} required
                                onChange={(event) => setEnd(event.target.value)} />
                        </label>
                    </div>
                    {error ? <p role="alert" className="text-xs text-danger">{error}</p> : null}
                    <GlassButton type="submit" size="sm" variant="primary">Apply range</GlassButton>
                </form>
            ) : null}
            <p className="mt-3 text-xs text-text-3">Days are UTC calendar days. Ranges can span up to 366 days.</p>
        </div>
    );
}

function ActivityPopover({ filters, typeOptions, counts, onChange, close }: {
    filters: ActivityFilters;
    typeOptions: ActivityTypeOption[];
    counts: Map<string, number>;
    onChange: (next: ActivityFilters) => void;
    close: () => void;
}) {
    const [find, setFind] = useState('');
    const groups = useMemo(() => {
        const known = new Map(typeOptions.map((option) => [option.activity_type, option]));
        const extra = [...new Set([...counts.keys(), ...filters.activity_type])]
            .filter((type) => !known.has(type))
            .map((type) => ({ activity_type: type, label: humanize(type) || 'Unknown', category: 'other', category_label: 'Other' }));
        const term = find.trim().toLowerCase();
        const grouped = new Map<string, { label: string; options: ActivityTypeOption[] }>();
        for (const option of [...typeOptions, ...extra]) {
            if (term && !option.label.toLowerCase().includes(term) && !option.activity_type.includes(term)) continue;
            const group = grouped.get(option.category) ?? { label: option.category_label, options: [] };
            group.options.push(option);
            grouped.set(option.category, group);
        }
        return [...grouped.values()];
    }, [typeOptions, counts, filters.activity_type, find]);
    const toggle = (type: string) => {
        const selected = filters.activity_type.includes(type)
            ? filters.activity_type.filter((item) => item !== type)
            : [...filters.activity_type, type];
        onChange({ ...filters, activity_type: selected });
    };
    return (
        <div>
            <PopoverHeading>Activity types</PopoverHeading>
            <label className="sr-only" htmlFor="activity-type-find">Find an activity type</label>
            <input id="activity-type-find" data-autofocus type="search" value={find} placeholder="Find an activity type"
                onChange={(event) => setFind(event.target.value)} className={FIELD} />
            <div className="mt-2 max-h-72 space-y-3 overflow-y-auto pr-1">
                {groups.length === 0 ? <p className="py-3 text-sm text-text-3">No activity type matches “{find}”.</p> : null}
                {groups.map((group) => (
                    <fieldset key={group.label}>
                        <legend className="mb-1 text-xs font-medium text-text-3">{group.label}</legend>
                        {group.options.map((option) => {
                            const count = counts.get(option.activity_type);
                            return (
                                <label key={option.activity_type}
                                    className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm text-text-1 hover:bg-surface-2">
                                    <input type="checkbox" className="accent-accent"
                                        checked={filters.activity_type.includes(option.activity_type)}
                                        onChange={() => toggle(option.activity_type)} />
                                    <span className="min-w-0 flex-1 truncate">{option.label}</span>
                                    {count ? <span className="shrink-0 text-xs tabular-nums text-text-3">{count.toLocaleString()}</span> : null}
                                </label>
                            );
                        })}
                    </fieldset>
                ))}
            </div>
            <div className="mt-3 flex items-center justify-between border-t border-edge pt-3">
                <p className="text-xs text-text-3">Counts cover the current date range and filters.</p>
                <div className="flex gap-1">
                    {filters.activity_type.length ? (
                        <GlassButton size="sm" onClick={() => onChange({ ...filters, activity_type: [] })}>Clear</GlassButton>
                    ) : null}
                    <GlassButton size="sm" variant="primary" onClick={close}>Done</GlassButton>
                </div>
            </div>
        </div>
    );
}

function TextFilterPopover({ title, label, help, initial, suggestions, allowText = true, onApply }: {
    title: string;
    label: string;
    help: string;
    initial: string;
    suggestions?: { value: string; label: string }[];
    allowText?: boolean;
    onApply: (value: string) => void;
}) {
    const [value, setValue] = useState(initial);
    return (
        <div>
            <PopoverHeading>{title}</PopoverHeading>
            {suggestions ? (
                <div className="mb-3 space-y-0.5">
                    {suggestions.map((option) => (
                        <button key={option.value} type="button" aria-pressed={initial === option.value}
                            className={optionClass(initial === option.value)} onClick={() => onApply(option.value)}>
                            {option.label}
                        </button>
                    ))}
                </div>
            ) : null}
            {allowText ? (
                <form onSubmit={(event) => { event.preventDefault(); onApply(value.trim()); }} className="space-y-2">
                    <label className="block text-xs text-text-2">{label}
                        <input data-autofocus={suggestions ? undefined : true} value={value} maxLength={256}
                            onChange={(event) => setValue(event.target.value)} className={clsx(FIELD, 'mt-1')} />
                    </label>
                    <p className="text-xs text-text-3">{help}</p>
                    <GlassButton type="submit" size="sm" variant="primary" disabled={!value.trim()}>Apply</GlassButton>
                </form>
            ) : <p className="text-xs text-text-3">{help}</p>}
        </div>
    );
}

function AddFilterMenu({ available, onAdd, buttonRef }: {
    available: typeof EXTRA_FILTERS;
    onAdd: (key: ExtraFilter) => void;
    buttonRef: MutableRefObject<HTMLButtonElement | null>;
}) {
    const popover = usePopover();
    if (!available.length) return null;
    return (
        <div ref={popover.anchorRef} className="inline-flex">
            <button
                ref={(node) => { popover.triggerRef.current = node; buttonRef.current = node; }}
                type="button" aria-haspopup="dialog" aria-expanded={popover.open}
                onClick={popover.toggle}
                className="inline-flex h-8 items-center gap-1 rounded-full border border-dashed border-edge-strong px-3 text-xs text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-accent">
                <Plus size={13} aria-hidden="true" />Add filter
            </button>
            {popover.open ? (
                <AnchoredPopover anchorRef={popover.anchorRef} label="Add a filter" width={220}
                    onClose={(restoreFocus) => popover.close(restoreFocus)}>
                    <div className="space-y-0.5">
                        {available.map((item) => (
                            <button key={item.key} type="button" className={optionClass(false)}
                                onClick={() => { popover.close(false); onAdd(item.key); }}>
                                {item.label}
                            </button>
                        ))}
                    </div>
                </AnchoredPopover>
            ) : null}
        </div>
    );
}

/** Lets an administrator filter by the ID of someone no longer in SimpleChat. */
function rawPersonOption(term: string, people: ActivityPersonOption[]): EntityResult[] {
    if (!looksLikeId(term) || people.some((person) => person.id === term)) return [];
    return [{
        value: { id: term, display_name: '', email: '' },
        option: { key: `raw:${term}`, primary: `Filter by user ID “${term}”`, secondary: 'For someone no longer in SimpleChat', raw: true },
    }];
}

/** Lets an administrator filter by the ID of a workspace no longer in SimpleChat. */
function rawWorkspaceOptions(term: string, workspaces: ActivityWorkspaceOption[], kind: WorkspaceType): EntityResult[] {
    if (!looksLikeId(term) || workspaces.some((workspace) => workspace.id === term)) return [];
    const types: ('group' | 'public')[] = kind === 'group' || kind === 'public' ? [kind] : ['group', 'public'];
    return types.map((type) => ({
        value: { type, id: term, name: '' },
        option: {
            key: `raw:${type}:${term}`, primary: `Filter by ${type === 'group' ? 'group' : 'public workspace'} ID “${term}”`,
            secondary: 'For a workspace no longer in SimpleChat', raw: true,
        },
    }));
}

export function ActivityFilterBar({ filters, labels, typeOptions, counts, searchPeople, onChange, onReset, onRememberName }: {
    filters: ActivityFilters;
    labels?: ActivityFilterLabels;
    typeOptions: ActivityTypeOption[];
    counts: Map<string, number>;
    searchPeople?: { matched: number; truncated: boolean };
    onChange: (next: ActivityFilters, options?: FilterChangeOptions) => void;
    onReset: () => void;
    /** Keeps a picked name on the pill while the filtered page loads. */
    onRememberName?: (kind: 'person' | 'workspace', key: string, name: string, email?: string) => void;
}) {
    const [draft, setDraft] = useState(filters.search);
    const [adding, setAdding] = useState<ExtraFilter | null>(null);
    // The search this field last sent to the URL, so its echo is not mistaken for a change.
    const pushed = useRef(filters.search);
    // An added filter whose value was just applied; its pill stays until the URL has the value.
    const applying = useRef<ExtraFilter | null>(null);
    const addFilterButton = useRef<HTMLButtonElement | null>(null);
    const searchInput = useRef<HTMLInputElement>(null);
    const latest = useRef({ filters, onChange });
    latest.current = { filters, onChange };

    // Only a change made elsewhere (Reset, a saved view, Back) replaces the text being typed.
    // The URL echoing this field's own search must not, or it would drop a trailing space or
    // a keystroke typed while the URL was updating.
    useEffect(() => {
        if (filters.search === pushed.current) return;
        pushed.current = filters.search;
        setDraft(filters.search);
    }, [filters.search]);
    useEffect(() => {
        const next = draft.trim();
        if (next === filters.search) return undefined;
        const timer = window.setTimeout(() => {
            pushed.current = next;
            latest.current.onChange({ ...latest.current.filters, search: next }, { replace: true });
        }, SEARCH_DEBOUNCE_MS);
        return () => window.clearTimeout(timer);
    }, [draft, filters.search]);
    useEffect(() => {
        if (adding && filters[adding]) setAdding(null);
    }, [adding, filters]);

    const focusAfterExtraPill = () => (addFilterButton.current ?? searchInput.current)?.focus();
    const typeLabels = new Map(typeOptions.map((option) => [option.activity_type, option.label]));
    const types = filters.activity_type;
    const activityValue = !types.length ? 'All'
        : types.length === 1 ? (typeLabels.get(types[0]) ?? humanize(types[0]))
            : `${types.length} types`;
    const personValue = !filters.user_id ? 'Anyone'
        : labels?.person?.name || labels?.person?.email || shortId(filters.user_id);
    const workspaceKind = filters.workspace_type;
    const workspaceLabel = filters.workspace_id && workspaceKind === 'group' ? 'Group'
        : filters.workspace_id && workspaceKind === 'public' ? 'Public workspace' : 'Workspace';
    const workspaceValue = !workspaceKind ? 'Any'
        : workspaceKind === 'personal' ? 'Personal'
            : filters.workspace_id ? (labels?.workspace?.name || shortId(filters.workspace_id))
                : workspaceKind === 'group' ? 'All groups' : 'All public workspaces';
    const setWorkspace = (type: WorkspaceType, id = '') => onChange({ ...filters, workspace_type: type, workspace_id: id });
    const extraValue = (key: ExtraFilter) => key === 'token_type'
        ? (TOKEN_TYPES.find((item) => item.value === filters.token_type)?.label ?? filters.token_type)
        : key === 'status' && filters.status === 'failed' ? 'Failed or error' : filters[key];

    return (
        <div className="space-y-2">
            <div role="search" aria-label="Filter activity" className="flex flex-wrap items-center gap-2">
                <div className="relative w-full sm:w-auto sm:max-w-80 sm:min-w-48 sm:flex-1">
                    <Search size={14} aria-hidden="true" className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-3" />
                    <input
                        ref={searchInput}
                        type="search"
                        aria-label="Search activity"
                        aria-describedby="activity-search-help"
                        value={draft}
                        maxLength={200}
                        placeholder="Search people, files, titles, IDs…"
                        onChange={(event) => setDraft(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                                event.preventDefault();
                                pushed.current = draft.trim();
                                onChange({ ...filters, search: pushed.current });
                            }
                        }}
                        className="h-8 w-full rounded-full border border-edge bg-surface-1 pr-3 pl-8 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                    />
                    <span id="activity-search-help" className="sr-only">Matches names and emails of people, file names, conversation titles, models and IDs. Results update as you type.</span>
                </div>
                <FilterPill pillId="date" label="Date" value={dateRangeLabel(filters)} active={filters.range !== DEFAULT_RANGE}
                    onClear={() => onChange({ ...filters, range: DEFAULT_RANGE, ...presetDates(DEFAULT_RANGE) })}
                    clearLabel="Reset date range to the last 30 days" popoverLabel="Choose a date range" width={300}>
                    {(close) => <DatePopover filters={filters} onChange={onChange} close={close} />}
                </FilterPill>
                <FilterPill pillId="activity" label="Activity" value={activityValue} active={types.length > 0}
                    onClear={() => onChange({ ...filters, activity_type: [] })} popoverLabel="Choose activity types" width={360}>
                    {(close) => <ActivityPopover filters={filters} typeOptions={typeOptions} counts={counts} onChange={onChange} close={close} />}
                </FilterPill>
                <FilterPill pillId="person" label="Person" value={personValue} active={Boolean(filters.user_id)}
                    onClear={() => onChange({ ...filters, user_id: '' })} popoverLabel="Choose a person" width={340}>
                    {(close) => (
                        <EntityCombobox<{ people: ActivityPersonOption[] }>
                            label="Find a person"
                            placeholder="Name, email or user ID"
                            endpoint="/api/v2/control-center/activity-logs/people"
                            emptyText="No SimpleChat user matches."
                            toOptions={(response, term) => [
                                ...response.people.map((person) => ({
                                    value: person,
                                    option: { key: person.id, primary: person.display_name || person.email || person.id,
                                        secondary: person.display_name ? person.email : person.id },
                                })),
                                ...rawPersonOption(term, response.people),
                            ]}
                            onSelect={(value) => {
                                const person = value as ActivityPersonOption;
                                if (person.display_name || person.email) {
                                    onRememberName?.('person', person.id, person.display_name, person.email);
                                }
                                onChange({ ...filters, user_id: person.id });
                                close();
                            }}
                            footer={<p className="text-xs text-text-3">Shows what this person did, including approvals and admin changes they made.</p>}
                        />
                    )}
                </FilterPill>
                <FilterPill pillId="workspace" label={workspaceLabel} value={workspaceValue} active={Boolean(workspaceKind)}
                    onClear={() => setWorkspace('')} popoverLabel="Choose a workspace" width={360}>
                    {(close) => (
                        <div className="space-y-3">
                            <div>
                                <PopoverHeading>Workspace</PopoverHeading>
                                <div role="group" aria-label="Workspace type" className="grid grid-cols-4 rounded-lg border border-edge p-0.5">
                                    {([['', 'Any'], ['personal', 'Personal'], ['group', 'Groups'], ['public', 'Public']] as const).map(([type, text]) => (
                                        <button key={text} type="button" aria-pressed={workspaceKind === type && !filters.workspace_id}
                                            onClick={() => { setWorkspace(type); if (type === '' || type === 'personal') close(); }}
                                            className={clsx('rounded-md px-2 py-1.5 text-xs transition-colors focus-visible:outline-2 focus-visible:outline-accent',
                                                workspaceKind === type ? 'bg-accent-soft font-medium text-accent' : 'text-text-2 hover:bg-surface-2')}>
                                            {text}
                                        </button>
                                    ))}
                                </div>
                            </div>
                            <EntityCombobox<{ workspaces: ActivityWorkspaceOption[] }>
                                label={workspaceKind === 'group' ? 'Find a group' : workspaceKind === 'public' ? 'Find a public workspace' : 'Find a group or public workspace'}
                                placeholder="Name or ID"
                                endpoint="/api/v2/control-center/activity-logs/workspaces"
                                emptyText="No group or public workspace matches."
                                toOptions={(response, term) => [
                                    ...response.workspaces
                                        .filter((workspace) => workspaceKind !== 'group' && workspaceKind !== 'public' || workspace.type === workspaceKind)
                                        .map((workspace) => ({
                                            value: workspace,
                                            option: { key: `${workspace.type}:${workspace.id}`, primary: workspace.name || workspace.id,
                                                secondary: workspace.name ? workspace.id : undefined,
                                                badge: workspace.type === 'group' ? 'Group' : 'Public' },
                                        })),
                                    ...rawWorkspaceOptions(term, response.workspaces, workspaceKind),
                                ]}
                                onSelect={(value) => {
                                    const workspace = value as ActivityWorkspaceOption;
                                    if (workspace.name) onRememberName?.('workspace', `${workspace.type}:${workspace.id}`, workspace.name);
                                    setWorkspace(workspace.type, workspace.id);
                                    close();
                                }}
                            />
                        </div>
                    )}
                </FilterPill>
                {EXTRA_FILTERS.filter((item) => filters[item.key] || adding === item.key).map((item) => (
                    <FilterPill key={item.key} label={item.label} value={filters[item.key] ? extraValue(item.key) : 'Choose'}
                        active={Boolean(filters[item.key])} defaultOpen={adding === item.key}
                        onOpenChange={(open, restoreFocus) => {
                            if (open) return;
                            if (applying.current === item.key) {
                                applying.current = null;
                                return;
                            }
                            // Closing an added filter without choosing a value removes its pill.
                            if (adding === item.key && !filters[item.key]) {
                                setAdding(null);
                                if (restoreFocus) requestAnimationFrame(focusAfterExtraPill);
                            }
                        }}
                        onClear={() => onChange({ ...filters, [item.key]: '' })} focusAfterClear={focusAfterExtraPill}
                        popoverLabel={`Filter by ${item.label.toLowerCase()}`}>
                        {(close) => (
                            <TextFilterPopover
                                title={item.label}
                                label={item.key === 'model' ? 'Model or deployment name' : item.key === 'token_type' ? 'Token type' : 'Recorded status'}
                                help={item.key === 'model' ? 'Matches token usage records for this exact model.'
                                    : item.key === 'token_type' ? 'Matches token usage records of this type.'
                                        : 'Failed or error matches any status that mentions either word. Other values match exactly.'}
                                initial={filters[item.key]}
                                suggestions={item.key === 'token_type' ? [...TOKEN_TYPES]
                                    : item.key === 'status' ? [{ value: 'failed', label: 'Failed or error' }] : undefined}
                                allowText={item.key !== 'token_type'}
                                onApply={(value) => {
                                    applying.current = item.key;
                                    onChange({ ...filters, [item.key]: value });
                                    close();
                                }}
                            />
                        )}
                    </FilterPill>
                ))}
                <AddFilterMenu buttonRef={addFilterButton}
                    available={EXTRA_FILTERS.filter((item) => !filters[item.key] && adding !== item.key)}
                    onAdd={setAdding} />
                {!isDefaultFilters(filters) ? (
                    <button type="button" onClick={() => { searchInput.current?.focus(); onReset(); }}
                        className="inline-flex h-8 items-center gap-1 rounded-full px-2.5 text-xs font-medium text-text-2 hover:bg-surface-2 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-accent">
                        <X size={13} aria-hidden="true" />Reset filters
                    </button>
                ) : null}
            </div>
            {filters.search && searchPeople?.truncated ? (
                <p className="text-xs text-text-3">
                    “{filters.search}” matches more than 25 people, so the search includes only the first 25. Use the Person filter to pick one.
                </p>
            ) : null}
        </div>
    );
}
