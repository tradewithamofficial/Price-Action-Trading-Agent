"""Offline fixtures only: fake TradingView in Node, fake CLI, and Tk with mocked readers."""
from copy import deepcopy
import json
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import main
import sr_agent as sr
import sr_grouping as grouping
from tests.test_grouping import OfflineSession, TARGET, OLD, NEW


class OfflineTradeSession(grouping.TradeSetupSession, OfflineSession):
    pass


def result_record(session, count, sr_drawings=None):
    setups = []
    for rank in range(1, count + 1):
        drawings = [{"id": f"setup{rank}_{role}", "role": role, "shape": "horizontal_line",
                     "points": [{"time": 1, "price": rank * 10 + index}],
                     "properties": {"text": f"Setup {rank} | {role}", "linecolor": grouping.SETUP_COLORS[rank-1]}}
                    for index,role in enumerate(("entry", "confirmation", "invalidation", "target1"))]
        setups.append({"rank": rank, "direction": "LONG" if rank % 2 else "SHORT", "strategy_type": "Breakout/retest",
                       "reasoning": "Offline example of conditional market structure reasoning.",
                       "entry_area": "Retest area", "confirmation": "Wait for the confirming candle.",
                       "invalidation": "Beyond the structural invalidation level", "target1": "Next relevant level",
                       "target2": None, "risk_reward": None, "cancel_conditions": "Cancel if structure fails.", "drawings": drawings})
    explanation = ("Setup 1 — Primary\nConditional LONG breakout/retest example. Wait for confirmation; "
                   "cancel if structure fails. This is synthetic offline test text, not market analysis."
                   if count else "NO TRADE / WAIT — Offline example: structure lacks confirmation and no credible entry is available.")
    return {"schema": 1, "run_id": session.run_id, "target": session.target, "status": "complete", "errors": [],
            "decision": "setups" if count else "wait", "final_analysis": explanation,
            "setups": setups, "sr_drawings": sr_drawings or []}


def add_drawings(session, data):
    drawings = data["sr_drawings"] + [d for s in data["setups"] for d in s["drawings"]]
    session.state["drawings"] += [{k:deepcopy(v) for k,v in d.items() if k != "role"} for d in drawings]


class SetupGroupingTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.session = OfflineTradeSession(self.directory)
        self.session.state["groups"] = [{"id": "sr", "name": grouping.GROUP_NAME, "ids": ["old"]}]
        self.session.prepare()

    def test_zero_one_two_three_real_setups_and_sr_preservation(self):
        for count in range(4):
            with self.subTest(count=count):
                session = OfflineTradeSession(self.directory)
                session.state["groups"] = deepcopy(self.session.state["groups"])
                session.prepare()
                data = result_record(session, count)
                add_drawings(session, data)
                self.assertEqual(session.finish(json.dumps(data)), count)
                self.assertEqual(session.creates, count)
                self.assertEqual(session.state["drawings"][0], OLD)
                self.assertEqual(session.state["groups"][0], self.session.state["groups"][0])
                self.assertEqual([g["name"] for g in session.state["groups"][1:]], list(grouping.SETUP_GROUP_NAMES[:count]))
                record = json.loads(session.path.read_text())
                self.assertEqual(record["last_verification_status"], "verified")
                self.assertEqual(record["setup_count"], count)

    def test_ambiguous_existing_setup_group_blocks_without_ai_or_changes(self):
        self.session.state["groups"].append({"id": "foreign", "name": grouping.SETUP_GROUP_NAMES[0], "ids": ["old"]})
        with self.assertRaisesRegex(ValueError, "ambiguous ownership"):
            self.session.prepare()
        self.assertEqual(self.session.creates, 0)

    def test_owned_existing_setup_is_verified_but_never_overwritten(self):
        data = result_record(self.session, 1)
        add_drawings(self.session, data)
        self.session.finish(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "existing ownership verified"):
            self.session.prepare()
        self.assertEqual(self.session.creates, 1)
        self.session.state["drawings"][1]["properties"]["text"] = "edited by operator"
        with self.assertRaisesRegex(ValueError, "ambiguous ownership"):
            self.session.prepare()

    def test_changed_sr_objects_block_all_setup_group_creation(self):
        data = result_record(self.session, 2)
        add_drawings(self.session, data)
        self.session.state["drawings"][0]["properties"]["text"] = "changed"
        with self.assertRaisesRegex(ValueError, "existing drawing changed"):
            self.session.finish(json.dumps(data))
        self.assertEqual(self.session.creates, 0)

    def test_second_group_failure_preserves_first_group_and_all_drawings(self):
        data = result_record(self.session, 3)
        add_drawings(self.session, data)
        before = deepcopy(self.session.state["drawings"])
        self.session.state["failRenameName"] = grouping.SETUP_GROUP_NAMES[1]
        with self.assertRaisesRegex(ValueError, "rename failed"):
            self.session.finish(json.dumps(data))
        self.assertEqual(self.session.creates, 2)
        self.assertEqual(self.session.state["drawings"], before)
        self.assertEqual(self.session.state["groups"][1]["name"], grouping.SETUP_GROUP_NAMES[0])
        self.assertEqual(len(self.session.record["groups"]), 2)
        self.assertTrue(self.session.analysis_completed)

    def test_membership_and_color_or_coordinates_must_match(self):
        data = result_record(self.session, 1)
        add_drawings(self.session, data)
        original = deepcopy(self.session.state["drawings"][1])
        for key,value in (("points", [{"time":1,"price":999}]), ("properties", {"text":"wrong","linecolor":"#000000"})):
            self.session.state["drawings"][1] = deepcopy(original)
            self.session.state["drawings"][1][key] = value
            with self.assertRaises(ValueError):
                self.session.finish(json.dumps(data))
        self.assertEqual(self.session.creates, 0)
        self.session.state["drawings"][1] = deepcopy(original)
        self.session.fault = lambda result,state: state["groups"][-1]["ids"].append("old")
        with self.assertRaisesRegex(ValueError, "membership"):
            self.session.finish(json.dumps(data))

    def test_optional_sr_only_when_group_absent_and_new_ids_verified(self):
        sr_drawings = [dict(deepcopy(d), role=role) for d,role in zip(NEW,("support","resistance"))]
        data = result_record(self.session, 1, sr_drawings)
        add_drawings(self.session, data)
        with self.assertRaisesRegex(ValueError, "Existing S/R group"):
            self.session.finish(json.dumps(data))
        self.assertEqual(self.session.creates, 0)
        fresh = OfflineTradeSession(self.directory)
        fresh.prepare()
        data = result_record(fresh, 1, sr_drawings)
        add_drawings(fresh, data)
        self.assertEqual(fresh.finish(json.dumps(data)), 1)
        self.assertEqual([g["name"] for g in fresh.state["groups"]], [grouping.GROUP_NAME,grouping.SETUP_GROUP_NAMES[0]])

    def test_invalid_or_missing_final_record_and_fake_placeholders_rejected(self):
        data = result_record(self.session, 1)
        variants = ["raw tool logs", "[]", "{}", json.dumps(dict(data,status="incomplete")),
                    json.dumps(dict(data,final_analysis="done")), json.dumps(dict(data,run_id="wrong"))]
        for text in variants:
            with self.subTest(text=text[:25]), self.assertRaises(ValueError):
                grouping.read_trade_completion(text, self.session.run_id, TARGET)
        data["setups"][0]["drawings"] = []
        with self.assertRaisesRegex(ValueError, "real drawings"):
            grouping.read_trade_completion(json.dumps(data),self.session.run_id,TARGET)

    def test_duplicate_ids_bad_rank_and_fourth_setup_rejected(self):
        data = result_record(self.session, 2)
        data["setups"][1]["drawings"][0]["id"] = data["setups"][0]["drawings"][0]["id"]
        with self.assertRaisesRegex(ValueError,"duplicate"):
            grouping.read_trade_completion(json.dumps(data),self.session.run_id,TARGET)
        data = result_record(self.session,1)
        data["setups"][0]["rank"] = 3
        with self.assertRaisesRegex(ValueError,"ranks"):
            grouping.read_trade_completion(json.dumps(data),self.session.run_id,TARGET)
        data["setups"] *= 4
        with self.assertRaisesRegex(ValueError,"zero to three"):
            grouping.read_trade_completion(json.dumps(data),self.session.run_id,TARGET)


class SetupExecutionTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.session = OfflineTradeSession(self.directory)
        self.enterContext(patch.object(sr,"TradeSetupSession",return_value=self.session))

    def analyze(self):
        return sr.run_trade_setup_analysis(sr.DEFAULT_SYMBOL,["4H","15m"],"gpt-6-sol",confirmed_chart=json.dumps(TARGET),live_confirmed=True)

    def execute(self, prompt, model, timeout, count=2):
        self.assertEqual(model,"gpt-6-sol")
        self.assertIn("Analysis timeframes: 4H, 15m",prompt)
        self.assertIn(self.session.run_id,prompt)
        data = result_record(self.session,count)
        add_drawings(self.session,data)
        return sr.AnalysisOutcome("completed_unverified",response=json.dumps(data),return_code=0,
                                  output="PRIVATE TOOL LOGS",errors="PRIVATE DIAGNOSTICS")

    def test_model_symbol_frames_and_only_final_explanation_returned(self):
        with patch.object(sr,"_execute_codex",side_effect=self.execute) as run:
            outcome = self.analyze()
        run.assert_called_once()
        self.assertEqual(outcome.status,"completed_verified")
        self.assertTrue(outcome.analysis_completed)
        self.assertNotIn("PRIVATE",outcome.final_analysis)
        self.assertNotIn("run_id",outcome.final_analysis)
        self.assertEqual(len(outcome.trade_report["setups"]),2)
        self.assertEqual(set(outcome.trade_report),{"run_id","final_analysis","setups"})
        self.assertNotIn("drawings",outcome.trade_report["setups"][0])
        self.assertNotIn("PRIVATE",json.dumps(outcome.trade_report))

    def test_actual_final_message_file_excludes_stdout_stderr_and_preserves_model(self):
        data = result_record(self.session,0)
        def fake_cli(command,**kwargs):
            self.assertEqual(command[command.index("--model")+1],"gpt-6-sol")
            self.assertEqual(command[command.index("--sandbox")+1],"read-only")
            Path(command[command.index("--output-last-message")+1]).write_text(json.dumps(data),encoding="utf-8")
            return subprocess.CompletedProcess(command,0,"PRIVATE TOOL TRACE","PRIVATE STDERR")
        with patch.object(sr,"codex_command",return_value=["mock-codex"]), patch.object(sr.subprocess,"run",side_effect=fake_cli):
            outcome = sr._execute_codex("PRIVATE PROMPT","gpt-6-sol",1)
        parsed = grouping.read_trade_completion(outcome.response,self.session.run_id,TARGET)
        self.assertEqual(parsed["final_analysis"],data["final_analysis"])
        self.assertNotIn("PRIVATE",parsed["final_analysis"])
        self.assertIn("PRIVATE TOOL TRACE",outcome.output)

    def test_no_trade_and_partial_grouping_outcomes(self):
        with patch.object(sr,"_execute_codex",side_effect=lambda *args:self.execute(*args,count=0)):
            outcome = self.analyze()
        self.assertEqual(outcome.status,"completed_no_trade")
        self.assertIn("WAIT",outcome.final_analysis)
        self.session.state["failRename"] = True
        with patch.object(sr,"_execute_codex",side_effect=self.execute) as run:
            outcome = self.analyze()
        run.assert_called_once()
        self.assertEqual(outcome.status,"partial_success")
        self.assertFalse(outcome.drawings_verified)
        self.assertTrue(outcome.analysis_completed)
        self.assertIn("rename failed",outcome.errors)

    def test_failed_timeout_or_missing_final_is_not_a_completed_analysis(self):
        for status in ("timed_out","failed","approval_blocked","completed_unverified"):
            with self.subTest(status=status), patch.object(sr,"_execute_codex",return_value=sr.AnalysisOutcome(status,output="final looking CLI logs")):
                outcome = self.analyze()
            self.assertFalse(outcome.analysis_completed)
            self.assertEqual(outcome.final_analysis,"")
        self.assertEqual(self.session.creates,0)

    def test_no_consent_bad_target_and_existing_group_prevent_cli(self):
        with patch.object(sr,"_execute_codex") as run:
            outcome = sr.run_trade_setup_analysis(sr.DEFAULT_SYMBOL)
            self.assertEqual(outcome.status,"confirmation_required")
            self.session.target = dict(TARGET,symbol="OTHER:SYMBOL")
            self.assertEqual(self.analyze().status,"grouping_preflight_failed")
            self.session.target = TARGET
            self.session.state["groups"] = [{"id":"foreign","name":grouping.SETUP_GROUP_NAMES[0],"ids":["old"]}]
            self.assertEqual(self.analyze().status,"grouping_preflight_failed")
        run.assert_not_called()

    def test_separate_prompt_covers_conditional_strategies_and_safety(self):
        prompt = sr.build_trade_setup_prompt(sr.DEFAULT_SYMBOL)
        for phrase in ("1H, 4H, 1D", "higher highs / higher lows", "lower highs / lower lows", "breakout and retest",
                       "trend continuation", "failed breakouts", "candlestick confirmation", "Target 2 only when justified",
                       "risk/reward only when supportable", "NO TRADE / WAIT", "outdated levels need refreshing",
                       "no placeholder", "standard Candles", "No Bybit", "order placement", "Telegram"):
            self.assertIn(phrase,prompt)
        self.assertNotIn("Find 3 nearby support",prompt)
        self.assertEqual(set(sr.TRADINGVIEW_SR_TOOLS),{"chart_get_state","tab_list","pane_list","chart_get_visible_range",
                        "data_get_ohlcv","chart_set_timeframe","draw_shape","draw_list","draw_get_properties"})
        with self.assertRaises(ValueError):
            grouping.fixed_operation("create",TARGET,drawings=NEW,group_name="Unrelated group")


