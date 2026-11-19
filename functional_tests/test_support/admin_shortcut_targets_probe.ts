// admin_shortcut_targets_probe.ts
//
// Resolves Latest Features admin shortcuts with the real V2 resolver, so
// test_v2_admin_parity.py can hold the shipped catalogue to it instead of to a second copy of its
// rules. Reads {nav, rendered, actions} as JSON from the file named by argv[2] and prints one
// resolved target per action.

import { readFileSync } from 'node:fs';
import { resolveAdminActionTarget } from '../../application/v2_ui/src/lib/latestFeatures';

const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const rendered = new Set<string>(input.rendered);
const targets = input.actions.map((action: { admin_tab?: string; admin_section?: string }) =>
    resolveAdminActionTarget(action, input.nav, rendered),
);
process.stdout.write(JSON.stringify(targets));
