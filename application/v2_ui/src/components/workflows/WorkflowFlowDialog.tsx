// WorkflowFlowDialog.tsx
// Standalone reader access does not depend on edit permission or an inactive run.

import { useEffect, useRef } from 'react';
import type { WorkflowScope } from '../../lib/workflowEditor';
import { Modal } from '../ui/Modal';
import { WorkflowFlowView } from './WorkflowFlowView';

export function WorkflowFlowDialog({ scope, workflowId, onClose }: {
    scope: WorkflowScope;
    workflowId: string;
    onClose: () => void;
}) {
    const contentRef = useRef<HTMLDivElement>(null);
    useEffect(() => {
        const previous = document.activeElement;
        const dialog = contentRef.current?.closest<HTMLElement>('[role="dialog"]');
        contentRef.current?.focus();
        const trap = (event: KeyboardEvent) => {
            if (event.key !== 'Tab' || !dialog) return;
            const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
                'button, a[href], input, select, textarea, [tabindex]',
            )).filter((element) => element.tabIndex >= 0 && !element.matches(':disabled') &&
                !element.closest('[hidden], [inert]') && element.getClientRects().length > 0);
            const first = focusable[0];
            const last = focusable.at(-1);
            if (!first || !last) return;
            if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
                event.preventDefault();
                first.focus();
            }
        };
        document.addEventListener('keydown', trap);
        return () => {
            document.removeEventListener('keydown', trap);
            if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
        };
    }, []);

    return <Modal title="Workflow Flow" description="Read the current saved structured definition without editing it."
        size="xl" tall onClose={onClose}>
        <div ref={contentRef} tabIndex={-1} className="min-w-0 focus:outline-none">
            <WorkflowFlowView scope={scope} target={{ kind: 'saved', workflowId }} />
        </div>
    </Modal>;
}
