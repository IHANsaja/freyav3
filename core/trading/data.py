"""Deterministic synthetic candles and read-only Coinbase public market data (no API key)."""
import asyncio
import math
import time
from datetime import datetime, timezone
from decimal import Decimal
import httpx

# Coinbase Exchange spot products: symbol -> (name, synthetic sample base price).
MARKETS = {
    "BTC-USD": ("Bitcoin", 60000), "ETH-USD": ("Ethereum", 3000), "SOL-USD": ("Solana", 150),
    "XRP-USD": ("XRP", 0.6), "DOGE-USD": ("Dogecoin", 0.15), "ADA-USD": ("Cardano", 0.5),
    "AVAX-USD": ("Avalanche", 30), "LINK-USD": ("Chainlink", 15), "LTC-USD": ("Litecoin", 80),
}
INTERVALS = (60, 300, 900, 3600, 21600, 86400)
EXCHANGE = "https://api.exchange.coinbase.com"
_stats_cache = {}


def sample(symbol="BTC-USD", interval=900, count=500):
    base = MARKETS.get(symbol, ("", 3000))[1]
    previous = base
    rows = []
    for i in range(count):
        digits = 2 if base >= 10 else 5
        close = round(base * (1 + .035 * math.sin(i / 13) + .012 * math.sin(i / 3) + i * .00003), digits)
        spread = round(base * (.003 + .001 * (1 + math.sin(i))), digits)
        rows.append(dict(id=f"{symbol}:{interval}:{1735689600+i*interval}",
            time=1735689600+i*interval, open=str(previous), high=str(max(previous, close)+spread),
            low=str(min(previous, close)-spread), close=str(close), volume=str(100+i%37)))
        previous = close
    return rows


def quality(rows, interval):
    flags = []
    ids=set()
    for i, row in enumerate(rows):
        if row['id'] in ids or not isinstance(row['time'],int): raise ValueError('Invalid candle identity')
        ids.add(row['id'])
        o,h,l,c,v = (Decimal(row[k]) for k in ("open","high","low","close","volume"))
        if not all(x.is_finite() for x in (o,h,l,c,v)) or not 0 < l <= min(o,c) <= max(o,c) <= h or v < 0:
            raise ValueError("Invalid OHLCV candle")
        if i and row['time']<=rows[i-1]['time']: raise ValueError('Candles must be strictly chronological')
        if i and row["time"] - rows[i-1]["time"] != interval:
            flags.append(f"gap:{rows[i-1]['time']}:{row['time']}")
    return flags


async def coinbase(symbol, interval, start, end):
    if symbol not in MARKETS or interval not in INTERVALS or not 0 < end-start <= interval*10000:
        raise ValueError("Invalid historical data range")
    candles = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for cursor in range(start, end, interval*299):
            iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
            response = await client.get(f"https://api.exchange.coinbase.com/products/{symbol}/candles",
                params={"granularity": interval,"start":iso(cursor),"end":iso(min(end,cursor+interval*299))})
            response.raise_for_status()
            for t,l,h,o,c,v in response.json():
                if start <= t < end:
                    candles[t] = dict(id=f"{symbol}:{interval}:{t}",time=t,
                        open=str(o),high=str(h),low=str(l),close=str(c),volume=str(v))
    rows = [candles[t] for t in sorted(candles)]
    flags=quality(rows,interval)
    if not rows or rows[0]['time']>start: flags.append('missing leading candles')
    if not rows or rows[-1]['time']+interval<end: flags.append('missing trailing candles')
    return {"candles":rows,"flags":flags,"source":"Coinbase Exchange historical"}


async def live_candle(symbol, interval):
    """The still-forming candle for display. Never persisted, never used for fills."""
    if symbol not in MARKETS or interval not in INTERVALS: raise ValueError("Invalid market")
    now = int(time.time()); bucket = now // interval * interval
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{EXCHANGE}/products/{symbol}/candles",
            params={"granularity": interval, "start": iso(bucket), "end": iso(now)})
        response.raise_for_status()
    row = next((r for r in response.json() if r[0] == bucket), None)
    if row is None: return None
    t, l, h, o, c, v = row
    return dict(id=f"{symbol}:{interval}:{t}", time=t, open=str(o), high=str(h), low=str(l),
        close=str(c), volume=str(v), forming=True)


def cached_price(symbol):
    entry = _stats_cache.get(symbol)
    return entry[1]["price"] if entry and time.time() - entry[0] < 60 else None


async def live_stats(symbols):
    """Last trade and 24h open per symbol. Display only: never used for fills or balances."""
    symbols = [s for s in dict.fromkeys(symbols) if s in MARKETS]
    now = time.time()
    stale = [s for s in symbols if now - _stats_cache.get(s, (0, None))[0] > 3]
    if stale:
        async with httpx.AsyncClient(timeout=10) as client:
            async def one(symbol):
                try:
                    response = await client.get(f"{EXCHANGE}/products/{symbol}/stats")
                    response.raise_for_status(); raw = response.json()
                    last, open_ = Decimal(raw["last"]), Decimal(raw["open"])
                    _stats_cache[symbol] = (time.time(), dict(symbol=symbol, price=str(last), open_24h=str(open_),
                        high_24h=raw["high"], low_24h=raw["low"], volume_24h=raw["volume"],
                        change_24h=str(round((last / open_ - 1) * 100, 2)) if open_ else "0"))
                except (httpx.HTTPError, KeyError, ArithmeticError, ValueError):
                    pass  # keep any previous value; the client shows it as delayed
            await asyncio.gather(*(one(s) for s in stale))
    return [dict(**_stats_cache[s][1], fetched_at=_stats_cache[s][0]) for s in symbols if s in _stats_cache]
