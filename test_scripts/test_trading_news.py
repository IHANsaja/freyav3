import asyncio
import unittest
from unittest.mock import patch
import httpx
from core.trading import news
from core.trading.data import INTERVALS, sample
from core.trading.schemas import NewSession

RSS=b'''<rss><channel><item><title>Bitcoin market update</title><link>https://www.coindesk.com/markets/update</link><pubDate>Mon, 14 Sep 2026 10:00:00 GMT</pubDate></item><item><title>Bad link</title><link>javascript:alert(1)</link><pubDate>Mon, 14 Sep 2026 10:00:00 GMT</pubDate></item><item><title>Undated</title><link>https://www.coindesk.com/a</link></item><item><title>Future</title><link>https://www.coindesk.com/future</link><pubDate>Mon, 14 Sep 2037 10:00:00 GMT</pubDate></item></channel></rss>'''
NOW=1789466400

class NewsTests(unittest.TestCase):
    def tearDown(self): news._cache.clear()

    def test_dated_safe_links_only(self):
        rows=news.parse_feed(RSS,'CoinDesk',NOW)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['symbols'],['BTC'])
        with self.assertRaises(ValueError): news.parse_feed(b'<!DOCTYPE rss [<!ENTITY x "attack">]><rss/>','CoinDesk',NOW)
        with self.assertRaises(ValueError): news.parse_feed(b'x'*1_000_001,'CoinDesk',NOW)

    def test_cache_and_explicit_stale_fallback(self):
        async def run():
            calls=[]
            def handle(request):
                calls.append(request.url)
                return httpx.Response(200,content=RSS)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                first=await news._source(client,'CoinDesk',NOW)
                again=await news._source(client,'CoinDesk',NOW+10)
                self.assertEqual(first,again);self.assertEqual(len(calls),1)
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(503))) as client:
                stale=await news._source(client,'CoinDesk',NOW+301)
                self.assertEqual(stale['items'],first['items'])
                self.assertEqual(stale['fetched_at'],NOW)
                self.assertTrue(stale['error'])
        asyncio.run(run())

    def test_failure_without_cache_never_invents_headlines(self):
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(503))) as client:
                failed=await news._source(client,'CoinDesk',NOW)
            self.assertEqual(failed['items'],[]);self.assertIsNone(failed['fetched_at'])
            with self.assertRaises(ValueError): await news.headlines('UNSUPPORTED')
        asyncio.run(run())

    def test_new_candle_resolutions_validate(self):
        for interval in (21600,86400):
            self.assertIn(interval,INTERVALS)
            self.assertEqual(NewSession(key='x',interval=interval).interval,interval)
            rows=sample(interval=interval,count=2)
            self.assertEqual(rows[1]['time']-rows[0]['time'],interval)

if __name__=='__main__':unittest.main()
