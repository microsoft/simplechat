// PromptsSection.tsx
// Saved prompts, as a workbench rather than a list with a form above it.
//
// The section previously rendered its editor between the header and the search box, so editing
// a row part-way down the list moved the form to the top of the page and out of view. The
// layout now mirrors the documents explorer: a list beside a rendered preview, full width and
// full height, with writing done in a dialog.
//
// Personal scope uses the default (personal) adapter. Group scope passes a group adapter built
// from the workspace's `prompt_management` hint, so the same workbench serves both without a
// fork -- the M9B documentOperations pattern applied to prompts.

import { useMemo } from 'react';
import { PromptWorkbench } from '../../components/prompts/PromptWorkbench';
import { createGroupPromptWorkbench } from '../../lib/promptWorkbench';
import type { GroupWorkspaceContext } from '../../lib/workspaceContext';

export function PromptsSection() {
    return <PromptWorkbench />;
}

/**
 * The prompts workbench bound to a group workspace.
 *
 * The adapter is memoised on the workspace identity and its management hint so switching groups
 * rebuilds it -- and so a fresh hint (for example after a role change on reload) re-gates the
 * write affordances without the component being remounted.
 */
export function GroupPromptsSection({ context }: { context: GroupWorkspaceContext }) {
    const adapter = useMemo(
        () =>
            createGroupPromptWorkbench(
                { kind: 'group', id: context.scope.id, name: context.workspace.name },
                context.prompt_management,
            ),
        [context.scope.id, context.workspace.name, context.prompt_management],
    );
    return <PromptWorkbench adapter={adapter} />;
}
