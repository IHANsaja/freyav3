"""The personality customizer: styles pick models, sliders tune the prompt."""

import pytest

import config
from config import persona
from config.models import LIVE_FALLBACK_MODEL, LIVE_MODEL, THINKING_LIVE_MODEL
from core import user_identity


def base_config(**persona_fields):
    cfg = {"freya": {"personality": "BASE"}, "active_mode": "default",
           "modes": {"default": {"theme": {"accent": "#111111"}}, "coding": {"theme": {"accent": "#222222"}}}}
    if persona_fields:
        cfg["persona"] = persona_fields
    return cfg


def test_styles_map_to_the_three_live_models():
    assert persona.STYLES["friendly"]["model"] == LIVE_FALLBACK_MODEL
    assert persona.STYLES["quick"]["model"] == LIVE_MODEL
    assert persona.STYLES["focused"]["model"] == THINKING_LIVE_MODEL


def test_prompt_untouched_until_setup_is_done():
    assert config.get_personality(base_config()) == "BASE"
    assert config.get_personality(base_config(style="friendly")) == "BASE"


def test_prompt_block_follows_style_and_sliders():
    cfg = base_config(setup_done=True, style="focused",
                      traits={"warmth": 90, "humor": 0, "detail": 50, "initiative": 100},
                      note="Explain code simply.")
    text = config.get_personality(cfg)
    assert text.startswith("BASE\n\n[PERSONALITY TUNING")
    assert "Put the task first." in text
    assert persona.TRAITS["warmth"][3] in text      # high
    assert persona.TRAITS["humor"][1] in text       # low
    assert persona.TRAITS["detail"][2] in text      # middle
    assert persona.TRAITS["initiative"][3] in text  # high
    assert "Explain code simply." in text


def test_missing_sliders_fall_back_to_the_style_defaults():
    got = persona.get_persona(base_config(style="friendly", traits={"humor": 5}))
    assert got["traits"] == {**persona.STYLES["friendly"]["traits"], "humor": 5}
    assert persona.get_persona(base_config(style="nonsense"))["style"] == persona.DEFAULT_STYLE


def test_accent_applies_to_default_mode_only():
    cfg = base_config(setup_done=True, accent="#e0559a")
    assert config.get_mode_theme(cfg)["accent"] == "#e0559a"
    cfg["active_mode"] = "coding"
    assert config.get_mode_theme(cfg)["accent"] == "#222222"


def test_validate_accepts_a_full_submission():
    clean, name = persona.validate({"style": "quick", "traits": {"warmth": 40.0}, "accent": "#8b7cff",
                                    "note": "  hi  ", "name": " Ihan "})
    assert clean == {"style": "quick", "traits": {"warmth": 40}, "accent": "#8b7cff", "note": "hi"}
    assert name == "Ihan"


@pytest.mark.parametrize("body", [
    {"style": "grumpy"},
    {"traits": {"sarcasm": 50}},
    {"traits": {"warmth": 101}},
    {"traits": {"warmth": True}},
    {"accent": "red"},
    {"accent": "#12345"},
    {"note": "x" * 401},
    {"name": "Ihan\n# injected heading"},
    {"name": "x" * 41},
])
def test_validate_rejects_bad_input(body):
    with pytest.raises(ValueError):
        persona.validate(body)


@pytest.fixture
def memory_file(tmp_path, monkeypatch):
    path = tmp_path / "memory" / "MEMORY.md"
    monkeypatch.setattr(user_identity, "MEMORY_MD_PATHS", (str(path),))
    return path


def test_name_creates_memory_file(memory_file):
    persona.save_preferred_name("Ihan")
    assert user_identity.get_user_name() == "Ihan"
    assert user_identity.get_preferred_name() == "Ihan"


def test_name_updates_preferred_line_and_keeps_the_rest(memory_file):
    memory_file.parent.mkdir(parents=True)
    memory_file.write_text("# Freya Memory - Ihan Hansaja\n\n- Name: Ihan Hansaja\n- Likes: tea\n", encoding="utf-8")
    persona.save_preferred_name("Ihan")
    persona.save_preferred_name("Boss")
    text = memory_file.read_text(encoding="utf-8")
    assert text.count("Preferred name") == 1
    assert "- Likes: tea" in text and "- Name: Ihan Hansaja" in text
    assert user_identity.get_preferred_name() == "Boss"


def test_blank_name_leaves_memory_alone(memory_file):
    persona.save_preferred_name("")
    assert not memory_file.exists()
