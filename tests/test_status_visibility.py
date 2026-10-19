"""Offline Tk checks: all external readers, analysis and delivery are mocked."""
import socket
import threading
import tkinter as tk
import customtkinter as ctk
import unittest
from unittest.mock import patch

import main
import sr_agent as sr
from tests import test_trade_setups as trade_tests


class StatusVisibilityTests(unittest.TestCase):
    close = trade_tests.SetupGuiTests.close
    pump = trade_tests.SetupGuiTests.pump

    def setUp(self):
        self.enterContext(patch.object(socket, 'socket', side_effect=AssertionError('Real network forbidden')))
        self.send = self.enterContext(patch.object(main, 'send_trade_analysis'))
        trade_tests.SetupGuiTests.setUp(self)
        self.root.deiconify()
        self.root.update()

    def test_default_hidden_and_checkbox_after_analysis_buttons(self):
        self.assertFalse(self.app.show_status.get())
        self.assertEqual(self.app.show_status_box.cget('text'), 'Show Status')
        self.assertEqual(self.app.find_button.master.pack_slaves(),
                         [self.app.find_button, self.app.trade_button, self.app.show_status_box])
        self.assertFalse(self.app.output_section.winfo_ismapped())
        for widget in (self.app.find_button, self.app.trade_button,
                       self.app.show_status_box, self.app.symbol_box, self.app.model_box, self.app.levels_box,
                       self.app.status_row, self.app.status_label, self.app.progress):
            self.assertTrue(widget.winfo_ismapped())
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                 self.root.winfo_rooty() + self.root.winfo_height())
        self.assertLess(self.root.winfo_height(), 680)

    def test_show_hide_reuses_text_widget_scrollbar_and_copy_selection(self):
        output = self.app.output
        scrollbar = output._y_scrollbar
        original = output.get('1.0', 'end-1c')
        for _ in range(2):
            self.app.show_status_box.toggle()
            self.root.update()
            self.assertTrue(self.app.output_section.winfo_ismapped())
            self.assertTrue(self.app.progress.winfo_ismapped())
            self.assertTrue(self.app.status_label.winfo_ismapped())
            self.assertTrue(output.winfo_ismapped())
            self.assertTrue(scrollbar.winfo_exists())  # CTk hides scrollbars until needed.
            self.assertEqual(str(output.cget('state')), 'disabled')
            output.tag_add('sel', '1.0', '1.3')
            output._textbox.event_generate('<<Copy>>')
            self.assertEqual(self.root.clipboard_get(), original[:3])
            self.app.show_status_box.toggle()
            self.root.update()
            self.assertFalse(self.app.output_section.winfo_ismapped())
            self.assertTrue(self.app.progress.winfo_ismapped())
            self.assertTrue(self.app.status_label.winfo_ismapped())
            self.assertFalse(output.winfo_ismapped())
            self.assertIs(self.app.output, output)
            self.assertIs(self.app.output._y_scrollbar, scrollbar)
            self.assertEqual(output.get('1.0', 'end-1c'), original)

    def test_hidden_logs_and_errors_are_retained_and_error_dialog_still_shown(self):
        self.app.log('OFFLINE hidden status message')
        self.app.events.put(('chart_error', 'OFFLINE chart connection error'))
        self.app.poll_events()
        self.error.assert_called_once()
        self.assertIn('OFFLINE chart connection error', self.error.call_args.args[1])
        self.assertFalse(self.app.output_section.winfo_ismapped())
        self.root.update()
        self.assertTrue(self.app.progress.winfo_ismapped())
        self.assertTrue(self.app.status_label.winfo_ismapped())
        self.assertIn('Chart verification failed', self.app.status_label._label.cget('text'))
        self.app.show_status_box.toggle()
        self.root.update()
        text = self.app.output.get('1.0', 'end-1c')
        for message in ('GUI ready.', 'OFFLINE hidden status message', 'OFFLINE chart connection error'):
            self.assertIn(message, text)
        self.app.show_status_box.toggle()
        self.app.log('OFFLINE message after collapsing again')
        self.app.show_status_box.toggle()
        self.assertIn('OFFLINE message after collapsing again', self.app.output.get('1.0', 'end-1c'))

    def test_window_expands_contracts_and_preserves_width(self):
        collapsed = self.root.winfo_height()
        width = self.root.winfo_width()
        self.app.show_status_box.toggle()
        self.root.update()
        expanded = self.root.winfo_height()
        self.assertGreater(expanded, collapsed)
        self.assertGreaterEqual(expanded, 740)
        self.assertEqual(self.root.winfo_width(), width)
        self.assertGreaterEqual(tk.Wm.minsize(self.root)[1], 680)
        self.app.show_status_box.toggle()
        self.root.update()
        self.assertEqual(self.root.winfo_height(), collapsed)
        self.assertEqual(self.root.winfo_width(), width)
        self.assertLess(tk.Wm.minsize(self.root)[1], 680)
        self.assertGreaterEqual(self.root.winfo_height(), self.root.winfo_reqheight())

    def test_toggle_never_starts_external_work(self):
        for _ in range(4):
            self.app.show_status_box.toggle()
        self.inspect.assert_not_called()
        self.verify.assert_not_called()
        self.run.assert_not_called()
        self.sr_run.assert_not_called()
        self.send.assert_not_called()

    def test_toggle_works_during_background_analysis_without_overlap(self):
        entered, gate = threading.Event(), threading.Event()
        self.addCleanup(gate.set)
        def slow(*args, **kwargs):
            entered.set()
            gate.wait(5)
            return sr.AnalysisOutcome('failed', output='OFFLINE background diagnostic', errors='OFFLINE failure')
        self.run.side_effect = slow
        self.confirm.return_value = True
        self.app.find_trade_setups()
        self.pump(entered.is_set)
        self.pump(lambda: 'Codex is running' in self.app.status.get())
        phase = self.app.progress._indeterminate_value
        self.pump(lambda: self.app.progress._indeterminate_value != phase)
        self.assertTrue(self.app.progress._loop_running)
        self.assertTrue(self.app.progress.winfo_ismapped())
        self.assertIn('Codex is running', self.app.status_label._label.cget('text'))
        for _ in range(2):
            self.assertEqual(self.app.show_status_box.cget('state'), 'normal')
            self.app.show_status_box.toggle()
            self.root.update()
            self.assertTrue(self.app.progress.winfo_ismapped())
            self.assertTrue(self.app.status_label.winfo_ismapped())
        self.assertTrue(self.app.running)
        self.app.find_levels()
        self.app.find_trade_setups()
        self.run.assert_called_once()
        self.sr_run.assert_not_called()
        gate.set()
        self.pump(lambda: not self.app.running)
        self.assertFalse(self.app.progress._loop_running)
        self.assertTrue(self.app.progress.winfo_ismapped())
        self.assertIn('failed', self.app.status_label._label.cget('text'))
        self.assertFalse(self.app.show_status.get())
        self.app.show_status_box.toggle()
        self.assertIn('OFFLINE background diagnostic', self.app.output.get('1.0', 'end-1c'))
        self.assertIn('OFFLINE failure', self.app.output.get('1.0', 'end-1c'))
        self.assertEqual(self.app.find_button.cget('state'), 'normal')
        self.assertEqual(self.app.trade_button.cget('state'), 'normal')
        self.send.assert_not_called()

    def test_progress_dimensions_and_separate_parent(self):
        self.assertEqual(self.app.progress.cget('width'), 165)  # Previous width: 110.
        self.assertEqual(self.app.progress.cget('height'), 10)  # Previous height: 5.
        self.assertIs(self.app.progress.master, self.app.status_row)
        self.assertIs(self.app.status_label.master, self.app.status_row)
        self.assertIs(self.app.status_row.master, self.app.output_section.master)
        self.assertEqual(str(self.app.status_label.cget('textvariable')), str(self.app.status))
        self.assertNotIn(self.app.status_row, self.app.output_section.winfo_children())

    def test_progress_and_status_remain_visible_after_verified_completion(self):
        self.app.running = True
        self.app.progress.start()
        self.app.events.put(('result', sr.AnalysisOutcome('completed_verified', drawings_verified=True)))
        self.app.poll_events()
        self.root.update()
        self.success.assert_called_once()
        self.assertFalse(self.app.running)
        self.assertFalse(self.app.progress._loop_running)
        self.assertFalse(self.app.output_section.winfo_ismapped())
        self.assertTrue(self.app.progress.winfo_ismapped())
        self.assertTrue(self.app.status_label.winfo_ismapped())
        self.assertIn('completed_verified', self.app.status_label._label.cget('text'))

    def test_progress_row_fits_without_overlap_at_both_window_widths(self):
        messages = ('Ready — no analysis has been run',
                    'Codex is running — waiting for response (up to 10 minutes)',
                    'Analysis completed | Telegram delivery failed/unconfirmed | chart verification INCOMPLETE')
        for width in (860, 780):
            self.root.geometry(f'{width}x'+self.root.geometry().split('x')[1])
            for show in (False, True):
                if self.app.show_status.get() != show:
                    self.app.show_status_box.toggle()
                for message in messages:
                    with self.subTest(width=width, show=show, message=message):
                        self.app.status.set(message)
                        self.root.update()
                        label, bar = self.app.status_label, self.app.progress
                        self.assertTrue(label.winfo_ismapped())
                        self.assertTrue(bar.winfo_ismapped())
                        self.assertEqual(label._label.cget('text'), message)
                        self.assertLessEqual(label.winfo_rootx()+label.winfo_width(), bar.winfo_rootx())
                        self.assertEqual(self.app.output_section.winfo_ismapped(), show)
                        for widget in (label, bar, self.app.find_button, self.app.trade_button,
                                       self.app.show_status_box, self.app.symbol_box, self.app.model_box):
                            self.assertTrue(widget.winfo_ismapped())
                            self.assertGreaterEqual(widget.winfo_rootx(), self.root.winfo_rootx())
                            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),
                                                 self.root.winfo_rootx()+self.root.winfo_width())
                            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),
                                                 self.root.winfo_rooty()+self.root.winfo_height())

    def test_clean_header_removed_copy_and_matching_analysis_buttons(self):
        body = self.app.find_button.master.master
        header = body.grid_slaves(row=0, column=0)[0]
        self.assertEqual(header.cget('text'), 'TRADE WITH AM')
        self.assertEqual(self.root.title(), 'Trade With AM — Price Action Trading Agent')
        self.assertEqual(body.grid_slaves(row=1, column=0)[0].cget('text'),
                         'Price Action Trading Agent')
        self.assertNotIn('COURSE V1', self.root.title())
        self.assertFalse(hasattr(self.app, 'copy_button'))
        self.assertFalse(hasattr(self.app, 'copy_prompt'))
        self.assertEqual(self.app.find_button.cget('text'), 'Find Support And Resistance Levels')
        self.assertEqual(self.app.trade_button.cget('text'), 'Find Trade Setups')
        self.assertIsInstance(self.app.find_button, ctk.CTkButton)
        self.assertIsInstance(self.app.trade_button, ctk.CTkButton)
        self.assertEqual(self.app.find_button.winfo_width(), self.app.trade_button.winfo_width())
        self.assertEqual(self.app.find_button.winfo_height(), self.app.trade_button.winfo_height())
        for option in ('width', 'height', 'font', 'fg_color', 'text_color', 'hover_color', 'border_width', 'corner_radius'):
            self.assertEqual(self.app.find_button.cget(option), self.app.trade_button.cget(option))
        for child in self.app.find_button.master.winfo_children():
            self.assertNotEqual(child.cget('text'), 'Copy Prompt')

    def test_both_analysis_buttons_keep_original_click_actions(self):
        with patch.object(self.app, 'start_analysis') as start:
            self.app.find_button.invoke()
            start.assert_called_once_with()
            start.reset_mock()
            self.app.trade_button.invoke()
            start.assert_called_once_with(trade=True)
        self.inspect.assert_not_called()
        self.run.assert_not_called()
        self.sr_run.assert_not_called()
        self.send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
