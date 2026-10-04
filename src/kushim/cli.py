"""kushim CLI (Gedächtnis-Verwaltung; Audio/UI folgen)."""
from __future__ import annotations

import argparse

from .config import Config
from .memory import open_store
from .memory.keys import get_or_create_key, store_key
from .memory.migrate import backup, migrate


HELP = """kushim: persönlicher, lokaler Assistent. Alles läuft auf diesem Rechner.

Täglich
  kushim start                 Lokale Dienste starten (Ollama, nur 127.0.0.1); Strg+C beendet
  kushim talk                  Sprechen per Wake Word
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

Sprachmodell und Grafikkarten
  kushim gpu                   Grafikkarten zeigen und wie Whisper und das Sprachmodell verteilt werden
  kushim llm                   Aktuelles Modell, vorheriges und installierte Modelle zeigen
  kushim llm set <name>        Modell wechseln (z. B. qwen3.5:9b); laden mit install.ps1 -Llm <name>
  kushim llm test [name]       Modell kurz ausprobieren und die Antwortzeit messen
  kushim llm back              Zurück zum vorherigen Modell

Gedächtnis und Schlüssel
  kushim memory init           Vault anlegen (erzeugt auch den Schlüssel)
  kushim memory info           Vault-Ort und Zustand
  kushim memory backup         Verschlüsselte Sicherung erstellen
  kushim memory migrate --to local:D:/kushim-vault
  kushim key export            Schlüssel zum Sichern anzeigen (nur im eigenen Terminal)
  kushim key import <vault_id> <hexkey>

Prüfen und Hilfe
  kushim research <frage>      Recherche: erst Claude (Internet), Ersatz Wikipedia; Vorschau und Bestätigung
  kushim claude [check|enable|disable]  Claude CLI und Anmeldung prüfen; Modus C ein/aus
  kushim claude folders|add|remove  Ordner für Claude freigeben (Entwicklung nur dort, immer eigener Worktree)
  kushim claude start [auftrag]     Claude arbeitet am Projekt (Vorschau, Freigabe); status|stop|result|answer
  kushim search <frage> [--llm]  Websuche (Wikipedia) mit Vorschau und Bestätigung; erst `tools enable web.search`
  kushim tools                 Werkzeuge anzeigen; enable|disable <name> schaltet ein/aus (alle standardmäßig aus)
  kushim doctor                Prüft, ob alles installiert und eingerichtet ist
  kushim setup                 Stand der Einrichtung: Systemcheck, Stimme, Wake Words, Notaus
  kushim help                  Diese Übersicht
  kushim <befehl> --help       Optionen eines Befehls

Einstellungen: config.toml (Vault, LLM, Grafikkarten), wakewords.toml (Wake Words, Zeiten). Anleitung: README.md
"""


def _gpu_plan(cfg: Config):
    """Karten lesen und gemäß [gpu] in config.toml verteilen. Gibt (Karten, Plan) zurück; falsche Einstellung: ValueError."""
    from . import gpu
    gpus = gpu.list_gpus()
    return gpus, gpu.make_plan(gpus, cfg.gpu_whisper, cfg.gpu_llm)


def _show_wiki(out, use_llm: bool, cfg: Config, root) -> int:
    """Wikipedia-Treffer anzeigen; mit `use_llm` fasst das lokale Modell sie über den werkzeuglosen Pfad zusammen."""
    if not out.sources:
        print("Keine brauchbaren Treffer." + (f" Ausgelassen (auffälliger Inhalt): {', '.join(out.skipped)}" if out.skipped else ""))
        return 0
    for i, s in enumerate(out.sources, 1):
        print(f"[{i}] {s.title}  {s.url}\n    {s.text}")
    if out.skipped:
        print("Ausgelassen (auffälliger Inhalt, nicht ans Modell gegeben): " + ", ".join(out.skipped))
    if use_llm:
        from .launcher import Launcher
        from .llm.ollama import OllamaClient
        from .web.answer import answer_from_sources
        _, plan = _gpu_plan(cfg)
        launcher = Launcher(root, cuda_devices=plan.llm_visible)
        try:
            launcher.start_ollama()
            answer = answer_from_sources(OllamaClient(cfg.llm_model).chat, out)       # werkzeuglos; Antwort nur anzeigen
        finally:
            launcher.stop()
        print("\nkushim:", answer)
    return 0


