"""API-Typen der Sprach-Pipeline: `voice.state` (nur lesen), der Pegeltest des Setup-Assistenten (E3b) und die
Mikrofon-Schwellen zur Laufzeit (`voice.tuning.*`).

`voice.state`: {"active", "state", "level", "wake_count", "wake_last", "tts"}. Kein Audio, kein Text; `wake_last` ist nur der
Name des zuletzt erkannten Wake Words (für den Wake-Word-Test), `tts` der Zustand der Sprachausgabe (loading | ready | cpu |
failed | off, für den Stimm-Chip der Oberfläche). Läuft kein Sprachdienst, ist `active` false.

Pegeltest: läuft im Sprachprozess, der das Mikrofon ohnehin hält (`kushim talk --ui`, API im selben Prozess, `LevelTest`
bekommt jeden Frame der Sprach-Schleife). Ohne diesen Prozess (z. B. `kushim serve`) gibt es keinen Test: `voice.level_test`
antwortet "unavailable", `voice.level_result` meldet `state: "unavailable"`. Es wird nie ein zweites Mikrofon geöffnet.
- `voice.level_test` {confirm: true} startet (oder beginnt neu): 3 s Ruhe, dann 6 s Sprechen.
- `voice.level_result` -> {state: idle|quiet|speak|done|unavailable, seconds_left, suggestion: {speech_level, barge_in_level}|null}
- `voice.level_apply` {speech_level, barge_in_level, confirm: true} schreibt geprüft über `wakeconfig.save` (mit
  Sicherungskopien wie `voice.tuning.save`) -> {speech_level, barge_in_level, restart_needed, live_clamped, live_changed}.
  Läuft `kushim talk` (mit `LiveTuning`), gelten die Werte sofort (`restart_needed: false`), live aber nur innerhalb der
  Live-Grenzen (`live_clamped: true`, wenn begrenzt; die Datei bekommt die Werte unverändert), damit ein gesprochener Notaus
  erreichbar bleibt. Wurde live in der Zwischenzeit etwas geändert, gilt der neuere Live-Stand (`live_changed: true`,
  `restart_needed: true`). Ohne talk: `restart_needed: true`, beide Flags false.

Mikrofon-Schwellen zur Laufzeit (`voice/tuning.py`, nur im Sprachprozess `kushim talk --ui`):
- `voice.tuning.get` -> {active, values, file_values, bounds, step, rms, peak, last_source, version}. Ohne Sprachprozess
  `active: false`, `values`/`file_values` dann aus der Datei (oder null, wenn sie fehlerhaft ist), Pegel 0.
- `voice.tuning.set` {values: {speech_level?, barge_in_level?, barge_in_ms?, end_silence_seconds?}, confirm: true}: wirkt ab
  dem nächsten Frame, nicht gespeichert. Außerhalb der Live-Grenzen "invalid", falscher Typ "bad_request".
- `voice.tuning.reset` {confirm: true}: zurück auf die Dateiwerte, Stufe 0.
- `voice.tuning.save` {confirm: true}: liest die aktuellen Werte unter `wakeconfig.SAVE_LOCK` und schreibt sie über
  `wakeconfig.save` (geprüft, atomar). Vorher `wakewords.toml.bak` (letzte Fassung) und beim allerersten Mal einmalig
  `wakewords.toml.orig.bak` (nie überschrieben). Danach sind es die neuen Dateiwerte (Stufe 0), außer es wurde live
  inzwischen etwas geändert (`live_changed: true`, der neuere Live-Stand bleibt). Antwort: get-Objekt + {backup,
  saved_values, live_changed}. Audit `voice_tuning_saved` ohne Werte.
Schreibende Typen brauchen `confirm: true` und sind bei aktivem Notaus gesperrt ("kill"); ohne Sprachprozess "unavailable".
"""
from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from ..safety import killswitch
from ..voice import statefile
from .protocol import ApiCore, ApiError

BACKUP = "wakewords.toml.bak"          # letzte Fassung vor dem Speichern
ORIGINAL = "wakewords.toml.orig.bak"   # Fassung vor dem allerersten Speichern über die API, wird nie überschrieben


