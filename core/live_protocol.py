"""Model routing and state rules for Gemini Live; no audio-device dependencies."""
from config.models import LIVE_MODEL, LIVE_FALLBACK_MODEL, THINKING_LIVE_MODEL


class ModeChange(Exception):
    """Reconnect with the new mode while retaining the runner's transcript."""


def is_thinking(model):
    return model.removeprefix('models/') == THINKING_LIVE_MODEL


def setup_options(model, config):
    """Never send thinking settings to regular 3.8 Live or the legacy fallback."""
    if not is_thinking(model):
        return {}
    mode = config.get('modes', {}).get(config.get('active_mode', 'default'), {})
    level = str(mode.get('thinking_level', config.get('live', {}).get('thinking_level', 'high'))).lower()
    if level not in ('low', 'medium', 'high'):
        raise ValueError('Complex Tasks thinking_level must be low, medium, or high')
    return {'thinking_config': {'thinking_level': level.upper()}}


def tool_behavior(model):
    if is_thinking(model):
        return 'NON_BLOCKING'
    if model.removeprefix('models/') == LIVE_MODEL:
        return 'BLOCKING'
    return None  # Preserve the 3.1 tool protocol.


class LiveRoute:
    """Bounded fallback, sticky until the user changes selection or starts again."""
    def __init__(self, desired, config):
        self.desired = None
        self.configure(desired, config)

    def configure(self, desired, config):
        if desired == self.desired:
            return
        self.desired = desired
        primary = desired.removeprefix('models/')
        fallback = config.get('live', {}).get('fallback_model', LIVE_FALLBACK_MODEL)
        candidates = [desired]
        if primary == THINKING_LIVE_MODEL:
            candidates.append(LIVE_MODEL)
        if primary in (LIVE_MODEL, THINKING_LIVE_MODEL) and fallback:
            candidates.append(fallback)
        self.models = list(dict.fromkeys(m.removeprefix('models/') for m in candidates))
        self.index = 0

    @property
    def model(self):
        return self.models[self.index]

    def fallback(self, exc):
        # Authentication, malformed setup and arbitrary local tool errors do not
        # become silent model downgrades. 1008 alone is not a rotation either.
        text = str(exc).lower()
        code = getattr(exc, 'code', None) or getattr(exc, 'status_code', None)
        eligible = code in (404, 429, 500, 502, 503, 504) or any(s in text for s in (
            'resource_exhausted', 'quota exceeded', 'rate limit', 'model not found',
            'model is not available', 'model unavailable', 'service unavailable',
            'overloaded', 'not found for api version',
        ))
        if eligible and self.index + 1 < len(self.models):
            self.index += 1
            return self.model
        return None


class Interaction:
    """Speech completion and reasoning completion are independent in 3.8 Thinking."""
    def __init__(self, extended):
        self.extended = extended
        self.idle = True
        self.utterance_complete = True

    def update(self, message):
        sc = getattr(message, 'server_content', None)
        status = getattr(message, 'interaction_status', None) or getattr(sc, 'interaction_status', None)
        if status is not None:
            status = getattr(status, 'value', status)
            if status in ('IDLE', 'IN_PROGRESS'):
                self.idle = status == 'IDLE'
        if getattr(message, 'tool_call', None):
            self.idle = False
        if sc is not None:
            if getattr(sc, 'model_turn', None) or getattr(sc, 'output_transcription', None):
                self.utterance_complete = False
                if status != 'IDLE':
                    self.idle = False
            if getattr(sc, 'turn_complete', False) or getattr(sc, 'interrupted', False):
                self.utterance_complete = True
                if not self.extended:
                    self.idle = True

    def state_after_playback(self):
        return 'listening' if self.idle else 'thinking'


def routing_instruction(config, actual_model):
    mode = config.get('active_mode', 'default')
    auto = config.get('live', {}).get('auto_complex_mode', True)
    if not auto:
        rule = 'Change modes only when the user asks.'
    elif mode == 'complex_tasks':
        rule = ('Finish the current task before switching again. After reporting the final result, '
                'call switch_mode(default) unless the user explicitly asked to stay in Complex Tasks mode. '
                'Do not switch back while a mission, approval or tool result is still pending.')
    else:
        rule = ('Before starting a task requiring multi-step reasoning, difficult debugging, architecture, '
                'or comparing and verifying research, call switch_mode(complex_tasks). '
                'Do not ask permission merely to change reasoning mode. Retain the exact goal and constraints. '
                'Simple commands, casual conversation and straightforward lookups stay in the current mode. '
                'Respect a user request to remain in their chosen mode.')
    return (f'LIVE ROUTING: Active mode is {mode}; actual connected model is {actual_model}. {rule} '
            'Complex Tasks is a voice reasoning mode, not a replacement for start_mission or existing task tools. '
            'When already in Complex Tasks, do not switch into it again, including if its model is using a fallback. '
            'Never claim a model upgrade until the switch tool succeeds.')
