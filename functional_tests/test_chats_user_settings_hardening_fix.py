#!/usr/bin/env python3
"""
Functional test for chats user settings hardening fix.
Version: 0.238.025
Implemented in: 0.238.025

This test ensures that malformed user settings documents are safely normalized
and do not crash the /chats page path that reads nested settings values.
"""

# pyright: reportMissingImports=false

import os
import sys
import types

from flask import Flask, session


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


def _install_auth_stub():
    sys.modules['functions_authentication'] = types.SimpleNamespace(
        get_user_profile_image=lambda: None
    )


class FakeContainer:
    def __init__(self, doc):
        self.doc = doc
        self.upsert_calls = []

    def read_item(self, item, partition_key):
        return self.doc

    def upsert_item(self, body):
        self.doc = body
        self.upsert_calls.append(body)


def test_get_user_settings_repairs_non_dict_settings():
    print("🔍 Testing non-dict settings repair...")

    import functions_settings

    _install_auth_stub()

    fake_doc = {
        'id': 'user-1',
        'settings': 'corrupted-value',
        'display_name': 'Existing Name',
    }
    fake_container = FakeContainer(fake_doc)
    functions_settings.cosmos_user_settings_container = fake_container

    app = Flask(__name__)
    app.secret_key = 'test-secret'

    with app.test_request_context('/'):
        session['user'] = {
            'preferred_username': 'user1@example.com',
            'name': 'User One',
        }

        result = functions_settings.get_user_settings('user-1')

    assert isinstance(result.get('settings'), dict), 'settings should be normalized to a dict'
    assert result['settings'].get('profileImage') is None, 'profileImage should be set to None by stub'
    assert len(fake_container.upsert_calls) >= 1, 'repaired document should be upserted'

    print("✅ Non-dict settings are repaired and persisted")
    return True


def test_get_user_settings_repairs_missing_settings_key():
    print("🔍 Testing missing settings key repair...")

    import functions_settings

    _install_auth_stub()

    fake_doc = {
        'id': 'user-2',
        'display_name': 'User Two',
    }
    fake_container = FakeContainer(fake_doc)
    functions_settings.cosmos_user_settings_container = fake_container

    app = Flask(__name__)
    app.secret_key = 'test-secret'

    with app.test_request_context('/'):
        session['user'] = {
            'preferred_username': 'user2@example.com',
            'name': 'User Two',
        }

        result = functions_settings.get_user_settings('user-2')

    assert isinstance(result.get('settings'), dict), 'missing settings key should be initialized as dict'
    assert len(fake_container.upsert_calls) >= 1, 'initialized document should be upserted'

    print("✅ Missing settings key is initialized and persisted")
    return True


if __name__ == '__main__':
    tests = [
        test_get_user_settings_repairs_non_dict_settings,
        test_get_user_settings_repairs_missing_settings_key,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            results.append(test())
        except Exception as e:
            print(f"❌ {test.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
