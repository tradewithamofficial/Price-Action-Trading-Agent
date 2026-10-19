"""Test the actual GUI code extracted from the built EXE, without AI execution.

This is a Tk component/clipboard test, not a screenshot or mouse-launch test.
Requires a built EXE, PyInstaller, and a Windows desktop session.
"""
from contextlib import ExitStack
import importlib.util
import marshal
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
import types
import unittest
from unittest.mock import patch


EXE = Path(__file__).resolve().parents[1] / "dist" / "SupportResistanceAgent.exe"


@unittest.skipUnless(EXE.is_file() and importlib.util.find_spec("PyInstaller"), "Build the EXE first")
class PackagedGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyInstaller.archive.readers import CArchiveReader
        archive = CArchiveReader(str(EXE))
        bundled_sr = types.ModuleType("sr_agent")
        bundled_sr.__file__ = str(EXE.parent / "sr_agent.py")
        cls.module_patch = patch.dict(sys.modules, {"sr_agent": bundled_sr})
        cls.module_patch.start()
        cls.addClassCleanup(cls.module_patch.stop)
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(EXE)):
            exec(archive.open_embedded_archive("PYZ.pyz").extract("sr_agent"), bundled_sr.__dict__)
        gui = types.ModuleType("packaged_main_test")
        gui.__file__ = str(EXE.parent / "main.py")
        exec(marshal.loads(archive.extract("main")), gui.__dict__)
        cls.gui, cls.sr = gui, bundled_sr
        cls.catalog = bundled_sr.load_codex_models()
        # Only read the existing watchlist. No analysis, timeframe or drawings.
        cls.watchlist = bundled_sr.get_tradingview_watchlist()

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.analysis = self.stack.enter_context(patch.object(self.gui, "run_support_resistance_analysis"))
        self.verify = self.stack.enter_context(patch.object(self.gui, "verify_tradingview_chart"))
        self.stack.enter_context(patch.object(self.gui, "get_tradingview_watchlist", return_value=self.watchlist))
        self.stack.enter_context(patch.object(self.gui, "load_codex_models", return_value=self.catalog))
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = self.gui.SupportResistanceApp(self.root)
        self.addCleanup(self.close_root)
        self.pump(lambda: bool(self.app.model.get()) and not self.app.refreshing)

    def close_root(self):
        # Several independent Tk roots are created by this test class. Cancel
        # pending callbacks before destroying each test interpreter.
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()

    def pump(self, predicate, timeout=5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.root.update()
            if predicate():
                return
            time.sleep(.01)
        self.fail("GUI callback did not finish")

    def test_defaults_layout_and_real_external_sources(self):
        self.assertEqual(self.sr.PROJECT_DIR, EXE.parent)
        self.assertEqual([f for f, v in self.app.timeframes.items() if v.get()], ["1H", "4H", "1D"])
        self.assertEqual(self.app.levels.get(), "3")
        self.assertFalse(self.app.all_charts.get())
        self.assertEqual(self.app.all_charts_box.grid_info()["row"], self.app.symbol_box.grid_info()["row"])
        self.assertEqual(tuple(self.app.symbol_box["values"]), tuple(self.watchlist["symbols"]))
        self.assertEqual(tuple(self.app.model_box["values"]), tuple(self.catalog["models"]))
        self.assertIn("actual symbols" if self.watchlist["source"] == "live" else "Fallback", self.app.symbol_source.get())

    def test_clipboard_and_model_timeframe_level_selection(self):
        selected_model = next(m for m in self.catalog["models"] if m != self.sr.DEFAULT_MODEL)
        self.app.model.set(selected_model)
        self.app.symbol.set(self.watchlist["symbols"][0])
        self.app.timeframes["15m"].set(True)
        self.app.levels.set("4")
        self.app.copy_button.invoke()
        copied = self.root.clipboard_get()
        self.assertIn("Requested model: " + selected_model, copied)
        self.assertIn("TradingView symbol: " + self.watchlist["symbols"][0], copied)
        self.assertIn("Analyze timeframes: 1H, 4H, 1D, 15m", copied)
        self.assertIn("4 nearby support levels/areas", copied)
        self.analysis.assert_not_called()

    def test_all_charts_is_blocked_and_can_be_unchecked(self):
        self.app.all_charts_box.invoke()
        self.assertTrue(self.app.symbol_box.instate(["disabled"]))
        self.app.find_button.invoke()
        self.assertIn("not yet implemented", self.app.status.get())
        self.app.copy_button.invoke()
        self.assertIn("CONCEPT ONLY", self.root.clipboard_get())
        self.app.all_charts_box.invoke()
        self.assertFalse(self.app.symbol_box.instate(["disabled"]))
        self.analysis.assert_not_called()
        self.verify.assert_not_called()

    def test_error_is_reported_without_closing_gui(self):
        for var in self.app.timeframes.values():
            var.set(False)
        with patch.object(self.gui.messagebox, "showerror") as error:
            self.app.copy_button.invoke()
            error.assert_called_once()
        self.assertTrue(self.root.winfo_exists())
        self.assertEqual(self.app.status.get(), "Could not copy prompt")
        self.analysis.assert_not_called()

    def test_cancel_never_starts_chart_verification_or_analysis(self):
        with patch.object(self.gui.messagebox, "askokcancel", return_value=False):
            self.app.find_button.invoke()
        self.assertIn("Cancelled", self.app.status.get())
        self.verify.assert_not_called()
        self.analysis.assert_not_called()

    def test_slow_refresh_is_responsive_and_clear_fallback(self):
        release = threading.Event()
        fallback = {"symbols": self.sr.fallback_symbols(), "source": "fallback", "name": "", "error": "Simulated connection timeout"}
        def delayed():
            release.wait(3)
            return fallback
        with patch.object(self.gui, "get_tradingview_watchlist", side_effect=delayed):
            self.app.refresh_sources()
            ticks = []
            self.root.after(10, lambda: ticks.append(True))
            self.pump(lambda: bool(ticks))
            self.assertTrue(self.app.refreshing)
            release.set()
            self.pump(lambda: not self.app.refreshing)
        self.assertIn("Fallback", self.app.symbol_source.get())
        self.assertIn("Simulated connection timeout", self.app.output.get("1.0", "end"))
        self.assertTrue(self.root.winfo_exists())
