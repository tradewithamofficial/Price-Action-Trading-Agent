"""Direct CLI execution and prompt-file regression tests; no model/chart calls."""
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import sr_agent as sr
from tests.test_grouping import TARGET, snapshot, finished

FRAMES=['1H','4H','1D']
REPORT='Full offline report: conditional LONG triangle breakout. Entry 100.25, stop 99.50, target 103.75. Wait for a close.'

class PromptTests(unittest.TestCase):
    def test_both_default_files_are_preserved_and_pattern_instructions_present(self):
        for trade,filename in ((False,'support_resistance.txt'),(True,'price_action.txt')):
            body=(sr.prompt_directory()/filename).read_text(encoding='utf-8-sig').strip()
            result=(sr.build_trade_setup_prompt(TARGET['symbol'],FRAMES) if trade else
                    sr.build_support_resistance_prompt(TARGET['symbol'],FRAMES))
            self.assertTrue(result.startswith(body+'\n\nGUI'))
        text=sr.build_trade_setup_prompt(TARGET['symbol'],FRAMES)
        for pattern in ('triangles','flags','pennants','head and shoulders','double tops','cup and handle','NO VALID SETUP'):
            self.assertIn(pattern,text)
    def test_custom_counts_change_only_known_count_and_label_markers(self):
        text=sr.build_support_resistance_prompt(TARGET['symbol'],FRAMES,4)
        for expected in ('exactly 4 significant resistance','exactly 4 significant support','Draw all 8','R1, R2, R3, R4','S1, S2, S3, S4'):
            self.assertIn(expected,text)
        self.assertIn('CRITICAL: Preserve everything already on the chart.',text)
    def test_lower_or_incomplete_timeframes_are_rejected(self):
        for frames in (['15m','4H','1D'],['1H'],[],['1H','4H','1D','15m']):
            with self.subTest(frames=frames),self.assertRaisesRegex(ValueError,'tested prompts require'):
                sr.build_trade_setup_prompt(TARGET['symbol'],frames)
    def test_missing_empty_and_edited_nondefault_prompts_fail_clearly(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(sr,'prompt_directory',return_value=Path(directory)):
            with self.assertRaisesRegex(ValueError,'Cannot read editable prompt'):
                sr.build_trade_setup_prompt(TARGET['symbol'],FRAMES)
            p=Path(directory)/'support_resistance.txt';p.write_text('')
            with self.assertRaisesRegex(ValueError,'empty'):sr.build_support_resistance_prompt(TARGET['symbol'],FRAMES)
            p.write_text('A customized analytical prompt.')
            with self.assertRaisesRegex(ValueError,'count markers'):sr.build_support_resistance_prompt(TARGET['symbol'],FRAMES,4)
    def test_frozen_external_editable_prompts_take_precedence_and_missing_file_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);external=root/'reference_simple';external.mkdir()
            with patch.object(sr,'PROJECT_DIR',root),patch.object(sr.sys,'frozen',True,create=True):
                self.assertEqual(sr.prompt_directory(),external)
                with self.assertRaisesRegex(ValueError,'Cannot read'):sr._load_prompt('price_action.txt')
                (external/'price_action.txt').write_text('User-edited complete prompt.',encoding='utf-8')
                self.assertEqual(sr._load_prompt('price_action.txt'),'User-edited complete prompt.')
    def test_exact_approved_target_is_bound_without_changing_analytical_text(self):
        result=sr.build_trade_setup_prompt(TARGET['symbol'],FRAMES,confirmed_chart=json.dumps(TARGET),live_confirmed=True)
        self.assertIn(TARGET['tab_id'],result);self.assertIn(TARGET['url'],result)
        self.assertNotIn('output-schema',result)
        with self.assertRaises(ValueError):sr.build_trade_setup_prompt('BYBIT:BTCUSDT.P',FRAMES,confirmed_chart=TARGET,live_confirmed=True)

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(sr,'PROJECT_DIR',self.directory))
        self.enterContext(patch.object(sr,'codex_command',return_value=['C:/Program Files/Codex/codex.exe']))
        self.enterContext(patch.object(sr,'node_executable',return_value=None))
        self.run=self.enterContext(patch.object(sr.subprocess,'run',side_effect=self.completed))
    def completed(self,command,**kwargs):
        Path(command[command.index('--output-last-message')+1]).write_text(REPORT,encoding='utf-8')
        return subprocess.CompletedProcess(command,0,stdout='Intermediate tool logs.',stderr='')
    def test_reference_cli_flags_stdin_utf8_model_and_persisted_final_file(self):
        result=sr._execute_codex('Complete reference prompt.','gpt-6-sol',600)
        command=self.run.call_args.args[0];kwargs=self.run.call_args.kwargs
        self.assertEqual(command[command.index('--model')+1],'gpt-6-sol')
        self.assertEqual(command[-1],'-');self.assertEqual(kwargs['input'],'Complete reference prompt.')
        self.assertEqual(kwargs['encoding'],'utf-8');self.assertFalse(kwargs['shell'])
        self.assertIn('--sandbox',command);self.assertIn('read-only',command)
        for forbidden in ('--output-schema','--json','--dangerously-bypass-approvals-and-sandbox','-c','--approve-for-me'):
            self.assertNotIn(forbidden,command)
        self.assertEqual(result.final_analysis,REPORT);self.assertTrue(result.analysis_completed)
        self.assertEqual(Path(result.response_file).read_text(),REPORT)
        self.assertNotIn('Intermediate',result.final_analysis)
        self.run.assert_called_once()
    def test_unique_response_paths_do_not_overwrite_previous_results(self):
        one=sr._execute_codex('one','gpt-6-astra',600);two=sr._execute_codex('two','gpt-6-astra',600)
        self.assertNotEqual(one.response_file,two.response_file)
        self.assertEqual(Path(one.response_file).read_text(),REPORT)
    def test_exit_zero_with_only_stdout_is_not_completion(self):
        self.run.side_effect=lambda command,**kwargs:subprocess.CompletedProcess(command,0,stdout=REPORT,stderr='')
        result=sr._execute_codex('prompt','gpt-6-astra',600)
        self.assertFalse(result.analysis_completed);self.assertEqual(result.final_analysis,'')
    def test_failed_cli_preserves_actual_response_without_marking_success(self):
        def fail(command,**kwargs):
            self.completed(command,**kwargs)
            return subprocess.CompletedProcess(command,1,stdout='',stderr='Model access denied.')
        self.run.side_effect=fail
        result=sr._execute_codex('prompt','gpt-6-astra',600)
        self.assertFalse(result.analysis_completed);self.assertEqual(result.final_analysis,REPORT)
    def test_timeout_preserves_partial_file_and_never_retries(self):
        def timeout(command,**kwargs):
            self.completed(command,**kwargs)
            raise subprocess.TimeoutExpired(command,1,output=b'partial log')
        self.run.side_effect=timeout
        result=sr._execute_codex('prompt','gpt-6-astra',1)
        self.assertEqual(result.status,'timed_out');self.assertFalse(result.analysis_completed)
        self.assertEqual(result.final_analysis,REPORT);self.run.assert_called_once()
    def test_missing_cli_and_approval_denial_are_safe(self):
        with patch.object(sr,'codex_command',side_effect=FileNotFoundError('Missing Codex CLI')):
            self.assertEqual(sr._execute_codex('prompt','gpt-6-astra',600).status,'launch_error')
        self.run.assert_not_called()
        self.run.side_effect=lambda command,**kwargs:subprocess.CompletedProcess(command,0,stdout='',stderr='MCP tool call requires approval, but approval policy is never')
        result=sr._execute_codex('prompt','gpt-6-astra',600)
        self.assertEqual(result.status,'approval_blocked');self.assertFalse(result.analysis_completed)
    def test_tool_access_failure_cannot_be_a_successful_wait_with_exit_zero(self):
        def unavailable(command,**kwargs):
            Path(command[command.index('--output-last-message')+1]).write_text('NO VALID SETUP — TradingView connection failed.',encoding='utf-8')
            return subprocess.CompletedProcess(command,0,stdout='',stderr='')
        self.run.side_effect=unavailable
        result=sr._execute_codex('prompt','gpt-6-astra',600)
        self.assertFalse(result.analysis_completed)
        self.assertEqual(result.status,'failed')

