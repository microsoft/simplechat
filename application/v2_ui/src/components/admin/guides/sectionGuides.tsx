// sectionGuides.tsx
// The in-app guides a section header can offer, by the id the server names them with.
//
// `ADMIN_SECTION_GUIDES` in admin_settings_fields.py decides which section offers which
// guide and what its button says; this decides what the guide contains. A section whose
// guide id has no entry here simply offers no button, rather than one that opens nothing.

import type { ReactNode } from 'react';
import type { AdminSectionGuide } from '../../../lib/adminFields';
import type { Json } from '../../../lib/types';
import { ControlCenterRolesGuide } from './ControlCenterRolesGuide';
import { GuideDialog } from './GuideDialog';
import { HealthCheckGuide } from './HealthCheckGuide';
import { SwaggerGuide } from './SwaggerGuide';

/** What a guide may read about the deployment it is describing. */
export interface SectionGuideContext {
    /** Saved settings, not the draft: a guide describes what is live. */
    settings: Json;
    runtimeFlags: Record<string, boolean>;
}

interface SectionGuideDefinition {
    title: string;
    description: string;
    render: (context: SectionGuideContext) => ReactNode;
}

const SECTION_GUIDES: Record<string, SectionGuideDefinition> = {
    'control-center-roles': {
        title: 'Control Center role setup',
        description: 'Create the app roles in Entra, assign them, then switch the requirements on.',
        render: () => <ControlCenterRolesGuide />,
    },
    'health-check': {
        title: 'Health check configuration',
        description: "Point App Service Health check, or another monitor, at SimpleChat's endpoints.",
        render: ({ settings }) => <HealthCheckGuide settings={settings} />,
    },
    'swagger': {
        title: 'Why enable Swagger?',
        description: 'What the API documentation offers, and who can see it.',
        render: ({ runtimeFlags }) => (
            <SwaggerGuide running={Boolean(runtimeFlags.swagger_routes_registered)} />
        ),
    },
};

export function hasSectionGuide(id: string): boolean {
    return Object.prototype.hasOwnProperty.call(SECTION_GUIDES, id);
}

export function SectionGuide({
    guide,
    context,
    onClose,
}: {
    guide: AdminSectionGuide;
    context: SectionGuideContext;
    onClose: () => void;
}) {
    if (!hasSectionGuide(guide.id)) {
        return null;
    }
    const definition = SECTION_GUIDES[guide.id];
    return (
        <GuideDialog
            title={definition.title}
            description={definition.description}
            docsUrl={guide.docs_url}
            onClose={onClose}
        >
            {definition.render(context)}
        </GuideDialog>
    );
}
