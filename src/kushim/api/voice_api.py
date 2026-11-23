"""API-Typen der Sprach-Pipeline: `voice.state` (nur lesen), der Pegeltest des Setup-Assistenten (E3b) und die
Mikrofon-Schwellen zur Laufzeit (`voice.tuning.*`).

`voice.state`: {"active", "state", "level", "wake_count", "wake_last"}. Kein Audio, kein Text; `wake_last` ist nur der Name
des zuletzt erkannten Wake Words (für den Wake-Word-Test). Läuft kein Sprachdienst, ist `active` false.

Pegeltest: läuft im Sprachprozess, der das Mikrofon ohnehin hält (`kushim talk --ui`, API im selben Prozess, `LevelTest`
bekommt jeden Frame der Sprach-Schleife). Ohne diesen Prozess (z. B. `kushim serve`) gibt es keinen Test: `voice.level_test`
antwortet "unavailable", `voice.level_result` meldet `state: "unavailable"`. Es wird nie ein zweites Mikrofon geöffnet.
- `voice.level_test` {confirm: true} startet (oder beginnt neu): 3 s Ruhe, dann 6 s Sprechen.
- `voice.level_result` -> {state: idle|quiet|speak|done|unavailable, seconds_left, suggestion: {speech_level, barge_in_level}|null}
- `voice.level_apply` {speech_level, barge_in_level, confirm: true} schreibt geprüft über `wakeconfig.save`. Läuft
  `kushim talk` (mit `LiveTuning`), gelten die Werte sofort (`restart_needed: false`), sonst ab dem nächsten Start (`true`).

Mikrofon-Schwellen zur Laufzeit (`voice/tuning.py`, nur im Sprachprozess `kushim talk --ui`):
- `voice.tuning.get` -> {active, values, file_values, bounds, step, rms, peak, last_source, version}. Ohne Sprachprozess
  `active: false`, `values`/`file_values` dann aus der Datei (oder null, wenn sie fehlerhaft ist), Pegel 0.
- `voice.tuning.set` {values: {speech_level?, barge_in_level?, barge_in_ms?, end_silence_seconds?}, confirm: true}: wirkt ab
  dem nächsten Frame, nicht gespeichert. Außerhalb der Live-Grenzen "invalid", falscher Typ "bad_request".
- `voice.tuning.reset` {confirm: true}: zurück auf die Dateiwerte, Stufe 0.
- `voice.tuning.save` {confirm: true}: schreibt die aktuellen Werte über `wakeconfig.save` (geprüft, atomar), vorher Kopie
  `wakewords.toml.bak`. Danach sind es die neuen Dateiwerte (Stufe 0). Audit `voice_tuning_saved` ohne Werte.
Schreibende Typen brauchen `confirm: true` und sind bei aktivem Notaus gesperrt ("kill"); ohne Sprachprozess "unavailable".
"""
from __future__ import annotations

import math
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from ..safety import killswitch
from ..voice import statefile
from .protocol import ApiCore, ApiError

BACKUP = "wakewords.toml.bak"
_SAVE_LOCK = threading.Lock()          # Sicherungskopie und Speichern gehören zusammen


def _level(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ApiError("bad_request")
    return float(value)


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

    def level_apply(payload: dict[str, Any]) -> dict[str, Any]:
        speech, barge = _level(payload.get("speech_level")), _level(payload.get("barge_in_level"))
        guard(payload)
        from ..voice import wakeconfig
        try:
            cfg = wakeconfig.load(root)
        except ValueError:
            raise ApiError("broken_file")
        try:
            wakeconfig.save(root, replace(cfg, settings=replace(cfg.settings, speech_level=speech, barge_in_level=barge)))
        except ValueError:
            raise ApiError("invalid")                  # außerhalb der Grenzen von wakeconfig.validate
        except OSError:
            raise ApiError("not_saved")
        write_audit("setup_levels")
        restart = True
        if live():                                     # talk läuft: die gespeicherten Werte gelten sofort
            try:
                tuning.adopt_file(source="ui", speech_level=speech, barge_in_level=barge)
                restart = False
            except ValueError:
                pass
        return {"speech_level": speech, "barge_in_level": barge, "restart_needed": restart}

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
        current = tuning.values.as_dict()
        with _SAVE_LOCK:
            try:
                cfg = wakeconfig.load(root)
            except ValueError:
                raise ApiError("broken_file")
            new = replace(cfg, settings=replace(cfg.settings, **current))
            try:
                wakeconfig.validate(new, root)
            except ValueError:
                raise ApiError("invalid")
            target = wakeconfig.path(root)
            backup = False
            try:
                if target.is_file():                   # Sicherungskopie vorher, ebenfalls atomar
                    bak = root / BACKUP
                    tmp = bak.with_name(bak.name + ".tmp")
                    tmp.write_bytes(target.read_bytes())
                    tmp.replace(bak)
                    backup = True
                wakeconfig.save(root, new)
            except ValueError:
                raise ApiError("invalid")
            except OSError:
                raise ApiError("not_saved")
        try:
            tuning.adopt_file(source="ui", **current)  # gespeichert: das sind jetzt die Dateiwerte (Stufe 0)
        except ValueError:
            pass
        write_audit("voice_tuning_saved")
        return {**tuning_state(), "backup": backup}

    for name, fn in (("voice.state", state), ("voice.level_test", level_test_start), ("voice.level_result", level_result),
                     ("voice.level_apply", level_apply), ("voice.tuning.get", tuning_get), ("voice.tuning.set", tuning_set),
                     ("voice.tuning.reset", tuning_reset), ("voice.tuning.save", tuning_save)):
        core.register(name, fn)
