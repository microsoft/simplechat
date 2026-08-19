---
layout: page
title: "Citations Settings"
description: "Controls enhanced citation storage, tabular previews, and large tabular run safeguards."
section: "Administration"
audience: admin
admin_tab: citation
---

## What this tab controls

Controls enhanced citation storage, tabular previews, and large tabular run safeguards.

## Why it matters

Enhanced citations let users open or preview the original source behind an answer, which improves trust and auditability. They require storage for source documents and can add memory pressure when previewing large tabular files. Large tabular confirmations prevent users from accidentally starting expensive row-level runs.

{% include media.html src="admin/citation-overview.png" alt="Screenshot of the Citations settings tab showing citations tab." title="Citations tab" capture="Capture the Citations tab for Citations tab. Show relevant controls and redact secrets." %}

{% include media.html type="video" title="Citations settings walkthrough" poster="video-posters/admin-citation.png" capture="Recording planned. Walk through every setting on the Citations tab and explain when to change each one." %}

## Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Enhanced Citations | Preserves source files for richer citation preview and source-document access in chat answers. | Off | `enable_enhanced_citations`; capability toggle |
| Storage Account Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `office_docs_authentication_type` |
| Storage Account Connection String | Controls how SimpleChat uses storage account connection string on this tab. | Empty | `office_docs_storage_account_url` |
| Storage Account Blob Service Endpoint | Points SimpleChat to the storage account blob service endpoint used by this feature. | Empty | `office_docs_storage_account_blob_endpoint` |
| Maximum File Size for Tabular Preview (MB) | Maximum blob size (in MB) allowed for tabular file previews (CSV, XLSX). Files larger than this will not be previewed. Increase for larger files if your compute has sufficient memory, or decrease to protect smaller insta | 200 | `tabular_preview_max_blob_size_mb` |
| Confirm very large row-level runs before starting | When a prompt includes an explicit large row count, users are asked to continue or narrow scope before the run starts. | On | `enable_tabular_durable_run_confirmation`; capability toggle |
| Confirmation Row Threshold | Caps or schedules confirmation row threshold so the feature stays within expected capacity. | 500 | `tabular_durable_run_confirmation_threshold_rows` |
| Confirmation Batch Threshold | Caps or schedules confirmation batch threshold so the feature stays within expected capacity. | 75 | `tabular_durable_run_confirmation_threshold_batches` |
| Chunk Processing Model | Chooses the model or deployment SimpleChat uses for chunk processing model. | current | `tabular_generated_output_chunk_model_mode` |
| Configured Chunk Model Deployment | Chooses the model or deployment SimpleChat uses for configured chunk model deployment. | Empty | `tabular_generated_output_chunk_model_deployment` |

### Enhanced citations

Enhanced citations store original files so answer citations can open richer previews or source references. Configure storage before enabling the switch; existing documents may need upload or reprocessing before enhanced previews appear.

### Large tabular run controls

Tabular preview and confirmation settings protect memory and compute when users work with CSV or Excel files. Increase preview size or confirmation thresholds only when the app instance and model budget can support larger runs.

## Before you change anything

- Provision storage for source files before enabling Enhanced Citations.
- Choose connection string or managed identity authentication and grant storage access before testing.
- Review memory capacity before increasing the tabular preview size.

## Common tasks

1. **Enable enhanced citations.**
    1. Enable **Enable Enhanced Citations**.
    2. Choose **Storage Account Authentication Type**.
    3. Enter the connection string or blob service endpoint.
    4. Save and upload or reprocess a document.
    Outcome to verify: Answer citations can open richer source previews.

{% include media.html src="admin/citation-enable-enhanced-citations.png" alt="Screenshot of the Citations settings tab showing enable enhanced citations." title="Citations: Enable enhanced citations" capture="Capture the Citations tab while performing Enable enhanced citations. Show the relevant controls and redact secrets." %}

2. **Tune tabular preview size.**
    1. Review **Maximum File Size for Tabular Preview**.
    2. Increase only when the app has enough memory for larger CSV or Excel previews.
    3. Save and preview a representative tabular file.
    Outcome to verify: Large files preview only up to the configured limit.

{% include media.html src="admin/citation-tune-tabular-preview-size.png" alt="Screenshot of the Citations settings tab showing tune tabular preview size." title="Citations: Tune tabular preview size" capture="Capture the Citations tab while performing Tune tabular preview size. Show the relevant controls and redact secrets." %}

3. **Require confirmation for large tabular runs.**
    1. Enable **Confirm very large row-level runs before starting**.
    2. Set **Confirmation Row Threshold** and **Confirmation Batch Threshold**.
    3. Choose the chunk-processing model mode if needed.
    4. Run a prompt that exceeds the threshold.
    Outcome to verify: Users must confirm large row-level work before it starts.

{% include media.html src="admin/citation-require-confirmation-for-large-tabular-runs.png" alt="Screenshot of the Citations settings tab showing require confirmation for large tabular runs." title="Citations: Require confirmation for large tabular runs" capture="Capture the Citations tab while performing Require confirmation for large tabular runs. Show the relevant controls and redact secrets." %}

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Enhanced citation previews do not open | Enhanced citations are off or source storage is not configured. | Enable enhanced citations and configure storage authentication. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Search and Extract]({{ '/admin/search-extract/' | relative_url }})
- [Latest Features New]({{ '/admin/latest-features/' | relative_url }})
