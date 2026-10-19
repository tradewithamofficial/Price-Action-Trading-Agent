"""CustomTkinter checks with mocked readers/workers; no live services or build."""
import importlib.util
from pathlib import Path
import runpy
import socket
import unittest
from unittest.mock import patch

import customtkinter as ctk
import main
import sr_agent as sr
from tests import test_trade_setups as trade_tests


class DarkGuiTests(unittest.TestCase):
    close = trade_tests.SetupGuiTests.close
    pump = trade_tests.SetupGuiTests.pump

    def setUp(self):
        self.enterContext(patch.object(socket, 'socket', side_effect=AssertionError('Real network forbidden')))
        self.send = self.enterContext(patch.object(main, 'send_trade_analysis'))
        trade_tests.SetupGuiTests.setUp(self)
        self.root.deiconify()
        self.root.update()

    def test_dark_window_and_modern_controls_open(self):
        self.assertIsInstance(self.root, ctk.CTk)
        self.assertEqual(ctk.get_appearance_mode(), 'Dark')
        self.assertEqual(self.root.state(), 'normal')
        for widget in (self.app.symbol_box, self.app.model_box, self.app.levels_box):
            self.assertIsInstance(widget, ctk.CTkComboBox)
        self.assertIsInstance(self.app.show_status_box, ctk.CTkCheckBox)
        self.assertIsInstance(self.app.output, ctk.CTkTextbox)
        self.assertIsInstance(self.app.progress, ctk.CTkProgressBar)
        self.assertEqual(self.app.find_button.cget('fg_color'), ctk.ThemeManager.theme['CTkButton']['fg_color'])
        self.assertGreater(self.app.find_button.cget('corner_radius'), 0)

    def test_dropdowns_timeframes_all_charts_and_validation(self):
        self.app.symbol_box.set('BYBIT:BTCUSDT.P')
        self.app.model_box.set('gpt-6-sol')
        self.app.levels_box.set('4')
        settings = self.app.levels_box.master
        for widget in settings.winfo_children():
            if isinstance(widget, ctk.CTkCheckBox):
                if widget.cget('text') in ('1H', '1D'):
                    widget.toggle()
        self.assertEqual(self.app.selection(), ('BYBIT:BTCUSDT.P', ['4H'], 4, 'gpt-6-sol'))
        self.assertEqual(self.app.levels_box.cget('values'), [str(n) for n in range(1, 21)])
        self.assertEqual(self.app.model_box.cget('state'), 'readonly')
        self.app.all_charts_box.toggle()
        self.assertEqual(self.app.symbol_box.cget('state'), 'disabled')
        for button in (self.app.find_button, self.app.trade_button):
            button.invoke()
            self.assertIn('not yet implemented', self.app.status.get())
        self.app.all_charts_box.toggle()
        self.assertEqual(self.app.symbol_box.cget('state'), 'normal')
        self.app.levels_box.set('21')
        self.app.find_button.invoke()
        self.error.assert_called_once()
        self.assertTrue(self.root.winfo_exists())
        self.confirm.assert_not_called()
        self.inspect.assert_not_called()
        self.run.assert_not_called()
        self.sr_run.assert_not_called()
        self.send.assert_not_called()

    def test_collapsible_panel_resizes_in_logical_units_at_higher_dpi(self):
        self.addCleanup(ctk.set_widget_scaling, 1.0)
        self.addCleanup(ctk.set_window_scaling, 1.0)
        ctk.set_widget_scaling(1.25)
        ctk.set_window_scaling(1.25)
        self.root.update()
        def size():
            return tuple(map(int, self.root.geometry().split('+')[0].split('x')))
        width, _ = size()
        for _ in range(2):
            self.app.show_status_box.toggle()
            self.root.update()
            expanded = size()
            self.assertEqual(expanded[0], width)
            self.assertTrue(self.app.output.winfo_ismapped())
            self.app.show_status_box.toggle()
            self.root.update()
            collapsed = size()
            self.assertEqual(collapsed[0], width)
            self.assertLess(collapsed[1], expanded[1])
            self.assertGreaterEqual(self.root.winfo_height(), self.root.winfo_reqheight() - 1)


class DarkPackagingTests(unittest.TestCase):
    def test_official_installed_hook_collects_themes_fonts_for_windowed_onedir_build(self):
        hooks = Path(importlib.util.find_spec('_pyinstaller_hooks_contrib').origin).parent
        data = runpy.run_path(str(hooks / 'stdhooks' / 'hook-customtkinter.py'))['datas']
        names = {Path(source).name for source, destination in data}
        self.assertIn('dark-blue.json', names)
        self.assertIn('CustomTkinter_shapes_font.otf', names)
        self.assertTrue(all(destination.startswith('customtkinter') for source, destination in data))
        project = Path(main.__file__).parent
        self.assertIn('--onedir --windowed', (project / 'build.ps1').read_text())
        self.assertIn('-r requirements.txt', (project / 'requirements-build.txt').read_text())
        self.assertIn('customtkinter=='+ctk.__version__, (project / 'requirements.txt').read_text())


if __name__ == '__main__':
    unittest.main()
