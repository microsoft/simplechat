// ApprovalsPage.tsx
// Every approval request the signed-in user can act on, in one full-page workspace.
//
// Laid out like Admin settings: a collapsible rail of request kinds on the left, the
// list for the chosen kind, and the selected request's detail and actions on the right.
// The category and the selected item live in the URL so notifications, chat cards, and
// bookmarks can link straight to one request.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import clsx from 'clsx';
import {
    Bot,
    Clock,
    Cloud,
    Inbox,
    PanelLeftClose,
    PanelLeftOpen,
    RefreshCw,
    Send,
    ShieldCheck,
    Users,
    type LucideIcon,
} from 'lucide-react';
import { AgentTemplatesPanel } from '../components/approvals/AgentTemplatesPanel';
import { GenericApprovalsPanel } from '../components/approvals/GenericApprovalsPanel';
import { PausedRequestsPanel } from '../components/approvals/PausedRequestsPanel';
import { PendingActionsPanel } from '../components/approvals/PendingActionsPanel';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassButton } from '../components/ui/primitives';
import { CONTENT_SCREENING_TYPE, GROUP_REQUEST_TYPES, M365_REQUEST_TYPES } from '../lib/approvalsApi';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { useUserSettingsStore } from '../stores/userSettingsStore';

interface ApprovalCategory {
    id: string;
    label: string;
    description: string;
    Icon: LucideIcon;
    types?: readonly string[] | null;
}

const DEFAULT_CATEGORY = 'all';

function buildCategories(contentScreening: boolean, isAdmin: boolean): ApprovalCategory[] {
    const categories: ApprovalCategory[] = [
        { id: 'all', label: 'All requests', description: 'Every approval request you can see.', Icon: Inbox, types: null },
        { id: 'group', label: 'Group requests', description: 'Changes to groups that need an owner or admin to agree.', Icon: Users, types: GROUP_REQUEST_TYPES },
        { id: 'm365', label: 'Microsoft 365', description: 'Requests to read, share, or act in Microsoft 365.', Icon: Cloud, types: M365_REQUEST_TYPES },
    ];
    if (contentScreening) {
        categories.push({
            id: 'content-screening',
            label: 'Content screening',
            description: 'Documents held by content screening for a reviewer.',
            Icon: ShieldCheck,
            types: [CONTENT_SCREENING_TYPE],
        });
    }
    categories.push(
        { id: 'outgoing', label: 'Outgoing actions', description: 'Emails and other Microsoft 365 actions waiting for you to send or cancel.', Icon: Send },
        { id: 'paused', label: 'Waiting requests', description: 'Saved chat requests paused for an approval or a sign-in.', Icon: Clock },
    );
    if (isAdmin) {
        categories.push({ id: 'agent-templates', label: 'Agent templates', description: 'Templates submitted for the shared gallery.', Icon: Bot });
    }
    return categories;
}

