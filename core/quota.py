"""Cross-thread Gemini pacing and bounded retries. Counts are local estimates.

Configure quota.rpm_by_model / tpm_by_model / rpd_by_model from AI Studio
(https://aistudio.google.com/rate-limit), not a presumed free-tier allowance:
Google does not publish fixed free-tier numbers and they differ per project.
All keys share one conservative local project bucket unless project is configured,
because Gemini limits apply per project, not per API key.
Only generation requests are retried here; tool side effects are never replayed.

What is paced, per (project, model):
  - requests per minute: one request every 60/RPM seconds
  - input tokens per minute: a rolling 60 s window. Each request reserves its
    estimated input tokens before it is sent, and the reservation is replaced by
    the exact prompt_token_count the response reports. TPM counts input tokens
    only, and system instructions and tool declarations are part of that input.
  - requests per day: counted per Pacific day (the reset is midnight Pacific)
    and kept on disk across restarts. A model whose daily quota ran out is
    skipped straight to its fallback until the reset, instead of spending a
    request on every call just to be refused again.
"""
import asyncio
import json
import os
import random
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from core.execution import ExecutionError


class QuotaError(ExecutionError):
    outcome = 'quota'


_lock = threading.Lock()
_next = defaultdict(float)
_usage = defaultdict(lambda: {'requests': 0, 'tokens': 0, 'input_tokens': 0, 'cached_tokens': 0,
                              'output_tokens': 0, 'thought_tokens': 0, 'models': {}})
_tpm = defaultdict(deque)   # bucket -> deque of [sent_at, input_tokens]
_daily = {}                 # "project|model" -> {"requests": n, "exhausted": bool}
_daily_day = None           # Pacific date the _daily counts belong to
_daily_loaded = False
_STATE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'memory', 'quota_state.json')

# Used only when a model has no tpm_by_model entry. Conservative on purpose:
# set your real limit from AI Studio to go faster.
DEFAULT_TPM = 200_000
_TOKENS_PER_MEDIA_PART = 1000   # images / documents: a rough, generous estimate


def reset():
    """Forget all pacing and counters (tests)."""
    global _daily_day, _daily_loaded
    with _lock:
        _next.clear(); _usage.clear(); _tpm.clear(); _daily.clear()
        _daily_day = None
        _daily_loaded = False


def usage(mission):
    with _lock:
        return json.loads(json.dumps(_usage[mission]))


# -- Pacific day (daily quotas reset at midnight Pacific time) ---------------

def _pacific_now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('America/Los_Angeles'))
    except Exception:
        # No tz database (some Windows Pythons without tzdata): apply the US
        # rule directly - DST from the second Sunday of March to the first
        # Sunday of November.
        utc = datetime.now(timezone.utc)
        year = utc.year
        march = datetime(year, 3, 8, 10, tzinfo=timezone.utc)      # 2 am PST
        dst_start = march + timedelta(days=(6 - march.weekday()) % 7)
        november = datetime(year, 11, 1, 9, tzinfo=timezone.utc)   # 2 am PDT
        dst_end = november + timedelta(days=(6 - november.weekday()) % 7)
        offset = -7 if dst_start <= utc < dst_end else -8
        return utc.astimezone(timezone(timedelta(hours=offset)))


def pacific_day():
    return _pacific_now().date().isoformat()


def seconds_until_reset():
    now = _pacific_now()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(0, int((midnight - now).total_seconds()))


def _roll_day():
    """Load the saved counts once, and start fresh when the Pacific day changes.
    Call with _lock held."""
    global _daily_day, _daily_loaded
    today = pacific_day()
    if not _daily_loaded:
        _daily_loaded = True
        try:
            with open(_STATE_PATH, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            if saved.get('day') == today:
                _daily.update(saved.get('models', {}))
                _daily_day = today
        except (OSError, ValueError):
            pass
    if _daily_day != today:
        _daily.clear()
        _daily_day = today


def _save_daily():
    """Persist today's counts. Call with _lock held; failures are not fatal."""
    try:
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        tmp = _STATE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'day': _daily_day, 'models': _daily}, f)
        os.replace(tmp, _STATE_PATH)
    except OSError:
        pass


def daily_state(project, model):
    with _lock:
        _roll_day()
        return dict(_daily.get(f'{project}|{model}', {'requests': 0, 'exhausted': False}))


