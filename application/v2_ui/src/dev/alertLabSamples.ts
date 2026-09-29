// alertLabSamples.ts
// Sample workflow alerts for the alert lab (AlertLabPage.tsx). Dev only.
//
// Each sample is a notification document shaped exactly as GET /api/notifications/workflow-alerts
// returns one, so it goes through the same reader (readWorkflowAlert) as a real alert. Every
// call makes fresh ids: a claimed alert never pops up twice, so replaying a sample needs new
// ones.
//
// Nothing here runs at load time. The lab is compiled out of production builds, and this file
// has to go with it.

import type { WorkflowAlertSeverity } from '../lib/workflowAlerts';

export type AlertLabScenarioId =
    | 'every-priority'
    | 'every-failure'
    | 'storm'
    | 'long'
    | 'short'
    | 'hostile'
    | 'group'
    | 'dialog'
    | 'notify-only'
    | 'old';

export interface AlertLabScenario {
    id: AlertLabScenarioId;
    label: string;
    /** What should happen, shown beside the button. */
    expect: string;
}

export function alertLabScenarios(): AlertLabScenario[] {
    return [
        { id: 'every-priority', label: 'Every priority', expect: 'Critical first, then "+4 more".' },
        { id: 'every-failure', label: 'Every priority, run failed', expect: 'Failed-run wording at each priority.' },
        { id: 'storm', label: 'Alert storm', expect: 'Six failures group into one entry with a count.' },
        { id: 'long', label: 'Long text', expect: 'The title clamps; Show more reveals the detail.' },
        { id: 'short', label: 'Short, no links', expect: 'No links, no Open workflow, no matched rules.' },
        { id: 'hostile', label: 'Hostile text and links', expect: 'Markup shows as text; off-site links are refused.' },
        { id: 'group', label: 'Group workflow', expect: 'Open workflow goes to the group\'s workflows.' },
        { id: 'dialog', label: 'While a dialog is open', expect: 'Waits until the dialog closes.' },
        { id: 'notify-only', label: 'Notify-only', expect: 'Never pops up; it waits in the bell.' },
        { id: 'old', label: 'Older than 24 hours', expect: 'Never pops up; it waits in the bell.' },
    ];
}

interface WorkflowSample {
    id: string;
    name: string;
    scope: 'personal' | 'group';
    groupId?: string;
}

interface LinkSample {
    label: string;
    url: string;
    context?: Record<string, unknown>;
}

interface AlertSampleInput {
    workflow: WorkflowSample;
    priority: WorkflowAlertSeverity;
    category: 'alert' | 'failure';
    title: string;
    summary: string;
    detail?: string;
    error?: string;
    triggerReason?: string;
    rules?: { name: string; severity: WorkflowAlertSeverity; reason: string }[];
    enrichments?: string[];
    triggerSource?: string;
    runnerType?: string;
    agent?: string;
    links?: LinkSample[];
    minutesAgo: number;
    delivery?: 'popup' | 'notify_only';
    /** Leave out the fields an alert written before workflow scope existed would lack. */
    legacy?: boolean;
}

type WorkflowKey = 'report' | 'inventory' | 'mail' | 'build' | 'security';

function workflows(stamp: string): Record<WorkflowKey, WorkflowSample> {
    return {
        report: { id: `lab-wf-report-${stamp}`, name: 'Weekly report', scope: 'personal' },
        inventory: { id: `lab-wf-inventory-${stamp}`, name: 'Inventory sync', scope: 'personal' },
        mail: { id: `lab-wf-mail-${stamp}`, name: 'Mail triage', scope: 'personal' },
        build: { id: `lab-wf-build-${stamp}`, name: 'Build watcher', scope: 'group', groupId: 'lab-group-platform' },
        security: { id: `lab-wf-security-${stamp}`, name: 'Security feed', scope: 'personal' },
    };
}

function conversationLink(label: string, conversationId: string, groupId?: string): LinkSample {
    return {
        label,
        url: `/chats?conversationId=${conversationId}`,
        context: {
            workspace_type: groupId ? 'group' : 'personal',
            conversation_id: conversationId,
            chat_type: groupId ? 'group-single-user' : 'personal_single_user',
            ...(groupId ? { group_id: groupId } : {}),
        },
    };
}

