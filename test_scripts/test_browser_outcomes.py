import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from google.genai import types
from core.browser.agent import BrowserAgent
from core.execution import ExecutionError


def response(name=None, args=None, text=None):
    part = types.Part(function_call=types.FunctionCall(name=name, args=args, id='test-call')) if name else types.Part(text=text)
    return SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(role='model',parts=[part]))])


class BrowserOutcomeTests(unittest.IsolatedAsyncioTestCase):
    def agent(self, replies):
        agent = BrowserAgent.__new__(BrowserAgent)
        agent.config = {}; agent.bcfg = {}; agent.task = 'Compare laptops with prices'
        agent.use_vision = True; agent.max_visual_requests = 2; agent.visual_requests = 0
        agent.history = []; agent.visited = []; agent.max_steps = 4; agent.on_step = None
        agent._generate = AsyncMock(side_effect=replies)
        agent._act = AsyncMock(return_value='Source price: LKR 250000')
        agent._observe = AsyncMock(return_value=[types.Part(text='Visible page')])
        return agent

    async def test_unsuccessful_finish_is_failure(self):
        agent = self.agent([response('finish',{'answer':'Browser unavailable','success':False})])
        with patch('core.browser.agent.get_browser',AsyncMock()):
            with self.assertRaises(ExecutionError): await agent.run()

    async def test_prose_does_not_report_success(self):
        agent = self.agent([response(text='I cannot browse'),response('finish',{'answer':'Blocked','success':False})])
        with patch('core.browser.agent.get_browser',AsyncMock()):
            with self.assertRaises(ExecutionError): await agent.run()
        self.assertEqual(agent._generate.await_count,2)

    async def test_browser_returns_structured_function_response(self):
        agent = self.agent([response('read_page',{}),response('finish',{'answer':'Verified prices','success':True})])
        with patch('core.browser.agent.get_browser',AsyncMock()):
            self.assertEqual(await agent.run(),'Verified prices')
        reply = agent.history[2].parts[0].function_response
        self.assertEqual(reply.name,'read_page')
        self.assertEqual(reply.id,'test-call')
        self.assertIn('250000',reply.response['result'])
