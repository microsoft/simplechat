// m365Links.ts
// Where V2 sends someone to connect, reconnect or review Microsoft 365.
//
// V2 Settings holds the Microsoft 365 cards and V2 Approvals the Microsoft 365 requests, so each
// link stays in this interface rather than opening the classic Profile or Approvals page. They
// are router paths under the /v2 basename: render them with Link, never a bare anchor, which
// would leave the app. `section` names the settings card to scroll to.

export const M365_CHAT_CONNECTION_HREF = '/settings?tab=preferences&section=m365-chat-connection';
export const M365_CONNECT_HREF = '/settings?tab=preferences&section=m365-workflow-connection';
export const M365_APPROVALS_HREF = '/approvals/m365';
/** The sharing card, which also holds each file source's Extended analysis preference. */
export const M365_SHARING_PREFERENCES_HREF = '/settings?tab=preferences&section=m365-sharing';