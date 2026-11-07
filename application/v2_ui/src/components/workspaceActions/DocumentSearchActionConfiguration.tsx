// DocumentSearchActionConfiguration.tsx

import { useMemo } from 'react';
import { RotateCcw } from 'lucide-react';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { changeActionField } from '../../lib/workspaceActionLogic';
import type { ActionConnectorProps } from '../../lib/workspaceActionTypes';
import type { WorkspaceRef } from '../../lib/types';
import { EditorDependents, EditorFieldRow, EditorFieldset, EditorSwitch } from '../workspace/EditorLayout';

const INPUT_CLASS = 'form-control w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none';
const SELECT_CLASS = 'form-select w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none';
const RANGE_CLASS = 'form-range w-full accent-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50';
const VALID_SCOPES = ['personal', 'group', 'public'] as const;

type DocumentSearchScope = typeof VALID_SCOPES[number];
type WindowSizingMode = 'automatic' | 'fixed' | 'percent';

function numberValue(value: unknown, fallback: number, min: number, max: number): number {
    const numeric = typeof value === 'number' ? value : Number(value);
    if (!Number.isFinite(numeric)) return fallback;
    return Math.min(max, Math.max(min, Math.round(numeric)));
}

function stringArrayValue(value: unknown): string[] {
    if (!Array.isArray(value)) return [];
    const seen = new Set<string>();
    return value.reduce<string[]>((items, item) => {
        const normalized = String(item || '').trim();
        if (normalized && !seen.has(normalized)) {
            seen.add(normalized);
            items.push(normalized);
        }
        return items;
    }, []);
}

function scopeArrayValue(value: unknown): DocumentSearchScope[] {
    const values = stringArrayValue(value).filter((item): item is DocumentSearchScope =>
        VALID_SCOPES.includes(item as DocumentSearchScope));
    return values.length ? values : [...VALID_SCOPES];
}

function parsePageTargetLength(value: unknown, min: number, max: number): { pages: number; custom: '' } | { pages: null; custom: string } {
    if (typeof value === 'number' && Number.isFinite(value)) {
        return { pages: numberValue(value, min, min, max), custom: '' };
    }
    const text = String(value ?? '').trim();
    if (!text) return { pages: min, custom: '' };
    const match = text.match(/^(\d+)(?:\s*pages?)?$/i);
    if (!match) return { pages: null, custom: text };
    return { pages: numberValue(Number(match[1]), min, min, max), custom: '' };
}

function joinNames(ids: string[], options: WorkspaceRef[]): string {
    const names = ids.map((id) => options.find((option) => option.id === id)?.name || id);
    return names.length ? names.join(', ') : 'All I can access';
}

function updateArrayValue(current: string[], value: string, enabled: boolean): string[] {
    if (!enabled) return current.filter((item) => item !== value);
    return current.includes(value) ? current : [...current, value];
}

function WorkspaceMultiSelect({
    label,
    description,
    options,
    selectedIds,
    disabled,
    onChange,
}: {
    label: string;
    description: string;
    options: WorkspaceRef[];
    selectedIds: string[];
    disabled: boolean;
    onChange: (ids: string[]) => void;
}) {
    const selected = useMemo(() => new Set(selectedIds), [selectedIds]);
    return (
        <div className="space-y-2 rounded-xl border border-edge bg-surface-1 p-3">
            <div>
                <p className="text-sm font-semibold text-text-1">{label}</p>
                <p className="text-xs leading-relaxed text-text-3">{description}</p>
            </div>
            {options.length ? (
                <div className="max-h-56 space-y-1 overflow-y-auto pe-1">
                    {options.map((option) => (
                        <label key={option.id} className="form-check flex items-start gap-2 rounded-lg px-2 py-1.5 text-sm text-text-2 hover:bg-surface-2">
                            <input
                                type="checkbox"
                                className="form-check-input mt-1"
                                checked={selected.has(option.id)}
                                disabled={disabled}
                                onChange={(event) => onChange(updateArrayValue(selectedIds, option.id, event.target.checked))}
                            />
                            <span className="min-w-0">
                                <span className="block break-words text-text-1">{option.name || option.id}</span>
                                <span className="block break-all text-xs text-text-3">{option.id}</span>
                            </span>
                        </label>
                    ))}
                </div>
            ) : (
                <p className="text-xs text-text-3">No workspaces are available from the current bootstrap data.</p>
            )}
        </div>
    );
}

