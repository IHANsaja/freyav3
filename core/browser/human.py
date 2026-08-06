"""
The motion layer — makes Freya's browsing look like a person, not a script.

Every primitive here exists because the naive Playwright equivalent is a tell.
`page.click(sel)` teleports the cursor and fires instantly; `page.fill()` sets a
value with no keystrokes at all; `mouse.wheel(0, 2000)` jumps the viewport a
screenful in one frame. Sites fingerprint exactly that. More importantly for
Freya, it's not what the user asked for: he wants her to *use* the browser, not
puppeteer it.

So: the cursor travels a curved path at a varying speed, keys land with
per-character rhythm, scrolling accelerates and settles, and she pauses to read
in proportion to how much there is to read.

All timings are jittered — the giveaway of a bot is not being slow, it's being
exactly as slow every time.
"""

import asyncio
import math
import random


# ── Timing helpers ─────────────────────────────────────────────────────────
def jitter(base: float, spread: float = 0.35) -> float:
    """A duration near `base`, never negative. Spread is fractional (0.35 = ±35%)."""
    return max(0.01, random.gauss(base, base * spread))


async def pause(base: float, spread: float = 0.35):
    await asyncio.sleep(jitter(base, spread))


async def think(scale: float = 1.0):
    """The beat between deciding and acting. People don't act on a page the
    instant it renders — they orient first."""
    await pause(0.45 * scale, 0.5)


async def read(text_len: int, wpm: int = 700):
    """Dwell as if actually reading. Capped: she skims, she doesn't study.

    700 wpm is deliberately faster than a human reader — Freya only needs the
    dwell to be plausible and non-uniform, not to genuinely re-read the page.
    """
    words = max(1, text_len / 5.5)
    seconds = min(4.0, (words / wpm) * 60.0)
    await pause(max(0.3, seconds), 0.4)


# ── Mouse ──────────────────────────────────────────────────────────────────
def _bezier(p0, p1, p2, p3, t: float):
    """Cubic Bezier point at t. Hand movement arcs; it does not travel in a
    straight line, and straight lines are the single easiest bot tell there is."""
    u = 1 - t
    return (
        u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
        u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
    )


def _ease(t: float) -> float:
    """Ease-in-out: accelerate away from the start, decelerate into the target.
    Real pointing motion follows Fitts's law — fast ballistic phase, slow
    corrective phase near the target."""
    return 3 * t * t - 2 * t * t * t


class Cursor:
    """Tracks where the pointer 'is' so each move starts from the last position.

    Playwright's mouse has no readable position, and starting every move from
    (0,0) would be as unnatural as teleporting.
    """

    def __init__(self, mouse, viewport: tuple[int, int] = (1280, 800)):
        self.mouse = mouse
        self.x = random.uniform(viewport[0] * 0.3, viewport[0] * 0.7)
        self.y = random.uniform(viewport[1] * 0.3, viewport[1] * 0.7)

    async def move_to(self, x: float, y: float, speed: float = 1.0):
        """Glide to (x, y) along an arc, in steps sized by distance."""
        dist = math.hypot(x - self.x, y - self.y)
        if dist < 2:
            self.x, self.y = x, y
            return

        # Control points pushed perpendicular to the path — the further the
        # travel, the wider the arc a hand naturally makes.
        bow = min(dist * 0.22, 180) * random.choice((-1, 1))
        mx, my = (self.x + x) / 2, (self.y + y) / 2
        nx, ny = -(y - self.y) / dist, (x - self.x) / dist
        c1 = (mx + nx * bow * 0.6 + random.uniform(-12, 12),
              my + ny * bow * 0.6 + random.uniform(-12, 12))
        c2 = (mx + nx * bow + random.uniform(-12, 12),
              my + ny * bow + random.uniform(-12, 12))

        steps = max(8, min(38, int(dist / 14)))
        start = (self.x, self.y)
        for i in range(1, steps + 1):
            t = _ease(i / steps)
            px, py = _bezier(start, c1, c2, (x, y), t)
            # Sub-pixel tremor. Hands are not stable.
            px += random.uniform(-0.6, 0.6)
            py += random.uniform(-0.6, 0.6)
            await self.mouse.move(px, py)
            await asyncio.sleep(jitter(0.010 / speed, 0.5))

        self.x, self.y = x, y

    async def click_at(self, x: float, y: float, double: bool = False):
        await self.move_to(x, y)
        # Settle before pressing — people land on a target, then commit.
        await pause(0.09, 0.6)
        await self.mouse.down()
        await pause(0.055, 0.5)   # dwell time of a real button press
        await self.mouse.up()
        if double:
            await pause(0.08, 0.4)
            await self.mouse.down()
            await pause(0.05, 0.5)
            await self.mouse.up()

    async def drift(self):
        """A small aimless movement. People's hands wander while they read."""
        if random.random() < 0.5:
            return
        await self.move_to(self.x + random.uniform(-90, 90),
                           self.y + random.uniform(-70, 70), speed=0.7)


