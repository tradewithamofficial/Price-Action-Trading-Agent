"""Exercise real dark modal dialogs; all analysis/readers/delivery stay mocked."""
import socket
import unittest
from unittest.mock import patch

import customtkinter as ctk
import main
import sr_agent as sr
import ui_dialogs
from tests import test_trade_setups as trade_tests

REAL_CONFIRM = ui_dialogs.askokcancel
REAL_MESSAGES = (ui_dialogs.showinfo, ui_dialogs.showwarning, ui_dialogs.showerror)


class DarkDialogTests(unittest.TestCase):
    close = trade_tests.SetupGuiTests.close
    pump = trade_tests.SetupGuiTests.pump

    def setUp(self):
        self.enterContext(patch.object(socket, 'socket', side_effect=AssertionError('Real network forbidden')))
        self.send = self.enterContext(patch.object(main, 'send_trade_analysis'))
        trade_tests.SetupGuiTests.setUp(self)
        self.root.deiconify()
        self.root.update()

    def schedule_action(self, action, before=None):
        seen, errors = {}, []
        def act():
            dialogs = [w for w in self.root.winfo_children() if isinstance(w, ctk.CTkToplevel)]
            if not dialogs or self.root.grab_current() is not dialogs[0]:
                self.root.after(10, act)
                return
            dialog = dialogs[0]
            try:
                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)
                widgets = list(descendants(dialog))
                buttons = {w.cget('text'):w for w in widgets if isinstance(w, ctk.CTkButton)}
                seen.update(title=dialog.title(), transient=dialog.transient(), modal=self.root.grab_current() is dialog,
                            labels=[w.cget('text') for w in widgets if isinstance(w, ctk.CTkLabel)],
                            button_names=set(buttons), ok_color=buttons['OK'].cget('fg_color'))
                textboxes = [w for w in widgets if isinstance(w, ctk.CTkTextbox)]
                if textboxes:
                    seen['long_text'] = textboxes[0].get('1.0', 'end-1c')
                    seen['text_state'] = textboxes[0].cget('state')
                if 'Cancel' in buttons:
                    seen['cancel_color'] = buttons['Cancel'].cget('fg_color')
                if before:
                    before()
                if action in buttons:
                    buttons[action].invoke()
                elif action == 'X':
                    dialog.tk.call(dialog.protocol('WM_DELETE_WINDOW'))
                else:
                    dialog.focus_force()
                    dialog.event_generate('<Escape>' if action == 'Escape' else '<Return>')
            except Exception as exc:
                errors.append(exc)
                dialog.destroy()
        def timeout():
            errors.append(AssertionError('Dark dialog did not complete within offline timeout'))
            for window in self.root.winfo_children():
                if isinstance(window, ctk.CTkToplevel):
                    window.destroy()
        self.root.after(30, act)
        timer = self.root.after(2500, timeout)
        return seen, errors, timer

    def check_action(self, function, action, *, message='Offline message. Continue?', before=None):
        seen, errors, timer = self.schedule_action(action, before)
        result = function('Offline Dialog', message, parent=self.root)
        self.root.after_cancel(timer)
        if errors:
            raise errors[0]
        self.assertTrue(seen['modal'])
        self.assertEqual(str(seen['transient']), str(self.root))
        self.assertEqual(seen['title'], 'Offline Dialog')
        self.assertEqual(seen['ok_color'], '#1f538d')
        self.assertFalse(any(isinstance(w, ctk.CTkToplevel) for w in self.root.winfo_children()))
        return result, seen

    def test_ok_approves_and_keeps_exact_message(self):
        result, seen = self.check_action(REAL_CONFIRM, 'OK')
        self.assertIs(result, True)
        self.assertIn('Offline message. Continue?', seen['labels'])
        self.assertEqual(seen['button_names'], {'OK', 'Cancel'})
        self.assertEqual(seen['cancel_color'], '#374151')

    def test_cancel_rejects(self):
        self.assertIs(self.check_action(REAL_CONFIRM, 'Cancel')[0], False)

    def test_escape_rejects(self):
        self.assertIs(self.check_action(REAL_CONFIRM, 'Escape')[0], False)

    def test_window_close_rejects(self):
        self.assertIs(self.check_action(REAL_CONFIRM, 'X')[0], False)

    def test_enter_defaults_to_rejection(self):
        self.assertIs(self.check_action(REAL_CONFIRM, 'Return')[0], False)

    def test_info_warning_error_use_same_dark_helper_and_only_ok(self):
        for function in REAL_MESSAGES:
            with self.subTest(kind=function.__name__):
                result, seen = self.check_action(function, 'OK', message='Exact success / warning / error text & prices 4174.50.')
                self.assertTrue(result)
                self.assertEqual(seen['button_names'], {'OK'})
                self.assertIn('Exact success / warning / error text & prices 4174.50.', seen['labels'])

    def test_long_error_is_scrollable_readonly_and_not_truncated(self):
        message = 'Offline diagnostic details and safety instructions.\n' * 35
        result, seen = self.check_action(REAL_MESSAGES[2], 'OK', message=message)
        self.assertTrue(result)
        self.assertEqual(seen['long_text'], message)
        self.assertEqual(seen['text_state'], 'disabled')

    def test_previous_modal_grab_is_restored(self):
        self.root.grab_set()
        self.check_action(REAL_CONFIRM, 'Cancel')
        self.assertIs(self.root.grab_current(), self.root)
        self.root.grab_release()

    def test_rapid_close_preserves_parent_callbacks_and_focus(self):
        tick = []
        self.app.symbol_box.focus_set()
        self.root.after(250, lambda: tick.append(True))
        self.check_action(REAL_CONFIRM, 'Cancel')
        self.pump(lambda: bool(tick))
        self.assertIsNone(self.root.grab_current())
        self.assertTrue(self.app.symbol_box.winfo_exists())

    def test_both_buttons_wait_for_real_dialog_approval_and_reject_all_cancel_paths(self):
        self.run.return_value = sr.AnalysisOutcome('failed', errors='Offline mocked analysis')
        self.sr_run.return_value = sr.AnalysisOutcome('failed', errors='Offline mocked analysis')
        with patch.object(main.messagebox, 'askokcancel', side_effect=REAL_CONFIRM):
            for trade in (False, True):
                for action in ('OK', 'Cancel', 'Escape', 'X'):
                    with self.subTest(trade=trade, action=action):
                        for mock in (self.inspect, self.verify, self.run, self.sr_run):
                            mock.reset_mock()
                        def before():
                            self.verify.assert_not_called()
                            self.run.assert_not_called()
                            self.sr_run.assert_not_called()
                            self.send.assert_not_called()
                            self.app.find_levels()
                            self.app.find_trade_setups()
                            self.inspect.assert_called_once()
                        seen, errors, timer = self.schedule_action(action, before)
                        (self.app.trade_button if trade else self.app.find_button).invoke()
                        self.pump(lambda: not self.app.running)
                        self.root.after_cancel(timer)
                        if errors:
                            raise errors[0]
                        self.assertTrue(seen['modal'])
                        self.assertIn('Continue?', '\n'.join(seen['labels']))
                        self.assertEqual(self.verify.call_count, int(action == 'OK'))
                        self.assertEqual(self.run.call_count, int(action == 'OK' and trade))
                        self.assertEqual(self.sr_run.call_count, int(action == 'OK' and not trade))
                        self.send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
