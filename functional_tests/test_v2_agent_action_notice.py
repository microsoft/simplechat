# test_v2_agent_action_notice.py
"""
Regression coverage for the V2 agent-selection action notice.
Version: 0.261.395
Implemented in: 0.261.395

The composer must not show a generic action warning when an agent is selected,
while actual recovery errors and unavailable-action decisions remain visible.
"""

from pathlib import Path

from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "application" / "v2_ui" / "src" / "components" / "chat"


def test_agent_selection_does_not_create_generic_recovery_notice():
    assert_app_version_at_least("0.261.395")
    notice = (CHAT / "ActionRecoveryNotice.tsx").read_text(encoding="utf-8")
    composer = (CHAT / "Composer.tsx").read_text(encoding="utf-8")
    assert "Actions are checked before sending." not in notice
    assert "hasAgent" not in notice
    assert "hasAgent=" not in composer
    assert 'role="alert"' in notice
    assert "This agent has unavailable actions" in notice
    assert "chooseActionRecovery('continue')" in notice
