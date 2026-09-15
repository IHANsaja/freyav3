"""Bounded public RSS headlines; no model calls, article scraping, or arbitrary URLs."""
import asyncio
import time
import re
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
import httpx

SOURCES = {
    'CoinDesk': ('https://www.coindesk.com/arc/outboundfeeds/rss', {'coindesk.com', 'www.coindesk.com'}),
    'Cointelegraph': ('https://cointelegraph.com/rss', {'cointelegraph.com', 'www.cointelegraph.com'}),
    'Federal Reserve': ('https://www.federalreserve.gov/feeds/press_all.xml', {'federalreserve.gov', 'www.federalreserve.gov'}),
}
WORDS = {'BTC':'bitcoin|btc', 'ETH':'ethereum|ether|eth', 'SOL':'solana|sol', 'XRP':'xrp|ripple',
    'DOGE':'dogecoin|doge', 'ADA':'cardano|ada', 'AVAX':'avalanche|avax', 'LINK':'chainlink|link', 'LTC':'litecoin|ltc'}
_cache = {}
_lock = asyncio.Lock()
TTL = 300


def parse_feed(raw, source, now):
    if b'\x00' in raw or len(raw) > 1_000_000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Unsafe or oversized news feed')
    root = ET.fromstring(raw)
    items = []
    for item in root.findall('.//item')[:100]:
        title = ' '.join((item.findtext('title') or '').split())[:240]
        url = (item.findtext('link') or '').strip()
        parsed = urlparse(url)
        if not title or parsed.scheme != 'https' or parsed.hostname not in SOURCES[source][1] or parsed.username or parsed.password: continue
        try:
            date = parsedate_to_datetime(item.findtext('pubDate') or '')
            if date.tzinfo is None: date = date.replace(tzinfo=timezone.utc)
            published = int(date.timestamp())
        except (TypeError,ValueError,OverflowError): continue
        if published > now + 60: continue
        tags = [key for key, words in WORDS.items() if re.search(r'\b('+words+r')\b',title,re.I)]
        items.append(dict(title=title,url=url,source=source,published_at=published,symbols=tags,macro=source=='Federal Reserve'))
    return items


async def _source(client, name, now):
    old = _cache.get(name)
    if old and now-old['attempted_at'] < (TTL if not old['error'] else 60): return old
    try:
        async with client.stream('GET', SOURCES[name][0]) as response:
            response.raise_for_status()
            parts=[];size=0
            async for part in response.aiter_bytes():
                size+=len(part)
                if size>1_000_000: raise ValueError('Oversized feed')
                parts.append(part)
        items=parse_feed(b''.join(parts),name,now)
        if not items: raise ValueError('No dated headlines available')
        entry=dict(items=items,fetched_at=now,attempted_at=now,error=None)
    except (httpx.HTTPError,ValueError,ET.ParseError):
        entry=dict(items=old['items'] if old else [],fetched_at=old['fetched_at'] if old else None,attempted_at=now,error='Source unavailable')
    _cache[name]=entry
    return entry


async def headlines(symbol='ALL'):
    if symbol != 'ALL' and symbol not in WORDS: raise ValueError('Unsupported news symbol')
    async with _lock:
        now=int(time.time())
        async with httpx.AsyncClient(timeout=10,follow_redirects=False,headers={'User-Agent':'FreyaTradingLab/1.0 RSS reader'}) as client:
            rows=await asyncio.gather(*(_source(client,name,now) for name in SOURCES))
    items={}
    statuses=[]
    for name,row in zip(SOURCES,rows):
        stale=bool(row['error']) or row['fetched_at'] is None or now-row['fetched_at']>TTL
        statuses.append(dict(source=name,fetched_at=row['fetched_at'],stale=stale,error=row['error']))
        for item in row['items']:
            if symbol=='ALL' or symbol in item['symbols'] or item['macro']:
                items[item['url']]={**item,'stale':stale}
    return dict(items=sorted(items.values(),key=lambda i:i['published_at'],reverse=True)[:30],sources=statuses,
        checked_at=now,cache_seconds=TTL,context='Current real-world news; not historical replay evidence')
