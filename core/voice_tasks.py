"""Keep a voice connection's workers within that connection's lifetime."""
import asyncio


async def run_voice_tasks(*workers):
    tasks = [asyncio.create_task(worker) for worker in workers]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
