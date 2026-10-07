// DataManagementGuides.tsx
// The Backup & Recovery guides: setup, backup, migration, restore and RU Boost.

import type { ReactNode } from 'react';
import { GlassButton } from '../../ui/primitives';
import { Modal } from '../../ui/Modal';
import { DmNotice } from './DmShared';

export type GuideId = 'setup' | 'backup' | 'migration' | 'restore' | 'ru-boost';

export const GUIDE_TITLES: Record<GuideId, string> = {
    setup: 'Set up Backup & Recovery',
    backup: 'How backups work',
    migration: 'How migration works',
    restore: 'How restore works',
    'ru-boost': 'RU Boost permissions',
};

const OPERATIONAL_WARNING =
    'We suggest not running backups, restores, or migrations during your operational business hours. These jobs run inside the App Service environment and can affect application performance.';

interface GuideSection {
    title: string;
    items: ReactNode[];
}

const GUIDE_CONTENT: Record<GuideId, { intro: string; sections: GuideSection[] }> = {
    setup: {
        intro: 'Use this order before an incident or cutover window. Prove backup first, then make restore or migration decisions from completed backup evidence.',
        sections: [
            {
                title: 'Readiness order',
                items: [
                    'Use backup storage that is dedicated to backup artifacts and separate from Enhanced Citation source files.',
                    'Generate the backup encryption key and protect it; Key Vault is the safer production storage location.',
                    'Queue a manual full backup and inspect the Backup Inventory record before depending on scheduled backups.',
                ],
            },
            {
                title: 'Before restore or migration',
                items: [
                    'For migration, configure destination Cosmos DB, AI Search, and storage before selecting scope.',
                    'For restore, start from Backup Inventory and stage the selected backup through the restore workflow.',
                ],
            },
        ],
    },
    backup: {
        intro: 'Backups write durable artifacts and job records that restore and migration workflows can inspect later. Full backups capture a complete selected snapshot; partial backups capture daily changes between full backups.',
        sections: [
            {
                title: 'Storage and encryption',
                items: [
                    'Use a dedicated backup account and container so restore and migration artifacts never overwrite source documents.',
                    'Keep backup encryption enabled for production and store generated keys in Key Vault when available.',
                ],
            },
            {
                title: 'Scope and timing',
                items: [
                    'Leave Cosmos DB and AI Search enabled unless you intentionally need a limited backup.',
                    'Queue large backups outside business hours because App Service workers perform the work.',
                ],
            },
        ],
    },
    migration: {
        intro: 'Migration moves selected SimpleChat users, groups, public workspaces, and optional documents to another SimpleChat environment.',
        sections: [
            {
                title: 'Run modes',
                items: [
                    <>
                        <strong>Copy missing items only:</strong> safest for a first run because existing
                        destination records are not changed.
                    </>,
                    <>
                        <strong>Catch up changed items:</strong> use after a completed migration to copy new
                        items and update migration-owned changes.
                    </>,
                    <>
                        <strong>Make destination match source:</strong> use only during cutover when migrated
                        destination-only items should be removed.
                    </>,
                ],
            },
            {
                title: 'Search coordination',
                items: [
                    'Freeze external destination writers before moving AI Search documents because SimpleChat cannot coordinate writers outside the app.',
                ],
            },
        ],
    },
    restore: {
        intro: 'Restore starts from Backup Inventory. A review checks the selected backup and the destination before a restore can be queued, and shows what each surface would restore.',
        sections: [
            {
                title: 'Choose evidence',
                items: [
                    'Prefer full backups for restore decisions because partial backups depend on earlier backup history.',
                    'Confirm the encryption key is still available before relying on encrypted artifacts.',
                ],
            },
            {
                title: 'Run safely',
                items: [
                    'Review warnings and missing surfaces before restoring AI Search or source document blobs.',
                    'Run restore only in a maintenance window because restored records can affect live users and search results.',
                ],
            },
        ],
    },
    'ru-boost': {
        intro: 'RU Boost temporarily raises eligible Cosmos DB throughput up to 10,000 RU/s for approved backup or migration windows, then restores the original capacity.',
        sections: [
            {
                title: 'Cost and recovery behavior',
                items: [
                    'Raising throughput can increase Azure charges while the boost is active.',
                    'The original capacity is restored after completion, failure, cancellation, or recovery.',
                ],
            },
            {
                title: 'Permission checks',
                items: [
                    'Data copy permissions prove the identity can create, read, and delete probe records in destination Cosmos containers.',
                    'RU Boost permissions prove the identity can read and write Cosmos throughput settings through Azure Resource Manager.',
                    'Management-plane permission is needed separately from data access.',
                    'Destination RU Boost also needs the destination subscription ID and resource group because those values are not part of the data-plane endpoint.',
                ],
            },
        ],
    },
};

/** One guide in a dialog. */
export function DataManagementGuideDialog({ guide, onClose }: { guide: GuideId; onClose: () => void }) {
    const content = GUIDE_CONTENT[guide];
    return (
        <Modal
            title={GUIDE_TITLES[guide]}
            description="Backup & Recovery operational guide"
            size="lg"
            onClose={onClose}
            footer={
                <GlassButton type="button" variant="primary" onClick={onClose}>
                    Close
                </GlassButton>
            }
        >
            <div className="space-y-4">
                <p className="max-w-[72ch] text-sm leading-relaxed text-text-2">{content.intro}</p>
                <DmNotice tone="warning" title="Operational window">
                    {OPERATIONAL_WARNING}
                </DmNotice>
                {content.sections.map((section) => (
                    <section
                        key={section.title}
                        aria-labelledby={`dm-guide-${guide}-${section.title.replace(/\s+/g, '-').toLowerCase()}`}
                    >
                        <h3
                            id={`dm-guide-${guide}-${section.title.replace(/\s+/g, '-').toLowerCase()}`}
                            className="text-sm font-semibold text-text-1"
                        >
                            {section.title}
                        </h3>
                        <ul className="mt-2 space-y-2 text-sm leading-relaxed text-text-2">
                            {section.items.map((item, index) => (
                                <li key={index} className="flex gap-2">
                                    <span
                                        aria-hidden="true"
                                        className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-accent"
                                    />
                                    <span className="min-w-0">{item}</span>
                                </li>
                            ))}
                        </ul>
                    </section>
                ))}
            </div>
        </Modal>
    );
}
