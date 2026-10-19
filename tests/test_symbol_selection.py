"""Offline only: mocked helper transport, fake connector modules and Tk jobs."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import sr_agent as sr
import main
from tests.test_grouping import TARGET
from tests import test_trade_setups as trade_tests

SOURCE = dict(TARGET, symbol="BYBIT:BTCUSDT.P")
DESTINATION = TARGET["symbol"]


class SelectionHelperTests(unittest.TestCase):
    def setUp(self):
        self.inspect = self.enterContext(patch.object(sr,"inspect_tradingview_chart",return_value=json.dumps(SOURCE)))
        self.verify = self.enterContext(patch.object(sr,"verify_tradingview_chart",return_value=json.dumps(TARGET)))
        self.lock = self.enterContext(patch.object(sr,"GroupingSession"))
        self.run = self.enterContext(patch.object(sr.subprocess,"run",return_value=subprocess.CompletedProcess([],0,
                   json.dumps({"success":True,"symbol":DESTINATION,"chart_ready":True}),"")))

    def select(self, **kwargs):
        return sr.ensure_selected_symbol(DESTINATION,json.dumps(SOURCE),live_confirmed=True,**kwargs)

    def test_already_matches_never_calls_setter(self):
        self.inspect.return_value=json.dumps(TARGET)
        result=sr.ensure_selected_symbol(DESTINATION,json.dumps(TARGET),live_confirmed=True)
        self.assertEqual(json.loads(result),TARGET)
        self.run.assert_called_once()  # Existing render-readiness check only.
        payload=json.loads(self.run.call_args.kwargs["input"])
        self.assertEqual(payload["approved_target"]["symbol"],payload["destination"])

    def test_exact_switch_single_call_same_chart_and_no_switch_back(self):
        self.assertEqual(json.loads(self.select()),TARGET)
        self.run.assert_called_once()
        command=self.run.call_args.args[0]
        self.assertEqual(command[-1],sr._SELECT_SYMBOL_PROGRAM)
        self.assertFalse(self.run.call_args.kwargs["shell"])
        self.assertEqual(json.loads(self.run.call_args.kwargs["input"]),{"approved_target":SOURCE,"destination":DESTINATION})
        self.verify.assert_called_once_with(DESTINATION)
        self.lock.return_value.exclusive.assert_called_once()
        self.assertNotIn("chart_set_symbol",sr.TRADINGVIEW_SR_TOOLS)

    def test_no_consent_or_bare_alias_does_not_read_or_switch(self):
        with self.assertRaisesRegex(ValueError,"Explicit confirmation"):
            sr.ensure_selected_symbol(DESTINATION,SOURCE)
        with self.assertRaisesRegex(ValueError,"full exchange-qualified"):
            sr.ensure_selected_symbol("BYBIT.P",SOURCE,live_confirmed=True)
        self.run.assert_not_called()
        self.inspect.assert_not_called()

    def test_unavailable_wrong_symbol_unready_and_invalid_output_stop_without_retry(self):
        cases=[(1,{"success":False,"error":"Symbol unavailable"},"Symbol unavailable"),
               (0,{"success":True,"symbol":SOURCE["symbol"],"chart_ready":True},"Exact destination"),
               (0,{"success":True,"symbol":DESTINATION,"chart_ready":False},"readiness"),
               (1,None,"Connector import error")]
        for code,data,message in cases:
            with self.subTest(message=message):
                self.run.reset_mock();self.verify.reset_mock()
                self.run.return_value=subprocess.CompletedProcess([],code,json.dumps(data) if data else "","Connector import error")
                with self.assertRaisesRegex(ValueError,message):self.select()
                self.run.assert_called_once()
                self.verify.assert_not_called()

    def test_loading_timeout_never_retries_or_verifies_as_success(self):
        self.run.side_effect=subprocess.TimeoutExpired("offline-node",35)
        with self.assertRaisesRegex(ValueError,"no automatic retry"):
            self.select()
        self.run.assert_called_once()
        self.verify.assert_not_called()

    def test_source_target_changed_since_confirmation_prevents_switch(self):
        for field,value in (("tab_id","OTHER"),("url","https://www.tradingview.com/chart/OTHER/"),
                            ("symbol","OTHER:SYMBOL"),("layout","2h")):
            with self.subTest(field=field):
                self.inspect.return_value=json.dumps(dict(SOURCE,**{field:value}))
                with self.assertRaisesRegex(ValueError,"changed since confirmation"):self.select()
        self.run.assert_not_called()

    def test_post_switch_tab_pane_layout_candles_or_symbol_mismatch_stops(self):
        for field,value in (("tab_id","OTHER"),("pane_index",1),("layout","2h"),("chart_type",2),("symbol","OTHER:SYMBOL")):
            with self.subTest(field=field):
                self.run.reset_mock()
                self.verify.return_value=json.dumps(dict(TARGET,**{field:value}))
                with self.assertRaisesRegex(ValueError,"Symbol selection stopped"):self.select()
                self.run.assert_called_once()


class FixedProgramTests(unittest.TestCase):
    """Execute the production Node wrapper, importing fake local modules only."""
    def setUp(self):
        self.node=sr.node_executable()
        self.folder=Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.folder/'src'/'core').mkdir(parents=True)
        (self.folder/'package.json').write_text('{"type":"module"}',encoding='utf-8')
        (self.folder/'src'/'fake.js').write_text("""
