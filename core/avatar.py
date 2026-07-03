"""
Avatar animation controller — the tool surface that lets Freya animate her own body.

The LLM decides the *intent* (an emotion to show, a gesture to punctuate a sentence,
an idle posture); the frontend AvatarController turns intents into actual animation:
GLB clip crossfades, procedural bone motion, and shader-core accents. These handlers
therefore do no animation work themselves — each one just publishes an `avatar` event
and returns instantly, so they're safe to call from the live audio loop.

Base states (listening/speaking/thinking/working) are driven automatically by session
state and mission events with zero LLM involvement; these tools layer expressiveness
on top.
"""

import random

from core.registry import register, tool, OBJ, P, STR, NUM

EXPRESSIONS = ["joyful", "warm", "playful", "focused", "stern", "curious", "calm", "alert"]
GESTURES = ["emphasize", "wave_off", "show_off", "celebrate", "conjure", "admire", "groove"]
IDLE_STATES = ["standing", "seated", "attentive"]
TRANSITIONS = ["walk", "run", "flourish"]


async def _emit(ctx, payload: dict) -> None:
    await ctx.emit("avatar", payload)


@tool(
    "set_expression",
    "Set your avatar's emotional expression so your body language matches your words. "
    "Use sparingly at genuine emotional beats, not every sentence.",
    OBJ({"expression": P(STR, "Your avatar's expression", enum=EXPRESSIONS),
         "intensity": P(NUM, "0.0-1.0, default 0.7")},
        ["expression"]),
)
async def set_expression(args, ctx) -> str:
    name = str(args.get("expression", "")).lower().strip()
    if name not in EXPRESSIONS:
        return f"Unknown expression '{name}'. Use one of: {', '.join(EXPRESSIONS)}."
    intensity = max(0.0, min(1.0, float(args.get("intensity", 0.7))))
    await _emit(ctx, {"intent": "expression", "name": name, "intensity": intensity})
    return f"Expression set to {name}."


@tool(
    "set_gesture",
    "Play a one-shot body gesture on your avatar to punctuate what you're saying. "
    "It plays once and returns to your current pose.",
    OBJ({"gesture": P(STR, "The gesture to play", enum=GESTURES)}, ["gesture"]),
)
async def set_gesture(args, ctx) -> str:
    name = str(args.get("gesture", "")).lower().strip()
    if name not in GESTURES:
        return f"Unknown gesture '{name}'. Use one of: {', '.join(GESTURES)}."
    await _emit(ctx, {"intent": "gesture", "name": name})
    return f"Playing the {name} gesture."


@tool(
    "set_idle_state",
    "Change your avatar's resting posture. States: standing (default), seated "
    "(relaxed night-time presence), attentive (leaning in, focused on Ihan).",
    OBJ({"state": P(STR, "The idle posture", enum=IDLE_STATES)}, ["state"]),
)
async def set_idle_state(args, ctx) -> str:
    name = str(args.get("state", "")).lower().strip()
    if name not in IDLE_STATES:
        return f"Unknown idle state '{name}'. Use one of: {', '.join(IDLE_STATES)}."
    await _emit(ctx, {"intent": "idle", "name": name})
    return f"Idle posture set to {name}."


@tool(
    "trigger_emphasis",
    "Quick emphasis beat: your avatar raises a hand and the core flares briefly. "
    "Use when making an important point.",
)
async def trigger_emphasis(args, ctx) -> str:
    await _emit(ctx, {"intent": "emphasis", "name": "emphasize"})
    return "Emphasis triggered."


@tool(
    "trigger_thinking",
    "Show that you're pondering: thoughtful pose, tilted head, dimmed core. "
    "Auto-clears when you next speak.",
)
async def trigger_thinking(args, ctx) -> str:
    await _emit(ctx, {"intent": "state", "name": "thinking"})
    return "Thinking pose on."


@tool(
    "trigger_listening",
    "Snap back to an attentive listening pose focused on Ihan.",
)
async def trigger_listening(args, ctx) -> str:
    await _emit(ctx, {"intent": "state", "name": "listening"})
    return "Listening pose on."


@tool(
    "animate_transition",
    "Play a dramatic transition animation (persona/mode changes, big reveals).",
    OBJ({"style": P(STR, "Transition style (default flourish)", enum=TRANSITIONS)}),
)
async def animate_transition(args, ctx) -> str:
    style = str(args.get("style", "flourish")).lower().strip()
    if style not in TRANSITIONS:
        style = "flourish"
    await _emit(ctx, {"intent": "gesture", "name": f"transition_{style}"})
    return f"Transition ({style}) playing."


# ── dance_for_user override ────────────────────────────────────────────────
# The legacy tool returned "DANCING:<clip>" and the frontend regex-matched the
# result string — brittle and invisible to the CLI. This handler-only override
# (decl=None keeps the static declaration in model.py) emits a real avatar
# event instead; the frontend picks the clip from its model manifest.

async def _dance_for_user(args, ctx) -> str:
    duration = int(args.get("duration_s", 10)) if isinstance(args, dict) else 10
    await _emit(ctx, {"intent": "state", "name": "dance",
                      "durationMs": max(3, min(60, duration)) * 1000})
    return random.choice([
        "Dancing for you now — watch the stage!",
        "Alright, hitting the floor. Eyes on me.",
        "One dance, coming right up.",
    ])

register("dance_for_user", _dance_for_user, decl=None)
