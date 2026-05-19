# Document Analysis Lossless Artifacts

## Overview

Version: 0.241.040

Fixed/Implemented in version: **0.241.040**

Related config.py update: `application/single_app/config.py` now sets `VERSION = "0.241.040"`.

This enhancement changes exhaustive document analysis requests so successful window-level work is retained and packaged into durable artifacts. When users ask to list, find, extract, inventory, or make a table from selected documents, SimpleChat now keeps raw analysis notes and prepares structured CSV plus Markdown analysis artifacts instead of relying only on the reduced final answer.

Dependencies: `functions_document_analysis.py`, `functions_workflow_runner.py`, generated chat artifacts, and existing document action workflow execution.

## Technical Specifications

Architecture overview:
The document analysis service now classifies exhaustive/table-style requests with deterministic guardrails and returns `analysis_intent`, `raw_analysis_items`, and `document_analysis_items` alongside the final reduced answer and coverage metadata.

Artifact generation:
The workflow runner uses the returned intent metadata to create lossless artifacts for exhaustive outputs:

- CSV artifact: extracted JSON rows or Markdown table rows from retained raw/window outputs, with source document and window metadata appended.
- Markdown artifact: final analysis, coverage summary, and retained raw window-level or document-level analysis notes.
- JSON artifact: preserved when the final analysis is valid JSON.

Reduction behavior:
Reduction still produces a readable analytical summary, but it is no longer the only surviving output for extraction/table requests. The retained artifacts become the audit trail for the work already performed.

Configuration:
No new administrator setting is required. The version was bumped in `application/single_app/config.py` for traceability.

## Usage Instructions

User workflow:
Select documents and ask an exhaustive analysis question such as:

- "List all vendors and services being performed."
- "Make a table of every entity and amount."
- "Extract all contract risks into rows."

Expected output:
The assistant response includes a concise summary and preview, while the chat receives generated artifacts containing the full structured rows and the full Markdown analysis/raw notes.

## Testing And Validation

Functional coverage:
`functional_tests/test_document_analysis_lossless_artifacts.py` verifies that exhaustive table prompts preserve raw window outputs, produce structured CSV rows from retained Markdown tables, render a Markdown artifact with raw notes, and keep version alignment with `config.py`.

Performance considerations:
Retained raw analysis is already produced during normal window processing, so this feature avoids extra document reads. Artifact size remains bounded by the existing generated chat artifact size limit.

Known limitations:
CSV extraction is schema-agnostic. It can parse JSON arrays/objects and Markdown tables from model outputs, but if a window returns only prose, that prose is retained as an `analysis_note` row instead of being force-shaped into a domain-specific schema.
