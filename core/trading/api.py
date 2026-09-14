"""HTTP and voice share exactly the same validated service."""
from pathlib import Path
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from core.trading.simulator import TradingService, Conflict
from core.trading.orchestration import AnalystDesk
from core.trading.schemas import NewSession, AnalysisRequest
from core import runtime
from core.trading.data import coinbase
import time
import asyncio

router=APIRouter(prefix='/trading',tags=['trading'])
_service=None
_desk=None


def services():
    global _service,_desk
    from config import load_config
    full=load_config()
    cfg={'gemini_model':'gemini-3.5-flash',**full.get('trading',{}),'quota':full.get('quota',{})}
    if not cfg.get('enabled',True): raise HTTPException(403,'Trading Lab disabled')
    if _service is None:
        _service=TradingService(Path(__file__).resolve().parents[2]/'memory'/'trading_lab.db',
            str(cfg.get('fee_rate','0.001')),str(cfg.get('slippage_rate','0.0005')))
        _desk=AnalystDesk(_service,cfg)
    return _service,_desk


def checked(fn,*args):
    try: return fn(*args)
    except Conflict as exc: raise HTTPException(409,str(exc)) from exc
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc


@router.get('/providers')
def providers():
    """Expose optional-provider availability, never credentials."""
    import os
    from config import load_config
    cfg=load_config().get('trading',{})
    if not cfg.get('enabled',True): raise HTTPException(403,'Trading Lab disabled')
    return {'default':'gemini', 'openai':bool(cfg.get('openai_model') and os.getenv('OPENAI_API_KEY'))}


@router.post('/sessions')
def create(body:NewSession):
    service,_=services()
    return checked(service.create,body.model_dump())


@router.get('/sessions/{sid}')
def snapshot(sid:str):
    service,_=services(); return checked(service.get,sid)


@router.post('/sessions/{sid}/{action}')
async def command(sid:str,action:str,body:dict):
    service,_=services()
    result=checked(service.mutate,sid,action,body)
    await runtime.emit('trading',{'session_id':sid,'sequence':result['sequence'],'revision':result['revision'],'event':'changed'})
    return result


@router.post('/analysis/{sid}')
async def analyze(sid:str,body:AnalysisRequest,request:Request):
    _,desk=services()
    task=asyncio.create_task(desk.analyze(sid,body.model_dump()))
    try:
        while not task.done():
            if await request.is_disconnected():
                task.cancel()
                raise HTTPException(499,'Analysis cancelled by client')
            await asyncio.wait({task},timeout=.2)
        return await task
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@router.get('/analysis/{sid}')
def last_analysis(sid:str):
    import json
    service,_=services();state=checked(service.get,sid)
    with service.store.transaction() as db:
        row=db.execute('SELECT data FROM analyses WHERE session=? ORDER BY rowid DESC LIMIT 1',(sid,)).fetchone()
    if not row:return None
    result=json.loads(row[0]);result['stale']=result['revision']!=state['revision']
    return result


@router.get('/journal')
def journal():
    service,_=services(); return service.journal()


@router.post('/review/{sid}')
def review(sid:str,body:dict):
    service,_=services(); return checked(service.review,sid,body)


@router.get('/progress/{sid}')
def progress(sid:str):
    service,_=services(); return checked(service.progress,sid)


@router.post('/historical')
async def historical(body:dict):
    service,_=services()
    try:
        start=int(body.pop('start'));end=int(body.pop('end'))
        request=NewSession.model_validate(body)
        data=await coinbase(request.symbol,request.interval,start,end)
        return service.create(request.model_dump(),data['candles'])
    except (ValueError,KeyError) as exc: raise HTTPException(422,str(exc)) from exc


@router.post('/observation')
async def observe(body:NewSession):
    service,_=services()
    end=int(time.time())//body.interval*body.interval
    data=await coinbase(body.symbol,body.interval,end-body.interval*100,end)
    return checked(service.create,{**body.model_dump(),'environment':'observation'},data['candles'])


@router.post('/observation/{sid}/poll')
async def poll(sid:str):
    service,_=services(); state=checked(service.get,sid)
    if state.get('environment')!='observation': raise HTTPException(422,'Not an observation account')
    end=int(time.time())//state['interval']*state['interval']
    start=state['candles'][-1]['time']
    data=await coinbase(state['symbol'],state['interval'],start,end)
    result=checked(service.ingest,sid,data['candles'],state['revision'])
    await runtime.emit('trading',{'session_id':sid,'sequence':result['sequence'],'revision':result['revision'],'event':'changed'})
    return result


# Offline launch without importing audio, desktop automation or Gemini Live.
app=FastAPI(title='Freya Trading Lab (simulation only)')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:3000'],allow_methods=['*'],allow_headers=['*'])
app.include_router(router)
