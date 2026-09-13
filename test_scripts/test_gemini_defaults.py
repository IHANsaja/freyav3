import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from config.models import TEXT_MODEL, LITE_MODEL, LIVE_MODEL, normalize_models
from core.trading.schemas import AnalysisRequest
from core.trading.providers import explain
from core.trading.api import providers


class GeminiDefaultsTests(unittest.TestCase):
    def test_migrate_retired_models_preserve_pins_and_prompts(self):
        cfg = {'active_model':'gemini-2.0-flash-live-001',
               'missions':{'planner_model':'gemini-flash-latest','verifier_model':'gemini-flash-lite-latest'},
               'model':'gemini-2.5-flash', 'prompt':'gemini-flash-latest',
               'modes':[{'model_override':'models/gemini-2.0-flash'}]}
        normalize_models(cfg)
        self.assertEqual(cfg['active_model'],LIVE_MODEL)
        self.assertEqual(cfg['missions'],{'planner_model':TEXT_MODEL,'verifier_model':LITE_MODEL})
        self.assertEqual(cfg['model'],'gemini-2.5-flash')
        self.assertEqual(cfg['prompt'],'gemini-flash-latest')
        self.assertEqual(cfg['modes'][0]['model_override'],'models/'+TEXT_MODEL)

    def test_default_request_uses_gemini(self):
        self.assertEqual(AnalysisRequest().provider,'gemini')

    def test_optional_provider_requires_model_and_key(self):
        for model,key,expected in [('', '',False),('test','',False),('', 'secret',False),('test','secret',True)]:
            with patch('config.load_config',return_value={'trading':{'openai_model':model}}),patch.dict(os.environ,{'OPENAI_API_KEY':key}):
                self.assertEqual(providers(),{'default':'gemini','openai':expected})

    def test_gemini_failure_never_calls_openai(self):
        with patch('config.get_agent_api_key',side_effect=ValueError('missing key')),patch('core.trading.providers.httpx.AsyncClient') as other:
            with self.assertRaises(ValueError):
                asyncio.run(explain({},'gemini',{'gemini_model':TEXT_MODEL}))
            other.assert_not_called()

    def test_unknown_provider_never_calls_network(self):
        with patch('core.trading.providers.httpx.AsyncClient') as other:
            with self.assertRaises(ValueError):asyncio.run(explain({},'unknown',{}))
            other.assert_not_called()
