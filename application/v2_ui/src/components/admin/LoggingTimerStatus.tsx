// LoggingTimerStatus.tsx
// When a log's automatic turnoff will happen, in the administrator's own time.
//
// The server-rendered page printed the stored turnoff time as a raw timestamp in the
// server's clock, which told an administrator in another zone almost nothing. Turnoff times
// are now stored in UTC, so this shows them in the browser's zone with how far off they are.
//
// It also says what a save would do. Changing the duration restarts the clock from the
// moment of saving, while saving an unrelated setting does not, and the readout follows the
// same rule as the server so it never promises a restart that will not happen.

import { AlarmClock, CircleAlert, Clock, Infinity as Endless } from 'lucide-react';
import type { AdminLoggingTimerKeys } from '../../lib/adminFields';
import { describeLoggingTimer, formatInstant, formatRelative } from '../../lib/adminOperations';
import type { Json } from '../../lib/types';
import { ReadoutLine, ReadoutRow } from './ReadoutRow';
import { useNow } from './useNow';

export function LoggingTimerStatus({
    label,
    help,
    keys,
    settings,
    draft,
}: {
    label: string;
    help?: string;
    keys: AdminLoggingTimerKeys;
    settings: Json;
    draft: Json;
}) {
    const now = useNow();
    const readout = describeLoggingTimer(keys, settings, draft, now);

    if (readout.kind === 'off') {
        return null;
    }

    return (
        <ReadoutRow label={label} help={help}>
            <div role="status">
                {readout.kind === 'no-timer' ? (
                    <ReadoutLine tone="info" icon={Endless}>
                        No automatic turnoff: it stays on until someone switches it off.
                    </ReadoutLine>
                ) : null}

                {readout.kind === 'on-save' && readout.reason !== 'missing' ? (
                    <ReadoutLine
                        tone="info"
                        icon={Clock}
                        detail="The clock starts when you save, not when you change the setting."
                    >
                        Saving now would turn it off {formatInstant(readout.projected)} (
                        {formatRelative(readout.projected, now)}).
                    </ReadoutLine>
                ) : null}

                {readout.kind === 'on-save' && readout.reason === 'missing' ? (
                    <ReadoutLine
                        tone="warn"
                        icon={CircleAlert}
                        detail="Change the duration or unit and save to start the timer."
                    >
                        No turnoff time is stored, so it will not switch itself off yet.
                    </ReadoutLine>
                ) : null}

                {readout.kind === 'scheduled' ? (
                    <ReadoutLine tone="ok" icon={AlarmClock} detail="Shown in your timezone.">
                        Turns off {formatInstant(readout.at)} ({formatRelative(readout.at, now)}).
                    </ReadoutLine>
                ) : null}

                {readout.kind === 'overdue' ? (
                    <ReadoutLine
                        tone="warn"
                        icon={AlarmClock}
                        detail="The background check runs every minute and switches it off then."
                    >
                        Due to turn off now; it was set for {formatInstant(readout.at)}.
                    </ReadoutLine>
                ) : null}

                {readout.kind === 'legacy' ? (
                    <ReadoutLine
                        tone="info"
                        icon={AlarmClock}
                        detail="Set before turnoff times were stored in UTC, so it is shown as the server wrote it."
                    >
                        Turns off at {readout.text}, server time.
                    </ReadoutLine>
                ) : null}
            </div>
        </ReadoutRow>
    );
}
