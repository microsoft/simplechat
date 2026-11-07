// assistLimits.ts
// The longest instruction each AI-assist editor accepts.
//
// Each value must stay at or below the server's own limit, so the counter rejects anything the
// server would otherwise cut short: `MAX_INSTRUCTION_LENGTH` in functions_block_revision_assist.py
// and functions_message_image_revisions.py, and `EDIT_INSTRUCTION_LIMIT` in
// functions_orchestration_plan_revisions.py. functional_tests/test_v2_assist_thread.py checks the
// two sides against each other.

export const ASSIST_INSTRUCTION_LIMITS = {
    block: 2000,
    image: 2000,
    plan: 2000,
} as const;

export type AssistInstructionKind = keyof typeof ASSIST_INSTRUCTION_LIMITS;
