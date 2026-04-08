---
layout: latest-release-feature
title: "Workspace Scope Lock"
description: "How workspace scope locking prevents cross-contamination between data sources"
section: "Latest Release"
---

Workspace scope automatically locks after the first AI search in a conversation, preventing accidental cross-contamination between data sources. Administrators can enforce this lock organization-wide so users cannot override it.

## Admin Configuration

Administrators enable the enforce setting from **Admin Settings > Workspaces**. When **Enforce Workspace Scope Lock** is toggled on, users cannot unlock scope in any conversation.

<img src="{{ '/images/feature-workspace_lock-configure.png' | relative_url }}" alt="Admin Settings - Enforce Workspace Scope Lock toggle" style="width: 70%;" />

## Scope Lock in Chat

After workspace scope locks, a lock icon appears next to the **Scope** label in the chat interface. The selected workspace badges remain visible at the top of the conversation.

<img src="{{ '/images/feature-workspace_lock-search_workspace.png' | relative_url }}" alt="Chat interface showing locked scope indicator and workspace badges" style="width: 70%;" />

## Locked Workspace Selection

Opening the scope dropdown while locked shows the initially selected workspace checked with a lock icon. Other workspace groups are greyed out and cannot be selected.

<img src="{{ '/images/feature-workspace_lock-show_workspace_selection_locked_to_initial.png' | relative_url }}" alt="Scope dropdown showing locked workspace selection" style="width: 70%;" />

## Unlock Behavior

What happens when a user attempts to unlock scope depends on whether the administrator has enforced the lock.

### Enforce Disabled

When the administrator has **not** enforced the lock, clicking the lock icon opens a confirmation modal with an **Unlock Scope** button. The user can choose to unlock and change workspaces.

<img src="{{ '/images/feature-workspace_lock-pop_up_to_unlock_workspace_if_enforce_disabled.png' | relative_url }}" alt="Unlock Workspace Scope modal with Unlock Scope button" style="width: 70%;" />

### Enforce Enabled

When the administrator **has** enforced the lock, the modal informs the user that workspace scope lock is enforced by their administrator and the scope cannot be unlocked. Only a **Cancel** button is available.

<img src="{{ '/images/feature-workspace_lock-pop_up_informing_user_workspace_lock_status.png' | relative_url }}" alt="Informational modal showing scope lock is enforced by administrator" style="width: 70%;" />

## Notes

- Scope locks automatically after the first AI search in a conversation
- The lock applies per-conversation, not globally
- Starting a new conversation resets the scope to unlocked
- When enforce is enabled, the backend returns 403 for any attempt to unlock scope
