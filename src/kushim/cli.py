"""kushim CLI (Gedächtnis-Verwaltung; Audio/UI folgen)."""
from __future__ import annotations

import argparse

from .config import Config, NotSaved
from .memory import open_store
from .memory.keys import get_or_create_key, store_key
from .memory.migrate import backup, migrate


HELP = """kushim: Sprachassistent mit Claude Code als Gehirn. Wake Word, Spracherkennung und Stimme laufen lokal.

Starten
  kushim                       Alles starten: Claude Code (eigenes Fenster), Zuhören und Oberfläche
  kushim start [ordner]        Dasselbe in einem bestimmten freigegebenen Ordner [--no-ui] [--mic NAME] [--out NAME]
  kushim kill                  NOTAUS: stoppt alle kushim-Dienste
  kushim resume                Notaus bewusst aufheben
  kushim restart               laufendes kushim start neu starten (nur auf ausdrücklichen Befehl)

Mikrofon
  kushim voice level           Mikrofonpegel messen, Schwellen vorschlagen [--apply] [--mic NAME]

Einzelteile (startet `kushim` sonst selbst)
  kushim talk                  Nur Zuhören (Claude Code mit Channel muss schon laufen) [--wake-words "hey kushim,kushim"]
  kushim app                   Nur die Oberfläche öffnen (--no-voice: ohne Mikrofon)
  kushim serve                 Nur die API für die Oberfläche (127.0.0.1, Port/Token in run/api.json)
  kushim gpu                   Grafikkarten zeigen und welche Whisper nutzt

Gedächtnis und Schlüssel
  kushim memory init           Vault anlegen (erzeugt auch den Schlüssel)
  kushim memory info           Vault-Ort und Zustand
  kushim memory backup         Verschlüsselte Sicherung erstellen
  kushim memory migrate --to local:D:/kushim-vault
  kushim key export            Schlüssel zum Sichern anzeigen (nur im eigenen Terminal)
  kushim key import <vault_id> <hexkey>

Prüfen und Hilfe
  kushim claude [check]        Claude CLI und Anmeldung prüfen
  kushim claude show           Die laufende Claude-Sitzung von kushim wieder in einem Fenster zeigen
  kushim claude folders|add|remove  Sichere Arbeitsordner für Claude verwalten
  kushim claude approvals           Protokoll der Freigaben (Oberfläche)
  kushim doctor                Prüft, ob alles installiert und eingerichtet ist
  kushim setup                 Stand der Einrichtung: Systemcheck, Mikrofon, Wake Words, Notaus
  kushim help                  Diese Übersicht
  kushim <befehl> --help       Optionen eines Befehls

Einstellungen: config.toml (Vault, Grafikkarte, Claude-Ordner, gemerkte Geräte [audio]), wakewords.toml (Wake Words, Zeiten). Anleitung: README.md
"""


CLAUDE_SECTION_NOT_SAVED = ("config.toml hat eine ungewöhnliche Form und wurde nicht geändert. "
                            "Bitte den Abschnitt [claude] als normale Tabelle schreiben.")


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
        try:
            cfg.set_claude_folders([f.entry() for f in known] + [cfolders.Folder(args.name, path).entry()])
        except NotSaved:
            print(CLAUDE_SECTION_NOT_SAVED)
            return 3
        print(f"Ordner «{args.name}» ist freigegeben.")
        return 0
    if action == "remove":
        if not any(f.name == args.name for f in known):
            print("Diesen Ordner gibt es nicht.")
            return 2
        try:
            cfg.set_claude_folders([f.entry() for f in known if f.name != args.name])
        except NotSaved:
            print(CLAUDE_SECTION_NOT_SAVED)
            return 3
        print(f"Freigabe für «{args.name}» entzogen.")
        return 0


def _notice() -> str | None:
    """Ein abgelegter Hinweis für die Stimme (z. B. Sprachkanal aus), jeder genau einmal; sonst None."""
    from .channel import launch
    try:
        return launch.NOTICES.popleft()
    except IndexError:
        return None