function TargetLengthControl({
    id,
    label,
    help,
    value,
    min,
    max,
    disabled,
    onChange,
}: {
    id: string;
    label: string;
    help: string;
    value: unknown;
    min: number;
    max: number;
    disabled: boolean;
    onChange: (value: string) => void;
}) {
    const parsed = parsePageTargetLength(value, min, max);
    return (
        <EditorFieldRow
            htmlFor={id}
            label={label}
            help={help}
            width="standard"
            trailing={parsed.pages === null ? undefined : <span className="text-xs font-semibold tabular-nums text-text-2">{parsed.pages} pages</span>}
        >
            {parsed.pages === null ? (
                <div className="space-y-2 rounded-lg border border-warn/40 bg-warn-soft p-3 text-sm text-text-2">
                    <p>Current custom value: <span className="font-semibold">{parsed.custom}</span></p>
                    <p className="text-xs text-text-3">Use reset to switch this action to page-based target lengths.</p>
                    <button
                        type="button"
                        className="btn btn-sm inline-flex items-center gap-1 rounded-lg border border-edge px-2 py-1 text-xs text-text-1 hover:bg-surface-2"
                        disabled={disabled}
                        onClick={() => onChange(`${min} pages`)}
                    >
                        <RotateCcw size={13} /> Reset to {min} pages
                    </button>
                </div>
            ) : (
                <div className="space-y-2">
                    <input
                        id={id}
                        type="range"
                        className={RANGE_CLASS}
                        min={min}
                        max={max}
                        step={1}
                        value={parsed.pages}
                        disabled={disabled}
                        onChange={(event) => onChange(`${Number(event.target.value)} pages`)}
                    />
                    <div className="flex items-center gap-3">
                        <input
                            type="number"
                            className={`${INPUT_CLASS} max-w-28`}
                            min={min}
                            max={max}
                            step={1}
                            value={parsed.pages}
                            disabled={disabled}
                            aria-label={`${label} pages`}
                            onChange={(event) => onChange(`${numberValue(event.target.valueAsNumber, min, min, max)} pages`)}
                        />
                        <span className="text-sm text-text-3">pages</span>
                    </div>
                    <div className="flex justify-between text-xs text-text-3">
                        <span>{min} page</span>
                        <span>{max} pages</span>
                    </div>
                </div>
            )}
        </EditorFieldRow>
    );
}

