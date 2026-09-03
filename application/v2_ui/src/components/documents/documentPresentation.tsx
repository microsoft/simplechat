// documentPresentation.tsx
// Shared visual vocabulary for the documents explorer.
//
// The icon, the tag chip and the status badge each appear in the table, the tiles and the
// details pane. Keeping one definition of each is what stops the three surfaces from
// drifting into three slightly different ideas of what a "processing" document looks like.

import { clsx } from 'clsx';
import {
    FileArchive,
    FileAudio,
    FileChartColumn,
    FileCode,
    FileImage,
    FileSpreadsheet,
    FileText,
    FileType,
    FileVideo,
    Loader2,
    type LucideIcon,
} from 'lucide-react';
import type { WorkspaceDocument } from '../../lib/types';
import { documentStatus } from '../../lib/documentExplorer';

/**
 * File-type icons, keyed by extension.
 *
 * A file manager is scanned rather than read, and the icon is what carries type at a glance,
 * so the groupings follow what a user would call the file rather than its MIME family.
 */
const EXTENSION_ICONS: Record<string, LucideIcon> = {
    pdf: FileType,
    doc: FileText,
    docx: FileText,
    docm: FileText,
    txt: FileText,
    md: FileText,
    rtf: FileText,
    odt: FileText,
    xls: FileSpreadsheet,
    xlsx: FileSpreadsheet,
    xlsm: FileSpreadsheet,
    csv: FileSpreadsheet,
    tsv: FileSpreadsheet,
    ppt: FileChartColumn,
    pptx: FileChartColumn,
    png: FileImage,
    jpg: FileImage,
    jpeg: FileImage,
    gif: FileImage,
    bmp: FileImage,
    webp: FileImage,
    svg: FileImage,
    tiff: FileImage,
    mp3: FileAudio,
    wav: FileAudio,
    m4a: FileAudio,
    flac: FileAudio,
    ogg: FileAudio,
    mp4: FileVideo,
    mov: FileVideo,
    avi: FileVideo,
    mkv: FileVideo,
    webm: FileVideo,
    zip: FileArchive,
    rar: FileArchive,
    '7z': FileArchive,
    tar: FileArchive,
    gz: FileArchive,
    json: FileCode,
    xml: FileCode,
    yaml: FileCode,
    yml: FileCode,
    html: FileCode,
    log: FileCode,
};

/** Colour by family, so a spreadsheet and a document are told apart before being read. */
const EXTENSION_TONES: Record<string, string> = {
    pdf: 'text-danger',
    doc: 'text-accent',
    docx: 'text-accent',
    docm: 'text-accent',
    xls: 'text-ok',
    xlsx: 'text-ok',
    xlsm: 'text-ok',
    csv: 'text-ok',
    tsv: 'text-ok',
    ppt: 'text-warn',
    pptx: 'text-warn',
};

export function documentExtension(document: WorkspaceDocument): string {
    const explicit = String(document.file_type ?? '').replace('.', '').toLowerCase();
    if (explicit) {
        return explicit;
    }
    const fileName = String(document.file_name ?? '');
    const dotIndex = fileName.lastIndexOf('.');
    return dotIndex === -1 ? '' : fileName.slice(dotIndex + 1).toLowerCase();
}

export function DocumentIcon({
    document,
    size = 18,
    className,
}: {
    document: WorkspaceDocument;
    size?: number;
    className?: string;
}) {
    const extension = documentExtension(document);
    const Icon = EXTENSION_ICONS[extension] ?? FileText;
    return (
        <Icon
            size={size}
            aria-hidden="true"
            className={clsx('shrink-0', EXTENSION_TONES[extension] ?? 'text-text-3', className)}
        />
    );
}

/**
 * Decide readable text for an arbitrary background colour.
 *
 * Tag colours are user-chosen and unconstrained, so a fixed foreground would be unreadable
 * against roughly half of them. The threshold is the usual relative-luminance one.
 */
export function readableTextColor(background: string | undefined): string {
    const hex = String(background ?? '').trim().replace('#', '');
    if (hex.length !== 3 && hex.length !== 6) {
        return 'inherit';
    }
    const expanded =
        hex.length === 3
            ? hex.split('').map((character) => character + character).join('')
            : hex;
    const red = parseInt(expanded.slice(0, 2), 16);
    const green = parseInt(expanded.slice(2, 4), 16);
    const blue = parseInt(expanded.slice(4, 6), 16);
    if ([red, green, blue].some((channel) => Number.isNaN(channel))) {
        return 'inherit';
    }
    const luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255;
    return luminance > 0.6 ? '#1f2933' : '#ffffff';
}

