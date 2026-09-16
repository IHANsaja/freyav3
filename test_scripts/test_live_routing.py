"""Offline Live protocol regression tests: no microphone, credentials or API calls."""
import asyncio
import copy
import json
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace as NS, ModuleType
from unittest.mock import AsyncMock, patch
from google.genai import types
from config.models import LIVE_MODEL, THINKING_LIVE_MODEL, LIVE_FALLBACK_MODEL, migrate_live_defaults
from core.live_protocol import LiveRoute, Interaction, ModeChange, setup_options, routing_instruction
from core.model import FreyaModel, TOOL_DECLARATIONS, is_rotation, SessionRotation


class RoutingTests(unittest.TestCase):
    def test_migration_is_once_and_preserves_later_manual_selection(self):
        cfg = {'active_model': LIVE_FALLBACK_MODEL, 'apps': {'editor': 'custom'},
               'modes': {'custom': {'model_override': 'my-model'}},
               'missions': {'planner_model': 'pinned-text-model'}}
        self.assertTrue(migrate_live_defaults(cfg))
        self.assertEqual(cfg['active_model'], LIVE_MODEL)
        self.assertEqual(cfg['live']['fallback_model'], LIVE_FALLBACK_MODEL)
        self.assertEqual(cfg['modes']['complex_tasks']['model_override'], THINKING_LIVE_MODEL)
        self.assertEqual(cfg['apps']['editor'], 'custom')
        self.assertEqual(cfg['missions']['planner_model'], 'pinned-text-model')
        cfg['active_model'] = LIVE_FALLBACK_MODEL
        self.assertFalse(migrate_live_defaults(cfg))
        self.assertEqual(cfg['active_model'], LIVE_FALLBACK_MODEL)

    def test_load_persists_upgrade_without_importing_example_as_mode(self):
        import config
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'freya_config.json'
            path.write_text(json.dumps({'active_model': LIVE_FALLBACK_MODEL}))
            (Path(tmp)/'freya_config.example.json').write_text(json.dumps({'freya': {'personality': 'template'}}))
            with patch.object(config, 'CONFIG_PATH', str(path)):
                loaded = config.load_config()
                self.assertEqual(loaded['active_model'], LIVE_MODEL)
                self.assertNotIn('config.example', loaded['modes'])
                self.assertEqual(json.loads(path.read_text())['live']['defaults_version'], 1)
                self.assertEqual(config.get_mode_model({**loaded, 'active_mode': 'complex_tasks'}), THINKING_LIVE_MODEL)

    def test_fallback_is_bounded_sticky_and_does_not_mask_auth(self):
        route = LiveRoute(THINKING_LIVE_MODEL, {})
        class ApiError(Exception):
            code = 429
        self.assertEqual(route.fallback(ApiError()), LIVE_MODEL)
        route.configure(THINKING_LIVE_MODEL, {})
        self.assertEqual(route.model, LIVE_MODEL)
        self.assertEqual(route.fallback(ApiError()), LIVE_FALLBACK_MODEL)
        self.assertIsNone(route.fallback(ApiError()))
        route.configure(LIVE_MODEL, {})
        self.assertEqual(route.model, LIVE_MODEL)
        for err in (ValueError('invalid config'), ValueError('401 unauthenticated'), ValueError('1008 policy violation')):
            self.assertIsNone(route.fallback(err))
        self.assertFalse(is_rotation(Exception('1008 policy violation')))
        self.assertTrue(is_rotation(SessionRotation('goaway')))

    def test_config_uses_correct_protocol_without_mutating_declarations(self):
        before = copy.deepcopy(TOOL_DECLARATIONS)
        with patch('core.model.build_declarations', return_value=[]):
            for model, behavior in [(LIVE_MODEL, 'BLOCKING'), (THINKING_LIVE_MODEL, 'NON_BLOCKING'), (LIVE_FALLBACK_MODEL, None)]:
                obj = FreyaModel('test', model, 'Zephyr', 'Test', {})
                cfg = obj.get_config()
                self.assertEqual(cfg.thinking_config is not None, model == THINKING_LIVE_MODEL)
                self.assertTrue(all(d.behavior == behavior for d in cfg.tools[0].function_declarations))
                self.assertEqual(cfg.response_modalities, ['AUDIO'])
                self.assertIsNotNone(cfg.output_audio_transcription)
        self.assertEqual(TOOL_DECLARATIONS, before)
        with self.assertRaises(ValueError):
            setup_options(THINKING_LIVE_MODEL, {'live': {'thinking_level': 'minimal'}})
        self.assertEqual(setup_options(LIVE_MODEL, {'live': {'thinking_level': 'minimal'}}), {})

    def test_thinking_status_survives_spoken_filler_and_final_audio(self):
        state = Interaction(True)
        state.update(NS(server_content=types.LiveServerContent(turn_complete=True, interaction_status='IN_PROGRESS')))
        self.assertTrue(state.utterance_complete)
        self.assertEqual(state.state_after_playback(), 'thinking')
        # Both supported locations, including a status-only frame.
        state.update(NS(interaction_status='IDLE', server_content=None))
        self.assertEqual(state.state_after_playback(), 'listening')
        state.update(NS(server_content=types.LiveServerContent(model_turn=types.Content(parts=[types.Part(inline_data=types.Blob(data=b'pcm'))]), turn_complete=True, interaction_status='IDLE')))
        self.assertTrue(state.idle)
        self.assertTrue(state.utterance_complete)
        legacy = Interaction(False)
        legacy.update(NS(server_content=types.LiveServerContent(turn_complete=True)))
        self.assertTrue(legacy.idle)

    def test_already_active_mode_does_not_reconnect_or_rewrite_config(self):
        from core.tools import switch_mode
        with patch('config.load_config', return_value={'active_mode':'complex_tasks', 'modes':{'complex_tasks':{}}}):
            self.assertIn('Already in', switch_mode('complex_tasks'))

    def test_auto_routing_instructions_and_opt_out(self):
        self.assertIn('call switch_mode(complex_tasks)', routing_instruction({}, LIVE_MODEL))
        self.assertIn('Change modes only when the user asks', routing_instruction({'live': {'auto_complex_mode': False}}, LIVE_MODEL))
        self.assertIn('do not switch into it again', routing_instruction({'active_mode': 'complex_tasks'}, LIVE_FALLBACK_MODEL))


