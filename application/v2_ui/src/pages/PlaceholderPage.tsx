// PlaceholderPage.tsx
// Navigation targets that exist in the V2 rail but whose surfaces have not been rebuilt
// yet. Rather than hiding the nav entry or dead-ending the user, each links through to the
// equivalent page in the current interface.

import { ArrowUpRight } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassPanel } from '../components/ui/primitives';

export function PlaceholderPage({
    title,
    description,
    classicHref,
    classicLabel,
}: {
    title: string;
    description: string;
    classicHref: string;
    classicLabel: string;
}) {
    return (
        <>
            <PageHeader title={title} />
            <div className="flex flex-1 items-center justify-center p-6">
                <GlassPanel edge className="max-w-lg p-6 text-center">
                    <h2 className="text-base font-semibold text-text-1">
                        Not rebuilt in V2 yet
                    </h2>
                    <p className="mt-2 text-sm text-text-3">{description}</p>
                    <a
                        href={classicHref}
                        className="mt-4 inline-flex items-center gap-1.5 rounded-xl bg-accent px-4 py-2 text-sm font-medium text-on-accent transition-colors hover:bg-accent-hover"
                    >
                        {classicLabel}
                        <ArrowUpRight size={15} />
                    </a>
                </GlassPanel>
            </div>
        </>
    );
}
