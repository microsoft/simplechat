// file_source_field_rules_probe.ts
//
// Runs the V2 group file source editor's real field rules on inputs from a JSON file and prints the
// results as JSON, so a Python test can hold them against the server's own normalizers and routes.
// Version: 0.261.171
// Implemented in: 0.261.171
//
// Bundled with the esbuild the V2 app already provides and executed under node by
// test_group_file_source_sync_fields.py. The request carries:
//   - `paths` and `tags`: raw text, answered with `normalizeSelectedPath` and `normalizeFixedTag`;
//   - `sources`: stored projections, answered with the write the editor sends for each one opened
//     and saved untouched (`draftFromSource` then `buildFileSourceWrite`);
//   - `edits`: a projection plus the typed paths, typed tags and choices a manager enters, answered
//     with the write the editor sends after applying them through the editor's own helpers.

import { readFileSync } from 'node:fs';
import {
    buildFileSourceWrite,
    draftFromSource,
    normalizeFixedTag,
    normalizeSelectedPath,
    withFixedTag,
    withSelectedPath,
    type FileSourceDraft,
} from '../../application/v2_ui/src/lib/fileSourceFields';
import type { WorkspaceSyncSource } from '../../application/v2_ui/src/lib/types';

interface EditRequest {
    source: WorkspaceSyncSource;
    add_paths?: string[];
    add_tags?: string[];
    folder_tag_mode?: string;
    remote_delete_policy?: string;
}

interface ProbeRequest {
    paths?: string[];
    tags?: string[];
    sources?: WorkspaceSyncSource[];
    edits?: EditRequest[];
}

function applyEdit(edit: EditRequest): { write: unknown; errors: string[] } {
    let draft: FileSourceDraft = draftFromSource(edit.source, 1);
    const errors: string[] = [];
    for (const raw of edit.add_paths ?? []) {
        const result = withSelectedPath(draft.selectedPaths, raw);
        if ('error' in result) {
            errors.push(result.error);
        } else {
            draft = { ...draft, selectedPaths: result.paths };
        }
    }
    for (const raw of edit.add_tags ?? []) {
        const result = withFixedTag(draft.fixedTags, raw);
        if ('error' in result) {
            errors.push(result.error);
        } else {
            draft = { ...draft, fixedTags: result.tags };
        }
    }
    if (edit.folder_tag_mode !== undefined) {
        draft = { ...draft, folderTagMode: edit.folder_tag_mode };
    }
    if (edit.remote_delete_policy !== undefined) {
        draft = { ...draft, remoteDeletePolicy: edit.remote_delete_policy };
    }
    return { write: buildFileSourceWrite(draft), errors };
}

const request = JSON.parse(readFileSync(process.argv[2], 'utf8')) as ProbeRequest;
const response = {
    paths: (request.paths ?? []).map((raw) => normalizeSelectedPath(raw)),
    tags: (request.tags ?? []).map((raw) => normalizeFixedTag(raw)),
    writes: (request.sources ?? []).map((source) => buildFileSourceWrite(draftFromSource(source, 1))),
    edits: (request.edits ?? []).map((edit) => applyEdit(edit)),
};
process.stdout.write(JSON.stringify(response));
