from dataclasses import replace
from pathlib import Path

import pytest

from kushim.voice import wakeconfig as wc
from kushim.voice.wakeconfig import Settings, WakeConfig, WakeWord

ROOT = Path(__file__).resolve().parents[1]
SIX = ["hey kushim", "kushim", "kush", "hallo kush", "hi kushim", "kushi"]


def test_builtin_default_is_the_six_user_words_without_jarvis(tmp_path):
    cfg = wc.load(tmp_path)                   # weder wakewords.toml noch Beispiel
    assert [w.name for w in cfg.enabled()] == SIX
    assert all(w.engine == "kws" for w in cfg.words)


def test_shipped_example_file_is_valid_and_has_the_six_words():
    cfg = wc.load(ROOT)
    assert [w.name for w in cfg.enabled()] == SIX
    assert not any("jarvis" in w.name for w in cfg.words)


def test_user_file_wins_over_example(tmp_path):
    (tmp_path / wc.EXAMPLE).write_text('[[wakeword]]\nname = "kushim"\nengine = "kws"\n', encoding="utf-8")
    (tmp_path / wc.FILE).write_text('[[wakeword]]\nname = "hallo kush"\nengine = "kws"\n', encoding="utf-8")
    assert [w.name for w in wc.load(tmp_path).words] == ["hallo kush"]


def test_roundtrip_save_load(tmp_path):
    cfg = WakeConfig(Settings(3.0, 8.0), (WakeWord("kushim", threshold=0.3, boost=2.0),
                                          WakeWord("alexa", "openwakeword", True),
                                          WakeWord("hi kushim", enabled=False)))
    wc.save(tmp_path, cfg)
    assert wc.load(tmp_path) == cfg


@pytest.mark.parametrize("word", [
    WakeWord("ab"), WakeWord("x" * 50), WakeWord("kush1m"), WakeWord("Kushim"), WakeWord("a b c d e"),
    WakeWord("kushim; rm -rf"), WakeWord("kushim", engine="magie"), WakeWord("kushim", threshold=0.99),
    WakeWord("kushim", boost=9.0), WakeWord("../evil.onnx", "openwakeword"), WakeWord("unbekannt", "openwakeword"),
])
def test_invalid_words_are_rejected(tmp_path, word):
    with pytest.raises(ValueError):
        wc.save(tmp_path, WakeConfig(words=(WakeWord("hey kushim"), word)))
    assert not (tmp_path / wc.FILE).exists()


def test_needs_one_enabled_word_and_no_duplicates(tmp_path):
    with pytest.raises(ValueError):
        wc.save(tmp_path, WakeConfig(words=(WakeWord("kushim", enabled=False),)))
    with pytest.raises(ValueError):
        wc.save(tmp_path, WakeConfig(words=(WakeWord("kushim"), WakeWord("kushim"))))
    with pytest.raises(ValueError):
        wc.save(tmp_path, WakeConfig(words=tuple(WakeWord(f"wort {c}") for c in "abcdefghijklm")))


def test_settings_are_validated(tmp_path):
    with pytest.raises(ValueError):
        wc.save(tmp_path, replace(WakeConfig(), settings=Settings(0.0, 5.0)))
    with pytest.raises(ValueError):
        wc.save(tmp_path, replace(WakeConfig(), settings=Settings(2.0, 100.0)))


def test_broken_file_is_reported_not_ignored(tmp_path):
    (tmp_path / wc.FILE).write_text("[[wakeword\nname=", encoding="utf-8")
    with pytest.raises(ValueError):
        wc.load(tmp_path)
    (tmp_path / wc.FILE).write_text('[[wakeword]]\nname = "kushim"\nengine = "x"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        wc.load(tmp_path)


def test_from_names_routes_engines(tmp_path):
    cfg = wc.from_names(["Hey Kushim", "alexa", " "], tmp_path)
    assert [(w.name, w.engine) for w in cfg.words] == [("hey kushim", "kws"), ("alexa", "openwakeword")]


def test_save_is_atomic_and_leaves_no_tmp(tmp_path):
    wc.save(tmp_path, WakeConfig(words=(WakeWord("kushim"),)))
    assert sorted(p.name for p in tmp_path.iterdir()) == [wc.FILE]


def test_command_wait_roundtrip_and_bounds(tmp_path):
    cfg = replace(WakeConfig(), settings=replace(Settings(), command_wait_seconds=2.0))
    wc.save(tmp_path, cfg)
    assert wc.load(tmp_path).settings.command_wait_seconds == 2.0
    for bad in (0.1, 9.0):
        with pytest.raises(ValueError):
            wc.save(tmp_path, replace(WakeConfig(), settings=replace(Settings(), command_wait_seconds=bad)))
    assert Settings().command_wait_seconds == 1.5 and Settings().listen_seconds == 4.0