# ── Keyboard ───────────────────────────────────────────────────────────────
# Keys physically near each other on QWERTY — used for realistic typos.
_NEIGHBOURS = {
    "a": "qsz", "b": "vgn", "c": "xdv", "d": "sfe", "e": "wrd", "f": "dgr",
    "g": "fht", "h": "gjy", "i": "uok", "j": "hkn", "k": "jlm", "l": "k;o",
    "m": "nk", "n": "bmj", "o": "ipl", "p": "ol", "q": "wa", "r": "etf",
    "s": "adw", "t": "ryg", "u": "yih", "v": "cfb", "w": "qes", "x": "zsc",
    "y": "tuh", "z": "asx",
}


async def type_like_human(keyboard, text: str, typo_rate: float = 0.0):
    """Send `text` one key at a time with human rhythm.

    Rhythm rules that matter: a space is a micro-rest, punctuation is a longer
    one, and roughly one keystroke in twenty stalls entirely (thinking, or
    glancing at the screen). `typo_rate` > 0 makes her mistype and correct with
    backspace — off by default, since a typo in a search box costs a real result.
    """
    for ch in text:
        if typo_rate and ch.lower() in _NEIGHBOURS and random.random() < typo_rate:
            wrong = random.choice(_NEIGHBOURS[ch.lower()])
            await keyboard.type(wrong.upper() if ch.isupper() else wrong)
            await pause(0.18, 0.4)          # the moment of noticing
            await keyboard.press("Backspace")
            await pause(0.12, 0.4)

        await keyboard.type(ch)

        if ch == " ":
            delay = 0.055
        elif ch in ".,!?;:":
            delay = 0.16
        else:
            delay = 0.075
        if random.random() < 0.05:
            delay += random.uniform(0.15, 0.5)  # a beat of thought mid-phrase
        await asyncio.sleep(jitter(delay, 0.45))


# ── Scrolling ──────────────────────────────────────────────────────────────
async def scroll_like_human(mouse, total: int, steps: int | None = None):
    """Wheel `total` pixels in accelerating-then-settling increments.

    A trackpad flick is many small deltas over ~300ms, not one jump. Rendering
    also needs those frames — a single huge delta lands before lazy-loaded
    content exists, so the page Freya then reads is half empty.
    """
    if total == 0:
        return
    direction = 1 if total > 0 else -1
    remaining = abs(total)
    steps = steps or max(4, min(14, remaining // 90))

    for i in range(steps):
        # Bell-shaped profile: slow, fast, slow.
        weight = math.sin(math.pi * (i + 0.5) / steps)
        delta = max(18, int((remaining / steps) * weight * 1.55))
        delta = min(delta, remaining)
        await mouse.wheel(0, delta * direction)
        remaining -= delta
        if remaining <= 0:
            break
        await asyncio.sleep(jitter(0.045, 0.5))

    # Momentum settle — the small overshoot correction a real scroll makes.
    if random.random() < 0.35:
        await asyncio.sleep(jitter(0.12, 0.4))
        await mouse.wheel(0, -direction * random.randint(12, 45))
