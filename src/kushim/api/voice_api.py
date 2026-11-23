"""API-Typen der Sprach-Pipeline: `voice.state` (nur lesen) und der Pegeltest des Setup-Assistenten (E3b).

`voice.state`: {"active", "state", "level", "wake_count", "wake_last"}. Kein Audio, kein Text; `wake_last` ist nur der Name
des zuletzt erkannten Wake Words (für den Wake-Word-Test). Läuft kein Sprachdienst, ist `active` false.

Pegeltest: läuft im Sprachprozess, der das Mikrofon ohnehin hält (`kushim talk --ui`, API im selben Prozess, `LevelTest`
bekommt jeden Frame der Sprach-Schleife). Ohne diesen Prozess (z. B. `kushim serve`) gibt es keinen Test: `voice.level_test`
antwortet "unavailable", `voice.level_result` meldet `state: "unavailable"`. Es wird nie ein zweites Mikrofon geöffnet.
- `voice.level_test` {confirm: true} startet (oder beginnt neu): 3 s Ruhe, dann 6 s Sprechen.
- `voice.level_result` -> {state: idle|quiet|speak|done|unavailable, seconds_left, suggestion: {speech_level, barge_in_level}|null}
- `voice.level_apply` {speech_level, barge_in_level, confirm: true} schreibt geprüft über `wakeconfig.save`; gilt ab dem
  nächsten Start (`restart_needed: true`).
Schreibende Typen brauchen `confirm: true` und sind bei aktivem Notaus gesperrt ("kill").
"""
from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..safety import killswitch
from ..voice import statefile
from .protocol import ApiCore, ApiError


def _level(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ApiError("bad_request")
    return float(value)


def register_voice(core: ApiCore, root: Path, level_test: Any = None) -> None:
    """`level_test`: der `LevelTest` des Sprachprozesses (nur mit `kushim talk --ui`), sonst None."""

    def guard(payload: dict[str, Any]) -> None:
        if payload.get("confirm") is not True:
            raise ApiError("confirm_required")
        if killswitch.is_triggered(root):
            raise ApiError("kill")

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
        return {"speech_level": speech, "barge_in_level": barge, "restart_needed": True}

    for name, fn in (("voice.state", state), ("voice.level_test", level_test_start), ("voice.level_result", level_result),
                     ("voice.level_apply", level_apply)):
        core.register(name, fn)
