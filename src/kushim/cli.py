"""kushim CLI (Gedächtnis-Verwaltung; Audio/UI folgen)."""
from __future__ import annotations

import argparse

from .config import Config
from .memory import open_store
from .memory.keys import get_or_create_key, store_key
from .memory.migrate import backup, migrate


HELP = """kushim: persönlicher, lokaler Assistent. Alles läuft auf diesem Rechner.

Täglich
  kushim start [ordner]        Claude Code mit kushim-Channel im freigegebenen Ordner öffnen und per Wake Word sprechen
  kushim talk                  Sprechen per Wake Word (Claude Code mit Channel muss schon laufen)
                               [--mic NAME] [--out NAME] [--wake-words "hey kushim,kushim"]
  kushim kill                  NOTAUS: stoppt alle kushim-Dienste
  kushim resume                Notaus bewusst aufheben

Stimme
  kushim voice enroll          Stimme einschreiben (10 Absätze) [--record] [--auto] [--quick] [--mic NAME]
  kushim voice test            Sprecherprüfung mit echten Werten ausprobieren [--mic NAME]
  kushim voice status          Profil und Schwelle anzeigen
  kushim voice threshold 0.79  Schwelle setzen (0,5 bis 0,9; niedriger = lockerer)
  kushim voice record          Absätze für den Stimmklon aufnehmen [--redo] [--auto] [--mic NAME]
  kushim voice level           Mikrofonpegel messen, Schwellen vorschlagen [--apply] [--mic NAME]
  kushim voice reset           Stimmprofil löschen

Oberfläche und Grafikkarte
  kushim gpu                   Grafikkarten zeigen und welche Whisper nutzt
  kushim app                   Die Oberfläche öffnen (startet Sprache und API selbst; --no-voice nur Oberfläche)
  kushim serve                 Backend-API für die Oberfläche starten (nur 127.0.0.1, Port/Token in run/api.json)

Gedächtnis und Schlüssel
  kushim memory init           Vault anlegen (erzeugt auch den Schlüssel)
  kushim memory info           Vault-Ort und Zustand
  kushim memory backup         Verschlüsselte Sicherung erstellen
  kushim memory migrate --to local:D:/kushim-vault
  kushim key export            Schlüssel zum Sichern anzeigen (nur im eigenen Terminal)
  kushim key import <vault_id> <hexkey>

Prüfen und Hilfe
  kushim claude [check|enable|disable]  Claude CLI und Anmeldung prüfen; Modus C ein/aus
  kushim claude folders|add|remove  Sichere Arbeitsordner für Claude verwalten
  kushim doctor                Prüft, ob alles installiert und eingerichtet ist
  kushim setup                 Stand der Einrichtung: Systemcheck, Stimme, Wake Words, Notaus
  kushim help                  Diese Übersicht
  kushim <befehl> --help       Optionen eines Befehls

Einstellungen: config.toml (Vault, Grafikkarte, Claude-Ordner), wakewords.toml (Wake Words, Zeiten). Anleitung: README.md
"""


def _gpu_plan(cfg: Config):
    """Karten lesen und gemäß [gpu] in config.toml verteilen. Gibt (Karten, Plan) zurück; falsche Einstellung: ValueError."""
    from . import gpu
    gpus = gpu.list_gpus()
    return gpus, gpu.make_plan(gpus, cfg.gpu_whisper)


def _claude_dev(args, cfg: Config, root) -> int:
    """`kushim claude folders|add|remove`: sichere Arbeitsordner für Claude verwalten."""
    from .claude_cli import folders as cfolders
    action = args.sub
    vault = cfolders.vault_path(cfg.memory_location)
    known = cfolders.parse(cfg.claude_folders)
    if action == "folders":
        if not known:
            print("Kein Ordner freigegeben. Freigeben: kushim claude add <name> <pfad>")
        for f in known:
            print(f"{f.name}  {f.path}")
        return 0
    if action == "add":
        try:
            if not cfolders.NAME_RE.fullmatch(args.name):
                raise ValueError("Der Name darf nur aus Kleinbuchstaben, Ziffern, - und _ bestehen (höchstens 31 Zeichen).")
            if any(f.name == args.name for f in known):
                raise ValueError("Diesen Namen gibt es schon.")
            path = cfolders.validate_path(args.path, vault)
        except ValueError as e:
            print(f"Nicht freigegeben: {e}")
            return 2
        print(f"Claude darf dann in «{path}» arbeiten, immer in einem eigenen Worktree und Branch. Beim Arbeiten gehen Auftrag und Ausschnitte aus den Dateien an Anthropic.")
        if input("Freigeben? (j/N): ").strip().lower() not in ("j", "ja", "y", "yes"):
            print("Nicht freigegeben.")
            return 1
        cfg.set_claude_folders([f.entry() for f in known] + [cfolders.Folder(args.name, path).entry()])
        print(f"Ordner «{args.name}» ist freigegeben.")
        return 0
    if action == "remove":
        if not any(f.name == args.name for f in known):
            print("Diesen Ordner gibt es nicht.")
            return 2
        cfg.set_claude_folders([f.entry() for f in known if f.name != args.name])
        print(f"Freigabe für «{args.name}» entzogen.")
        return 0


