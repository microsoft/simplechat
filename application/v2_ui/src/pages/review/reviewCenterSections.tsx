// reviewCenterSections.tsx
// What the admin Review center's rail offers, section by section.
//
// Each entry is one page of a section: its dashboard, its workbench, or a queue such as
// unchecked chat content. An entry names the address it lives at, how the rail shows it,
// and what it draws; an entry whose records open in an editor also draws that editor, at
// the entry's address followed by the record id. The page reads only this list, so adding
// a page to a section -- such as an AI suggestions queue -- is adding an entry here.

import type { ReactNode } from 'react';
import { LayoutDashboard, ListChecks, ScanSearch, ShieldAlert, type LucideIcon } from 'lucide-react';
import type { ReviewAccessInput, ReviewSectionId } from '../../lib/reviewAccess';
import { FeedbackDashboard } from './FeedbackDashboard';
import { FeedbackEditorPage } from './FeedbackEditorPage';
import { FeedbackWorkbench } from './FeedbackWorkbench';
import { SafetyDashboard } from './SafetyDashboard';
import { SafetyEditorPage } from './SafetyEditorPage';
import { SafetyWorkbench } from './SafetyWorkbench';
import { UncheckedChatContent } from './UncheckedChatContent';

export interface ReviewEntryContext {
    /** Bumped by the page's Refresh, so the entry reloads what it shows. */
    reloadKey: number;
    /** Reports how many records the entry lists, shown beside it in the rail. */
    onCountChange: (count: number) => void;
}

export interface ReviewEntry {
    /** Unique across the Review center, such as `feedback-queue`. Also the rail's test id suffix. */
    id: string;
    section: ReviewSectionId;
    /** The address segment after the section: '' for the dashboard, otherwise one word. */
    view: string;
    label: string;
    /** The name read for the entry, which must contain the label, such as "Feedback dashboard". */
    accessibleLabel: string;
    description: string;
    Icon: LucideIcon;
    render: (context: ReviewEntryContext) => ReactNode;
    /** The editor a record opens in, at `<view>/<recordId>`. */
    renderRecord?: (recordId: string, context: ReviewEntryContext) => ReactNode;
    /** Further narrows who sees the entry, beyond access to its section. */
    available?: (input: ReviewAccessInput) => boolean;
}

export const REVIEW_SECTION_LABELS: Readonly<Record<ReviewSectionId, string>> = {
    feedback: 'Feedback',
    safety: 'Safety',
};

export const REVIEW_CENTER_ENTRIES: ReviewEntry[] = [
    {
        id: 'feedback-dashboard',
        section: 'feedback',
        view: '',
        label: 'Dashboard',
        accessibleLabel: 'Feedback dashboard',
        description: 'What users are saying about AI responses, and what is waiting for a review.',
        Icon: LayoutDashboard,
        render: ({ reloadKey }) => <FeedbackDashboard reloadKey={reloadKey} />,
    },
    {
        id: 'feedback-queue',
        section: 'feedback',
        view: 'queue',
        label: 'Feedback',
        accessibleLabel: 'Feedback queue',
        description: 'Every feedback record, to review one at a time or many at once.',
        Icon: ListChecks,
        render: ({ reloadKey, onCountChange }) => (
            <FeedbackWorkbench reloadKey={reloadKey} onCountChange={onCountChange} />
        ),
        renderRecord: (recordId) => <FeedbackEditorPage key={recordId} recordId={recordId} />,
    },
    {
        id: 'safety-dashboard',
        section: 'safety',
        view: '',
        label: 'Dashboard',
        accessibleLabel: 'Safety dashboard',
        description: 'Flagged activity, remediation in progress, and who is restricted now.',
        Icon: LayoutDashboard,
        render: ({ reloadKey }) => <SafetyDashboard reloadKey={reloadKey} />,
    },
    {
        id: 'safety-violations',
        section: 'safety',
        view: 'violations',
        label: 'Violations',
        accessibleLabel: 'Safety violations',
        description: 'Every safety violation, to review one at a time or many at once.',
        Icon: ShieldAlert,
        render: ({ reloadKey, onCountChange }) => (
            <SafetyWorkbench reloadKey={reloadKey} onCountChange={onCountChange} />
        ),
        renderRecord: (recordId) => <SafetyEditorPage key={recordId} recordId={recordId} />,
    },
    {
        id: 'safety-unchecked',
        section: 'safety',
        view: 'unchecked',
        label: 'Unchecked chat content',
        accessibleLabel: 'Unchecked chat content',
        description: 'Messages allowed through when a required check could not finish.',
        Icon: ScanSearch,
        render: ({ reloadKey }) => <UncheckedChatContent reloadKey={reloadKey} />,
    },
];

/** The entries a user may open, grouped by section in rail order. */
export function reviewEntriesFor(
    sections: readonly ReviewSectionId[],
    input: ReviewAccessInput,
    entries: readonly ReviewEntry[] = REVIEW_CENTER_ENTRIES,
): ReviewEntry[] {
    return sections.flatMap((section) => entries.filter(
        (entry) => entry.section === section && (!entry.available || entry.available(input)),
    ));
}

/** An entry's address, which its records' editors extend. */
export function reviewEntryPath(entry: Pick<ReviewEntry, 'section' | 'view'>): string {
    return entry.view ? `/admin/review/${entry.section}/${entry.view}` : `/admin/review/${entry.section}`;
}