def _watch_channel(folder, started: float, done, check=None) -> str:
    """Nach dem Start: Ist der Channel in Claude Code an? Wenn sicher aus, einmal im Terminal und einmal per Stimme sagen.
    Liest nur die zwei Marker im MCP-Protokoll dieser Sitzung (channel/claude_log.py)."""
    from .channel import claude_log, launch
    check = check or claude_log.check
    try:
        state = check(claude_log.log_dir(folder), started)
    except Exception:                                  # noqa: BLE001 (nur ein Hinweis: darf den Start nie stören)
        return "unknown"
    if state == "off" and not done.is_set():
        from .voice import earcon
        print("\n" + claude_log.TERMINAL_HINT)
        launch.NOTICES.append(earcon.mark(claude_log.SPOKEN_HINT))     # Systemansage: mit Signalton
    return state


def _pause() -> None:
    """Wartet auf einen Tastendruck (Windows: eine beliebige Taste; sonst Enter). Nie über eine Shell."""
    try:
        import msvcrt
    except ImportError:
        msvcrt = None
    try:
        if msvcrt is not None:
            print("Eine Taste drücken, um das Fenster zu schließen.", flush=True)
            msvcrt.getch()
        else:
            input("Enter drücken, um das Fenster zu schließen.")
    except (EOFError, OSError):
        pass


def _start(args, cfg: Config, root) -> int:
    """`kushim start`; im durch Neustart erzeugten Prozess (launch.RESTARTED_ENV) bleibt das Fenster bei einem Abbruch
    (Rückgabe ungleich 0, z. B. Notaus, nicht angemeldet, Ordner unzulässig) offen, bis eine Taste gedrückt wird. Sonst
    schlösse sich die neue Konsole sofort, und die Meldung wäre weg. Das Kennzeichen gilt nur für diesen Prozess."""
    import os
    from .channel import launch
    after_restart = os.environ.pop(launch.RESTARTED_ENV, None) == "1"
    try:
        rc = _start_run(args, cfg, root)
    except Exception:                                 # noqa: BLE001 (nur nach Neustart: Fehler sichtbar lassen, dann Ende)
        if not after_restart:
            raise
        import traceback
        traceback.print_exc()
        _pause()
        return 1
    if rc and after_restart:
        _pause()
    return rc


