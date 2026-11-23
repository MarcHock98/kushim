"""API-Typen für den Setup-Assistenten und den Notaus (transportunabhängig, hängen am `ApiCore`).

Erster Schnitt (siehe docs/ui-setup-plan.md): Status der Schritte, Überspringen/Wiedereröffnen/Bestätigen,
Geräteliste, Notaus auslösen und bewusst aufheben. E3 (docs/ui-e2e3-plan.md) ergänzt:
- `setup.checks`: Systemcheck (`doctor.run_checks`) plus Claude (`claude_checks`, über `ClaudeProbe`: höchstens ein
  `claude auth status` je 30 s, die Version nur einmal je Programmdatei) als {id, label, ok, hint}; nur lesen.
- `audio.get` / `audio.set` {mic, out, confirm}: gemerkte Geräte in `config.toml [audio]`, geprüft gegen die Geräteliste.
- `wake.get` / `wake.set` {words, confirm}: Wake Words aus `wakewords.toml`, geprüft mit `wakeconfig.validate`.
Kein Vault anlegen (nur Hinweis aufs Terminal), kein echter Notaus im Setup.

Regeln: Antworten enthalten nur Zustände und Namen, nie Schlüssel, Token, Pfade oder Audio. Fehler sind kurze feste
Codes (`ApiError`). Der Notaus lässt sich immer auslösen; Aufheben braucht `confirm: true`. Jeder schreibende Setup-Typ
braucht `confirm: true` und ist bei aktivem Notaus gesperrt ("kill"). Gerät und Wake Words gelten ab dem nächsten
`kushim start` (`restart_needed: true`).
"""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from ..claude_cli.base import MIN_VERSION
from ..config import NotSaved
from ..doctor import Check, claude_checks, run_checks
from ..safety import killswitch
from ..setup import state as setup_state
from ..setup import status as setup_status
from .protocol import ApiCore, ApiError

MAX_TEXT = 120
MAX_PHRASE = 60
# Pfade (Laufwerk, UNC, Home, absolute Unix-Pfade) und tokenartige Zeichenketten gehören nie in Anzeigetexte.
_UNSAFE = re.compile(r"[A-Za-z]:[\\/]|\\\\|~[\\/]|(^|\s)/\w|[A-Za-z0-9_+=-]{24,}")


class _Checking(Exception):
    """Die Claude-Prüfung läuft noch (`ClaudeState.checking`)."""


def safe_text(text: Any, fallback: str = "") -> str:
    """Anzeigetext für die Oberfläche: nur druckbar, höchstens 120 Zeichen, nie pfad- oder tokenartig (sonst `fallback`)."""
    if not isinstance(text, str):
        return fallback
    clean = "".join(c for c in text if c.isprintable())[:MAX_TEXT].strip()
    return fallback if _UNSAFE.search(clean) else clean


def _step(payload: dict[str, Any]) -> str:
    step = payload.get("step")
    if not isinstance(step, str) or step not in setup_state.STEPS:
        raise ApiError("bad_step")
    return step


