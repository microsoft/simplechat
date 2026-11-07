// AdminMarkdown.tsx
// Markdown preview for administrator-authored content.
//
// The renderer moved to components/ui/PlainMarkdown.tsx when the prompts workbench needed the
// same one: a saved prompt and a landing page are both authored markdown, and both want a
// renderer that does not parse citations or apply masking. This file stays so the admin
// settings call sites keep their own name for it.

export { PlainMarkdown as AdminMarkdown } from '../ui/PlainMarkdown';
export type { MarkdownSize } from '../ui/PlainMarkdown';
