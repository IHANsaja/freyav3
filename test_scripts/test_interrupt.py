import asyncio
import sys

async def dummy_run():
    print("Running...")
    try:
        while True:
            await asyncio.sleep(0.1)
    except asyncio.CancelledError:
        print("dummy_run: CancelledError caught")
        raise

async def do_async_cleanup():
    print("Starting async cleanup...")
    await asyncio.sleep(0.5)
    print("Async cleanup finished!")

async def trigger_interrupt():
    await asyncio.sleep(0.5)
    print("Triggering KeyboardInterrupt...")
    # Raise KeyboardInterrupt in the main thread
    import _thread
    _thread.interrupt_main()

async def main():
    # Schedule KeyboardInterrupt
    asyncio.create_task(trigger_interrupt())
    try:
        await dummy_run()
    finally:
        print("finally: Starting cleanup")
        try:
            await do_async_cleanup()
        except Exception as e:
            print("finally: Exception during async cleanup:", type(e), e)
        except BaseException as be:
            print("finally: BaseException during async cleanup:", type(be), be)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("KeyboardInterrupt caught in __main__")