export function TagChip({
    name,
    color,
    onRemove,
    onClick,
}: {
    name: string;
    color?: string;
    onRemove?: () => void;
    onClick?: () => void;
}) {
    const style = color
        ? { backgroundColor: color, color: readableTextColor(color) }
        : undefined;

    return (
        <span
            className={clsx(
                'inline-flex max-w-full items-center gap-1 rounded-full px-2 py-0.5',
                'text-[11px] leading-none font-medium',
                !color && 'bg-surface-2 text-text-2',
            )}
            style={style}
        >
            {onClick ? (
                <button
                    type="button"
                    onClick={onClick}
                    className="max-w-[10rem] truncate hover:underline"
                >
                    {name}
                </button>
            ) : (
                <span className="max-w-[10rem] truncate">{name}</span>
            )}
            {onRemove ? (
                <button
                    type="button"
                    onClick={onRemove}
                    aria-label={`Remove tag ${name}`}
                    className="-mr-0.5 rounded-full px-0.5 leading-none opacity-70 hover:opacity-100"
                >
                    &times;
                </button>
            ) : null}
        </span>
    );
}

/** A row of tag chips that stops at `limit` and reports how many it left out. */
export function TagChipList({
    tags,
    colors,
    limit,
    onSelectTag,
}: {
    tags: string[];
    colors?: Record<string, string | undefined>;
    limit?: number;
    onSelectTag?: (tag: string) => void;
}) {
    if (tags.length === 0) {
        return <span className="text-xs text-text-3">—</span>;
    }

    const shown = limit ? tags.slice(0, limit) : tags;
    const hidden = tags.length - shown.length;

    return (
        <span className="flex flex-wrap items-center gap-1">
            {shown.map((tag) => (
                <TagChip
                    key={tag}
                    name={tag}
                    color={colors?.[tag]}
                    onClick={onSelectTag ? () => onSelectTag(tag) : undefined}
                />
            ))}
            {hidden > 0 ? (
                <span className="text-[11px] text-text-3" title={tags.join(', ')}>
                    +{hidden}
                </span>
            ) : null}
        </span>
    );
}

export function DocumentStatusBadge({
    document,
    showProgressBar = false,
}: {
    document: WorkspaceDocument;
    showProgressBar?: boolean;
}) {
    const status = documentStatus(document);

    if (status.state === 'ready') {
        return (
            <span className="rounded-full bg-ok-soft px-2 py-0.5 text-[11px] leading-none font-medium text-ok">
                Ready
            </span>
        );
    }

    if (status.state === 'error') {
        return (
            <span
                className="rounded-full bg-danger-soft px-2 py-0.5 text-[11px] leading-none font-medium text-danger"
                title={String(document.status ?? 'Processing failed')}
            >
                Error
            </span>
        );
    }

    if (status.state === 'pending_approval') {
        return (
            <span className="rounded-full bg-warn-soft px-2 py-0.5 text-[11px] leading-none font-medium text-warn">
                Pending approval
            </span>
        );
    }

    return (
        <span className="inline-flex min-w-0 flex-col gap-1">
            <span
                className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2 py-0.5 text-[11px] leading-none font-medium text-warn"
                title={String(document.status ?? 'Processing')}
            >
                <Loader2 size={10} className="animate-spin" />
                {status.label}
            </span>
            {showProgressBar ? (
                <span
                    className="block h-1 w-full overflow-hidden rounded-full bg-surface-sunken"
                    role="progressbar"
                    aria-valuenow={status.percent}
                    aria-valuemin={0}
                    aria-valuemax={100}
                >
                    <span
                        className="block h-full rounded-full bg-warn transition-[width] duration-500"
                        style={{ width: `${status.percent}%` }}
                    />
                </span>
            ) : null}
        </span>
    );
}

export function ClassificationBadge({
    classification,
    color,
}: {
    classification: string;
    color?: string;
}) {
    return (
        <span
            className={clsx(
                'rounded-full px-2 py-0.5 text-[11px] leading-none font-medium whitespace-nowrap',
                !color && 'bg-surface-2 text-text-2',
            )}
            style={color ? { backgroundColor: color, color: readableTextColor(color) } : undefined}
        >
            {classification}
        </span>
    );
}
