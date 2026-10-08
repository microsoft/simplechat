// ApprovalsPage.tsx
// Every approval request the signed-in user can act on, in one full-page workspace.
//
// Laid out like Admin settings: a collapsible rail of request kinds on the left, the
// list for the chosen kind, and the selected request's detail and actions on the right.
// The category and the selected item live in the URL so notifications, chat cards, and
// bookmarks can link straight to one request. The Dashboard category summarizes the
// requests the user can see, and each figure opens the list it counts.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
    Bot,
    Clock,
    Cloud,
    Inbox,
    LayoutDashboard,
    RefreshCw,
    Send,
    ShieldAlert,
    ShieldCheck,
    Users,
    type LucideIcon,
} from 'lucide-react';
import { AgentTemplatesPanel } from '../components/approvals/AgentTemplatesPanel';
import { ApprovalsDashboard } from '../components/approvals/ApprovalsDashboard';
import { GenericApprovalsPanel } from '../components/approvals/GenericApprovalsPanel';
import { PausedRequestsPanel } from '../components/approvals/PausedRequestsPanel';
import { PendingActionsPanel } from '../components/approvals/PendingActionsPanel';
import { CategoryRailPage } from '../components/layout/CategoryRail';
import { GlassButton } from '../components/ui/primitives';
import {
    CONTENT_SCREENING_TYPE,
    GROUP_REQUEST_TYPES,
    M365_REQUEST_TYPES,
    SAFETY_REMEDIATION_TYPES,
} from '../lib/approvalsApi';
import { canSeeSafetyRemediationApprovals } from '../lib/reviewAccess';
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

function buildCategories(contentScreening: boolean, isAdmin: boolean, safetyRemediation: boolean): ApprovalCategory[] {
    const categories: ApprovalCategory[] = [
        { id: 'dashboard', label: 'Dashboard', description: 'What is waiting on you, what you asked for, and what was decided recently.', Icon: LayoutDashboard },
        { id: 'all', label: 'All requests', description: 'Every approval request you can see.', Icon: Inbox, types: null },
        { id: 'group', label: 'Group requests', description: 'Changes to groups that need an owner or admin to agree.', Icon: Users, types: GROUP_REQUEST_TYPES },
        { id: 'm365', label: 'Microsoft 365', description: 'Requests to read, share, or act in Microsoft 365.', Icon: Cloud, types: M365_REQUEST_TYPES },
    ];
    if (safetyRemediation) {
        categories.push({
            id: 'safety-remediation',
            label: 'Safety remediation',
            description: 'Warn, suspend and block requests raised from safety violation reviews.',
            Icon: ShieldAlert,
            types: SAFETY_REMEDIATION_TYPES,
        });
    }
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
    const roles = useBootstrapStore((state) => state.data?.user?.roles);
    const safetyRemediation = canSeeSafetyRemediationApprovals(roles ?? []);
    const railCollapsed = useUserSettingsStore((state) => state.settings.v2ApprovalsRailCollapsed === true);
    const updateUserSettings = useUserSettingsStore((state) => state.update);
    const [reloadKey, setReloadKey] = useState(0);
    const [count, setCount] = useState<{ category: string; value: number } | null>(null);

    const categories = useMemo(
        () => buildCategories(contentScreening, isAdmin, safetyRemediation),
        [contentScreening, isAdmin, safetyRemediation],
    );
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
        if (id !== active?.id) navigate(`/approvals/${encodeURIComponent(id)}`);
    };

    if (!active) return null;

    const selectedId = itemId || undefined;
    const selectedGroupId = searchParams.get('group_id') ?? undefined;
    const activeCount = count?.category === active.id ? count.value : null;

    let panel;
    if (active.id === 'dashboard') {
        panel = <ApprovalsDashboard reloadKey={reloadKey} />;
    } else if (active.id === 'outgoing') {
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
        <CategoryRailPage
            testId="v2-approvals-page"
            title="Approval requests"
            description="Review requests waiting on you, see what you have already decided, and act on the selected request."
            actions={
                <GlassButton size="sm" variant="ghost" onClick={() => setReloadKey((value) => value + 1)} data-testid="v2-approvals-refresh">
                    <RefreshCw size={14} aria-hidden="true" />
                    Refresh
                </GlassButton>
            }
            railLabel="Approval categories"
            railTestId="v2-approvals-rail"
            itemTestIdPrefix="v2-approvals-category-"
            collapseNoun="approval categories"
            listId="approvals-category-list"
            sections={[{ id: 'categories', items: categories }]}
            activeId={active.id}
            activeCount={activeCount}
            countTestId="v2-approvals-active-count"
            collapsed={railCollapsed}
            onToggleCollapsed={() => updateUserSettings({ v2ApprovalsRailCollapsed: !railCollapsed })}
            onSelect={selectCategory}
            pickerId="approvals-category"
            pickerLabel="Request type"
            pickerTestId="v2-approvals-category-select"
        >
            {panel}
        </CategoryRailPage>
    );
}