import fs from 'node:fs';
export const s=JSON.parse(fs.readFileSync(new URL('../state.json',import.meta.url),'utf8'));
export const calls={set:[],render:0,disconnected:false};
export function persist(){fs.writeFileSync(new URL('../calls.json',import.meta.url),JSON.stringify(calls));}
""",encoding='utf-8')
        (self.folder/'src'/'core'/'chart.js').write_text("""
import {s,calls,persist} from '../fake.js';
export async function getState(){return {success:true,symbol:s.symbol,chartType:s.chart_type};}
export async function setSymbol({symbol}){
 calls.set.push(symbol);persist();
 if(s.unavailable)throw Error('Symbol unavailable');
 s.symbol=s.wrong_symbol||symbol;
 if(s.changed_tab)s.tab_id='OTHER';
 if(s.changed_pane)s.pane_index=1;
 return {success:true,symbol,chart_ready:false};
}
""",encoding='utf-8')
        (self.folder/'src'/'core'/'tab.js').write_text("""
import {s} from '../fake.js';
export async function list(){return {success:true,tab_count:1,tabs:[{id:s.tab_id,url:s.url,chart_id:s.chart_id,is_chart:true}]};}
""",encoding='utf-8')
        (self.folder/'src'/'core'/'pane.js').write_text("""
import {s} from '../fake.js';
export async function list(){return {success:true,layout:s.layout,chart_count:1,active_index:s.pane_index,
 panes:[{index:s.pane_index,symbol:s.symbol}]};}
""",encoding='utf-8')
        (self.folder/'src'/'connection.js').write_text("""
import {s,calls,persist} from './fake.js';
export async function getTargetInfo(){return {id:s.tab_id,url:s.url};}
export async function disconnect(){calls.disconnected=true;persist();}
""",encoding='utf-8')
        (self.folder/'src'/'wait.js').write_text("""
