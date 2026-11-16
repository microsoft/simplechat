// orchestrationExports.ts

import type { Json } from './types';
import type { OrchestrationStep } from './orchestration';

/** Arguments accepted by execute_render_file; source identity remains a named input binding. */
export interface OrchestrationFileSpecification {
    file_name: string;
    output_format: string;
    profile: string;
    options: Json;
}

export function plannedFileSpecification(step: OrchestrationStep): OrchestrationFileSpecification | null {
    if (step.capability_id !== 'render_file' || step.role !== 'render') return null;
    const args = step.arguments;
    if (typeof args.file_name !== 'string' || !args.file_name
        || typeof args.output_format !== 'string' || !args.output_format
        || typeof args.profile !== 'string' || !args.profile) return null;
    if (args.options != null && (typeof args.options !== 'object' || Array.isArray(args.options))) {
        return null;
    }
    return {
        file_name: args.file_name, output_format: args.output_format, profile: args.profile,
        options: (args.options as Json | undefined) ?? {},
    };
}

/** Sanitized descriptors from get_generated_file_export_catalog, not a client-side format list. */
export interface OrchestrationExportProfile {
    profile: string;
    source_kinds: string[];
    required_options: string[];
    supported_options: string[];
    requires_complete: boolean;
    options_schema: Json;
    input_schema: Json;
}

export interface OrchestrationExportFormat {
    format_id: string;
    aliases: string[];
    file_extension: string;
    media_type: string;
    renderer_version: number;
    profiles: OrchestrationExportProfile[];
    streaming: boolean;
    rich_media: boolean;
    dependencies: string[];
    default_limits: Record<string, number>;
    office_default_limits?: Record<string, number>;
    max_output_bytes_required: boolean;
    failure_codes: string[];
    validation_failures_retryable: boolean;
    retryable_failure_codes: string[];
}