def register_setup(core: ApiCore, root: Path, vault_state: Callable[[], str],
                   list_devices: Callable[[], dict[str, list[str]]] | None = None,
                   audit: Callable[[str, str], None] | None = None,
                   claude: Callable[[], Any] | None = None,
                   folders_ok: Callable[[], bool] | None = None,
                   load_config: Callable[[], Any] | None = None) -> None:
    """Hängt `setup.*`, `audio.*`, `wake.*` und `safety.*` an den Kern.
    `claude()` liefert den `ClaudeState` (`ClaudeProbe.get`), `folders_ok()` ob ein Arbeitsordner freigegeben ist,
    `load_config()` frisch die `Config` (für `[audio]`). Fehlt etwas davon, antworten die Typen neutral."""

    def overview() -> dict[str, Any]:
        steps = setup_status.compute(root, vault_state, claude=claude, folders=folders_ok)
        return {"steps": [{"step": s.step, "title": s.title, "status": s.status, "detail": s.detail} for s in steps],
                "first_start": setup_status.first_start(steps),
                "restricted": setup_status.restricted_notes(steps),
                "kill": setup_status.kill_active(root)}

    def status(_: dict[str, Any]) -> dict[str, Any]:
        return overview()

    # Schreiben `run/setup-state.json`: wie alle schreibenden Setup-Typen nur mit `confirm: true` und nie bei Notaus
    # (`kushim setup` im Terminal liest nur und benutzt die API nicht).
    def skip(payload: dict[str, Any]) -> dict[str, Any]:
        step = _step(payload)
        guard(payload)
        setup_state.mark(root, step, "skipped")
        return overview()

    def reopen(payload: dict[str, Any]) -> dict[str, Any]:
        step = _step(payload)
        guard(payload)
        setup_state.mark(root, step, "open")
        return overview()

    def done(payload: dict[str, Any]) -> dict[str, Any]:
        step = _step(payload)
        guard(payload)
        if step not in setup_status.MANUAL_DONE:      # die anderen Schritte ergeben sich aus echten Fakten
            raise ApiError("not_allowed")
        setup_state.mark(root, step, "done")
        return overview()

    def device_lists() -> tuple[list[str], list[str]]:
        if list_devices is None:
            raise ApiError("unavailable")
        try:
            found = list_devices()
            return [str(n) for n in found.get("inputs", [])], [str(n) for n in found.get("outputs", [])]
        except Exception:
            raise ApiError("unavailable")

    def devices(_: dict[str, Any]) -> dict[str, Any]:
        inputs, outputs = device_lists()
        return {"inputs": inputs, "outputs": outputs}

    def guard(payload: dict[str, Any]) -> None:
        """Schreibende Setup-Typen: nur bewusst (`confirm: true`) und nie bei aktivem Notaus."""
        if payload.get("confirm") is not True:
            raise ApiError("confirm_required")
        if killswitch.is_triggered(root):
            raise ApiError("kill")

    # --- Systemcheck --------------------------------------------------------------------------------------
    def checks(_: dict[str, Any]) -> dict[str, Any]:
        found = list(run_checks(root, vault_state))
        if claude is not None:
            try:
                st = claude()
                if getattr(st, "checking", False):    # erste Prüfung läuft noch im Hintergrund: später erneut fragen
                    raise _Checking()
                found += claude_checks(lambda: "claude" if st.installed else None, lambda _exe: st.version,
                                       lambda _exe: st.logged_in, MIN_VERSION)
            except _Checking:
                found.append(Check("Claude Code wird geprüft", False, "", "claude_checking"))
            except Exception:                         # noqa: BLE001 (nie Systemtext nach außen)
                found.append(Check("Claude Code prüfbar", False, "kushim doctor im eigenen Terminal", "claude_installed"))
        out = []
        for c in found:
            cid = c.id if re.fullmatch(r"[a-z0-9_]{1,32}", c.id or "") else "check"
            out.append({"id": cid, "label": safe_text(c.name, cid), "ok": bool(c.ok),
                        "hint": "" if c.ok else safe_text(c.hint)})
        return {"checks": out}

    # --- Mikrofon und Lautsprecher ([audio] in config.toml) -----------------------------------------------
    def config():
        if load_config is None:
            raise ApiError("unavailable")
        try:
            return load_config()
        except Exception:                             # noqa: BLE001 (kaputte config.toml: nichts verändern)
            raise ApiError("broken_file")

    def audio_get(_: dict[str, Any]) -> dict[str, Any]:
        cfg = config()
        return {"mic": cfg.audio_mic, "out": cfg.audio_out}

    def audio_set(payload: dict[str, Any]) -> dict[str, Any]:
        mic, out = payload.get("mic"), payload.get("out")
        if not isinstance(mic, str) or not isinstance(out, str) or len(mic) > 200 or len(out) > 200:
            raise ApiError("bad_request")
        guard(payload)
        inputs, outputs = device_lists()
        if (mic and mic not in inputs) or (out and out not in outputs):
            raise ApiError("unknown_device")
        cfg = config()
        try:
            cfg.set_audio(mic, out)
        except (NotSaved, OSError):                   # Gegenprobe gescheitert oder Datei nicht beschreibbar: nichts geändert
            raise ApiError("not_saved")
        except ValueError:
            raise ApiError("bad_request")
        _audit("setup_audio")
        return {"mic": mic, "out": out, "restart_needed": True}

    # --- Wake Words (wakewords.toml) ------------------------------------------------------------------------
    from ..voice import wakeconfig

    def wake_load():
        try:
            return wakeconfig.load(root)
        except ValueError:
            raise ApiError("broken_file")

    def wake_view(cfg) -> dict[str, Any]:
        return {"words": [{"phrase": w.name, "enabled": w.enabled} for w in cfg.words], "max": wakeconfig.MAX_WORDS}

    def wake_get(_: dict[str, Any]) -> dict[str, Any]:
        return wake_view(wake_load())

    def wake_set(payload: dict[str, Any]) -> dict[str, Any]:
        words = payload.get("words")
        if not isinstance(words, list):
            raise ApiError("bad_request")
        if len(words) > wakeconfig.MAX_WORDS:
            raise ApiError("too_many")
        wanted: list[tuple[str, bool]] = []
        for w in words:
            if (not isinstance(w, dict) or not isinstance(w.get("phrase"), str) or not isinstance(w.get("enabled"), bool)
                    or len(w["phrase"]) > MAX_PHRASE):
                raise ApiError("bad_request")
            wanted.append((w["phrase"], w["enabled"]))
        if not any(enabled for _, enabled in wanted):
            raise ApiError("none_enabled")              # das letzte aktive Wort lässt sich nicht abschalten
        guard(payload)
        current = wake_load()
        known = {(w.engine, w.name): w for w in current.words}
        new_words = []
        for phrase, enabled in wanted:
            # vorhandene Wörter behalten Engine, Schwelle und boost; neue sind freie Wörter (kws)
            old = known.get(("kws", wakeconfig.normalize_name(phrase, "kws"))) or \
                known.get(("openwakeword", wakeconfig.normalize_name(phrase, "openwakeword")))
            if old is not None:
                new_words.append(replace(old, enabled=enabled))
            else:
                new_words.append(wakeconfig.WakeWord(wakeconfig.normalize_name(phrase, "kws"), "kws", enabled))
        cfg = replace(current, words=tuple(new_words))
        try:
            wakeconfig.save(root, cfg)
        except ValueError:
            raise ApiError("invalid")                    # Textregeln, Doppelte, Grenzen aus wakeconfig.validate
        except OSError:
            raise ApiError("not_saved")
        _audit("setup_wake")
        return {**wake_view(cfg), "restart_needed": True}

    def _audit(event: str) -> None:
        if audit is None:
            return
        try:
            audit(event, "api")
        except Exception:                             # ein Audit-Fehler darf den Notaus nie verhindern
            pass

    def kill_status(_: dict[str, Any]) -> dict[str, Any]:
        return {"kill": killswitch.is_triggered(root)}

    def kill(_: dict[str, Any]) -> dict[str, Any]:
        killswitch.trigger(root)                      # immer erlaubt: Anhalten ist sicher
        _audit("safety_kill")
        return {"kill": True}

    def resume(payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirm") is not True:        # bewusster Schritt, nie versehentlich
            raise ApiError("confirm_required")
        killswitch.clear(root)
        _audit("safety_resume")
        return {"kill": False}

    for name, fn in (("setup.status", status), ("setup.skip", skip), ("setup.reopen", reopen), ("setup.done", done),
                     ("setup.checks", checks), ("audio.devices", devices), ("audio.get", audio_get), ("audio.set", audio_set),
                     ("wake.get", wake_get), ("wake.set", wake_set),
                     ("safety.status", kill_status), ("safety.kill", kill), ("safety.resume", resume)):
        core.register(name, fn)
