// SettingsIndex.tsx
// The "On this page" index beside the Admin Settings cards.
//
// A category can hold twenty sections (Knowledge does), each with its own status. The
// index lists them with that status beside each name, so an administrator can see what is
// configured, what is off, and what still needs something without scrolling every card,
// and jump straight to the one they want. It follows the page's filters, marks the section
// currently in view, and is only drawn when there is width to spare for it.

import { useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import { clsx } from 'clsx';
import type { LucideIcon } from 'lucide-react';
import type { SectionStatus } from '../../lib/adminSections';
import { needsAttention, presentSectionStatus } from './sectionStatusPresentation';

export interface SettingsIndexEntry {
    sectionId: string;
    label: string;
    groupId: string;
    groupLabel: string;
    Icon: LucideIcon;
    status: SectionStatus;
}

interface IndexGroup {
    id: string;
    label: string;
    entries: SettingsIndexEntry[];
}

export function SettingsIndex({
    entries,
    grouped,
    scrollRoot,
    onJump,
    className,
}: {
    entries: SettingsIndexEntry[];
    /** Label entries by category, for views that span more than one. */
    grouped: boolean;
    /** The element the cards scroll inside, which decides what counts as in view. */
    scrollRoot: RefObject<HTMLElement>;
    onJump: (sectionId: string) => void;
    className?: string;
}) {
    const [current, setCurrent] = useState<string | null>(null);
    // A section chosen in the index stays current while the page scrolls to it, and until
    // the administrator scrolls themselves. Without this a section near the end -- which
    // cannot scroll all the way up -- would hand "current" back to the one above it.
    const pinnedRef = useRef<string | null>(null);

    // Only a change to which sections are listed needs the listeners rebuilt; a status
    // changing as a draft is edited does not move anything.
    const idsKey = entries.map((entry) => entry.sectionId).join('|');

    useEffect(() => {
        const root = scrollRoot.current;
        const order = idsKey ? idsKey.split('|') : [];
        pinnedRef.current = null;
        if (!root || !order.length) {
            return;
        }
        let frame = 0;
        const update = () => {
            frame = 0;
            if (pinnedRef.current) {
                return;
            }
            const bounds = root.getBoundingClientRect();
            const line = bounds.top + bounds.height * 0.3;
            const atBottom = root.scrollTop + root.clientHeight >= root.scrollHeight - 2;
            let next: string | null = null;
            for (const id of order) {
                const top = document.getElementById(id)?.getBoundingClientRect().top;
                if (top === undefined) {
                    continue;
                }
                // The last section whose top has passed the line is current. At the very
                // bottom, the last section showing at all is, since it can rise no further.
                if (top <= line || (atBottom && top < bounds.bottom)) {
                    next = id;
                }
            }
            setCurrent(next ?? order[0]);
        };
        const onScroll = () => {
            if (!frame) {
                frame = requestAnimationFrame(update);
            }
        };
        const release = () => {
            pinnedRef.current = null;
        };
        update();
        root.addEventListener('scroll', onScroll, { passive: true });
        root.addEventListener('wheel', release, { passive: true });
        root.addEventListener('touchstart', release, { passive: true });
        root.addEventListener('pointerdown', release);
        window.addEventListener('keydown', release);
        return () => {
            cancelAnimationFrame(frame);
            root.removeEventListener('scroll', onScroll);
            root.removeEventListener('wheel', release);
            root.removeEventListener('touchstart', release);
            root.removeEventListener('pointerdown', release);
            window.removeEventListener('keydown', release);
        };
    }, [idsKey, scrollRoot]);

    const groups = useMemo<IndexGroup[]>(() => {
        if (!grouped) {
            return [{ id: '', label: '', entries }];
        }
        const byId = new Map<string, IndexGroup>();
        const ordered: IndexGroup[] = [];
        for (const entry of entries) {
            let group = byId.get(entry.groupId);
            if (!group) {
                group = { id: entry.groupId, label: entry.groupLabel, entries: [] };
                byId.set(entry.groupId, group);
                ordered.push(group);
            }
            group.entries.push(entry);
        }
        return ordered;
    }, [entries, grouped]);

    const attention = entries.filter((entry) => needsAttention(entry.status)).length;

    return (
        <nav
            aria-label="On this page"
            className={clsx('sticky top-4 self-start', className)}
        >
            <div className="max-h-[calc(100dvh-15rem)] overflow-y-auto rounded-2xl border border-edge-strong bg-surface-2 p-3">
                <h2 className="px-2 text-sm font-semibold text-text-1">On this page</h2>
                <p className="px-2 pt-0.5 pb-2 text-xs text-text-3">
                    {entries.length} {entries.length === 1 ? 'section' : 'sections'}
                    {attention ? (
                        <span className="text-warn">
                            {' · '}
                            {attention} {attention === 1 ? 'needs' : 'need'} attention
                        </span>
                    ) : null}
                </p>

                {groups.map((group) => (
                    <div key={group.id || '__all'} className={clsx(grouped && 'pt-2')}>
                        {grouped ? (
                            <p className="px-2 pb-1 text-xs font-semibold text-text-2">{group.label}</p>
                        ) : null}
                        <ol className="space-y-0.5">
                            {group.entries.map((entry) => {
                                const active = current === entry.sectionId;
                                const presentation = presentSectionStatus(entry.status);
                                return (
                                    <li key={entry.sectionId}>
                                        <a
                                            href={`#${encodeURIComponent(entry.sectionId)}`}
                                            aria-current={active ? 'location' : undefined}
                                            onClick={(event) => {
                                                event.preventDefault();
                                                pinnedRef.current = entry.sectionId;
                                                setCurrent(entry.sectionId);
                                                onJump(entry.sectionId);
                                            }}
                                            className={clsx(
                                                'flex items-start gap-2 rounded-lg px-2 py-1.5 text-[0.8125rem] leading-snug transition-colors',
                                                active
                                                    ? 'bg-accent-soft font-medium text-accent'
                                                    : 'text-text-2 hover:bg-surface-sunken hover:text-text-1',
                                            )}
                                        >
                                            <entry.Icon size={14} aria-hidden="true" className="mt-0.5 shrink-0" />
                                            <span className="min-w-0 flex-1">{entry.label}</span>
                                            {presentation ? (
                                                <span
                                                    className={clsx('mt-0.5 shrink-0', presentation.toneClassName)}
                                                    title={presentation.label}
                                                >
                                                    <presentation.Icon size={13} aria-hidden="true" />
                                                    <span className="sr-only">{presentation.label}</span>
                                                </span>
                                            ) : null}
                                        </a>
                                    </li>
                                );
                            })}
                        </ol>
                    </div>
                ))}
            </div>
        </nav>
    );
}
