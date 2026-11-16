// RelatedSettingsLinks.tsx
// The governance state beside the switch it qualifies.
//
// Allow Personal Agents decides whether people may build agents; Govern Personal Agents,
// two categories away, decides which people. The classic page linked them with a "Govern"
// button that jumped tabs. This shows the related switch's current state under the control
// and links to it, so the answer is visible before anyone goes looking.

import { clsx } from 'clsx';
import { asBoolean, type AdminRelatedSetting } from '../../../lib/adminFields';

export function RelatedSettingsLinks({
    related,
    read,
    sectionOf,
    onNavigate,
}: {
    related: AdminRelatedSetting[];
    read: (key: string) => unknown;
    sectionOf: (key: string) => string | undefined;
    onNavigate: (sectionId: string) => void;
}) {
    if (!related.length) {
        return null;
    }
    return (
        <div role="group" aria-label="Related governance" className="mb-2 ml-14 flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {related.map((entry) => {
                const on = asBoolean(read(entry.key));
                const sectionId = sectionOf(entry.key);
                return (
                    <span key={entry.key} className="inline-flex items-center gap-1.5">
                        <span className="text-text-3">{entry.label}</span>
                        <span
                            className={clsx(
                                'rounded-full px-1.5 py-0.5 text-[11px] font-medium',
                                on ? 'bg-accent-soft text-accent' : 'bg-surface-2 text-text-3',
                            )}
                        >
                            {on ? 'On' : 'Off'}
                        </span>
                        {sectionId ? (
                            <button
                                type="button"
                                onClick={() => onNavigate(sectionId)}
                                aria-label={`Review ${entry.label}`}
                                className="text-accent hover:underline"
                            >
                                Review
                            </button>
                        ) : null}
                    </span>
                );
            })}
        </div>
    );
}
