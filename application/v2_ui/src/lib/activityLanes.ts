// activityLanes.ts
// Turning a stream of reasoning steps into a progress report.
//
// Some work an assistant does is long, staged and countable — a tabular analysis reads a
// workbook tool call at a time, then post-processes what it found. Rendered as a flat list of
// sentences that reads as a wall of text with no sense of how much is left, which for a run
// that takes minutes is the difference between "working" and "hung".
//
// A *lane* is a named kind of staged work. Lanes are declared in one table below rather than
// branched on at the call site, so adding workflow activity later is a table entry and not a
// second copy of the progress card. Tabular analysis is the first consumer; the agent lane is
// declared alongside it because the same activity payloads already describe both.
//
// The shapes here are those of `serialize_thought_event` in route_backend_chats.py and of the
// sanitized records `route_backend_thoughts.py` returns; both carry the same `activity`
// object, so a live run and a reloaded one produce the same report.

/** One unit of staged work, as `build_tabular_activity_payload` and friends emit it. */
export interface ActivityPayload {
    [key: string]: unknown;
    activity_key?: string;
    kind?: string;
    lane_key?: string;
    plugin_name?: string;
    title?: string;
    status?: string;
    state?: string;
}

export interface LaneDefinition {
    key: string;
    /** Heading on the progress card. */
    title: string;
    /** Introduces the activity currently running. */
    currentStepPrefix: string;
    /** Said before anything has been reported. */
    initialStatus: string;
    /** Said once every activity has finished. */
    completedStatus: string;
    /** Said instead, once the lane has moved past its tool calls. */
    postProcessingInitialStatus?: string;
    postProcessingCompletedStatus?: string;
    /** Counted noun for the "3/7 tool calls" summary. */
    unit: string;
    /** Counted noun once the lane reports work that is not a tool call. */
    mixedUnit?: string;
}

interface LaneRule extends LaneDefinition {
    /** `activity.kind` values that belong to this lane. */
    kinds: string[];
    /** `activity.lane_key` values that belong to this lane. */
    laneKeys: string[];
    /** `activity.plugin_name` values that belong to this lane. */
    plugins: string[];
    /** Thought `step_type` values that belong to this lane on their own. */
    stepTypes: string[];
    /** Kinds that mean the lane has moved past gathering, which changes the wording. */
    postProcessingKinds: string[];
    /** Kinds that are a tool call rather than lane-managed work. */
    toolKinds: string[];
}

/**
 * The declared lanes, most specific first.
 *
 * Order matters only where a thought could match more than one rule; the agent lane is last
 * because it is the general case.
 */
const LANE_RULES: LaneRule[] = [
    {
        key: 'tabular',
        title: 'Tabular analysis',
        currentStepPrefix: 'Current tabular step',
        initialStatus: 'Gathering workbook evidence',
        completedStatus: 'Workbook evidence ready',
        postProcessingInitialStatus: 'Preparing workbook output',
        postProcessingCompletedStatus: 'Tabular export ready',
        unit: 'tool call',
        mixedUnit: 'step',
        kinds: ['tabular_tool_invocation', 'tabular_post_processing'],
        laneKeys: ['tabular'],
        plugins: ['TabularProcessingPlugin'],
        stepTypes: ['tabular_analysis'],
        postProcessingKinds: ['tabular_post_processing'],
        toolKinds: ['tabular_tool_invocation'],
    },
    {
        // Orchestration is declared above the agent lane and not below it because a planned run
        // dispatches capabilities that are themselves agent work: without a more specific rule the
        // step-execution thoughts would be claimed by the agent lane and the plan's own progress
        // would vanish into "Agent progress". Step executions are the countable unit here, the way
        // tool calls are for tabular; synthesis is the post-gathering phase, so it drives the same
        // wording switch tabular uses for its export.
        key: 'orchestration',
        title: 'Orchestration',
        currentStepPrefix: 'Current step',
        initialStatus: 'Planning the work',
        completedStatus: 'Plan complete',
        postProcessingInitialStatus: 'Synthesizing the answer',
        postProcessingCompletedStatus: 'Answer ready',
        unit: 'step',
        mixedUnit: 'step',
        kinds: [
            'orchestration_planning',
            'orchestration_step_execution',
            'orchestration_synthesis',
        ],
        laneKeys: ['orchestration'],
        plugins: [],
        stepTypes: [
            'orchestration_triage',
            'orchestration_planning',
            'orchestration_step',
            'orchestration_synthesis',
        ],
        postProcessingKinds: ['orchestration_synthesis'],
        toolKinds: ['orchestration_step_execution'],
    },
    {
        key: 'agent',
        title: 'Agent progress',
        currentStepPrefix: 'Current tool',
        initialStatus: 'Connecting to the selected agent',
        completedStatus: 'Response ready',
        unit: 'tool',
        kinds: [],
        laneKeys: ['agent'],
        plugins: [],
        stepTypes: ['agent_tool_call'],
        postProcessingKinds: [],
        toolKinds: [],
    },
];

