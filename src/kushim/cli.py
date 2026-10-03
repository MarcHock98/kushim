"""kushim CLI (Gedächtnis-Verwaltung; Audio/UI folgen)."""
from __future__ import annotations

import argparse

from .config import Config
from .memory import open_store
from .memory.keys import get_or_create_key, store_key
from .memory.migrate import backup, migrate


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kushim")
    sub = p.add_subparsers(dest="cmd", required=True)
    mem = sub.add_parser("memory").add_subparsers(dest="sub", required=True)
    mem.add_parser("init")
    mem.add_parser("info")
    mem.add_parser("backup")
    m = mem.add_parser("migrate")
    m.add_argument("--to", required=True, help='z.B. "local:D:/kushim-vault"')
    key = sub.add_parser("key").add_subparsers(dest="sub", required=True)
    key.add_parser("export")
    ki = key.add_parser("import")
    ki.add_argument("vault_id")
    ki.add_argument("hexkey")
    sub.add_parser("start", help="Lokale Dienste (Ollama, nur 127.0.0.1) starten; Strg+C beendet")
    sub.add_parser("kill", help="Notaus: stoppt laufende kushim-Dienste")
    sub.add_parser("resume", help="Notaus aufheben (nur bewusst durch den Nutzer)")
    t = sub.add_parser("talk", help="Sprechen: Taste halten (Standard F9) oder Wake Word")
    t.add_argument("--mic", help="Namensteil des Mikrofons, sonst Systemstandard")
    t.add_argument("--out", help="Namensteil des Ausgabegeräts, sonst Systemstandard")
    t.add_argument("--wake", action="store_true", help="Wake Word (hey_jarvis) statt Taste")
    t.add_argument("--key", default="f9", help="Push-to-Talk-Taste")
    args = p.parse_args(argv)
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
    if args.cmd == "talk":
        from .launcher import Launcher
        from .safety.killswitch import is_triggered
        from .voice import audio
        from .voice.talk import TalkLoop, build_live
        if is_triggered(root):
            print("Notaus ist aktiv. Erst bewusst aufheben: kushim resume")
            return 1
        launcher = Launcher(root)
        try:
            launcher.start_ollama()
            pipeline, kill = build_live(root, audio.find_device(args.out, "output"))
            frames = audio.frames(audio.find_device(args.mic, "input"))
            out = lambda r: print(f"Du: {r.heard}\nkushim: {r.reply or '(' + r.outcome + ')'}")
            if args.wake:
                from .voice.trigger import WakeWordDetector
                det = WakeWordDetector.from_openwakeword()
                loop = TalkLoop(frames, pipeline, kill, wake=lambda f: det.process(f) is not None,
                                on_result=out)
                print("Sage 'hey jarvis'. Notaus: sag 'Notaus' oder starte die Notaus-Verknüpfung.")
            else:
                from .voice.trigger import PushToTalk
                down = {"v": False}
                ptt = PushToTalk(args.key, lambda e: down.update(v=True), lambda: down.update(v=False))
                ptt.start()
                loop = TalkLoop(frames, pipeline, kill, ptt_down=lambda: down["v"], on_result=out)
                print(f"Taste {args.key.upper()} halten und sprechen. Strg+C beendet.")
            print("Ende:", loop.run())
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
        launcher = Launcher(root)
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


if __name__ == "__main__":
    raise SystemExit(main())
