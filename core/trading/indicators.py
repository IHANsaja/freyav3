"""EMA seeds with SMA(20); RSI/ATR use Wilder(14), null before warm-up."""
def calculate(rows):
    result = []
    closes = []; gains = []; losses = []; trs = []
    ema = gain = loss = atr = None
    for i,r in enumerate(rows):
        c,h,l = (float(r[k]) for k in ("close","high","low"))
        prev = closes[-1] if closes else c
        closes.append(c)
        trs.append(max(h-l,abs(h-prev),abs(l-prev)))
        if i:
            gains.append(max(c-prev,0)); losses.append(max(prev-c,0))
        if i == 19: ema = sum(closes[-20:])/20
        elif i > 19: ema += (c-ema)*2/21
        if i == 13: atr = sum(trs)/14
        elif i > 13: atr = (atr*13+trs[-1])/14
        if i == 14: gain,loss = sum(gains)/14,sum(losses)/14
        elif i > 14: gain,loss = (gain*13+gains[-1])/14,(loss*13+losses[-1])/14
        rsi = None if gain is None else (50 if gain == loss == 0 else 100 if loss == 0 else 100-100/(1+gain/loss))
        result.append(dict(time=r["time"],ema=ema,rsi=rsi,atr=atr))
    return result