def _daily_blocked(cfg, project, model):
    """Why this model cannot take more requests today, or None. _lock held."""
    _roll_day()
    entry = _daily.get(f'{project}|{model}', {})
    if entry.get('exhausted'):
        return 'daily quota used up'
    rpd = int(cfg.get('rpd_by_model', {}).get(model, cfg.get('default_rpd', 0)) or 0)
    if rpd > 0 and entry.get('requests', 0) >= rpd:
        return f'local daily budget of {rpd} requests reached'
    return None


# -- Token estimates ---------------------------------------------------------

def _dump(value):
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)


def _part_tokens(part):
    if isinstance(part, str):
        return len(part) // 4
    if isinstance(part, dict):
        return len(_dump(part)) // 4
    tokens = 0
    text = getattr(part, 'text', None)
    if text:
        tokens += len(text) // 4
    call = getattr(part, 'function_call', None)
    if call is not None:
        tokens += (len(_dump(dict(getattr(call, 'args', None) or {}))) + len(getattr(call, 'name', '') or '')) // 4 + 8
    response = getattr(part, 'function_response', None)
    if response is not None:
        tokens += len(_dump(getattr(response, 'response', None) or {})) // 4 + 8
    if getattr(part, 'inline_data', None) is not None or getattr(part, 'file_data', None) is not None:
        tokens += _TOKENS_PER_MEDIA_PART
    # thought_signature is opaque bytes; not counted as text here.
    return tokens


def _content_tokens(content):
    if isinstance(content, (str, dict)) or not hasattr(content, 'parts'):
        return _part_tokens(content)
    return sum(_part_tokens(p) for p in (content.parts or [])) + 4


def estimate_tokens(contents=None, config=None):
    """Rough input-token estimate (about 4 characters per token, the ratio
    Google documents) for contents + system instruction + tool declarations."""
    if contents is None:
        items = []
    elif isinstance(contents, (list, tuple)):
        items = contents
    else:
        items = [contents]
    tokens = sum(_content_tokens(c) for c in items)
    if config is not None:
        system = getattr(config, 'system_instruction', None)
        if system is not None:
            tokens += _content_tokens(system)
        for tool in getattr(config, 'tools', None) or []:
            for decl in getattr(tool, 'function_declarations', None) or []:
                try:
                    tokens += len(decl.model_dump_json(exclude_none=True)) // 4
                except Exception:
                    tokens += len(_dump(decl)) // 4
    return tokens


def _tpm_wait(bucket, tpm, estimate, now):
    """Seconds until `estimate` more tokens fit in the rolling minute. _lock held."""
    window = _tpm[bucket]
    while window and now - window[0][0] >= 60:
        window.popleft()
    used = sum(entry[1] for entry in window)
    # A single request larger than the whole budget can never fit; let the
    # server decide rather than wait forever.
    if used + estimate <= tpm or not window or estimate > tpm:
        return 0
    freed, wait = used, 0
    for sent_at, tokens in window:
        freed -= tokens
        wait = 60 - (now - sent_at)
        if freed + estimate <= tpm:
            break
    return max(wait, 0.05)


# -- Errors ------------------------------------------------------------------

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


def describe_failure(exc):
    """A plain sentence for the user about a quota failure, or None."""
    kind, _ = classify(exc)
    text = str(exc).lower()
    if kind == 'daily' or 'daily quota' in text or 'daily budget' in text:
        hours = max(1, round(seconds_until_reset() / 3600))
        return (f"Gemini's daily quota for this model is used up; it resets at midnight Pacific time, "
                f"in about {hours} hour{'s' if hours != 1 else ''}.")
    if kind in ('tokens/minute', 'requests/minute') or 'per minute' in text or '/minute' in text:
        return "Gemini's per-minute limit was hit; it clears within a minute, so try again shortly."
    if kind or 'quota' in text or '429' in text:
        return "Gemini refused the request for quota reasons; check your limits in AI Studio."
    return None


# -- Generation --------------------------------------------------------------

_DEFAULT_FALLBACKS = {'gemini-3.5-flash': 'gemini-3.5-flash-lite'}


def _fallback_model(cfg: dict, model: str):
    """quota.fallback_models overrides the default map; {} turns it off."""
    table = cfg.get('fallback_models', _DEFAULT_FALLBACKS)
    fallback = (table or {}).get(model)
    return fallback if fallback and fallback != model else None


