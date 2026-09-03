// PromptsSection.tsx
// Saved prompts, as a workbench rather than a list with a form above it.
//
// The section previously rendered its editor between the header and the search box, so editing
// a row part-way down the list moved the form to the top of the page and out of view. The
// layout now mirrors the documents explorer: a list beside a rendered preview, full width and
// full height, with writing done in a dialog.

import { PromptWorkbench } from '../../components/prompts/PromptWorkbench';

export function PromptsSection() {
    return <PromptWorkbench />;
}
