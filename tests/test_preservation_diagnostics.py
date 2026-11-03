"""Preservation readback failures remain visible without driving an analysis engine."""
from copy import deepcopy
import unittest
from tests.test_grouping import snapshot,finished
from sr_grouping import verify_readbacks

class PreservationDiagnosticsTests(unittest.TestCase):
    def test_every_existing_point_style_label_and_visibility_change_is_reported(self):
        for field in ('time','price','style','text','visible'):
            current=finished()
            if field in ('time','price'):current['drawings'][0]['points'][0][field]+=1
            else:current['drawings'][0]['properties'][field]='changed'
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'old'):
                verify_readbacks(snapshot(),current,trade=False,levels=3,response='Offline report.')
    def test_missing_original_is_named(self):
        current=finished();current['drawings'].pop(0)
        with self.assertRaisesRegex(ValueError,'old'):
            verify_readbacks(snapshot(),current,trade=False,levels=3,response='Offline report.')
    def test_readback_cannot_claim_success_with_no_group(self):
        with self.assertRaisesRegex(ValueError,'No independently verified'):
            verify_readbacks(snapshot(),snapshot(),trade=False,levels=3,response='Everything drawn successfully.')
