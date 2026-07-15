# test_personal_agent_user_id_saved.py
#!/usr/bin/env python3
"""
Functional test for personal agent user_id persistence.
Version: 0.250.068
Implemented in: 0.236.050; updated in: 0.250.068

This test ensures personal agent create and update operations bind the persisted
payload to the authorized user instead of trusting caller-supplied ownership.
"""

import sys
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
sys.path.insert(0, str(SINGLE_APP_ROOT))

import functions_personal_agents  # noqa: E402


class FakePersonalAgentContainer:
    def __init__(self):
        self.existing = None
        self.saved = []

    def read_item(self, *, item, partition_key):
        del item, partition_key
        return dict(self.existing) if self.existing else None

    def upsert_item(self, *, body):
        saved = dict(body)
        self.saved.append(saved)
        return saved


def test_personal_agent_user_id_saved():
    container = FakePersonalAgentContainer()
    payload = {
        'id': 'personal-agent-1',
        'name': 'personal_agent',
        'display_name': 'Personal Agent',
        'description': 'Test agent',
        'instructions': 'Help the user.',
        'user_id': 'forged-owner',
    }

    with (
        patch.object(functions_personal_agents, 'cosmos_personal_agents_container', container),
        patch.object(functions_personal_agents, 'ensure_governance_access'),
        patch.object(
            functions_personal_agents,
            'sanitize_agent_payload',
            side_effect=lambda value: dict(value),
        ),
        patch.object(
            functions_personal_agents,
            'keyvault_agent_save_helper',
            side_effect=lambda value, *args, **kwargs: dict(value),
        ),
        patch.object(functions_personal_agents, 'bump_chat_bootstrap_user_cache_version'),
    ):
        created = functions_personal_agents.save_personal_agent(
            'authorized-owner',
            payload,
        )
        container.existing = dict(created)
        updated = functions_personal_agents.save_personal_agent(
            'authorized-owner',
            {**payload, 'description': 'Updated agent'},
            actor_user_id='authorized-editor',
        )

    assert len(container.saved) == 2
    assert created['user_id'] == 'authorized-owner'
    assert created['created_by'] == 'authorized-owner'
    assert created['last_updated']
    assert updated['user_id'] == 'authorized-owner'
    assert updated['created_at'] == created['created_at']
    assert updated['modified_by'] == 'authorized-editor'
    assert updated['last_updated']

    print("✅ Personal agent save user_id persistence verified.")


def run_tests():
    tests = [test_personal_agent_user_id_saved]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            print("✅ Test passed")
            results.append(True)
        except Exception as exc:
            print(f"❌ Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)