function sample(stamp: string, index: number, now: number, input: AlertSampleInput): Record<string, unknown> {
    const links = input.links ?? [];
    const delivery = input.delivery ?? 'popup';
    const priorityLabel = `${input.priority.charAt(0).toUpperCase()}${input.priority.slice(1)}`;
    const metadata: Record<string, unknown> = {
        workflow_id: input.workflow.id,
        workflow_name: input.workflow.name,
        priority: input.priority,
        category: input.category,
        delivery,
        alert_mode: 'rules',
        matched_rules: (input.rules ?? []).map((rule, ruleIndex) => ({
            rule_id: `lab-rule-${ruleIndex}`,
            rule_name: rule.name,
            severity: rule.severity,
            condition_type: 'keyword',
            reason: rule.reason,
        })),
        trigger_reason: input.triggerReason ?? '',
        trigger_source: input.triggerSource ?? 'schedule',
        run_id: `lab-run-${stamp}-${index}`,
        runner_type: input.runnerType ?? 'agent',
        status: input.category === 'failure' ? 'failed' : 'completed',
        error: input.error ?? '',
        event_title: input.title,
        alert_title: input.title,
        alert_summary: input.summary,
        alert_detail: input.detail ?? '',
        alert_enrichments: input.enrichments ?? [],
        link_targets: links.map((link) => ({
            label: link.label,
            link_url: link.url,
            link_context: link.context ?? {},
        })),
    };
    if (!input.legacy) {
        metadata.workflow_scope = input.workflow.scope;
        metadata.group_id = input.workflow.groupId ?? '';
    }
    if (input.agent) {
        metadata.agent_display_name = input.agent;
    }
    return {
        id: `lab-${stamp}-${index}`,
        user_id: 'lab-user',
        notification_type: 'workflow_priority_alert',
        title: `${priorityLabel} priority workflow alert: ${input.workflow.name}`,
        message: input.summary,
        created_at: new Date(now - input.minutesAgo * 60_000).toISOString(),
        is_read: false,
        is_dismissed: false,
        link_url: links[0]?.url ?? '',
        link_context: links[0]?.context ?? {},
        metadata,
        priority: input.priority,
        category: input.category,
        delivery,
    };
}

interface PriorityText {
    workflow: WorkflowKey;
    alert: string;
    summary: string;
    failure: string;
    error: string;
}

function priorityText(priority: WorkflowAlertSeverity): PriorityText {
    switch (priority) {
        case 'info':
            return {
                workflow: 'report',
                alert: 'Weekly report is ready',
                summary: 'This week\'s report covers 42 closed tickets and 3 new customers.',
                failure: 'Weekly report could not be written',
                error: 'No data was returned for last week.',
            };
        case 'low':
            return {
                workflow: 'inventory',
                alert: 'Three items are below their reorder level',
                summary: 'Blue mugs, A4 paper and USB-C cables are under the level you set.',
                failure: 'Inventory sync did not finish',
                error: 'The supplier feed timed out after 30 seconds.',
            };
        case 'medium':
            return {
                workflow: 'mail',
                alert: 'Two messages need a reply today',
                summary: 'Contoso legal asks for the signed NDA by 5 PM, and Fabrikam wants to move Thursday\'s call.',
                failure: 'Mail triage could not read the mailbox',
                error: 'The mailbox answered 401 Unauthorized. The connection may need to be signed in again.',
            };
        case 'high':
            return {
                workflow: 'build',
                alert: 'The main branch build is red',
                summary: 'Three test suites failed after the 09:40 merge. The release pipeline is blocked.',
                failure: 'Build watcher could not reach the CI service',
                error: 'The CI API refused the token (403). Builds are not being watched.',
            };
        case 'critical':
        default:
            return {
                workflow: 'security',
                alert: 'A critical vulnerability affects a production dependency',
                summary: 'CVE-2025-0001 (CVSS 9.8) affects the image library the upload service uses.',
                failure: 'Security feed failed three runs in a row',
                error: 'The advisory feed has not been read since 06:00. New advisories may be missed.',
            };
    }
}

function severities(): WorkflowAlertSeverity[] {
    return ['info', 'low', 'medium', 'high', 'critical'];
}

