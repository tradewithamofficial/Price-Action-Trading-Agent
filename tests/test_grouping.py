"""Offline only: fake TradingView page in Node, mocked connector/CLI and Tk."""
from copy import deepcopy
import json
from pathlib import Path
import queue
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import sr_agent as sr
import sr_grouping as grouping

TARGET = {"tab_id": "TAB", "url": "https://www.tradingview.com/chart/TEST/", "chart_id": "TEST",
          "pane_index": 0, "layout": "s", "symbol": sr.DEFAULT_SYMBOL, "chart_type": 1}
OLD = {"id": "old", "shape": "rectangle", "points": [{"time": 1, "price": 10}, {"time": 2, "price": 11}],
       "properties": {"text": "unrelated"}}
NEW = [
    {"id": "new1", "shape": "horizontal_line", "points": [{"time": 1, "price": 8}],
     "properties": {"text": "8 | 1H", "linecolor": "#008000"}},
    {"id": "new2", "shape": "rectangle", "points": [{"time": 1, "price": 12}, {"time": 2, "price": 13}],
     "properties": {"text": "12–13 | 1H", "color": "#ff0000", "backgroundColor": "rgba(255, 0, 0, 0.1)"}},
]

# Runs the production fixed expression against an in-memory page, with no CDP,
# connector imports, external data, model, or live chart connection.
HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0,'utf8')), state = input.state;
let creates = 0, renames = 0;
const controller = {
 groups: () => state.groups.map(x=>x.id),
 getGroupName: id => state.groups.find(x=>x.id===id).name,
 shapesInGroup: id => state.groups.find(x=>x.id===id).ids,
 createGroup: ids => { creates++; let n=1; while(state.groups.some(x=>x.id==='group'+n)) n++;
   const id='group'+n; state.groups.push({id,name:'',ids:ids.slice()}); return id; },
 setGroupName: (id,name) => { renames++; if(state.failRename || state.failRenameName===name) throw Error('rename failed');
   state.groups.find(x=>x.id===id).name=name; }
};
const widget = {}, chart = {
 _chartWidget:widget, symbol:()=>state.symbol, chartType:()=>state.chartType,
 resolution:()=>state.resolution, getAllStudies:()=>state.studies,
 shapesGroupController:()=>controller,
 getAllShapes:()=>state.drawings.map(x=>({id:x.id,name:x.shape})),
 getShapeById:id=>{const d=state.drawings.find(x=>x.id===id);
   return {getPoints:()=>d.points,getProperties:()=>d.properties};}
};
const context = {location:{href:state.url,pathname:new URL(state.url).pathname},
 window:{TradingViewApi:{_activeChartWidgetWV:{value:()=>chart},
 _chartWidgetCollection:{_layoutType:{value:()=>state.layout},getAll:()=>[widget]}}}};
try { const result=vm.runInNewContext(input.script,context,{timeout:1000});
 console.log(JSON.stringify({result,state,creates,renames})); }
