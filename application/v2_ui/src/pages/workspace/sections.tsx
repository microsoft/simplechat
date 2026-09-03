// sections.tsx
// The personal workspace section registry.
//
// One place that names every section, says which group it belongs to, and explains what it
// is for. The navigation rail, the overview and the router all read from here, so a section
// cannot appear in one and be missing from another.
//
// `blurb` is written to answer "why would I open this?" rather than to restate the label.
// It is the text the overview shows, and for a section an administrator has switched off it
// is the only thing a user has to go on.

import type { LucideIcon } from 'lucide-react';
import {
    FileText,
    FolderSync,
    KeyRound,
    MessageSquareQuote,
    Plug,
    Server,
    Sparkles,
    Tags,
    Workflow,
} from 'lucide-react';
import type { ReactNode } from 'react';
import type { WorkspaceSectionGroup } from '../../lib/types';
import type { WorkspaceSectionDescriptor } from '../../lib/workspaceSections';
import { ActionsSection } from './ActionsSection';
import { AgentsSection } from './AgentsSection';
import { DocumentsSection } from './DocumentsSection';
import { EndpointsSection } from './EndpointsSection';
import { FileSourcesSection } from './FileSourcesSection';
import { IdentitiesSection } from './IdentitiesSection';
import { PromptsSection } from './PromptsSection';
import { TagsSection } from './TagsSection';
import { WorkflowsSection } from './WorkflowsSection';

export interface WorkspaceSectionContext {
    /** Whether another section is available, for cross-links that should not dead-end. */
    isEnabled: (sectionId: string) => boolean;
}

/**
 * How much room a section needs.
 *
 * Most sections are a column of rows and read better constrained to a comfortable measure.
 * The documents explorer and the prompts workbench are not: each carries its own list, details
 * pane and command bar, and each manages its own scrolling, so they need the full width and
 * height of the page rather than being centred inside a narrower one.
 */
export type WorkspaceSectionLayout = 'prose' | 'full';

export interface WorkspaceSectionDefinition extends WorkspaceSectionDescriptor {
    id: string;
    label: string;
    group: WorkspaceSectionGroup;
    icon: LucideIcon;
    /** One line on what the section is for. Shown on the overview. */
    blurb: string;
    layout?: WorkspaceSectionLayout;
    render: (context: WorkspaceSectionContext) => ReactNode;
}

export const WORKSPACE_SECTIONS: WorkspaceSectionDefinition[] = [
    {
        id: 'documents',
        label: 'Documents',
        group: 'knowledge',
        icon: FileText,
        blurb: 'Files you upload, indexed so the assistant can quote them.',
        layout: 'full',
        render: (context) => <DocumentsSection syncEnabled={context.isEnabled('sync')} />,
    },
    {
        id: 'tags',
        label: 'Tags',
        group: 'knowledge',
        icon: Tags,
        blurb: 'The labels your documents are filed under, and what each one is called.',
        render: (context) => <TagsSection documentsEnabled={context.isEnabled('documents')} />,
    },
    {
        id: 'sync',
        label: 'File sources',
        group: 'knowledge',
        icon: FolderSync,
        blurb: 'Bring files in from where they already live, instead of uploading them.',
        render: () => <FileSourcesSection />,
    },
    {
        id: 'prompts',
        label: 'Prompts',
        group: 'knowledge',
        icon: MessageSquareQuote,
        blurb: 'Wording you have refined once and want to reuse in chat.',
        layout: 'full',
        render: () => <PromptsSection />,
    },
    {
        id: 'agents',
        label: 'Agents',
        group: 'automation',
        icon: Sparkles,
        blurb: 'Assistants you configure once: instructions, knowledge and actions.',
        render: (context) => <AgentsSection actionsEnabled={context.isEnabled('actions')} />,
    },
    {
        id: 'actions',
        label: 'Actions',
        group: 'automation',
        icon: Plug,
        blurb: 'Tools an agent may call, such as an API, a database or an MCP server.',
        render: (context) => <ActionsSection agentsEnabled={context.isEnabled('agents')} />,
    },
    {
        id: 'workflows',
        label: 'Workflows',
        group: 'automation',
        icon: Workflow,
        blurb: 'Repeatable tasks that run on a schedule or on demand.',
        render: () => <WorkflowsSection />,
    },
    {
        id: 'identities',
        label: 'Identities',
        group: 'connections',
        icon: KeyRound,
        blurb: 'Saved sign-ins that file sources and actions use to reach other systems.',
        render: (context) => (
            <IdentitiesSection
                syncEnabled={context.isEnabled('sync')}
                actionsEnabled={context.isEnabled('actions')}
            />
        ),
    },
    {
        id: 'endpoints',
        label: 'Endpoints',
        group: 'connections',
        icon: Server,
        blurb: 'Model endpoints of your own for agents and workflows to use.',
        render: () => <EndpointsSection />,
    },
];

export const WORKSPACE_SECTIONS_BY_ID: Record<string, WorkspaceSectionDefinition> =
    Object.fromEntries(WORKSPACE_SECTIONS.map((section) => [section.id, section]));