def _voice_tools(cfg: Config, root):
    """Sprachbefehle für Werkzeuge (docs/tools-plan.md): geprüfte Bausteine, Schalter immer frisch aus config.toml."""
    from .claude_cli import ask as claude_ask
    from .claude_cli import base as claude_base
    from .claude_cli import folders as cfolders
    from .claude_cli.control import Control
    from .claude_cli.session import ClaudeSessions
    from .config import LiveConfig
    from .llm.ollama import OllamaClient
    from .net import web as netweb
    from .privacy import EgressGate
    from .research import Research
    from .tasks import TaskRegistry
    from .tools.registry import ToolRegistry, default_tools
    from .safety.gate import ActionGate
    from .timers import TimerStore
    from .tools.registry import TIMER, ToolGate
    from .voice.timer_commands import TimerCommands
    from .voice.tool_commands import ToolCommands
    from .web import search as websearch
    from .web.answer import answer_from_sources
    live = LiveConfig()
    exe = claude_base.find_claude()
    cache = claude_base.AuthCache(exe)
    tasks = TaskRegistry()
    reg = ToolRegistry(default_tools(live, cache), live.tools_enabled)
    egress = EgressGate(live.claude_enabled, confirm=lambda dest, payload: True)       # die Freigabe der Vorschau passiert vorher per "ja"
    sessions = ClaudeSessions(root, exe, vault=cfolders.vault_path(live.memory_location), tasks=tasks)
    wiki = websearch.make_search(reg, netweb.fetch_text)
    research = Research(reg, lambda q, c: claude_ask.ask(q, exe, root / "run" / "claude-research", cancelled=c), wiki, cache.get, egress, tasks=tasks)
    folders = lambda: cfolders.parse(live.claude_folders)
    control = Control(reg, sessions, egress, cache.get, folders, tasks=tasks)
    chat = OllamaClient(live.llm_model).chat
    tc = ToolCommands(live, reg, research, control, sessions, lambda wiki: str(answer_from_sources(chat, wiki)), folders)
    tc.timers = TimerCommands(live, reg, ToolGate(ActionGate([TIMER.spec]), reg), TimerStore(root))
    sessions.viewer = lambda: open_viewer(root)                                       # Claude läuft sichtbar in einem eigenen Fenster
    tc.before = lambda: setattr(egress, "enabled", live.claude_enabled)               # Modus C ausschalten wirkt sofort, auch hier
    return tc, tasks


class SimpleState:
    status = ""


def open_viewer(root) -> None:
    """Öffnet ein eigenes Terminalfenster mit der Live-Ansicht (Windows). Nur Anzeige; kein Einfluss auf den Lauf."""
    import subprocess
    import sys
    if sys.platform == "win32":
        subprocess.Popen([sys.executable, "-m", "kushim.cli", "claude", "watch"], cwd=str(root),
                         creationflags=subprocess.CREATE_NEW_CONSOLE)


