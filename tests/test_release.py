"""Offline release checks; no actual connector, AI analysis, or Telegram requests."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import marshal
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time
import tkinter as tk
import types
import unittest
from unittest.mock import patch

import main
from tests import test_trade_setups as trade_tests
from tests import test_dark_dialogs as dialog_tests

PROJECT = Path(main.__file__).parent
RELEASE = PROJECT / 'release' / 'PriceActionTradingAgent'
EXE = RELEASE / 'PriceActionTradingAgent.exe'
INTERNAL = RELEASE / '_internal'
ICON = 'TradeWithAM_Robot.ico'


class SourceIconTests(unittest.TestCase):
    close = trade_tests.SetupGuiTests.close
    pump = trade_tests.SetupGuiTests.pump
    def setUp(self):
        original = main.ctk.CTk.iconbitmap
        self.icons = self.enterContext(patch.object(main.ctk.CTk, 'iconbitmap', autospec=True, side_effect=original))
        trade_tests.SetupGuiTests.setUp(self)

    def test_robot_window_icon_survives_customtkinter_delayed_default(self):
        ready = []
        self.root.after(260, lambda: ready.append(True))
        self.pump(lambda: bool(ready))
        self.icons.assert_any_call(self.root, str(PROJECT / 'assets' / ICON))
        self.icons.assert_any_call(self.root, default=str(PROJECT / 'assets' / ICON))
        self.assertTrue(self.root._iconbitmap_method_called)
        self.run.assert_not_called()
        self.sr_run.assert_not_called()

    def test_future_build_uses_new_application_name_and_existing_assets(self):
        build = (PROJECT / 'build.ps1').read_text(encoding='utf-8')
        self.assertIn('--name PriceActionTradingAgent', build)
        self.assertIn("'release\\PriceActionTradingAgent'", build)
        self.assertIn("'PriceActionTradingAgent.exe'", build)
        self.assertIn(ICON, build)
        self.assertIn('Futuristic AI Robot with Breakout Chart.png', build)


@unittest.skipUnless(EXE.is_file(), 'Build the release first')
class ReleaseArtifactTests(unittest.TestCase):
    def test_public_resources_runtime_and_blank_example_only(self):
        self.assertEqual({p.name for p in RELEASE.iterdir()},
                         {'PriceActionTradingAgent.exe', '_internal', 'telegram_config.example.json', 'README-SETUP.txt',
                          'LICENSE', 'THIRD-PARTY-NOTICES.md', 'third_party_licenses'})
        for name in ('LICENSE', 'THIRD-PARTY-NOTICES.md'):
            self.assertEqual((RELEASE / name).read_bytes(), (PROJECT / name).read_bytes())
        for license_file in (PROJECT / 'third_party_licenses').iterdir():
            self.assertEqual((RELEASE / 'third_party_licenses' / license_file.name).read_bytes(),
                             license_file.read_bytes())
        example = json.loads((RELEASE / 'telegram_config.example.json').read_text())
        self.assertEqual(example, {'bot_token':'', 'chat_id':''})
        forbidden = {'telegram_config.local.json', 'auth.json', 'config.toml', 'models_cache.json',
                     'cookies', 'cookies.sqlite', '.env'}
        self.assertFalse(any(p.name.lower() in forbidden for p in RELEASE.rglob('*')))
        for name in (ICON, 'Futuristic AI Robot with Breakout Chart.png'):
            self.assertEqual(hashlib.sha256((INTERNAL / 'assets' / name).read_bytes()).digest(),
                             hashlib.sha256((PROJECT / 'assets' / name).read_bytes()).digest())
        self.assertTrue(list(INTERNAL.rglob('dark-blue.json')))
        self.assertTrue(list(INTERNAL.rglob('CustomTkinter_shapes_font.otf')))
        self.assertTrue(list((INTERNAL / 'PIL').glob('_imaging*.pyd')))
        self.assertTrue(list(INTERNAL.glob('python3*.dll')))
        from PyInstaller.archive.readers import CArchiveReader
        archive = CArchiveReader(str(EXE))
        pyz = archive.open_embedded_archive('PYZ.pyz')
        for module in ('sr_agent','sr_grouping','telegram_sender','ui_dialogs','customtkinter','PIL.ImageTk'):
            self.assertIn(module, pyz.toc)
        self.assertFalse(any(Path(name).name.lower() in forbidden for name in archive.toc))

    def test_windowed_x64_exe_embeds_exact_robot_icon_images(self):
        import pefile
        pe = pefile.PE(str(EXE))
        try:
            self.assertEqual(pe.FILE_HEADER.Machine, 0x8664)
            self.assertEqual(pe.OPTIONAL_HEADER.Subsystem, 2)  # Windows GUI, no console.
            actual = set()
            for resource in pe.DIRECTORY_ENTRY_RESOURCE.entries:
                if resource.id == 3:  # RT_ICON
                    for entry in resource.directory.entries:
                        for language in entry.directory.entries:
                            data = language.data.struct
                            actual.add(pe.get_data(data.OffsetToData, data.Size))
            raw = (PROJECT / 'assets' / ICON).read_bytes()
            count = struct.unpack_from('<H', raw, 4)[0]
            expected = set()
            for index in range(count):
                size, offset = struct.unpack_from('<II', raw, 6+index*16+8)
                expected.add(raw[offset:offset+size])
            self.assertEqual(actual, expected)
        finally:
            pe.close()

    def test_actual_exe_launches_offline_with_visible_window_and_icon_without_private_config(self):
        self.assertFalse((RELEASE / 'telegram_config.local.json').exists())
        fixture = PROJECT / 'build' / 'release-offline-check'
        fixture.mkdir(parents=True, exist_ok=True)
        (fixture / 'models_cache.json').write_text(json.dumps({'models':[
            {'slug':'gpt-6-astra','visibility':'list'}, {'slug':'gpt-6-sol','visibility':'list'}],
            'fetched_at':'OFFLINE TEST FIXTURE'}), encoding='utf-8')
        env = dict(os.environ, CODEX_HOME=str(fixture),
                   SR_TRADINGVIEW_MCP_DIR=str(fixture / 'missing-connector'),
                   SR_NODE_PATH=str(fixture / 'missing-node.exe'), SR_CODEX_PATH=str(fixture / 'missing-codex.exe'))
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SendMessageW.restype = ctypes.c_void_p
        process = subprocess.Popen([str(EXE)], cwd=fixture, env=env,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            windows = []
            @callback_type
            def visit(hwnd, _):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == process.pid and user32.IsWindowVisible(hwnd):
                    title = ctypes.create_unicode_buffer(512)
                    user32.GetWindowTextW(hwnd, title, len(title))
                    if title.value == 'Trade With AM — Price Action Trading Agent':
                        windows.append(hwnd)
                return True
            deadline = time.monotonic()+15
            while time.monotonic() < deadline and not windows:
                self.assertIsNone(process.poll(), 'The packaged GUI exited before showing its window')
                user32.EnumWindows(visit, 0)
                time.sleep(.1)
            self.assertTrue(windows, 'The EXE did not expose its expected visible main window')
            time.sleep(1)
            self.assertIsNone(process.poll())
            self.assertTrue(user32.SendMessageW(windows[0], 0x7f, 1, 0)
                            or user32.SendMessageW(windows[0], 0x7f, 0, 0), 'No window icon was assigned')
        finally:
            # Only our isolated, idle smoke-test child is stopped; no analysis was started.
            process.terminate()
            process.wait(timeout=10)


@unittest.skipUnless(EXE.is_file(), 'Build the release first')
class ReleaseGuiTests(unittest.TestCase):
    close = trade_tests.SetupGuiTests.close
    pump = trade_tests.SetupGuiTests.pump
    schedule_action = dialog_tests.DarkDialogTests.schedule_action
    check_action = dialog_tests.DarkDialogTests.check_action

    @classmethod
    def setUpClass(cls):
        from PyInstaller.archive.readers import CArchiveReader
        archive = CArchiveReader(str(EXE))
        pyz = archive.open_embedded_archive('PYZ.pyz')
        modules = {name:types.ModuleType(name) for name in ('sr_grouping','telegram_sender','sr_agent','ui_dialogs')}
        cls.module_patch = patch.dict(sys.modules, modules)
        cls.module_patch.start()
        cls.addClassCleanup(cls.module_patch.stop)
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(EXE)):
            for name, module in modules.items():
                module.__file__ = str(INTERNAL / (name+'.py'))
                exec(pyz.extract(name), module.__dict__)
            cls.gui = types.ModuleType('release_gui_check')
            cls.gui.__file__ = str(INTERNAL / 'main.py')
            exec(marshal.loads(archive.extract('main')), cls.gui.__dict__)
        cls.dark_confirm = staticmethod(cls.gui.messagebox.askokcancel)
        cls.telegram = modules['telegram_sender']
        cls.agent = modules['sr_agent']

    def setUp(self):
        self.enterContext(patch.object(socket, 'socket', side_effect=AssertionError('Real network forbidden')))
        self.enterContext(patch.object(trade_tests, 'main', self.gui))
        self.enterContext(patch.object(sys, 'frozen', True, create=True))
        self.enterContext(patch.object(sys, 'executable', str(EXE)))
        self.send = self.enterContext(patch.object(self.gui, 'send_trade_analysis'))
        original = self.gui.ctk.CTk.iconbitmap
        self.icons = self.enterContext(patch.object(self.gui.ctk.CTk, 'iconbitmap', autospec=True, side_effect=original))
        trade_tests.SetupGuiTests.setUp(self)
        self.root.deiconify()
        self.root.update()

    def test_bundled_dark_gui_icon_image_and_missing_private_config_startup(self):
        self.assertEqual(self.gui.ctk.get_appearance_mode(), 'Dark')
        self.icons.assert_any_call(self.root, str(INTERNAL / 'assets' / ICON))
        self.assertTrue(self.root._iconbitmap_method_called)
        self.assertTrue(self.app.agent_image_label.winfo_ismapped())
        self.assertEqual(self.app.agent_image.cget('dark_image').mode, 'RGBA')
        self.assertEqual(self.agent.PROJECT_DIR, RELEASE)
        self.assertEqual(self.telegram.local_config_path(), RELEASE / 'telegram_config.local.json')
        with self.assertRaisesRegex(ValueError, 'Missing telegram_config.local.json'):
            self.telegram.load_config()
        self.assertTrue(self.root.winfo_exists())

    def test_bundled_dropdowns_checkboxes_callbacks_and_persistent_progress(self):
        self.app.symbol_box.set('BYBIT:BTCUSDT.P')
        self.app.model_box.set('gpt-6-sol')
        self.app.levels_box.set('4')
        self.assertEqual(self.app.selection(), ('BYBIT:BTCUSDT.P',['1H','4H','1D'],4,'gpt-6-sol'))
        for _ in range(2):
            self.app.show_status_box.toggle()
            self.root.update()
            self.assertEqual(bool(self.app.output.winfo_ismapped()), self.app.show_status.get())
            self.assertTrue(self.app.progress.winfo_ismapped())
            self.assertTrue(self.app.status_label.winfo_ismapped())
        self.assertEqual(self.app.progress.cget('width'), 165)
        self.assertEqual(self.app.progress.cget('height'), 10)
        self.app.all_charts_box.toggle()
        self.app.find_button.invoke()
        self.app.trade_button.invoke()
        self.assertIn('not yet implemented', self.app.status.get())
        self.app.all_charts_box.toggle()
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

    def test_bundled_confirmation_is_dark_modal_robot_icon_and_cancel_is_safe(self):
        original = self.gui.ctk.CTkToplevel.iconbitmap
        with patch.object(self.gui.ctk.CTkToplevel, 'iconbitmap', autospec=True, side_effect=original) as icons:
            result, seen = self.check_action(self.dark_confirm, 'Cancel')
        self.assertTrue(any(call.args[1:] == (str(INTERNAL / 'assets' / ICON),) for call in icons.call_args_list))
        self.assertFalse(result)
        self.assertEqual(seen['button_names'], {'OK','Cancel'})
        self.verify.assert_not_called()
        self.run.assert_not_called()
        self.send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
