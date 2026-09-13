import asyncio
import unittest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace as NS
from core.missions import MissionOrchestrator, Mission, MissionStep
from core.execution import Exhausted, VerificationError, ApprovalDenied, ExecutionError, ExecutionTimedOut, bounded
from core.agents import _declarations, react_loop
from core.registry import ToolContext
from core.approvals import ApprovalManager


class MissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_verifier_error_fails_closed(self):
        with patch('core.missions.genai.Client',side_effect=RuntimeError('offline')):
            with self.assertRaises(VerificationError):
                await MissionOrchestrator()._verify_step(Mission('m','test'),MissionStep(1,'test','test'),[],{})
    async def test_no_retry_after_effect_or_denial(self):
        for failure in [False,True]:
            step=MissionStep(1,'test','test');m=Mission('m','test',steps=[step]);o=MissionOrchestrator()
            execute=AsyncMock(side_effect=ApprovalDenied('denied')) if failure else AsyncMock(return_value='wrote file')
            with patch('core.missions.react_loop',execute),patch.object(o,'_verify_step',AsyncMock(return_value=(False,'missing proof'))):
                self.assertFalse(await o._execute_step(m,step,{}))
            self.assertEqual(execute.await_count,1);self.assertEqual(step.status,'failed')
    async def test_cancel_before_start(self):
        o=MissionOrchestrator()
        with patch.object(o,'_plan',AsyncMock()):
            m=await o.start('test',{});o.cancel(m.id)
            await asyncio.gather(m.task,return_exceptions=True)
            self.assertEqual(m.status,'cancelled')
    async def test_approval_cancel_cleanup_no_speech_wait(self):
        manager=ApprovalManager()
        with patch('core.runtime.announce'):
            task=asyncio.create_task(manager.wait('test','tool',{},'mission:m'))
            await asyncio.sleep(0);self.assertEqual(len(manager.pending()),1)
            action=manager.pending()[0];task.cancel()
            await asyncio.gather(task,return_exceptions=True);await asyncio.sleep(0)
            self.assertFalse(manager.pending());self.assertTrue(action.timeout_task.done())
    async def test_menu_uses_filtered_declarations(self):
        with patch('core.registry.build_declarations',return_value=[NS(name='enabled')]):
            result=_declarations({'tools':['enabled','disabled']},{})
            self.assertEqual([r.name for r in result],['enabled'])
    async def test_exhaustion_and_allowlist(self):
        client=NS(aio=NS(models=NS(generate_content=AsyncMock())))
        with patch('core.agents.genai.Client',return_value=client),patch('core.agents._declarations',return_value=[]):
            with self.assertRaises(Exhausted):await react_loop('test','test',[],'test',{},ToolContext({}),max_steps=0)

    async def test_model_cannot_call_unadvertised_tool(self):
        call=NS(name='write_file',args={'path':'not-used'})
        response=NS(candidates=[NS(content=NS(parts=[NS(function_call=call)]))])
        client=NS(aio=NS(models=NS(generate_content=AsyncMock(return_value=response))))
        with patch('core.agents.genai.Client',return_value=client),patch('core.agents._declarations',return_value=[]),patch('core.agents.registry_dispatch',AsyncMock()) as dispatch:
            with self.assertRaises(ExecutionError):await react_loop('test','test',[],'test',{},ToolContext({}))
            dispatch.assert_not_awaited()

    async def test_timeout_cancels_wait(self):
        cleaned=asyncio.Event()
        async def slow():
            try:await asyncio.sleep(60)
            finally:cleaned.set()
        with self.assertRaises(ExecutionTimedOut):await bounded(slow(),.01)
        self.assertTrue(cleaned.is_set())

    async def test_verification_exception_cannot_finish_step(self):
        o=MissionOrchestrator();s=MissionStep(1,'test','test');m=Mission('m','test',steps=[s])
        with patch('core.missions.react_loop',AsyncMock(return_value='work completed')),patch.object(o,'_verify_step',AsyncMock(side_effect=VerificationError('bad schema'))):
            self.assertFalse(await o._execute_step(m,s,{}))
        self.assertEqual(s.outcome,'verification_error')
    async def test_browser_completion_awaited(self):
        import concurrent.futures
        from core.browser_agent import browser_task
        future=concurrent.futures.Future()
        class Loop:
            def submit(self,coro): coro.close();return future
        with patch('core.browser.driver.BrowserLoop.get',return_value=Loop()):
            task=asyncio.create_task(browser_task({'task':'test'},ToolContext({},source='mission:m')))
            await asyncio.sleep(0);self.assertFalse(task.done())
            future.set_result('actual findings');self.assertEqual(await task,'actual findings')


if __name__=='__main__':unittest.main()
