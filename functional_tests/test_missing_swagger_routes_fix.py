#!/usr/bin/env python3
"""
Functional test for missing swagger route decorator fix.
Version: 0.240.004
Implemented in: 0.240.004

This test ensures that the previously missing swagger decorators were added to
the approvals API route, the speech transcription route, and the approvals page route.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


def read_file_contents(*path_parts):
    """Read a repository file used by this regression test."""
    file_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..',
        *path_parts,
    )
    with open(file_path, 'r', encoding='utf-8') as handle:
        return handle.read()


def test_backend_control_center_approvals_swagger():
    """Verify the standalone approvals API route has swagger security."""
    print("🔍 Testing control center approvals API swagger integration...")

    try:
        content = read_file_contents('application', 'single_app', 'route_backend_control_center.py')
        required_block = (
            "@app.route('/api/approvals', methods=['GET'])\n"
            "    @swagger_route(security=get_auth_security())\n"
            "    @login_required\n"
            "    def api_get_approvals():"
        )

        if required_block not in content:
            print('❌ Standalone approvals API route is missing swagger integration')
            return False

        print('✅ Standalone approvals API route has swagger integration')
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_backend_speech_swagger():
    """Verify the speech transcription route imports and uses swagger security."""
    print("🔍 Testing speech route swagger integration...")

    try:
        content = read_file_contents('application', 'single_app', 'route_backend_speech.py')

        if 'from swagger_wrapper import swagger_route, get_auth_security' not in content:
            print('❌ Speech route file is missing swagger imports')
            return False

        required_block = (
            "@app.route('/api/speech/transcribe-chat', methods=['POST'])\n"
            "    @swagger_route(security=get_auth_security())\n"
            "    @login_required\n"
            "    def transcribe_chat_audio():"
        )

        if required_block not in content:
            print('❌ Speech transcription route is missing swagger integration')
            return False

        print('✅ Speech transcription route has swagger integration')
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_frontend_approvals_swagger():
    """Verify the approvals page route has swagger security."""
    print("🔍 Testing approvals page swagger integration...")

    try:
        content = read_file_contents('application', 'single_app', 'route_frontend_control_center.py')
        required_block = (
            "@app.route('/approvals', methods=['GET'])\n"
            "    @swagger_route(security=get_auth_security())\n"
            "    @login_required\n"
            "    @user_required\n"
            "    def approvals():"
        )

        if required_block not in content:
            print('❌ Approvals page route is missing swagger integration')
            return False

        print('✅ Approvals page route has swagger integration')
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_backend_control_center_approvals_swagger,
        test_backend_speech_swagger,
        test_frontend_approvals_swagger,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)