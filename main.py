import asyncio
from config import load_config, get_api_key, get_memory_api_key, get_active_voice, get_personality
from config import get_mode_personality, get_mode_model  # ← add these
from core.audio import MicStream, SpeakerStream
from core.model import FreyaModel, is_rotation
from core.memory import load_memory, build_system_prompt, update_memory, TranscriptCollector

config = load_config()
api_key = get_api_key()
model_id = get_mode_model(config)          # ← was get_active_model(config)
voice = get_active_voice(config)
base_personality = get_personality(config)

input_idx = config["audio"]["input_device_index"]
output_idx = config["audio"]["output_device_index"]

async def main():
    global config, api_key, model_id, voice, base_personality
    memory = load_memory(config)
    personality = build_system_prompt(get_mode_personality(config, base_personality), memory)  # ← was just base_personality
    transcript = TranscriptCollector()

    mic = MicStream(device_index=input_idx)
    speaker = SpeakerStream(device_index=output_idx)

    mic.start()
    speaker.start()

    # Learn the machine on first run (or refresh a stale index). Runs on its own
    # thread so a cold start still reaches "Freya is live" immediately — the
    # index fills in behind her while she's already talking.
    try:
        from core.machine_index import ensure_index
        ensure_index(config)
    except Exception as e:
        print(f"  Machine index unavailable: {e}")

    # Desktop popups — the console path has no dashboard at all, so this is the
    # only surface `show_info` / `show_image` have here.
    try:
        from core import desktop_popup
        desktop_popup.attach_to_bus(config)
    except Exception as e:
        print(f"  Desktop popups unavailable: {e}")

    consecutive_failures = 0
    max_reconnect_attempts = 5
    resume_handle = None

    try:
        while True:
            freya = FreyaModel(
                api_key=api_key,
                model_id=model_id,
                voice=voice,
                personality=personality,
                config=config,
                transcript=transcript,
                resume_handle=resume_handle,
            )
            try:
                await freya.run(mic, speaker)
                break
            except KeyboardInterrupt:
                break
            except Exception as e:
                # Carry the conversation forward whatever went wrong.
                resume_handle = freya.resume_handle

                if is_rotation(e):
                    # Expected lifecycle event, not a fault: don't spend the
                    # failure budget and don't make the user wait 2-10 seconds.
                    print("🔄 Rotating session (context preserved)...")
                    await asyncio.sleep(0.5)
                else:
                    consecutive_failures += 1
                    print(f"\n⚠️ Freya session error (attempt {consecutive_failures}/{max_reconnect_attempts}): {e}")
                    if consecutive_failures >= max_reconnect_attempts:
                        print("❌ Max reconnect attempts reached. Exiting.")
                        break
                    print(f"🔄 Reconnecting in {2 * consecutive_failures} seconds...")
                    await asyncio.sleep(2 * consecutive_failures)

                # Reload config and keys
                config = load_config()
                api_key = get_api_key()
                model_id = get_mode_model(config)
                voice = get_active_voice(config)
                base_personality = get_personality(config)
                personality = build_system_prompt(get_mode_personality(config, base_personality), memory)
    finally:
        mic.stop()
        speaker.stop()
        try:
            from core.mcp_client import mcp_manager
            await mcp_manager.stop()
        except Exception:
            pass
        try:
            from core.browser.driver import shutdown_browser
            shutdown_browser()
        except Exception:
            pass
        try:
            from core import desktop_popup
            desktop_popup.shutdown()
        except Exception:
            pass
        memory_key = get_memory_api_key()
        await update_memory(memory_key, transcript.get(), memory)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Freya stopped manually.")