---
layout: page
title: "Data Lifecycle settings"
description: "Data Lifecycle decides how long conversations and documents are kept, which labels a document can carry, and whether a deleted conversation can still be reviewed."
section: "Administration"
audience: admin
admin_tab: data-lifecycle
---


# Data Lifecycle settings

## What this group controls

Data Lifecycle decides three things about the data people create in SimpleChat:

- **Retention**: how long conversations and documents are kept before they are deleted
  automatically, set separately for personal, group and public workspaces.
- **Classification**: the labels a document can carry, such as *Confidential* or *Public*.
- **Archiving**: whether a deleted conversation is gone or kept for review.

## Why it matters

Retention is the only part of SimpleChat that deletes user data on a schedule without anyone
asking. Classification tells readers and reviewers how sensitive a document is before they open
it. Archiving decides whether a deletion, whether a user made it or retention did, can be
reviewed afterwards. Together they are your organisation's records position, so agree them
with whoever owns that policy before switching anything on.

{% include media.html src="admin/data-lifecycle-overview.png" alt="Screenshot placeholder for the Data Lifecycle group in Admin Settings." title="Data Lifecycle settings" capture="Capture the Data Lifecycle group in Admin Settings showing its tabs." %}

{% include media.html type="video" title="Data Lifecycle settings walkthrough" poster="video-posters/admin-data-lifecycle.png" capture="Recording planned. Walk through each tab in the Data Lifecycle group and explain when to change each setting." %}

## Before you change anything

- Agree a period for each workspace type with your records owner. Personal drafts, group
  records and organisation-wide knowledge rarely share one answer.
- Decide whether deletions must be reviewable before retention runs. Archiving only covers
  deletions made while it is on.
- Agree the classification labels first. Renaming or removing a label later does not relabel
  the documents that already carry it.

## Retention {#retention}

### Retention Policy {#retention-policy-section}

Retention is switched on separately for each workspace type. Switching a type on lets that
type's owners choose how long their conversations and documents are kept; until they choose,
the organization defaults set here apply. **No automatic deletion** keeps everything, and it is
the starting default for every type.

#### Who chooses the period

| Workspace type | Who chooses | What the period governs |
| --- | --- | --- |
| Personal | Each user, from their own settings | Their documents, and their conversations other than chats grounded in a group or public workspace |
| Group | Group owners and admins | The group's documents, and every conversation grounded in the group, including members' own chats |
| Public | Workspace owners and admins | The workspace's documents, and every conversation grounded in it, including other users' chats with its documents |

A conversation is *grounded* in its primary workspace, which is usually the workspace whose
documents it cited first. That workspace's policy governs the conversation, not its owner's
personal period. Public workspaces have no conversations of their own, so their conversation
period applies only to chats grounded in them. Deleting a public workspace leaves the chats
grounded in it in place, and they return to their owners' personal periods.

If retention is off for a workspace type, nothing grounded in that type is deleted by
retention, including chats that would otherwise have followed an owner's personal period.

#### What a run deletes

