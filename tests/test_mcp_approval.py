"""Offline regression tests. No Codex model or TradingView tool is executed."""
import json
import queue
import subprocess
import tomllib
import unittest
from unittest.mock import Mock, patch

import sr_agent as sr


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.run = self.enterContext(patch.object(sr.subprocess, "run"))
        self.run.return_value = subprocess.CompletedProcess([], 0, "Mock response", "")
        self.cli = self.enterContext(patch.object(sr, "codex_command", return_value=["mock-codex.exe"]))
        temporary = self.enterContext(patch.object(sr.tempfile, "TemporaryDirectory"))
        # No real temporary files or subprocesses are needed for these cases.
        temporary.return_value.__enter__.return_value = str(sr.PROJECT_DIR / "__offline_mcp_test__")
        grouping = self.enterContext(patch.object(sr, "GroupingSession"))
        self.grouping = grouping.return_value
        self.grouping.target = {"symbol": sr.DEFAULT_SYMBOL}
        self.grouping.run_id = "offline-run"
        self.grouping.record = {"drawing_ids": []}
        self.grouping.finish.side_effect = ValueError("No completion record in this CLI-only mock")

    def analyze(self):
        return sr.run_support_resistance_analysis(
            sr.DEFAULT_SYMBOL, ["1H", "4H", "1D"], 3, "gpt-6-astra",
            confirmed_chart='{"tab_id":"MOCK","pane_index":0}', live_confirmed=True,
        )

    def test_no_consent_or_identity_never_launches_cli(self):
        outcome = sr.run_support_resistance_analysis(sr.DEFAULT_SYMBOL, ["1H"])
        self.assertEqual(outcome.status, "confirmation_required")
        outcome = sr.run_support_resistance_analysis(sr.DEFAULT_SYMBOL, ["1H"], live_confirmed=True)
        self.assertEqual(outcome.status, "invalid_input")
        self.run.assert_not_called()
        self.cli.assert_not_called()

    def test_only_required_mcp_tools_preapproved_and_sandbox_preserved(self):
        outcome = self.analyze()
        self.assertEqual(outcome.status, "completed_unverified")
        self.assertFalse(outcome.drawings_verified)
        self.run.assert_called_once()
        command = self.run.call_args.args[0]
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertEqual(command[command.index("--model") + 1], "gpt-6-astra")
        overrides = [command[i + 1] for i, item in enumerate(command) if item == "-c"]
        policy = tomllib.loads("\n".join(overrides))["mcp_servers"]["tradingview"]
        expected = {"chart_get_state", "tab_list", "pane_list", "chart_get_visible_range",
                    "data_get_ohlcv", "chart_set_timeframe", "draw_shape", "draw_list", "draw_get_properties"}
        self.assertEqual(set(policy["enabled_tools"]), expected)
        self.assertEqual(set(policy["tools"]), expected)
        self.assertTrue(all(item["approval_mode"] == "approve" for item in policy["tools"].values()))
        forbidden = {"draw_clear", "draw_remove_one", "ui_evaluate", "ui_click", "pine_set_source",
                     "chart_set_symbol", "chart_manage_indicator", "tab_switch", "pane_focus", "quote_get"}
        self.assertFalse(set(policy["enabled_tools"]) & forbidden)
        for flag in ("--dangerously-bypass-approvals-and-sandbox", "--approve-for-me",
                     "--ignore-rules", "--ignore-user-config", "--ask-for-approval"):
            self.assertNotIn(flag, command)
        self.assertFalse(self.run.call_args.kwargs["shell"])
        self.assertEqual(self.run.call_args.kwargs["env"]["PATH"].split(sr.os.pathsep)[0], str(sr.Path(sr.node_executable()).parent))
        self.assertIn("same verified tab/pane identity", self.run.call_args.kwargs["input"])
        self.assertIn("Never delete, replace, move or regroup existing objects", self.run.call_args.kwargs["input"])

    def test_approval_block_reported_even_with_zero_exit_code(self):
        blocker = "MCP tool call requires approval, but approval policy is never"
        for code, stdout, stderr in ((0, blocker, ""), (1, "", blocker)):
            with self.subTest(code=code):
                self.run.reset_mock()
                self.run.return_value = subprocess.CompletedProcess([], code, stdout, stderr + "\nAPI_KEY=privatevalue")
                outcome = self.analyze()
                self.assertEqual(outcome.status, "approval_blocked")
                self.assertEqual(outcome.return_code, code)
                self.assertFalse(outcome.drawings_verified)
                self.assertIn("interactive Codex/Astra", outcome.errors)
                self.assertNotIn("privatevalue", outcome.errors)
                self.run.assert_called_once()  # No automatic retry.

    def test_nonapproval_error_keeps_diagnostics_and_return_code(self):
        self.run.return_value = subprocess.CompletedProcess([], 9, "", "Connector unavailable")
        outcome = self.analyze()
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.return_code, 9)
        self.assertIn("Connector unavailable", outcome.errors)
        self.run.assert_called_once()

    def test_timeout_not_retried(self):
        self.run.side_effect = subprocess.TimeoutExpired("mock-codex", 600, output=b"partial")
        outcome = self.analyze()
        self.assertEqual(outcome.status, "timed_out")
        self.assertIn("Partial chart changes may exist", outcome.errors)
        self.run.assert_called_once()

    def test_gui_cancel_and_chart_verification_remain_required(self):
        import main
        app = main.SupportResistanceApp.__new__(main.SupportResistanceApp)
        app.root = Mock()
        app.running = False
        app.all_charts = Mock()
        app.all_charts.get.return_value = False
        app.selection = Mock(return_value=(sr.DEFAULT_SYMBOL, ["1H"], 3, sr.DEFAULT_MODEL))
        app.status = Mock()
        app.events = queue.Queue()
        app.refreshing = False
        for attr in ("progress", "find_button", "trade_button", "refresh_button"):
            setattr(app, attr, Mock())
        from tests.test_grouping import TARGET
        with patch.object(main.messagebox, "askokcancel", return_value=False), \
                patch.object(main, "ensure_selected_symbol") as verify, \
                patch.object(main, "run_support_resistance_analysis") as analysis:
            app.confirm_analysis(app.selection(), False, json.dumps(TARGET))
            verify.assert_not_called()
            analysis.assert_not_called()
        with patch.object(main, "ensure_selected_symbol", side_effect=ValueError("Symbol mismatch")) as verify, \
                patch.object(main, "run_support_resistance_analysis") as analysis:
            app.worker(app.selection(), approved_chart=json.dumps(TARGET))
            verify.assert_called_once_with(sr.DEFAULT_SYMBOL, json.dumps(TARGET), live_confirmed=True)
            analysis.assert_not_called()
            self.assertEqual(app.events.get_nowait(), ("chart_error", "Symbol mismatch"))
        self.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
