import wave
from dataclasses import replace

import numpy as np
import pytest

from kushim.config import Config
from kushim.memory import open_store
from kushim.voice import voiceprint, wakeconfig
from kushim.voice.enrollment import enroll_from_recordings, load_wav_16k
from kushim.voice.profile import MAX_THRESHOLD, MIN_THRESHOLD, SpeakerProfile, build_profile, kmeans, unit
from kushim.voice.speaker import SpeakerVerifier
from kushim.voice.verify import RATE, AudioVerifier, windows

DIM = 64
RNG = np.random.default_rng(0)
CENTERS = [RNG.normal(size=DIM) for _ in range(2)]            # zwei Sprechweisen derselben Person


def own(center, n, noise=0.15, seed=0):
    r = np.random.default_rng(seed)
    return [CENTERS[center] + r.normal(size=DIM) * noise for _ in range(n)]


def strangers(n=20, seed=100):
    r = np.random.default_rng(seed)
    return [r.normal(size=DIM) for _ in range(n)]


def recordings():
    return [own(i % 2, 8, seed=i) for i in range(6)]          # 6 Aufnahmen, abwechselnd beide Sprechweisen


def test_profile_covers_both_speaking_styles_where_a_single_mean_blurs():
    prof = build_profile(recordings(), strangers(), "m")
    assert len(prof.prototypes) >= 2
    for c in (0, 1):
        assert prof.verify(own(c, 1, seed=50)[0]).accepted
    mean_only = SpeakerVerifier(threshold=prof.threshold)
    mean_only.enroll(own(0, 4, seed=1) + own(1, 4, seed=2))
    # Der Mittelwert liegt zwischen den Sprechweisen: für beide schlechter als der nächste Prototyp
    s_proto = min(prof.score(own(c, 1, seed=60)[0]) for c in (0, 1))
    s_mean = min(mean_only.verify(own(c, 1, seed=60)[0]).score for c in (0, 1))
    assert s_proto > s_mean


def test_strangers_are_rejected_and_threshold_is_clamped():
    prof = build_profile(recordings(), strangers(), "m")
    assert MIN_THRESHOLD <= prof.threshold <= MAX_THRESHOLD
    assert not any(prof.verify(e).accepted for e in strangers(30, seed=7))
    assert prof.stats["separation"] > 0.1


def test_overlap_is_reported_not_hidden():
    # "Fremde" sind in Wahrheit fast dieselbe Stimme: die Trennung muss klein/negativ gemeldet werden
    prof = build_profile(recordings(), own(0, 20, noise=0.2, seed=9), "m")
    assert prof.stats["separation"] < 0.1


def test_too_little_material_is_refused():
    with pytest.raises(ValueError):
        build_profile([own(0, 3)], strangers())
    with pytest.raises(ValueError):
        build_profile([own(0, 2)] * 3, strangers())


def test_json_roundtrip_and_corruption():
    prof = build_profile(recordings(), strangers(), "m")
    back = SpeakerProfile.from_json(prof.to_json())
    probe = own(0, 1, seed=70)[0]
    assert back.score(probe) == pytest.approx(prof.score(probe), abs=1e-5)
    assert back.threshold == prof.threshold and back.model == "m"
    bad = prof.to_json()
    bad["dim"] = 5
    with pytest.raises(ValueError):
        SpeakerProfile.from_json(bad)


def test_kmeans_handles_small_inputs():
    x = np.array([unit(v) for v in own(0, 3)])
    assert kmeans(x, 10).shape[0] == 3


# --- Fenster und Prüfung langer Äußerungen ---------------------------------------------------

def tone(seconds, amp=3000):
    return (np.ones(int(seconds * RATE)) * amp).astype(np.int16)


def test_windows_split_long_audio_and_skip_silence():
    ws = windows(np.concatenate([tone(6), np.zeros(6 * RATE, dtype=np.int16)]))
    assert len(ws) >= 3 and all(len(w) == 3 * RATE for w in ws)
    assert len(windows(tone(2))) == 1


class FixedEmbed:
    """Embedding je Fenster aus einer Liste (Zielstimme/Fremde)."""

    def __init__(self, vectors):
        self.vectors, self.i = vectors, 0

    def __call__(self, seg):
        v = self.vectors[min(self.i, len(self.vectors) - 1)]
        self.i += 1
        return v


def verifier(vectors):
    prof = build_profile(recordings(), strangers(), "m")
    return prof, AudioVerifier(prof, FixedEmbed(vectors))


def test_short_utterance_rejected_below_minimum():
    prof, v = verifier([own(0, 1)[0]])
    r = v.check(tone(0.5))
    assert not r.accepted and r.reason == "zu kurz"
    assert v.check(tone(0.5), min_seconds=0.4).accepted           # kurze Bestätigung nur mit gelockerter Grenze


def test_weak_vs_strong_by_length():
    prof, v = verifier([own(0, 1)[0]] * 2)
    assert v.check(tone(1.0)).accepted and not v.check(tone(1.0)).strong          # akzeptiert, aber zu kurz
    assert v.check(tone(2.0)).strong


def test_long_utterance_needs_most_windows_to_match():
    mine = own(0, 1, seed=3)[0]
    stranger = strangers(1, seed=5)[0]
    n = len(windows(tone(12)))
    only_me = AudioVerifier(build_profile(recordings(), strangers(), "m"), FixedEmbed([mine] * n))
    assert only_me.check(tone(12)).accepted
    mostly_stranger = AudioVerifier(build_profile(recordings(), strangers(), "m"),
                                    FixedEmbed([mine] + [stranger] * (n - 1)))
    assert not mostly_stranger.check(tone(12)).accepted


