// DocumentsSection.tsx
// Hosts the documents explorer inside the personal workspace.
//
// Thin on purpose: the explorer owns its own command bar, rail, status bar and internal
// scrolling, so the only thing left for this section is the sentence explaining where these
// files can come from.

import { FolderSync } from 'lucide-react';
import { Link } from 'react-router-dom';
import { DocumentExplorer } from '../../components/documents/DocumentExplorer';

export function DocumentsSection({ syncEnabled }: { syncEnabled: boolean }) {
    return (
        <div className="flex h-full min-h-0 flex-col gap-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div className="min-w-0">
                    <h2 className="text-base font-semibold text-text-1">Documents</h2>
                    <p className="mt-0.5 text-sm text-text-3">
                        Files you upload here are indexed and can be cited in chat. Everything
                        in this section is private to you.
                    </p>
                </div>

                {syncEnabled ? (
                    <p className="text-xs text-text-3">
                        Documents can also arrive automatically from a{' '}
                        <Link to="/workspace/sync" className="text-accent hover:underline">
                            file source
                        </Link>
                        .
                    </p>
                ) : (
                    <p className="flex items-center gap-1.5 text-xs text-text-3">
                        <FolderSync size={13} />
                        File sync is not enabled for your account, so documents can only be
                        added by uploading them.
                    </p>
                )}
            </div>

            <div className="min-h-0 flex-1">
                <DocumentExplorer />
            </div>
        </div>
    );
}
