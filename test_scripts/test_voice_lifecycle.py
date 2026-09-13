import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from core.voice_tasks import run_voice_tasks


class VoiceLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_error_stops_playback_and_microphone(self):
        stopped = []

        async def worker(name):
            try:
                await asyncio.Event().wait()
            finally:
                stopped.append(name)

        async def receiver():
            await asyncio.sleep(0)
            raise ConnectionError('disconnected')

        with self.assertRaises(ConnectionError):
            await run_voice_tasks(worker('mic'), receiver(), worker('speaker'))
        self.assertCountEqual(stopped, ['mic', 'speaker'])

    async def test_normal_connection_end_stops_other_workers(self):
        stopped = asyncio.Event()

        async def playback():
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        await run_voice_tasks(asyncio.sleep(0), playback())
        self.assertTrue(stopped.is_set())

    async def test_concurrent_restarts_never_overlap_sessions(self):
        import server
        active = 0
        maximum = 0

        async def session():
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(.01)  # simulate slow device release
                active -= 1

        with patch.object(server, 'run_freya', session), patch.object(server, 'broadcast', AsyncMock()), \
             patch.object(server, '_session_payload', return_value={}), \
             patch.object(server, '_voice_lifecycle_lock', asyncio.Lock()), \
             patch.object(server, 'freya_task', None), patch.object(server, 'freya_running', False), \
             patch.object(server, 'freya_started_at', None):
            await server.start_freya()
            await asyncio.sleep(0)
            await asyncio.gather(server.restart_freya(), server.restart_freya())
            await asyncio.sleep(0)
            await server.stop_freya()
            await server.restart_freya()
            self.assertEqual(maximum, 1)
            self.assertEqual(active, 0)
            self.assertIsNone(server.freya_task)
