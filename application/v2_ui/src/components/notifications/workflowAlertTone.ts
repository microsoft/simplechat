// workflowAlertTone.ts
// How loud a workflow alert looks: its icon and the token colours for its priority.
//
// The mapping follows WORKFLOW_ALERT_PRIORITY_CONFIG (functions_notifications.py), which
// the classic pop-up reads: info and low use the info colour, medium warn, high danger, and
// critical a solid danger band. A failed run shows the failed-run icon at any priority.
//
// Colour never carries the meaning alone. Every surface that uses these also shows the
// priority's name and, for a failed run, says so. Labels keep the ordinary text colour over
// a tint, because the light theme's --warn is too pale to pass as text.

import { Bell, CircleAlert, Info, OctagonAlert, OctagonX, TriangleAlert, type LucideIcon } from 'lucide-react';
import type { WorkflowAlertSeverity } from '../../lib/workflowAlerts';
import type { WorkflowAlertCategory } from '../../lib/workflowAlertNotices';

export interface WorkflowAlertTone {
    /** The notice's edge, where the priority is loud enough to deserve one. */
    outline: string;
    /** The round chip an icon sits in on an ordinary surface. */
    chip: string;
    /** The priority tag. */
    tag: string;
    /** The card's header band. */
    band: string;
    /** Secondary text in the band. */
    bandMuted: string;
    /** An icon in the band. */
    bandIcon: string;
}

const INFO: WorkflowAlertTone = {
    outline: '',
    chip: 'bg-info-soft text-info',
    tag: 'bg-info-soft text-text-1',
    band: 'bg-info-soft text-text-1',
    bandMuted: 'text-text-2',
    bandIcon: 'text-info',
};

const TONES: Record<WorkflowAlertSeverity, WorkflowAlertTone> = {
    info: INFO,
    low: INFO,
    medium: {
        outline: '',
        chip: 'bg-warn-soft text-warn',
        tag: 'bg-warn-soft text-text-1',
        band: 'bg-warn-soft text-text-1',
        bandMuted: 'text-text-2',
        bandIcon: 'text-warn',
    },
    high: {
        outline: 'border-danger/35',
        chip: 'bg-danger-soft text-danger',
        tag: 'bg-danger-soft text-text-1',
        band: 'bg-danger-soft text-text-1',
        bandMuted: 'text-text-2',
        bandIcon: 'text-danger',
    },
    critical: {
        outline: 'border-danger/60',
        chip: 'bg-danger text-text-inverse',
        tag: 'bg-danger text-text-inverse',
        band: 'bg-danger text-text-inverse',
        bandMuted: 'text-text-inverse',
        bandIcon: 'text-text-inverse',
    },
};

const ICONS: Record<WorkflowAlertSeverity, LucideIcon> = {
    info: Info,
    low: Bell,
    medium: CircleAlert,
    high: TriangleAlert,
    critical: OctagonAlert,
};

export function workflowAlertTone(priority: WorkflowAlertSeverity): WorkflowAlertTone {
    return TONES[priority];
}

export function workflowAlertIcon(priority: WorkflowAlertSeverity, category: WorkflowAlertCategory): LucideIcon {
    return category === 'failure' ? OctagonX : ICONS[priority];
}

/** "Run failed" or "Alert", as the card's band and the notice say it. */
export function workflowAlertKindLabel(category: WorkflowAlertCategory): string {
    return category === 'failure' ? 'Run failed' : 'Alert';
}