def _start_run(args, cfg: Config, root) -> int:
    """`kushim start [ordner]`: Claude Code mit dem kushim-Channel im freigegebenen Ordner (eigenes Fenster), dann `kushim talk`."""
    from .channel import launch
    from .claude_cli import base as claude_base
    from .claude_cli import folders as cfolders
    from .safety.killswitch import is_triggered
    if is_triggered(root):
        print("Notaus ist aktiv. Erst bewusst aufheben: kushim resume")
        return 1
    if _inside_claude_session():
        print("kushim läuft hier innerhalb einer Claude-Code-Sitzung. Dann schaltet Claude Code den kushim-Channel ab "
              "(\"Channels are not currently available\"). Bitte über die Verknüpfung \"kushim start\" oder in einem "
              "eigenen Terminal starten.")
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
    if _token_dir_inside(root, folder):
        print("Achtung: kushims Ordner run/ (Token für Channel und Oberfläche) liegt im Arbeitsordner von Claude. Claude "
              "könnte die Token lesen. Freigaben in der Oberfläche und per Stimme dann nur mit Vorsicht benutzen.")
    try:
        model, effort = launch.check_options(cfg.claude_model, cfg.claude_effort)
    except ValueError as e:
        print(f"[claude] in config.toml: {e}")
        return 2
    import _thread
    import threading
    import time as _time
    from .procflags import kill_tree
    started = _time.time() - 2.0
    restart_asked = threading.Event()
    (root / launch.RESTART_FILE).unlink(missing_ok=True)   # alte Marke gilt nicht für diesen Start
    window = launch.launch(exe, folder, root, model=model, effort=effort)
    print(f"Claude Code startet im Fenster \"kushim-Claude\" im Ordner «{chosen.name}»"
          + (f" (Modell {model}" + (f", Aufwand {effort}" if effort else "") + ")" if model else "") + ".")
    print("Dort einmal den Hinweis zum Entwicklungs-Channel bestätigen; danach hört kushim zu.")
    print("Schließt du das Claude-Fenster, beendet sich alles (Claude, Channel, Zuhören).")
    done = threading.Event()
    threading.Thread(target=_watch_channel, args=(folder, started, done), daemon=True).start()

    def watch_window():                               # Fenster zu: ganzen Ablauf beenden
        window.wait()
        if not done.is_set():
            print("\nClaude-Fenster geschlossen: kushim beendet sich.")
            _thread.interrupt_main()
    threading.Thread(target=watch_window, daemon=True).start()

    def watch_restart():                              # `kushim restart` (nur auf Befehl des Nutzers): sauber beenden, dann neu
        while not done.is_set():
            if launch.restart_requested(root):
                restart_asked.set()
                print()
                print("Neustart angefordert: kushim beendet sich und startet neu.")
                _thread.interrupt_main()
                return
            _time.sleep(1.0)
    threading.Thread(target=watch_restart, daemon=True).start()
    with_ui = not getattr(args, "no_ui", False)       # Standard: mit Oberfläche (Wunsch des Nutzers 2026-11-11)
    talk = ["talk"] + (["--mic", args.mic] if args.mic else []) + (["--out", args.out] if args.out else []) + (["--ui"] if with_ui else [])
    ui_proc: list = []
    if with_ui:
        def ui_closed():
            print()
            print("kushim-Fenster geschlossen: kushim beendet sich.")
            _thread.interrupt_main()
        threading.Thread(target=_open_ui_window, args=(root, done, ui_proc), kwargs={"on_close": ui_closed},
                         daemon=True).start()
    try:
        return _main(talk)
    finally:                                          # kushim endet (Strg+C, "beende dich", Notaus): Claude-Sitzung mit beenden
        done.set()
        for p in ui_proc:                             # das selbst geöffnete App-Fenster mit schließen
            if p.poll() is None:
                kill_tree(p.pid)
        launch.stop(exe, root)
        if window.poll() is None:
            kill_tree(window.pid)
        print("Claude-Sitzung beendet (der Verlauf bleibt in Claude Code erhalten).")
        if restart_asked.is_set() and not is_triggered(root):     # erst nach dem vollständigen Aufräumen (Mikrofon, Port frei)
            try:
                launch.restart(launch.restart_argv(chosen.name, args.mic, args.out, bool(getattr(args, "no_ui", False))))
                print("kushim startet in einem neuen Fenster neu.")
            except OSError as e:
                print(f"Neustart nicht möglich: {e}")


def _open_ui_window(root, done, procs: list, popen=None, wait=None, on_close=None) -> None:
    """Öffnet das App-Fenster, sobald die API von `kushim talk --ui` bereit ist (frisches run/api.json). Fehlt die gebaute
    App oder wird die API nicht bereit, gibt es nur einen Hinweis; Sprache und Claude laufen weiter. Schließt der Nutzer
    das Fenster selbst, ruft `on_close()` auf: dann beendet sich ganz kushim (Wunsch des Nutzers 2026-11-11)."""
    import subprocess
    import time
    from . import appstart
    exe = appstart.ui_path(root)
    if not exe.is_file():
        print("Hinweis: Die Oberfläche ist nicht gebaut (cd ui && npx tauri build --no-bundle). kushim läuft ohne Fenster.")
        return
    since = time.time()
    if not (wait or appstart.wait_for_api)(root, since, alive=lambda: not done.is_set()):
        if not done.is_set():
            print("Hinweis: Die Oberfläche konnte nicht verbinden (API nicht bereit). kushim läuft ohne Fenster.")
        return
    if done.is_set():
        return
    proc = (popen or subprocess.Popen)([str(exe)], cwd=str(root))
    procs.append(proc)
    proc.wait()
    if not done.is_set() and on_close is not None:     # vom Nutzer geschlossen, nicht von kushim beim Beenden
        on_close()