/** A reasoning step, in whichever of the two shapes it arrived in. */
export interface LaneThought {
    step_type?: string;
    content?: string;
    detail?: string;
    activity?: unknown;
    step_index?: number;
}

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : value == null ? '' : String(value).trim();
}

function lower(value: unknown): string {
    return text(value).toLowerCase();
}

export function asActivityPayload(value: unknown): ActivityPayload | null {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? (value as ActivityPayload)
        : null;
}

function ruleMatchesActivity(rule: LaneRule, activity: ActivityPayload): boolean {
    return (
        rule.kinds.includes(lower(activity.kind)) ||
        rule.laneKeys.includes(lower(activity.lane_key)) ||
        rule.plugins.includes(text(activity.plugin_name))
    );
}

function ruleForThought(thought: LaneThought): LaneRule | null {
    const stepType = lower(thought.step_type);
    const activity = asActivityPayload(thought.activity);

    for (const rule of LANE_RULES) {
        if (stepType && rule.stepTypes.includes(stepType)) {
            return rule;
        }
        if (activity && ruleMatchesActivity(rule, activity)) {
            return rule;
        }
    }

    // The agent lane also opens on the sentence the server writes when it hands off, which
    // predates activity payloads and is still the only marker on some turns.
    if (lower(thought.content).startsWith('sending to agent')) {
        return LANE_RULES.find((rule) => rule.key === 'agent') ?? null;
    }

    return null;
}

export function activityStatus(activity: ActivityPayload): string {
    return lower(activity.status) || lower(activity.state);
}

export interface LaneCounters {
    total: number;
    finished: number;
    running: number;
    failed: number;
}

export interface LaneProgress {
    lane: LaneDefinition;
    /** 0-100, and never lower than it has already been for this set of steps. */
    percent: number;
    completed: boolean;
    failedCount: number;
    /** "3/7 tool calls | 1 running", or the lane's opening line when nothing is counted. */
    summary: string;
    /** The activity in flight, or the most recent thing said. */
    currentStep: string;
    /** The most recent sentence, shown under the bar. */
    latestContent: string;
}

/**
 * Fold reasoning steps into a progress report, or return null when none form a lane.
 *
 * Returning null is the normal case: an ordinary reply has reasoning steps but no staged
 * work, and those are better read as the list they are.
 *
 * The percentage ratchets. Recomputing it from scratch on each render would let the bar run
 * backwards — finishing two of two activities reads as 80%, and a third activity starting
 * would drop it to 50% — so the fold carries the highest value reached so far. Doing that
 * inside the fold rather than in component state keeps it a pure function of the list.
 */
