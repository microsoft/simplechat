# test_m365_workflow_binding.py
"""
Functional tests for explicit Microsoft 365 workflow execution bindings.
Version: 0.261.029
Implemented in: 0.261.029

Material changes invalidate approval references; labels and runtime status do
not. Paused runs remain nonterminal and never acquire an implicit Run as user.
"""

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "application" / "single_app" / "functions_m365_workflow_binding.py"
)
SPEC = importlib.util.spec_from_file_location("m365_workflow_binding", MODULE_PATH)
BINDING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BINDING)


class WorkflowBindingTests(unittest.TestCase):
    def test_run_as_is_explicit(self):
        workflow = {"id": "workflow", "user_id": "owner", "task_prompt": "Read files"}
        result = BINDING.normalize_workflow_run_as(workflow, {})
        self.assertEqual(result["m365_run_as_user_id"], "")
        self.assertIsNone(result["m365_binding_approval_id"])

    def test_material_change_drops_old_reference(self):
        original = {"id": "workflow", "user_id": "owner", "task_prompt": "Read files"}
        BINDING.normalize_workflow_run_as(original, {"m365_run_as_user_id": "reader"})
        original["m365_binding_approval_id"] = "approval"
        changed = {**original, "task_prompt": "Send mail"}
        BINDING.normalize_workflow_run_as(changed, {}, original)
        self.assertNotEqual(changed["m365_revision"], original["m365_revision"])
        self.assertIsNone(changed["m365_binding_approval_id"])

    def test_label_and_status_preserve_revision(self):
        original = {"id": "workflow", "task_prompt": "Read files"}
        BINDING.normalize_workflow_run_as(original, {"m365_run_as_user_id": "reader"})
        original["m365_binding_approval_id"] = "approval"
        renamed = {**original, "name": "New label", "status": "running"}
        BINDING.normalize_workflow_run_as(renamed, {}, original)
        self.assertEqual(renamed["m365_revision"], original["m365_revision"])
        self.assertEqual(renamed["m365_binding_approval_id"], "approval")

    def test_new_action_capabilities_change_fingerprint(self):
        workflow = {"id": "workflow", "m365_run_as_user_id": "reader"}
        before = BINDING.workflow_execution_fingerprint(
            workflow, [{"id": "action", "enabled_functions": ["get_my_messages"]}]
        )
        after = BINDING.workflow_execution_fingerprint(
            workflow, [{"id": "action", "enabled_functions": ["send_mail"]}]
        )
        self.assertNotEqual(before, after)

    def test_waiting_run_does_not_complete(self):
        result = BINDING.build_waiting_workflow_result(
            {"id": "workflow"},
            {"id": "run", "status": "running"},
            {"status": "awaiting_run_as_approval", "approval_id": "approval"},
        )
        status = BINDING.workflow_result_runtime_status(result)
        self.assertEqual(status, "awaiting_run_as_approval")
        self.assertFalse(result["success"])
        self.assertTrue(result["pending"])
        self.assertIsNone(result["run"]["completed_at"])
        self.assertEqual(result["workflow_updates"]["active_run_id"], "run")


if __name__ == "__main__":
    unittest.main()
