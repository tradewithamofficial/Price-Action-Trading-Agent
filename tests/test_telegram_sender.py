"""Offline only: synthetic analysis/config and mocked HTTPS; sockets forbidden."""
from copy import deepcopy
from datetime import datetime, timezone
import html
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import main
import sr_agent as sr
import telegram_sender as tg
from tests import test_trade_setups as trade_tests
from tests.test_grouping import TARGET

TOKEN = "123456:" + "FAKE_OFFLINE_TOKEN_" * 2
CHAT = "-1001234567890"
STAMP = datetime(2026,10,19,9,30,tzinfo=timezone.utc)


def report(count=1):
    session=Mock(run_id="offline-report",target=TARGET)
    return trade_tests.result_record(session,count)


class FakeHTTPS:
    def __init__(self, responses=None):
        self.responses=responses or []
        self.connections=[]
        self.payloads=[]

    def __call__(self, host, **kwargs):
        assert host == "api.telegram.org"
        assert kwargs["context"].check_hostname
        assert 0 < kwargs["timeout"] <= 10
        connection=Mock()
        connection.sock=None
        self.connections.append(connection)
        index=len(self.connections)-1
        def request(method,path,*,body,headers):
            assert method=="POST" and path=="/bot"+TOKEN+"/sendMessage"
            self.payloads.append(json.loads(body))
        connection.request.side_effect=request
        def response():
            override=self.responses[index] if index<len(self.responses) else None
            if isinstance(override,Exception):raise override
            payload=self.payloads[-1]
            data={"ok":True,"result":{"message_id":index+1,"chat":{"id":int(CHAT)},
                  "text":html.unescape(re.sub(r"</?(?:b|i)>","",payload["text"]))}}
            status=200
            if override is not None:
                status,data=override
            result=Mock(status=status)
            raw=data if isinstance(data,bytes) else json.dumps(data).encode()
            result.read1.side_effect=io.BytesIO(raw).read
            return result
        connection.getresponse.side_effect=response
        return connection


class HtmlCheck(HTMLParser):
    def __init__(self):
        super().__init__();self.stack=[];self.text=[]
    def handle_starttag(self, tag, attrs):
        assert tag in ("b","i") and not attrs
        self.stack.append(tag)
    def handle_endtag(self,tag):assert self.stack.pop()==tag
    def handle_data(self,data):self.text.append(data)


class TelegramTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket,"socket",side_effect=AssertionError("Real network forbidden")))
        self.directory=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.config=self.directory/'telegram_config.local.json'
        self.config.write_text(json.dumps({"bot_token":TOKEN,"chat_id":CHAT}),encoding='utf-8')
        self.http=FakeHTTPS()

    def send(self,data=None,**kwargs):
        return tg.send_trade_analysis(report() if data is None else data,TARGET['symbol'],['1H','4H','1D'],
                                     chart_verified=True,live_send_enabled=True,config_path=self.config,
                                     timestamp=STAMP,connection_factory=self.http,**kwargs)

    def test_success_requires_every_exact_destination_message_ack(self):
        result=self.send()
        self.assertTrue(result.accepted)
        self.assertEqual(result.accepted_parts,result.required_parts)
        self.assertEqual(len(self.http.connections),result.required_parts)
        for connection in self.http.connections:
            connection.request.assert_called_once()
            connection.close.assert_called_once()
            connection.set_debuglevel.assert_called_once_with(0)
        for payload in self.http.payloads:
            self.assertEqual(payload['chat_id'],CHAT)
            self.assertEqual(payload['parse_mode'],'HTML')
            self.assertEqual(set(payload),{'chat_id','text','parse_mode','link_preview_options'})
            self.assertNotIn('reply_markup',payload)

    def test_config_missing_empty_invalid_or_wrong_destination_is_not_sent(self):
        bad=[None,{}, {'bot_token':'','chat_id':''}, {'bot_token':TOKEN,'chat_id':True},
             {'bot_token':TOKEN,'chat_id':'@not-a-numeric-destination'},
             {'bot_token':TOKEN,'chat_id':CHAT,'extra':'unsupported'}, {'bot_token':TOKEN,'chat_id':'0'}]
        for config in bad:
            with self.subTest(config_keys=list(config) if isinstance(config,dict) else 'missing'):
                if config is None:self.config.unlink(missing_ok=True)
                else:self.config.write_text(json.dumps(config),encoding='utf-8')
                result=self.send()
                self.assertFalse(result.accepted)
                self.assertNotIn(TOKEN,result.error)
        self.assertEqual(self.http.connections,[])
        self.config.write_text('{"bot_token": "'+TOKEN+'", malformed',encoding='utf-8')
        self.assertNotIn(TOKEN,self.send().error)

    def test_default_gate_disabled_before_config_or_network(self):
        with patch.object(tg,'load_config') as config:
            result=tg.send_trade_analysis(report(),TARGET['symbol'],['1H'],chart_verified=True)
        config.assert_not_called()
        self.assertFalse(result.accepted)

    def test_api_rejection_redirect_and_rate_limit_never_retry_or_leak_description(self):
        for code in (400,401,403,429,500,302):
            with self.subTest(code=code):
                self.http=FakeHTTPS([(code,{'ok':False,'description':TOKEN,'error_code':code})])
                result=self.send()
                self.assertFalse(result.accepted)
                self.assertNotIn(TOKEN,result.error)
                self.assertEqual(len(self.http.connections),1)

    def test_timeout_and_raw_transport_exception_are_sanitized(self):
        for error in (TimeoutError(TOKEN),OSError('https://api.telegram.org/bot'+TOKEN)):
            self.http=FakeHTTPS([error])
            result=self.send()
            self.assertFalse(result.accepted)
            self.assertNotIn(TOKEN,result.error)
            self.assertEqual(len(self.http.connections),1)
            self.http.connections[0].close.assert_called_once()

    def test_invalid_json_oversized_response_and_incomplete_ack_are_not_success(self):
        data=[b'not json',b'x'*(tg.MAX_RESPONSE_BYTES+1),{'ok':True},
              {'ok':True,'result':{'message_id':True,'chat':{'id':int(CHAT)}}},
              {'ok':True,'result':{'message_id':1,'chat':{'id':123},'text':'wrong'}}]
        for value in data:
            self.http=FakeHTTPS([(200,value)])
            self.assertFalse(self.send().accepted)

    def test_correct_text_with_wrong_destination_is_not_an_accepted_delivery(self):
        message=tg.format_trade_messages(report(),TARGET['symbol'],['1H','4H','1D'],chart_verified=True,timestamp=STAMP)[0]
        plain=html.unescape(re.sub(r'</?(?:b|i)>','',message))
        self.http=FakeHTTPS([(200,{'ok':True,'result':{'message_id':1,'chat':{'id':123},'text':plain}})])
        self.assertFalse(self.send().accepted)
        self.assertEqual(self.http.payloads[0]['chat_id'],CHAT)

    def test_long_report_splits_balanced_html_unicode_entities_and_numbering(self):
        data=report(3)
        data['setups'][0]['confirmation']=('MOCK only: 🟢 <price> & "confirmation" / conditional.\n'*180)
        messages=tg.format_trade_messages(data,TARGET['symbol'],['1H','4H','1D'],chart_verified=True,timestamp=STAMP)
        self.assertGreater(len(messages),1)
        self.assertLessEqual(len(messages),20)
        for number,message in enumerate(messages,1):
            parser=HtmlCheck();parser.feed(message);parser.close()
            self.assertEqual(parser.stack,[])
            self.assertLessEqual(len(message.encode('utf-16-le'))//2,4096)
            self.assertIn(f'Message {number}/{len(messages)}',message)
            self.assertIn(tg.DISCLAIMER,message)
        rendered='\n'.join(html.unescape(re.sub(r'</?(?:b|i)>','',m)) for m in messages)
        self.assertEqual(rendered.count('MOCK only:'),180)

    def test_one_two_three_and_wait_use_human_fields_without_duplicate_assessment(self):
        for count in range(4):
            data=report(count)
            data.update(prompt='PRIVATE PROMPT',output='PRIVATE TOOL LOGS',errors=['PRIVATE STDERR'])
            messages=tg.format_trade_messages(data,TARGET['symbol'],['1H'],chart_verified=True,timestamp=STAMP)
            text='\n'.join(messages)
            self.assertEqual(len(messages),1)
            self.assertTrue(text.startswith('<b>TRADE WITH AM — PRICE ACTION TRADING AGENT</b>'))
            self.assertIn('Symbol: '+TARGET['symbol'],text)
            self.assertIn('Analysis: 2026-10-19T09:30:00+00:00\nTimeframes: 1H',text)
            self.assertNotIn('Message 1/1',text)
            self.assertEqual(text.count('<b>Setup '),count)
            for rank,name in enumerate(('Primary','Secondary','Alternative')[:count],1):
                direction='LONG' if rank%2 else 'SHORT'
                self.assertIn(f'<b>Setup {rank} — {name} | {direction}</b>',text)
            self.assertNotIn('PRIVATE',text)
            self.assertNotIn('setup1_entry',text)
            self.assertNotIn('drawings',text)
            if count==0:
                self.assertIn('NO TRADE / WAIT',text)
                self.assertEqual(text.count(html.escape(data['final_analysis'])),1)
            else:
                self.assertNotIn('Final Astra assessment',text)
                self.assertNotIn(html.escape(data['final_analysis']),text)
                self.assertNotIn('Approx. risk/reward:',text)
                self.assertNotIn('\n\nCancel if:',text)
                self.assertIn('<b>Entry area:',text)
                self.assertIn('<b>Stop / invalidation:',text)
                self.assertIn('<b>Target 1:',text)
            self.assertTrue(text.endswith('<i>Conditional setup — wait for confirmation.</i>'))

    def test_dynamic_html_is_escaped_in_every_human_field(self):
        data=report()
        for field in tg.SETUP_FIELDS[2:]:data['setups'][0][field]='<script>bad</script> & "quoted"'
        data['final_analysis']='This is a MOCK final assessment: <b>not markup</b> & only conditional explanations.'
        text='\n'.join(tg.format_trade_messages(data,TARGET['symbol'],['1H'],chart_verified=True,timestamp=STAMP))
        self.assertNotIn('<script>',text)
        self.assertIn('&lt;script&gt;',text)
        self.assertIn('&quot;quoted&quot;',text)
        self.assertNotIn('final assessment',text)
        parser=HtmlCheck();parser.feed(text);parser.close()
        self.assertEqual(parser.stack,[])

    def test_exact_prices_optional_target_and_all_structured_safety_caveats_survive(self):
        data=report()
        setup=data['setups'][0]
        setup.update(entry_area='4174.50–4174.80 after a closed candle',
                     invalidation='4161.0600; never widen the stop', target1='4189.12345678',
                     target2='4200.00 only after Target 1 confirms',
                     confirmation='1H close above 4174.80 AND retest; no early entry.',
                     risk_reward='Only valid if spread stays below 0.000012340; otherwise WAIT.',
                     cancel_conditions='Cancel if 4H closes below 4161.0600 or the retest fails.')
        text='\n'.join(tg.format_trade_messages(data,TARGET['symbol'],['1H','4H'],chart_verified=True,timestamp=STAMP))
        for label,key in (('Entry area','entry_area'),('Stop / invalidation','invalidation'),
                          ('Target 1','target1'),('Target 2','target2')):
            self.assertIn(f'<b>{label}: {html.escape(setup[key])}</b>',text)
        for key in ('confirmation','risk_reward','cancel_conditions'):
            self.assertEqual(text.count(html.escape(setup[key])),1)
        self.assertIn('Reasoning: '+setup['reasoning']+' '+setup['risk_reward'],text)
        self.assertIn('Confirmation: '+setup['confirmation']+' Cancel / stand aside: '+setup['cancel_conditions'],text)
        self.assertNotIn('Approx. risk/reward:',text)
        self.assertNotIn('\n\nCancel if:',text)
        setup['target2']=None
        self.assertNotIn('Target 2:',tg.format_trade_messages(data,TARGET['symbol'],['1H'],chart_verified=True,timestamp=STAMP)[0])

    def test_repeated_structured_caveats_are_not_duplicated(self):
        data=report();setup=data['setups'][0]
        setup['risk_reward']='Spread must remain below 0.10.'
        setup['reasoning']+=' '+setup['risk_reward']
        setup['confirmation']+=' '+setup['cancel_conditions']
        text=tg.format_trade_messages(data,TARGET['symbol'],['1H'],chart_verified=True,timestamp=STAMP)[0]
        self.assertEqual(text.count(setup['risk_reward']),1)
        self.assertEqual(text.count(setup['cancel_conditions']),1)

    def test_single_message_at_exact_limit_splits_only_when_exceeded(self):
        data=report()
        def format_now():
            return tg.format_trade_messages(data,TARGET['symbol'],['1H'],chart_verified=True,timestamp=STAMP)
        original=format_now()[0]
        data['setups'][0]['confirmation']+='x'*(tg.MAX_HTML_UNITS-tg._units(original))
        messages=format_now()
        self.assertEqual(len(messages),1)
        self.assertEqual(tg._units(messages[0]),4096)
        data['setups'][0]['confirmation']+='x'
        messages=format_now()
        self.assertGreater(len(messages),1)
        self.assertTrue(all(tg._units(message)<=4096 for message in messages))

    def test_large_duplicate_assessment_is_not_sent_for_valid_setups(self):
        data=report();data['final_analysis']='Repeated Astra assessment: market structure summary. '*10000
        messages=tg.format_trade_messages(data,TARGET['symbol'],['1H'],chart_verified=True,timestamp=STAMP)
        self.assertEqual(len(messages),1)
        self.assertNotIn('Repeated Astra assessment',messages[0])

    def test_wait_explanation_is_escaped_and_preserves_reason_without_inventing_setup(self):
        data=report(0)
        data['final_analysis']='NO TRADE / WAIT — Structure is unclear & confirmation < required; wait for a closed candle.'
        messages=tg.format_trade_messages(data,TARGET['symbol'],['1H'],chart_verified=True,timestamp=STAMP)
        self.assertEqual(len(messages),1)
        self.assertIn(html.escape(data['final_analysis']),messages[0])
        self.assertNotIn('Entry area:',messages[0])
        self.assertNotIn('<b>Setup ',messages[0])

    def test_partial_delivery_stops_at_first_failure_without_resend(self):
        data=report();data['setups'][0]['confirmation']='MOCK conditional analysis without live prices. '*260
        self.http=FakeHTTPS([None,TimeoutError(TOKEN)])
        result=self.send(data)
        self.assertFalse(result.accepted)
        self.assertEqual(result.accepted_parts,1)
        self.assertGreater(result.required_parts,1)
        self.assertEqual(len(self.http.connections),2)

    def test_excessive_report_and_embedded_configured_token_are_blocked_before_http(self):
        data=report();data['setups'][0]['confirmation']='Mock conditional analysis. '*10000
        self.assertFalse(self.send(data).accepted)
        self.assertEqual(self.http.connections,[])
        data=report();data['setups'][0]['confirmation']+=' '+TOKEN
        self.assertFalse(self.send(data).accepted)
        self.assertEqual(self.http.connections,[])

    def test_partial_chart_verification_is_explicit_in_the_message(self):
        messages=tg.format_trade_messages(report(),TARGET['symbol'],['1H'],chart_verified=False,timestamp=STAMP)
        self.assertIn('NOT VERIFIED','\n'.join(messages))

    def test_frozen_config_is_external_next_to_exe_not_working_or_bundle_directory(self):
        exe=self.directory/'course'/'SupportResistanceAgent.exe'
        with patch.object(sys,'frozen',True,create=True),patch.object(sys,'executable',str(exe)), \
                patch.object(sys,'_MEIPASS',str(self.directory/'private-bundle'),create=True):
            self.assertEqual(tg.local_config_path(),exe.parent/'telegram_config.local.json')
        self.assertNotIn(TOKEN,repr(tg.TelegramConfig(TOKEN,CHAT)))


class TelegramGuiTests(unittest.TestCase):
    setUp=trade_tests.SetupGuiTests.setUp
    close=trade_tests.SetupGuiTests.close
    pump=trade_tests.SetupGuiTests.pump

    def outcome(self,count=1,verified=True):
        data=report(count)
        return sr.AnalysisOutcome('completed_verified' if verified else 'partial_success',analysis_completed=True,
                                  final_analysis=data['final_analysis'],drawings_verified=verified,trade_report=data,
                                  telegram_delivery=tg.DeliveryOutcome('accepted',1,1,(123,)))

    def test_success_popup_only_after_every_required_part_accepted_actual_count_or_wait(self):
        for count in range(4):
            self.success.reset_mock()
            value=self.outcome(count)
            self.app.events.put(('trade_result',value));self.app.poll_events()
            self.success.assert_called_once()
            self.assertEqual(self.success.call_args.args[0],'Analysis Completed')
            if count:self.assertIn(f'{count} trade setup',self.success.call_args.args[1])
            else:self.assertIn('NO TRADE / WAIT',self.success.call_args.args[1])
        self.assertIn('accepted all',self.app.status.get())

    def test_incomplete_acceptance_fails_and_preserves_copy_fallback(self):
        for receipt in (None,tg.DeliveryOutcome('failed',1,2,(123,),error='Network timeout; acceptance unknown'),
                        tg.DeliveryOutcome('accepted',1,2,(123,))):
            with self.subTest(receipt=receipt),patch.object(self.app,'show_trade_results') as fallback:
                self.success.reset_mock()
                value=self.outcome();value.telegram_delivery=receipt
                self.app.events.put(('trade_result',value));self.app.poll_events()
                self.success.assert_not_called()
                fallback.assert_called_once_with(value.final_analysis)
                self.assertIn('Analysis completed, but Telegram delivery failed.',self.warning.call_args.args[1])

    def test_telegram_acceptance_never_claims_partial_chart_success(self):
        value=self.outcome(verified=False)
        with patch.object(self.app,'show_trade_results') as fallback:
            self.app.events.put(('trade_result',value));self.app.poll_events()
        self.success.assert_not_called()
        self.assertIn('Chart Verification Incomplete',self.warning.call_args.args[0])
        fallback.assert_called_once_with(value.final_analysis)

    def test_delivery_runs_off_tk_thread_remains_responsive_and_no_ai_retry(self):
        entered,gate=threading.Event(),threading.Event()
        self.addCleanup(gate.set)
        value=self.outcome();value.telegram_delivery=None
        self.run.return_value=value;self.confirm.return_value=True
        threads=[]
        def slow(*args,**kwargs):
            threads.append(threading.get_ident());entered.set();gate.wait(2)
            return tg.DeliveryOutcome('failed',error='Offline simulated timeout')
        with patch.object(main,'send_trade_analysis',side_effect=slow) as send:
            self.app.find_trade_setups();self.pump(entered.is_set)
            ticks=[];self.root.after(1,lambda:ticks.append(True));self.pump(lambda:bool(ticks))
            self.assertTrue(self.app.running)
            self.assertEqual(self.app.find_button.cget('state'), 'disabled')
            self.app.find_trade_setups();self.run.assert_called_once()
            self.assertNotEqual(threads[0],threading.get_ident())
            gate.set();self.pump(lambda:not self.app.running)
            send.assert_called_once()
        self.run.assert_called_once()
        self.verify.assert_called_once()
        self.success.assert_not_called()

    def test_same_analysis_identity_is_not_automatically_sent_twice(self):
        value=self.outcome();self.run.return_value=value
        with patch.object(main,'send_trade_analysis',return_value=tg.DeliveryOutcome('failed',error='Offline timeout')) as send:
            self.app.worker((TARGET['symbol'],['1H'],3,sr.DEFAULT_MODEL),True,json.dumps(TARGET))
            self.app.worker((TARGET['symbol'],['1H'],3,sr.DEFAULT_MODEL),True,json.dumps(TARGET))
        send.assert_called_once()

    def test_sr_button_never_sends_telegram(self):
        self.sr_run.return_value=self.outcome()
        with patch.object(main,'send_trade_analysis') as send:
            self.app.worker((TARGET['symbol'],['1H'],3,sr.DEFAULT_MODEL),False,json.dumps(TARGET))
        send.assert_not_called()


if __name__=='__main__':unittest.main()
