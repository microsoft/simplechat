# Workspace chat deep links

**Implemented in version: 0.261.473**

**Whole-workspace selection and reasoning persistence updated in version: 0.261.474**

## Overview

Workspace chat deep links are compact, server-backed URLs that prepare a new
private chat with one exact agent or model, one workspace, and either that
whole workspace or explicit selected documents. The model's selected reasoning
effort is stored as part of the link. A link is an opaque reference, not a capability. Recipients must
already be authorized for every selected resource.

## Dependencies

- Azure Cosmos DB `chat_links` container, partitioned by `/id`
- Existing agent and model catalog governance
- Existing workspace and document source authorization
- Existing Classic and V2 chat initialization paths
- Control Center full-admin capability

## Technical specifications

### Architecture

The application stores only identifiers, schema metadata, creator identity,
creation time, selected lifetime, the canonical scoped selection, and the model
reasoning effort.
It does not store prompts, conversation history, agent instructions, document
contents, endpoint credentials, or service URLs.

References contain 128 random bits encoded as 22 URL-safe characters. Timed
items use an absolute `expires_at`, an item TTL, and an explicit read-time
expiry check. Never-expiring items omit `expires_at` and `ttl`.

Authorization is repeated:

1. When a creator requests the link.
2. When a recipient resolves it.
3. Before the first linked chat request starts model or agent work.

The exact request selection is compared with the stored configuration.
Missing, changed, revoked, expired, or inaccessible dependencies fail the whole
launch; SimpleChat never drops a document or substitutes a different runner.

### APIs

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/api/chat-links` | Create a link after full creator authorization |
| `GET` | `/api/chat-links` | List the signed-in creator's active links |
| `GET` | `/api/chat-links/<reference>` | Resolve and reauthorize a launch |
| `DELETE` | `/api/chat-links/<reference>` | Revoke a creator-owned link |
| `GET` | `/l/<reference>` | Preserve the compact reference through normal navigation and sign-in |
| `GET` | `/api/v2/control-center/chat-links` | List all active links for a full Control Center administrator |
| `DELETE` | `/api/v2/control-center/chat-links/<reference>` | Administratively revoke any active link |

### Configuration and storage

Creators choose `7 days`, `30 days`, `90 days`, `1 year`, or `Never expires`.
The default is 90 days. Timed records use the Cosmos container's per-item TTL;
the container default is `-1`, allowing never-expiring records to omit TTL.

The application backup inventory deliberately excludes `chat_links`. Account
point-in-time restore requires an explicit invalidation/recovery decision
before restored links are trusted; backup exclusion alone does not invalidate
links in an account restore.

### File structure

- `application/single_app/chat_link_contract.py`
- `application/single_app/functions_chat_links.py`
- `application/single_app/route_chat_links.py`
- `application/single_app/static/js/chat/chat-links.js`
- `application/v2_ui/src/lib/chatLinks.ts`
- `application/v2_ui/src/components/chat/ChatLinkDialog.tsx`
- `application/v2_ui/src/components/controlCenter/ChatLinksSection.tsx`

## Usage

### Create and send a link

1. Select an available agent or model and, for a model, its reasoning effort.
2. Choose one whole personal, group, or public workspace, or explicit documents from one workspace.
3. Open **Create chat link**.
4. Select a lifetime. The default is 90 days; **Never expires** remains available.
5. Create and copy the plain-text URL.
6. Paste the URL into an email or another message.

Personal runner resources remain personal. Personal documents work only for
the creator or recipients with an existing approved share.

### Open a link

Opening a link starts normal authentication, Terms of Use, access restriction,
and idle-session handling. SimpleChat then resolves the stored reference and
creates a local new-chat draft only after authorization succeeds. It does not
send a prompt or persist an empty conversation.

If a recipient lacks a dependency, SimpleChat displays:

> You don't have permission to use this linked configuration.

No inaccessible resource names, owners, or details are disclosed.

### Revoke a link

Creators revoke links from the creation dialog. Full Control Center
administrators can review all active records and revoke any reference from the
Classic or V2 **Chat Links** section. Existing conversations are unaffected.

## Testing and validation

Coverage includes:

- Opaque reference generation and collision handling
- 90-day default, fixed lifetimes, and never-expiring records
- Creator, recipient, group, public, and document authorization
- Whole personal, group, and public workspace selections
- Expiry, revocation, stale resources, and malformed records
- Exact agent/model, reasoning, and canonical source binding at first send
- Classic and V2 hydration without an empty conversation
- Control Center admin-only listing and revocation
- Copy/manual-copy fallback, keyboard navigation, and mobile placement
- Cosmos response normalization and point-read storage boundaries
- Bicep, ARM, Terraform, and Azure CLI container parity

Performance uses point reads for navigation resolution and paginated creator or
administrator queries. Link records are small and exclude search content.

Known limitations:

- Links support either one selected workspace or explicit document references
  from one workspace. Tag-only, mixed-workspace, and global **Search all
  documents** presets are intentionally not encoded.
- Personal agent and model references are useful only to their authorized owner.
- Restored account data still requires an explicit link invalidation decision.
