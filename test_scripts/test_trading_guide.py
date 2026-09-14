"""Guide context must stay read-only, visible-only and quota-bounded."""
import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from core.trading.simulator import TradingService
from core.trading.guide import Workspace, context, set_workspace, answer, _views
from core.trading import api


class TradingGuideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.svc = TradingService(Path(self.tmp.name) / 'guide.db')
        self.s = self.svc.create({'key': 'test'})
        _views.clear()

    def tearDown(self):
        _views.clear()
        self.tmp.cleanup()

    def ask(self, question, **kwargs):
        return asyncio.run(answer(self.svc, kwargs.pop('config', {}), self.s['id'], {'question': question, **kwargs}))

    def test_local_help_is_read_only_and_free(self):
        for question in ['Explain RSI', 'Explain EMA', 'Explain this candle', 'Available cash?', 'Why pending orders?', 'Draw a trendline', 'How to start?']:
            reply = self.ask(question, provider='gemini')
            self.assertEqual(reply['provider'], 'local')
            self.assertEqual(reply['tokens'], 0)
            self.assertTrue(reply['answer'])
        self.assertEqual(self.s, self.svc.get(self.s['id']))
        with self.svc.store.transaction() as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='guide_runs'").fetchone())

    def test_selected_context_and_no_future_access(self):
        candle = self.s['candles'][0]
        set_workspace(self.svc, Workspace(client_id='one', session_id=self.s['id'], candle_id=candle['id'], panel='analysis'))
        facts = context(self.svc)
        self.assertEqual(facts['selected_candle'], candle)
        self.assertTrue(facts['analysis_locked'])
        self.assertEqual(facts['active_panel'], 'analysis')
        self.assertNotIn('candles', facts)
        with self.assertRaises(ValueError): context(self.svc, self.s['id'], 'unrevealed-candle')
        with self.assertRaises(ValueError):
            set_workspace(self.svc, Workspace(client_id='one', session_id=self.s['id'], candle_id='unrevealed-candle'))
        self.assertEqual(self.s, self.svc.get(self.s['id']))

    def test_missing_expired_and_ambiguous_focus(self):
        with self.assertRaisesRegex(ValueError, 'No active'): context(self.svc)
        set_workspace(self.svc, Workspace(client_id='one', session_id=self.s['id']))
        second = self.svc.create({'key': 'second'})
        set_workspace(self.svc, Workspace(client_id='two', session_id=second['id']))
        # Several open tabs never block Freya: the most recently used one wins.
        self.assertEqual(context(self.svc)['id'], second['id'])
        self.assertEqual(context(self.svc, self.s['id'])['id'], self.s['id'])
        set_workspace(self.svc, Workspace(client_id='two', session_id=second['id'], active=False))
        self.assertEqual(context(self.svc)['id'], self.s['id'])
        with patch('core.trading.guide.time.monotonic', return_value=time.monotonic() + 91):
            with self.assertRaisesRegex(ValueError, 'No active'): context(self.svc)

    def test_independent_gate_before_provider_call(self):
        with patch('core.quota.generate', new_callable=AsyncMock) as generate:
            with self.assertRaisesRegex(ValueError, 'thesis'):
                self.ask('Evaluate the current market structure', provider='gemini')
            generate.assert_not_called()

    def test_focused_chart_and_yellow_line_without_thesis(self):
        other = self.svc.create({'key': 'background'})
        set_workspace(self.svc, Workspace(client_id='front', session_id=self.s['id'], focused=True, ema=True))
        set_workspace(self.svc, Workspace(client_id='back', session_id=other['id']))
        facts = context(self.svc)
        self.assertEqual(facts['id'], self.s['id'])
        self.assertEqual(facts['chart_legend']['yellow_gold_line']['name'], 'EMA 20')
        self.assertTrue(facts['chart_legend']['yellow_gold_line']['visible'])
        reply = self.ask('What is this yellow line on the chart?', provider='gemini')
        self.assertEqual(reply['provider'], 'local')
        self.assertIn('EMA(20)', reply['answer'])

    def test_workspace_sync_does_not_interrupt_voice(self):
        with patch.object(api, 'services', return_value=(self.svc, SimpleNamespace(config={}))), patch('core.runtime.announce') as announce, TestClient(api.app) as client:
            response = client.post('/trading/workspace', json={'client_id':'front', 'session_id':self.s['id'], 'focused':True, 'ema':False})
            self.assertEqual(response.status_code, 200)
            announce.assert_not_called()
            self.assertFalse(client.get('/trading/context').json()['chart_legend']['yellow_gold_line']['visible'])

    def test_custom_cache_and_budget(self):
        self.s = self.svc.mutate(self.s['id'], 'thesis', {'key': 'thesis', 'revision': 0, 'thesis': 'Range may break higher', 'invalidation': 'Below the range'})
        response = SimpleNamespace(text='Interpretation from the visible snapshot.', usage_metadata=SimpleNamespace(total_token_count=24))
        client = SimpleNamespace(aio=SimpleNamespace(aclose=AsyncMock()))
        with patch('google.genai.Client', return_value=client), patch('config.get_agent_api_key', return_value='test'), patch('core.quota.generate', new_callable=AsyncMock, return_value=response) as generate:
            kwargs = {'provider': 'gemini', 'config': {'max_guide_questions_per_session': 1}}
            first = self.ask('Evaluate the current structure', **kwargs)
            self.assertEqual(first, self.ask('Evaluate the current structure', **kwargs))
            self.assertEqual(generate.await_count, 1)
            with self.assertRaisesRegex(ValueError, 'budget'):
                self.ask('Describe the visible evidence', **kwargs)
            self.assertEqual(self.ask('Explain RSI', **kwargs)['provider'], 'local')
        self.assertEqual(self.s, self.svc.get(self.s['id']))

    def test_http_context_and_validation(self):
        with patch.object(api, 'services', return_value=(self.svc, SimpleNamespace(config={}))), TestClient(api.app) as client:
            self.assertEqual(client.get('/trading/context').status_code, 422)
            self.assertEqual(client.post('/trading/workspace', json={'client_id': 'one', 'session_id': self.s['id']}).status_code, 200)
            self.assertEqual(client.get('/trading/context').json()['id'], self.s['id'])
            reply = client.post('/trading/guide/' + self.s['id'], json={'question': 'Explain this candle'})
            self.assertEqual(reply.status_code, 200)
            self.assertEqual(reply.json()['candle_id'], self.s['candles'][-1]['id'])
            self.assertEqual(client.post('/trading/guide/' + self.s['id'], json={'question': 'Explain it', 'candle_id': 'future'}).status_code, 422)
            self.assertEqual(client.post('/trading/guide/' + self.s['id'], json={'question': 'Explain it', 'provider': 'invalid'}).status_code, 422)


if __name__ == '__main__': unittest.main()