export function buildLaneProgress(
    thoughts: LaneThought[] | undefined,
    options: { live?: boolean } = {},
): LaneProgress | null {
    if (!thoughts || thoughts.length === 0) {
        return null;
    }

    let rule: LaneRule | null = null;
    let dispatchStarted = false;
    let latestContent = '';
    let latestStepType = '';
    let completed = false;
    let maxPercent = 0;
    const activities = new Map<string, ActivityPayload>();

    thoughts.forEach((thought, index) => {
        const stepType = lower(thought.step_type);
        const content = text(thought.content);
        const matched = ruleForThought(thought);

        if (matched && (!rule || rule.key === 'agent')) {
            // A more specific lane supersedes the general agent one, which is what a tabular
            // run looks like: it dispatches an agent and then reports tabular activity.
            rule = matched;
        }

        if (stepType === 'agent_tool_call' || lower(content).startsWith('sending to agent')) {
            dispatchStarted = true;
        }
        if (content) {
            latestContent = content;
        }
        if (stepType) {
            latestStepType = stepType;
        }

        const activity = asActivityPayload(thought.activity);
        if (activity) {
            const key =
                text(activity.activity_key) ||
                text(activity.title) ||
                String(thought.step_index ?? index);
            activities.set(key, { ...(activities.get(key) ?? {}), ...activity });
        }

        if (stepType === 'generation' && lower(content).includes('responded')) {
            completed = true;
        }

        if (rule) {
            maxPercent = Math.max(
                maxPercent,
                instantaneousPercent(
                    { dispatchStarted, latestStepType, completed },
                    countActivities(activities),
                ),
            );
        }
    });

    if (!rule) {
        return null;
    }

    const lane: LaneRule = rule;
    const counters = countActivities(activities);
    const all = [...activities.values()];
    const hasPostProcessing = all.some((activity) =>
        lane.postProcessingKinds.includes(lower(activity.kind)),
    );
    // A lane whose tool kinds are declared can tell managed work apart from tool calls, and
    // counts "steps" rather than "tool calls" once it sees any.
    const hasNonToolActivity =
        lane.toolKinds.length > 0 &&
        all.some((activity) => !lane.toolKinds.includes(lower(activity.kind)));

    // A lane that declares post-processing is not finished merely because its tool calls
    // have settled. Every invocation is reported running and then completed, so between one
    // finishing and the next starting there are momentarily no running activities — without
    // this the lane would announce itself complete at 100% mid-run and then fall back.
    const activitiesSettled = counters.total > 0 && counters.running === 0;
    const isCompleted = lane.postProcessingKinds.length
        ? completed || (hasPostProcessing && activitiesSettled)
        : completed || activitiesSettled;

    const percent = isCompleted
        ? 100
        : Math.max(
              maxPercent,
              instantaneousPercent({ dispatchStarted, latestStepType, completed }, counters),
          );

    const initialStatus =
        hasPostProcessing && lane.postProcessingInitialStatus
            ? lane.postProcessingInitialStatus
            : lane.initialStatus;
    const completedStatus =
        hasPostProcessing && lane.postProcessingCompletedStatus
            ? lane.postProcessingCompletedStatus
            : lane.completedStatus;

    const summaryParts: string[] = [];
    if (counters.total > 0) {
        const unit = hasNonToolActivity ? (lane.mixedUnit ?? lane.unit) : lane.unit;
        summaryParts.push(
            `${counters.finished}/${counters.total} ${counters.total === 1 ? unit : `${unit}s`}`,
        );
    }
    if (counters.running > 0) {
        summaryParts.push(`${counters.running} running`);
    }
    if (counters.failed > 0) {
        summaryParts.push(`${counters.failed} failed`);
    }
    if (isCompleted) {
        summaryParts.push(completedStatus);
    }

    const running = [...all].reverse().find((activity) => activityStatus(activity) === 'running');
    const currentStep = running?.title
        ? `${lane.currentStepPrefix}: ${text(running.title)}`
        : options.live
          ? latestContent || initialStatus
          : `${lane.title} captured for this response`;

    return {
        lane: {
            key: lane.key,
            title: lane.title,
            currentStepPrefix: lane.currentStepPrefix,
            initialStatus,
            completedStatus,
            unit: lane.unit,
        },
        percent,
        completed: isCompleted,
        failedCount: counters.failed,
        summary: summaryParts.join(' | ') || initialStatus,
        currentStep,
        latestContent: latestContent || (isCompleted ? completedStatus : initialStatus),
    };
}

function countActivities(activities: Map<string, ActivityPayload>): LaneCounters {
    let finished = 0;
    let running = 0;
    let failed = 0;

    activities.forEach((activity) => {
        const status = activityStatus(activity);
        if (status === 'failed') {
            failed += 1;
        } else if (status === 'completed') {
            finished += 1;
        } else {
            running += 1;
        }
    });

    return { total: activities.size, finished: finished + failed, running, failed };
}

/**
 * The percentage implied by the state right now, before the ratchet is applied.
 *
 * The bands are arbitrary but load-bearing: dispatch alone is worth 15, so the bar moves as
 * soon as the request is accepted; activities occupy 35-80, so their progress dominates; and
 * an incomplete run is capped at 95 so a full bar always means finished.
 */
function instantaneousPercent(
    state: { dispatchStarted: boolean; latestStepType: string; completed: boolean },
    counters: LaneCounters,
): number {
    let percent = state.dispatchStarted ? 15 : 0;

    if (state.latestStepType === 'generation') {
        percent = Math.max(percent, 25);
    }

    if (counters.total > 0) {
        percent = Math.max(percent, 35 + Math.round((counters.finished / counters.total) * 45));
        if (counters.running > 0) {
            percent = Math.max(percent, 45);
        }
        if (counters.finished === counters.total) {
            percent = Math.max(percent, 80);
        }
    }

    if (state.completed) {
        return 100;
    }

    return Math.max(0, Math.min(95, Math.round(percent)));
}
