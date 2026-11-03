"""Authoritative prompt drawing instructions remain intact; no replacement analysis rules."""
from pathlib import Path
import unittest
from unittest.mock import Mock
import main
import sr_agent as sr

class DrawingPromptTests(unittest.TestCase):
    def test_tested_lines_zones_labels_and_group_name_are_retained(self):
        prompt=sr.build_support_resistance_prompt(sr.DEFAULT_SYMBOL,['1H','4H','1D'])
        for phrase in ('HORIZONTAL LINE','RECTANGULAR ZONE','R1, R2, R3','S1, S2, S3','Support And Resistance Levels'):
            self.assertIn(phrase,prompt)
        self.assertNotIn('schema',prompt)
        self.assertNotIn('application groups',prompt)
    def test_complete_classical_pattern_and_non_destructive_rules_are_retained(self):
        original=Path('reference_simple/price_action.txt').read_text(encoding='utf-8-sig').strip()
        prompt=sr.build_trade_setup_prompt(sr.DEFAULT_SYMBOL,['1H','4H','1D'])
        self.assertEqual(prompt[:len(original)],original)
        self.assertIn('cup and handle',prompt)
        self.assertIn('Do not delete, edit, move, relabel, hide, or regroup',prompt)
    def test_gui_selections_are_validated_without_running_codex(self):
        app=main.SupportResistanceApp.__new__(main.SupportResistanceApp)
        app.symbol=Mock(get=Mock(return_value=sr.DEFAULT_SYMBOL))
        app.model=Mock(get=Mock(return_value='gpt-6-sol'))
        app.levels=Mock(get=Mock(return_value='4'))
        app.all_charts=Mock(get=Mock(return_value=False))
        app.timeframes={tf:Mock(get=Mock(return_value=True)) for tf in ('1H','4H','1D')}
        self.assertEqual(app.selection(),(sr.DEFAULT_SYMBOL,['1H','4H','1D'],4,'gpt-6-sol'))
        app.timeframes['15m']=Mock(get=Mock(return_value=True))
        with self.assertRaisesRegex(ValueError,'tested prompts require'):app.selection()
