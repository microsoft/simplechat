# test_get_messages_agent_citation_hydration.py
"""
Functional test for /api/get_messages agent citation hydration.
Version: 0.241.116
Implemented in: 0.241.116

This test ensures the legacy chat history endpoint rebuilds assistant artifact
payloads before it filters those child records from the visible message list,
so externalized agent citations still hydrate to their full frontend payload.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / 'application' / 'single_app' / 'route_backend_conversations.py'
CONFIG_FILE = REPO_ROOT / 'application' / 'single_app' / 'config.py'


def read_text(path):
    return path.read_text(encoding='utf-8')


def read_version():
    for line in read_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def test_get_messages_route_rehydrates_agent_citation_artifacts():
    print('🔍 Testing /api/get_messages agent citation hydration wiring...')

    route_source = read_text(ROUTE_FILE)
    required_snippets = [
        'build_message_artifact_payload_map',
        'hydrate_agent_citations_from_artifacts',
        'artifact_payload_map = build_message_artifact_payload_map(all_items)',
        'all_items = filter_assistant_artifact_items(all_items)',
        'all_items = hydrate_agent_citations_from_artifacts(all_items, artifact_payload_map)',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in route_source]
    assert not missing, f'Missing route hydration snippets: {missing}'

    artifact_index = route_source.index('artifact_payload_map = build_message_artifact_payload_map(all_items)')
    filter_index = route_source.index('all_items = filter_assistant_artifact_items(all_items)')
    hydrate_index = route_source.index('all_items = hydrate_agent_citations_from_artifacts(all_items, artifact_payload_map)')

    assert artifact_index < filter_index < hydrate_index, (
        'Expected /api/get_messages to build the artifact payload map before filtering assistant artifact items '
        'and to hydrate visible citations afterwards.'
    )

    print('✅ /api/get_messages hydration wiring passed')
    return True


def test_version_alignment():
    print('🔍 Testing version alignment...')
    assert read_version() == '0.241.116'
    print('✅ Version alignment passed')
    return True


if __name__ == '__main__':
    tests = [
        test_get_messages_route_rehydrates_agent_citation_artifacts,
        test_version_alignment,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    raise SystemExit(0 if success else 1)