def test_one_noisy_window_does_not_invalidate_a_real_command():
    mine = own(0, 1, seed=3)[0]
    stranger = strangers(1, seed=5)[0]
    n = len(windows(tone(12)))
    v = AudioVerifier(build_profile(recordings(), strangers(), "m"), FixedEmbed([mine] * (n - 1) + [stranger]))
    assert v.check(tone(12)).accepted


def test_strong_threshold_is_reachable_even_for_a_very_high_threshold():
    prof = SpeakerProfile(np.array([unit(CENTERS[0])]), threshold=0.9)
    v = AudioVerifier(prof, lambda s: CENTERS[0])                # Wert 1,0
    r = v.check(tone(2.0))
    assert r.accepted and r.strong
    weaker = AudioVerifier(prof, lambda s: unit(CENTERS[0]) * 0.93 + unit(CENTERS[1]) * 0.37)   # knapp über 0,9
    r2 = weaker.check(tone(2.0))
    assert r2.accepted and not r2.strong


def test_empty_embedding_fails_closed():
    v = AudioVerifier(build_profile(recordings(), strangers(), "m"), lambda s: np.zeros(0))
    assert not v.check(tone(2.0)).accepted


# --- Vault: v2 und älteres Format ------------------------------------------------------------

@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("KUSHIM_VAULT_KEY", "ab" * 32)
    cfg = Config(path=tmp_path / "c.toml", memory_location=f"local:{tmp_path / 'v'}")
    with open_store(cfg, create=True) as s:
        yield s


def test_vault_roundtrip_v2_and_legacy_still_loads(store):
    prof = build_profile(recordings(), strangers(), "m")
    voiceprint.save_profile(store, prof)
    loaded = voiceprint.load(store)
    assert isinstance(loaded, SpeakerProfile) and loaded.threshold == prof.threshold
    legacy = SpeakerVerifier()
    base = own(0, 3)
    legacy.enroll(base)
    voiceprint.save(store, legacy, "old")
    old = voiceprint.load(store)
    assert isinstance(old, SpeakerVerifier) and old.enrolled
    store.set_profile(voiceprint.KEY, '{"version": 2, "dim": 3, "prototypes": ["AAAA"]}')
    assert voiceprint.load(store) is None                       # kaputt: lieber kein Profil


# --- Einschreiben aus Aufnahmen ---------------------------------------------------------------

def write_wav(path, rate, seconds, freq=220.0):
    t = np.arange(int(rate * seconds)) / rate
    x = (np.sin(2 * np.pi * freq * t) * 8000).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(x.tobytes())


def test_load_wav_resamples_24k_to_16k(tmp_path):
    write_wav(tmp_path / "a.wav", 24_000, 2.0)
    x = load_wav_16k(tmp_path / "a.wav")
    assert x.dtype == np.int16 and len(x) == 32_000


def test_enroll_from_recordings_builds_profile(tmp_path):
    paths = []
    for i in range(5):
        p = tmp_path / f"{i + 1:02d}.wav"
        write_wav(p, 24_000, 12.0, freq=200 + 20 * (i % 2))
        paths.append(p)
    calls = {"n": 0}

    def embed(seg):                          # deterministisch "Stimme" aus der Energie, mit etwas Streuung
        calls["n"] += 1
        r = np.random.default_rng(calls["n"] % 3)
        return CENTERS[0] + r.normal(size=DIM) * 0.1

    cohort = [(np.random.default_rng(1).normal(size=96000) * 2000).astype(np.int16)]
    cohort_embed_calls = []

    def embed2(seg):
        # Kohorte erkennt man an der Rauschform: hier einfach zweiter Vektorraum
        if np.std(seg) > 1900 and np.std(seg) < 2100:
            cohort_embed_calls.append(1)
            return strangers(1, seed=len(cohort_embed_calls))[0]
        return embed(seg)

    prof = enroll_from_recordings(paths, embed2, cohort, "m", say=lambda m: None)
    assert prof.stats["recordings"] == 5 and prof.stats["windows"] >= 12 and cohort_embed_calls
    assert prof.verify(CENTERS[0]).accepted


# --- längere Eingaben: Einstellungen --------------------------------------------------------

def test_long_input_settings_are_validated_and_roundtripped(tmp_path):
    cfg = replace(wakeconfig.WakeConfig(), settings=wakeconfig.Settings(2.0, 5.0, 2.0, 90.0))
    wakeconfig.save(tmp_path, cfg)
    loaded = wakeconfig.load(tmp_path).settings
    assert loaded.end_silence_seconds == 2.0 and loaded.max_seconds == 90.0
    for bad in (wakeconfig.Settings(2.0, 5.0, 0.1, 60.0), wakeconfig.Settings(2.0, 5.0, 1.2, 500.0)):
        with pytest.raises(ValueError):
            wakeconfig.save(tmp_path, replace(cfg, settings=bad))


def test_defaults_allow_longer_dictation_than_before():
    s = wakeconfig.Settings()
    assert s.end_silence_seconds == 1.2 and s.max_seconds == 60.0       # früher 0,8 s Stille und 15 s Maximum


def test_cohort_without_model_is_only_noise(tmp_path):
    from kushim.voice.enrollment import cohort_audio
    audios = cohort_audio(tmp_path, ["Ein Absatz."], speakers=5)
    assert len(audios) == 3 and all(a.dtype == np.int16 for a in audios)


def test_threshold_may_exceed_old_cap_when_data_is_clean():
    prof = build_profile(recordings(), strangers(), "m")
    assert MAX_THRESHOLD == 0.9 and prof.threshold <= MAX_THRESHOLD
