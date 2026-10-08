// ReviewCenterPage.tsx
// The admin Review center: feedback and safety review in one place, laid out like the
// Approvals page -- a rail of each section's pages, and the chosen page beside it.
//
// /admin/review opens the first section the signed-in user may review. Each section has a
// dashboard whose figures open its workbench already filtered, a workbench for reviewing
// records one at a time or many at once, and full-page editors at the workbench's address
// followed by a record id. Access mirrors the server's decorators (lib/reviewAccess.ts); the
// server still answers every request on its own terms.

import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { Navigate, useLocation, useNavigate, useParams } from 'react-router-dom';
import { RefreshCw, ShieldOff } from 'lucide-react';
import { CategoryRailPage, type RailSection } from '../../components/layout/CategoryRail';
import { PageHeader } from '../../components/layout/PageHeader';
import { EmptyState, GlassButton } from '../../components/ui/primitives';
import { reviewAccessInput, reviewSections, type ReviewSectionId } from '../../lib/reviewAccess';
import { safeReviewViewHref } from '../../lib/reviewCenter';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import {
    REVIEW_SECTION_LABELS,
    reviewEntriesFor,
    reviewEntryPath,
    type ReviewEntry,
} from './reviewCenterSections';

const SECTION_IDS: readonly ReviewSectionId[] = ['feedback', 'safety'];

function NotAvailable({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
    return (
        <div className="flex h-full items-center justify-center p-6" data-testid="v2-review-not-available">
            <EmptyState icon={<ShieldOff size={28} />} title={title} description={description} action={action} />
        </div>
    );
}

export function ReviewCenterPage() {
    const navigate = useNavigate();
    const location = useLocation();
    const { section: sectionParam, view: viewParam, recordId } = useParams();
    const bootstrap = useBootstrapStore((state) => state.data);
    const railCollapsed = useUserSettingsStore((state) => state.settings.v2ReviewRailCollapsed === true);
    const updateUserSettings = useUserSettingsStore((state) => state.update);
    const [reloadKey, setReloadKey] = useState(0);
    const [count, setCount] = useState<{ entry: string; value: number } | null>(null);

    const access = useMemo(() => reviewAccessInput(bootstrap), [bootstrap]);
    const sections = useMemo(() => reviewSections(access), [access]);
    const entries = useMemo(() => reviewEntriesFor(sections, access), [sections, access]);
    const view = viewParam ?? '';
    const active: ReviewEntry | undefined = entries.find(
        (entry) => entry.section === sectionParam && entry.view === view,
    );

    const reportCount = useCallback(
        (value: number) => {
            if (active) setCount({ entry: active.id, value });
        },
        [active],
    );

    if (!sections.length) {
        return (
            <div className="flex h-full min-h-0 flex-col" data-testid="v2-review-center">
                <PageHeader title="Review center" description="Review user feedback and safety violations." />
                <NotAvailable
                    title="The Review center is not available to you"
                    description="Reviewing feedback or safety violations needs the reviewer role for that area, and the area turned on in Admin Settings."
                />
            </div>
        );
    }

    if (!sectionParam) {
        return <Navigate to={safeReviewViewHref(sections[0], 'dashboard', new URLSearchParams(location.search))} replace />;
    }

    const knownSection = SECTION_IDS.find((id) => id === sectionParam);
    const sectionAllowed = knownSection ? sections.includes(knownSection) : false;
    if (!knownSection) {
        return <Navigate to={safeReviewViewHref(sections[0], 'dashboard')} replace />;
    }
    if (sectionAllowed && !active) {
        // An unknown page of a section the user may open leads to that section's dashboard.
        return <Navigate to={safeReviewViewHref(knownSection, 'dashboard')} replace />;
    }

    const railSections: RailSection[] = sections.map((section) => ({
        id: section,
        label: REVIEW_SECTION_LABELS[section],
        items: entries.filter((entry) => entry.section === section).map((entry) => ({
            id: entry.id,
            label: entry.label,
            accessibleLabel: entry.accessibleLabel,
            description: entry.description,
            Icon: entry.Icon,
        })),
    }));

    const editing = Boolean(recordId && active?.renderRecord);
    const context = { reloadKey, onCountChange: reportCount };
    let content;
    if (!sectionAllowed || !active) {
        const label = REVIEW_SECTION_LABELS[knownSection];
        content = (
            <NotAvailable
                title={`${label} review is not available to you`}
                description={`Reviewing ${label.toLowerCase()} needs its reviewer role, and the area turned on in Admin Settings.`}
                action={(
                    <GlassButton type="button" size="sm" variant="subtle" onClick={() => navigate(safeReviewViewHref(sections[0], 'dashboard'))}>
                        Open {REVIEW_SECTION_LABELS[sections[0]].toLowerCase()} review
                    </GlassButton>
                )}
            />
        );
    } else if (recordId && active.renderRecord) {
        content = <div className="h-full min-h-0 px-4 pt-3 lg:px-6">{active.renderRecord(recordId, context)}</div>;
    } else {
        content = active.render(context);
    }

    const activeCount = active && count?.entry === active.id ? count.value : null;

    return (
        <CategoryRailPage
            testId="v2-review-center"
            title="Review center"
            description="Review user feedback and safety violations, alone or many at a time."
            actions={editing ? undefined : (
                <GlassButton size="sm" variant="ghost" onClick={() => setReloadKey((value) => value + 1)} data-testid="v2-review-refresh">
                    <RefreshCw size={14} aria-hidden="true" />
                    Refresh
                </GlassButton>
            )}
            railLabel="Review center pages"
            railTestId="v2-review-rail"
            itemTestIdPrefix="v2-review-rail-"
            collapseNoun="review pages"
            listId="review-center-pages"
            sections={railSections}
            activeId={active?.id ?? ''}
            activeCount={activeCount}
            countTestId="v2-review-active-count"
            collapsed={railCollapsed}
            onToggleCollapsed={() => updateUserSettings({ v2ReviewRailCollapsed: !railCollapsed })}
            onSelect={(id) => {
                const entry = entries.find((candidate) => candidate.id === id);
                if (entry) navigate(reviewEntryPath(entry));
            }}
            pickerId="review-center-page"
            pickerLabel="Review page"
            pickerTestId="v2-review-page-select"
            showHeading={!editing}
        >
            {content}
        </CategoryRailPage>
    );
}
