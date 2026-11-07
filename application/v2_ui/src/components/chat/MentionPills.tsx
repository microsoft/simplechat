// MentionPills.tsx
// The people and the AI target a shared-conversation message is addressed to, drawn as pills.
//
// Two places use them. Above the message box they are the chips the `@` menu adds, which can be
// removed before sending. On a sent message they replace the `@Name` text, the way a reply shows
// its quote above the text rather than inside it.
//
// Each kind has its own tint and icon, and the name itself is always drawn in the body text
// colour so it stays readable on every tint.

import { clsx } from 'clsx';
import { Bot, Cpu, Image as ImageIcon, User, X } from 'lucide-react';
import type { ComposerMention, InvocationTarget } from '../../lib/mentions';
import type { MessageMentionPill } from '../../lib/sharedMessage';

type PillKind = 'person' | 'self' | InvocationTarget['target_type'];

const PILL_TINT: Record<PillKind, string> = {
    person: 'bg-ok-soft ring-ok/30',
    self: 'bg-accent-soft ring-accent/40',
    agent: 'bg-warn-soft ring-warn/40',
    model: 'bg-info-soft ring-info/30',
    image: 'bg-surface-sunken ring-edge',
};

const ICON_TINT: Record<PillKind, string> = {
    person: 'text-ok',
    self: 'text-accent',
    agent: 'text-warn',
    model: 'text-info',
    image: 'text-text-3',
};

const KIND_LABEL: Record<PillKind, string> = {
    person: 'Person',
    self: 'You',
    agent: 'Agent',
    model: 'Model',
    image: 'Image',
};

function PillIcon({ kind, className }: { kind: PillKind; className?: string }) {
    const Icon = kind === 'agent' ? Bot : kind === 'model' ? Cpu : kind === 'image' ? ImageIcon : User;
    return <Icon size={11} aria-hidden="true" className={clsx('shrink-0', className)} />;
}

function pillKind(mention: { kind: string; target_type?: string; self?: boolean }): PillKind {
    if (mention.kind === 'ai') {
        const target = mention.target_type;
        return target === 'model' || target === 'image' ? target : 'agent';
    }
    return mention.self ? 'self' : 'person';
}

/** The pills on a sent message, above its text. */
export function MessageMentionPills({
    pills,
    onAccent = false,
}: {
    pills: MessageMentionPill[];
    /** Drawn on the reader's own accent-coloured bubble. */
    onAccent?: boolean;
}) {
    if (pills.length === 0) {
        return null;
    }
    return (
        <ul aria-label="Addressed to" className="mb-1.5 flex flex-wrap items-center gap-1" data-message-mentions="">
            {pills.map((pill) => {
                const kind = pillKind(pill);
                return (
                    <li key={pill.key}
                        title={kind === 'self' ? 'You were mentioned' : undefined}
                        data-mention-kind={kind}
                        className={clsx(
                            'inline-flex max-w-[14rem] items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset',
                            onAccent
                                ? 'bg-on-accent/10 text-on-accent ring-on-accent/30'
                                : clsx(PILL_TINT[kind], 'text-text-1'),
                        )}>
                        <PillIcon kind={kind} className={onAccent ? undefined : ICON_TINT[kind]} />
                        <span className="sr-only">{KIND_LABEL[kind]}: </span>
                        <span className="truncate">{pill.label}</span>
                    </li>
                );
            })}
        </ul>
    );
}

/** The chips above the message box, each removable before the message is sent. */
export function ComposerMentionChips({
    mentions,
    onRemove,
    disabled = false,
}: {
    mentions: ComposerMention[];
    onRemove: (mention: ComposerMention) => void;
    disabled?: boolean;
}) {
    if (mentions.length === 0) {
        return null;
    }
    return (
        <ul aria-label="Sending to" className="mb-1.5 flex flex-wrap items-center gap-1.5 px-1" data-composer-mentions="">
            {mentions.map((mention) => {
                const kind = pillKind(mention);
                return (
                    <li key={mention.key} data-mention-kind={kind}
                        className={clsx(
                            'inline-flex max-w-[16rem] items-center gap-1.5 rounded-full py-0.5 pl-2 pr-1 text-xs text-text-1 ring-1 ring-inset',
                            PILL_TINT[kind],
                        )}>
                        <PillIcon kind={kind} className={ICON_TINT[kind]} />
                        <span className="sr-only">{KIND_LABEL[kind]}: </span>
                        <span className="truncate">{mention.display_name}</span>
                        <button type="button" disabled={disabled} onClick={() => onRemove(mention)}
                            aria-label={`Remove ${mention.display_name}`}
                            className="shrink-0 rounded-full p-0.5 text-text-3 hover:bg-surface-2 hover:text-text-1 disabled:opacity-50">
                            <X size={11} />
                        </button>
                    </li>
                );
            })}
        </ul>
    );
}
