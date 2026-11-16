// ControlCenterRolesGuide.tsx
// How to create, assign and enforce the two Control Center app roles.
//
// Ported from the server-rendered page's Role Setup Guide. One troubleshooting line is
// corrected rather than copied: it told administrators that a ControlCenterAdmin holder also
// needs the general Admin role, but `control_center_required` and the navigation admit the
// role on its own while the requirement is enforced.

import { CopyChip } from '../CopyValue';
import {
    GuideCode,
    GuideIssue,
    GuideLinks,
    GuideNote,
    GuideSection,
    GuideSteps,
    Literal,
    UiName,
} from './GuideDialog';

const ROLE_DEFINITIONS = [
    {
        value: 'ControlCenterAdmin',
        description: 'Full administrative access to Control Center features',
        grants: 'The whole Control Center: dashboard, users, groups, public workspaces and activity logs.',
    },
    {
        value: 'ControlCenterDashboardReader',
        description: 'Read-only access to Control Center dashboard and metrics',
        grants: 'The dashboard only: statistics, activity trends and usage metrics, with no management.',
    },
] as const;

const INSTALL_GRAPH = 'Install-Module Microsoft.Graph -Scope CurrentUser';

const CONNECT_GRAPH = 'Connect-MgGraph -Scopes "AppRoleAssignment.ReadWrite.All", "User.Read.All"';

const FIND_ROLES = `# Get your app's service principal
$sp = Get-MgServicePrincipal -Filter "displayName eq 'YourAppName'"

# List its app roles and their ids
$sp.AppRoles | Select-Object DisplayName, Id, Value`;

const ASSIGN_ROLE = `# Get the user
$user = Get-MgUser -UserId "user@domain.com"

# The id of the role to assign, from the previous step
$appRoleId = "role-guid-from-previous-step"

# Create the assignment
$params = @{
    principalId = $user.Id
    resourceId = $sp.Id
    appRoleId = $appRoleId
}

New-MgUserAppRoleAssignment -UserId $user.Id -BodyParameter $params`;

