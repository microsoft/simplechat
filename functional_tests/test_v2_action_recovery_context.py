# test_v2_action_recovery_context.py
"""
Functional test for idempotent V2 action-recovery conversation ownership.
Version: 0.261.355
Implemented in: 0.261.355

Bundles and executes the real TypeScript module. Only the HTTP boundary is
replaced, with a held response; no service, model, or browser is contacted.
"""

import json
from pathlib import Path
import subprocess

from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "application" / "v2_ui"
MODULE = UI / "src" / "lib" / "actionRecovery.ts"


def test_conversation_identity_is_idempotent_and_real_changes_invalidate(tmp_path):
    assert_app_version_at_least("0.261.355")
    esbuild = UI / "node_modules" / "esbuild" / "bin" / "esbuild"
    assert esbuild.is_file(), "Restore the locked V2 UI dependencies before running this test."
    entry = tmp_path / "recovery-context.mjs"
    bundle = tmp_path / "recovery-context.bundle.mjs"
    entry.write_text(
        """
import assert from 'node:assert/strict';
import {
    actionRecoveryHeaders, clearActionRecovery, getActionRecoveryRevision,
    setActionRecoveryConversation,
} from MODULE;

const originalFetch = globalThis.fetch;
let release;
globalThis.fetch = async (url) => {
    assert.equal(url, '/api/action-recovery/context');
    return await new Promise(resolve => {
        release = () => resolve(new Response(JSON.stringify({csrf_token: 'synthetic-csrf'}), {
            headers: {'Content-Type': 'application/json'},
        }));
    });
};
try {
    setActionRecoveryConversation(null);
    const initial = getActionRecoveryRevision();
    setActionRecoveryConversation('created-chat');
    assert.equal(getActionRecoveryRevision(), initial + 1);

    const valid = actionRecoveryHeaders();
    setActionRecoveryConversation('created-chat');
    assert.equal(getActionRecoveryRevision(), initial + 1);
    release();
    const headers = await valid;
    assert.deepEqual(headers, {'X-CSRFToken': 'synthetic-csrf'});

    const stale = actionRecoveryHeaders();
    setActionRecoveryConversation('different-chat');
    release();
    await assert.rejects(stale, /selected chat context changed/);

    setActionRecoveryConversation(null);
    const anotherDraft = actionRecoveryHeaders();
    clearActionRecovery();
    setActionRecoveryConversation(null);
    release();
    await assert.rejects(anotherDraft, /selected chat context changed/);

    const controller = new AbortController();
    const aborted = actionRecoveryHeaders(controller.signal);
    controller.abort();
    release();
    await assert.rejects(aborted, /selected chat context changed/);
} finally {
    globalThis.fetch = originalFetch;
    clearActionRecovery();
}
""".replace("from MODULE", f"from {json.dumps(str(MODULE))}"),
        encoding="utf-8",
    )
    subprocess.run(
        ["node", str(esbuild), str(entry), "--bundle", "--platform=node", "--format=esm",
         "--define:import.meta.env={}", f"--outfile={bundle}", "--log-level=error"],
        cwd=UI, check=True, capture_output=True, text=True,
    )
    result = subprocess.run(
        ["node", str(bundle)], cwd=UI, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