def _claude_dev(args, cfg: Config, root) -> int:
    """`kushim claude folders|add|remove|start|status|stop|result|answer`: Claude entwickelt in freigegebenen Ordnern (docs/claude-cli-plan.md)."""
    import time as _time
    from .claude_cli import base as claude_base
    from .claude_cli import folders as cfolders
    from .claude_cli import report as creport
    from .claude_cli.control import Control
    from .claude_cli.session import ClaudeSessions, SessionError
    from .privacy import EgressGate
    from .safety import killswitch
    from .safety.gate import Decision
    from .tools.registry import ToolRegistry, default_tools
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

    if action == "branches":
        sessions = ClaudeSessions(root, None, vault=vault)
        n = 0
        for f in known:
            for w, dirty, ahead in sessions.branches(f):
                n += 1
                print(f"{f.name}  {w.path.name}  Branch {w.branch}  ungesichert: {dirty}  Commits: {ahead}")
        print("Keine Claude-Branches." if not n else "Weitermachen: per Sprache \"Mach bei Nummer eins weiter\" (kushim talk).")
        return 0
    if action == "watch":
        from .claude_cli.watch import run_watch
        try:
            return run_watch(root, state=lambda: (ClaudeSessions(root, None).state() or SimpleState).status)
        except KeyboardInterrupt:
            return 0
    exe = claude_base.find_claude()
    cache = claude_base.AuthCache(exe)
    sessions = ClaudeSessions(root, exe, vault=vault)
    sessions.viewer = lambda: open_viewer(root)
    if action == "status":
        st = sessions.state()
        if st is None:
            print("Kein Claude-Lauf.")
            return 0
        names = {"running": "läuft", "waiting": "wartet auf deine Antwort oder ist fertig", "failed": "gescheitert", "stopped": "gestoppt"}
        print(f"Claude-Lauf {st.id}: {names.get(st.status, st.status)} (Ordner {st.folder}, Zug {st.turn}, {st.seconds / 60:.1f} min, {st.cost_usd:.2f} USD)")
        if st.error:
            print(f"Hinweis: {st.error}")
        return 0
    if action == "stop":
        print("Stopp ausgelöst." if sessions.stop() else "Es läuft kein Claude-Lauf.")
        return 0
    if action == "result":
        got = sessions.result()
        if got is None:
            print("Kein Claude-Lauf.")
            return 0
        print(creport.written(got[2]))
        return 0

    reg = ToolRegistry(default_tools(cfg, cache), cfg.tools_enabled)
    why = next((t.available() for t in reg.tools.values() if t.name == "claude.code"), "")
    if not reg.is_active("claude.code"):
        print("Das Werkzeug claude.code ist " + (f"nicht verfügbar: {why}" if why else "aus. Einschalten: kushim tools enable claude.code"))
        return 1
    ctl = Control(reg, sessions, EgressGate(cfg.claude_enabled, confirm=lambda dest, payload: True), cache.get, lambda: cfolders.parse(cfg.claude_folders))
    if action == "start":
        prop = ctl.propose_start(" ".join(args.auftrag), args.folder, speaker_verified=True)       # am Terminal sitzt der Nutzer selbst
    else:
        prop = ctl.propose_answer(" ".join(args.text), args.allow, speaker_verified=True)
    if prop.decision is not Decision.ASK:
        print(prop.reason or "Nicht erlaubt.")
        return 1
    print(prop.preview)
    if input("Senden und starten? (j/N): ").strip().lower() not in ("j", "ja", "y", "yes"):
        ctl.deny(prop)
        print("Nichts gesendet.")
        return 1
    if not ctl.approve(prop):
        print("Freigabe ungültig oder abgelaufen.")
        return 1
    try:
        ctl.execute(prop)
    except SessionError as e:
        print(f"Nicht gestartet: {e}")
        return 1
    print("Claude arbeitet. Strg+C oder `kushim claude stop` bricht ab, der Branch bleibt erhalten.")
    last = _time.monotonic()
    try:
        while True:
            st = sessions.state()
            if st is None or st.status != "running":
                break
            if killswitch.is_triggered(root):
                sessions.stop()
                print("Notaus: Claude wird beendet.")
            if _time.monotonic() - last > 30:
                print(f"... läuft seit {(_time.monotonic() - last) / 60:.1f} min weiter (Zug {st.turn})", flush=True)
                last = _time.monotonic()
            _time.sleep(0.5)
    except KeyboardInterrupt:
        sessions.stop()
        sessions.join(15)
        print("Abgebrochen: Claude wurde gestoppt, der Branch bleibt erhalten.")
        return 130
    sessions.join(15)
    got = sessions.result()
    if got is not None:
        st, _rv, ov = got
        if st.status == "failed" and st.error:
            print(f"Hinweis: {st.error}")
        print(creport.written(ov))
        if ov.question or ov.permission_questions:
            print("Antworten: kushim claude answer <Text>" + (" [--allow MUSTER]" if st.offers else ""))
    return 0


