---
layout: page
title: "Azure Files Search"
description: "Reference for the Azure Files Search SimpleChat action."
section: "Reference"
audience: admin
---

<!-- action-slug: azure-files-index -->

{% include media.html src="reference/actions-azure-files-index-configuration.png" alt="The Azure Files Search configuration showing the search endpoint, index name, index layout, permission mode, and storage share list." title="Azure Files Search action configuration" capture="Capture the Azure Files Search global action editor with the search index, file permissions, and limits sections visible. Redact keys, subscription IDs, and user identifiers." %}

## What this action does

Azure Files Search lets agents search an Azure AI Search index that a customer already built from Azure file shares with the [Azure Files indexer](https://learn.microsoft.com/azure/search/search-file-storage-integration). SimpleChat does not copy or re-index the files.

The index holds file text and paths but no permissions. Azure AI Search can't import Azure Files ACLs. So for every candidate result, SimpleChat reads the file's NTFS permissions from Azure Files and checks them, together with the share's permissions, against the signed-in user. Only results from files the user is proven able to open reach the agent.

## Why and when to use it

Use it when file shares are already indexed in Azure AI Search and you want agents to answer from that content without a second ingestion pipeline, while still respecting who can open each file.

Use [File Sync]({{ '/guides/create-a-file-sync/' | relative_url }}) instead when the files should become SimpleChat workspace documents. Synced documents follow workspace membership, not the share's file permissions.

## Before you start

- **Who can create it:** only administrators, as a global action. Users reach it through the agents it is assigned to, including orchestration. It can't be created as a personal or group action.
- **The index:** an Azure AI Search index built by the Azure Files indexer. It needs the field that holds each file's URL, `metadata_storage_path` by default.
- **Roles for SimpleChat's managed identity:**
  - **Search Index Data Reader** on the search service. Role-based access must be enabled on the service. You can use a query key instead.
  - **Storage File Data Privileged Reader** on each storage account or share, to read file permissions.
  - **Reader** on each storage account, to check share-level permissions.

  The deployers can grant these on existing resources. See the deployer READMEs for `azureFilesStorageAccountResourceIds` and `externalSearchServiceResourceIds`.
- **User sign-in:** SimpleChat reads the user's group memberships from Microsoft Graph with the user's own delegated token. A run with no signed-in user returns no results.

## How permissions are checked

For each file in the search results, SimpleChat:

1. Confirms the file's storage account and share are on the action's share list.
2. Checks share-level access: the storage account's default share-level permission, then the user's Azure role assignments on the share, including assignments through groups.
3. Reads the file's security descriptor from Azure Files and evaluates its DACL in order, the way Windows does, for permission to read the file's data.

The user's identity comes from Microsoft Graph: the user's and their groups' security identifiers (`securityIdentifier`, `onPremisesSecurityIdentifier`, and the SID derived from each Entra object ID). Everyone, Authenticated Users, and Network apply to every signed-in user.

Each file ends in one of three outcomes:

| Outcome | Meaning | Shown to the user? |
| --- | --- | --- |
| Allowed | The ACL grants the user read access and the share admits them. | Yes |
| Denied | The ACL denies the user, grants only principals the user isn't, or the share doesn't admit them. | No |
| Unverified | SimpleChat couldn't prove the answer. For example, the ACL names an Active Directory group that isn't synced to Entra ID, the file no longer exists, a permission read failed, or time ran out. | No |

Users are never told that results were withheld. Denied and unverified files are recorded for administrators.

## Configuration

### Search index

- **Search endpoint and index name:** the customer's Azure AI Search service and index. SimpleChat's own workspace indexes can't be used.
- **Index layout:**
  - **One document per file** matches the indexer's default index. Snippets come from semantic captions or highlights.
  - **Chunked** matches integrated vectorization with index projections (`chunk`, `title`, `text_vector`, and `metadata_storage_path` projected to each chunk).
  - **Custom** lets you map every field.
- **Query mode:**
  - **Keyword:** full-text search.
  - **Semantic:** needs a semantic configuration.
  - **Hybrid:** needs a vector field whose index defines a vectorizer.

### File permissions

- **Permission mode:** **Check file permissions** is the default and recommended. **Off** returns every matching file to everyone who can use the action, and requires an acknowledgment.
- **File shares:** the storage account resource IDs and share names the index was built from. Results from any other share are withheld as unverified.
- **Share-level check:** **Check share access** uses the default share-level permission and Azure role assignments. **Skip** relies on file permissions only. Choose Skip only when every user reaches the share through a default share-level permission or another path you manage.
- **Treat BUILTIN\Users as every signed-in user:** off by default, so entries for that group leave a file unverified. Turn it on only if your shares grant domain users access through BUILTIN\Users.

### Limits

Default results (1-20), candidates examined per search (5-200), snippet length (200-4,000 characters), and the time allowed for permission checks (5-60 seconds). Files not checked in time are withheld as unverified.

## Connection test

The connection test runs as you, the administrator, and reports each check:

- Search access.
- Whether the index's file paths are Azure Files URLs.
- The query mode.
- Your directory groups.
- Share-level permissions and file permissions for each listed share.

Failures name the role or setting to fix.

## What administrators see

- **Activity logs:** each search that withheld files writes an `azure_files_search_access` entry. It records counts, reason codes such as `acl_no_allow`, `acl_explicit_deny`, `sid_unresolved`, `share_access_denied`, `file_not_found`, and `time_budget_exceeded`, and up to 25 withheld file paths with any unresolved SIDs. It never contains file content or the user's question. Filter for **Azure Files Search Access** in Control Center.
- **Notifications:** when results couldn't be verified, administrators get one notification per action per day.
- **Telemetry:** every search writes an `[AZURE_FILES_SEARCH]` event to Application Insights with the same counts, for trend queries.

## Limitations

- Evaluation follows Windows rules, but it can't see Active Directory groups that aren't synced to Entra ID or memberships that exist only in Active Directory. Those files are withheld as unverified rather than shown.
- Built-in administrator, system, and service accounts are never treated as the signed-in user.
- Conditional ACEs, object ACEs, and rights granted only through generic bits leave a file unverified.
- The search index can lag behind the share. Deleted files are withheld as unverified and logged as `file_not_found`.
- Results are cited by file name and network path (`\\account.file.core.windows.net\share\...`). Users open them with their own share access.

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
- [Document-level access control in Azure AI Search](https://learn.microsoft.com/azure/search/search-document-level-access-overview)
