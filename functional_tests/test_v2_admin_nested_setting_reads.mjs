// test_v2_admin_nested_setting_reads.mjs
//
// Companion to test_v2_admin_nested_setting_reads.py.
// Version: 0.261.260
// Implemented in: 0.261.260
//
// Runs the real V2 admin readers against the real field schema for each scenario the
// Python driver supplies, and prints what they produced as JSON. The driver owns the
// assertions, because the connection-test payload computed here is handed on to the
// server-side Web Search validator, which only Python can run.
//
// Run through the driver: `python functional_tests/test_v2_admin_nested_setting_reads.py`.
// Requires Node 22.6 or newer, which strips the TypeScript types so the real modules are
// imported.

import { readFileSync } from 'node:fs';

import './test_support/tsResolve.mjs';

const {
    buildConnectionTestPayload,
    buildFieldIndex,
    isFieldVisible,
    readStoredFieldValue,
} = await import('../application/v2_ui/src/lib/adminFields.ts');

const { computeSectionStatus } = await import('../application/v2_ui/src/lib/adminSections.ts');

const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const fieldsByKey = buildFieldIndex(input.schema);
const sectionFields = input.schema[input.section_id] ?? [];
const testField = sectionFields.find((field) => field.component === 'connection-test');
const secretField = sectionFields.find((field) => field.type === 'secret');

if (!testField) {
    console.error(`${input.section_id} declares no connection-test component.`);
    process.exit(2);
}

const results = {};
for (const [name, { settings, draft }] of Object.entries(input.scenarios)) {
    // The page drops hidden fields before it computes a status, so this does the same.
    const visibleFields = sectionFields.filter((field) =>
        isFieldVisible(field, settings, draft, fieldsByKey),
    );

    results[name] = {
        payload: buildConnectionTestPayload(testField, settings, draft, fieldsByKey),
        // An empty index reads every key as a top-level setting, which is what the
        // connection test did before the fix.
        flat_payload: buildConnectionTestPayload(testField, settings, draft, new Map()),
        visible: Object.fromEntries(
            sectionFields
                .filter((field) => field.key)
                .map((field) => [field.key, visibleFields.includes(field)]),
        ),
        status: computeSectionStatus(
            visibleFields,
            settings,
            draft,
            input.status_rule ?? undefined,
            fieldsByKey,
        ),
        stored_secret: secretField ? (readStoredFieldValue(secretField, settings) ?? null) : null,
    };
}

process.stdout.write(JSON.stringify(results));
