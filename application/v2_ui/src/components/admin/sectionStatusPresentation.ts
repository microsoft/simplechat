// sectionStatusPresentation.ts
// The words, colours, and icons for a section's status, shared by the card and the index.

import {
    AlertTriangle,
    CircleCheck,
    CircleDashed,
    CircleSlash,
    type LucideIcon,
} from 'lucide-react';
import type { SectionStatus } from '../../lib/adminSections';

export interface SectionStatusPresentation {
    label: string;
    /** Chip treatment: text, border, and fill. */
    className: string;
    /** Icon colour alone, for the compact index entry. */
    toneClassName: string;
    Icon: LucideIcon;
}

export const SECTION_STATUS_PRESENTATION: Record<
    Exclude<SectionStatus, 'none'>,
    SectionStatusPresentation
> = {
    off: {
        label: 'Off',
        className: 'text-text-3 border-edge-strong',
        toneClassName: 'text-text-3',
        Icon: CircleSlash,
    },
    blocked: {
        label: 'Prerequisite missing',
        className: 'text-warn border-warn/40 bg-warn/5',
        toneClassName: 'text-warn',
        Icon: AlertTriangle,
    },
    incomplete: {
        label: 'Needs configuration',
        className: 'text-warn border-warn/40 bg-warn/5',
        toneClassName: 'text-warn',
        Icon: CircleDashed,
    },
    ready: {
        label: 'Configured',
        className: 'text-ok border-ok/40 bg-ok/5',
        toneClassName: 'text-ok',
        Icon: CircleCheck,
    },
};

export function presentSectionStatus(status: SectionStatus): SectionStatusPresentation | null {
    return status === 'none' ? null : SECTION_STATUS_PRESENTATION[status];
}

/** Statuses that ask the administrator to do something. */
export function needsAttention(status: SectionStatus): boolean {
    return status === 'blocked' || status === 'incomplete';
}
