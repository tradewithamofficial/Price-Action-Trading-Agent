"""Read-only chart verification/lock tests; no model or live connector."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import sr_grouping as grouping

TARGET = {'tab_id':'offline-tab','url':'https://www.tradingview.com/chart/offline/','chart_id':'offline',
          'pane_index':0,'layout':'s','symbol':'BYBIT:XAUUSDT.P','chart_type':1}
OLD = {'id':'old','shape':'horizontal_line','points':[{'time':1,'price':100}],
       'properties':{'text':'Original drawing','linecolor':'#ffffff'}}
NEW = [{'id':f'new{i}','shape':'horizontal_line','points':[{'time':1,'price':i}],
        'properties':{'text':f'R{i}'}} for i in range(1,7)]

def snapshot():
    return {'target':deepcopy(TARGET),'resolution':'60','drawings':[deepcopy(OLD)],
            'groups':[{'id':'original','name':'Manual annotations','ids':['old']}], 'studies':[]}

def finished(trade=False):
    data=snapshot();data['drawings']+=deepcopy(NEW)
    data['groups'].append({'id':'newgroup','name':grouping.SETUP_GROUP_NAMES[0] if trade else grouping.GROUP_NAME,
                           'ids':[d['id'] for d in NEW]})
    return data

class ReadbackTests(unittest.TestCase):
    def verify(self,after,trade=False,response='Completed offline analysis.'):
        return grouping.verify_readbacks(snapshot(),after,trade=trade,levels=3,response=response)
    def test_new_drawings_and_exact_group_are_read_back(self):
        self.assertIn('6 new objects',self.verify(finished()))
        self.assertIn('1 new group',self.verify(finished(True),True))
    def test_missing_wrong_or_ungrouped_objects_are_not_verified(self):
        for kind in ('wrongname','ungrouped','missing','adoptold'):
            data=finished()
            if kind=='wrongname':data['groups'][-1]['name']='Unrelated'
            if kind=='ungrouped':data['groups'][-1]['ids'].pop()
            if kind=='missing':data['drawings'].pop()
            if kind=='adoptold':data['groups'][-1]['ids'].append('old')
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.verify(data)
    def test_existing_object_or_group_change_and_timeframe_change_are_rejected(self):
        for kind in ('price','delete','group','timeframe','study'):
            data=finished()
            if kind=='price':data['drawings'][0]['points'][0]['price']=101
            if kind=='delete':data['drawings'].pop(0)
            if kind=='group':data['groups'][0]['ids'].append('new1')
            if kind=='timeframe':data['resolution']='240'
            if kind=='study':data['studies']=[{'id':'new-study'}]
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.verify(data)
    def test_ordering_does_not_invent_a_preservation_failure(self):
        data=finished();data['drawings'].reverse();data['groups'].reverse()
        self.verify(data)
    def test_no_valid_setup_without_any_changes_is_verified_as_no_drawings(self):
        self.assertIn('No new drawings',self.verify(snapshot(),True,'NO VALID SETUP — offline fixture.'))
    def test_existing_setup_group_is_not_adopted_and_distinct_new_group_is_allowed(self):
        data=finished(True);data['groups'][-1]['name']='Price Action Setup 1 (new analysis)'
        self.verify(data,True)
    def test_duplicate_ids_and_changed_target_fail(self):
        data=finished();data['drawings'].append(deepcopy(OLD))
        with self.assertRaises(ValueError):self.verify(data)
        data=finished();data['target']['tab_id']='other'
        with self.assertRaises(ValueError):self.verify(data)

class ChartSessionTests(unittest.TestCase):
    def test_shared_lock_prevents_overlap_and_releases(self):
        with tempfile.TemporaryDirectory() as folder:
            a=grouping.ChartSession(TARGET,Mock(),'.','node',directory=folder)
            b=grouping.ChartSession(TARGET,Mock(),'.','node',directory=folder)
            with a.exclusive():
                with self.assertRaisesRegex(ValueError,'analysis.lock'):
                    with b.exclusive():pass
            self.assertFalse((Path(folder)/'analysis.lock').exists())
    def test_snapshot_is_fixed_and_read_only(self):
        verify=Mock(return_value=json.dumps(TARGET))
        session=grouping.ChartSession(TARGET,verify,'.','node')
        with patch.object(grouping.subprocess,'run',return_value=subprocess.CompletedProcess([],0,
                stdout=json.dumps({'success':True,'result':snapshot()}),stderr='')) as run:
            self.assertEqual(session.snapshot(),snapshot())
        expression=run.call_args.args[0][-1]
        for mutation in ('createGroup','setGroupName','remove','setSymbol'):
            self.assertNotIn(mutation,expression)
        self.assertEqual(verify.call_count,2)
    def test_invalid_target_is_rejected_before_subprocess(self):
        for key,value in [('symbol','BYBIT.P'),('pane_index',1),('chart_type',3)]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                grouping.ChartSession(dict(TARGET,**{key:value}),Mock(),'.','node')

if __name__=='__main__':unittest.main()
