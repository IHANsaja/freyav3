"""Settings lists each real mic/speaker once and defaults to the Windows devices."""

import pytest

import config
from core import audio

MME, DSOUND, WASAPI, WDMKS = 0, 1, 2, 3


def dev(index, host, name, ins, outs):
    return {"index": index, "hostApi": host, "name": name,
            "maxInputChannels": ins, "maxOutputChannels": outs}


# A real laptop (2026-09-28): 31 PyAudio entries for 2 mics and 3 speakers.
LAPTOP = [
    dev(0, MME, "Microsoft Sound Mapper - Input", 2, 0),
    dev(1, MME, "Headset Microphone (Realtek(R) ", 2, 0),
    dev(2, MME, "Microphone Array (AMD Audio Dev", 2, 0),
    dev(3, MME, "Microsoft Sound Mapper - Output", 0, 2),
    dev(4, MME, "FxSound Speakers (FxSound Audio", 0, 8),
    dev(5, MME, "Headphone (Realtek(R) Audio)", 0, 2),
    dev(6, MME, "Speaker (Realtek(R) Audio)", 0, 2),
    dev(7, DSOUND, "Primary Sound Capture Driver", 2, 0),
    dev(8, DSOUND, "Headset Microphone (Realtek(R) Audio)", 2, 0),
    dev(9, DSOUND, "Microphone Array (AMD Audio Device)", 2, 0),
    dev(10, DSOUND, "Primary Sound Driver", 0, 2),
    dev(11, DSOUND, "FxSound Speakers (FxSound Audio Enhancer)", 0, 8),
    dev(12, DSOUND, "Headphone (Realtek(R) Audio)", 0, 2),
    dev(13, DSOUND, "Speaker (Realtek(R) Audio)", 0, 2),
    dev(14, WASAPI, "Headphone (Realtek(R) Audio)", 0, 2),
    dev(15, WASAPI, "FxSound Speakers (FxSound Audio Enhancer)", 0, 2),
    dev(16, WASAPI, "Speaker (Realtek(R) Audio)", 0, 2),
    dev(17, WASAPI, "Headset Microphone (Realtek(R) Audio)", 2, 0),
    dev(18, WASAPI, "Microphone Array (AMD Audio Device)", 2, 0),
    dev(19, WDMKS, "Speakers 1 (Realtek HD Audio output with HAP)", 0, 2),
    dev(22, WDMKS, "Microphone (Realtek HD Audio Mic input)", 2, 0),
    dev(23, WDMKS, "Stereo Mix (Realtek HD Audio Stereo input)", 2, 0),
]


def listed():
    return audio.filter_devices(LAPTOP, MME, default_in=1, default_out=4)


def test_only_real_devices_of_the_default_host_api():
    devices = listed()
    assert [d["index"] for d in devices["input"]] == [1, 2]
    assert [d["index"] for d in devices["output"]] == [4, 5, 6]


def test_truncated_mme_names_are_completed():
    names = [d["name"] for d in listed()["input"]]
    assert names == ["Headset Microphone (Realtek(R) Audio)", "Microphone Array (AMD Audio Device)"]
    assert listed()["output"][0]["name"] == "FxSound Speakers (FxSound Audio Enhancer)"


def test_windows_defaults_are_flagged():
    assert [d["default"] for d in listed()["input"]] == [True, False]
    assert [d["default"] for d in listed()["output"]] == [True, False, False]


@pytest.fixture
def devices(monkeypatch):
    state = {"list": listed()}
    monkeypatch.setattr(audio, "list_audio_devices", lambda: state["list"])
    return state


def test_unset_device_means_system_default(devices):
    assert audio.resolve_device(None, "input") is None


def test_saved_name_follows_the_device_when_windows_reorders(devices):
    # Saved as #5 "Headphone"; Windows then moves it to #4.
    devices["list"] = {"input": [], "output": [
        {"index": 4, "name": "Headphone (Realtek(R) Audio)", "default": True},
        {"index": 5, "name": "FxSound Speakers (FxSound Audio Enhancer)", "default": False},
    ]}
    assert audio.resolve_device(5, "output", "Headphone (Realtek(R) Audio)") == 4


def test_unplugged_named_device_falls_back_to_default(devices):
    assert audio.resolve_device(5, "output", "USB Headset", quiet=True) is None


@pytest.mark.parametrize("index", [0, 3, 17])  # Sound Mapper entries, a WASAPI duplicate
def test_legacy_index_of_hidden_entry_falls_back_to_default(devices, index):
    side = "output" if index == 3 else "input"
    assert audio.resolve_device(index, side, quiet=True) is None


def test_legacy_index_of_listed_device_is_kept(devices):
    assert audio.resolve_device(2, "input") == 2


def test_template_indexes_migrate_to_system_default():
    cfg = {"audio": {"input_device_index": 0, "output_device_index": 3}}
    assert config.migrate_audio_defaults(cfg)
    assert cfg["audio"]["input_device_index"] is None
    assert cfg["audio"]["output_device_index"] is None
    assert not config.migrate_audio_defaults(cfg)  # one-time


def test_user_choice_survives_migration():
    cfg = {"audio": {"input_device_index": 2, "output_device_index": 6}}
    config.migrate_audio_defaults(cfg)
    assert (cfg["audio"]["input_device_index"], cfg["audio"]["output_device_index"]) == (2, 6)