export function ApprovalsPage() {
    const navigate = useNavigate();
    const location = useLocation();
    const { category: categoryParam, itemId } = useParams();
    const [searchParams] = useSearchParams();
    const contentScreening = useBootstrapStore((state) => state.data?.features?.enable_content_screening === true);
    const isAdmin = useBootstrapStore((state) => Boolean(state.data?.user?.is_admin));
    const railCollapsed = useUserSettingsStore((state) => state.settings.v2ApprovalsRailCollapsed === true);
    const updateUserSettings = useUserSettingsStore((state) => state.update);
    const [reloadKey, setReloadKey] = useState(0);
    const [count, setCount] = useState<{ category: string; value: number } | null>(null);

    const categories = useMemo(() => buildCategories(contentScreening, isAdmin), [contentScreening, isAdmin]);
    const active = categories.find((category) => category.id === categoryParam);

    // Classic-style links (`/approvals?m365_approval=...`, `?approval_id=...`, and the
    // agent-template anchor) still arrive from notifications and older chat cards.
    useEffect(() => {
        if (categoryParam) {
            if (!active) navigate(`/approvals/${DEFAULT_CATEGORY}`, { replace: true });
            return;
        }
        const m365Approval = searchParams.get('m365_approval');
        const approvalId = searchParams.get('approval_id');
        if (m365Approval) {
            navigate(`/approvals/m365/${encodeURIComponent(m365Approval)}`, { replace: true });
        } else if (approvalId) {
            const groupId = searchParams.get('group_id');
            const query = groupId ? `?${new URLSearchParams({ group_id: groupId }).toString()}` : '';
            navigate(`/approvals/${DEFAULT_CATEGORY}/${encodeURIComponent(approvalId)}${query}`, { replace: true });
        } else if (location.hash === '#agent-template-approvals' && isAdmin) {
            navigate('/approvals/agent-templates', { replace: true });
        } else {
            navigate(`/approvals/${DEFAULT_CATEGORY}`, { replace: true });
        }
    }, [categoryParam, active, searchParams, location.hash, isAdmin, navigate]);

    const reportCount = useCallback(
        (value: number) => {
            if (active) setCount({ category: active.id, value });
        },
        [active],
    );

    const selectCategory = (id: string) => {
        if (id !== active?.id) navigate(`/approvals/${id}`);
    };

    if (!active) return null;

    const selectedId = itemId || undefined;
    const selectedGroupId = searchParams.get('group_id') ?? undefined;
    const activeCount = count?.category === active.id ? count.value : null;

    let panel;
    if (active.id === 'outgoing') {
        panel = <PendingActionsPanel selectedId={selectedId} reloadKey={reloadKey} onCountChange={reportCount} />;
    } else if (active.id === 'paused') {
        panel = <PausedRequestsPanel selectedId={selectedId} reloadKey={reloadKey} onCountChange={reportCount} />;
    } else if (active.id === 'agent-templates') {
        panel = <AgentTemplatesPanel selectedId={selectedId} reloadKey={reloadKey} onCountChange={reportCount} />;
    } else {
        panel = (
            <GenericApprovalsPanel
                key={active.id}
                category={active.id}
                types={active.types ?? null}
                selectedId={selectedId}
                selectedGroupId={selectedGroupId}
                emptyTitle={`No ${active.label.toLowerCase()} in this view.`}
                reloadKey={reloadKey}
                onCountChange={reportCount}
            />
        );
    }

    return (
        <div className="flex h-full min-h-0 flex-col" data-testid="v2-approvals-page">
            <PageHeader
                title="Approval requests"
                description="Review requests waiting on you, see what you have already decided, and act on the selected request."
                actions={
                    <GlassButton size="sm" variant="ghost" onClick={() => setReloadKey((value) => value + 1)} data-testid="v2-approvals-refresh">
                        <RefreshCw size={14} aria-hidden="true" />
                        Refresh
                    </GlassButton>
                }
            />
            <div className="flex min-h-0 flex-1">
                <aside
                    aria-label="Approval categories"
                    data-testid="v2-approvals-rail"
                    className={clsx(
                        'hidden shrink-0 overflow-y-auto border-r border-edge transition-[width] motion-reduce:transition-none lg:block',
                        railCollapsed ? 'w-16 px-2 py-3' : 'w-56 p-3',
                    )}
                >
                    <button
                        type="button"
                        onClick={() => updateUserSettings({ v2ApprovalsRailCollapsed: !railCollapsed })}
                        aria-label={railCollapsed ? 'Expand approval categories' : 'Collapse approval categories'}
                        aria-expanded={!railCollapsed}
                        aria-controls="approvals-category-list"
                        title={railCollapsed ? 'Expand approval categories' : 'Collapse approval categories'}
                        className={clsx(
                            'mb-2 flex w-full items-center gap-2 rounded-lg py-1.5 text-xs text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1',
                            railCollapsed ? 'justify-center px-2' : 'px-3',
                        )}
                    >
                        {railCollapsed ? (
                            <PanelLeftOpen size={15} aria-hidden="true" />
                        ) : (
                            <>
                                <PanelLeftClose size={15} aria-hidden="true" />
                                <span>Collapse</span>
                            </>
                        )}
                    </button>
                    <div id="approvals-category-list" className="space-y-0.5">
                        {categories.map((category) => {
                            const isActive = category.id === active.id;
                            return (
                                <button
                                    key={category.id}
                                    type="button"
                                    aria-pressed={isActive}
                                    title={railCollapsed ? category.label : category.description}
                                    onClick={() => selectCategory(category.id)}
                                    data-testid={`v2-approvals-category-${category.id}`}
                                    className={clsx(
                                        'relative flex w-full items-center gap-2.5 rounded-lg py-2.5 text-left text-sm transition-colors',
                                        railCollapsed ? 'justify-center px-2' : 'px-3',
                                        isActive
                                            ? 'bg-accent-soft font-semibold text-accent'
                                            : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
                                    )}
                                >
                                    <category.Icon
                                        size={16}
                                        aria-hidden="true"
                                        className={clsx('shrink-0', isActive ? 'text-accent' : 'text-text-3')}
                                    />
                                    <span className={railCollapsed ? 'sr-only' : 'min-w-0 flex-1'}>{category.label}</span>
                                    {isActive && activeCount && !railCollapsed ? (
                                        <span className="rounded-full bg-accent px-1.5 text-[11px] font-semibold text-white" data-testid="v2-approvals-active-count">
                                            {activeCount}
                                        </span>
                                    ) : null}
                                </button>
                            );
                        })}
                    </div>
                </aside>

                <div className="flex min-w-0 flex-1 flex-col">
                    <div className="shrink-0 border-b border-edge px-4 py-3 lg:px-6">
                        <div className="max-w-md lg:hidden">
                            <label htmlFor="approvals-category" className="mb-1 block text-xs text-text-2">Request type</label>
                            <select
                                id="approvals-category"
                                value={active.id}
                                onChange={(event) => selectCategory(event.target.value)}
                                className="w-full rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1"
                                data-testid="v2-approvals-category-select"
                            >
                                {categories.map((category) => (
                                    <option key={category.id} value={category.id}>{category.label}</option>
                                ))}
                            </select>
                        </div>
                        <div className="hidden lg:block">
                            <h2 className="text-sm font-semibold text-text-1">{active.label}</h2>
                            <p className="text-xs text-text-3">{active.description}</p>
                        </div>
                    </div>
                    <div className="min-h-0 flex-1">{panel}</div>
                </div>
            </div>
        </div>
    );
}
