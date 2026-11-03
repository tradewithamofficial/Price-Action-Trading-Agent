"""Offline GUI fixtures; analytical execution is tested in test_direct_analysis."""
import json
import queue
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch
import main
import sr_agent as sr
from tests.test_grouping import TARGET


def result_record(session, count, sr_drawings=None):
    setups = []
    for rank in range(1, count + 1):
        drawings = [{"id": f"setup{rank}_{role}", "role": role, "shape": "horizontal_line",
                     "points": [{"time": 1, "price": rank * 10 + index}],
                     "properties": {"text": f"Setup {rank} | {role}", "linecolor": ("#1565c0", "#7b1fa2", "#ef6c00")[rank-1]}}
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
        self.run.assert_called_once_with(sr.DEFAULT_SYMBOL,["1H","4H","1D"],"gpt-6-sol",confirmed_chart=json.dumps(TARGET),live_confirmed=True)
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

    def test_complete_and_failed_responses_are_not_confused(self):
        self.app.show_telegram_outcome=Mock()
        self.app.show_trade_results=Mock()
        for complete in (True,False):
            self.app.show_telegram_outcome.reset_mock()
            outcome=sr.AnalysisOutcome('completed_response' if complete else 'failed',analysis_completed=complete,
                final_analysis='Full final response from the offline fixture.',return_code=0 if complete else 1)
            self.app.events.put(('trade_result',outcome))
            self.pump(lambda:self.app.events.empty())
            self.assertEqual(self.app.show_telegram_outcome.call_count,int(complete))
        self.warning.assert_called()
        self.app.events.put(('result',sr.AnalysisOutcome('completed_response',analysis_completed=True,
            final_analysis='Complete offline S/R report.',drawings_verified=True)))
        self.pump(lambda:self.app.events.empty())
        self.success.assert_called_once()