def _start(args, cfg: Config, root) -> int:
    """`kushim start [ordner]`: Claude Code mit dem kushim-Channel im freigegebenen Ordner (eigenes Fenster), dann `kushim talk`."""
    from .channel import launch
    from .claude_cli import base as claude_base
    from .claude_cli import folders as cfolders
    from .safety.killswitch import is_triggered
    if is_triggered(root):
        print("Notaus ist aktiv. Erst bewusst aufheben: kushim resume")
        return 1
    exe = claude_base.find_claude()
    if exe is None:
        print("Claude Code nicht gefunden. Installieren und anmelden, dann erneut: kushim start")
        return 1
    ver = claude_base.version(exe)
    if ver is None or ver < claude_base.MIN_VERSION:
        need = ".".join(map(str, claude_base.MIN_VERSION))
        print(f"Claude Code {'.'.join(map(str, ver)) if ver else '?'} ist zu alt oder nicht lesbar; nötig ist mindestens {need}.")
        return 1
    if not claude_base.auth_status(exe).logged_in:
        print("In Claude Code nicht angemeldet: claude auth login")
        return 1
    known = cfolders.parse(cfg.claude_folders)
    if not known:
        print("Kein Arbeitsordner freigegeben. Erst: kushim claude add <name> <pfad>")
        return 1
    if args.folder:
        chosen = next((f for f in known if f.name == args.folder), None)
        if chosen is None:
            print("Diesen Ordner gibt es nicht. Freigegeben: " + ", ".join(f.name for f in known))
            return 2
    elif len(known) == 1:
        chosen = known[0]
    else:
        print("Welcher Ordner? kushim start <name>  (freigegeben: " + ", ".join(f.name for f in known) + ")")
        return 2
    try:
        folder = cfolders.validate_path(str(chosen.path), cfolders.vault_path(cfg.memory_location))
    except ValueError as e:
        print(f"Ordner «{chosen.name}» ist nicht (mehr) zulässig: {e}")
        return 2
    launch.launch(exe, folder, root)
    print(f"Claude Code startet in einem eigenen Fenster im Ordner «{chosen.name}».")
    print("Dort einmal den Hinweis zum Entwicklungs-Channel bestätigen; danach hört kushim zu.")
    talk = ["talk"] + (["--mic", args.mic] if args.mic else []) + (["--out", args.out] if args.out else []) + (["--ui"] if args.ui else [])
    return _main(talk)


def _vault_state(cfg: Config) -> str:
    """"ok" (Vault und Stimmprofil da), "kein-profil" oder "kein-vault" (für doctor und setup)."""
    from .voice import voiceprint
    try:
        with open_store(cfg) as store:
            return "ok" if voiceprint.load(store) else "kein-profil"
    except FileNotFoundError:
        return "kein-vault"


def _api_start(cfg: Config, root, extra=None):
    """Baut den API-Kern (setup, safety, voice; `extra(core, store)` hängt mehr an) und startet den Server auf 127.0.0.1.
    Port und Token kommen nach run/api.json (nur für die eigene Oberfläche). Gibt (server, store, info) zurück."""
    import json
    from .api.protocol import ApiCore, new_token
    from .api.setup_api import register_setup
    from .api.voice_api import register_voice
    from .net.server import LocalServer
    store = None
    try:
        store = open_store(cfg, shared=True)           # die API-Threads dürfen den Vault nur über die Sperre benutzen
    except Exception:
        print("Hinweis: Vault nicht offen, Notaus-Aktionen werden nicht im Audit protokolliert.")
    token = new_token()
    core = ApiCore(token)
    register_voice(core, root)
    register_setup(core, root, lambda: _vault_state(cfg),
                   audit=store.audit if store else None)
    from .api.safety_view import register_safety_view
    from .config import LiveConfig
    from .api.folders_api import register_folders
    from .claude_cli import folders as cfolders
    register_folders(core, Config.load, lambda raw: cfolders.validate_path(raw, cfolders.vault_path(cfg.memory_location)),
                     audit=store.audit if store else None)
    if extra is not None:
        extra(core, store)
    else:
        register_safety_view(core, LiveConfig(), root, store=store)
        if store is not None:
            from .api.memory_api import register_memory
            register_memory(core, store)
    server = LocalServer(core)
    port = server.start()
    info = root / "run" / "api.json"
    info.parent.mkdir(exist_ok=True)
    info.write_text(json.dumps({"port": port, "token": token}), encoding="utf-8")
    print(f"kushim API auf 127.0.0.1:{port} (nur lokal).")
    return server, store, info


