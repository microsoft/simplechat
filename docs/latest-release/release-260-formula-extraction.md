---
layout: latest-release-feature
title: Mathematical Formulas Captured as LaTeX
description: Equations in PDFs and images can be captured as LaTeX instead of being approximated as ordinary OCR text.
section: Latest Release
generated_from_catalog: true
---

Current release version for Mathematical Formulas Captured as LaTeX: **0.261.001**

When your admin enables the Extract mathematical formulas option, equations are captured as LaTeX during processing. This is a billed Document Intelligence add-on, so it is off by default and has to be turned on deliberately. It applies to the Layout model only, which means it has no effect while extraction is set to Standard.

## Why It Matters

This matters because an equation flattened into plain OCR text is usually wrong in a way that is easy to miss and hard to correct later.

## How to Try It

1. Ask your admin whether formula extraction is enabled for your environment.
2. Upload a PDF or image that contains mathematical equations.
3. Expand the document row once processing finishes and confirm Extraction reads Enhanced rather than Standard.
4. Open Chat and ground a question on that document.
5. Ask about a specific equation.
6. Confirm the answer reproduces the real expression as LaTeX instead of garbled inline text.
7. Open the citation to read the captured LaTeX in the source passage.

## Where to Find It

- **Open Personal Workspace** &mdash; Upload a document with equations and review the extracted formulas.
