// FileSourcesSection.tsx
// Personal file sources use the same native editor as shared workspaces.

import { PERSONAL_FILE_SOURCE_WORKBENCH } from '../../lib/fileSourceWorkbench';
import { FileSourcesWorkbenchSection } from './GroupFileSourcesSection';

export { sourceTypeLabel } from '../../lib/fileSourceFields';

export function FileSourcesSection() {
    return (
        <FileSourcesWorkbenchSection
            adapter={PERSONAL_FILE_SOURCE_WORKBENCH}
            scopeNoun="workspace"
        />
    );
}
