import asyncio
import unittest
from unittest.mock import patch
from core.events import EventBus


class DashboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_histories_not_replayed(self):
        bus=EventBus()
        await bus.publish('trading',{'session_id':'s','sequence':1,'revision':1,'event':'changed'})
        self.assertFalse(bus.replay_buffer())

    async def test_slow_client_does_not_block(self):
        import server
        class Slow:
            async def send_json(self,message):await asyncio.sleep(60)
            async def close(self,code):pass
        client=Slow();queue=asyncio.Queue(maxsize=2)
        with patch.object(server,'_client_queues',{client:queue}),patch.object(server,'_client_writers',{}):
            await asyncio.wait_for(server.broadcast({'type':'test'}),.1)
            await asyncio.wait_for(server.broadcast({'type':'test'}),.1)
            await asyncio.wait_for(server.broadcast({'type':'test'}),.1)
            self.assertNotIn(client,server._client_queues)

    async def test_authoritative_reconnect_has_terminal_mission(self):
        import server
        from core.missions import missions,Mission
        from fastapi.testclient import TestClient
        from core.events import bus
        original=missions._missions
        try:
            missions._missions={'proof':Mission('proof','test',status='failed')}
            with TestClient(server.app).websocket_connect('/ws') as socket:
                found=False
                for _ in range(len(bus.replay_buffer())+10):
                    message=socket.receive_json()
                    if message['type']=='authoritative':
                        self.assertEqual(message['payload']['missions'][0]['status'],'failed');found=True;break
                self.assertTrue(found)
        finally:missions._missions=original


if __name__=='__main__':unittest.main()
