// workflowEditorSectionIcons.ts
// The icon each workflow editor card shows, shared by the card header and the On this page index.
//
// Kept beside the editor rather than in `workflowEditorSections.ts` so that module stays free of
// components and can be executed in a plain Node test.

import type { LucideIcon } from 'lucide-react';
import { BellRing, CalendarClock, FolderSync, Gauge, Library, ListChecks, Settings2, Workflow } from 'lucide-react';
import type { WorkflowEditorSectionId } from '../../lib/workflowEditorSections';

export const WORKFLOW_EDITOR_SECTION_ICONS: Readonly<Record<WorkflowEditorSectionId, LucideIcon>> = {
    basics: Workflow,
    trigger: CalendarClock,
    // The workspace navigation's File sources icon, so the two read as the same feature.
    'file-sync': FolderSync,
    execution: Settings2,
    references: Library,
    limits: Gauge,
    tasks: ListChecks,
    alerts: BellRing,
};
