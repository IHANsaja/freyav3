import json
import asyncio
from core import runtime
from core.registry import tool, OBJ, P, STR, INT, NUM, ARR
from core.trading.api import services, command

SESSION={'session_id':P(STR,'Session returned by open_trading_lab')}
MUTATION={**SESSION,'key':P(STR,'Unique command id; reuse only for an identical retry'),
    'revision':P(INT,'Current backend revision')}


@tool('open_trading_lab','Open the simulated Trading Lab; returns its URL and existing session or creates one.',
    OBJ({'session_id':P(STR),'key':P(STR,'Required for a new session')}),gate='trading.enabled')
def open_trading_lab(args,ctx):
    service,_=services()
    state=service.get(args['session_id']) if args.get('session_id') else service.create({'key':args.get('key','')})
    return json.dumps({'url':f"http://localhost:3000/trading?session={state['id']}",'session_id':state['id'],'revision':state['revision']})


@tool('analyze_chart','Explain visible candles and the recorded thesis. Independent practice requires a thesis first.',
    OBJ({**SESSION,'provider':P(STR,'gemini (default), offline (explicit no-AI lesson), openai (only if configured)')},['session_id']),gate='trading.enabled')
async def analyze_chart(args,ctx):
    _,desk=services()
    async def run():
        result=await desk.analyze(args['session_id'],{'provider':args.get('provider','gemini')})
        compact={k:result[k] for k in ('id','status','analysis','veto','revision','usage')}
        return json.dumps(compact,default=str)
    if ctx.source=='live':
        async def background():
            try: result=await run()
            except Exception as exc: result=f'Chart analysis failed ({type(exc).__name__})'
            runtime.announce(result)
        task=asyncio.create_task(background())
        _analysis_tasks.add(task);task.add_done_callback(_analysis_tasks.discard)
        return 'Chart analysis started in the background; the result will be announced. No order was submitted.'
    return await run()


_analysis_tasks=set()


@tool('paper_order','Submit a virtual long spot order only. Requires a recorded thesis, revision and idempotency key.',
    OBJ({**MUTATION,'side':P(STR,'buy or sell'),'kind':P(STR,'market, limit, stop or bracket'),
         'quantity':P(STR,'Positive decimal quantity'),'price':P(STR),'target':P(STR)},
        ['session_id','key','revision','side','quantity']),gate='trading.enabled')
async def paper_order(args,ctx):
    body=dict(args); sid=body.pop('session_id')
    return json.dumps(await command(sid,'order',body),default=str)


@tool('advance_replay','Advance simulated time; fill eligible virtual orders on newly revealed candles.',
    OBJ({**MUTATION,'bars':P(INT)},['session_id','key','revision']),gate='trading.enabled')
async def advance_replay(args,ctx):
    body=dict(args); sid=body.pop('session_id')
    return json.dumps(await command(sid,'advance',body),default=str)


@tool('get_paper_portfolio','Read virtual cash, position, reservations and revision.',OBJ(SESSION,['session_id']),gate='trading.enabled')
def get_paper_portfolio(args,ctx):
    service,_=services(); state=service.get(args['session_id'])
    return json.dumps({k:state[k] for k in ('id','revision','cash','quantity','reserved_cash','reserved_quantity','equity','fees')})


@tool('review_trades','Read the saved simulated decision journal.',OBJ(),gate='trading.enabled')
def review_trades(args,ctx):
    service,_=services(); return json.dumps(service.journal(),default=str)


@tool('record_trading_thesis','Record the user\'s own thesis and invalidation before analysis or paper ordering.',
    OBJ({**MUTATION,'thesis':P(STR),'invalidation':P(STR)},['session_id','key','revision','thesis','invalidation']),gate='trading.enabled')
async def record_trading_thesis(args,ctx):
    body=dict(args); sid=body.pop('session_id')
    return json.dumps(await command(sid,'thesis',body),default=str)


@tool('get_trading_learner_profile',
    "Read what the user already knows about trading (level, concepts understood, struggles, current topic). "
    "Call at the start of any trading lesson and pitch explanations at that level; empty means a complete beginner.",
    OBJ(),gate='trading.enabled')
def get_trading_learner_profile(args,ctx):
    from core.trading.learner import profile
    return json.dumps(profile())


@tool('update_trading_learner_profile',
    "Save the user's trading learning progress into long-term memory so future lessons build on it. Call when they "
    "show they understood a concept, struggle with one, or you start a new topic. Raise level gradually.",
    OBJ({'level':P(STR,'One of: complete beginner, beginner, developing, intermediate, advanced. Omit to keep.'),
         'understood':P(ARR,'Concepts they just showed they understand, in plain words e.g. "what a candle is"',items=P(STR)),
         'struggling':P(ARR,'Concepts they found confusing',items=P(STR)),
         'learning_now':P(STR,'The topic you are teaching next'),
         'note':P(STR,'Short teaching note, e.g. "learns best with food analogies"')}),gate='trading.enabled')
def update_trading_learner_profile(args,ctx):
    from core.trading.learner import update
    return json.dumps(update(args.get('level'),args.get('understood'),args.get('struggling'),
        args.get('learning_now'),args.get('note')))


FREYA_DRAW_LIMIT=30


