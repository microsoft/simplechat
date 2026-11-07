// RestartStatus.tsx
// Says whether a setting the app only reads at startup is live yet.
//
// Application Insights global logging and the Swagger routes are both wired up once, when
// the App Service starts. Saving either switch changes the settings document and nothing
// else, so the page would otherwise show a setting as on while the running app behaves as
// though it were off -- with nothing to explain why the change "did not work". The server
// reports how the running process was started; this compares that with the saved value and
// any unsaved edit.

import { CheckCircle2, Info, RotateCcw } from 'lucide-react';
import { describeRestartState } from '../../lib/adminOperations';
import { ReadoutLine, ReadoutRow } from './ReadoutRow';

function onOff(value: boolean): string {
    return value ? 'on' : 'off';
}

export function RestartStatus({
    label,
    help,
    saved,
    draft,
    running,
    available,
}: {
    label: string;
    help?: string;
    saved: boolean;
    draft: boolean;
    running: boolean;
    /** False when the setting cannot take effect whatever is saved; another readout says why. */
    available: boolean;
}) {
    const state = describeRestartState({ saved, draft, running, available });
    if (state.kind === 'unavailable') {
        return null;
    }

    return (
        <ReadoutRow label={label} help={help}>
            <div role="status">
                {state.kind === 'in-sync' ? (
                    <ReadoutLine tone="ok" icon={CheckCircle2}>
                        Running as saved: {onOff(state.running)}.
                    </ReadoutLine>
                ) : null}
                {state.kind === 'restart' ? (
                    <ReadoutLine
                        tone="warn"
                        icon={RotateCcw}
                        detail="Restart the App Service to apply the saved setting."
                    >
                        Saved as {onOff(state.saved)}, but the running app started with it{' '}
                        {onOff(state.running)}.
                    </ReadoutLine>
                ) : null}
                {state.kind === 'save-then-restart' ? (
                    <ReadoutLine tone="info" icon={Info} detail="Saving alone does not change the running app.">
                        Turns {onOff(state.next)} after you save and then restart the App Service.
                    </ReadoutLine>
                ) : null}
            </div>
        </ReadoutRow>
    );
}
