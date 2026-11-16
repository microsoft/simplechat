// WorkflowAlertLiveRegion.tsx
// What a screen reader hears when a workflow alert arrives.
//
// The notice never takes focus, so it is announced instead: politely, so a sentence being
// read is finished first, and assertively for a critical alert. Both regions are always in
// the page -- a region added together with its text is not reliably read -- and each message
// is cleared again after a few seconds, so reading the page later does not find it there.

import { useEffect, useState } from 'react';
import { useWorkflowAlertStore } from '../../stores/workflowAlertStore';

const CLEAR_AFTER_MS = 7_000;
/** Emptied first and filled a moment later, so the same words twice are still read twice. */
const FILL_DELAY_MS = 100;

export function WorkflowAlertLiveRegion() {
    const announcement = useWorkflowAlertStore((state) => state.announcement);
    const [polite, setPolite] = useState('');
    const [assertive, setAssertive] = useState('');

    useEffect(() => {
        setPolite('');
        setAssertive('');
        if (!announcement) {
            return undefined;
        }
        const fill = setTimeout(() => {
            (announcement.assertive ? setAssertive : setPolite)(announcement.text);
        }, FILL_DELAY_MS);
        const clear = setTimeout(() => {
            setPolite('');
            setAssertive('');
        }, CLEAR_AFTER_MS);
        return () => {
            clearTimeout(fill);
            clearTimeout(clear);
        };
    }, [announcement]);

    return (
        <div className="sr-only">
            <div aria-live="polite" aria-atomic="true" data-workflow-alert-live="polite">{polite}</div>
            <div aria-live="assertive" aria-atomic="true" data-workflow-alert-live="assertive">{assertive}</div>
        </div>
    );
}
