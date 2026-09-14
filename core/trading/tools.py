import json
import asyncio
from core import runtime
from core.registry import tool, OBJ, P, STR, INT
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


@tool('get_trading_lab_context',
    "Read the active Trading Lab's selected candle, indicators, portfolio, recent orders and UI help WITHOUT screenshots. Call before answering questions about this workspace. If multiple sessions are active, ask which one. Read-only; never place orders unless separately requested. If analysis_locked=true, explain mechanics only until the user records a thesis.",
    OBJ({'session_id':P(STR,'Optional explicit session; otherwise use the active workspace')}),gate='trading.enabled')
def get_trading_lab_context(args,ctx):
    from core.trading.guide import context
    service,_=services()
    return json.dumps(context(service,args.get('session_id')),default=str)
