import asyncio
import time
import unittest
from unittest.mock import patch,AsyncMock
from test_scripts import test_trading
from core.trading.data import sample,quality,coinbase
from core.trading.indicators import calculate
from core.trading.orchestration import AnalystDesk
from core.trading.providers import image_data


class ExtendedTradingTests(test_trading.TradingTests):
    def test_budget_and_append_only_audit(self):
        self.thesis();desk=AnalystDesk(self.svc,{'max_analyses_per_session':1})
        asyncio.run(desk.analyze(self.s['id'],{'provider':'offline'}))
        self.command('advance')
        with self.assertRaises(ValueError):asyncio.run(desk.analyze(self.s['id'],{'provider':'offline'}))
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            with self.svc.store.transaction() as db:db.execute('DELETE FROM analyses')
        self.svc.review(self.s['id'],{'key':'review','note':'I followed the invalidation','followed_plan':True})
        self.assertEqual(self.svc.progress(self.s['id'])['followed_plan_count'],1)

    def test_gemini_sdk_schema_and_valid_image(self):
        from core.trading.providers import gemini_schema
        from google.genai import types
        types.GenerateContentConfig(response_json_schema=gemini_schema())
        import base64,io
        from PIL import Image
        out=io.BytesIO();Image.new('RGB',(10,10)).save(out,format='PNG')
        self.assertEqual(image_data(base64.b64encode(out.getvalue()).decode())[1],'image/png')

    def test_openai_adapter_uses_available_model_and_no_tools(self):
        import json,os
        from core.trading.providers import explain
        self.thesis();snapshot=self.svc.snapshot(self.s['id'])
        raw,_=asyncio.run(explain(snapshot,'offline',{}));sent=[]
        class Response:
            def __init__(self,data):self.data=data
            def raise_for_status(self):pass
            def json(self):return self.data
        class Client:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def get(self,url):return Response({'data':[{'id':'test-model'}]})
            async def post(self,url,json):
                sent.append(json)
                return Response({'status':'completed','output':[{'content':[{'type':'output_text','text':__import__('json').dumps(raw)}]}],'usage':{'total_tokens':123}})
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-placeholder'}),patch('core.trading.providers.httpx.AsyncClient',return_value=Client()):
            result,usage=asyncio.run(explain(snapshot,'openai',{'openai_model':'test-model'}))
        self.assertEqual(result,raw);self.assertEqual(usage['tokens'],123)
        self.assertNotIn('tools',sent[0]);self.assertFalse(sent[0]['store'])
    def test_limit_activates_next_bar(self):
        self.thesis();self.command('order',side='buy',kind='limit',quantity='.01',price='99999')
        self.assertFalse(self.s['fills']);self.command('advance')
        self.assertLessEqual(float(self.s['fills'][0]['price']),99999)
    def test_gap_buy_reject_preserves_cash(self):
        self.thesis();self.command('order',side='buy',quantity='.1')
        with self.svc.store.transaction() as db:
            s=self.svc._load(db,self.s['id']);s['candles'][30].update(open='200000',high='210000',low='190000',close='200000')
            from core.trading.persistence import encode
            db.execute('UPDATE sessions SET state=? WHERE id=?',(encode(s),s['id']))
        self.command('advance');self.assertEqual(self.s['orders'][0]['status'],'rejected');self.assertEqual(self.s['cash'],'10000')
    def test_indicator_warmup(self):
        rows=calculate(sample());self.assertIsNone(rows[18]['ema']);self.assertIsNotNone(rows[19]['ema'])
        self.assertIsNone(rows[13]['rsi']);self.assertIsNotNone(rows[14]['rsi'])
        self.assertIsNone(rows[12]['atr']);self.assertIsNotNone(rows[13]['atr'])
    def test_images_and_analysis_cancellation(self):
        with self.assertRaises(ValueError):image_data('not base64')
        self.thesis();desk=AnalystDesk(self.svc)
        async def check():
            async def slow(*args):await asyncio.sleep(60)
            with patch('core.trading.orchestration.explain',slow):
                task=asyncio.create_task(desk.analyze(self.s['id'],{'provider':'gemini'}))
                await asyncio.sleep(.02);task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
        asyncio.run(check())
        with self.svc.store.transaction() as db:
            import json
            self.assertEqual(json.loads(db.execute('SELECT data FROM analyses').fetchone()[0])['status'],'cancelled')
    def test_future_evidence_rejected(self):
        self.thesis();desk=AnalystDesk(self.svc)
        from core.trading.providers import explain
        raw,usage=asyncio.run(explain(self.svc.snapshot(self.s['id']),'offline',{}))
        raw['observations'][0]['evidence']=[sample()[40]['id']]
        with patch('core.trading.orchestration.explain',AsyncMock(return_value=(raw,usage))):
            result=asyncio.run(desk.analyze(self.s['id'],{'provider':'gemini'}))
        self.assertTrue(result['veto']);self.assertIsNone(result['analysis'])
    def test_observation_backfill_dedupe_gaps_stale(self):
        rows=sample(count=35)
        state=self.svc.create({'key':'observe','environment':'observation'},rows[:30])
        self.assertTrue(state['feed_stale'])
        updated=self.svc.ingest(state['id'],rows[29:33],0)
        self.assertEqual(len(updated['candles']),33)
        again=self.svc.ingest(state['id'],rows[29:33],1);self.assertEqual(again['revision'],1)
        with self.assertRaises(ValueError):self.svc.ingest(state['id'],[rows[34]],1)
        with self.assertRaises(ValueError):self.svc.ingest(self.s['id'],rows,0)
    def test_coinbase_paginates_sorts_deduplicates(self):
        rows=sample(count=620);calls=[]
        class Client:
            async def __aenter__(self):return self
            async def __aexit__(self,*a):pass
            async def get(self,url,params):
                calls.append(params)
                from datetime import datetime
                start=int(datetime.fromisoformat(params['start']).timestamp());end=int(datetime.fromisoformat(params['end']).timestamp())
                selected=[r for r in reversed(rows) if start<=r['time']<=end]
                return type('Response',(),{'raise_for_status':lambda self:None,'json':lambda self:[[r['time'],r['low'],r['high'],r['open'],r['close'],r['volume']] for r in selected]})()
        with patch('core.trading.data.httpx.AsyncClient',return_value=Client()):
            data=asyncio.run(coinbase('BTC-USD',900,rows[0]['time'],rows[-1]['time']+900))
        self.assertEqual(len(calls),3);self.assertEqual(len(data['candles']),620);self.assertFalse(data['flags'])


if __name__=='__main__':unittest.main()