def _record_response(mission, bucket, reservation, result):
    """Swap the token reservation for what the response actually reports."""
    meta = getattr(result, 'usage_metadata', None)

    def count(name):
        value = getattr(meta, name, None)
        return value if isinstance(value, int) else 0

    prompt = count('prompt_token_count')
    with _lock:
        if prompt:
            reservation[1] = prompt
        stats = _usage[mission]
        stats['tokens'] += count('total_token_count')
        stats['input_tokens'] += prompt
        stats['cached_tokens'] += count('cached_content_token_count')
        stats['output_tokens'] += count('candidates_token_count')
        stats['thought_tokens'] += count('thoughts_token_count')


async def generate(client, *, quota_config=None, _no_fallback=False, **kwargs):
    if quota_config is None:
        from config import load_config
        quota_config = load_config()
    config = quota_config
    cfg = config.get('quota', {})
    model = kwargs['model'].removeprefix('models/')
    project = cfg.get('project', 'default-project')
    bucket = (project, model)
    rpm = float(cfg.get('rpm_by_model', {}).get(model, cfg.get('default_rpm', 10)))
    if rpm <= 0: raise ValueError('quota RPM must be positive')
    tpm = float(cfg.get('tpm_by_model', {}).get(model, cfg.get('default_tpm', DEFAULT_TPM)))
    mission = config.get('_quota_mission', 'background')
    limit = int(cfg.get('max_requests_per_mission', 60))
    retries = max(0, min(3, int(cfg.get('max_retries', 2))))

    with _lock:
        blocked = _daily_blocked(cfg, project, model)
    if blocked:
        fallback = _fallback_model(cfg, model)
        if fallback and not _no_fallback:
            print(f'  [quota] {model}: {blocked} - using {fallback} until the reset.')
            return await generate(client, quota_config=config, _no_fallback=True,
                                  **{**kwargs, 'model': fallback})
        raise QuotaError(f'Gemini {model}: {blocked} (resets at midnight Pacific). '
                         'Execution stopped without replaying tools.')

    estimate = estimate_tokens(kwargs.get('contents'), kwargs.get('config'))
    for attempt in range(retries + 1):
        while True:
            with _lock:
                now = time.monotonic()
                delay = max(_next[bucket] - now, _tpm_wait(bucket, tpm, estimate, now))
                if delay <= 0:
                    if mission != 'background' and _usage[mission]['requests'] >= limit:
                        raise QuotaError('Local mission request budget reached; inspect saved evidence before continuing.')
                    _next[bucket] = now + 60 / rpm
                    reservation = [now, estimate]
                    _tpm[bucket].append(reservation)
                    _usage[mission]['requests'] += 1
                    counts = _usage[mission]['models']
                    counts[model] = counts.get(model, 0) + 1
                    key = f'{project}|{model}'
                    entry = _daily.setdefault(key, {'requests': 0, 'exhausted': False})
                    entry['requests'] = entry.get('requests', 0) + 1
                    _save_daily()
                    break
            await asyncio.sleep(min(delay, 1))
        try:
            result = await client.aio.models.generate_content(**kwargs)
            _record_response(mission, bucket, reservation, result)
            return result
        except Exception as exc:
            kind, retry = classify(exc)
            if kind is None: raise
            if kind == 'daily':
                # Remember it until the reset, so later calls skip this model
                # instead of spending a request each just to be refused.
                with _lock:
                    _daily.setdefault(f'{project}|{model}', {'requests': 0})['exhausted'] = True
                    _save_daily()
            # Daily exhaustion cannot be fixed by quick retries or rotating keys.
            if kind == 'daily' or attempt == retries:
                # A different model has its own quota and its own servers: an
                # overloaded or exhausted gemini-3.5-flash used to fail whole
                # missions and sub-agents while flash-lite was answering in 1.5 s.
                fallback = _fallback_model(cfg, model)
                if fallback and not _no_fallback:
                    print(f'  [quota] {model}: {kind} - retrying once on {fallback}.')
                    return await generate(client, quota_config=config,
                                          _no_fallback=True, **{**kwargs, 'model': fallback})
                raise QuotaError(f'Gemini {model}: {kind} limit/error. Execution stopped without replaying tools; check AI Studio and completed evidence.') from exc
            delay = max(retry or 0, 2 ** attempt + random.random())
            if delay > float(cfg.get('max_retry_wait_s', 60)):
                raise QuotaError(f'Gemini {model}: {kind}; retry requested after {delay:g}s. Resume only after checking completed evidence.') from exc
            with _lock:
                _next[bucket] = max(_next[bucket], time.monotonic() + delay)
