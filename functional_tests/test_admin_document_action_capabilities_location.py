#!/usr/bin/env python3
# test_admin_document_action_capabilities_location.py
"""
Functional test for admin document action capabilities placement.
Version: 0.241.095
Implemented in: 0.241.089

This test ensures the Document Action Capabilities card is rendered at the
top of the Agents and Actions tab as its own card and clearly references the
Action dropdown in Chat and Workflow.
"""

from pathlib import Path
import traceback


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_admin_document_action_capabilities_card_location() -> None:
    print("🔍 Testing admin document action capabilities card placement...")

    config_content = read_text("application/single_app/config.py")
    template_content = read_text("application/single_app/templates/admin_settings.html")

    assert 'VERSION = "0.241.095"' in config_content, (
        "Expected config.py version 0.241.095 for the admin document action capabilities placement update."
    )
    assert template_content.count('id="document-action-capabilities-card"') == 1, (
        "Expected exactly one document action capabilities card in the admin settings template."
    )

    card_index = template_content.find('id="document-action-capabilities-card"')
    agents_tab_index = template_content.find('id="agents" role="tabpanel"')
    agents_config_index = template_content.find('id="agents-configuration"')

    assert card_index != -1, "Expected the admin settings template to render the document action capabilities card."
    assert agents_tab_index != -1, "Expected the admin settings template to render the Agents and Actions tab pane."
    assert agents_config_index != -1, "Expected the admin settings template to render the agents configuration card."
    assert agents_tab_index < card_index < agents_config_index, (
        "Expected the document action capabilities card to appear at the top of the Agents and Actions tab before the existing configuration cards."
    )
    assert 'Action</strong> dropdown in Chat and Workflow' in template_content, (
        "Expected the card copy to explain that these settings control the Action dropdown in Chat and Workflow."
    )
    assert 'global agent and custom action cards below' in template_content, (
        "Expected the card copy to explain that the capability settings remain separate from the cards below in the Agents and Actions tab."
    )

    print("✅ Admin document action capabilities card placement verified")


def run_tests() -> bool:
    tests = [test_admin_document_action_capabilities_card_location]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            print("✅ Test passed")
            results.append(True)
        except Exception as exc:
            print(f"❌ Test failed: {exc}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)