class SetupGuiTests(unittest.TestCase):
    def setUp(self):
        # No real watchlist/model/AI readers, even at startup.
        self.enterContext(patch.object(main,"get_tradingview_watchlist",return_value={"symbols":[sr.DEFAULT_SYMBOL],"source":"fallback","name":"","error":"Offline fixture"}))
        self.enterContext(patch.object(main,"load_codex_models",return_value={"models":[sr.DEFAULT_MODEL,"gpt-6-sol"],"source":"offline","fetched_at":"offline","error":""}))
        self.inspect = self.enterContext(patch.object(main,"inspect_tradingview_chart",return_value=json.dumps(TARGET)))
        self.verify = self.enterContext(patch.object(main,"ensure_selected_symbol",return_value=json.dumps(TARGET)))
        self.run = self.enterContext(patch.object(main,"run_trade_setup_analysis"))
        self.sr_run = self.enterContext(patch.object(main,"run_support_resistance_analysis"))
        self.confirm = self.enterContext(patch.object(main.messagebox,"askokcancel",return_value=False))
        self.warning = self.enterContext(patch.object(main.messagebox,"showwarning"))
        self.error = self.enterContext(patch.object(main.messagebox,"showerror"))
        self.success = self.enterContext(patch.object(main.messagebox,"showinfo"))
        self.root = main.ctk.CTk()
        self.root.withdraw()
        self.app = main.SupportResistanceApp(self.root)
        self.addCleanup(self.close)
        self.pump(lambda:not self.app.refreshing and bool(self.app.model.get()))

    def close(self):
        for callback in self.root.tk.call("after","info"):
            # Cancel timers without deleting child widgets' Tcl commands;
            # each widget releases its commands during normal destruction.
            self.root.tk.call("after", "cancel", callback)
        self.root.destroy()

    def pump(self, predicate, timeout=3):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.root.update()
            if predicate(): return
            time.sleep(.005)
        self.fail("Offline GUI callback did not finish")

    def test_button_placement_cancel_and_all_charts_remain_protected(self):
        buttons = self.app.find_button.master.pack_slaves()
        self.assertEqual(buttons,[self.app.find_button,self.app.trade_button,self.app.show_status_box])
        self.app.trade_button.invoke()
        self.pump(lambda:not self.app.running)
        self.run.assert_not_called()
        self.verify.assert_not_called()
        self.app.all_charts.set(True)
        self.confirm.reset_mock()
        self.app.trade_button.invoke()
        self.confirm.assert_not_called()
        self.assertIn("not yet implemented",self.app.status.get())
        self.app.all_charts.set(False)
        self.assertEqual(self.app.symbol_box.cget('state'), 'normal')

    def test_background_responsive_no_overlapping_jobs_correct_selection(self):
        gate, entered = threading.Event(), threading.Event()
        self.addCleanup(gate.set)
        def slow(*args,**kwargs):
            entered.set()
            gate.wait(2)
            return sr.AnalysisOutcome("timed_out",errors="Offline timeout")
        self.run.side_effect = slow
        self.confirm.return_value = True
        self.app.model.set("gpt-6-sol")
        self.app.levels.set("not used by setup analysis")
        self.app.timeframes["1H"].set(False)
        self.app.trade_button.invoke()
        self.pump(entered.is_set)
        tick = []
        self.root.after(1,lambda:tick.append(True))
        self.pump(lambda:bool(tick))
        self.assertTrue(self.app.running)
        self.assertEqual(self.app.find_button.cget('state'), 'disabled')
        self.assertEqual(self.app.trade_button.cget('state'), 'disabled')
        self.app.find_levels()
        self.app.find_trade_setups()
        self.run.assert_called_once_with(sr.DEFAULT_SYMBOL,["4H","1D"],"gpt-6-sol",confirmed_chart=json.dumps(TARGET),live_confirmed=True)
        self.sr_run.assert_not_called()
        gate.set()
        self.pump(lambda:not self.app.running)
        self.assertEqual(self.app.trade_button.cget('state'), 'normal')
        self.warning.assert_called_once()

    def test_popup_only_final_text_scroll_resize_copy_and_close(self):
        text = "NO TRADE / WAIT — Offline fixture: confirmation is missing; wait for a supported setup."
        popup = self.app.show_trade_results(text)
        self.assertEqual(popup.title(),"Trade Setups — Analysis Results")
        self.assertEqual(tuple(map(bool,popup.resizable())),(True,True))
        analysis = next(w for w in popup.winfo_children() if isinstance(w,tk.Frame)).children["analysis"]
        self.assertEqual(analysis.get("1.0","end-1c"),text)
        self.assertEqual(str(analysis["state"]),"disabled")
        self.assertTrue(analysis.vbar.winfo_exists())
        popup.nametowidget("actions.copy").invoke()
        self.assertEqual(self.root.clipboard_get(),text)
        popup.nametowidget("actions.close").invoke()
        self.assertFalse(popup.winfo_exists())

    def test_result_gating_warning_before_partial_explanation_and_sr_popup_unchanged(self):
        cases = [("completed_verified",True,True),("completed_no_trade",True,True),
                 ("partial_success",False,True),("completed_unverified",False,False),("failed",False,False)]
        for status,verified,completed in cases:
            with self.subTest(status=status), patch.object(self.app,"show_trade_results") as popup:
                self.warning.reset_mock()
                text = "Conditional offline explanation only, without technical execution logs."
                value = sr.AnalysisOutcome(status,output="PRIVATE CLI LOG",errors="PRIVATE STDERR",prompt="PRIVATE PROMPT",
                                           drawings_verified=verified,analysis_completed=completed,final_analysis=text if completed else "")
                self.app.events.put(("trade_result",value))
                self.app.poll_events()
                self.assertEqual(popup.call_count,int(completed))
                if completed: popup.assert_called_once_with(text)
                self.assertEqual(self.warning.call_count,int(not verified) + int(completed))
        self.success.assert_not_called()
        self.app.events.put(("result",sr.AnalysisOutcome("completed_verified",drawings_verified=True)))
        self.app.poll_events()
        self.success.assert_called_once()
        self.assertEqual(self.success.call_args.args[0],"Analysis Completed")

    def test_symbol_mismatch_stops_trade_ai(self):
        self.verify.side_effect = ValueError("Symbol mismatch")
        self.confirm.return_value = True
        self.app.trade_button.invoke()
        self.pump(lambda:not self.app.running)
        self.run.assert_not_called()
        self.error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
