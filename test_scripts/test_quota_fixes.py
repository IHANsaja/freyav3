import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from core import quota
from core.missions import MissionOrchestrator, Mission, MissionStep
from core.trading.simulator import TradingService
from core.trading.data import sample
from core.trading.orchestration import AnalystDesk
from core.trading.providers import explain


class QuotaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        quota._next.clear(); quota._usage.clear()
        self.cfg={'_quota_mission':'test','quota':{'default_rpm':1e9,'max_requests_per_mission':2}}
    def client(self, **kwargs):
        return NS(aio=NS(models=NS(generate_content=AsyncMock(**kwargs))))
    async def test_budget_counts_nested_calls_before_dispatch(self):
        client=self.client(return_value=NS(usage_metadata=NS(total_token_count=7)))
        await quota.generate(client,quota_config=self.cfg,model='test')
        await quota.generate(client,quota_config=self.cfg,model='other')
        with self.assertRaises(quota.QuotaError):
            await quota.generate(client,quota_config=self.cfg,model='test')
        self.assertEqual(client.aio.models.generate_content.await_count,2)
        self.assertEqual(quota.usage('test')['tokens'],14)
    async def test_daily_quota_does_not_retry(self):
        exc=RuntimeError('429'); exc.response_json={'error':{'code':429,'details':[{'violations':[{'quotaId':'GenerateRequestsPerDayPerProjectPerModel'}]}]}}
        client=self.client(side_effect=exc)
        with self.assertRaisesRegex(quota.QuotaError,'daily'):
            await quota.generate(client,quota_config=self.cfg,model='test')
        self.assertEqual(client.aio.models.generate_content.await_count,1)
    async def test_unknown_429_is_not_daily(self):
        self.assertEqual(quota.classify(RuntimeError('429'))[0],'unknown quota')
    async def test_structured_token_limit_and_retry_delay(self):
        exc=RuntimeError('429');exc.response_json={'error':{'details':[{'violations':[{'quotaId':'TokensPerMinute'}]},{'retryDelay':'15s'}]}}
        self.assertEqual(quota.classify(exc),('tokens/minute',15))
    async def test_shared_pacing_and_cancelled_wait_does_not_count(self):
        self.cfg['quota']['default_rpm']=600
        client=self.client(return_value=NS())
        await quota.generate(client,quota_config=self.cfg,model='test')
        task=asyncio.create_task(quota.generate(client,quota_config=self.cfg,model='test'))
        await asyncio.sleep(.01);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(quota.usage('test')['requests'],1)
        start=time.monotonic()
        await quota.generate(client,quota_config=self.cfg,model='test')
        self.assertGreater(time.monotonic()-start,.05)
    async def test_retry_only_generation_not_tools(self):
        exc=RuntimeError('429');exc.code=429
        client=self.client(side_effect=[exc,NS()])
        with patch('core.quota.random.random',return_value=0),patch('core.quota.time.monotonic',side_effect=[0,0,10]):
            await quota.generate(client,quota_config=self.cfg,model='test')
        self.assertEqual(client.aio.models.generate_content.await_count,2)
    async def test_report_no_api_and_quota_terminal_steps(self):
        orchestrator=MissionOrchestrator();step=MissionStep(1,'Work','Work',status='done');mission=Mission('test','Work',status='done',steps=[step])
        with patch.object(orchestrator,'_publish',AsyncMock()),patch('core.missions.genai.Client') as client:
            await orchestrator._report(mission,{})
            client.assert_not_called();self.assertEqual(mission.status,'done')
        step.status='pending';pending=MissionStep(2,'Next','Next');mission.steps.append(pending)
        with patch.object(orchestrator,'_publish',AsyncMock()),patch.object(orchestrator,'_plan',AsyncMock()),patch('core.missions.react_loop',AsyncMock(side_effect=quota.QuotaError('Daily quota reached'))):
            await orchestrator._run(mission,{})
        self.assertEqual((mission.status,step.status,step.outcome,pending.status),('failed','failed','quota','skipped'))
        self.assertIn('Daily quota',mission.report)


class TradingFixTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.svc=TradingService(Path(self.tmp.name)/'test.db')
    def tearDown(self):self.tmp.cleanup()
    async def test_transient_analysis_retry_and_success_cache(self):
        s=self.svc.create({'key':'s','mode':'coached'});desk=AnalystDesk(self.svc)
        with patch('core.trading.orchestration.explain',AsyncMock(side_effect=TimeoutError())):
            first=await desk.analyze(s['id'],{'provider':'gemini'})
        raw,usage=await explain(self.svc.snapshot(s['id']),'offline',{})
        with patch('core.trading.orchestration.explain',AsyncMock(return_value=(raw,usage))) as provider:
            second=await desk.analyze(s['id'],{'provider':'gemini'})
            third=await desk.analyze(s['id'],{'provider':'gemini'})
        self.assertEqual((first['status'],second['status'],third['id']),('error','done',second['id']))
        self.assertEqual(provider.await_count,1)
        with self.svc.store.transaction() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM analyses').fetchone()[0],2)
    async def test_observation_ignores_bar_opened_before_submission(self):
        rows=sample(count=32);submitted=rows[30]['time']+600
        with patch('core.trading.simulator.time.time',return_value=submitted):
            s=self.svc.create({'key':'s','environment':'observation'},rows[:30])
            s=self.svc.mutate(s['id'],'thesis',{'key':'t','revision':0,'thesis':'Test hypothesis','invalidation':'Below support'})
            s=self.svc.mutate(s['id'],'order',{'key':'o','revision':1,'side':'buy','quantity':'.01'})
        with patch('core.trading.simulator.time.time',return_value=rows[31]['time']+901):
            s=self.svc.ingest(s['id'],rows[30:31],2)
            self.assertFalse(s['fills'])
            s=self.svc.ingest(s['id'],rows[31:32],3)
        self.assertEqual(s['fills'][0]['time'],rows[31]['time'])
        self.assertGreater(s['fills'][0]['time'],submitted)