def _device(flag: str | None, saved: str, kind: str, note=print):
    """Gerät für `talk`/`start`: `--mic`/`--out` hat Vorrang (fehlt es, ist das ein Fehler wie bisher); sonst die gemerkte Wahl
    aus `config.toml [audio]`. Ist das gemerkte Gerät nicht (mehr) da, gilt mit einem Hinweis der Systemstandard."""
    from .voice import audio
    if flag:
        return audio.find_device(flag, kind)
    if not saved:
        return None
    try:
        return audio.find_device(saved, kind)
    except LookupError:
        note(f"Gemerktes Gerät ({'Mikrofon' if kind == 'input' else 'Ausgabe'}) nicht gefunden, es gilt der Systemstandard.")
        return None


def _inside_claude_session(env=None) -> bool:
    """Wurde kushim aus einer laufenden Claude-Code-Sitzung gestartet? Dann gilt das neue Claude als Unter-Sitzung und
    Claude Code lädt keine Channels (2026-11-11 so beobachtet mit 2.1.321). Wir umgehen das nicht, sondern sagen es."""
    import os
    env = os.environ if env is None else env
    return bool(env.get("CLAUDE_CODE_CHILD_SESSION") or env.get("CLAUDECODE"))


def _token_dir_inside(root, folder) -> bool:
    """Liegt kushims `run/` (Token für Channel und API) in Claudes Arbeitsordner? (Safety-Audit 2026-11-11, B5)"""
    try:
        (root / "run").resolve().relative_to(folder.resolve())
        return True
    except (ValueError, OSError):
        return False


def _approval_log(cfg: Config):
    """Freigabe-Protokoll im Vault (C5); öffnet den Vault je Eintrag, damit es aus jedem Thread geht."""
    from .channel.approval_log import ApprovalLog
    return ApprovalLog(lambda: open_store(cfg),
                       on_fail=lambda: print("[Hinweis] Freigabe-Protokoll konnte nicht in den Vault geschrieben werden."))


def _vault_state(cfg: Config) -> str:
    """"ok" (Vault da) oder "kein-vault" (für doctor und setup)."""
    try:
        with open_store(cfg):
            return "ok"
    except FileNotFoundError:
        return "kein-vault"


def _folders_ok() -> bool:
    """Ist mindestens ein Arbeitsordner für Claude freigegeben? (Setup-Schritt `folder`, frisch aus config.toml)"""
    from .claude_cli import folders as cfolders
    return bool(cfolders.parse(Config.load().claude_folders))


