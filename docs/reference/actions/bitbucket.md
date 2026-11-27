---
layout: page
title: "Bitbucket"
description: "Read approved repository source and compare branches with private Bitbucket connections or token identities."
section: "Reference"
audience: user
version: "0.261.450"
---

<!-- action-slug: bitbucket -->

## What this action does

Supplies repository source and branch changes to an agent for code review.
It supports self-hosted **Bitbucket Data Center** and **Bitbucket Cloud**.
It cannot push commits, create pull requests, post comments, approve reviews,
merge branches, execute repository code, or clone repositories.

Fixed/Implemented in version: **0.261.450**, recorded in
`application/single_app/config.py`.

## Choose authentication

| Method | Use it when | Credential |
| --- | --- | --- |
| Each user's OAuth connection | Users should sign in individually through Bitbucket, potentially using its SSO or smart-card login | A registered Data Center incoming application link or Cloud OAuth consumer; each user connects separately |
| HTTP access / bearer token | A Data Center HTTP access token or Cloud repository/project/workspace access token authorizes the repository | Bearer-token identity or shared action token |
| Cloud email and scoped API token | An Atlassian API token is the credential available to the user | Username/password identity with Atlassian email as username and API token as password |

Select **Each user's private identity** for personal token selection in chat.
Alternatively, bind an identity from the action's own workspace, or enter a
shared credential. A shared group/global identity is shared by the action's
users; it is not automatically replaced with the caller's identity.

SimpleChat and Microsoft 365 login tokens are **not forwarded** to Bitbucket.
The same identity provider does not make their token audiences interchangeable.
OAuth redirects to Bitbucket's own sign-in; an existing browser SSO session may
help there. Browser cookies, smart-card private keys, SSH keys and deprecated
Cloud app passwords are not accepted by this REST action.

## Configure repositories and branches

1. Select the edition and HTTPS server base URL. Include a Data Center context
   path when configured. Cloud uses `https://api.bitbucket.org`.
2. Configure authentication and save. An action with no permitted repositories
   can be saved for setup, but cannot read code.
3. For OAuth, open **Connect / reconnect my Bitbucket account** and complete
   Bitbucket sign-in. Return to the editor.
4. Enter a Data Center project key or Cloud workspace, choose **Find
   repositories**, and select one or several repositories.
5. For each repository, choose **Any branch** or **One fixed branch**, configure
   the branch/default, and save again.

Discovery uses the **saved** connection configuration and requires action
management rights. Save changed credentials or destinations before discovering.
For per-user token actions, discover using OAuth or a saved/shared token first,
then switch to each user's private identity before sharing the action.
Discovery lists what the current credential can access; a repository-scoped
token may not have permission to enumerate a project/workspace.

A fixed branch is the only permitted branch, including both inputs to a
comparison. Any-branch mode accepts an exact branch name; an omitted branch
uses the configured default, or Bitbucket's own default when none is configured.
An inaccessible/deleted configured default returns an error rather than silently
switching branches. Tags, commit hashes and ref expressions are not alternate
ways around branch policy.

## Use it in chat

Assign the action to an agent or use it through authorized orchestration. Ask,
for example, "List the repositories available for review", then "Review changes
from main to feature/login in Repository". Repository choices use the returned
stable IDs. If several are allowed, the agent must select one explicitly.
There are no new chat toolbar selectors.

For OAuth, users who do not edit the action can follow the private connection
link returned by the tool. Connect, return to chat, and retry the request.
OAuth does not automatically resume paused work. Personal **token** identity
requests use the existing private **Save and continue** credential card.
Never paste credentials into chat.

## Results and review limits

Each source read reports its branch and immutable commit. Comparisons report
the resolved baseline and target commits plus their merge base, and review
**merge-base-to-target** changes, not baseline-tip-to-target changes.
Separate calls are not a frozen repository-wide snapshot.

Directory/branch pages contain at most 50 entries; comparison pages contain
at most 10 files. Follow `next_cursor` when present. Source files are limited
to 250,000 bytes and 500 returned lines per call, with `next_line` for more
lines. Provider JSON and combined patch text are bounded to 1,000,000 bytes.
Binary, oversized and unsupported-text files are reported, not silently
reviewed. Comparison inputs above 10,000 lines per file are also omitted
to bound diff work. A truncated page or omitted file is **not a complete review**.
Repository source is untrusted data, never an instruction to execute commands
or change permissions.

## Deployment and troubleshooting

OAuth requires these **server-side environment settings**, not browser settings:

| Setting | Purpose |
| --- | --- |
| `BITBUCKET_REDIRECT_URI` | Canonical HTTPS callback ending exactly in `/api/bitbucket/callback`; register the same URI with Bitbucket |
| `BITBUCKET_TOKEN_ENCRYPTION_KEY` | Fernet key supplied from deployment secret storage/Key Vault reference, used to encrypt private access and refresh tokens |

Use a persistent encryption key shared across application workers. Losing or
changing it requires users to reconnect. Do not put it in action metadata or
source control. Configure repository-read permission only on the provider's
application/consumer and token. Data Center uses OAuth authorization-code
with S256 PKCE; Cloud uses its confidential-client flow without assuming
Data Center PKCE support.

The SimpleChat execution host must reach the server's private DNS/network.
"Self-hosted" does not mean `localhost` on the SimpleChat worker. Verified
HTTPS is required; install the organization's trusted CA through the existing
[custom CA workflow]({{ '/guides/docker-customization/' | relative_url }}#custom-certificate-authorities).
Forward proxies, browser-only proxy challenges and copied session cookies
are not authentication workarounds. REST redirects to login HTML are errors.

The action requires the Data Center REST repository API and, for OAuth, the
incoming application-link OAuth 2 provider API. Legacy Bitbucket Server
installations are not assumed to implement that OAuth flow. Actual server,
Cloud consumer and customer smart-card/SSO acceptance require live deployment
testing; offline contract tests do not establish that compatibility.

Disconnect removes this user's local token access and fences in-flight work.
Revoke the application grant in Bitbucket to remove provider-side authorization.
Changing destination, edition, OAuth client ID or repository/branch policy
requires a new OAuth connection. A failed/interrupted refresh requires retry
or reconnect; SimpleChat does not replay a possibly rotated refresh token.

## Related

- [Personal action credentials]({{ '/guides/personal-action-credentials/' | relative_url }})
- [Actions reference]({{ '/reference/actions/' | relative_url }})
- [Bitbucket implementation details](https://github.com/microsoft/simplechat/blob/Development/docs/explanation/features/BITBUCKET_REPOSITORY_ACTION.md)
