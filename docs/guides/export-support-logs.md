---
layout: page
title: "Export diagnostic logs for support"
description: "Build a scoped, privacy-reviewed support ZIP without granting admins unrestricted access to personal conversations."
section: "Guides"
audience: admin
version: "0.261.428"
---

## What this does

Implemented in version **0.261.428**, the **Support Log Export** tool collects
retained application evidence into one ZIP for manual sharing with support.
Use it for a reproducible chat, orchestration, upload or infrastructure issue.
It does not enable logging, retrieve expired data or send the file anywhere.

## Prepare the sources

Open **Admin Settings > Operations > Logging & Health > Support Log Export**.
Under **Source and storage setup**, choose Commercial or US Government and
enter the Application Insights resource ID. Add the App Service resource ID
only when its console logs already go to Azure Monitor.

The application identity needs resource monitoring read access. The connected
workspace must allow resource permissions, or its administrator must grant the
additional workspace/table access required by that workspace's access mode.
An ingestion connection string is not a query credential.

Initialize the private export container using the existing application Blob
storage configuration, then select **Test source access**. The app does not
grant roles, change diagnostic settings or create an Azure account. A normal
background runner or dedicated SimpleChat scheduler must process queued work.

## Isolate the incident

Select one registered user, or explicitly choose **All users** for a
deployment-wide problem. For one user, search conversation IDs and select
the relevant entries. The picker deliberately omits private titles/messages.

Choose **Time-based** for a known incident range. Choose **Conversation
windows** to expand recorded activity by the before/after margins, initially
15 minutes each. Long-lived conversations can be narrowed to an explicit
range. Separate windows do not collect the unrelated gap between them.

Times are entered in the displayed browser timezone and reviewed in UTC.
Invalid or repeated daylight-saving endpoints are rejected; choose
unambiguous endpoints spanning the clock change, or use explicit timezone
offsets through the documented API.

Select the retained log sources. Explicitly deselect unavailable sources rather
than interpreting their absence as evidence of no failure. Nearby system
context can help with infrastructure errors, but historical untagged records
may include unrelated activity. One-user console collection requires this
option.

## Choose privacy and transcript scope

Deterministic credential/PII redaction is the default. The optional AI privacy
pass sends only already-scrubbed data to the configured default text model and
must finish the complete inspection within its budget. It is not a guarantee
of anonymity. A failed or oversized AI check never silently becomes a
deterministic-only result.

Leave transcripts off unless the issue needs message text. To include them,
select personal conversations and request owner approval. Approval covers
whole text snapshots through the review cutoff, not just the log time window.
Shared/group conversations remain logs-only.

The owner reviews the requesting administrator, purpose, exact conversations,
cutoff, expiry, privacy mode and model where applicable, then previews and
approves or declines. An administrator cannot approve another person's data.
The owner can revoke future release; already downloaded copies or submitted
AI inputs cannot be recalled.

## Review, generate and download

Select **Review export scope** and inspect the server-resolved UTC windows,
users, sources, privacy choice and transcript requirement. Acknowledge the
limitations, then select **Generate support ZIP**. This does not save unrelated
admin settings.

Follow the status under **Your support exports**. A transcript request waits
for its owner; a declined or expired request needs an explicit logs-only
alternative or a new request. Errors and incomplete source results block a
completed download.

When ready, open **Review redacted preview**. Acknowledge that you will check
the complete ZIP for residual sensitive data, then download it. Only the
requesting administrator can download, and availability lasts at most
24 hours. Inspect `manifest.json` for exact windows, coverage, exclusions,
expiry and checksums; use `logs/diagnostics.txt` for a readable timeline.

Share only through the organization's approved support channel. ZIP expiry
does not delete copies already downloaded.

## Limits and recovery

Each request is bounded to seven days, 20 conversations, 100,000 records and
50 MiB of uncompressed archive contents. The AI pass has a conservative
200,000-input-token budget and the model's own context limit. Narrow the scope
or explicitly choose deterministic-only processing when necessary.

If a request stays queued, check the normal background runner or dedicated
scheduler. If source access fails, verify resource IDs, cloud, workspace
access mode and the identity's monitoring permissions. Missing console logs
require an existing Azure collection configuration; the tool cannot recover
earlier stdout that was never retained.

For a reproducible issue, enable the existing timed debug logging option,
reproduce the problem, and collect that later interval. Do not expect turning
debug on now to add evidence to an earlier incident.

## Related

- [Operations settings]({{ '/admin/operations/' | relative_url }})
- [Review approval requests]({{ '/guides/review-approval-requests/' | relative_url }})
- [Diagnostic support export feature]({{ '/features/admin-support-exports/' | relative_url }})