class AnalysisFlowTests(unittest.TestCase):
    def setUp(self):
        self.verify=self.enterContext(patch.object(sr,'verify_tradingview_chart',return_value=json.dumps(TARGET)))
        self.session=self.enterContext(patch.object(sr,'ChartSession')).return_value
        self.session.exclusive.return_value=nullcontext()
        self.session.snapshot.side_effect=[snapshot(),finished()]
        self.execute=self.enterContext(patch.object(sr,'_execute_codex',return_value=sr.AnalysisOutcome(
            'completed_response',response=REPORT,final_analysis=REPORT,analysis_completed=True,run_id='offline-run',return_code=0)))
    def test_sr_and_setup_buttons_use_the_correct_complete_file_without_schema(self):
        result=sr.run_support_resistance_analysis(TARGET['symbol'],FRAMES,confirmed_chart=TARGET,live_confirmed=True)
        self.assertTrue(result.drawings_verified)
        self.assertTrue(self.execute.call_args.args[0].startswith(sr._load_prompt('support_resistance.txt')))
        self.session.exclusive.return_value=nullcontext();self.session.snapshot.side_effect=[snapshot(),finished(True)]
        result=sr.run_trade_setup_analysis(TARGET['symbol'],FRAMES,confirmed_chart=TARGET,live_confirmed=True)
        self.assertTrue(self.execute.call_args.args[0].startswith(sr._load_prompt('price_action.txt')))
        self.assertEqual(result.trade_report['format'],'plain_text')
        self.assertEqual(result.trade_report['final_analysis'],REPORT)
    def test_unavailable_readback_does_not_block_plain_analysis_or_fake_drawing_success(self):
        self.session.snapshot.side_effect=ValueError('Readback API unavailable')
        result=sr.run_trade_setup_analysis(TARGET['symbol'],FRAMES,confirmed_chart=TARGET,live_confirmed=True)
        self.assertTrue(result.analysis_completed);self.assertFalse(result.drawings_verified)
        self.assertIn('unavailable',result.verification_details)
    def test_no_approval_or_prelaunch_target_change_never_runs_codex(self):
        result=sr.run_support_resistance_analysis(TARGET['symbol'],FRAMES)
        self.assertEqual(result.status,'confirmation_required');self.execute.assert_not_called()
        self.verify.return_value=json.dumps(dict(TARGET,tab_id='other'))
        result=sr.run_trade_setup_analysis(TARGET['symbol'],FRAMES,confirmed_chart=TARGET,live_confirmed=True)
        self.assertEqual(result.status,'target_mismatch');self.execute.assert_not_called()
    def test_postlaunch_target_change_prevents_telegram_eligibility(self):
        self.verify.side_effect=[json.dumps(TARGET),json.dumps(dict(TARGET,tab_id='other'))]
        result=sr.run_trade_setup_analysis(TARGET['symbol'],FRAMES,confirmed_chart=TARGET,live_confirmed=True)
        self.assertEqual(result.status,'target_mismatch');self.assertFalse(result.analysis_completed)
        self.assertIsNone(result.trade_report)
    def test_existing_drawing_change_is_reported_without_any_application_mutation(self):
        data=finished();data['drawings'][0]['properties']['text']='Changed'
        self.session.snapshot.side_effect=[snapshot(),data]
        result=sr.run_support_resistance_analysis(TARGET['symbol'],FRAMES,confirmed_chart=TARGET,live_confirmed=True)
        self.assertTrue(result.analysis_completed);self.assertFalse(result.drawings_verified)
        self.assertIn('old',result.verification_details)
        self.session.assert_not_called()

if __name__=='__main__':unittest.main()
