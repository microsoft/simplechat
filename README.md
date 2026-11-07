![SimpleChat logo](./docs/images/logo-wide.png)

# SimpleChat

SimpleChat is an open-source Flask application for grounded conversations, focused AI assistants, and repeatable workflows on an Azure deployment you manage. It combines Microsoft Entra ID sign-in, Azure Cosmos DB application records, and Azure AI Search-backed workspace retrieval with configurable AI connections and administrative controls.

**[Documentation](https://microsoft.github.io/simplechat/)** · **[Get started](https://microsoft.github.io/simplechat/guides/getting-started/)** · **[Feature catalog](https://microsoft.github.io/simplechat/features/)** · **[Choose a deployment path](https://microsoft.github.io/simplechat/start/deployment-options/)**

## What you can do

Many capabilities are optional and administrator-controlled. Availability also depends on roles, source permissions, configured services, and compatible models. Enabling a tool does not grant access to new sources or approve sharing data with an external destination.

| Capability | Use it for |
| --- | --- |
| [Grounded workspace knowledge](https://microsoft.github.io/simplechat/features/grounded-document-search/) | Ask questions using hybrid keyword/vector retrieval across permitted [personal](https://microsoft.github.io/simplechat/features/personal-workspace/), [group](https://microsoft.github.io/simplechat/features/group-workspaces/), and [public](https://microsoft.github.io/simplechat/features/public-workspaces/) collections. Public workspaces serve signed-in SimpleChat users, not anonymous visitors. |
| [Chat file uploads](https://microsoft.github.io/simplechat/features/chat-file-uploads/) and [citations](https://microsoft.github.io/simplechat/features/enhanced-citations/) | Bring a file into a conversation and inspect supporting passages and supported source previews. A citation is evidence to review, not a guarantee that an answer is correct. |
| [Saved prompts](https://microsoft.github.io/simplechat/features/saved-prompts/), [agents](https://microsoft.github.io/simplechat/features/agents/), and [actions](https://microsoft.github.io/simplechat/features/core-actions/) | Reuse instructions and variables, configure focused assistants with assigned knowledge, and give them approved tools instead of rebuilding the same setup for every question. |
| [V2 chat orchestration](https://microsoft.github.io/simplechat/features/chat-orchestration/) | Plan multi-step work across enabled capabilities, inspect dependencies, and follow execution. [Review or edit proposed plans](https://microsoft.github.io/simplechat/guides/review-and-edit-orchestration-plans/) before execution when the selected approval mode permits. |
| [Repeatable workflows](https://microsoft.github.io/simplechat/features/workflows/) | Save tasks and inputs, run on demand or on configured schedules and File Sync triggers, and inspect run history and delivered results. |
| [Analyze](https://microsoft.github.io/simplechat/features/document-analysis/) and [Compare](https://microsoft.github.io/simplechat/features/document-compare/) | Review selected documents or compare a baseline with targets, then inspect findings, supporting passages, and limitations. Saved findings are not a fresh check of the original sources. |
| [Spreadsheet analysis](https://microsoft.github.io/simplechat/features/tabular-analysis/) | Compute grouped results, charts, and exports from supported CSV and spreadsheet data rather than treating rows as prose. Spreadsheet processing depends on Enhanced Citations and its storage configuration. |
| [File Sync](https://microsoft.github.io/simplechat/features/file-sync/) | Import workspace documents from approved network shares, Azure Files, or Azure Blob sources, with filters, schedules, and configured deletion handling. |
| [Collaboration](https://microsoft.github.io/simplechat/features/collaborative-conversations/) and [workspace scope lock](https://microsoft.github.io/simplechat/features/workspace-scope-lock/) | Work in shared conversations and keep grounded retrieval tied to its recorded workspace scope. Scope lock is not a frozen document snapshot or a grant of source access. |
| [Conversation details](https://microsoft.github.io/simplechat/features/conversation-details/) and [message details](https://microsoft.github.io/simplechat/features/message-details/) | Inspect recorded scope, state, attribution, source evidence, and tool outcomes instead of inferring what happened from the answer's prose. |
| [Memory](https://microsoft.github.io/simplechat/features/chat-memory/) and [preferences](https://microsoft.github.io/simplechat/guides/update-profile-preferences/) | Keep user-managed instructions and facts across conversations; manage interface and audio preferences separately. Retained memories are not a place for secrets. |
| [Generated deliverables](https://microsoft.github.io/simplechat/features/generated-deliverables/) | Turn prepared results into supported reports, presentations, spreadsheets, and data files, with charts, diagrams, or generated images where supported. A planned file is not a completed download. |
| [Web search](https://microsoft.github.io/simplechat/features/web-search/), [deep research](https://microsoft.github.io/simplechat/features/deep-research/), and [media ingestion](https://microsoft.github.io/simplechat/features/media-file-ingestion/) | Bring in current public sources or searchable audio/video when the supporting services are configured. External research has its own destination and data-sharing controls. |
| [Feedback and archiving](https://microsoft.github.io/simplechat/features/feedback-and-archiving/) | Collect response ratings and comments for review, and optionally retain conversation archives. Feedback does not automatically retrain models; archiving is not legal hold. |
| [Content Safety](https://microsoft.github.io/simplechat/features/content-safety/), [content screening](https://microsoft.github.io/simplechat/features/content-screening/), and [governance](https://microsoft.github.io/simplechat/admin/governance/) | Configure chat checks, document screening and review, and policies for agents, actions, and external destinations. These controls do not establish regulatory compliance. |
| [Microsoft 365](https://microsoft.github.io/simplechat/guides/microsoft-365-conversation-data/) and [Teams](https://microsoft.github.io/simplechat/guides/microsoft-teams-app/) | Use configured Calendar, Email, OneDrive, and SharePoint actions, or open SimpleChat as a Teams personal tab. Consent, source permissions, and outgoing-action delivery policies remain separate decisions. |

Use the [task guides](https://microsoft.github.io/simplechat/guides/) for walkthroughs and the [chat interface reference](https://microsoft.github.io/simplechat/reference/chat-controls/) for individual controls.

## Deploy and operate

Start with the documentation rather than copying a partial setup sequence:

1. **Choose and deploy:** compare [deployment paths](https://microsoft.github.io/simplechat/start/deployment-options/). The repository-recommended [Azure Developer CLI path](https://microsoft.github.io/simplechat/reference/deploy/azd-cli_deploy/) deploys a container-based App Service; the guides cover toolchain, identity, network, and cloud prerequisites and alternative deployers.
2. **Configure and verify:** follow [first configuration](https://microsoft.github.io/simplechat/guides/admin-first-configuration/), configure [AI connections](https://microsoft.github.io/simplechat/guides/configure-ai-connections/), and prove one document-grounded conversation before expanding the rollout.
3. **Update and scale:** use [upgrade paths](https://microsoft.github.io/simplechat/guides/upgrade-paths/) for existing deployments and the [Azure scaling guide](https://microsoft.github.io/simplechat/guides/scale-simplechat-on-azure/) for capacity planning. Configure shared Redis sessions before App Service scale-out; adding web instances does not add search capacity or model quota.
4. **Manage lifecycle and recovery:** configure [retention and archiving](https://microsoft.github.io/simplechat/admin/data-lifecycle/) separately from [backup, restore, and migration](https://microsoft.github.io/simplechat/admin/backup-recovery/). An archive does not replace a tested backup and restore.

AI connections support compatible Azure OpenAI, Foundry, and approved custom endpoints. Azure Commercial and Government deployments need cloud-appropriate configuration; model capabilities, service availability, and quotas vary by provider, cloud, and region. Review [model routing](https://microsoft.github.io/simplechat/features/model-routing/) and [special deployment scenarios](https://microsoft.github.io/simplechat/deploy/special-scenarios/) rather than assuming every integration is available or stays in the hosting cloud.

Read the [architecture](https://microsoft.github.io/simplechat/explanation/architecture/) for application, data, identity, and outbound-service boundaries. Developers can use the dedicated [local development guide](https://microsoft.github.io/simplechat/explanation/running_simplechat_locally/) instead of production deployment instructions.

## Help and contributions

- **Product and deployment help:** [FAQ](https://microsoft.github.io/simplechat/start/faqs/), [troubleshooting](https://microsoft.github.io/simplechat/troubleshooting/), and [administration](https://microsoft.github.io/simplechat/admin/).
- **Bugs and feature requests:** [GitHub issues](https://github.com/microsoft/simplechat/issues).
- **Source and contributions:** [microsoft/simplechat](https://github.com/microsoft/simplechat) and the [contribution workflow](https://microsoft.github.io/simplechat/contributing/). Contributor pull requests target `Development`, not `main` or `Staging`.
- **Security reports:** follow [SECURITY.md](./SECURITY.md); do not report vulnerabilities in public issues.
- **License:** [MIT](./LICENSE).

## Community

[Register for the SimpleChat community call](https://aka.ms/simplechat-community-call) for meeting details.

Previous recordings:

- [December 11, 2025](https://www.youtube.com/watch?v=X12waLe1TKM)
- [February 5, 2026](https://www.youtube.com/watch?v=WOeWTzeXMFU)
- [March 19, 2026](https://www.youtube.com/watch?v=EpIVCwGXh1E)
- [April 30, 2026](https://www.youtube.com/watch?v=A2QiGNa6pwM)
- [June 11, 2026](https://www.youtube.com/watch?v=gBcm8g4i3rs)
- [July 23, 2026](https://www.youtube.com/watch?v=6w_ypzkIKqo)