import {s,calls,persist} from './fake.js';
export async function waitForChartRender(){calls.render++;persist();return s.ready;}
""",encoding='utf-8')

    def execute(self, *, destination=DESTINATION, **changes):
        state=dict(SOURCE,ready=True)
        state.update(changes)
        (self.folder/'state.json').write_text(json.dumps(state),encoding='utf-8')
        result=subprocess.run([self.node,'--input-type=module','-e',sr._SELECT_SYMBOL_PROGRAM],
                              input=json.dumps({'approved_target':SOURCE,'destination':destination}),
                              capture_output=True,text=True,encoding='utf-8',cwd=self.folder,timeout=5)
        self.assertTrue(result.stdout,result.stderr)
        return json.loads(result.stdout),json.loads((self.folder/'calls.json').read_text())

    def test_existing_render_wait_can_confirm_exact_loaded_symbol_despite_legacy_header_timeout(self):
        result,calls=self.execute()
        self.assertTrue(result['success'])
        self.assertTrue(result['chart_ready'])
        self.assertFalse(result['connector_symbol_ready'])
        self.assertEqual(calls['set'],[DESTINATION])
        self.assertEqual(calls['render'],1)
        self.assertTrue(calls['disconnected'])

    def test_already_displayed_symbol_checks_readiness_without_any_setter_call(self):
        result,calls=self.execute(destination=SOURCE['symbol'])
        self.assertTrue(result['success'])
        self.assertEqual(calls['set'],[])
        self.assertEqual(calls['render'],1)

    def test_source_tab_or_pane_mismatch_never_calls_existing_setter(self):
        for changes in ({'tab_id':'OTHER'},{'pane_index':1},{'layout':'2h'},{'chart_type':2}):
            with self.subTest(changes=changes):
                result,calls=self.execute(**changes)
                self.assertFalse(result['success'])
                self.assertEqual(calls['set'],[])

    def test_unavailable_loading_timeout_wrong_symbol_and_changed_chart_fail_once(self):
        for changes in ({'unavailable':True},{'ready':False},{'wrong_symbol':'OTHER:SYMBOL'},
                        {'changed_tab':True},{'changed_pane':True}):
            with self.subTest(changes=changes):
                result,calls=self.execute(**changes)
                self.assertFalse(result['success'])
                self.assertEqual(calls['set'],[DESTINATION])
                self.assertTrue(calls['disconnected'])


class SelectionGuiTests(unittest.TestCase):
    setUp = trade_tests.SetupGuiTests.setUp
    close = trade_tests.SetupGuiTests.close
    pump = trade_tests.SetupGuiTests.pump

    def test_both_buttons_confirm_requested_change_before_shared_helper(self):
        self.inspect.return_value=json.dumps(SOURCE)
        self.run.return_value=sr.AnalysisOutcome('failed',errors='Offline fixture: no analysis executed')
        self.sr_run.return_value=sr.AnalysisOutcome('failed',errors='Offline fixture: no analysis executed')
        self.confirm.return_value=True
        for trade in (False,True):
            with self.subTest(trade=trade):
                self.verify.reset_mock();self.confirm.reset_mock()
                self.app.find_trade_setups() if trade else self.app.find_levels()
                self.pump(lambda:not self.app.running)
                message=self.confirm.call_args.args[1]
                self.assertIn(SOURCE['symbol']+' → '+DESTINATION,message)
                self.assertNotIn('pane',message)
                self.assertLess(len(message.split()),65)
                self.verify.assert_called_once_with(DESTINATION,json.dumps(SOURCE),live_confirmed=True)
        self.run.assert_called_once()
        self.sr_run.assert_called_once()

    def test_cancel_mismatch_confirmation_never_switches_or_runs_ai(self):
        self.inspect.return_value=json.dumps(SOURCE)
        self.confirm.return_value=False
        with patch.object(main,'send_trade_analysis') as send:
            for trade in (False,True):
                self.app.find_trade_setups() if trade else self.app.find_levels()
                self.pump(lambda:not self.app.running)
            send.assert_not_called()
        self.verify.assert_not_called()
        self.run.assert_not_called()
        self.sr_run.assert_not_called()

    def test_concise_dialogs_show_dynamic_selections_and_only_needed_switch(self):
        self.confirm.return_value=False
        for frames in (['1H'],['4H','15m'],['1H','4H','1D']):
            display = {1:'1H',2:'4H and 15m',3:'1H, 4H and 1D'}[len(frames)]
            for trade in (False,True):
                for current in (TARGET,SOURCE):
                    with self.subTest(frames=frames,trade=trade,current=current['symbol']):
                        self.confirm.reset_mock()
                        self.app.confirm_analysis((DESTINATION,frames,3,'gpt-6-sol'),trade,json.dumps(current))
                        title,message=self.confirm.call_args.args
                        self.assertEqual(title,'Confirm Trade Setup Analysis' if trade else 'Confirm TradingView Analysis')
                        drawings='potential trade setups' if trade else 'support and resistance levels'
                        self.assertIn(f'Analyze {DESTINATION} on {display}, then draw {drawings} on TradingView.',message)
                        self.assertLess(len(message.split()),65)
                        self.assertEqual(message.count('\n\n'),1)
                        self.assertTrue(message.endswith('Continue?'))
                        self.assertEqual('Telegram' in message,trade)
                        if current['symbol']!=DESTINATION:
                            self.assertIn(current['symbol']+' → '+DESTINATION,message)
                        else:
                            self.assertNotIn('switch',message.lower())
                            self.assertNotIn('→',message)
                        for technical in ('Selected Codex model','pane','candlestick','grouping','chart_id'):
                            self.assertNotIn(technical,message)
                        self.assertIs(self.confirm.call_args.kwargs['parent'],self.root)
                        self.assertEqual(self.confirm.call_args.kwargs['default'],'cancel')
        self.verify.assert_not_called()
        self.run.assert_not_called()
        self.sr_run.assert_not_called()

    def test_cancel_matching_chart_blocks_switch_analysis_and_telegram_for_both_buttons(self):
        self.confirm.return_value=False
        with patch.object(main,'send_trade_analysis') as send:
            for trade in (False,True):
                self.app.find_trade_setups() if trade else self.app.find_levels()
                self.pump(lambda:not self.app.running)
            send.assert_not_called()
        self.verify.assert_not_called()
        self.run.assert_not_called()
        self.sr_run.assert_not_called()

    def test_dialog_uses_selected_symbol_instead_of_a_fixed_gold_example(self):
        for trade in (False,True):
            self.app.confirm_analysis((SOURCE['symbol'],['15m'],2,'gpt-6-sol'),trade,json.dumps(TARGET))
            message=self.confirm.call_args.args[1]
            self.assertIn('Analyze '+SOURCE['symbol']+' on 15m',message)
            self.assertIn(DESTINATION+' → '+SOURCE['symbol'],message)
        self.verify.assert_not_called()
        self.run.assert_not_called()
        self.sr_run.assert_not_called()

    def test_chart_changed_after_confirmation_never_starts_ai(self):
        self.confirm.return_value=True
        self.verify.side_effect=ValueError('Approved tab changed; stopped without recovery')
        self.app.find_levels()
        self.pump(lambda:not self.app.running)
        self.sr_run.assert_not_called()
        self.error.assert_called_once()

    def test_readonly_preview_is_responsive_and_blocks_overlapping_requests(self):
        gate,entered=threading.Event(),threading.Event()
        self.addCleanup(gate.set)
        def slow_preview():
            entered.set();gate.wait(2);return json.dumps(SOURCE)
        self.inspect.side_effect=slow_preview
        self.confirm.return_value=False
        self.app.find_trade_setups()
        self.pump(entered.is_set)
        ticks=[]
        self.root.after(1,lambda:ticks.append(True))
        self.pump(lambda:bool(ticks))
        self.confirm.assert_not_called()
        self.assertTrue(self.app.running)
        self.app.find_levels()
        self.inspect.assert_called_once()
        gate.set()
        self.pump(lambda:not self.app.running)
        self.verify.assert_not_called()


if __name__=='__main__':unittest.main()
