"""Atomic Decimal spot simulator. Unrevealed candles stay inside persisted state."""
import hashlib
import json
import uuid
import time
from decimal import Decimal as D
from core.trading.data import sample, quality
from core.trading.indicators import calculate
from core.trading.persistence import Store, encode
from core.trading.schemas import NewSession, Order, Thesis, Advance, Command


class Conflict(ValueError): pass


class TradingService:
    def __init__(self, path, fee="0.001", slippage="0.0005"):
        self.store = Store(path)
        self.fee, self.slippage = D(fee),D(slippage)
        if not 0 <= self.fee < D('.1') or not 0 <= self.slippage < D('.1'):
            raise ValueError("Invalid simulation costs")

    def create(self, request, candles=None):
        req = NewSession.model_validate(request)
        if req.environment == 'observation' and candles is None:
            raise ValueError('Live paper accounts require exchange candles; synthetic data is not allowed')
        signature = encode({"create":req.model_dump(),"candles":candles})
        with self.store.transaction() as db:
            old = self._duplicate(db, req.key, signature)
            if old is not None: return old
            rows = candles if candles is not None else sample(req.symbol,req.interval)
            if len(rows)<30: raise ValueError("At least 30 candles required")
            quality(rows,req.interval)
            s = dict(id=uuid.uuid4().hex,symbol=req.symbol,interval=req.interval,mode=req.mode,
                source="Deterministic sample data (synthetic)" if candles is None else ("Coinbase Exchange · live market" if req.environment == 'observation' else "Imported historical candles"),
                environment=req.environment,revision=0,sequence=0,cursor=len(rows)-1 if req.environment=='observation' else 29,candles=rows,cash="10000",quantity="0",
                fee=str(self.fee),slippage=str(self.slippage),orders=[],fills=[],ledger=[],
                thesis=None,equity_history=["10000"])
            db.execute("INSERT INTO sessions VALUES (?,?)",(s['id'],encode(s)))
            result = self._view(s)
            db.execute("INSERT INTO commands VALUES (?,?,?)",(req.key,signature,encode(result)))
            return result

    def _duplicate(self, db, key, signature):
        row = db.execute("SELECT request,response FROM commands WHERE key=?",(key,)).fetchone()
        if row:
            if row[0] != signature: raise Conflict("Idempotency key reused for a different command")
            return json.loads(row[1])

    def _load(self, db, sid):
        row = db.execute("SELECT state FROM sessions WHERE id=?",(sid,)).fetchone()
        if not row: raise ValueError("Unknown session")
        return json.loads(row[0])

    def get(self, sid):
        with self.store.transaction() as db: return self._view(self._load(db,sid))

    def progress(self, sid):
        with self.store.transaction() as db:
            self._load(db,sid)
            result={}
            entries=[json.loads(row[0]) for row in db.execute('SELECT entry FROM journal WHERE session=?',(sid,))]
            reviews=[e for e in entries if e.get('action')=='review']
            analyses=[json.loads(row[0]) for row in db.execute('SELECT data FROM analyses WHERE session=?',(sid,))]
            result['learning']={'review_count':len(reviews),'followed_plan_count':sum(bool(e.get('followed_plan')) for e in reviews),
                'analysis_count':len(analyses),'known_ai_tokens':sum(a['usage'].get('tokens') or 0 for a in analyses),
                'ai_cost_usd':None if any(a['usage'].get('cost_usd') is None for a in analyses) else str(sum((D(a['usage']['cost_usd']) for a in analyses),D(0)))}
            return result['learning']

    def journal(self):
        with self.store.transaction() as db:
            return [dict(id=i,session=s,**json.loads(e)) for i,s,e in db.execute("SELECT * FROM journal ORDER BY id DESC LIMIT 500")]

    def review(self,sid,request):
        from core.trading.schemas import Review
        req=Review.model_validate(request);signature=encode([sid,'review',request])
        with self.store.transaction() as db:
            old=self._duplicate(db,req.key,signature)
            if old is not None:return old
            s=self._load(db,sid)
            result=dict(action='review',note=req.note,followed_plan=req.followed_plan,
                as_of=s['candles'][s['cursor']]['time'],revision=s['revision'])
            db.execute('INSERT INTO journal(session,entry) VALUES (?,?)',(sid,encode(result)))
            db.execute('INSERT INTO commands VALUES (?,?,?)',(req.key,signature,encode(result)))
            return result

    def _view(self,s):
        visible = s['candles'][:s['cursor']+1]
        reserved_cash,reserved_qty = self._reserved(s)
        equity = D(s['cash'])+D(s['quantity'])*D(visible[-1]['close'])
        peak=D('10000'); drawdown=D(0)
        for value in s['equity_history']:
            peak=max(peak,D(value)); drawdown=max(drawdown,(peak-D(value))/peak)
        return {**{k:v for k,v in s.items() if k not in ('candles','equity_history')},
            "candles":visible,"indicators":calculate(visible),"flags":quality(visible,s['interval']),
            "reserved_cash":str(reserved_cash),"reserved_quantity":str(reserved_qty),
            "equity":str(equity),"fees":str(sum((D(f['fee']) for f in s['fills']),D(0))),
            "drawdown":str(drawdown),"sample_size":len(s['fills']),
            "feed_stale":s.get('environment')=='observation' and time.time()>visible[-1]['time']+s['interval']*2,
            "finished":s.get('environment','replay')=='replay' and s['cursor']==len(s['candles'])-1}

    def _reserved(self,s,exclude=None):
        orders=[o for o in s['orders'] if o['status']=='pending' and o['id']!=exclude]
        return (sum((D(o['reserved']) for o in orders if o['side']=='buy'),D(0)),
                sum((D(o['quantity']) for o in orders if o['side']=='sell'),D(0)))

    def mutate(self,sid,action,request):
        schema={'order':Order,'thesis':Thesis,'advance':Advance,'cancel':Command}.get(action)
        if schema is None: raise ValueError("Unknown command")
        body=dict(request); order_id=body.pop('order_id',None)
        req=schema.model_validate(body)
        signature=encode([sid,action,request])
        with self.store.transaction() as db:
            old=self._duplicate(db,req.key,signature)
            if old is not None: return old
            s=self._load(db,sid)
            if req.revision!=s['revision']: raise Conflict("Revision changed; refresh the authoritative snapshot")
            if action=='thesis':
                s['thesis']={'text':req.thesis,'invalidation':req.invalidation,'as_of':s['candles'][s['cursor']]['time']}
            elif action=='order': self._order(s,req)
            elif action=='advance':
                if s.get('environment')=='observation': raise ValueError("Observation advances only on fetched closed market candles")
                for _ in range(req.bars):
                    if s['cursor']>=len(s['candles'])-1: break
                    s['cursor']+=1
                    self._fill_bar(s)
                    s['equity_history'].append(str(D(s['cash'])+D(s['quantity'])*D(s['candles'][s['cursor']]['close'])))
            else:
                order=next((o for o in s['orders'] if o['id']==order_id and o['status']=='pending'),None)
                if order is None: raise ValueError("Pending order not found")
                order['status']='cancelled'
            s['revision']+=1; s['sequence']+=1
            db.execute("UPDATE sessions SET state=? WHERE id=?",(encode(s),sid))
            db.execute("INSERT INTO journal(session,entry) VALUES (?,?)",(sid,encode({
                'action':action,'as_of':s['candles'][s['cursor']]['time'],'revision':s['revision'],
                'command':request,'thesis':s['thesis'],'fills':s['fills'] if action=='advance' else []})))
            result=self._view(s)
            db.execute("INSERT INTO commands VALUES (?,?,?)",(req.key,signature,encode(result)))
            return result

    def _order(self,s,r):
        if quality(s['candles'][:s['cursor']+1],s['interval']):
            raise ValueError('Data validator veto: visible history contains missing candles')
        if not s['thesis']: raise ValueError("Record a thesis and invalidation before ordering")
        if s.get('environment','replay')=='replay' and s['cursor']==len(s['candles'])-1: raise ValueError("Replay complete")
        if s.get('environment')=='observation' and time.time()>s['candles'][-1]['time']+s['interval']*2:
            raise ValueError("Market feed is stale; refresh before ordering")
        if r.kind!='market' and r.price is None: raise ValueError("Trigger/limit price required")
        if r.kind=='bracket' and (r.side!='sell' or r.target is None or r.target<=r.price):
            raise ValueError("Bracket requires a sell stop below its target")
        cash,qty=self._reserved(s)
        reference=r.price if r.kind=='limit' else D(s['candles'][s['cursor']]['close'])
        reserve=r.quantity*reference*(1+D(s['slippage']))*(1+D(s['fee']))
        if r.side=='buy' and reserve>D(s['cash'])-cash: raise ValueError("Insufficient available cash")
        if r.side=='sell' and r.quantity>D(s['quantity'])-qty: raise ValueError("Insufficient unreserved position")
        s['orders'].append(dict(id=uuid.uuid4().hex,side=r.side,kind=r.kind,quantity=str(r.quantity),
            price=str(r.price) if r.price else None,target=str(r.target) if r.target else None,
            submitted=s['cursor'],submitted_at=time.time() if s.get('environment')=='observation' else None,status='pending',reserved=str(reserve) if r.side=='buy' else '0',thesis=s['thesis']))

    def _fill_bar(self,s):
        bar=s['candles'][s['cursor']]
        op,hi,lo=(D(bar[k]) for k in ('open','high','low'))
        for order in s['orders']:
            if order['status']!='pending' or order['submitted']>=s['cursor']: continue
            if s.get('environment')=='observation' and (order.get('submitted_at') is None or bar['time'] < order['submitted_at']):
                # Never infer pre-submission execution from a partially observed candle.
                if order.get('submitted_at') is None:
                    order['status']='rejected';order['reason']='Legacy observation order lacks submission time'
                continue
            if s['cursor'] and bar['time']-s['candles'][s['cursor']-1]['time']!=s['interval']:
                order['status']='rejected';order['reason']='Missing candle interval; execution cannot be reconstructed';continue
            buy=order['side']=='buy'; kind=order['kind']; price=None; ambiguous=False
            trigger=D(order['price']) if order['price'] else None
            if kind=='market': price=op
            elif kind=='limit':
                if buy and lo<=trigger: price=min(op,trigger)
                elif not buy and hi>=trigger: price=max(op,trigger)
            elif kind=='stop':
                if buy and hi>=trigger: price=max(op,trigger)
                elif not buy and lo<=trigger: price=min(op,trigger)
            elif kind=='bracket':
                target=D(order['target'])
                ambiguous=lo<=trigger and hi>=target
                if lo<=trigger: price=min(op,trigger)
                elif hi>=target: price=max(op,target)
            if price is None: continue
            price*=1+D(s['slippage'])*(1 if buy else -1)
            if kind=='limit': price=min(price,trigger) if buy else max(price,trigger)
            quantity=D(order['quantity']); value=quantity*price; fee=value*D(s['fee'])
            reserved,_=self._reserved(s,order['id'])
            if buy and value+fee>D(s['cash'])-reserved:
                order['status']='rejected'; order['reason']='Gap exceeded available cash; no partial fill'; continue
            s['cash']=str(D(s['cash'])+(-value-fee if buy else value-fee))
            s['quantity']=str(D(s['quantity'])+quantity*(1 if buy else -1))
            order['status']='filled'
            fill=dict(order_id=order['id'],time=bar['time'],candle_id=bar['id'],side=order['side'],
                quantity=str(quantity),price=str(price),fee=str(fee),ambiguous=ambiguous)
            s['fills'].append(fill)
            s['ledger'].append(dict(**fill,cash=s['cash'],position=s['quantity']))

    def snapshot(self,sid):
        view=self.get(sid)
        if view['mode']=='independent' and not view['thesis']:
            raise ValueError("Record your thesis before revealing analysis in independent practice")
        snapshot={k:view[k] for k in ('id','revision','symbol','interval','source','candles','indicators','flags','thesis','fills','orders','cash','quantity','fees')}
        snapshot['as_of']=view['candles'][-1]['time']+view['interval']
        snapshot['snapshot_id']=hashlib.sha256(encode(snapshot).encode()).hexdigest()
        return snapshot

    def ingest(self,sid,rows,revision):
        """Append closed observation candles, deduplicating reconnect backfill atomically."""
        with self.store.transaction() as db:
            s=self._load(db,sid)
            if s.get('environment')!='observation': raise ValueError('Replay accounts cannot ingest current data')
            if s['revision']!=revision: raise Conflict('Refresh observation snapshot before backfill')
            fresh=sorted({r['time']:r for r in rows if r['time']>s['candles'][-1]['time']}.values(),key=lambda r:r['time'])
            if any(r['time']+s['interval']>time.time() for r in fresh): raise ValueError('Open/future candle rejected')
            if quality([s['candles'][-1],*fresh],s['interval']):
                raise ValueError('Backfill contains missing candles; no fabricated fills across gaps')
            for row in fresh:
                s['candles'].append(row);s['cursor']+=1;self._fill_bar(s)
                s['equity_history'].append(str(D(s['cash'])+D(s['quantity'])*D(row['close'])))
            if fresh:
                s['revision']+=1;s['sequence']+=1
                db.execute('UPDATE sessions SET state=? WHERE id=?',(encode(s),sid))
                db.execute('INSERT INTO journal(session,entry) VALUES (?,?)',(sid,encode({'action':'market_backfill','as_of':fresh[-1]['time'],'count':len(fresh)})))
            return self._view(s)
