# test_v2_chat_picker_search.py
"""
Functional tests for V2 chat picker matching and public model search metadata.
Version: 0.261.395
Implemented in: 0.261.395

Executes the production TypeScript helpers through the existing esbuild toolchain.
Node's explicit assertions remain active under optimized Python. Browser focus,
scrolling, selection, and request behavior are covered by the companion UI suite.
"""

import json
import subprocess
from pathlib import Path

import pytest

from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "application" / "v2_ui"


@pytest.fixture(scope="module")
def search_bundle(tmp_path_factory):
    bundle = tmp_path_factory.mktemp("picker-search") / "search.cjs"
    dropdown = UI / "src" / "components" / "ui" / "Dropdown.tsx"
    models = UI / "src" / "lib" / "models.ts"
    entry = (
        f"exports.filterDropdownOptions = require({json.dumps(str(dropdown))}).filterDropdownOptions;\n"
        f"exports.modelSearchText = require({json.dumps(str(models))}).modelSearchText;\n"
    )
    subprocess.run([
        "node", str(UI / "node_modules" / "esbuild" / "bin" / "esbuild"),
        "--bundle", "--platform=node", "--format=cjs", "--loader=tsx",
        "--define:import.meta.env={}", f"--outfile={bundle}", "--log-level=error",
    ], input=entry, check=True, capture_output=True, text=True)
    return bundle


def run_probe(bundle, source):
    result = subprocess.run(
        ["node", "-e", source, str(bundle)], capture_output=True, text=True,
    )
    if result.returncode:
        raise AssertionError(f"Picker search probe failed:\n{result.stdout}\n{result.stderr}")


def test_implementation_version():
    assert_app_version_at_least("0.261.395")


def test_names_descriptions_scopes_and_empty_queries(search_bundle):
    run_probe(search_bundle, r"""
const assert = require('node:assert/strict');
const {filterDropdownOptions: filter} = require(process.argv[1]);
const options = [
    {value: 'one', label: 'Weekly brief', description: 'Forecast narrative', group: 'personal'},
    {value: 'two', label: 'Response plan', description: 'Incident triage', group: 'group'},
    {value: 'three', label: 'Minimal prompt'},
];
const original = JSON.stringify(options);
const values = query => filter(options, query).map(option => option.value);
assert.deepEqual(values('WEEKLY'), ['one']);
assert.deepEqual(values('  forecast  '), ['one']);
assert.deepEqual(values('triage'), ['two']);
assert.deepEqual(values('personal'), ['one']);
assert.deepEqual(values('unknown'), []);
assert.equal(filter(options, ''), options);
assert.equal(filter(options, ' \t '), options);
assert.deepEqual(filter([], 'anything'), []);
assert.equal(JSON.stringify(options), original);
const many = Array.from({length: 120}, (_, i) => ({value: String(i), label: `Agent ${i}`}));
assert.equal(filter(many, 'Agent').length, 120);
assert.deepEqual(filter(many, 'Agent 119').map(option => option.value), ['119']);
""")


def test_model_names_publishers_and_families(search_bundle):
    run_probe(search_bundle, r"""
const assert = require('node:assert/strict');
const {filterDropdownOptions: filter, modelSearchText} = require(process.argv[1]);
const models = [
    {selection_key: 'east:gpt', display_name: 'Daily writer', model_name: 'gpt-4.1',
        deployment_name: 'writer-east', provider: 'aoai',
        profile: {displayName: 'GPT-4.1', publisher: 'openai'}},
    {selection_key: 'west:claude', display_name: 'Review model', model_name: 'claude-sonnet-4-5',
        provider: 'custom', profile: {publisher: 'anthropic'}},
    {selection_key: 'east:grok', display_name: 'Quick answers', model_name: 'grok-4',
        provider: 'new_foundry', profile: {publisher: 'xai'}},
    {selection_key: 'local:llama', display_name: 'Local reasoning', model_name: 'llama-4',
        provider: 'custom', profile: {publisher: 'meta'}},
    {selection_key: 'legacy:gpt', deployment_name: 'legacy-deployment',
        profile: {displayName: 'Legacy GPT', publisher: 'openai'}},
];
const original = JSON.stringify(models);
const options = models.map(model => ({
    value: model.selection_key, label: model.display_name || model.deployment_name,
    searchText: modelSearchText(model),
}));
const values = query => filter(options, query).map(option => option.value);
assert.deepEqual(values('  OPENAI  '), ['east:gpt', 'legacy:gpt']);
assert.deepEqual(values('anthropic'), ['west:claude']);
assert.deepEqual(values('grok'), ['east:grok']);
assert.deepEqual(values('xAI'), ['east:grok']);
assert.deepEqual(values('llama'), ['local:llama']);
assert.deepEqual(values('meta'), ['local:llama']);
assert.deepEqual(values('writer-east'), ['east:gpt']);
assert.deepEqual(values('Legacy GPT'), ['legacy:gpt']);
assert.equal(JSON.stringify(models), original);
const sameNames = [
    {value: 'east:model', label: 'Same model', searchText: 'OpenAI'},
    {value: 'west:model', label: 'Same model', searchText: 'OpenAI'},
];
assert.deepEqual(filter(sameNames, 'openai').map(option => option.value), ['east:model', 'west:model']);
""")


def test_missing_metadata_and_api_compatibility_do_not_invent_vendors(search_bundle):
    run_probe(search_bundle, r"""
const assert = require('node:assert/strict');
const {filterDropdownOptions: filter, modelSearchText} = require(process.argv[1]);
for (const model of [
    {display_name: 'Private model'},
    {display_name: 'Private model', profile: null},
    {display_name: 'Private model', profile: {}},
    {display_name: 'Private model', profile: {publisher: ''}},
    {display_name: 'Private model', provider: 'custom'},
    {display_name: 'Private model', provider: 'openai_compatible'},
]) {
    const options = [{value: 'private', label: model.display_name, searchText: modelSearchText(model)}];
    assert.equal(filter(options, 'private').length, 1);
    for (const vendor of ['OpenAI', 'Anthropic', 'Unspecified publisher']) {
        assert.equal(filter(options, vendor).length, 0, JSON.stringify({model, vendor}));
    }
}
assert.ok(modelSearchText({provider: 'aoai'}).includes('OpenAI'));
assert.equal(modelSearchText({}), '');
assert.equal(modelSearchText({profile: {publisher: 'blackforestlabs'}}).includes('Black Forest Labs'), true);
assert.equal(modelSearchText({
    display_name: 'Private', api_key: 'test-placeholder', endpoint: 'internal-only.example.test',
}).includes('test-placeholder'), false);
""")
