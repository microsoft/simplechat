// GroupAgentDelegationPage.tsx

import { useEffect, useState } from 'react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassButton } from '../components/ui/primitives';
import { AgentDelegationManager } from '../components/agents/AgentDelegationManager';
import { DELEGATION_INPUT_CLASS } from '../components/agents/CallAgentEditor';
import { delegationError } from '../lib/agentDelegation';
import { GROUP_WORKSPACES, type WorkspaceSummary } from '../lib/workspaces';

export function GroupAgentDelegationPage() {
    const [groups, setGroups] = useState<WorkspaceSummary[]>([]);
    const [selectedGroup, setSelectedGroup] = useState<WorkspaceSummary | null>(null);
    const [search, setSearch] = useState('');
    const [page, setPage] = useState(1);
    const [totalCount, setTotalCount] = useState(0);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [reload, setReload] = useState(0);
    const [dirty, setDirty] = useState(false);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError('');
        void GROUP_WORKSPACES.list(page, 25, search).then((result) => {
            if (!cancelled) {
                setGroups(result.items);
                setTotalCount(result.totalCount);
            }
        }).catch((failure: unknown) => {
            if (!cancelled) {
                setError(delegationError(failure));
                setGroups([]);
            }
        }).finally(() => { if (!cancelled) { setLoading(false); } });
        return () => { cancelled = true; };
    }, [page, search, reload]);

    return (
        <div className="flex h-full min-h-0 flex-col">
            <PageHeader title="Group workspaces" description="Call agent actions and local caller bindings" />
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
                <div className="mx-auto max-w-3xl space-y-4">
                    <p className="text-sm text-text-3">Select a group to manage delegation without changing your active workspace. Membership, documents, models and full agent management remain in <a href="/group_workspaces" className="text-accent underline">classic group workspaces</a>.</p>
                    <label className="block text-sm text-text-2">
                        Search your groups
                        <input className={`${DELEGATION_INPUT_CLASS} mt-1`} type="search" value={search} disabled={dirty}
                            onChange={(event) => { setSearch(event.target.value); setPage(1); }} />
                    </label>
                    {loading ? <p role="status" className="text-sm text-text-3">Loading groups…</p> : null}
                    {error ? (
                        <div role="alert" className="text-sm text-danger">
                            <p>{error}</p>
                            <GlassButton size="sm" onClick={() => setReload((value) => value + 1)}>Retry group list</GlassButton>
                        </div>
                    ) : null}
                    <div>
                        <label htmlFor="delegation-group" className="block text-sm text-text-2">Group workspace</label>
                        <select id="delegation-group" className={`${DELEGATION_INPUT_CLASS} mt-1`} disabled={dirty || loading} value={selectedGroup?.id ?? ''}
                            onChange={(event) => setSelectedGroup(groups.find((group) => group.id === event.target.value) ?? null)}>
                            <option value="">Select a group workspace</option>
                            {selectedGroup && !groups.some((group) => group.id === selectedGroup.id) ? (
                                <option value={selectedGroup.id}>{selectedGroup.name}</option>
                            ) : null}
                            {groups.map((group) => <option key={group.id} value={group.id}>{group.name} · {group.userRole || 'Member'}</option>)}
                        </select>
                    </div>
                    {dirty ? <p role="status" className="text-sm text-warn">Save or cancel your Call agent changes before switching groups.</p> : null}
                    {!loading && !error && !groups.length ? <p role="status" className="text-sm text-text-3">No groups match your search or you have no group membership.</p> : null}
                    {page > 1 || totalCount > 25 ? (
                        <div className="flex items-center gap-2">
                            <GlassButton size="sm" disabled={loading || dirty || page === 1} onClick={() => setPage((value) => value - 1)}>Previous groups</GlassButton>
                            <span className="text-xs text-text-3">Page {page}</span>
                            <GlassButton size="sm" disabled={loading || dirty || page * 25 >= totalCount} onClick={() => setPage((value) => value + 1)}>Next groups</GlassButton>
                        </div>
                    ) : null}
                    {selectedGroup ? (
                        <AgentDelegationManager key={selectedGroup.id} scope={{ type: 'group', groupId: selectedGroup.id }}
                            allowManage={['Owner', 'Admin'].includes(selectedGroup.userRole ?? '')} onDirtyChange={setDirty} />
                    ) : null}
                </div>
            </div>
        </div>
    );
}