export function ControlCenterRolesGuide() {
    return (
        <>
            <GuideSection title="The two roles">
                <p>
                    App roles let you hand out Control Center access without making someone a full
                    SimpleChat administrator. Each is defined once on the app registration and then
                    assigned to people or groups.
                </p>
                <dl className="divide-y divide-edge rounded-lg border border-edge">
                    {ROLE_DEFINITIONS.map((role) => (
                        <div key={role.value} className="space-y-1 px-3 py-2.5">
                            <dt>
                                <CopyChip value={role.value} label={`the ${role.value} role value`} />
                            </dt>
                            <dd>{role.grants}</dd>
                        </div>
                    ))}
                </dl>
                <GuideNote tone="warning">
                    While <UiName>Require ControlCenterAdmin App Role</UiName> is on, general Admins
                    without that role lose Control Center access. Admin Settings stays open to them, so
                    the requirement can always be switched back off.
                </GuideNote>
            </GuideSection>

            <GuideSection title="1. Create the app roles">
                <GuideSteps>
                    <li>
                        In the Azure portal, open <UiName>Microsoft Entra ID</UiName>, then{' '}
                        <UiName>App registrations</UiName>, and select SimpleChat&rsquo;s registration.
                    </li>
                    <li>
                        Select <UiName>App roles</UiName>, then <UiName>Create app role</UiName>.
                    </li>
                    <li>
                        Use <Literal>ControlCenterAdmin</Literal> as both the display name and the value,
                        allow <UiName>Users/Groups</UiName>, add the description below, leave the role
                        enabled, and select <UiName>Apply</UiName>.
                    </li>
                    <li>
                        Repeat for <Literal>ControlCenterDashboardReader</Literal>.
                    </li>
                </GuideSteps>
                <div className="relative overflow-x-auto rounded-lg border border-edge">
                    <table className="w-full min-w-[28rem] border-collapse text-left text-xs">
                        <caption className="sr-only">Values for each app role</caption>
                        <thead className="bg-surface-2 text-text-2">
                            <tr>
                                <th scope="col" className="px-3 py-2 font-semibold">
                                    Display name and value
                                </th>
                                <th scope="col" className="px-3 py-2 font-semibold">
                                    Description
                                </th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-edge">
                            {ROLE_DEFINITIONS.map((role) => (
                                <tr key={role.value}>
                                    <th scope="row" className="px-3 py-2 align-top font-normal">
                                        <CopyChip value={role.value} label={`the ${role.value} role value`} />
                                    </th>
                                    <td className="px-3 py-2 align-top">
                                        <CopyChip
                                            value={role.description}
                                            label={`the ${role.value} description`}
                                        />
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
                <GuideNote>The value must match exactly. It is case-sensitive.</GuideNote>
            </GuideSection>

            <GuideSection title="2. Assign people or groups">
                <GuideSteps>
                    <li>
                        In <UiName>Microsoft Entra ID</UiName>, open <UiName>Enterprise applications</UiName>,
                        set the application type filter to <UiName>All applications</UiName>, and select the
                        application with the same name as the registration.
                    </li>
                    <li>
                        Select <UiName>Users and groups</UiName>, then <UiName>Add user/group</UiName>.
                    </li>
                    <li>Choose the users or groups, choose the role, and select <UiName>Assign</UiName>.</li>
                </GuideSteps>
                <GuideNote tone="warning">
                    A new assignment reaches someone at their next sign-in, so ask them to sign out and
                    back in.
                </GuideNote>
            </GuideSection>

            <GuideSection title="Or assign with Microsoft Graph PowerShell">
                <p>Useful for assigning many people at once, or from automation.</p>
                <GuideSteps>
                    <li className="space-y-1.5">
                        <p>Install the module.</p>
                        <GuideCode code={INSTALL_GRAPH} label="the module install command" />
                    </li>
                    <li className="space-y-1.5">
                        <p>Connect with permission to manage role assignments.</p>
                        <GuideCode code={CONNECT_GRAPH} label="the connect command" />
                    </li>
                    <li className="space-y-1.5">
                        <p>Find the application and its role ids.</p>
                        <GuideCode code={FIND_ROLES} label="the role lookup script" />
                    </li>
                    <li className="space-y-1.5">
                        <p>Assign a role to a user.</p>
                        <GuideCode code={ASSIGN_ROLE} label="the role assignment script" />
                    </li>
                </GuideSteps>
                <GuideNote>
                    Replace <Literal>YourAppName</Literal> with the application&rsquo;s display name and{' '}
                    <Literal>user@domain.com</Literal> with the person&rsquo;s sign-in name.
                </GuideNote>
            </GuideSection>

            <GuideSection title="3. Switch the requirements on and check">
                <GuideSteps>
                    <li>Make sure everyone you assigned has signed in again.</li>
                    <li>
                        Turn on <UiName>Require ControlCenterAdmin App Role</UiName>,{' '}
                        <UiName>Allow ControlCenterDashboardReader App Role</UiName>, or both, and save.
                    </li>
                    <li>
                        Open the Control Center as each kind of user. ControlCenterAdmin holders see every
                        tab; dashboard readers see the dashboard only.
                    </li>
                </GuideSteps>
            </GuideSection>

            <GuideSection title="Troubleshooting">
                <GuideIssue symptom="Someone with the role cannot open the Control Center">
                    <li>They have not signed in again since the role was assigned.</li>
                    <li>The role value in Entra does not match exactly, including case.</li>
                    <li>The matching switch here is not on, or has not been saved.</li>
                    <li>
                        While the ControlCenterAdmin requirement is on, that role is enough by itself. The
                        general Admin role is neither needed nor enough.
                    </li>
                </GuideIssue>
                <GuideIssue symptom="The roles are missing when assigning">
                    <li>
                        They were created on the enterprise application instead of the app registration.
                    </li>
                    <li>A role was left disabled.</li>
                    <li>New roles can take a few minutes to appear; refresh the enterprise application.</li>
                </GuideIssue>
                <GuideIssue symptom="A dashboard reader sees Forbidden">
                    <li>
                        The role covers the dashboard only. Users, groups, public workspaces and activity
                        logs are refused by design.
                    </li>
                    <li>Assign ControlCenterAdmin to anyone who needs the management features.</li>
                </GuideIssue>
            </GuideSection>

            <GuideSection title="Further reading">
                <GuideLinks
                    links={[
                        {
                            label: 'Microsoft Learn: Add app roles to your application',
                            href: 'https://learn.microsoft.com/en-us/entra/identity-platform/howto-add-app-roles-in-apps',
                        },
                        {
                            label: 'Microsoft Learn: Assign users and groups to an application',
                            href: 'https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/assign-user-or-group-access-portal',
                        },
                        {
                            label: 'Microsoft Graph PowerShell SDK',
                            href: 'https://learn.microsoft.com/en-us/powershell/microsoftgraph/overview',
                        },
                    ]}
                />
            </GuideSection>
        </>
    );
}
