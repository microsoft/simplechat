// SupportLatestFeaturesPage.tsx
// The Support menu's Latest Features page: what changed in recent releases, as administrators
// chose to share it with users.
//
// The V2 counterpart of the classic `/support/latest-features` page, behind the same gates and
// reading the same announcements, from `GET /api/v2/support/latest-features`. Administrators
// decide which announcements are shared in Admin Settings; the server sends only those, with
// each shortcut already filtered by the stored settings, so this page renders what it is given.
//
// A search sits above the releases because there are dozens of announcements and a reader
// usually arrives looking for one capability. The current release starts open and older ones
// start closed, as on the classic page.

import { useEffect, useMemo, useState } from 'react';
import { Lock, RotateCcw, Zap } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { CatalogueSkeleton } from '../components/admin/LatestFeatureParts';
import { SupportAnnouncementList } from '../components/support/SupportAnnouncements';
import { SectionError, SectionSearch } from '../components/workspace/primitives';
import { EmptyState, GlassButton } from '../components/ui/primitives';
import { api, ApiError } from '../lib/apiClient';
import {
    allFeatures,
    filterGroups,
    USER_LATEST_FEATURES_ENDPOINT,
    type LatestFeatureGroup,
    type UserLatestFeaturesPayload,
} from '../lib/latestFeatures';

type LoadState = 'loading' | 'ready' | 'unavailable' | 'error';

/**
 * Whether a failed load means the page is switched off rather than broken.
 *
 * The Support menu being off answers 400, the destination being off answers 404, and a caller
 * without an application role answers 403. None of those is fixed by trying again.
 */
function isSwitchedOff(error: unknown): boolean {
    return error instanceof ApiError && [400, 403, 404].includes(error.status);
}

function countText(total: number, shown: number, searching: boolean): string {
    const noun = total === 1 ? 'announcement' : 'announcements';
    return searching ? `${shown} of ${total} ${noun} match` : `${total} ${noun}`;
}

export function SupportLatestFeaturesPage() {
    const [groups, setGroups] = useState<LatestFeatureGroup[]>([]);
    const [loadState, setLoadState] = useState<LoadState>('loading');
    const [attempt, setAttempt] = useState(0);
    const [query, setQuery] = useState('');

    useEffect(() => {
        const controller = new AbortController();
        setLoadState('loading');
        api.get<UserLatestFeaturesPayload>(USER_LATEST_FEATURES_ENDPOINT, controller.signal)
            .then((payload) => {
                setGroups(Array.isArray(payload?.groups) ? payload.groups : []);
                setLoadState('ready');
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return;
                }
                setLoadState(isSwitchedOff(error) ? 'unavailable' : 'error');
            });
        return () => controller.abort();
    }, [attempt]);

    const searching = Boolean(query.trim());
    const total = useMemo(() => allFeatures(groups).length, [groups]);
    const shown = useMemo(
        () => (searching ? allFeatures(filterGroups(groups, query)).length : total),
        [groups, query, searching, total],
    );

    let content;
    if (loadState === 'loading') {
        content = (
            <div role="status" aria-label="Loading Latest Features">
                <CatalogueSkeleton />
            </div>
        );
    } else if (loadState === 'unavailable') {
        content = (
            <EmptyState
                icon={<Lock size={28} />}
                title="Latest Features is not available"
                description="Your administrators have not turned on the Latest Features page for your account."
            />
        );
    } else if (loadState === 'error') {
        content = (
            <SectionError
                message="Latest Features could not be loaded. Check your connection and try again."
                action={
                    <GlassButton size="sm" onClick={() => setAttempt((count) => count + 1)}>
                        <RotateCcw size={14} aria-hidden="true" />
                        Try again
                    </GlassButton>
                }
            />
        );
    } else if (!total) {
        content = (
            <EmptyState
                icon={<Zap size={28} />}
                title="No announcements right now"
                description="Your administrators have not shared any Latest Features announcements yet. Check back after the next release."
            />
        );
    } else {
        content = (
            <>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                    <div className="w-full max-w-sm">
                        <SectionSearch
                            value={query}
                            onChange={setQuery}
                            placeholder="Search announcements"
                        />
                    </div>
                    <p className="text-xs text-text-3" aria-live="polite">
                        {countText(total, shown, searching)}
                    </p>
                </div>
                <SupportAnnouncementList groups={groups} query={query} />
            </>
        );
    }

    return (
        <div className="flex h-full min-h-0 flex-col">
            <PageHeader
                title="Latest Features"
                description="What changed in recent releases, as your administrators chose to share it."
            />
            <div
                data-testid="support-page-scroll"
                className="min-h-0 flex-1 overflow-y-auto px-4 py-5 lg:px-6"
            >
                <div className="mx-auto w-full max-w-4xl space-y-4 pb-10">{content}</div>
            </div>
        </div>
    );
}