/** The runner's trigger reason, as summarize_alert_decision writes it. */
function loggedReason(priority: WorkflowAlertSeverity, ruleNames: string[]): string {
    const severity = priority.toUpperCase();
    return ruleNames.length ? `${severity} alert triggered by: ${ruleNames.join(', ')}` : `${severity} alert triggered.`;
}

/** The run-status rule a workflow uses to alert when a run fails. */
function failedRunRule(priority: WorkflowAlertSeverity) {
    return { name: 'Failed runs', severity: priority, reason: 'Run status is failed' };
}

/** One alert at one priority, as an alert or a failed run. */
function priorityAlert(
    stamp: string,
    index: number,
    now: number,
    priority: WorkflowAlertSeverity,
    category: 'alert' | 'failure',
    minutesAgo: number,
): Record<string, unknown> {
    const text = priorityText(priority);
    const workflow = workflows(stamp)[text.workflow];
    const failed = category === 'failure';
    const rule = failed
        ? failedRunRule(priority)
        : { name: `${workflow.name} watch`, severity: priority, reason: 'The run\'s result matched the rule.' };
    return sample(stamp, index, now, {
        workflow,
        priority,
        category,
        title: failed ? text.failure : text.alert,
        summary: failed ? `The ${workflow.name} run stopped before it finished.` : text.summary,
        error: failed ? text.error : '',
        triggerReason: loggedReason(priority, [rule.name]),
        rules: [rule],
        enrichments: failed ? ['Run failed'] : ['Summarised by the agent'],
        agent: failed ? undefined : 'Workflow assistant',
        links: [conversationLink('Open workflow', `lab-conv-${text.workflow}-${stamp}`, workflow.groupId)],
        minutesAgo,
    });
}

/** A single alert, for the priority and category grid. */
export function alertLabSingle(
    stamp: string,
    now: number,
    priority: WorkflowAlertSeverity,
    category: 'alert' | 'failure',
): Record<string, unknown>[] {
    return [priorityAlert(stamp, 0, now, priority, category, 1)];
}

/** The priorities, in the order the grid lists them. */
export function alertLabSeverities(): WorkflowAlertSeverity[] {
    return severities();
}

