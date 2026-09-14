"""Cross-thread Gemini pacing and bounded retries. Counts are local estimates.

Configure quota.rpm_by_model from AI Studio, not a presumed free-tier allowance.
All keys share one conservative local project bucket unless project is configured.
Only generation requests are retried here; tool side effects are never replayed.
"""
import asyncio
import json
import random
import threading
import time
from collections import defaultdict
from core.execution import ExecutionError


class QuotaError(ExecutionError):
    outcome = 'quota'


_lock = threading.Lock()
_next = defaultdict(float)
_usage = defaultdict(lambda: {'requests': 0, 'tokens': 0, 'models': {}})


def usage(mission):
    with _lock:
        return json.loads(json.dumps(_usage[mission]))


def classify(exc):
    """Read structured quota metrics when present; unknown 429 is not 'daily'."""
    payload = getattr(exc, 'response_json', None) or {}
    if not isinstance(payload, dict): payload = {}
    error = payload.get('error', payload)
    if not isinstance(error, dict): error = {}
    code = getattr(exc, 'code', None) or error.get('code')
    details = error.get('details', [])
    metrics = []
    retry = None
    for detail in details if isinstance(details, list) else []:
        if not isinstance(detail, dict): continue
        for violation in detail.get('violations', []):
            metrics.append(str(violation.get('quotaId', '')) + ' ' + str(violation.get('quotaMetric', '')))
        delay = detail.get('retryDelay')
        if isinstance(delay, str):
            try: retry = max(0, float(delay.removesuffix('s')))
            except ValueError: pass
    text = ' '.join(metrics).lower()
    if str(code) == '429' or '429' in str(exc) or 'resource_exhausted' in str(exc).lower():
        kind = 'daily' if any(x in text for x in ('perday', 'per_day', '/day')) else 'tokens/minute' if 'token' in text else 'requests/minute' if any(x in text for x in ('perminute', 'per_minute')) else 'unknown quota'
        return kind, retry
    if str(code) in ('500', '502', '503', '504'): return 'transient', retry
    return None, None


async def generate(client, *, quota_config=None, **kwargs):
    if quota_config is None:
        from config import load_config
        quota_config = load_config()
    config = quota_config
    cfg = config.get('quota', {})
    model = kwargs['model'].removeprefix('models/')
    bucket = (cfg.get('project', 'default-project'), model)
    rpm = float(cfg.get('rpm_by_model', {}).get(model, cfg.get('default_rpm', 10)))
    if rpm <= 0: raise ValueError('quota RPM must be positive')
    mission = config.get('_quota_mission', 'background')
    limit = int(cfg.get('max_requests_per_mission', 60))
    retries = max(0, min(3, int(cfg.get('max_retries', 2))))
    for attempt in range(retries + 1):
        while True:
            with _lock:
                now = time.monotonic()
                delay = _next[bucket] - now
                if delay <= 0:
                    if mission != 'background' and _usage[mission]['requests'] >= limit:
                        raise QuotaError('Local mission request budget reached; inspect saved evidence before continuing.')
                    _next[bucket] = now + 60 / rpm
                    _usage[mission]['requests'] += 1
                    counts = _usage[mission]['models']
                    counts[model] = counts.get(model, 0) + 1
                    break
            await asyncio.sleep(min(delay, 1))
        try:
            result = await client.aio.models.generate_content(**kwargs)
            tokens = getattr(getattr(result, 'usage_metadata', None), 'total_token_count', 0)
            with _lock:
                if isinstance(tokens, int): _usage[mission]['tokens'] += tokens
            return result
        except Exception as exc:
            kind, retry = classify(exc)
            if kind is None: raise
            # Daily exhaustion cannot be fixed by quick retries or rotating keys.
            if kind == 'daily' or attempt == retries:
                raise QuotaError(f'Gemini {model}: {kind} limit/error. Execution stopped without replaying tools; check AI Studio and completed evidence.') from exc
            delay = max(retry or 0, 2 ** attempt + random.random())
            if delay > float(cfg.get('max_retry_wait_s', 60)):
                raise QuotaError(f'Gemini {model}: {kind}; retry requested after {delay:g}s. Resume only after checking completed evidence.') from exc
            with _lock:
                _next[bucket] = max(_next[bucket], time.monotonic() + delay)
