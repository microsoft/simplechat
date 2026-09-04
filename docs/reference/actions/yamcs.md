---
layout: page
title: "Yamcs"
description: "Reference for the Yamcs SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: yamcs -->

{% include media.html src="reference/actions-yamcs-configuration.png" alt="Yamcs action setup or assignment UI." title="Yamcs action" capture="Capture the Yamcs action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Retrieves read-only Yamcs telemetry, mission database, archive, event, packet, alarm, and link information.

## Why and when to use it

Use it for mission-control visibility. Do not use it for commanding; the plugin source intentionally does not support commands or writes.

## Before you start

- Yamcs server URL, instance, processor, auth method, and retrieval limits.
- If the server sits behind a reverse proxy that challenges callers, the username and password that proxy expects.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

Set Server URL, Instance, Processor, Authentication Method, credentials, Max Rows, Timeout, Verify TLS, and optional read-only archive SQL.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Reaching a Yamcs server behind an authenticating proxy

Ground segments often publish Yamcs through a reverse proxy, such as Apache, that
challenges every request with HTTP Basic authentication against a directory before the
request reaches Yamcs at all. Yamcs behind that proxy frequently has no authentication of
its own. Without a way to answer the proxy challenge, SimpleChat cannot reach such a server
even though the Yamcs configuration is correct.

**Reverse Proxy Authentication** covers that case. Turning it on makes the action send an
HTTP Basic `Authorization` header on every request, which satisfies the proxy and is then
consumed before Yamcs sees it. Leave it off when you reach Yamcs directly, such as a local
simulator, so no unnecessary credential is sent.

### Which authentication methods it can be combined with

HTTP Basic authentication uses the `Authorization` header, and so do two of the Yamcs
authentication methods. That makes some combinations impossible rather than merely
unsupported:

| Yamcs Authentication Method | Works with proxy Basic auth | Why |
|---|---|---|
| No Authentication | Yes | Yamcs sends nothing, so the header is free for the proxy. This is the usual case for a proxied dev or mission server. |
| API Key | Yes | The Yamcs API key travels in the `x-api-key` header, leaving `Authorization` for the proxy. |
| Username and Password | No | Yamcs exchanges the credentials for a bearer token carried in `Authorization`, and the token request itself would be refused by the proxy. |
| Access Token | No | The bearer token also needs `Authorization`. |

Choosing a blocked combination is reported when you save the action and when you use
**Test Yamcs Connection**, so the conflict surfaces before an agent depends on it.

### Supplying the proxy credential

The proxy username and password can be entered directly on the action. The password is
stored in Key Vault, never in the action document, and is never returned to the browser.

Where the credential expires and is reissued, which is common for directory-issued
temporary passwords, select a **Reusable Identity** instead. The action then stores only a
reference, and the credential is maintained once under **Workspace → Identities**. Rotating
it there updates every action that points at it, so a new password does not require editing
the action. Only username and password identities appear in this list, because HTTP Basic
authentication is always a username and password pair.

An identity resolves within the workspace that owns the action. A personal action paired
with a personal identity therefore uses that person's own credential.

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
