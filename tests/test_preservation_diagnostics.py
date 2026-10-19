"""Focused offline diagnostics tests; no connector, chart or model calls."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import sr_grouping as grouping
from tests.test_grouping import TARGET


class PreservationDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.session = grouping.TradeSetupSession(TARGET, Mock(), Path.cwd(), "unused", directory=self.directory)
        self.drawing = {"id": "Zy1t8H", "shape": "rectangle",
                        "points": [{"price": 4155.35, "time": 1791907200}, {"price": 4156.84, "time": 1792389600}],
                        "properties": {"visible": False, "color": "#008000", "text": "4155.35–4156.84 | 1H / 4H / 1D"}}
        self.session.before = {"target": deepcopy(TARGET), "resolution": "60", "drawings": [deepcopy(self.drawing)],
                               "studies": [], "groups": [{"id": "xDUCHK", "name": grouping.GROUP_NAME, "ids": ["Zy1t8H"]}]}
        self.current = deepcopy(self.session.before)

    def evidence(self):
        return json.loads(self.session.path.read_text(encoding="utf-8"))["preservation_failure"]

    def test_exact_id_fields_values_and_membership_persist_before_failure(self):
        self.current["drawings"][0]["points"][1]["time"] = 1792382400
        self.current["drawings"][0]["properties"]["visible"] = True
        with patch.object(self.session, "call") as connector, self.assertRaises(ValueError) as failure:
            self.session._preserved(self.current)
        connector.assert_not_called()
        self.assertIn("Zy1t8H: points[1].time, properties.visible", str(failure.exception))
        evidence = self.evidence()
        self.assertEqual(evidence["before_snapshot"], self.session.before)
        self.assertEqual(evidence["after_snapshot"], self.current)
        changed = evidence["differences"][0]
        self.assertEqual(changed["drawing_id"], "Zy1t8H")
        self.assertFalse(changed["missing"])
        self.assertEqual(changed["groups_before"][0]["name"], grouping.GROUP_NAME)
        self.assertEqual(changed["fields"], [
            {"field": "points[1].time", "before": 1792389600, "after": 1792382400},
            {"field": "properties.visible", "before": False, "after": True}])
        # Caller status writes retain the original comparison evidence.
        self.session.save("completed_unverified", error="operator review")
        self.assertEqual(self.evidence(), evidence)

    def test_missing_original_is_blocked_and_named(self):
        self.current["drawings"] = []
        with self.assertRaisesRegex(ValueError, "Zy1t8H: missing"):
            self.session._preserved(self.current)
        changed = self.evidence()["differences"][0]
        self.assertTrue(changed["missing"])
        self.assertIsNone(changed["fields"][0]["after"])

    def test_only_dictionary_and_drawing_order_do_not_trigger_mismatch(self):
        other = dict(deepcopy(self.drawing), id="other")
        self.session.before["drawings"].append(other)
        self.current["drawings"] = [other, dict(reversed(list(self.drawing.items())))]
        self.session._preserved(self.current)
        self.assertFalse(self.session.path.exists())

    def test_every_point_price_style_label_and_visibility_change_remains_blocked(self):
        changes = [("points", [{"time": 1791907200, "price": 4150}, {"time": 1792389600, "price": 4156.84}]),
                   ("properties", {"visible": False, "color": "#ff0000", "text": "changed"}),
                   ("properties", {"visible": True, "color": "#008000", "text": self.drawing["properties"]["text"]})]
        for key, value in changes:
            with self.subTest(key=key):
                current = deepcopy(self.session.before)
                current["drawings"][0][key] = value
                with self.assertRaisesRegex(ValueError, "existing drawing changed"):
                    self.session._preserved(current)

    def test_original_timeframe_group_and_target_guards_are_not_changed(self):
        self.current["resolution"] = "240"
        with self.assertRaisesRegex(ValueError, "Original timeframe"):
            self.session._preserved(self.current)
        self.current = deepcopy(self.session.before)
        self.current["groups"][0]["ids"] = []
        with self.assertRaisesRegex(ValueError, "existing group changed"):
            self.session._preserved(self.current)
        with self.assertRaises(ValueError):
            grouping.target_identity(dict(TARGET, chart_type=2))

    def test_failure_to_write_diagnostics_does_not_bypass_guard(self):
        self.current["drawings"] = []
        with patch.object(self.session, "save", side_effect=OSError("disk unavailable")), \
                self.assertRaisesRegex(ValueError, "Zy1t8H: missing.*Could not save"):
            self.session._preserved(self.current)

    def test_missing_property_is_distinguished_from_null(self):
        self.current["drawings"][0]["properties"]["extra"] = None
        with self.assertRaises(ValueError):
            self.session._preserved(self.current)
        field = self.evidence()["differences"][0]["fields"][0]
        self.assertEqual(field["field"], "properties.extra")
        self.assertFalse(field["before_present"])
        self.assertTrue(field["after_present"])


if __name__ == "__main__":
    unittest.main()