catch(e) { console.log(JSON.stringify({error:e.message,state,creates,renames})); }
"""


class OfflineSession(grouping.GroupingSession):
    """Only transport is replaced; production validation/group JS executes."""
    def __init__(self, directory):
        super().__init__(TARGET, Mock(return_value=json.dumps(TARGET)), Path.cwd(), sr.node_executable(), directory=directory)
        self.state = {"symbol": TARGET["symbol"], "url": TARGET["url"], "chartType": 1,
                      "layout": "s", "resolution": "60", "drawings": [deepcopy(OLD)],
                      "groups": [], "studies": [{"id": "indicator", "name": "Existing indicator"}]}
        self.creates = self.renames = 0
        self.fault = None

    def call(self, operation, drawings=None, *, group_name=grouping.GROUP_NAME):
        completed = subprocess.run([self.node, "-e", HARNESS],
                                   input=json.dumps({"state": self.state, "script": grouping.fixed_operation(operation, self.target, drawings=drawings, group_name=group_name)}),
                                   capture_output=True, text=True, encoding="utf-8", timeout=5)
        if completed.returncode:
            raise AssertionError(completed.stderr)
        data = json.loads(completed.stdout)
        self.state = data["state"]
        self.creates += data["creates"]
        self.renames += data["renames"]
        if "error" in data:
            raise ValueError(data["error"])
        if operation == "create" and self.fault:
            self.fault(data["result"], self.state)
        return data["result"]

    def completion(self):
        return json.dumps({"schema": 1, "run_id": self.run_id, "target": self.target,
                           "status": "complete", "errors": [], "summary": "done",
                           "drawings": [dict(deepcopy(d), role=role) for d,role in zip(NEW, ("support", "resistance"))]})


class GroupingTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.session = OfflineSession(self.directory)
        if not self.session.node:
            self.skipTest("Node is required for the offline JavaScript harness")
        self.session.prepare()
        self.session.state["drawings"] += deepcopy(NEW)

    def finish(self):
        return self.session.finish(self.session.completion(), 1)

    def test_success_creates_exact_group_preserves_old_objects_and_persists(self):
        path = self.finish()
        record = json.loads(path.read_text())
        self.assertEqual(self.session.creates, 1)
        self.assertEqual(self.session.renames, 1)
        self.assertEqual(self.session.state["groups"], [{"id": "group1", "name": grouping.GROUP_NAME, "ids": ["new1", "new2"]}])
        self.assertEqual(self.session.state["drawings"][0], OLD)
        self.assertEqual(record["last_verification_status"], "verified")
        self.assertEqual(record["target"], TARGET)
        self.assertEqual(record["drawing_ids"], ["new1", "new2"])
        self.assertEqual(record["group_id"], "group1")
        self.assertTrue(record["created_at"])

    def test_group_name_and_membership_must_both_match(self):
        for key, value in (("name", "Wrong group"), ("ids", ["new1", "old"])):
            with self.subTest(key=key):
                self.session.state["groups"] = []
                self.session.fault = lambda result,state: (result.update({key:value}), state["groups"][0].update({key:value}))
                with self.assertRaisesRegex(ValueError, "name or exact membership|Unexpected new group"):
                    self.finish()
                self.assertNotEqual(self.session.record["last_verification_status"], "verified")

    def test_drawing_mismatch_and_old_id_cannot_be_adopted(self):
        original = deepcopy(self.session.state)
        for field, value in (("shape", "trend_line"), ("points", [{"time": 1, "price": 9}]), ("properties", {"text": "wrong"})):
            with self.subTest(field=field):
                self.session.state = deepcopy(original)
                self.session.state["drawings"][1][field] = value
                with self.assertRaises(ValueError):
                    self.finish()
        record = json.loads(self.session.completion())
        record["drawings"][0]["id"] = "old"
        with self.assertRaisesRegex(ValueError, "new chart objects"):
            self.session.finish(json.dumps(record), 1)
        self.assertEqual(self.session.creates, 0)

    def test_page_target_mismatch_never_creates_group(self):
        for key,value in (("symbol", "OTHER:SYMBOL"), ("url", "https://www.tradingview.com/chart/OTHER/"), ("layout", "2h"), ("chartType", 2)):
            with self.subTest(key=key):
                state = deepcopy(self.session.state)
                self.session.state[key] = value
                with self.assertRaisesRegex(ValueError, "mismatch"):
                    self.finish()
                self.session.state = state
        self.assertEqual(self.session.creates, 0)

    def test_ambiguous_existing_group_blocks_prepare(self):
        self.session.state["groups"] = [{"id": "foreign", "name": grouping.GROUP_NAME, "ids": ["old"]}]
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.session.prepare()
        self.assertEqual(self.session.creates, 0)

    def test_rename_failure_preserves_drawings_and_partial_group_without_retry(self):
        self.session.state["failRename"] = True
        with self.assertRaisesRegex(ValueError, "rename failed"):
            self.finish()
        self.assertEqual(self.session.creates, 1)
        self.assertEqual(self.session.renames, 1)
        self.assertEqual(self.session.state["drawings"], [OLD] + NEW)
        self.assertEqual(self.session.record["last_verification_status"], "group_created_unverified")
        self.assertEqual(self.session.record["group_id"], "group1")

    def test_repeated_finish_does_not_create_duplicate(self):
        self.finish()
        with self.assertRaisesRegex(ValueError, "Groups changed"):
            self.finish()
        self.assertEqual(self.session.creates, 1)
        with self.assertRaisesRegex(ValueError, "existing owned group"):
            self.session.prepare()

    def test_local_record_is_not_enough_when_owned_members_change(self):
        self.finish()
        self.session.state["drawings"][1]["properties"]["text"] = "changed"
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.session.prepare()

    def test_unrelated_changes_and_unexpected_new_objects_stop_grouping(self):
        original = deepcopy(self.session.state)
        mutations = [lambda s: s["drawings"][0]["properties"].update(text="changed"),
                     lambda s: s["drawings"].append(dict(deepcopy(NEW[0]), id="unknown")),
                     lambda s: s.update(resolution="240"), lambda s: s.update(studies=[])]
        for mutate in mutations:
            self.session.state = deepcopy(original)
            mutate(self.session.state)
            with self.assertRaises(ValueError):
                self.finish()
        self.assertEqual(self.session.creates, 0)

    def test_completion_must_be_current_run_complete_json(self):
        for value in ("I drew everything successfully", "[]", "{}", self.session.completion().replace(self.session.run_id, "different-run"),
                      self.session.completion().replace('"complete"', '"incomplete"')):
            with self.subTest(value=value[:40]), self.assertRaises(ValueError):
                self.session.finish(value, 1)
        self.assertEqual(self.session.creates, 0)

    def test_exclusive_lock_blocks_second_run_and_is_released(self):
        with self.session.exclusive():
            with self.assertRaisesRegex(ValueError, "analysis.lock"):
                with self.session.exclusive():
                    self.fail("Lock failed")
        self.assertFalse((Path(self.directory) / "analysis.lock").exists())

    def test_arbitrary_operation_and_injected_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            grouping.fixed_operation("alert('arbitrary')", TARGET)
        with self.assertRaises(ValueError):
            grouping.fixed_operation("create", TARGET, drawings=[dict(NEW[0], id="');alert(1);//")])
        with self.assertRaises(ValueError):
            grouping.fixed_operation("create", TARGET, drawings=[NEW[0],NEW[0]])

    def test_drawing_change_between_snapshot_and_mutation_is_blocked(self):
        self.session.state["drawings"][1]["properties"]["text"] = "edited"
        with self.assertRaisesRegex(ValueError, "Drawing changed"):
            self.session.call("create", NEW)
        self.assertEqual(self.session.creates, 0)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.session = OfflineSession(self.directory)
        self.enterContext(patch.object(sr, "GroupingSession", return_value=self.session))

    def analyze(self):
        return sr.run_support_resistance_analysis(sr.DEFAULT_SYMBOL, ["1H"], 1, confirmed_chart=json.dumps(TARGET), live_confirmed=True)

    def execute(self, prompt, model, timeout):
        self.assertIn("APPLICATION COMPLETION PROTOCOL", prompt)
        self.assertIn(self.session.run_id, prompt)
        self.session.state["drawings"] += deepcopy(NEW)
        return sr.AnalysisOutcome("completed_unverified", response=self.session.completion(), return_code=0)

    def test_full_flow_verifies_then_allows_success(self):
        with patch.object(sr, "_execute_codex", side_effect=self.execute) as execute:
            outcome = self.analyze()
        execute.assert_called_once()
        self.assertEqual(outcome.status, "completed_verified")
        self.assertTrue(outcome.drawings_verified)

    def test_partial_grouping_failure_reports_warning_and_records_ids(self):
        self.session.state["failRename"] = True
        with patch.object(sr, "_execute_codex", side_effect=self.execute):
            outcome = self.analyze()
        self.assertEqual(outcome.status, "partial_success")
        self.assertFalse(outcome.drawings_verified)
        self.assertIn("rename failed", outcome.errors)
        record = json.loads(self.session.path.read_text())
        self.assertEqual(record["last_verification_status"], "partial_success")
        self.assertEqual(record["drawing_ids"], ["new1", "new2"])
        self.assertEqual(self.session.creates, 1)

    def test_ambiguous_group_prevents_ai_launch(self):
        self.session.state["groups"] = [{"id": "unknown", "name": grouping.GROUP_NAME, "ids": ["old"]}]
        with patch.object(sr, "_execute_codex") as execute:
            outcome = self.analyze()
        execute.assert_not_called()
        self.assertEqual(outcome.status, "grouping_preflight_failed")

    def test_zero_exit_without_completion_is_never_success(self):
        with patch.object(sr, "_execute_codex", return_value=sr.AnalysisOutcome("completed_unverified", response="all done", return_code=0)):
            outcome = self.analyze()
        self.assertFalse(outcome.drawings_verified)
        self.assertEqual(self.session.creates, 0)

    def test_cli_uses_only_final_message_never_stdout_fallback(self):
        with patch.object(sr, "codex_command", return_value=["mock"]), \
                patch.object(sr.subprocess, "run", return_value=subprocess.CompletedProcess([],0,"TOOL LOGS", "")), \
                patch.object(sr.Path, "exists", return_value=False):
            outcome = sr._execute_codex("prompt", sr.DEFAULT_MODEL, 1)
        self.assertEqual(outcome.response, "")
        self.assertEqual(outcome.output, "TOOL LOGS")

    def test_transport_checks_exact_tab_identity_before_any_evaluation(self):
        session = grouping.GroupingSession(TARGET, Mock(return_value=json.dumps(dict(TARGET,tab_id="OTHER"))), Path.cwd(), "node", directory=self.directory)
        with patch.object(grouping.subprocess, "run") as run, self.assertRaisesRegex(ValueError, "target changed"):
            session.call("snapshot")
        run.assert_not_called()

    def test_popup_only_after_verified_status_and_flag(self):
        import main
        for status, verified in (("completed_verified", True), ("completed_verified",False),
                                 ("partial_success",False), ("completed_unverified",False), ("failed",False)):
            with self.subTest(status=status,verified=verified):
                app = main.SupportResistanceApp.__new__(main.SupportResistanceApp)
                for attr in ("root","progress","find_button","trade_button","refresh_button","status","log"):
                    setattr(app,attr,Mock())
                app.refreshing = False
                app.events = queue.Queue()
                app.events.put(("result", sr.AnalysisOutcome(status, drawings_verified=verified)))
                with patch.object(main.messagebox,"showinfo") as success, patch.object(main.messagebox,"showwarning") as warning:
                    app.poll_events()
                if status == "completed_verified" and verified:
                    success.assert_called_once_with("Analysis Completed", "Support and resistance levels have been successfully drawn and grouped on TradingView.", parent=app.root)
                    warning.assert_not_called()
                else:
                    success.assert_not_called()
                    warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