def _vault_state(cfg: Config) -> str:
    """"ok" (Vault und Stimmprofil da), "kein-profil" oder "kein-vault" (für doctor und setup)."""
    from .voice import voiceprint
    try:
        with open_store(cfg) as store:
            return "ok" if voiceprint.load(store) else "kein-profil"
    except FileNotFoundError:
        return "kein-vault"


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
    sub.add_parser("start", help="Lokale Dienste (Ollama, nur 127.0.0.1) starten; Strg+C beendet")
    sub.add_parser("kill", help="Notaus: stoppt laufende kushim-Dienste")
    sub.add_parser("resume", help="Notaus aufheben (nur bewusst durch den Nutzer)")
    t = sub.add_parser("talk", help="Sprechen per Wake Word (nur das Wake Word wird dauerhaft ausgewertet)")
    t.add_argument("--mic", help="Namensteil des Mikrofons, sonst Systemstandard")
    t.add_argument("--out", help="Namensteil des Ausgabegeräts, sonst Systemstandard")
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
    rec = vo.add_parser("record", help="Absätze für den Stimmklon aufnehmen (nur lokal, voice-data/)")
    rec.add_argument("--mic", help="Namensteil des Mikrofons, sonst Systemstandard")
    rec.add_argument("--redo", action="store_true", help="Schon vorhandene Aufnahmen neu sprechen")
    rec.add_argument("--auto", action="store_true", help="Ende eines Absatzes automatisch per Stille statt per Enter")
    ll = sub.add_parser("llm", help="Lokales Sprachmodell anzeigen oder wechseln (Ollama-Modellname)").add_subparsers(dest="sub")
    ls = ll.add_parser("set", help="z. B. kushim llm set qwen3.5:9b")
    ls.add_argument("model")
    lt = ll.add_parser("test", help="Modell mit einer kurzen Frage ausprobieren und die Zeit messen (startet Ollama kurz)")
    lt.add_argument("model", nargs="?", help="Standard: das aktive Modell")
    ll.add_parser("back", help="Zurück zum vorherigen Modell")
    sub.add_parser("doctor", help="Prüft, ob alles installiert und eingerichtet ist")
    sub.add_parser("help", help="Übersicht aller Befehle mit Beispielen")
    tl = sub.add_parser("tools", help="Werkzeuge anzeigen, ein- und ausschalten (alle standardmäßig aus)").add_subparsers(dest="sub")
    tl.add_parser("enable", help="Werkzeug einschalten (mit Rückfrage)").add_argument("name")
    tl.add_parser("disable", help="Werkzeug sofort ausschalten").add_argument("name")
    rs = sub.add_parser("research", help="Recherche: erst Claude (Internet), Ersatz Wikipedia; mit Vorschau und Bestätigung")
    rs.add_argument("frage", nargs="+")
    rs.add_argument("--llm", action="store_true", help="Bei Wikipedia-Ersatz: Treffer mit dem lokalen Modell zusammenfassen")
    cl = sub.add_parser("claude", help="Claude CLI prüfen, Modus C ein-/ausschalten").add_subparsers(dest="sub")
    cl.add_parser("check", help="Zeigt CLI, Anmeldung und Schalter")
    cl.add_parser("enable", help="Modus C einschalten (mit Rückfrage)")
    cl.add_parser("disable", help="Modus C sofort ausschalten")
    cl.add_parser("folders", help="Für Claude freigegebene Ordner anzeigen")
    ca = cl.add_parser("add", help="Einen Ordner für Claude freigeben (mit Rückfrage)")
    ca.add_argument("name")
    ca.add_argument("path")
    cl.add_parser("remove", help="Die Freigabe eines Ordners sofort entziehen").add_argument("name")
    cs = cl.add_parser("start", help="Claude arbeitet an einem freigegebenen Ordner (Vorschau, Freigabe, eigener Worktree)")
    cs.add_argument("--folder", help="Name des Ordners (bei nur einem Ordner nicht nötig)")
    cs.add_argument("auftrag", nargs="*", help="Auftrag; ohne Angabe: nächster offener Roadmap-Punkt")
    cl.add_parser("status", help="Stand des Claude-Laufs")
    cl.add_parser("branches", help="Vorhandene Claude-Branches (Worktrees) der freigegebenen Ordner")
    cl.add_parser("watch", help="Live-Ansicht: zeigt, was Claude gerade tut (nur Anzeige, Schließen stoppt nichts)")
    cl.add_parser("stop", help="Laufenden Claude-Lauf stoppen (der Branch bleibt)")
    cl.add_parser("result", help="Übersicht: was Claude getan hat, Fakten aus Git, nächste Schritte")
    cn = cl.add_parser("answer", help="Auf eine Rückfrage von Claude antworten (nächster Zug)")
    cn.add_argument("text", nargs="+")
    cn.add_argument("--allow", action="append", default=[], help="Von kushim angebotenes Muster für diese Sitzung erlauben")
    sr = sub.add_parser("search", help="Websuche (Wikipedia) mit Vorschau und Bestätigung; web.search muss eingeschaltet sein")
    sr.add_argument("frage", nargs="+")
    sr.add_argument("--llm", action="store_true", help="Treffer mit dem lokalen Modell zusammenfassen (startet Ollama kurz)")
    sub.add_parser("setup", help="Stand der Einrichtung (Systemcheck, Stimme, Wake Words, Notaus) anzeigen")
    sub.add_parser("gpu", help="Grafikkarten anzeigen und wie sie genutzt werden (Einstellung: [gpu] in config.toml)")
    args = p.parse_args(argv)
    if args.cmd == "help":
        print(HELP)
        return 0
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
    if args.cmd == "llm":
        from .llm import manage
        from .llm.ollama import manifest_rel
        sub_llm = getattr(args, "sub", None)
        if sub_llm == "set":
            try:
                old = cfg.llm_model
                cfg.set_llm_model(args.model)
                if cfg.llm_model != old:
                    manage.save_previous(root, old)          # für `kushim llm back`
            except ValueError as e:
                print(e)
                return 2
            print(f"LLM gesetzt: {cfg.llm_model} (gilt ab dem nächsten Start). Zurück: kushim llm back")
        elif sub_llm == "back":
            res = manage.rollback(cfg, root, run_probe=False)
            if not res.switched:
                print("Kein vorheriges Modell gemerkt." if res.reason == "nothing_to_roll_back" else f"Nicht umgeschaltet ({res.reason}).")
                return 1
            print(f"LLM zurückgesetzt auf {res.model} (vorher {res.previous}). Gilt ab dem nächsten Start.")
        elif sub_llm == "test":
            from .launcher import Launcher
            target = args.model or cfg.llm_model
            if not manage.is_installed(root, target):
                print(f"{target} ist nicht installiert: install.ps1 -Llm {target}")
                return 1
            _, plan = _gpu_plan(cfg)
            launcher = Launcher(root, cuda_devices=plan.llm_visible)
            try:
                launcher.start_ollama()
                res = manage.probe(target)
            finally:
                launcher.stop()
            if res.ok:
                print(f"{target}: ok. Erster Token nach {res.first_token_s:g} s, Antwort nach {res.total_s:g} s ({res.text!r}).")
            else:
                print(f"{target}: Probe fehlgeschlagen ({res.error}).")
            return 0 if res.ok else 1
        else:
            print(f"LLM: {cfg.llm_model}")
            prev = manage.load_previous(root)
            if prev:
                print(f"Vorher: {prev} (zurück mit: kushim llm back)")
            names = [m.name for m in manage.installed(root)]
            if names:
                print("Installiert: " + ", ".join(names))
        if not (root / manifest_rel(cfg.llm_model)).exists():
            print(f"Noch nicht installiert. Laden (einmalig, Netzwerk nur zu registry.ollama.ai): "
                  f"install.ps1 -Llm {cfg.llm_model}")
        return 0
    if args.cmd == "search":
        from .net import web as netweb
        from .safety.gate import Decision
        from .tools.registry import ToolRegistry, default_tools
        from .web import search as websearch
        reg = ToolRegistry(default_tools(), cfg.tools_enabled)
        if not reg.is_active("web.search"):
            print("Das Werkzeug web.search ist aus. Einschalten: kushim tools enable web.search")
            return 1
        ws = websearch.make_search(reg, netweb.fetch_text)
        prop = ws.propose(" ".join(args.frage), speaker_verified=True)        # am Terminal sitzt der Nutzer selbst
        if prop.decision is not Decision.ASK:
            print(prop.reason or "Nicht erlaubt.")
            return 1
        print(prop.preview)
        if input("Senden? (j/N): ").strip().lower() not in ("j", "ja", "y", "yes"):
            ws.queue.deny(prop.approval_id)
            print("Nichts gesendet.")
            return 1
        if not ws.queue.approve(prop.approval_id, prop.approval.digest):
            print("Freigabe ungültig oder abgelaufen.")
            return 1
        try:
            out = ws.execute(prop.approval_id)
        except (websearch.WebDenied, netweb.WebDenied) as e:
            print(f"Abruf nicht möglich: {e}")
            return 1
        return _show_wiki(out, args.llm, cfg, root)
    if args.cmd == "research":
        from .claude_cli import ask as claude_ask
        from .claude_cli import base as claude_base
        from .net import web as netweb
        from .research import Research
        from .safety.gate import Decision
        from .tools.registry import ToolRegistry, default_tools
        from .web import search as websearch
        exe = claude_base.find_claude()
        cache = claude_base.AuthCache(exe)
        reg = ToolRegistry(default_tools(cfg, cache), cfg.tools_enabled)
        wiki = websearch.make_search(reg, netweb.fetch_text)
        from .privacy import EgressGate
        egress = EgressGate(cfg.claude_enabled, confirm=lambda dest, payload: True)    # Freigabe der exakten Vorschau ist schon erfolgt
        res = Research(reg, lambda q, c: claude_ask.ask(q, exe, root / "run" / "claude-research", cancelled=c), wiki, cache.get, egress)
        prop = res.propose(" ".join(args.frage), speaker_verified=True)       # am Terminal sitzt der Nutzer selbst
        if prop.decision is not Decision.ASK:
            print(prop.reason or "Nicht erlaubt.")
            return 1
        print(prop.preview)
        if input("Senden? (j/N): ").strip().lower() not in ("j", "ja", "y", "yes"):
            res.deny(prop)
            print("Nichts gesendet.")
            return 1
        if not res.approve(prop):
            print("Freigabe ungültig oder abgelaufen.")
            return 1
        try:
            out = res.execute(prop)
        except (websearch.WebDenied, netweb.WebDenied) as e:
            print(f"Recherche nicht möglich: {e}")
            return 1
        if out.note:
            print(f"[Hinweis] {out.note}")
        if out.kind == "claude":
            print("Quelle: Claude (Internetsuche, Angaben laut Claude)")
            print(out.answer)
            return 0
        if out.kind == "wikipedia" and out.wiki is not None:
            return _show_wiki(out.wiki, args.llm, cfg, root)
        return 1
    if args.cmd == "claude" and getattr(args, "sub", None) in ("folders", "add", "remove", "start", "status", "stop", "result", "answer", "watch", "branches"):
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
            print("Modus C ist an. Recherche über Claude zusätzlich einschalten: kushim tools enable claude.research")
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
        print(f"Werkzeug claude.research: {'an' if 'claude.research' in cfg.tools_enabled else 'aus (kushim tools enable claude.research)'}")
        return 0
    if args.cmd == "tools":
        from .claude_cli import base as claude_base
        from .tools.registry import ToolNotAllowed, ToolRegistry, default_tools
        reg = ToolRegistry(default_tools(cfg, claude_base.AuthCache(claude_base.find_claude())), cfg.tools_enabled)
        sub_cmd = getattr(args, "sub", None)
        if sub_cmd is None:
            for t in reg.tools.values():
                why = t.available()
                state = "AN " if reg.is_active(t.name) else ("an, aber nicht verfügbar" if reg.is_enabled(t.name) else "aus")
                print(f"[{state}] {t.name}: {t.title}" + ("  (sendet Daten nach außen)" if t.sends_data_out else ""))
                print(f"        {t.description}")
                if why:
                    print(f"        Nicht verfügbar: {why}")
            print("Einschalten: kushim tools enable <name>   Ausschalten: kushim tools disable <name>")
            return 0
        try:
            tool = reg.info(args.name)
            if sub_cmd == "enable":
                if tool.available().startswith("Modus C ist aus") and args.name.startswith("claude."):
                    print("Modus C ist aus. Claude wird nur über deine angemeldete Claude CLI genutzt (nur Abo-Kontingent, nie API-Credits), "
                          "und nur nach Vorschau und deinem Ja.")
                    if input("Modus C jetzt einschalten? (j/N): ").strip().lower() in ("j", "ja", "y", "yes"):
                        cfg.set_claude_enabled(True)
                        cfg = Config.load()
                        reg = ToolRegistry(default_tools(cfg, claude_base.AuthCache(claude_base.find_claude())), cfg.tools_enabled)
                        tool = reg.info(args.name)
                if tool.available():
                    print(f"Nicht verfügbar: {tool.available()}")
                    return 1
                print(f"{tool.title}: {tool.description}")
                print("Dabei verlassen Daten den PC (nur nach Vorschau und Freigabe)." if tool.sends_data_out
                      else "Dabei verlassen keine Daten den PC.")
                if input("Einschalten? (j/N): ").strip().lower() not in ("j", "ja", "y", "yes"):
                    print("Nicht eingeschaltet.")
                    return 1
            reg.set_enabled(args.name, sub_cmd == "enable", confirmed=True, persist=cfg.set_tools_enabled)
        except ToolNotAllowed as e:
            print(f"Nicht möglich ({e.code}).")
            return 2
        print(f"{args.name}: {'eingeschaltet' if sub_cmd == 'enable' else 'ausgeschaltet'}.")
        return 0
    if args.cmd == "setup":
        from .setup import status as setup_status
        steps = setup_status.compute(root, lambda: _vault_state(cfg), cfg.llm_model)
        marks = {"done": "[ok]      ", "skipped": "[übersprungen] ", "open": "[offen]   "}
        for s in steps:
            print(f"{marks[s.status]}{s.title}: {s.detail}")
        for note in setup_status.restricted_notes(steps):
            print("Eingeschränkt:", note)
        if setup_status.first_start(steps):
            print("Offene Schritte erscheinen beim Start in der Oberfläche (sobald es sie gibt). Überspringen ändert keine Sicherheitsregel.")
        return 0
    if args.cmd == "doctor":
        from .doctor import run_checks
        results = run_checks(root, lambda: _vault_state(cfg), cfg.llm_model)
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
    if args.cmd == "talk":
        from .launcher import Launcher
        from .safety.killswitch import is_triggered
        from .voice import audio, voiceprint, wakeconfig
        from .voice.audio import UtteranceCollector
        from .voice.bargein import BargeIn
        from .voice.embedder import SherpaEmbedder
        from .voice.talk import TalkLoop, build_live
        from .voice.wake_commands import WakeWordCommands
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
        launcher = Launcher(root, cuda_devices=plan.llm_visible)
        try:
            launcher.start_ollama()
            tool_cmds, tasks = _voice_tools(cfg, root)
            from .voice.commands import CommandChain
            pipeline, kill, mic, ack = build_live(root, audio.find_device(args.out, "output"),
                                                  audio.find_device(args.mic, "input"),
                                                  verifier=verifier, commands=CommandChain([WakeWordCommands(root), tool_cmds, tool_cmds.timers]),
                                                  tasks=tasks,
                                                  wake_names=[w.name for w in wcfg.enabled()],
                                                  llm_model=cfg.llm_model, whisper_device=plan.whisper_device,
                                                  whisper_index=plan.whisper_index)
            tool_cmds.say = pipeline.say_text
            kill.actions.append(tool_cmds.sessions.stop)          # Notaus beendet auch einen laufenden Claude-Lauf
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
            loop = TalkLoop(mic, pipeline, kill, wake=lambda f: det.process(f) is not None, ack=ack,
                            flush=mic.flush, new_collector=lambda: utter(wait_ms),
                            on_result=out,
                            first_collector=lambda: utter(first_ms),
                            follow_collector=(lambda: utter(follow_ms)) if follow_ms > 0 else None,
                            barge=barge, preroll_frames=round(st.preroll_seconds / 0.08),
                            announce=lambda: tool_cmds.announcement() or tool_cmds.timers.announcement(), say=pipeline.say_text,
                            on_note=lambda s: print(f"[Hinweis] {s}"))
            print("Wake Words: " + ", ".join(w.name for w in wcfg.enabled())
                  + ". Notaus: 'Notaus' sagen oder die Verknüpfung. Strg+C beendet.")
            if follow_ms > 0:
                print(f"Gespräch: nach einer Antwort hörst du {st.follow_up_seconds:g} s lang ohne Wake Word zu; "
                      "\"das war's\" oder Stille beendet es.")
            if barge is not None:
                print("Unterbrechen: einfach dazwischensprechen (Kopfhörer empfohlen; mit Lautsprechern kann kushim sich "
                      "selbst hören: barge_in_level erhöhen oder barge_in = false in wakewords.toml).")
            reason = loop.run()
            print("Ende:", reason)
            if reason == "shutdown":                                  # "beende dich": Claude-Lauf stoppen, Dienste beendet das finally
                tool_cmds.sessions.stop()
                tool_cmds.sessions.join(15)
        except KeyboardInterrupt:
            pass
        finally:
            launcher.stop()
        return 0
    if args.cmd == "start":
        import time
        from .launcher import Launcher
        from .safety.killswitch import KillSwitch, is_triggered
        if is_triggered(root):
            print("Notaus ist aktiv. Erst bewusst aufheben: kushim resume")
            return 1
        try:
            _, plan = _gpu_plan(cfg)
        except ValueError as e:
            print(f"[gpu] in config.toml: {e}")
            return 2
        launcher = Launcher(root, cuda_devices=plan.llm_visible)
        kill = KillSwitch(root, [launcher.stop])
        try:
            print("Ollama:", launcher.start_ollama(), "(nur 127.0.0.1). Strg+C zum Beenden.")
            while not kill.poll():
                time.sleep(0.5)
            print("NOTAUS: Dienste beendet.")
        except KeyboardInterrupt:
            pass
        finally:
            launcher.stop()
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
