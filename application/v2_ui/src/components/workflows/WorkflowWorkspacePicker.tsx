// WorkflowWorkspacePicker.tsx
// Search authorized workspace metadata without loading document catalogs.

import { useRef, useState } from 'react';
import { documentScopeKey, type DocumentScope } from '../../lib/workflowDocumentSelection';

const inputClass = 'w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none';
const buttonClass = 'rounded-lg border border-edge px-3 py-2 text-sm text-text-1 hover:bg-surface-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50';
type Workspace = DocumentScope & { name: string };

export function WorkflowWorkspacePicker({ workspaces, selected, onChange }: {
    workspaces: Workspace[]; selected: DocumentScope[]; onChange: (value: DocumentScope[]) => void;
}) {
    const [query, setQuery] = useState('');
    const [kind, setKind] = useState('all');
    const searchInput = useRef<HTMLInputElement>(null);
    const matching = workspaces.filter((workspace) => (kind === 'all' || workspace.scope_type === kind) &&
        workspace.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
    const label = (workspace: Workspace) => `${workspace.name} · ${workspace.scope_type === 'personal' ? 'Personal' :
        workspace.scope_type === 'group' ? 'Group' : 'Public'}${workspaces.some((other) =>
        documentScopeKey(other) !== documentScopeKey(workspace) && other.name === workspace.name &&
        other.scope_type === workspace.scope_type) ? ` · ${workspace.scope_id}` : ''}`;
    return <fieldset className="min-w-0 space-y-3">
        <legend className="mb-2 text-sm font-medium text-text-1">Source workspaces</legend>
        <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm text-text-2">Source kind
                <select aria-label="Source kind" className={`${inputClass} mt-1`} value={kind} onChange={(event) => setKind(event.target.value)}>
                    <option value="all">All sources</option><option value="personal">My workspace</option>
                    <option value="group">Groups</option><option value="public">Public workspaces</option>
                </select>
            </label>
            <label className="text-sm text-text-2">Find workspaces
                <input ref={searchInput} className={`${inputClass} mt-1`} type="search" value={query}
                    placeholder="Search workspace names" onChange={(event) => setQuery(event.target.value)} />
            </label>
        </div>
        <p role="status" className="text-xs text-text-3">
            {matching.length} matching workspaces. Showing up to 25; search to find any authorized workspace.
        </p>
        <ul aria-label="Available source workspaces" className="max-h-60 space-y-2 overflow-y-auto">
            {matching.slice(0, 25).map((workspace) => {
                const added = selected.some((item) => documentScopeKey(item) === documentScopeKey(workspace));
                return <li key={documentScopeKey(workspace)} className="flex min-w-0 items-center gap-3">
                    <span className="min-w-0 flex-1 break-words text-sm text-text-1">{label(workspace)}</span>
                    <button type="button" className={buttonClass} disabled={added || selected.length >= 20}
                        aria-label={`Add ${label(workspace)}`} onClick={() => onChange([...selected, {
                            scope_type: workspace.scope_type, ...(workspace.scope_id ? { scope_id: workspace.scope_id } : {}),
                        }])}>{added ? 'Added' : 'Add'}</button>
                </li>;
            })}
        </ul>
        {!matching.length ? <p className="text-sm text-text-2">No matching authorized workspace. Try another name or source kind.</p> : null}
        <p className="text-sm font-medium text-text-1">Selected workspaces ({selected.length} / 20)</p>
        <p className="text-xs text-text-3">The 20-workspace limit applies to your selection, not available search results.</p>
        <ul aria-label="Selected source workspaces" className="space-y-2">
            {selected.map((item) => {
                const workspace = workspaces.find((candidate) => documentScopeKey(candidate) === documentScopeKey(item));
                return <li key={documentScopeKey(item)} className="flex min-w-0 items-center gap-3">
                    <span className="min-w-0 flex-1 break-words text-sm text-text-1">
                        {workspace ? label(workspace) : 'Unavailable workspace'}
                        {!workspace ? <span role="alert" className="block text-danger">Remove this source or restore access before running.</span> : null}
                    </span>
                    <button type="button" className={buttonClass} aria-label={workspace ? `Remove ${label(workspace)}` : 'Remove unavailable workspace'}
                        onClick={() => {
                            onChange(selected.filter((candidate) => documentScopeKey(candidate) !== documentScopeKey(item)));
                            searchInput.current?.focus();
                        }}>Remove</button>
                </li>;
            })}
        </ul>
        {!selected.length ? <p className="text-sm text-danger">Add at least one workspace.</p> : null}
    </fieldset>;
}