def _api_start(cfg: Config, root, extra=None, level_test=None):
    """Baut den API-Kern (setup, safety, voice, usage; `extra(core, store)` hängt mehr an) und startet den Server auf 127.0.0.1.
    Port und Token kommen nach run/api.json (nur für die eigene Oberfläche). Gibt (server, store, info) zurück.
    `level_test`: der Pegeltest des Sprachprozesses (nur `kushim talk --ui`, wo die API im selben Prozess läuft)."""
    import json
    from .api.protocol import ApiCore, new_token
    from .api.setup_api import register_setup
    from .api.usage_api import register_usage
    from .api.voice_api import register_voice
    from .api.system_api import register_system
    from .claude_cli.base import ClaudeProbe
    from .net.server import LocalServer
    from .voice.audio import list_devices
    store = None
    try:
        store = open_store(cfg, shared=True)           # die API-Threads dürfen den Vault nur über die Sperre benutzen
    except Exception:
        print("Hinweis: Vault nicht offen, Notaus-Aktionen werden nicht im Audit protokolliert.")
    token = new_token()
    core = ApiCore(token)
    register_voice(core, root, level_test=level_test, audit=store.audit if store else None)
    register_system(core, root)                        # Systemzustand (nur lesen, nur lokale Messwerte)
    register_setup(core, root, lambda: _vault_state(cfg), list_devices=list_devices,
                   audit=store.audit if store else None, claude=ClaudeProbe().get, folders_ok=_folders_ok,
                   load_config=Config.load)
    register_usage(core, root)                         # Verbrauch der kushim-Sitzung (run/usage.json, von der Statuszeile)
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
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:                                       # einfach `kushim`: alles starten
        argv = ["start"]
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
    sub.add_parser("restart", help="laufendes kushim start neu starten (nur auf ausdrücklichen Befehl des Nutzers)")
    st = sub.add_parser("start", help="Claude Code mit dem kushim-Channel im freigegebenen Ordner starten, dann Sprechen per Wake Word")
    st.add_argument("folder", nargs="?", help="Name eines freigegebenen Ordners (kushim claude folders)")
    st.add_argument("--mic", help="Namensteil des Mikrofons, sonst Systemstandard")
    st.add_argument("--out", help="Namensteil des Ausgabegeräts, sonst Systemstandard")
    st.add_argument("--ui", action="store_true", help="(Standard) Oberfläche mitstarten: API auf 127.0.0.1 und App-Fenster")
    st.add_argument("--no-ui", action="store_true", help="ohne Oberfläche starten (nur Claude-Fenster und Sprache)")
    t = sub.add_parser("talk", help="Sprechen per Wake Word (nur das Wake Word wird dauerhaft ausgewertet)")
    t.add_argument("--mic", help="Namensteil des Mikrofons, sonst Systemstandard")
    t.add_argument("--out", help="Namensteil des Ausgabegeräts, sonst Systemstandard")
    t.add_argument("--ui", action="store_true", help="Backend-API für die Oberfläche mitstarten (127.0.0.1): Freigabe-Leiste, Zustand, Notaus")
    t.add_argument("--wake-words", help="Komma-getrennt, überschreibt wakewords.toml nur für diesen Start (z. B. \"hey kushim,kushim\")")
    vo = sub.add_parser("voice", help="Mikrofonpegel messen und Schwellen vorschlagen").add_subparsers(dest="sub", required=True)
    lv = vo.add_parser("level", help="Mikrofonpegel messen und Schwellen fürs Sprechen/Unterbrechen vorschlagen")
    lv.add_argument("--mic", help="Namensteil des Mikrofons, sonst Systemstandard")
    lv.add_argument("--apply", action="store_true", help="Vorschlag in wakewords.toml übernehmen")
    sub.add_parser("doctor", help="Prüft, ob alles installiert und eingerichtet ist")
    sub.add_parser("help", help="Übersicht aller Befehle mit Beispielen")
    cl = sub.add_parser("claude", help="Claude CLI prüfen, Sitzung zeigen, Ordner verwalten").add_subparsers(dest="sub")
    cl.add_parser("check", help="Zeigt CLI und Anmeldung")
    cl.add_parser("show", help="Die laufende kushim-Sitzung von Claude Code wieder in einem Fenster zeigen")
    cl.add_parser("folders", help="Für Claude freigegebene Ordner anzeigen")
    ca = cl.add_parser("add", help="Einen Ordner für Claude freigeben (mit Rückfrage)")
    ca.add_argument("name")
    ca.add_argument("path")
    cl.add_parser("remove", help="Die Freigabe eines Ordners sofort entziehen").add_argument("name")
    cl.add_parser("approvals", help="Protokoll der Freigaben (per Stimme und Oberfläche) anzeigen").add_argument(
        "--limit", type=int, default=20)
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
    if args.cmd == "claude" and getattr(args, "sub", None) == "approvals":
        from .channel import approval_log
        with _vault(cfg) as store:
            rows = approval_log.recent(store, max(1, min(args.limit, 200)))
        if not rows:
            print("Noch keine Freigaben protokolliert.")
        for row in rows:
            print(approval_log.format_row(row))
        return 0
    if args.cmd == "claude":
        from .claude_cli import base as claude_base
        action = getattr(args, "sub", None) or "check"
        if action == "show":
            from .channel import launch
            exe = claude_base.find_claude()
            if exe is None:
                print("Claude Code nicht gefunden.")
                return 1
            if launch.show(exe, root) is None:
                print("Keine kushim-Sitzung bekannt. Starten mit: kushim start")
                return 1
            print("Fenster \"kushim-Claude\" geöffnet.")
            return 0
        exe = claude_base.find_claude()
        print(f"Claude CLI: {exe if exe else 'nicht gefunden'}")
        if exe:
            auth = claude_base.auth_status(exe)
            print("Angemeldet: " + (f"ja ({'Abo' if auth.subscription else 'Konto: ' + auth.method})" if auth.logged_in else "nein (claude auth login)"))
        return 0
    if args.cmd == "setup":
        from .claude_cli.base import ClaudeProbe
        from .setup import status as setup_status
        steps = setup_status.compute(root, lambda: _vault_state(cfg), claude=ClaudeProbe(spawn=lambda fn: fn()).get,
                                     folders=_folders_ok)                      # im Terminal: auf das Ergebnis warten
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
    if args.cmd == "voice":
        from .voice import audio
        if args.sub == "level":
            from dataclasses import replace
            from .voice import levels, wakeconfig
            frames = iter(audio.Mic(_device(args.mic, cfg.audio_mic, "input")))
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
        return 0
    if args.cmd == "restart":
        from .channel import launch
        launch.request_restart(root)
        print("Neustart angefordert: das laufende kushim start beendet sich und startet in einem neuen Fenster neu. "
              "Dort den Hinweis zum Entwicklungs-Channel noch einmal bestätigen.")
        return 0
    if args.cmd == "start":
        return _start(args, cfg, root)
    if args.cmd == "talk":
        from .safety.killswitch import is_triggered
        from .voice import audio, wakeconfig
        from .voice.audio import UtteranceCollector
        from .voice.bargein import BargeIn
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
        try:
            _, plan = _gpu_plan(cfg)
        except ValueError as e:
            print(f"[gpu] in config.toml: {e}")
            return 2
        api = None
        try:
            from .tasks import TaskRegistry
            from .voice.talklog import TalkLog
            tasks = TaskRegistry()
            talklog = TalkLog(root / "run" / "talk.log")       # Gesprächsprotokoll zur Fehlersuche (lokal, ohne Audio)
            talklog.write("start")

            def note(s: str) -> None:
                print(f"[Hinweis] {s}")
                talklog.write("note", text=s)
            pipeline, kill, mic, ack = build_live(root, _device(args.out, cfg.audio_out, "output", note),
                                                  _device(args.mic, cfg.audio_mic, "input", note),
                                                  tasks=tasks,
                                                  on_note=note,
                                                  wake_names=[w.name for w in wcfg.enabled()],
                                                  whisper_device=plan.whisper_device,
                                                  whisper_index=plan.whisper_index)
            pipeline.handle = talklog.timed(pipeline.handle, metrics=lambda: pipeline.metrics)   # Ergebnis, Dauer, Kennzahlen
            raw_ack = ack

            def ack():
                talklog.write("wake")                           # Wake Word erkannt, "Ja?" kommt
                raw_ack()
            det = build_detector(wcfg, root)
            wait_ms = int(wcfg.settings.listen_seconds * 1000)
            first_ms = int(wcfg.settings.command_wait_seconds * 1000)
            end_ms = int(wcfg.settings.end_silence_seconds * 1000)
            max_ms = int(wcfg.settings.max_seconds * 1000)
            st = wcfg.settings
            follow_ms = int(st.follow_up_seconds * 1000)
            out = lambda r: print(f"kushim (Meldung): {r.reply}" + (" [unterbrochen]" if r.outcome == "announce_interrupted" else "")
                                  if r.outcome in ("announced", "announce_interrupted") else
                                  f"Du: {r.heard}\nkushim: {r.reply or '(' + r.outcome + ')'}"
                                  + (" [unterbrochen]" if r.outcome == "interrupted" else "")
                                  + (f"  [{r.detail}]" if r.detail else ""))
            barge = (BargeIn(level=st.barge_in_level, min_ms=st.barge_in_ms, echo_guard=st.echo_schutz,
                             echo_factor=st.echo_factor, echo_ignore_ms=st.echo_ignore_ms) if st.barge_in else None)
            utter = lambda wait: UtteranceCollector(wait_ms=wait, silence_ms=end_ms, max_ms=max_ms, energy_threshold=st.speech_level)
            from .voice import statefile
            from .voice.levels import LevelTest
            from .voice.transcript import Transcript
            publisher = statefile.StatePublisher(root, pending=tasks.pending_approvals)
            transcript = Transcript()
            pipeline.notes = transcript                   # Zeile „Du“ direkt nach der Spracherkennung (nur im Speicher)
            level_test = LevelTest()                      # Pegeltest der Oberfläche: nur Pegelzahlen aus den Frames dieser Schleife

            def on_frame(f, p):
                publisher.phase(p, statefile.frame_level(f))
                level_test.feed(f, p)

            def wake(f) -> bool:
                event = det.process(f)
                if event is None:
                    return False
                publisher.wake(getattr(event, "name", ""))    # Zähler und Name für den Wake-Word-Test (nie Audio)
                return True

            def on_result(r):
                out(r)
                if r.outcome in ("announced", "announce_interrupted"):
                    talklog.announced(r.outcome, r.spoken)       # nur Ergebnis-Code und Satzzahl
                    return                                    # Meldung ohne Nutzereingabe: keine Zeile „Du“
                transcript.add(r)                         # ergänzt den Eintrag der Runde (r.entry) um die Antwort
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
                    bridge = getattr(pipeline.chat, 'bridge', None)
                    if bridge is not None:                      # Freigaben von Claude Code (C0), protokolliert wie per Stimme (C5)
                        from .api.approvals_api import register_approvals
                        register_approvals(core, bridge, root, on_decision=_approval_log(cfg))
                        from .api.stage_api import register_stage       # Ansichten von Claude (zeige) für die Bühne
                        register_stage(core, bridge.stage, root)
                api = _api_start(cfg, root, extra, level_test=level_test)
            loop = TalkLoop(mic, pipeline, kill, wake=wake, ack=ack,
                            flush=mic.flush, new_collector=lambda: utter(wait_ms),
                            on_result=on_result,
                            on_frame=on_frame,
                            first_collector=lambda: utter(first_ms),
                            follow_collector=(lambda: utter(follow_ms)) if follow_ms > 0 else None,
                            barge=barge, preroll_frames=round(st.preroll_seconds / 0.08),
                            announce=lambda: _notice() or pipeline.chat.announcement(),   # Hinweise von kushim start, verspätete Antworten
                            say=pipeline.say_text, on_note=note, on_barge=talklog.barge)
            print("Wake Words: " + ", ".join(w.name for w in wcfg.enabled())
                  + ". Notaus: 'Notaus' sagen oder die Verknüpfung. Strg+C beendet.")
            if follow_ms > 0:
                print(f"Gespräch: nach einer Antwort hörst du {st.follow_up_seconds:g} s lang ohne Wake Word zu; "
                      "\"das war's\" oder Stille beendet es.")
            if barge is not None:
                print("Unterbrechen: einfach dazwischensprechen (Kopfhörer empfohlen; mit Lautsprechern kann kushim sich "
                      "selbst hören: echo_schutz = true oder barge_in_level erhöhen in wakewords.toml).")
            talklog.write("ready", wake_words=", ".join(w.name for w in wcfg.enabled()),
                          channel=pipeline.chat.bridge.available())
            reason = loop.run()
            publisher.clear()
            print("Ende:", reason)
            talklog.write("end", reason=reason)
        except KeyboardInterrupt:
            talklog.write("end", reason="strg+c oder Fenster geschlossen")
        except Exception as e:                            # noqa: BLE001 (protokollieren, dann wie bisher abbrechen)
            talklog.write("error", where="talk", error=f"{type(e).__name__}: {e}")
            raise
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
            from .memory.migrate import ConfigNotSwitched
            try:
                dst = migrate(cfg, args.to)
            except ConfigNotSwitched as e:
                print(f"Die Vault-Kopie liegt geprüft in {e.dst}, aber config.toml hat eine ungewöhnliche Form und wurde nicht "
                      "geändert: kushim benutzt weiter den alten Vault (er bleibt unverändert). Bitte den Abschnitt [memory] als "
                      "normale Tabelle schreiben und die Migration wiederholen oder location von Hand setzen.")
                return 3
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