- **Conversations** with no activity for longer than their period. With
  [Conversation Archiving](#conversation-archiving-section) on, each is copied to the archive
  before it is removed; with it off, the conversation and its messages are deleted permanently.
- **Documents** not updated for longer than their period. They are always deleted permanently,
  together with their search index entries and stored files.
- **Notifications** follow every run. Users are told about their own items, group members
  through their group, and public workspace managers receive a count of removed conversations.
  The titles of chats grounded in a public workspace go only to each chat's owner, never to the
  workspace's managers.

#### When it runs

Retention runs once a day at the chosen hour, in UTC. The new interface shows the hour on your
own clock beside it, with the last run and the next run.

Saving a new hour, or switching a workspace type on, schedules the next run. Switching every
type off clears it. In the new interface, a save that touches neither leaves a pending run where
it is; the classic page reschedules on every save. The scheduler checks every five minutes, so a
run that is due starts within five minutes.

#### Run now

**Run retention now** deletes everything already past its period without waiting for the daily
run. It opens a review first: choose the workspace types to clean up, check the defaults each
one follows and what happens to conversations given the current archiving setting, then
confirm. The result reports what was removed for each type.

In the new interface:

- Only workspace types whose retention is on in the saved settings can be chosen. The classic
  page's Manual Execution lets you pick a type whose retention is off, and runs it anyway.
- It waits while Retention or archiving changes are unsaved, because a run applies the saved
  settings. Save or discard first.
- A run on a large deployment can take several minutes. If the page stops waiting before the
  run reports back, the run carries on; use **Check again** beside **Last run** to see when it
  finishes.

#### Reset to the defaults

**Reset to the defaults**, called *Force Push Defaults* on the classic page, clears the period
every user, group or public workspace of the chosen types has set, so each follows the
organization defaults again. Nothing is deleted by the reset itself; the next run applies the
defaults. It cannot be undone, because the periods people chose are not kept.

The classic page saves the whole form before pushing. The new interface instead waits until
unsaved Retention changes are saved or discarded, and offers only types whose retention is on.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Personal workspaces | Lets each user choose how long their own conversations and documents are kept. | Off | `enable_retention_policy_personal`; "Enable for Personal Workspaces" on the classic page |
| Group workspaces | Lets group owners and admins choose a period for the group and the chats grounded in it. | Off | `enable_retention_policy_group` |
| Public workspaces | Lets public workspace owners and admins choose a period for the workspace's documents and the chats grounded in it. | Off | `enable_retention_policy_public` |
| Default conversation retention (personal) | The conversation period for every user who has not chosen one. | No automatic deletion | `default_retention_conversation_personal` |
| Default document retention (personal) | The document period for every user who has not chosen one. | No automatic deletion | `default_retention_document_personal` |
| Default conversation retention (group) | The conversation period for every group that has not chosen one. | No automatic deletion | `default_retention_conversation_group` |
| Default document retention (group) | The document period for every group that has not chosen one. | No automatic deletion | `default_retention_document_group` |
| Default conversation retention (public) | The period for chats grounded in a public workspace that has not chosen one. | No automatic deletion | `default_retention_conversation_public` |
| Default document retention (public) | The document period for every public workspace that has not chosen one. | No automatic deletion | `default_retention_document_public` |
| Daily run time | The hour, in UTC, at which retention runs each day. | 02:00 UTC | `retention_policy_execution_hour`; a whole hour from 0 to 23. "Scheduled Execution Time" on the classic page |

The defaults offer the same periods in both interfaces: no automatic deletion, 1 to 7 days, 10,
14, 21, 30, 60 and 90 days, six months, one year and two years.

## Classification {#classification}

### Document Classification {#document-classification-section}

Classification lets people label each document with one of a fixed list of categories. The
label shows as a coloured badge on the document, and on the conversations that cite it, so a
reader sees how sensitive the source is before relying on an answer. Documents can be filtered
by it.

The categories are offered in the order you list them. In the new interface each category is a
row you edit in place: its label, its colour (picked or typed as a hex value), and buttons to
move or remove it. A preview shows the badges as users will see them. The section reads
**Needs configuration** while classification is on with no categories, because users would have
nothing to choose from.

Documents store the label itself rather than a reference to the category. That is why:

- two categories may not share a label, compared without regard to case;
- renaming or removing a category leaves documents that already carry the old label unchanged.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Document Classification | Lets users label documents with the categories below. | Off | `enable_document_classification`; capability toggle |
| Categories | The labels and badge colours users choose from, in display order. | None (grey), N/A (grey), Pending (blue) | `document_classification_categories`; labels up to 80 characters, colours as six-digit hex such as `#808080` |

## Archiving {#archiving}

### Conversation Archiving {#conversation-archiving-section}

With archiving on, a deleted conversation and its messages are copied to the archive before
they are removed, and a single deleted message is hidden rather than erased. Deleted messages no
longer appear in the conversation, in search results, or in the context sent to the model.
Archived copies are not shown to users; they are kept for compliance and audit review.

Retention follows this setting too: conversations past their period are archived before they
are removed. Documents are always deleted permanently, whether archiving is on or off.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Archive deleted conversations | Copies deleted conversations and messages to the archive instead of deleting them outright. | Off | `enable_conversation_archiving`; "Enable Conversation Archiving" on the classic page; capability toggle |

## Common tasks

1. **Keep group records for a year.** Switch **Group workspaces** on, set both group defaults
   to *365 days (1 year)*, and save. Groups that never chose their own period follow it from
   the next run. Outcome to verify: **Next run** shows a time.
2. **Bring every group back to the defaults.** Use **Reset to the defaults**, choose **Group
   workspaces**, and confirm. Outcome to verify: the result reports how many groups were reset.
3. **Clean up now after tightening a default.** Save the new default, then use **Run retention
   now**. Outcome to verify: the result lists what was removed and **Last run** updates.
4. **Add a sensitivity label.** Add a category, give it a unique label and a colour, and save.
   Outcome to verify: the badge appears in the preview and in the document classification
   choices.
5. **Make deletions reviewable.** Switch **Archive deleted conversations** on before retention
   or users delete anything you need to keep.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| **Run now** or **Reset to the defaults** cannot be clicked | There are unsaved Retention changes (or, for a run, an unsaved archiving change), or no workspace type has retention on in the saved settings. | Save or discard the changes, or switch a type on and save. |
| **Next run** says it is not set | Retention was switched on without a run time being saved, so no run has been scheduled yet. | Save the run time again, or let the next run set it. |
| A run removed nothing | No owner chose a period and the defaults keep everything, or nothing is older than its period yet. | Check the defaults shown in the review. |
| Chats grounded in a public workspace stopped following a user's personal period | Since 0.261.272 they follow the public workspace's period, as group-grounded chats follow their group's. | Switch **Public workspaces** on and set a default, or let workspace owners choose. |
| Saving categories fails because two categories share a label | Labels must be unique, without regard to case. | Rename one of them. |
| Deleted conversations disappear permanently | Archiving was off when the deletion happened. | Switch archiving on before relying on review of future deletions. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Backup & Recovery settings]({{ '/admin/backup-recovery/' | relative_url }})
- [Workspaces settings]({{ '/admin/workspaces/' | relative_url }})
- [Governance settings]({{ '/admin/governance/' | relative_url }})
