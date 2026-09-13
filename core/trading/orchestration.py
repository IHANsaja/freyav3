import asyncio
import hashlib
import json
import time
from core.trading.providers import explain, image_data, PROMPT_VERSION
from core.trading.schemas import Analysis, AnalysisRequest
from core.trading.persistence import encode


class AnalystDesk:
    def __init__(self, service, config=None):
        from config.models import TEXT_MODEL, normalize_models
        self.service=service; self.config=normalize_models({"gemini_model":TEXT_MODEL, **(config or {})}); self.lock=asyncio.Lock()

    async def analyze(self,sid,request):
        req=AnalysisRequest.model_validate(request)
        image=image_data(req.image_base64)
        if image and req.provider=='offline': raise ValueError('Image analysis requires a configured Gemini or OpenAI provider')
        snapshot=self.service.snapshot(sid)
        identity=hashlib.sha256(encode([snapshot,req.provider,self.config,PROMPT_VERSION,
            hashlib.sha256(image[0]).hexdigest() if image else None]).encode()).hexdigest()
        async with self.lock:
            with self.service.store.transaction() as db:
                old=db.execute('SELECT data FROM analyses WHERE id=?',(identity,)).fetchone()
                if old:
                    result=json.loads(old[0])
                used=db.execute('SELECT COUNT(*) FROM analyses WHERE session=?',(sid,)).fetchone()[0]
            if old:
                result['stale']=snapshot['revision']!=self.service.get(sid)['revision']
                return result
            if used>=self.config.get('max_analyses_per_session',20): raise ValueError('Analysis budget exhausted')
            stages=[]
            def stage(name,status,finding,start,evidence=None):
                stages.append(dict(name=name,status=status,finding=finding,duration_ms=round((time.perf_counter()-start)*1000,2),
                    evidence=evidence or [snapshot['candles'][-1]['id']],snapshot_id=snapshot['snapshot_id']))
            start=time.perf_counter(); stage('Scout','done','Visible replay snapshot captured',start)
            start=time.perf_counter(); veto=bool(snapshot['flags'])
            stage('Data validator','veto' if veto else 'done','; '.join(snapshot['flags']) or 'OHLCV and cadence valid',start)
            start=time.perf_counter()
            usage={'model':self.config.get(f'{req.provider}_model'),'tokens':None,'cost_usd':None}
            cancelled=False
            try:
                raw,usage=await asyncio.wait_for(explain(snapshot,req.provider,self.config,image),self.config.get('analysis_timeout_s',45))
                analysis=Analysis.model_validate(raw)
                ids={r['id'] for r in snapshot['candles']}
                for observation in [*analysis.observations,*analysis.zones]:
                    if not set(observation.evidence)<=ids: raise ValueError('Analysis cites unavailable candles')
                for zone in analysis.zones:
                    if zone.high<zone.low: raise ValueError('Invalid analysis zone')
                stage('Analyst/Skeptic','done' if req.provider!='offline' else 'offline','Scenarios are interpretations, not measured forecasts',start)
                status='done'; error=None
            except asyncio.CancelledError:
                cancelled=True;analysis=None;status='cancelled';error='Analysis cancelled; provider billing may still apply';veto=True
                stage('Analyst/Skeptic','cancelled',error,start)
            except Exception as exc:
                analysis=None
                status='error'; error=f'Analysis failed ({type(exc).__name__}); no validated result'
                stage('Analyst/Skeptic','error',error,start); veto=True
            start=time.perf_counter(); stage('Risk checker','veto' if veto else 'done',
                'Veto retained: incomplete data or analysis error' if veto else 'Explanation only. Orders independently validate cash, reservations and long-only quantity.',start)
            start=time.perf_counter(); stage('Coach','skipped' if analysis is None else 'done',analysis.lesson if analysis else 'No lesson from invalid analysis',start)
            start=time.perf_counter(); stage('Recorder','done','Immutable snapshot and stage audit saved',start)
            result=dict(id=identity,snapshot_id=snapshot['snapshot_id'],snapshot=snapshot,as_of=snapshot['as_of'],
                revision=snapshot['revision'],provider=req.provider,prompt_version=PROMPT_VERSION,usage=usage,
                status=status,error=error,veto=veto,stages=stages,image_levels_approximate=bool(image),
                analysis=analysis.model_dump(mode='json') if analysis else None)
            with self.service.store.transaction() as db:
                db.execute('INSERT INTO analyses VALUES (?,?,?)',(identity,sid,encode(result)))
                db.execute('INSERT INTO journal(session,entry) VALUES (?,?)',(sid,encode({'action':'analysis','analysis_id':identity,'as_of':snapshot['as_of'],'status':status})))
            result['stale']=self.service.get(sid)['revision']!=snapshot['revision']
            if cancelled: raise asyncio.CancelledError()
            return result
