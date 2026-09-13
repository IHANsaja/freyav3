"""Deterministic synthetic candles and read-only Coinbase historical candles."""
import math
from datetime import datetime, timezone
from decimal import Decimal
import httpx


def sample(symbol="BTC-USD", interval=900, count=500):
    base = 60000 if symbol == "BTC-USD" else 3000
    previous = base
    rows = []
    for i in range(count):
        close = round(base * (1 + .035 * math.sin(i / 13) + .012 * math.sin(i / 3) + i * .00003), 2)
        spread = round(base * (.003 + .001 * (1 + math.sin(i))), 2)
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
    if symbol not in ("BTC-USD", "ETH-USD") or interval not in (900,3600) or not 0 < end-start <= interval*10000:
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