class FakeSession:
    def __init__(self):
        self.frames = asyncio.Queue()
        self.responses = []
        self.send_client_content = AsyncMock()
        self.send_realtime_input = AsyncMock()

    async def receive(self):
        frame = await self.frames.get()
        if isinstance(frame, Exception):
            raise frame
        yield frame

    async def send_tool_response(self, **kw):
        self.responses.extend(kw['function_responses'])


def message(**kw):
    return types.LiveServerMessage(**kw)


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def run_model(self, session, dispatch, scenario, model=THINKING_LIVE_MODEL):
        obj = FreyaModel('test', model, 'Zephyr', 'Test', {'active_mode': 'complex_tasks'})
        obj.get_config = lambda: types.LiveConnectConfig(response_modalities=['AUDIO'])
        obj.on_state = AsyncMock()
        played = []
        @asynccontextmanager
        async def connect(**kw):
            yield session
        obj.client = NS(aio=NS(live=NS(connect=connect)))
        stubs = {}
        for mod, attr, value in [
            ('mcp_client', 'mcp_manager', NS(start=AsyncMock())),
            ('scheduler', 'scheduler', NS(attach=lambda _:None, detach=lambda:None)),
            ('context_watch', 'tracker', NS(attach=lambda _:None, detach=lambda:None)),
            ('day_context', 'rotator', NS(attach=lambda _:None, detach=lambda:None)),
            ('hotkeys', 'start_pause_hotkey', lambda _:None),
            ('ambient', 'ambient', NS(stop_all=lambda:None)),
        ]:
            stub = ModuleType('core.'+mod); setattr(stub, attr, value); stubs['core.'+mod] = stub
        with patch.dict('sys.modules', stubs), patch('core.model.registry_dispatch', dispatch):
            task = asyncio.create_task(obj.run(NS(read=lambda:None), NS(write=played.append)))
            try:
                await asyncio.wait_for(scenario(obj, played, task), 3)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertIsNone(obj.session)

    async def test_slow_tool_does_not_block_audio_or_status_and_final_frame_plays(self):
        session = FakeSession(); started = asyncio.Event(); release = asyncio.Event(); stopped = asyncio.Event()
        async def dispatch(*args):
            started.set()
            try:
                await release.wait()
                return 'done'
            finally:
                stopped.set()
        async def scenario(obj, played, task):
            await session.frames.put(message(tool_call=types.LiveServerToolCall(function_calls=[types.FunctionCall(id='slow', name='lookup', args={})])))
            await started.wait()
            await session.frames.put(message(server_content=types.LiveServerContent(model_turn=types.Content(parts=[types.Part(inline_data=types.Blob(data=b'final-pcm'))]), turn_complete=True, interaction_status='IN_PROGRESS')))
            while not played or obj.on_state.call_args != unittest.mock.call('thinking'):
                await asyncio.sleep(.001)
            self.assertEqual(played, [b'final-pcm'])
            self.assertEqual(session.responses, [])
            release.set()
            while not session.responses: await asyncio.sleep(.001)
            await session.frames.put(message(server_content=types.LiveServerContent(interaction_status='IDLE')))
            while obj.on_state.call_args != unittest.mock.call('listening'): await asyncio.sleep(.001)
        await self.run_model(session, dispatch, scenario)
        self.assertTrue(stopped.is_set())

    async def test_mode_switch_returns_tool_result_then_reconnects(self):
        session = FakeSession()
        async def scenario(obj, played, task):
            await session.frames.put(message(tool_call=types.LiveServerToolCall(function_calls=[types.FunctionCall(id='mode', name='switch_mode', args={'mode':'complex_tasks'})])))
            with self.assertRaises(ModeChange): await task
            self.assertEqual(session.responses[0].response['result'], 'MODE_SWITCHED:complex_tasks')
        await self.run_model(session, AsyncMock(return_value='MODE_SWITCHED:complex_tasks'), scenario)

    async def test_tool_cancellation_suppresses_late_response_and_deduplicates_calls(self):
        session = FakeSession(); started = asyncio.Event(); release = asyncio.Event()
        async def dispatch(*args):
            started.set(); await release.wait(); return 'completed'
        call = message(tool_call=types.LiveServerToolCall(function_calls=[types.FunctionCall(id='once', name='action', args={})]))
        wrapped = AsyncMock(side_effect=dispatch)
        async def scenario(obj, played, task):
            await session.frames.put(call); await started.wait()
            await session.frames.put(call)
            await session.frames.put(message(tool_call_cancellation=types.LiveServerToolCallCancellation(ids=['once'])))
            await session.frames.put(message(server_content=types.LiveServerContent(interaction_status='IDLE')))
            while obj._interaction.idle is False: await asyncio.sleep(.001)
            release.set()
            while obj._pending_tools: await asyncio.sleep(.001)
            self.assertEqual(session.responses, [])
            self.assertEqual(wrapped.await_count, 1)
        await self.run_model(session, wrapped, scenario)

    async def test_recap_keeps_goal_and_only_resumes_after_mode_handoff(self):
        obj = FreyaModel('test', THINKING_LIVE_MODEL, 'Zephyr', 'Test', {},
                         transcript=NS(get=lambda:['User: debug the parser without changing the API', 'Tool: switch_mode: MODE_SWITCHED:complex_tasks']), continue_task=True)
        obj.session = FakeSession()
        await obj._send_recap()
        kw = obj.session.send_client_content.call_args.kwargs
        self.assertTrue(kw['turn_complete'])
        self.assertIn('without changing the API', kw['turns'].parts[0].text)
        obj.continue_task = False
        await obj._send_recap()
        self.assertFalse(obj.session.send_client_content.call_args.kwargs['turn_complete'])


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_handoff_and_fallback_keep_transcript_clear_cross_model_tokens(self):
        import importlib
        from unittest.mock import MagicMock
        # Import the dashboard without requiring PortAudio on the test machine.
        with patch.dict('sys.modules', {'pyaudio': NS(paInt16=8)}):
            server = importlib.import_module('server')
        cfg = {'active_provider': 'gemini', 'active_model': LIVE_MODEL, 'active_mode': 'default',
               'modes': {'complex_tasks': {'model_override': THINKING_LIVE_MODEL}},
               'audio': {'input_device_index': None, 'output_device_index': None},
               'providers': {'gemini': {'active_voice': 'Zephyr'}}, 'freya': {'personality': 'Test'}}
        attempts = []
        class ApiError(Exception): code = 503
        class FakeModel:
            def __init__(self, **kw):
                self.kw = kw; self.resume_handle = kw['resume_handle']; self.connected = False
            async def run(self, *args):
                attempts.append(self.kw)
                i = len(attempts)
                if i in (1, 3, 4): raise ApiError('unavailable')
                if i == 2:
                    self.connected = True
                    self.resume_handle = 'legacy-token'
                    self.kw['transcript'].add('User', 'debug parser, preserve public API')
                    cfg['active_mode'] = 'complex_tasks'
                    raise ModeChange('complex_tasks')
                self.connected = True
        with patch.object(server, 'FreyaModel', FakeModel), patch.object(server, 'load_config', return_value=cfg), \
             patch.object(server, 'get_api_key', return_value='test'), patch.object(server, 'load_memory', return_value=''), \
             patch.object(server, 'MicStream', MagicMock()), patch.object(server, 'SpeakerStream', MagicMock()), \
             patch.object(server, 'broadcast', AsyncMock()), patch.object(server, 'update_memory', AsyncMock()), \
             patch.object(server, 'freya_running', True), patch('core.machine_index.ensure_index'), \
             patch('asyncio.sleep', AsyncMock()):
            await server.run_freya()
        self.assertEqual([a['model_id'] for a in attempts], [LIVE_MODEL, LIVE_FALLBACK_MODEL, THINKING_LIVE_MODEL, LIVE_MODEL, LIVE_FALLBACK_MODEL])
        self.assertTrue(all(a['resume_handle'] is None for a in attempts))
        self.assertTrue(all(a['continue_task'] for a in attempts[2:]))
        self.assertEqual(len({id(a['transcript']) for a in attempts}), 1)
        self.assertIn('preserve public API', '\n'.join(attempts[-1]['transcript'].get()))

if __name__ == '__main__': unittest.main()
