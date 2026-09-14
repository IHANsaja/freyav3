import asyncio
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch, AsyncMock
from core.trading.simulator import TradingService, Conflict
from core.trading.orchestration import AnalystDesk
from core.trading.data import sample


class TradingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.db'
        self.svc=TradingService(self.path);self.s=self.svc.create({'key':'create'})
    def tearDown(self): self.tmp.cleanup()
    def command(self,action,**body):
        self.s=self.svc.mutate(self.s['id'],action,{'key':str(self.s['revision'])+action,'revision':self.s['revision'],**body})
        return self.s
    def thesis(self): self.command('thesis',thesis='Range breakout test',invalidation='Close below range')
    def test_live_account_cannot_fall_back_to_sample(self):
        with self.assertRaisesRegex(ValueError, 'require exchange candles'):
            self.svc.create({'key':'live-missing', 'environment':'observation'})
        state = self.svc.create({'key':'live-import', 'environment':'observation'}, sample(count=40))
        self.assertEqual(len(state['candles']), 40)
        self.assertEqual(state['cash'], '10000')
        self.assertEqual(state['source'], 'Coinbase Exchange · live market')

    def test_no_future_or_early_fill(self):
        self.assertEqual(len(self.s['candles']),30)
        with self.assertRaises(ValueError): self.svc.snapshot(self.s['id'])
        self.thesis();snap=self.svc.snapshot(self.s['id'])
        self.assertEqual(len(snap['candles']),30)
        self.command('order',side='buy',quantity='0.01')
        self.assertFalse(self.s['fills']);self.command('advance')
        f=self.s['fills'][0];expected=D(sample()[30]['open'])*D('1.0005')
        self.assertEqual(D(f['price']),expected)
        self.assertEqual(D(f['fee']),expected*D('.01')*D('.001'))
        self.assertEqual(D(self.s['cash']),D(10000)-expected*D('.01')*D('1.001'))
    def test_invalid_and_reserved(self):
        self.thesis()
        for qty in ['0','-1','NaN','Infinity','1000000']:
            with self.assertRaises(ValueError):self.command('order',side='buy',quantity=qty)
        with self.assertRaises(ValueError):self.command('order',side='sell',quantity='.01')
        self.command('order',side='buy',quantity='.1')
        with self.assertRaises(ValueError):self.command('order',side='buy',quantity='.1')
        self.command('cancel',order_id=self.s['orders'][0]['id'])
        self.assertEqual(self.s['reserved_cash'],'0')
    def test_idempotency_revision_persistence_reset(self):
        self.thesis();body={'key':'order-once','revision':1,'side':'buy','quantity':'.01'}
        first=self.svc.mutate(self.s['id'],'order',body)
        self.assertEqual(first,self.svc.mutate(self.s['id'],'order',body))
        with self.assertRaises(Conflict):self.svc.mutate(self.s['id'],'order',{**body,'quantity':'.02'})
        with self.assertRaises(Conflict):self.svc.mutate(self.s['id'],'advance',{'key':'stale','revision':1})
        restarted=TradingService(self.path);self.assertEqual(restarted.get(self.s['id']),first)
        new=restarted.create({'key':'reset'});self.assertNotEqual(new['id'],self.s['id'])
        self.assertTrue(restarted.journal())
    def test_concurrent_revision(self):
        self.thesis()
        def submit(key):
            try:return self.svc.mutate(self.s['id'],'order',{'key':key,'revision':1,'side':'buy','quantity':'.01'})
            except Conflict:return None
        with ThreadPoolExecutor(2) as pool: results=list(pool.map(submit,['a','b']))
        self.assertEqual(sum(r is not None for r in results),1)
    def test_gap_and_ambiguous_stop(self):
        self.thesis();self.command('order',side='buy',quantity='.01');self.command('advance')
        self.command('order',side='sell',kind='bracket',quantity='.01',price='55000',target='70000')
        with self.svc.store.transaction() as db:
            s=self.svc._load(db,self.s['id']);s['candles'][31].update(open='50000',low='49000',high='71000',close='60000')
            from core.trading.persistence import encode
            db.execute('UPDATE sessions SET state=? WHERE id=?',(encode(s),s['id']))
        self.command('advance');f=self.s['fills'][-1]
        self.assertTrue(f['ambiguous']);self.assertEqual(D(f['price']),D(50000)*D('.9995'))
        self.assertEqual(D(self.s['quantity']),0)
    def test_analysis_offline_invalid_stale_and_veto(self):
        self.thesis();desk=AnalystDesk(self.svc)
        result=asyncio.run(desk.analyze(self.s['id'],{'provider':'offline'}))
        self.assertEqual(result['status'],'done');self.assertEqual(len(result['stages']),6)
        self.assertEqual(result['id'],asyncio.run(desk.analyze(self.s['id'],{'provider':'offline'}))['id'])
        self.command('advance');self.assertNotEqual(result['revision'],self.s['revision'])
        with patch('core.trading.orchestration.explain',new=AsyncMock(return_value=({},{}))):
            result=asyncio.run(desk.analyze(self.s['id'],{'provider':'gemini'}))
        self.assertEqual(result['status'],'error');self.assertTrue(result['veto'])
    def test_api_flow(self):
        from fastapi.testclient import TestClient
        from core.trading.api import app
        with patch('core.trading.api.services',return_value=(self.svc,AnalystDesk(self.svc))):
            client=TestClient(app)
            self.assertEqual(client.get('/trading/sessions/'+self.s['id']).status_code,200)
            self.assertEqual(client.post('/trading/sessions/'+self.s['id']+'/order',json={'key':'bad','revision':0,'side':'buy','quantity':'.01'}).status_code,422)


if __name__=='__main__': unittest.main()