def _api_stop(server, store, info) -> None:
    server.stop()
    info.unlink(missing_ok=True)
    if store:
        store.close()


def _serve(cfg: Config) -> int:
    """Startet die Backend-API auf 127.0.0.1; Port und Token liegen in run/api.json (nur für die eigene Oberfläche).
    Beim Notaus läuft die API weiter (nur setup/safety), damit die UI ihn anzeigen und aufheben kann."""
    import time
    from pathlib import Path
    root = Path(__file__).resolve().parents[1].parent
    server, store, info = _api_start(cfg, root)
    print("Strg+C beendet. Ohne Sprachdienst gibt es hier keine Freigaben: dafür `kushim talk --ui`.")
    try:
        while True:                                   # bleibt auch bei Notaus erreichbar: die UI zeigt "NOTAUS aktiv" und hebt auf
            time.sleep(0.5)
    finally:
        _api_stop(server, store, info)
    return 0


def _vault(cfg: Config):
    """Öffnet den Vault oder erklärt, was fehlt (der Vault wird nie automatisch angelegt)."""
    try:
        return open_store(cfg)
    except FileNotFoundError:
        print("Noch kein Vault. Einmalig anlegen mit: kushim memory init (erzeugt auch den Schlüssel).")
        raise SystemExit(3)


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kushim")
    sub = p.add_subparsers(dest="cmd", required=True)
    mem = sub.add_parser("memory", help="Vault anlegen, Info, Backup, Umzug").add_subparsers(dest="sub", required=True)
    mem.add_parser("init")
    mem.add_parser("info")
    mem.add_parser("backup")
    m = mem.add_parser("migrate")
    m.add_argument("--to", required=True, help='z.B. "local:D:/kushim-vault"')
    key = sub.add_parser("key", help="Vault-Schlüssel sichern oder einspielen").add_subparsers(dest="sub", required=True)
    key.add_parser("export")
    ki = key.add_parser("import")
    ki.add_argument("vault_id")
    ki.add_argument("hexkey")
    sub.add_parser("kill", help="Notaus: stoppt laufende kushim-Dienste")
    sub.add_parser("resume", help="Notaus aufheben (nur bewusst durch den Nutzer)")
    st = sub.add_parser("start", help="Claude Code mit dem kushim-Channel im freigegebenen Ordner starten, dann Sprechen per Wake Word")
    st.add_argument("folder", nargs="?", help="Name eines freigegebenen Ordners (kushim claude folders)")
    st.add_argument("--mic", help="Namensteil des Mikrofons, sonst Systemstandard")
    st.add_argument("--out", help="Namensteil des Ausgabegeräts, sonst Systemstandard")
    st.add_argument("--ui", action="store_true", help="Backend-API für die Oberfläche mitstarten (127.0.0.1)")
    t = sub.add_parser("talk", help="Sprechen per Wake Word (nur das Wake Word wird dauerhaft ausgewertet)")
    t.add_argument("--mic", help="Namensteil des Mikrofons, sonst Systemstandard")
    t.add_argument("--out", help="Namensteil des Ausgabegeräts, sonst Systemstandard")
    t.add_argument("--ui", action="store_true", help="Backend-API für die Oberfläche mitstarten (127.0.0.1): Freigabe-Leiste, Zustand, Notaus")
    t.add_argument("--wake-words", help="Komma-getrennt, überschreibt wakewords.toml nur für diesen Start (z. B. \"hey kushim,kushim\")")
    vo = sub.add_parser("voice", help="Eigene Stimme: einschreiben, testen, Status, löschen").add_subparsers(
        dest="sub", required=True)
    for name in ("enroll", "test"):
        v = vo.add_parser(name)
        v.add_argument("--mic", help="Namensteil des Mikrofons, sonst Systemstandard")
        if name == "enroll":
            v.add_argument("--record", action="store_true", help="die 10 Absätze neu aufnehmen (auch wenn vorhanden)")
            v.add_argument("--quick", action="store_true", help="altes kurzes Einschreiben mit 5 Sätzen")
            v.add_argument("--auto", action="store_true", help="Ende eines Absatzes automatisch per Stille statt per Enter")
    vo.add_parser("status")
    lv = vo.add_parser("level", help="Mikrofonpegel messen und Schwellen fürs Sprechen/Unterbrechen vorschlagen")
    lv.add_argument("--mic", help="Namensteil des Mikrofons, sonst Systemstandard")
    lv.add_argument("--apply", action="store_true", help="Vorschlag in wakewords.toml übernehmen")
    th = vo.add_parser("threshold", help="Schwelle der Sprecherprüfung setzen (0,5 bis 0,9; niedriger = lockerer)")
    th.add_argument("value", type=float)
    vo.add_parser("reset")
    ct = vo.add_parser("clone-test", help="Hörvergleich: derselbe Satz mit Piper und mit deiner geklonten Stimme (alles lokal, ohne Netz)")
    ct.add_argument("text", nargs="*", help="Satz (Standard: ein Beispielsatz)")
    ct.add_argument("--out", help="Namensteil des Ausgabegeräts, sonst Systemstandard")
    rec = vo.add_parser("record", help="Absätze für den Stimmklon aufnehmen (nur lokal, voice-data/)")
    rec.add_argument("--mic", help="Namensteil des Mikrofons, sonst Systemstandard")
    rec.add_argument("--redo", action="store_true", help="Schon vorhandene Aufnahmen neu sprechen")
    rec.add_argument("--auto", action="store_true", help="Ende eines Absatzes automatisch per Stille statt per Enter")
    sub.add_parser("doctor", help="Prüft, ob alles installiert und eingerichtet ist")
    sub.add_parser("help", help="Übersicht aller Befehle mit Beispielen")
    cl = sub.add_parser("claude", help="Claude CLI prüfen, Modus C ein-/ausschalten").add_subparsers(dest="sub")
    cl.add_parser("check", help="Zeigt CLI, Anmeldung und Schalter")
    cl.add_parser("enable", help="Modus C einschalten (mit Rückfrage)")
    cl.add_parser("disable", help="Modus C sofort ausschalten")
    cl.add_parser("folders", help="Für Claude freigegebene Ordner anzeigen")
    ca = cl.add_parser("add", help="Einen Ordner für Claude freigeben (mit Rückfrage)")
    ca.add_argument("name")
    ca.add_argument("path")
    cl.add_parser("remove", help="Die Freigabe eines Ordners sofort entziehen").add_argument("name")
    sub.add_parser("setup", help="Stand der Einrichtung (Systemcheck, Stimme, Wake Words, Notaus) anzeigen")
    ap = sub.add_parser("app", help="Die Oberfläche öffnen: startet Sprache und API im Hintergrund und beendet sie beim Schließen des Fensters")
    ap.add_argument("--no-voice", action="store_true", help="nur API und Fenster, ohne Sprachdienst")
    sub.add_parser("serve", help="Backend-API für die Oberfläche (WebSocket nur auf 127.0.0.1); Strg+C beendet")
    sub.add_parser("gpu", help="Grafikkarten anzeigen und wie sie genutzt werden (Einstellung: [gpu] in config.toml)")
    args = p.parse_args(argv)
    if args.cmd == "help":
        print(HELP)
        return 0
    if args.cmd == "app":
        from . import appstart
        return appstart.run(__import__("pathlib").Path(__file__).resolve().parents[2], voice=not args.no_voice)
    if args.cmd == "serve":
        return _serve(Config.load())
    if args.cmd == "gpu":
        from . import gpu
        try:
            gpus, plan = _gpu_plan(Config.load())
        except ValueError as e:
            print(f"[gpu] in config.toml: {e}")
            return 2
        print(gpu.describe(gpus, plan))
        return 0
    cfg = Config.load()

    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    if args.cmd in ("kill", "resume"):
        from .safety import killswitch
        if args.cmd == "kill":
            killswitch.trigger(root)
            print("NOTAUS ausgelöst. kushim stoppt. Aufheben mit: kushim resume")
        else:
            killswitch.clear(root)
            print("Notaus aufgehoben.")
        return 0
    if args.cmd == "claude" and getattr(args, "sub", None) in ("folders", "add", "remove"):
        return _claude_dev(args, cfg, root)
    if args.cmd == "claude":
        from .claude_cli import base as claude_base
        action = getattr(args, "sub", None) or "check"
        if action == "enable":
            print("Modus C: Fragen, die du an Claude richtest, gehen an Anthropic (über deine angemeldete Claude CLI; kushim speichert keine Zugangsdaten).")
            if input("Einschalten? (j/N): ").strip().lower() not in ("j", "ja", "y", "yes"):
                print("Nicht eingeschaltet.")
                return 1
            cfg.set_claude_enabled(True)
            print("Modus C ist an.")
            return 0
        if action == "disable":
            cfg.set_claude_enabled(False)
            print("Modus C ist aus. Nichts geht mehr an Claude.")
            return 0
        exe = claude_base.find_claude()
        print(f"Claude CLI: {exe if exe else 'nicht gefunden'}")
        if exe:
            auth = claude_base.auth_status(exe)
            print("Angemeldet: " + (f"ja ({'Abo' if auth.subscription else 'Konto: ' + auth.method})" if auth.logged_in else "nein (claude auth login)"))
        print(f"Modus C: {'an' if cfg.claude_enabled else 'aus (kushim claude enable)'}")
        return 0
    if args.cmd == "setup":
        from .setup import status as setup_status
        steps = setup_status.compute(root, lambda: _vault_state(cfg))
        marks = {"done": "[ok]      ", "skipped": "[übersprungen] ", "open": "[offen]   "}
        for s in steps:
            print(f"{marks[s.status]}{s.title}: {s.detail}")
        for note in setup_status.restricted_notes(steps):
            print("Eingeschränkt:", note)
        if setup_status.first_start(steps):
            print("Offene Schritte erscheinen beim Start in der Oberfläche (sobald es sie gibt). Überspringen ändert keine Sicherheitsregel.")
        return 0
    if args.cmd == "doctor":
        from .claude_cli import base as claude_base
        from .doctor import claude_checks, run_checks
        results = run_checks(root, lambda: _vault_state(cfg))
        results += claude_checks(claude_base.find_claude, claude_base.version,
                                 lambda exe: claude_base.auth_status(exe).logged_in, claude_base.MIN_VERSION)
        for c in results:
            print(("[ok]    " if c.ok else "[FEHLT] ") + c.name + ("" if c.ok else f"  -> {c.hint}"))
        return 0 if all(c.ok for c in results) else 1
    if args.cmd == "voice" and args.sub == "record":
        from .voice import audio
        from .voice.recorder import record_session
        mic = audio.Mic(audio.find_device(args.mic, "input"), rate=24_000, frame=1920)
        from .voice.recorder import EnterController
        record_session(root / "voice-data" / "clone", iter(mic), redo=args.redo, flush=mic.flush,
                       controller=None if args.auto else EnterController())
        return 0
    if args.cmd == "voice" and args.sub == "clone-test":
        from .voice import audio, clone
        from .voice.tts import PiperEngine
        text = " ".join(args.text) or "Hallo, ich bin kushim. Schön, dass du da bist. Die Hauptstadt von Frankreich ist Paris."
        why = clone.missing(root, cfg.voice_clone_ref)
        if why:
            print(f"Nicht möglich: {why}")
            return 1
        dev = audio.find_device(args.out, "output")
        piper = PiperEngine.from_local(str(root / "models" / "piper" / "de_DE-thorsten-high.onnx"))
        engine = clone.build(root, piper, cfg.voice_clone_ref, on_note=print)
        print("1) Piper (Standardstimme):")
        audio.play_wav(piper.synthesize(text), dev)
        print("2) Deine geklonte Stimme (erster Satz braucht einige Sekunden, das Modell lädt) ...")
        audio.play_wav(engine.synthesize(text), dev)
        print("Gefällt sie dir? Einschalten: in config.toml  [voice]  clone = true   (Piper bleibt als Ersatz, falls der Klon ausfällt).")
        getattr(getattr(engine, "primary", None), "close", lambda: None)()
        return 0
    if args.cmd == "voice":
        from .voice import audio, voiceprint
        from .voice.embedder import SherpaEmbedder
        from .voice.enrollment import enroll as run_quick_enroll, frames_recorder
        from .voice.verify import AudioVerifier
        if args.sub == "level":
            from dataclasses import replace
            from .voice import levels, wakeconfig
            frames = iter(audio.Mic(audio.find_device(args.mic, "input")))
            input("Gleich 3 Sekunden Ruhe messen. Sei still, dann Enter: ")
            noise = levels.frame_rms([next(frames) for _ in range(38)])
            input("Jetzt 6 Sekunden normal sprechen, wie bei einem Befehl (z. B. einen Satz mit kurzen Pausen). Enter zum Start: ")
            speech = levels.frame_rms([next(frames) for _ in range(75)])
            try:
                sg = levels.suggest(noise, speech)
            except ValueError as e:
                print(f"Keine Auswertung möglich: {e}")
                return 1
            cur = wakeconfig.load(root).settings
            print(f"Ruhe (95 %): {sg.noise_p95}; Sprechen: untere Hälfte ab {sg.speech_p25}, Median {sg.speech_p50} ({sg.speech_frames} Frames).")
            print(f"speech_level:    jetzt {cur.speech_level:g}, Vorschlag {sg.speech_level:g}")
            print(f"barge_in_level:  jetzt {cur.barge_in_level:g}, Vorschlag {sg.barge_in_level:g}")
            if sg.warning:
                print("Hinweis:", sg.warning)
            if args.apply:
                cfgw = wakeconfig.load(root)
                wakeconfig.save(root, replace(cfgw, settings=replace(cfgw.settings, speech_level=float(sg.speech_level),
                                                                    barge_in_level=float(sg.barge_in_level))))
                print("Übernommen in wakewords.toml (gilt ab dem nächsten Start von kushim talk).")
            else:
                print("Übernehmen mit: kushim voice level --apply")
            return 0
        model = root / "models" / "speaker" / "wespeaker_en_voxceleb_CAM++_LM.onnx"
        with _vault(cfg) as store:
            if args.sub == "status":
                vp = voiceprint.load(store)
                if vp is None:
                    print("Stimmprofil: keines")
                else:
                    stats = getattr(vp, "stats", {})
                    extra = (f", {stats['prototypes']} Prototypen aus {stats['recordings']} Aufnahmen, "
                             f"Abstand zu Fremden {stats['separation']:+.2f}") if stats else " (älteres Format, bitte neu einschreiben)"
                    print(f"Stimmprofil: vorhanden, Schwelle {vp.threshold:.2f}{extra}")
            elif args.sub == "threshold":
                try:
                    old = voiceprint.set_threshold(store, args.value)
                except ValueError as e:
                    print(f"Nicht geändert: {e}")
                    return 1
                print(f"Schwelle {old:.2f} -> {args.value:.2f}. Gilt ab dem nächsten Start von `kushim talk`. "
                      "Niedriger heißt: auch fremde Stimmen kommen eher durch; prüfe das mit `voice test`.")
            elif args.sub == "reset":
                voiceprint.clear(store)
                print("Stimmprofil gelöscht. kushim talk startet erst nach erneutem Einschreiben.")
            else:
                embed = SherpaEmbedder.from_local(str(model))
                if args.sub == "enroll":
                    rec_dir = root / "voice-data" / "clone"
                    if args.quick:
                        frames = iter(audio.Mic(audio.find_device(args.mic, "input")))
                        print("Kurzes Einschreiben (5 Sätze, weniger robust). Aufnahmen bleiben im Speicher.")
                        res = run_quick_enroll(frames_recorder(frames), embed)
                        voiceprint.save(store, res.verifier, model.name)
                        print(f"Gespeichert im Vault. Proben: {res.used}, Schwelle {res.threshold:.2f}.")
                        return 0
                    if args.record or len(list(rec_dir.glob("*.wav"))) < 3:
                        from .voice.recorder import record_session
                        print("Aufnahme der 10 Absätze (ca. 5 Minuten). Danach wird daraus dein Stimmprofil berechnet.")
                        mic = audio.Mic(audio.find_device(args.mic, "input"), rate=24_000, frame=1920)
                        from .voice.recorder import EnterController
                        record_session(rec_dir, iter(mic), redo=args.record, flush=mic.flush,
                                       controller=None if args.auto else EnterController())
                    paths = sorted(rec_dir.glob("*.wav"))
                    if len(paths) < 3:
                        print("Zu wenige Aufnahmen. Nochmal: kushim voice enroll --record")
                        return 1
                    from .voice.enrollment import cohort_audio, enroll_from_recordings
                    from .voice.recorder import load_paragraphs
                    print("Berechne Stimmabdrücke ...")
                    cohort = cohort_audio(root, load_paragraphs(root))
                    try:
                        profile = enroll_from_recordings(paths, embed, cohort, model.name)
                    except ValueError as e:
                        print(f"Einschreiben nicht möglich: {e}")
                        return 1
                    voiceprint.save_profile(store, profile)
                    st = profile.stats
                    print(f"Gespeichert im Vault: {st['prototypes']} Prototypen aus {st['recordings']} Aufnahmen "
                          f"({st['windows']} Stimmabdrücke).")
                    print(f"Deine Werte (zurückgehalten): Median {st['target_median']}, schwächste 10 % ab {st['target_p10']}. "
                          f"Fremde Vergleichsstimmen: obere 5 % bei {st['cohort_p95']}. Schwelle: {profile.threshold:.2f}.")
                    if st["separation"] < 0.1:
                        print("ACHTUNG: Deine Stimme und die Vergleichsstimmen liegen eng beieinander "
                              f"(Abstand {st['separation']:+.2f}). Die Prüfung ist dann nur begrenzt sicher; "
                              "`voice test` zeigt dir die echten Werte, auch mit einer zweiten Person.")
                else:
                    vp = voiceprint.load(store)
                    if vp is None:
                        print("Kein Stimmprofil. Erst: kushim voice enroll")
                        return 1
                    ver = AudioVerifier(vp, embed)
                    frames = iter(audio.Mic(audio.find_device(args.mic, "input")))
                    print("Sprich einen oder mehrere Sätze (Test). Strg+C beendet.")
                    try:
                        while True:
                            v = ver.check(frames_recorder(frames)())
                            print(f"Ähnlichkeit {v.score:.2f} (Schwelle {vp.threshold:.2f}), {v.seconds:.1f} s, "
                                  f"{v.windows} Fenster: {'akzeptiert' if v.accepted else 'abgelehnt'}"
                                  f"{' (stark)' if v.strong else ''}")
                    except KeyboardInterrupt:
                        pass
        return 0
    if args.cmd == "start":
        return _start(args, cfg, root)
    if args.cmd == "talk":
        from .safety.killswitch import is_triggered
        from .voice import audio, voiceprint, wakeconfig
        from .voice.audio import UtteranceCollector
        from .voice.bargein import BargeIn
        from .voice.embedder import SherpaEmbedder
        from .voice.talk import TalkLoop, build_live
        from .voice.wakebuild import build_detector
        if is_triggered(root):
            print("Notaus ist aktiv. Erst bewusst aufheben: kushim resume")
            return 1
        try:
            wcfg = (wakeconfig.from_names(args.wake_words.split(","), root) if args.wake_words
                    else wakeconfig.load(root))
        except ValueError as e:
            print(f"Wake-Word-Konfiguration: {e}")
            return 2
        with _vault(cfg) as store:
            profile = voiceprint.load(store)
        if profile is None:
            print("Kein Stimmprofil. kushim hört nur auf deine Stimme: erst `kushim voice enroll`.")
            return 1
        embed = SherpaEmbedder.from_local(str(root / "models" / "speaker" / "wespeaker_en_voxceleb_CAM++_LM.onnx"))
        from .voice.verify import AudioVerifier
        verifier = AudioVerifier(profile, embed)
        try:
            _, plan = _gpu_plan(cfg)
        except ValueError as e:
            print(f"[gpu] in config.toml: {e}")
            return 2
        api = None
        try:
            from .tasks import TaskRegistry
            tasks = TaskRegistry()
            pipeline, kill, mic, ack = build_live(root, audio.find_device(args.out, "output"),
                                                  audio.find_device(args.mic, "input"),
                                                  verifier=verifier, tasks=tasks, clone=cfg.voice_clone, clone_ref=cfg.voice_clone_ref,
                                                  on_note=lambda s: print(f"[Hinweis] {s}"),
                                                  wake_names=[w.name for w in wcfg.enabled()],
                                                  whisper_device=plan.whisper_device,
                                                  whisper_index=plan.whisper_index)
            det = build_detector(wcfg, root)
            wait_ms = int(wcfg.settings.listen_seconds * 1000)
            first_ms = int(wcfg.settings.command_wait_seconds * 1000)
            end_ms = int(wcfg.settings.end_silence_seconds * 1000)
            max_ms = int(wcfg.settings.max_seconds * 1000)
            st = wcfg.settings
            follow_ms = int(st.follow_up_seconds * 1000)
            out = lambda r: print(f"Du: {r.heard}\nkushim: {r.reply or '(' + r.outcome + ')'}"
                                  + (" [unterbrochen]" if r.outcome == "interrupted" else "")
                                  + (f"  [{r.detail}]" if r.detail else ""))
            barge = BargeIn(level=st.barge_in_level, min_ms=st.barge_in_ms) if st.barge_in else None
            utter = lambda wait: UtteranceCollector(wait_ms=wait, silence_ms=end_ms, max_ms=max_ms, energy_threshold=st.speech_level)
            from .voice import statefile
            from .voice.transcript import Transcript
            publisher = statefile.StatePublisher(root, pending=tasks.pending_approvals)
            transcript = Transcript()

            def on_result(r):
                out(r)
                transcript.add(r)
                if r.outcome == "rejected_speaker":
                    publisher.alarm()
            pipeline.dialog._on_change = lambda s: publisher.phase(s.value)
            if args.ui:                                   # die API muss im selben Prozess laufen: nur hier liegen Aufgaben und Verlauf
                from .api.feedback_api import register_feedback
                from .api.memory_api import register_memory
                from .api.safety_view import register_safety_view
                from .api.transcript_api import register_transcript
                from .config import LiveConfig

                def extra(core, store):
                    from .api.folders_api import register_folders
                    from .claude_cli import folders as cfolders
                    register_folders(core, Config.load, lambda raw: cfolders.validate_path(raw, cfolders.vault_path(cfg.memory_location)),
                                     audit=store.audit if store else None)
                    if store is not None:
                        register_memory(core, store)
                        register_feedback(core, transcript, store)
                    register_safety_view(core, LiveConfig(), root, store=store)
                    register_transcript(core, transcript)
                api = _api_start(cfg, root, extra)
            loop = TalkLoop(mic, pipeline, kill, wake=lambda f: det.process(f) is not None, ack=ack,
                            flush=mic.flush, new_collector=lambda: utter(wait_ms),
                            on_result=on_result,
                            on_frame=lambda f, p: publisher.phase(p, statefile.frame_level(f)),
                            first_collector=lambda: utter(first_ms),
                            follow_collector=(lambda: utter(follow_ms)) if follow_ms > 0 else None,
                            barge=barge, preroll_frames=round(st.preroll_seconds / 0.08),
                            announce=pipeline.chat.announcement,          # verspätete Antworten von Claude
                            say=pipeline.say_text, on_note=lambda s: print(f"[Hinweis] {s}"))
            print("Wake Words: " + ", ".join(w.name for w in wcfg.enabled())
                  + ". Notaus: 'Notaus' sagen oder die Verknüpfung. Strg+C beendet.")
            if follow_ms > 0:
                print(f"Gespräch: nach einer Antwort hörst du {st.follow_up_seconds:g} s lang ohne Wake Word zu; "
                      "\"das war's\" oder Stille beendet es.")
            if barge is not None:
                print("Unterbrechen: einfach dazwischensprechen (Kopfhörer empfohlen; mit Lautsprechern kann kushim sich "
                      "selbst hören: barge_in_level erhöhen oder barge_in = false in wakewords.toml).")
            reason = loop.run()
            publisher.clear()
            print("Ende:", reason)
        except KeyboardInterrupt:
            pass
        finally:
            if api is not None:
                _api_stop(*api)
        return 0
    if args.cmd == "memory":
        if args.sub == "init":
            with open_store(cfg, create=True) as s:
                print(f"Vault bereit: {cfg.memory_location} (id {s.manifest.vault_id})")
        elif args.sub == "info":
            with open_store(cfg) as s:
                print(cfg.memory_location, s.manifest, s.counts())
        elif args.sub == "backup":
            print("Backup:", backup(cfg))
        elif args.sub == "migrate":
            dst = migrate(cfg, args.to)
            print(f"Migriert nach {dst}. Alter Vault bleibt als Rollback erhalten.")
    elif args.cmd == "key":
        if args.sub == "export":
            with open_store(cfg) as s:
                print(s.manifest.vault_id, get_or_create_key(s.manifest.vault_id))
        else:
            store_key(args.vault_id, args.hexkey)
            print("Schlüssel gespeichert.")
    return 0




def main(argv: list[str] | None = None) -> int:
    """Strg+C bricht den laufenden Befehl ab (laufende Prozesse werden dabei beendet), ohne Fehlermeldung."""
    try:
        return _main(argv)
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
