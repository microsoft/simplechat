#!/usr/bin/env python3
# test_generated_artifact_workspace_promotion.py
"""
Functional test for generated artifact workspace promotion.
Version: 0.241.128
Implemented in: 0.241.128

This test ensures generated chat artifacts can be promoted into workspace
documents, that group and public promotions support approval, denial, and
requester cancellation, and that the chat and workspace UIs expose the related
actions.
"""

from pathlib import Path
import traceback


ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT / "application" / "single_app" / "route_enhanced_citations.py"
GROUP_ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_group_documents.py"
PUBLIC_ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_public_documents.py"
CHAT_MESSAGES_FILE = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"
GROUP_WORKSPACE_FILE = ROOT / "application" / "single_app" / "templates" / "group_workspaces.html"
PUBLIC_WORKSPACE_FILE = ROOT / "application" / "single_app" / "static" / "js" / "public" / "public_workspace.js"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_backend_promotion_routes() -> None:
    print("Testing generated artifact promotion backend routes...")

    route_content = read_text(ROUTE_FILE)
    group_route_content = read_text(GROUP_ROUTE_FILE)
    public_route_content = read_text(PUBLIC_ROUTE_FILE)

    assert "/api/chat_artifacts/promote" in route_content, (
        "Expected route_enhanced_citations.py to register the chat artifact promotion route."
    )
    assert "def promote_chat_artifact_to_workspace(" in route_content, (
        "Expected route_enhanced_citations.py to expose a workspace promotion handler."
    )
    assert 'generated_artifact_promotion_status="pending_approval"' in route_content, (
        "Expected group/public artifact promotions to persist a pending approval marker."
    )
    assert "create_group_notification(" in route_content, (
        "Expected group promotions to notify the group workspace."
    )
    assert "create_public_workspace_notification(" in route_content, (
        "Expected public promotions to notify the public workspace."
    )

    assert "/approve-generated-artifact" in group_route_content, (
        "Expected route_backend_group_documents.py to register a generated artifact approval endpoint."
    )
    assert "/deny-generated-artifact" in group_route_content, (
        "Expected route_backend_group_documents.py to register a generated artifact denial endpoint."
    )
    assert "/cancel-generated-artifact" in group_route_content, (
        "Expected route_backend_group_documents.py to register a generated artifact cancel endpoint."
    )
    assert "queue_generated_document_processing(" in group_route_content, (
        "Expected group approvals to queue document processing from the stored chat artifact."
    )
    assert "_cleanup_group_generated_artifact_notifications" in group_route_content, (
        "Expected group generated artifact routes to clean up pending notifications after actioning a request."
    )

    assert "/approve-generated-artifact" in public_route_content, (
        "Expected route_backend_public_documents.py to register a generated artifact approval endpoint."
    )
    assert "/deny-generated-artifact" in public_route_content, (
        "Expected route_backend_public_documents.py to register a generated artifact denial endpoint."
    )
    assert "/cancel-generated-artifact" in public_route_content, (
        "Expected route_backend_public_documents.py to register a generated artifact cancel endpoint."
    )
    assert "queue_generated_document_processing(" in public_route_content, (
        "Expected public approvals to queue document processing from the stored chat artifact."
    )
    assert "_cleanup_public_generated_artifact_notifications" in public_route_content, (
        "Expected public generated artifact routes to clean up pending notifications after actioning a request."
    )

    print("Generated artifact promotion backend checks passed")


def test_workspace_promotion_ui_wiring() -> None:
    print("Testing generated artifact promotion UI wiring...")

    chat_messages_content = read_text(CHAT_MESSAGES_FILE)
    group_workspace_content = read_text(GROUP_WORKSPACE_FILE)
    public_workspace_content = read_text(PUBLIC_WORKSPACE_FILE)

    assert "resolveGeneratedArtifactPromotionTarget" in chat_messages_content, (
        "Expected chat-messages.js to resolve a single workspace target for artifact promotion."
    )
    assert "Add to Workspace" in chat_messages_content, (
        "Expected generated artifact cards to render an Add to Workspace action."
    )
    assert "/api/chat_artifacts/promote" in chat_messages_content, (
        "Expected generated artifact cards to call the backend promotion route."
    )

    assert "approveGroupGeneratedArtifactDocument" in group_workspace_content, (
        "Expected the group workspace UI to expose a generated artifact approval handler."
    )
    assert "buildGroupGeneratedArtifactApproveButton" in group_workspace_content, (
        "Expected the group workspace UI to render an Approve action for pending generated artifacts."
    )
    assert "denyGroupGeneratedArtifactDocument" in group_workspace_content, (
        "Expected the group workspace UI to expose a generated artifact denial handler."
    )
    assert "cancelGroupGeneratedArtifactDocument" in group_workspace_content, (
        "Expected the group workspace UI to expose a generated artifact cancel handler."
    )

    assert "approvePublicGeneratedArtifactDocument" in public_workspace_content, (
        "Expected the public workspace UI to expose a generated artifact approval handler."
    )
    assert "buildPublicGeneratedArtifactApproveButton" in public_workspace_content, (
        "Expected the public workspace UI to render an Approve action for pending generated artifacts."
    )
    assert "denyPublicGeneratedArtifactDocument" in public_workspace_content, (
        "Expected the public workspace UI to expose a generated artifact denial handler."
    )
    assert "cancelPublicGeneratedArtifactDocument" in public_workspace_content, (
        "Expected the public workspace UI to expose a generated artifact cancel handler."
    )

    print("Generated artifact promotion UI checks passed")


def run_tests() -> bool:
    tests = [
        test_backend_promotion_routes,
        test_workspace_promotion_ui_wiring,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)