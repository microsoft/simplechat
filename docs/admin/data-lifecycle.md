---
layout: page
title: "Data Lifecycle settings"
description: "Data Lifecycle groups retention, classification, and conversation archiving decisions."
section: "Administration"
audience: admin
admin_tab: data-lifecycle
---


# Data Lifecycle settings

## What this group controls

Data Lifecycle groups retention, classification, and conversation archiving decisions.

## Why it matters

Lifecycle choices shape compliance and recovery expectations. Retention and archiving preserve evidence, while classification helps users and reviewers understand document sensitivity.

{% include media.html src="admin/data-lifecycle-overview.png" alt="Screenshot placeholder for the Data Lifecycle group in Admin Settings." title="Data Lifecycle settings" capture="Capture the Data Lifecycle group in Admin Settings showing its tabs." %}

{% include media.html type="video" title="Data Lifecycle settings walkthrough" poster="video-posters/admin-data-lifecycle.png" capture="Recording planned. Walk through each tab in the Data Lifecycle group and explain when to change each setting." %}

## Before you change anything

- Confirm retention requirements for every workspace scope.
- Agree on classification labels before enabling classification.
- Decide whether deleted conversations should be recoverable.

## Retention {#retention}

### Retention Policy {#retention-policy-section}

The Retention Policy section belongs to the Retention tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable for Personal Workspaces | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_retention_policy_personal`; capability toggle |
| Enable for Group Workspaces | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_retention_policy_group`; capability toggle |
| Enable for Public Workspaces | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_retention_policy_public`; capability toggle |
| Conversation Retention | Defines behavior for the related admin workflow; verify the affected feature after saving. | none | `default_retention_conversation_personal` |
| Document Retention | Defines behavior for the related admin workflow; verify the affected feature after saving. | none | `default_retention_document_personal` |
| Conversation Retention | Defines behavior for the related admin workflow; verify the affected feature after saving. | none | `default_retention_conversation_group` |
| Document Retention | Defines behavior for the related admin workflow; verify the affected feature after saving. | none | `default_retention_document_group` |
| Conversation Retention | Defines behavior for the related admin workflow; verify the affected feature after saving. | none | `default_retention_conversation_public` |
| Document Retention | Defines behavior for the related admin workflow; verify the affected feature after saving. | none | `default_retention_document_public` |
| Scheduled Execution Time (Hour of Day) | Retention policy will run once daily at this hour (UTC timezone). | 2 | `retention_policy_execution_hour` |

## Classification {#classification}

### Document Classification {#document-classification-section}

The Document Classification section belongs to the Classification tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Document Classification | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_document_classification`; capability toggle |

## Archiving {#archiving}

### Conversation Archiving {#conversation-archiving-section}

The Conversation Archiving section belongs to the Archiving tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Conversation Archiving | Changes conversation deletion behavior to archive conversations instead of permanently deleting them immediately. | Off | `enable_conversation_archiving`; capability toggle |

## Common tasks

1. **Apply retention policy.** Enable retention for intended scopes and check a test item after the policy job runs. Outcome to verify: Items follow the configured retention window.
2. **Classify documents.** Enable classification and upload a representative file. Outcome to verify: The document carries expected classification metadata.
3. **Archive conversations.** Enable archiving and delete a test conversation. Outcome to verify: Deletion follows the archive path.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Deleted conversations disappear permanently | Archiving was not enabled when deletion occurred. | Enable archiving before relying on recovery for future deletions. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Backup & Recovery settings]({{ '/admin/backup-recovery/' | relative_url }})
- [Governance settings]({{ '/admin/governance/' | relative_url }})
