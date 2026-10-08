// M365CitationChip.tsx
// Inline chips for Microsoft 365 citations, and the source card each one opens.
//
// An answer that used SharePoint or OneDrive files, emails or calendar events cites them with the
// same markers as workspace documents. Their records travel with the message, so a chip shows the
// file name or subject directly, and its card lists what the item is and links to it in
// SharePoint, OneDrive or Outlook, where the reader's own sign-in decides what opens. Nothing here
// calls the workspace citation endpoint: these ids do not name workspace passages.

import { useCallback, useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { CalendarDays, ExternalLink, FileText, Mail, TriangleAlert, X } from 'lucide-react';
import { GlassPanel } from '../ui/primitives';
import {
    m365ChipLabel,
    m365DetailRows,
    m365OpenLabel,
    safeM365Url,
} from '../../lib/m365Citations';
import type { CitationGroup, ParsedCitation } from '../../lib/citations';
import type { M365Citation, M365CitationKind } from '../../lib/types';
import { useM365Citation } from './M365CitationContext';

/** The icon for an item's kind: a file, an email or a calendar event. */
export function M365KindIcon({
    kind,
    size,
    className,
}: {
    kind: M365CitationKind | undefined;
    size: number;
    className?: string;
}) {
    if (kind === 'email') {
        return <Mail size={size} className={className} aria-hidden="true" />;
    }
    if (kind === 'event') {
        return <CalendarDays size={size} className={className} aria-hidden="true" />;
    }
    return <FileText size={size} className={className} aria-hidden="true" />;
}

/** The link that opens an item where it lives, shown only for a checked https URL. */
export function M365OpenLink({
    record,
    label,
    className,
}: {
    record: M365Citation;
    label?: string;
    className?: string;
}) {
    const openUrl = safeM365Url(record.web_url);
    if (!openUrl) {
        return null;
    }
    return (
        <a
            href={openUrl}
            target="_blank"
            rel="noopener noreferrer"
            className={className}
            aria-label={`${label ?? m365OpenLabel(record)}: ${m365ChipLabel(record)}`}
        >
            <ExternalLink size={13} className="shrink-0" aria-hidden="true" />
            {label ?? m365OpenLabel(record)}
        </a>
    );
}

function M365SourceCard({
    record,
    fallbackTitle,
    onClose,
}: {
    record: M365Citation | undefined;
    fallbackTitle: string;
    onClose: () => void;
}) {
    const closeRef = useRef<HTMLButtonElement>(null);

    useEffect(() => {
        closeRef.current?.focus();
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onClose();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [onClose]);

    const rows = record ? m365DetailRows(record) : [];
    const title = record ? record.title : fallbackTitle || 'Microsoft 365 source';

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label="Microsoft 365 source"
        >
            <div className="absolute inset-0 bg-black/40" aria-hidden="true" onClick={onClose} />

            <GlassPanel
                elevation="modal"
                edge
                className="relative flex max-h-[70vh] w-full max-w-lg flex-col"
            >
                <div className="flex shrink-0 items-start gap-3 border-b border-edge px-5 py-3.5">
                    <M365KindIcon kind={record?.kind} size={17} className="mt-0.5 shrink-0 text-text-3" />
                    <div className="min-w-0 flex-1">
                        <h2 className="break-words text-sm font-semibold text-text-1">{title}</h2>
                        {record?.location_label && (
                            <p className="text-xs text-text-3">{record.location_label}</p>
                        )}
                    </div>
                    <button
                        ref={closeRef}
                        type="button"
                        onClick={onClose}
                        aria-label="Close source"
                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={17} />
                    </button>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
                    {record ? (
                        rows.length > 0 ? (
                            <dl className="space-y-2">
                                {rows.map((row) => (
                                    <div key={row.label} className="flex gap-3 text-sm">
                                        <dt className="w-24 shrink-0 text-text-3">{row.label}</dt>
                                        <dd className="min-w-0 flex-1 break-words text-text-1">{row.value}</dd>
                                    </div>
                                ))}
                            </dl>
                        ) : (
                            <p className="text-sm text-text-3">No further details were recorded for this item.</p>
                        )
                    ) : (
                        <p className="flex items-start gap-2 text-sm text-text-2">
                            <TriangleAlert size={15} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
                            This Microsoft 365 source is no longer available in this conversation.
                        </p>
                    )}
                </div>

                {record && safeM365Url(record.web_url) && (
                    <div className="flex shrink-0 justify-end border-t border-edge px-5 py-3">
                        <M365OpenLink
                            record={record}
                            className="inline-flex h-8 items-center gap-1.5 rounded-xl bg-accent px-3 text-sm font-medium text-on-accent shadow-sm transition-colors hover:bg-accent-hover"
                        />
                    </div>
                )}
            </GlassPanel>
        </div>
    );
}

function M365Chip({ citation, fallbackLabel }: { citation: ParsedCitation; fallbackLabel: string }) {
    const record = useM365Citation(citation.citationId);
    const [open, setOpen] = useState(false);
    const chipRef = useRef<HTMLButtonElement>(null);
    const label = record ? m365ChipLabel(record) : fallbackLabel || 'Microsoft 365 source';
    const where = record?.location_label;

    const close = useCallback(() => {
        setOpen(false);
        chipRef.current?.focus();
    }, []);

    return (
        <>
            <button
                ref={chipRef}
                type="button"
                onClick={() => setOpen(true)}
                title={where ? `${label} \u2014 ${where}` : label}
                data-m365-citation-id={citation.citationId}
                aria-haspopup="dialog"
                className={clsx(
                    'inline-flex max-w-[16rem] items-center gap-1 rounded-full border border-edge',
                    'bg-surface-2 px-1.5 py-0.5 text-[11px] text-accent transition-colors hover:bg-surface-3',
                )}
            >
                <M365KindIcon kind={record?.kind} size={10} className="shrink-0" />
                <span className="truncate">{label}</span>
            </button>
            {open && <M365SourceCard record={record} fallbackTitle={fallbackLabel} onClose={close} />}
        </>
    );
}

/** The chips for one Microsoft 365 citation marker, one per item it names. */
export function M365CitationChips({ group }: { group: CitationGroup }) {
    return (
        <span className="mx-0.5 inline-flex flex-wrap items-center gap-0.5 align-baseline">
            {group.citations.map((citation) => (
                <M365Chip key={citation.citationId} citation={citation} fallbackLabel={group.fileName} />
            ))}
        </span>
    );
}