/** The samples for a scenario, as the route would return them. */
export function alertLabScenarioAlerts(id: AlertLabScenarioId, stamp: string, now: number): Record<string, unknown>[] {
    const wf = workflows(stamp);
    switch (id) {
        case 'every-priority':
            return severities().map((priority, index) => priorityAlert(stamp, index, now, priority, 'alert', 1 + index));
        case 'every-failure':
            return severities().map((priority, index) => priorityAlert(stamp, index, now, priority, 'failure', 1 + index));
        case 'storm': {
            const failures = Array.from({ length: 6 }, (_, index) => sample(stamp, index, now, {
                workflow: wf.build,
                priority: 'high',
                category: 'failure',
                title: 'Build watcher could not reach the CI service',
                summary: 'The run stopped before it finished.',
                error: `Attempt ${6 - index}: the CI API refused the token (403).`,
                triggerReason: loggedReason('high', ['Failed runs']),
                rules: [failedRunRule('high')],
                enrichments: ['Run failed'],
                links: [conversationLink('Open workflow', `lab-conv-build-${stamp}`, wf.build.groupId)],
                minutesAgo: 2 + index * 9,
            }));
            return [
                ...failures,
                priorityAlert(stamp, 6, now, 'medium', 'alert', 3),
                priorityAlert(stamp, 7, now, 'low', 'alert', 4),
            ];
        }
        case 'long':
            return [sample(stamp, 0, now, {
                workflow: { ...wf.mail, name: 'Customer escalations and contract renewals across every region' },
                priority: 'high',
                category: 'alert',
                title: 'A renewal worth $1.2M is at risk: Contoso Pharmaceuticals has asked to pause the rollout in three regions until the data residency review is complete',
                summary: 'Contoso\'s procurement lead replied to the renewal thread asking to pause the rollout in Germany, France and the Netherlands. '
                    + 'They cite the data residency review that legal opened last month, and ask for a call before Friday. '
                    + 'The account team has not replied yet, and the renewal closes at the end of the quarter.',
                detail: 'From: procurement@contoso.example\nSubject: RE: Renewal and rollout plan\n\n'
                    + 'Hi team,\n\nBefore we sign the renewal we need the data residency review to be complete. '
                    + 'Until then, please pause the rollout in Germany, France and the Netherlands.\n\n'
                    + 'We would also like to understand:\n- where conversation history is stored\n- how long uploaded documents are kept\n'
                    + '- whether the model provider keeps any of our prompts\n\n'
                    + 'Can we set up a call before Friday? Our legal team would like to join.\n\nThanks,\nMegan\n\n'
                    + '---\nThe agent read 14 messages in this thread and 3 attachments. '
                    + 'It matched the renewal amount from the CRM record and the deadline from the quarter\'s close date.',
                triggerReason: loggedReason('high', ['Renewals over $1M', 'Rollout paused or cancelled', 'Legal involvement']),
                rules: [
                    { name: 'Renewals over $1M', severity: 'high', reason: 'The thread names a renewal amount of $1.2M, which is over the $1M threshold this rule sets.' },
                    { name: 'Rollout paused or cancelled', severity: 'medium', reason: 'The customer asks to pause the rollout in three regions.' },
                    { name: 'Legal involvement', severity: 'low', reason: 'The customer says their legal team would like to join the call.' },
                ],
                enrichments: ['Customer: Contoso Pharmaceuticals', 'Amount: $1.2M', 'Regions: DE, FR, NL', 'Deadline: Friday', 'Thread: 14 messages', 'Attachments: 3'],
                agent: 'Account insights agent',
                links: [
                    conversationLink('Open workflow', `lab-conv-long-${stamp}`),
                    conversationLink('Open created conversation', `lab-conv-long-created-${stamp}`),
                    conversationLink('Open conversation', `lab-conv-long-thread-${stamp}`),
                ],
                minutesAgo: 2,
            })];
        case 'short':
            return [sample(stamp, 0, now, {
                workflow: { id: '', name: 'Ping', scope: 'personal' },
                priority: 'medium',
                category: 'alert',
                title: 'Ping',
                summary: 'Done.',
                minutesAgo: 1,
                legacy: true,
            })];
        case 'hostile':
            return [sample(stamp, 0, now, {
                workflow: { ...wf.mail, name: '<b>Mail</b> triage <img src=x onerror=alert(1)>' },
                priority: 'high',
                category: 'alert',
                title: '<script>alert("title")</script> Reset your password <a href="https://evil.example">here</a>',
                summary: 'Quoted from an email: <img src=x onerror="alert(\'summary\')"> Click [this link](javascript:alert(1)) to claim.',
                detail: '<iframe src="https://evil.example"></iframe>\n<style>body{display:none}</style>\n**Not bold**, `not code`.',
                // Not the runner's log line, so the card shows it, as text.
                triggerReason: 'The rule "Phishing words" matched: <em>reset your password</em>.',
                rules: [{ name: '<u>Phishing</u> words', severity: 'high', reason: '"Click here" and "reset your password" appear together.' }],
                enrichments: ['<b>chip</b>', 'javascript:alert(1)'],
                links: [
                    { label: 'Open <b>site</b>', url: 'https://evil.example/phish' },
                    { label: 'Run script', url: 'javascript:alert(1)' },
                    conversationLink('Open conversation', `lab-conv-hostile-${stamp}`),
                ],
                minutesAgo: 1,
            })];
        case 'group':
            return [priorityAlert(stamp, 0, now, 'high', 'alert', 1)];
        case 'notify-only':
            return [sample(stamp, 0, now, {
                workflow: wf.mail,
                priority: 'medium',
                category: 'alert',
                title: 'A newsletter arrived',
                summary: 'This workflow is set to notify only, so it waits in the bell.',
                minutesAgo: 1,
                delivery: 'notify_only',
            })];
        case 'old':
            return [sample(stamp, 0, now, {
                workflow: wf.security,
                priority: 'high',
                category: 'alert',
                title: 'Yesterday\'s advisory',
                summary: 'This alert is 26 hours old, so it waits in the bell.',
                minutesAgo: 26 * 60,
            })];
        case 'dialog':
        default:
            return [priorityAlert(stamp, 0, now, 'medium', 'alert', 1)];
    }
}
