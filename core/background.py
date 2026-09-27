"""
Two loops, one process — keeping heavy background work off the voice path.

The problem
-----------
Freya's realtime voice session is a set of coroutines (mic capture, playback
scheduling, the receive stream, the tool executor) sharing one event loop. Any
other coroutine placed on that loop competes with them, and anything that blocks
inside an `async def` — a browser driver, PyAutoGUI, UI-Automation, a synchronous
HTTP client — stalls the loop outright and the user hears it as Freya going deaf
mid-sentence.

Two powers were doing exactly that:

  • Missions ran `asyncio.create_task(self._run(...))` on the live session's loop,
    so the planner call, every ReAct step, every tool and every verification ran
    shoulder to shoulder with the audio coroutines.
  • Sub-agents *looked* isolated — each gets its own thread and loop — but every
    tool call was marshalled straight back to the voice loop through
    `ctx.owner_loop`, which put the expensive half of the work back where it
    started.

The shape of the fix
--------------------
One long-lived background loop on its own thread runs all of it. Only the things
that genuinely belong to the live session go back to the main loop:

  • `runtime.inject` — touches `FreyaModel.session` and an asyncio.Lock created
    on the main loop.
  • the event bus — subscribers are per-client WebSocket queues bound to the
    server's loop; `put_nowait` from another thread is not safe.
  • approval futures — created on one loop and resolved by a click or a spoken
    "yes" arriving on the other.

`on_main(coro)` is the single door for all three. It is a no-op hop when the
caller is already on the main loop, so the same code path works from either side
and callers never have to know where they are running.
"""

import asyncio
import atexit
import threading

_bg_loop: asyncio.AbstractEventLoop | None = None
_bg_thread: threading.Thread | None = None
_bg_lock = threading.Lock()

_main_loop: asyncio.AbstractEventLoop | None = None


# ── The main (voice/server) loop ──────────────────────────────────────────

def set_main_loop(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Record the loop that owns the live session and the dashboard sockets."""
    global _main_loop
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
    _main_loop = loop


def main_loop() -> asyncio.AbstractEventLoop | None:
    return _main_loop


def on_main_loop() -> bool:
    """True when the caller is already running on the main loop."""
    if _main_loop is None:
        return True  # nothing else registered; treat here as home
    try:
        return asyncio.get_running_loop() is _main_loop
    except RuntimeError:
        return False


async def on_main(coro):
    """Await `coro` on the main loop, from whichever loop is calling.

    Already on the main loop → awaited directly, no hop. No main loop has been
    registered (unit tests, CLI scripts) → also awaited directly, so this is
    never a hard dependency on a running session.
    """
    if on_main_loop() or _main_loop is None or _main_loop.is_closed():
        return await coro
    return await asyncio.wrap_future(
        asyncio.run_coroutine_threadsafe(coro, _main_loop)
    )


def call_on_main(coro) -> None:
    """Fire-and-forget `coro` on the main loop. Never raises, never blocks.

    For sync callers and for paths where the result genuinely does not matter
    (status events, avatar intents). If the coroutine is dropped it is closed so
    Python doesn't warn about it never being awaited.
    """
    loop = _main_loop
    if loop is None or loop.is_closed():
        coro.close()
        return
    try:
        if on_main_loop():
            loop.create_task(coro)
        else:
            asyncio.run_coroutine_threadsafe(coro, loop)
    except Exception as e:
        coro.close()
        print(f"  [background] could not reach the main loop: {e}")


# ── The background loop ───────────────────────────────────────────────────

def loop() -> asyncio.AbstractEventLoop:
    """The shared background loop, started on first use."""
    global _bg_loop, _bg_thread
    with _bg_lock:
        if _bg_loop is not None and not _bg_loop.is_closed():
            return _bg_loop
        ready = threading.Event()

        def _run():
            global _bg_loop
            _bg_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_bg_loop)
            ready.set()
            _bg_loop.run_forever()

        _bg_thread = threading.Thread(target=_run, name="freya-background", daemon=True)
        _bg_thread.start()
        ready.wait(5)
        return _bg_loop


def spawn(coro):
    """Run `coro` on the background loop. Returns a concurrent.futures.Future.

    The future is the cancellation handle: `.cancel()` works across threads, so
    a mission started here can still be cancelled by a voice tool running on the
    main loop.
    """
    return asyncio.run_coroutine_threadsafe(coro, loop())


async def on_loop(loop: asyncio.AbstractEventLoop | None, coro):
    """Await `coro` on a specific loop, whoever is calling.

    Like `on_main`, but for a loop the caller captured itself rather than the
    globally registered one — useful when correct ordering has to hold before
    any session has claimed "main" (and in tests, which never register one).
    """
    if loop is None or loop.is_closed():
        return await coro
    try:
        if asyncio.get_running_loop() is loop:
            return await coro
    except RuntimeError:
        pass
    return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro, loop))


def spawn_awaitable(coro):
    """`spawn`, but the handle behaves like a Task on the CALLER's loop.

    Callers that want to `await` a background job (or `asyncio.gather` it) get an
    asyncio.Future chained to the background one. Cancelling either side
    cancels the other, so `mission.task.cancel()` still reaches the coroutine
    running on the other loop.
    """
    return asyncio.wrap_future(spawn(coro))


def shutdown() -> None:
    """Stop the background loop. Safe to call more than once."""
    global _bg_loop
    bg = _bg_loop
    if bg is None or bg.is_closed():
        return
    bg.call_soon_threadsafe(bg.stop)


atexit.register(shutdown)
