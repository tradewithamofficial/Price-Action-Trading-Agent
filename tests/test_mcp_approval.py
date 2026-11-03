"""No policy overrides or bypass flags are added to the tested CLI workflow."""
from pathlib import Path
import subprocess
import unittest
from tests import test_direct_analysis as direct_tests
import sr_agent as sr

class ApprovalTests(unittest.TestCase):
    setUp=direct_tests.RunnerTests.setUp
    completed=direct_tests.RunnerTests.completed
    def test_existing_configuration_is_inherited_without_new_tool_grants(self):
        sr._execute_codex('Offline prompt','gpt-6-astra',600)
        command=self.run.call_args.args[0]
        self.assertNotIn('-c',command)
        self.assertNotIn('--ignore-user-config',command)
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',command)
        self.assertNotIn('--approve-for-me',command)
        self.assertFalse(hasattr(sr,'support_resistance_mcp_arguments'))
    def test_approval_rejection_is_not_retried_even_with_final_text(self):
        def blocked(command,**kwargs):
            self.completed(command,**kwargs)
            return subprocess.CompletedProcess(command,0,stdout='',stderr='MCP tool call requires approval, but approval policy is never')
        self.run.side_effect=blocked
        outcome=sr._execute_codex('Offline prompt','gpt-6-astra',600)
        self.assertEqual(outcome.status,'approval_blocked')
        self.assertFalse(outcome.analysis_completed)
        self.assertTrue(Path(outcome.response_file).is_file())
        self.run.assert_called_once()
