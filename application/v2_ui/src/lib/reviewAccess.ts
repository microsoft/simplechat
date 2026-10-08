// reviewAccess.ts
// Who may open each part of the admin Review center.
//
// Mirrors the server's decorators so the interface only offers what the server will answer:
// feedback_admin_required with enabled_required("enable_user_feedback") for Feedback, and
// safety_violation_admin_required with content_checks_report_enabled for Safety. The server
// stays the authority; a stale bootstrap only ever shows a section that then reports it is
// unavailable, never data the server would refuse.

export type ReviewSectionId = 'feedback' | 'safety';

export interface ReviewAccessInput {
    roles: readonly string[];
    features: Readonly<Record<string, boolean | undefined>>;
    settings: Readonly<Record<string, unknown>>;
}

interface BootstrapLike {
    user?: { roles?: readonly string[] | null } | null;
    features?: Readonly<Record<string, boolean | undefined>> | null;
    settings?: unknown;
}

/** The parts of the bootstrap payload the access rules read. */
export function reviewAccessInput(data: BootstrapLike | null | undefined): ReviewAccessInput {
    const settings = data?.settings;
    return {
        roles: Array.isArray(data?.user?.roles) ? data.user.roles : [],
        features: data?.features ?? {},
        settings: settings && typeof settings === 'object' && !Array.isArray(settings)
            ? (settings as Record<string, unknown>)
            : {},
    };
}

/**
 * Feedback review: the FeedbackAdmin role when Admin Settings requires it, otherwise Admin,
 * and only while user feedback is turned on.
 */
export function canReviewFeedback(input: ReviewAccessInput): boolean {
    if (input.features.enable_user_feedback !== true) return false;
    return input.settings.require_member_of_feedback_admin === true
        ? input.roles.includes('FeedbackAdmin')
        : input.roles.includes('Admin');
}

/**
 * Safety review: the SafetyViolationAdmin role when Admin Settings requires it, otherwise
 * Admin, and only while content safety or content screening is on.
 */
export function canReviewSafety(input: ReviewAccessInput): boolean {
    if (!(input.features.enable_content_safety === true || input.features.enable_content_screening === true)) {
        return false;
    }
    return input.settings.require_member_of_safety_violation_admin === true
        ? input.roles.includes('SafetyViolationAdmin')
        : input.roles.includes('Admin');
}

/** The sections this user may open, in the order the rail lists them. */
export function reviewSections(input: ReviewAccessInput): ReviewSectionId[] {
    const sections: ReviewSectionId[] = [];
    if (canReviewFeedback(input)) sections.push('feedback');
    if (canReviewSafety(input)) sections.push('safety');
    return sections;
}

/** Where /admin/review leads: the first section this user may open, or null for none. */
export function defaultReviewPath(input: ReviewAccessInput): string | null {
    const [first] = reviewSections(input);
    return first ? `/admin/review/${first}` : null;
}

/**
 * Whether the Approvals page offers its Safety remediation category: the roles that can act
 * on warn, suspend and block requests or raise them. The approvals API still decides which
 * requests each person sees.
 */
export function canSeeSafetyRemediationApprovals(roles: readonly string[]): boolean {
    return roles.includes('Admin') || roles.includes('ControlCenterAdmin') || roles.includes('SafetyViolationAdmin');
}
