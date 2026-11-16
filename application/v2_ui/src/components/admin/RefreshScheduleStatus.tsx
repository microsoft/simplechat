// RefreshScheduleStatus.tsx
// When the Control Center's daily refresh runs next, and when it last ran.
//
// The schedule is set in one timezone and read by administrators in others, so the next
// run is shown twice when the two differ: in the schedule's own zone, which is what the
// refresh follows, and in the reader's, which is what they will actually be doing at the
// time. The server-rendered page showed only the reader's.
//
// It follows the server's rule for when a save moves the next run, so an unsaved change to
// the time or timezone is shown as what the save would schedule rather than as the run
// that is still stored.

import { ArrowUpRight, CalendarClock, CalendarOff, Clock, History } from 'lucide-react';
import {
    CONTROL_CENTER_SCHEDULE_KEYS,
    describeRefreshSchedule,
    formatInstant,
    formatRelative,
    formatWallTime,
    isKnownTimeZone,
    readStoredInstant,
    viewerTimeZone,
} from '../../lib/adminOperations';
import type { Json } from '../../lib/types';
import { ReadoutLine, ReadoutRow } from './ReadoutRow';
import { useNow } from './useNow';

/** "Tue, 2:00 AM (America/New_York)", plus the reader's own time when it differs. */
function ZonedTime({ at, zone, now }: { at: Date; zone: string; now: Date }) {
    const viewer = viewerTimeZone();
    const zoneKnown = isKnownTimeZone(zone);
    if (!zoneKnown || !viewer || viewer === zone) {
        return (
            <>
                {formatInstant(at)} ({formatRelative(at, now)})
            </>
        );
    }
    return (
        <>
            {formatInstant(at, zone)} in {zone}, which is {formatInstant(at)} your time (
            {formatRelative(at, now)})
        </>
    );
}

export function RefreshScheduleStatus({
    label,
    help,
    settings,
    draft,
}: {
    label: string;
    help?: string;
    settings: Json;
    draft: Json;
}) {
    const now = useNow();
    const readout = describeRefreshSchedule(settings, draft, now);
    const lastRefresh = readStoredInstant(settings[CONTROL_CENTER_SCHEDULE_KEYS.lastRefresh]);

    return (
        <ReadoutRow label={label} help={help}>
            <div className="space-y-2">
                <div role="status">
                    {readout.kind === 'off' ? (
                        <ReadoutLine
                            tone="info"
                            icon={CalendarOff}
                            detail="The figures change only when someone refreshes them in the Control Center."
                        >
                            The daily refresh is off.
                        </ReadoutLine>
                    ) : null}

                    {readout.kind === 'on-save' ? (
                        <ReadoutLine
                            tone="info"
                            icon={Clock}
                            detail="The stored schedule stays in force until you save."
                        >
                            {readout.projected ? (
                                <>
                                    Saving schedules the next refresh for{' '}
                                    <ZonedTime at={readout.projected} zone={readout.timezone} now={now} />.
                                </>
                            ) : (
                                'Saving calculates the next refresh from the time and timezone above.'
                            )}
                        </ReadoutLine>
                    ) : null}

                    {readout.kind === 'scheduled' ? (
                        <ReadoutLine
                            tone="ok"
                            icon={CalendarClock}
                            detail={`Runs daily at ${formatWallTime(readout.time)}, ${readout.timezone} time.`}
                        >
                            Next refresh <ZonedTime at={readout.at} zone={readout.timezone} now={now} />.
                        </ReadoutLine>
                    ) : null}

                    {readout.kind === 'overdue' ? (
                        <ReadoutLine
                            tone="warn"
                            icon={CalendarClock}
                            detail="The scheduler checks every five minutes and starts it then."
                        >
                            Due now; it was scheduled for{' '}
                            {isKnownTimeZone(readout.timezone)
                                ? formatInstant(readout.at, readout.timezone)
                                : formatInstant(readout.at)}
                            .
                        </ReadoutLine>
                    ) : null}

                    {readout.kind === 'unscheduled' ? (
                        <ReadoutLine
                            tone="info"
                            icon={Clock}
                            detail="The scheduler sets it within five minutes, or saving the schedule sets it now."
                        >
                            No run is scheduled yet.
                        </ReadoutLine>
                    ) : null}
                </div>

                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs text-text-3">
                    <span className="flex items-center gap-1.5">
                        <History size={13} aria-hidden="true" className="shrink-0" />
                        {lastRefresh.kind === 'instant' ? (
                            <>
                                Last refreshed {formatInstant(lastRefresh.at)} (
                                {formatRelative(lastRefresh.at, now)}).
                            </>
                        ) : lastRefresh.kind === 'legacy' ? (
                            <>Last refreshed {lastRefresh.text}, server time.</>
                        ) : (
                            'Not refreshed yet.'
                        )}
                    </span>
                    <a
                        href="/admin/control-center"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 font-medium text-accent hover:underline"
                    >
                        Open Control Center
                        <ArrowUpRight size={13} aria-hidden="true" />
                        <span className="sr-only">(opens in a new tab)</span>
                    </a>
                </div>
            </div>
        </ReadoutRow>
    );
}