export function DocumentSearchActionConfiguration({ draft, onChange, readOnly }: ActionConnectorProps) {
    const groups = useBootstrapStore((state) => state.data?.scope?.groups ?? []);
    const publicWorkspaces = useBootstrapStore((state) => state.data?.scope?.public_workspaces ?? []);
    const fields = draft.additionalFields;
    const scopes = scopeArrayValue(fields.allowed_scopes);
    const groupIds = stringArrayValue(fields.allowed_group_ids);
    const publicWorkspaceIds = stringArrayValue(fields.allowed_public_workspace_ids);
    const topN = numberValue(fields.default_top_n, draft.type === 'search' ? 12 : 50, 1, 500);
    const sliderTopN = Math.min(100, Math.max(5, topN));
    const windowSize = numberValue(fields.default_window_size, 10, 1, 100);
    const windowPercent = numberValue(fields.default_window_percent, 25, 1, 100);
    const sizingMode: WindowSizingMode = fields.default_window_percent !== undefined
        ? 'percent'
        : fields.default_window_size !== undefined ? 'fixed' : 'automatic';
    const updateField = (path: string, value: unknown) => onChange((current) => changeActionField(current, path, value));
    const updateWindowSizing = (mode: WindowSizingMode) => onChange((current) => {
        let next = changeActionField(current, '/additionalFields/default_window_size', undefined);
        next = changeActionField(next, '/additionalFields/default_window_percent', undefined);
        if (mode === 'fixed') next = changeActionField(next, '/additionalFields/default_window_size', windowSize);
        if (mode === 'percent') next = changeActionField(next, '/additionalFields/default_window_percent', windowPercent);
        return next;
    });
    const toggleScope = (scope: DocumentSearchScope, enabled: boolean) => {
        updateField('/additionalFields/allowed_scopes', updateArrayValue(scopes, scope, enabled));
    };

    return (
        <div className="min-w-0 space-y-5" data-testid="document-search-configuration">
            <p className="text-[0.8125rem] leading-relaxed text-text-2">
                Search and summarize documents the current user is allowed to read. These settings can narrow
                the action, but they never grant access beyond the user’s workspace permissions.
            </p>
            <EditorFieldset
                legend="Allowed document scopes"
                help="Choose which document areas this action may search. Turning a scope off makes the backend skip it even when a tool call asks for all documents."
            >
                <EditorSwitch
                    label="My workspace"
                    description="Allow documents from the signed-in user’s personal workspace."
                    checked={scopes.includes('personal')}
                    disabled={readOnly}
                    onChange={(enabled) => toggleScope('personal', enabled)}
                />
                <EditorSwitch
                    label="Group workspaces"
                    description={`Allow group workspace documents. Current selection: ${joinNames(groupIds, groups)}.`}
                    checked={scopes.includes('group')}
                    disabled={readOnly}
                    onChange={(enabled) => toggleScope('group', enabled)}
                />
                {scopes.includes('group') ? (
                    <EditorDependents>
                        <EditorFieldRow
                            htmlFor="document-search-groups-mode"
                            label="Group workspace access"
                            help="Choose all authorized groups, or restrict the action to selected groups. An empty selected list is treated as all."
                            width="standard"
                        >
                            <select
                                id="document-search-groups-mode"
                                className={SELECT_CLASS}
                                value={groupIds.length ? 'restricted' : 'all'}
                                disabled={readOnly}
                                onChange={(event) => {
                                    if (event.target.value === 'all') updateField('/additionalFields/allowed_group_ids', []);
                                    else updateField('/additionalFields/allowed_group_ids', groups[0]?.id ? [groups[0].id] : []);
                                }}
                            >
                                <option value="all">All I can access</option>
                                <option value="restricted">Only these…</option>
                            </select>
                        </EditorFieldRow>
                        {groupIds.length ? (
                            <WorkspaceMultiSelect
                                label="Allowed groups"
                                description="The backend intersects this list with the user’s current group memberships."
                                options={groups}
                                selectedIds={groupIds}
                                disabled={readOnly}
                                onChange={(ids) => updateField('/additionalFields/allowed_group_ids', ids)}
                            />
                        ) : null}
                    </EditorDependents>
                ) : null}
                <EditorSwitch
                    label="Public workspaces"
                    description={`Allow public workspace documents. Current selection: ${joinNames(publicWorkspaceIds, publicWorkspaces)}.`}
                    checked={scopes.includes('public')}
                    disabled={readOnly}
                    onChange={(enabled) => toggleScope('public', enabled)}
                />
                {scopes.includes('public') ? (
                    <EditorDependents>
                        <EditorFieldRow
                            htmlFor="document-search-public-mode"
                            label="Public workspace access"
                            help="Choose all visible public workspaces, or restrict the action to selected workspaces. An empty selected list is treated as all."
                            width="standard"
                        >
                            <select
                                id="document-search-public-mode"
                                className={SELECT_CLASS}
                                value={publicWorkspaceIds.length ? 'restricted' : 'all'}
                                disabled={readOnly}
                                onChange={(event) => {
                                    if (event.target.value === 'all') updateField('/additionalFields/allowed_public_workspace_ids', []);
                                    else updateField('/additionalFields/allowed_public_workspace_ids', publicWorkspaces[0]?.id ? [publicWorkspaces[0].id] : []);
                                }}
                            >
                                <option value="all">All I can access</option>
                                <option value="restricted">Only these…</option>
                            </select>
                        </EditorFieldRow>
                        {publicWorkspaceIds.length ? (
                            <WorkspaceMultiSelect
                                label="Allowed public workspaces"
                                description="The backend intersects this list with the public workspaces visible to the user."
                                options={publicWorkspaces}
                                selectedIds={publicWorkspaceIds}
                                disabled={readOnly}
                                onChange={(ids) => updateField('/additionalFields/allowed_public_workspace_ids', ids)}
                            />
                        ) : null}
                    </EditorDependents>
                ) : null}
            </EditorFieldset>
            <EditorFieldRow
                htmlFor="document-search-top-n"
                label="Default search result limit"
                help="The slider covers the common 5–100 range. The number box can raise the limit up to the backend maximum of 500."
                width="standard"
                trailing={<span className="text-xs font-semibold tabular-nums text-text-2">{topN}</span>}
            >
                <input
                    id="document-search-top-n"
                    type="range"
                    className={RANGE_CLASS}
                    min={5}
                    max={100}
                    step={1}
                    value={sliderTopN}
                    disabled={readOnly}
                    onChange={(event) => updateField('/additionalFields/default_top_n', Number(event.target.value))}
                />
                <input
                    type="number"
                    className={`${INPUT_CLASS} max-w-32`}
                    min={1}
                    max={500}
                    step={1}
                    value={topN}
                    disabled={readOnly}
                    aria-label="Default search result limit"
                    onChange={(event) => updateField('/additionalFields/default_top_n', numberValue(event.target.valueAsNumber, topN, 1, 500))}
                />
            </EditorFieldRow>
            <EditorFieldRow
                htmlFor="document-search-window-unit"
                label="Preferred window unit"
                help="Window units control how document content is divided into summarization passes. Pages keep page ranges together when page numbers are available; chunks use indexed text chunks when pages are unavailable or preferred."
                width="standard"
            >
                <select
                    id="document-search-window-unit"
                    className={SELECT_CLASS}
                    value={String(fields.default_window_unit || 'pages')}
                    disabled={readOnly}
                    onChange={(event) => updateField('/additionalFields/default_window_unit', event.target.value)}
                >
                    <option value="pages">Pages</option>
                    <option value="chunks">Chunks</option>
                </select>
            </EditorFieldRow>
            <EditorFieldset
                legend="Window sizing"
                help="Automatic uses the service default. Fixed size sends exactly N pages or chunks per pass. Percent of document sizes each first-pass window as a percentage of the available source."
            >
                <EditorFieldRow htmlFor="document-search-window-sizing" label="Sizing mode" width="standard">
                    <select
                        id="document-search-window-sizing"
                        className={SELECT_CLASS}
                        value={sizingMode}
                        disabled={readOnly}
                        onChange={(event) => updateWindowSizing(event.target.value as WindowSizingMode)}
                    >
                        <option value="automatic">Automatic</option>
                        <option value="fixed">Fixed size (N units)</option>
                        <option value="percent">Percent of document (N%)</option>
                    </select>
                </EditorFieldRow>
                {sizingMode === 'fixed' ? (
                    <EditorFieldRow htmlFor="document-search-window-size" label="Fixed window size" help="Number of preferred units per summarization pass." width="standard">
                        <input
                            id="document-search-window-size"
                            type="number"
                            className={INPUT_CLASS}
                            min={1}
                            max={100}
                            step={1}
                            value={windowSize}
                            disabled={readOnly}
                            onChange={(event) => updateField('/additionalFields/default_window_size', numberValue(event.target.valueAsNumber, windowSize, 1, 100))}
                        />
                    </EditorFieldRow>
                ) : null}
                {sizingMode === 'percent' ? (
                    <EditorFieldRow htmlFor="document-search-window-percent" label="Window percent" help="Percentage of the document to include in each first-pass summary window." width="standard">
                        <input
                            id="document-search-window-percent"
                            type="number"
                            className={INPUT_CLASS}
                            min={1}
                            max={100}
                            step={1}
                            value={windowPercent}
                            disabled={readOnly}
                            onChange={(event) => updateField('/additionalFields/default_window_percent', numberValue(event.target.valueAsNumber, windowPercent, 1, 100))}
                        />
                    </EditorFieldRow>
                ) : null}
            </EditorFieldset>
            <EditorFieldRow
                htmlFor="document-search-focus"
                label="Default focus instructions"
                help="Optional guidance for summaries. Examples: “emphasize security risks,” “extract open decisions,” or “focus on deadlines and owners.”"
                width="wide"
            >
                <textarea
                    id="document-search-focus"
                    className={INPUT_CLASS}
                    rows={3}
                    value={String(fields.default_focus_instructions || '')}
                    disabled={readOnly}
                    onChange={(event) => updateField('/additionalFields/default_focus_instructions', event.target.value)}
                />
            </EditorFieldRow>
            <TargetLengthControl
                id="document-search-window-target"
                label="Window summary target length"
                help="Target length for each first-pass window summary. Stored as “N pages” for the backend summarization prompt."
                min={1}
                max={10}
                value={fields.default_window_target_length || '2 pages'}
                disabled={readOnly}
                onChange={(value) => updateField('/additionalFields/default_window_target_length', value)}
            />
            <TargetLengthControl
                id="document-search-final-target"
                label="Final summary target length"
                help="Target length for the final synthesized summary after all windows are reduced. Stored as “N pages”."
                min={1}
                max={20}
                value={fields.default_final_target_length || '2 pages'}
                disabled={readOnly}
                onChange={(value) => updateField('/additionalFields/default_final_target_length', value)}
            />
        </div>
    );
}
