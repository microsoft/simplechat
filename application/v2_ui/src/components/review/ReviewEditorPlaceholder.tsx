// ReviewEditorPlaceholder.tsx
// What a Review center editor page shows while its record loads, or in place of a record
// that could not be loaded: the state, and the way back to the workbench.

import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { GlassButton } from '../ui/primitives';

export function ReviewEditorPlaceholder({ backTo, children }: { backTo: string; children: ReactNode }) {
    const navigate = useNavigate();
    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="shrink-0 border-b border-edge pb-3">
                <GlassButton type="button" size="sm" variant="ghost" className="-ml-2" onClick={() => navigate(backTo)}>
                    <ArrowLeft size={15} aria-hidden="true" /> Back
                </GlassButton>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto py-4">{children}</div>
        </div>
    );
}
