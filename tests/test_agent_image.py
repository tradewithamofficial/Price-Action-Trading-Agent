"""Offline checks for the decorative header PNG and its future bundle path."""
import gc
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from PIL import Image
import customtkinter as ctk
import main
from tests import test_trade_setups as trade_tests

ASSET = Path(main.__file__).parent / 'assets' / 'Futuristic AI Robot with Breakout Chart.png'


class ImageLoadingTests(unittest.TestCase):
    def test_ctk_image_keeps_rgba_alpha_and_proportions(self):
        image = main.load_agent_image()
        self.assertIsInstance(image, ctk.CTkImage)
        self.assertEqual(image.cget('size')[0], 160)
        with Image.open(ASSET) as original:
            rgba = original.convert('RGBA')
            for mode in ('light_image', 'dark_image'):
                loaded = image.cget(mode)
                self.assertEqual(loaded.mode, 'RGBA')
                self.assertEqual(loaded.size, original.size)
                self.assertEqual(loaded.getchannel('A').tobytes(), rgba.getchannel('A').tobytes())
                self.assertEqual(loaded.getchannel('A').getextrema(), (0, 255))
            self.assertEqual(image.cget('size')[1], round(original.height * 160 / original.width))

    def test_missing_corrupt_or_unreadable_file_is_optional(self):
        for error in (FileNotFoundError(), OSError('Unreadable offline PNG'), ValueError('Invalid image')):
            with self.subTest(error=type(error).__name__), patch.object(Image, 'open', side_effect=error):
                self.assertIsNone(main.load_agent_image())

    def test_resource_path_uses_module_location_for_source_and_frozen_bundle(self):
        with Image.open(ASSET) as original:
            for folder in (Path(main.__file__).parent, Path(main.__file__).parent / 'mock_MEI_bundle'):
                with self.subTest(folder=folder.name), patch.object(main, '__file__', str(folder / 'main.py')), \
                        patch.object(Image, 'open', return_value=original.copy()) as opened:
                    self.assertIsNotNone(main.load_agent_image())
                    opened.assert_called_once_with(folder / 'assets' / ASSET.name)

    def test_build_argument_only_adds_this_png_to_assets_without_building(self):
        from PyInstaller.__main__ import generate_parser
        args = generate_parser().parse_args(['--add-data', str(ASSET)+';assets', 'main.py'])
        self.assertEqual([(Path(source), destination) for source, destination in args.datas], [(ASSET, 'assets')])
        build = (Path(main.__file__).parent / 'build.ps1').read_text()
        self.assertIn("--add-data \"$(Join-Path $PSScriptRoot 'assets\\"+ASSET.name+"');assets\"", build)


class ImageGuiTests(unittest.TestCase):
    close = trade_tests.SetupGuiTests.close
    pump = trade_tests.SetupGuiTests.pump

    def setUp(self):
        self.enterContext(patch.object(socket, 'socket', side_effect=AssertionError('Real network forbidden')))
        trade_tests.SetupGuiTests.setUp(self)
        self.root.deiconify()
        self.root.update()

    def test_top_right_image_is_transparent_decorative_and_never_overlaps(self):
        label = self.app.agent_image_label
        self.assertIsInstance(label, ctk.CTkLabel)
        self.assertEqual(label.cget('text'), '')
        self.assertEqual(label.cget('fg_color'), 'transparent')
        self.assertEqual(label.cget('corner_radius'), 0)
        self.assertEqual(label.grid_info()['column'], 1)
        self.assertEqual(label.grid_info()['rowspan'], 3)
        body = label.master
        def bounds(widget):
            return (widget.winfo_rootx(), widget.winfo_rooty(),
                    widget.winfo_rootx()+widget.winfo_width(), widget.winfo_rooty()+widget.winfo_height())
        for width in (860, 780):
            self.root.geometry(f'{width}x'+self.root.geometry().split('x')[1])
            self.root.update()
            left, top, right, bottom = bounds(label)
            self.assertTrue(label.winfo_ismapped())
            self.assertLessEqual(right, bounds(body)[2])
            for row in range(3):
                for text in body.grid_slaves(row=row, column=0):
                    self.assertGreaterEqual(left, bounds(text)[2])
            self.assertLessEqual(bottom, bounds(self.app.symbol_box)[1])
            for widget in (self.app.symbol_box, self.app.model_box, self.app.levels_box,
                           self.app.find_button, self.app.trade_button, self.app.show_status_box):
                self.assertTrue(widget.winfo_ismapped())
                x1,y1,x2,y2 = bounds(widget)
                rx1,ry1,rx2,ry2 = bounds(self.root)
                self.assertGreaterEqual(x1,rx1)
                self.assertGreaterEqual(y1,ry1)
                self.assertLessEqual(x2,rx2)
                self.assertLessEqual(y2,ry2)
        gc.collect()
        self.assertIs(label.cget('image'), self.app.agent_image)
        self.assertFalse(self.app.show_status.get())
        self.assertLess(self.root.winfo_height(), 600)
        self.inspect.assert_not_called()
        self.run.assert_not_called()
        self.sr_run.assert_not_called()


class MissingImageGuiTests(unittest.TestCase):
    close = trade_tests.SetupGuiTests.close
    pump = trade_tests.SetupGuiTests.pump

    def setUp(self):
        self.enterContext(patch.object(socket, 'socket', side_effect=AssertionError('Real network forbidden')))
        self.enterContext(patch.object(Image, 'open', side_effect=FileNotFoundError('Offline missing illustration')))
        trade_tests.SetupGuiTests.setUp(self)
        self.root.deiconify()
        self.root.update()

    def test_gui_launches_without_image_and_buttons_keep_original_callbacks(self):
        self.assertTrue(self.root.winfo_exists())
        self.assertIsNone(self.app.agent_image)
        self.assertIsNone(self.app.agent_image_label)
        self.assertIn('GUI ready.', self.app.output.get('1.0', 'end-1c'))
        with patch.object(self.app, 'start_analysis') as start:
            self.app.find_button.invoke()
            start.assert_called_once_with()
            start.reset_mock()
            self.app.trade_button.invoke()
            start.assert_called_once_with(trade=True)
        self.app.show_status_box.toggle()
        self.root.update()
        self.assertTrue(self.app.output_section.winfo_ismapped())
        self.error.assert_not_called()
        self.inspect.assert_not_called()
        self.run.assert_not_called()
        self.sr_run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