def _level(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("bad_request")
    try:
        if not math.isfinite(value):
            raise ApiError("bad_request")
        return float(value)
    except OverflowError:                              # riesige Ganzzahl
        raise ApiError("bad_request")


def _backup(root: Path) -> bool:
    """Vor dem Schreiben: `wakewords.toml.bak` = letzte Fassung (jedes Mal neu), beim allerersten Mal zusätzlich
    `wakewords.toml.orig.bak` (wird nie überschrieben). Beides atomar über eine Temp-Datei. False, wenn es noch keine eigene
    Datei gibt. OSError geht an den Aufrufer (dann wird nicht gespeichert)."""
    from ..voice import wakeconfig
    target = wakeconfig.path(root)
    if not target.is_file():
        return False
    data = target.read_bytes()
    orig = root / ORIGINAL
    if not orig.exists():
        tmp = orig.with_name(orig.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(orig)
    bak = root / BACKUP
    tmp = bak.with_name(bak.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(bak)
    return True


def _tuning_values(payload: dict[str, Any]) -> dict[str, float]:
    """`values` von `voice.tuning.set`: ein nicht leeres Objekt mit bekannten Namen und Zahlen (Grenzen prüft `LiveTuning`)."""
    from ..voice.tuning import KEYS
    values = payload.get("values")
    if not isinstance(values, dict) or not values or any(k not in KEYS for k in values):
        raise ApiError("bad_request")
    return {k: _level(v) for k, v in values.items()}


def register_voice(core: ApiCore, root: Path, level_test: Any = None,
                   audit: Callable[[str, str], None] | None = None, tuning: Any = None) -> None:
    """`level_test`: der `LevelTest` des Sprachprozesses (nur mit `kushim talk --ui`), sonst None.
    `audit(event, detail)`: Audit-Eintrag nach dem Speichern (nie Werte oder Pfade).
    `tuning`: das `LiveTuning` des Sprachprozesses (dasselbe Objekt wie Collector und Unterbrechen), sonst None."""

    def guard(payload: dict[str, Any]) -> None:
        if payload.get("confirm") is not True:
            raise ApiError("confirm_required")
        if killswitch.is_triggered(root):
            raise ApiError("kill")

    def write_audit(event: str) -> None:
        if audit is not None:
            try:
                audit(event, "api")
            except Exception:                          # noqa: BLE001 (ein Audit-Fehler macht das Speichern nicht rückgängig)
                pass

    def live() -> bool:
        return tuning is not None and statefile.read(root)["active"]

    def state(_: dict[str, Any]) -> dict[str, Any]:
        return statefile.read(root)

    def level_test_start(payload: dict[str, Any]) -> dict[str, Any]:
        guard(payload)
        if level_test is None or not statefile.read(root)["active"]:
            raise ApiError("unavailable")
        level_test.start()
        return {}

    def level_result(_: dict[str, Any]) -> dict[str, Any]:
        if level_test is None or not statefile.read(root)["active"]:
            return {"state": "unavailable", "seconds_left": 0.0, "suggestion": None}
        return level_test.result()

    def write_file(new: Any) -> bool:
        """Sicherungskopien, dann geprüft und atomar schreiben (unter `wakeconfig.SAVE_LOCK`). Gibt `backup` zurück."""
        from ..voice import wakeconfig
        try:
            wakeconfig.validate(new, root)
        except ValueError:
            raise ApiError("invalid")                  # außerhalb der Grenzen von wakeconfig.validate
        try:
            backup = _backup(root)
            wakeconfig.save(root, new)
        except ValueError:
            raise ApiError("invalid")
        except OSError:
            raise ApiError("not_saved")
        return backup

    def level_apply(payload: dict[str, Any]) -> dict[str, Any]:
        speech, barge = _level(payload.get("speech_level")), _level(payload.get("barge_in_level"))
        guard(payload)
        from ..voice import wakeconfig
        clamped = changed = False
        restart = True
        with wakeconfig.SAVE_LOCK:                     # dieselbe Sperre wie wakeconfig.save und voice.tuning.save
            version = tuning.version if live() else None    # Live-Stand vor dem Schreiben
            try:
                cfg = wakeconfig.load(root)
            except ValueError:
                raise ApiError("broken_file")
            write_file(replace(cfg, settings=replace(cfg.settings, speech_level=speech, barge_in_level=barge)))
            if version is not None:                    # talk läuft: live gelten die Werte sofort, aber nur in den Live-Grenzen
                snap = tuning.adopt_file(source="ui", expect_version=version, clamp=True,
                                         speech_level=speech, barge_in_level=barge)
                if snap is None:                       # inzwischen live geändert: der neuere Stand gilt
                    changed = True
                else:
                    restart = False
                    clamped = (snap["values"]["speech_level"], snap["values"]["barge_in_level"]) != (speech, barge)
        write_audit("setup_levels")
        return {"speech_level": speech, "barge_in_level": barge, "restart_needed": restart,
                "live_clamped": clamped, "live_changed": changed}

    # --- Mikrofon-Schwellen zur Laufzeit
    def tuning_state() -> dict[str, Any]:
        from ..voice import tuning as tmod
        if live():
            snap = tuning.snapshot()
            return {"active": True, "values": snap["values"], "file_values": snap["file_values"], "bounds": tmod.bounds(),
                    "step": snap["step"], "rms": snap["rms"], "peak": snap["peak"], "last_source": snap["source"],
                    "version": snap["version"]}
        from ..voice import wakeconfig
        try:
            s = wakeconfig.load(root).settings
            values: dict[str, Any] | None = tmod.TuningValues(float(s.speech_level), float(s.barge_in_level),
                                                              int(s.barge_in_ms), float(s.end_silence_seconds)).as_dict()
        except ValueError:
            values = None
        return {"active": False, "values": values, "file_values": dict(values) if values else None, "bounds": tmod.bounds(),
                "step": 0, "rms": 0.0, "peak": 0.0, "last_source": "file", "version": 0}

    def tuning_get(_: dict[str, Any]) -> dict[str, Any]:
        return tuning_state()

    def tuning_set(payload: dict[str, Any]) -> dict[str, Any]:
        values = _tuning_values(payload)
        guard(payload)
        if not live():
            raise ApiError("unavailable")
        try:
            tuning.set(source="ui", **values)
        except ValueError:
            raise ApiError("invalid")                  # außerhalb der Live-Grenzen (oder barge_in_ms nicht ganzzahlig)
        return tuning_state()

    def tuning_reset(payload: dict[str, Any]) -> dict[str, Any]:
        guard(payload)
        if not live():
            raise ApiError("unavailable")
        tuning.reset(source="ui")
        return tuning_state()

    def tuning_save(payload: dict[str, Any]) -> dict[str, Any]:
        guard(payload)
        if not live():
            raise ApiError("unavailable")
        from ..voice import wakeconfig
        with wakeconfig.SAVE_LOCK:                     # Werte unter derselben Sperre lesen, mit der gespeichert wird
            snap = tuning.snapshot()
            current, version = snap["values"], snap["version"]
            try:
                cfg = wakeconfig.load(root)
            except ValueError:
                raise ApiError("broken_file")
            backup = write_file(replace(cfg, settings=replace(cfg.settings, **current)))
            # gespeichert: das sind jetzt die Dateiwerte (Stufe 0), aber nur, wenn live inzwischen nichts geändert wurde
            adopted = tuning.adopt_file(source="ui", expect_version=version, **current)
        write_audit("voice_tuning_saved")
        return {**tuning_state(), "backup": backup, "saved_values": current, "live_changed": adopted is None}

    for name, fn in (("voice.state", state), ("voice.level_test", level_test_start), ("voice.level_result", level_result),
                     ("voice.level_apply", level_apply), ("voice.tuning.get", tuning_get), ("voice.tuning.set", tuning_set),
                     ("voice.tuning.reset", tuning_reset), ("voice.tuning.save", tuning_save)):
        core.register(name, fn)