@tool('draw_on_chart',
    "Draw on the user's active Trading Lab chart to teach visually (shown in violet as Freya's drawing). "
    "Use candle open times and prices from get_trading_lab_context (recent_candles). Kinds and points needed: "
    "hline/hray/vline/cross/text=1; trend/ray/extended/arrow/rect/ellipse/fib/long/short/pricerange/daterange/datepricerange=2; "
    "channel/pitchfork/triangle/fibext=3. After drawing, say in plain words what you drew and why. Never an order.",
    OBJ({'kind':P(STR,'Drawing kind, e.g. hline, trend, rect, fib, text, arrow'),
         'points':P(ARR,'Anchor points in order',items=OBJ({'time':P(INT,'Candle open time, unix seconds UTC'),
                                                            'price':P(NUM,'Price level')},['time','price'])),
         'text':P(STR,'Label text; required for kind=text'),
         'session_id':P(STR,'Optional; defaults to the chart the user is on')},['kind','points']),gate='trading.enabled')
async def draw_on_chart(args,ctx):
    from core.trading.guide import DRAWING_KINDS, _current_view
    service,_=services()
    view=_current_view()
    sid=args.get('session_id') or (view or {}).get('session_id')
    if not sid: return 'No Trading Lab chart is open. Ask the user to open the Trading Lab first.'
    state=service.get(sid)
    kind=str(args.get('kind','')).strip().lower()
    if kind not in DRAWING_KINDS or kind=='brush': return f'Unknown drawing kind {kind!r}. Use one of: {", ".join(k for k in DRAWING_KINDS if k!="brush")}.'
    need=DRAWING_KINDS[kind][1]
    raw=args.get('points') or []
    if len(raw)!=need: return f'{kind} needs exactly {need} point(s); got {len(raw)}.'
    iv=state['interval']; points=[]
    for p in raw:
        try: t=int(p['time']); price=float(p['price'])
        except (KeyError,TypeError,ValueError): return 'Each point needs numeric time (unix seconds) and price.'
        if price<=0: return 'Prices must be positive.'
        if t>10**11: t//=1000  # tolerate milliseconds
        points.append({'time':t//iv*iv,'price':price})
    text=str(args.get('text') or '').strip()[:200]
    if kind=='text' and not text: return 'kind=text needs text.'
    if view and view.get('session_id')==sid and sum(d.get('author')=='freya' for d in view.get('drawings') or [])>=FREYA_DRAW_LIMIT:
        return f'You already have {FREYA_DRAW_LIMIT} drawings on this chart; call clear_my_drawings first.'
    from core.trading.guide import expect_draw_ack, _draw_acks
    import uuid
    drawing={'kind':kind,'points':points,**({'text':text} if text else {})}
    draw_id=uuid.uuid4().hex
    delivered=expect_draw_ack(draw_id)
    await runtime.emit('trading',{'session_id':sid,'event':'draw','draw_id':draw_id,'drawing':drawing})
    try:
        await asyncio.wait_for(delivered,DRAW_ACK_TIMEOUT_S)
        visible=True
    except asyncio.TimeoutError:
        _draw_acks.pop(draw_id,None); visible=False
    result={'drawn':DRAWING_KINDS[kind][0],'visible':visible,'color':'violet','session_id':sid,'drawing':drawing}
    if not visible:
        result['problem']=('The Trading Lab page did not confirm the drawing, so the user cannot see it. Tell them it did '
            'not appear; they may need to reload the Trading Lab page.')
    return json.dumps(result)


DRAW_ACK_TIMEOUT_S=4


@tool('clear_my_drawings',"Remove all of Freya's own drawings from the active Trading Lab chart. The user's drawings stay.",
    OBJ({'session_id':P(STR,'Optional; defaults to the chart the user is on')}),gate='trading.enabled')
async def clear_my_drawings(args,ctx):
    from core.trading.guide import _current_view
    sid=args.get('session_id') or (_current_view() or {}).get('session_id')
    if not sid: return 'No Trading Lab chart is open.'
    await runtime.emit('trading',{'session_id':sid,'event':'clear_freya'})
    return 'Cleared your drawings from the chart.'


@tool('get_trading_lab_context',
    "Read the active Trading Lab's selected candle, indicators, portfolio, recent orders, the user's and your drawings, the learner profile and UI help WITHOUT screenshots. Call before answering questions about this workspace. It automatically resolves the chart the user is currently using, so never ask which session or chart they mean. Read-only; never place orders unless separately requested. If analysis_locked=true, explain mechanics only until the user records a thesis.",
    OBJ({'session_id':P(STR,'Optional explicit session; otherwise use the active workspace')}),gate='trading.enabled')
def get_trading_lab_context(args,ctx):
    from core.trading.guide import context
    service,_=services()
    return json.dumps(context(service,args.get('session_id')),default=str)


@tool('get_market_news',
    'Read current financial headlines with publisher links and publication times. These are TODAY’S news, never historical replay evidence or trade signals. Mention source failures/staleness. No model calls or screenshots. Fetch only when the user asks about current news.',
    OBJ({'symbol':P(STR,'ALL or asset ticker such as BTC, ETH, SOL')}),gate='trading.enabled')
async def get_market_news(args,ctx):
    from core.trading.news import headlines
    services()
    return json.dumps(await headlines(args.get('symbol','ALL')),default=str)
