"""Offline requirements for drawing styles, labels and ownership safeguards."""
import unittest
from unittest.mock import Mock, patch

import sr_agent as sr


class DrawingPromptTests(unittest.TestCase):
    def test_drawing_guidance_in_copy_and_confirmed_requests(self):
        for confirmed in (False, True):
            with self.subTest(confirmed=confirmed), patch.object(sr.subprocess, "run") as run:
                prompt = sr.build_support_resistance_prompt(
                    sr.DEFAULT_SYMBOL, ["1H", "4H", "1D"],
                    confirmed_chart='{"tab_id":"MOCK","pane_index":0}' if confirmed else "",
                    live_confirmed=confirmed,
                )
                for requirement in (
                    "horizontal_line for a relatively precise", "rectangle only for a genuine zone",
                    "meaningful lower and upper price boundaries", "market structure, repeated price reactions, swing levels",
                    "Do not force all levels to be zones or all levels to be lines",
                    "red (#ff0000) for resistance", "green (#008000) for support",
                    "3 nearby support levels/areas and 3 nearby resistance levels/areas TOTAL",
                    "rather than multiplying the count per timeframe",
                    "Each line or zone counts as one level/area",
                ):
                    self.assertIn(requirement, prompt)
                self.assertNotIn("zones as clearly labeled rectangles", prompt)
                run.assert_not_called()

    def test_labels_keep_prices_and_contributing_timeframes_only(self):
        prompt = sr.build_support_resistance_prompt(sr.DEFAULT_SYMBOL, ["1H", "4H", "1D"])
        for requirement in (
            "ONLY prices and contributing timeframes",
            "'LOW–HIGH | TF / TF'", "'PRICE | TF / TF'",
            "4155.35–4161.06 | 1H / 4H / 1D", "4174.50 | 1H / 4H",
            "Format examples only, not market levels", "instrument-appropriate precision",
            "only selected timeframes that contribute to that level",
            "Do not prefix visible labels with 'Trade With AM', 'S1 Support'",
            "'R1 Resistance'", "or any role/sequence label",
        ):
            self.assertIn(requirement, prompt)

    def test_custom_count_and_timeframes_are_preserved(self):
        prompt = sr.build_support_resistance_prompt(sr.DEFAULT_SYMBOL, ["15m", "4H"], 5, "gpt-6-sol")
        self.assertIn("5 nearby support levels/areas and 5 nearby resistance levels/areas TOTAL", prompt)
        self.assertIn("Analyze timeframes: 15m, 4H", prompt)
        self.assertIn("Requested model: gpt-6-sol", prompt)

    def test_shorter_labels_do_not_weaken_ownership_or_execution_safety(self):
        prompt = sr.build_support_resistance_prompt(sr.DEFAULT_SYMBOL, ["1H"])
        for requirement in (
            "NO authorization for live chart changes yet",
            "same verified tab/pane identity", "standard Candles (chartType 1)",
            "Do not invent metadata fields or tools",
            "If hidden ownership metadata is unsupported, clearly report that limitation",
            "Record returned new drawing IDs in the response",
            "Never infer ownership from color or simplified price/timeframe labels",
            "never automatically modify or delete ambiguously owned objects",
            "Never delete, replace, move or regroup existing objects",
            "Do not automatically retry a failed drawing call",
        ):
            self.assertIn(requirement, prompt)

    def test_gui_selection_keeps_internal_prompt_validation_without_copy_button(self):
        import main
        app = main.SupportResistanceApp.__new__(main.SupportResistanceApp)
        app.all_charts = Mock(get=Mock(return_value=False))
        app.symbol = Mock(get=Mock(return_value=sr.DEFAULT_SYMBOL))
        app.levels = Mock(get=Mock(return_value="3"))
        app.model = Mock(get=Mock(return_value=sr.DEFAULT_MODEL))
        app.timeframes = {tf:Mock(get=Mock(return_value=True)) for tf in ("1H", "4H")}
        expected = (sr.DEFAULT_SYMBOL, ["1H", "4H"], 3, sr.DEFAULT_MODEL)
        with patch.object(sr.subprocess, "run") as run, \
                patch.object(main, "build_support_resistance_prompt", wraps=sr.build_support_resistance_prompt) as build:
            self.assertEqual(app.selection(), expected)
            build.assert_called_once_with(*expected)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
