// GeneratedFileIcon.tsx
// The tile that opens a generated file's card: a glance says Word, Excel, PowerPoint or PDF
// before the name is read. Colour only repeats what the glyph and the card's type label
// already say, so nothing here is conveyed by colour alone.

import { clsx } from 'clsx';
import {
    Braces, File, FileCode2, FileSpreadsheet, FileText, FileType2, Presentation, type LucideIcon,
} from 'lucide-react';

interface FileIcon {
    icon: LucideIcon;
    tone: string;
}

const DOCUMENT: FileIcon = { icon: FileText, tone: 'bg-accent-soft text-accent' };
const SHEET: FileIcon = { icon: FileSpreadsheet, tone: 'bg-ok-soft text-ok' };
const DATA: FileIcon = { icon: Braces, tone: 'bg-info-soft text-info' };
const PLAIN: FileIcon = { icon: FileType2, tone: 'bg-surface-3 text-text-2' };
const UNKNOWN: FileIcon = { icon: File, tone: 'bg-surface-3 text-text-2' };

const FILE_ICONS: Readonly<Record<string, FileIcon>> = {
    csv: SHEET,
    docx: DOCUMENT,
    json: DATA,
    md: PLAIN,
    pdf: { icon: FileText, tone: 'bg-danger-soft text-danger' },
    pptx: { icon: Presentation, tone: 'bg-warn-soft text-warn' },
    txt: PLAIN,
    xlsx: SHEET,
    xml: { icon: FileCode2, tone: 'bg-info-soft text-info' },
    yaml: DATA,
    yml: DATA,
};

export function GeneratedFileIcon({ format, className }: { format: string; className?: string }) {
    const key = format.trim().replace(/^\./, '').toLowerCase();
    const known = Object.hasOwn(FILE_ICONS, key);
    const { icon: Icon, tone } = known ? FILE_ICONS[key] : UNKNOWN;
    return (
        <span aria-hidden="true" data-file-icon={known ? key : 'file'}
            className={clsx('flex h-10 w-10 shrink-0 items-center justify-center rounded-lg', tone, className)}>
            <Icon size={20} strokeWidth={1.75} />
        </span>
    );
}
