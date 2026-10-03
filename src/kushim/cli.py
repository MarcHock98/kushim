"""kushim CLI (Gedächtnis-Verwaltung; Audio/UI folgen)."""
from __future__ import annotations

import argparse

from .config import Config
from .memory import open_store
from .memory.keys import get_or_create_key, store_key
from .memory.migrate import backup, migrate


def _vault(cfg: Config):
    """Öffnet den Vault oder erklärt, was fehlt (der Vault wird nie automatisch angelegt)."""
    try:
        return open_store(cfg)
    except FileNotFoundError:
        print("Noch kein Vault. Einmalig anlegen mit: kushim memory init (erzeugt auch den Schlüssel).")
        raise SystemExit(3)


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
    t = sub.add_parser("talk", help="Sprechen per Wake Word (nur das Wake Word wird dauerhaft ausgewertet)")
    t.add_argument("--mic", help="Namensteil des Mikrofons, sonst Systemstandard")
    t.add_argument("--out", help="Namensteil des Ausgabegeräts, sonst Systemstandard")
    t.add_argument("--wake-words", help="Komma-getrennt, überschreibt die Konfiguration (z. B. hey_jarvis,alexa)")
    vo = sub.add_parser("voice", help="Eigene Stimme: einschreiben, testen, Status, löschen").add_subparsers(
        dest="sub", required=True)
    for name in ("enroll", "test"):
        v = vo.add_parser(name)
        v.add_argument("--mic", help="Namensteil des Mikrofons, sonst Systemstandard")
    vo.add_parser("status")
    vo.add_parser("reset")
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
    if args.cmd == "voice":
        from .voice import audio, voiceprint
        from .voice.enrollment import enroll as run_enroll, frames_recorder
        from .voice.embedder import SherpaEmbedder
        model = root / "models" / "speaker" / "wespeaker_en_voxceleb_CAM++_LM.onnx"
        with _vault(cfg) as store:
            if args.sub == "status":
                vp = voiceprint.load(store)
                print("Stimmprofil: " + (f"vorhanden (Schwelle {vp.threshold:.2f})" if vp else "keines"))
            elif args.sub == "reset":
                voiceprint.clear(store)
                print("Stimmprofil gelöscht. kushim talk startet erst nach erneutem Einschreiben.")
            else:
                embed = SherpaEmbedder.from_local(str(model))
                frames = iter(audio.Mic(audio.find_device(args.mic, "input")))
                if args.sub == "enroll":
                    print("Lies die Sätze in normaler Lautstärke vor. Aufnahmen bleiben im Speicher.")
                    res = run_enroll(frames_recorder(frames), embed)
                    voiceprint.save(store, res.verifier, model.name)
                    print(f"Gespeichert im Vault. Proben: {res.used}, mittlere Ähnlichkeit "
                          f"{res.mean_similarity:.2f}, Schwelle {res.threshold:.2f}.")
                else:
                    vp = voiceprint.load(store)
                    if vp is None:
                        print("Kein Stimmprofil. Erst: kushim voice enroll")
                        return 1
                    print("Sprich einen Satz (Test). Strg+C beendet.")
                    try:
                        while True:
                            v = vp.verify(embed(frames_recorder(frames)()))
                            print(f"Ähnlichkeit {v.score:.2f} (Schwelle {vp.threshold:.2f}): "
                                  f"{'akzeptiert' if v.accepted else 'abgelehnt'}")
                    except KeyboardInterrupt:
                        pass
        return 0
    if args.cmd == "talk":
        from .launcher import Launcher
        from .safety.killswitch import is_triggered
        from .voice import audio
        from .voice.talk import TalkLoop, build_live
        from .voice.trigger import WakeWordDetector, resolve_wake_words
        if is_triggered(root):
            print("Notaus ist aktiv. Erst bewusst aufheben: kushim resume")
            return 1
        words = args.wake_words.split(",") if args.wake_words else cfg.wake_words
        try:
            models = resolve_wake_words(words, root)
        except ValueError as e:
            print(e)
            return 2
        from .voice import voiceprint
        from .voice.embedder import SherpaEmbedder
        with _vault(cfg) as store:
            verifier = voiceprint.load(store)
        if verifier is None:
            print("Kein Stimmprofil. kushim hört nur auf deine Stimme: erst `kushim voice enroll`.")
            return 1
        embed = SherpaEmbedder.from_local(str(root / "models" / "speaker" / "wespeaker_en_voxceleb_CAM++_LM.onnx"))
        launcher = Launcher(root)
        try:
            launcher.start_ollama()
            pipeline, kill, mic, ack = build_live(root, audio.find_device(args.out, "output"),
                                                  audio.find_device(args.mic, "input"),
                                                  verifier=verifier, embed=embed)
            det = WakeWordDetector.from_openwakeword(models)
            out = lambda r: print(f"Du: {r.heard}\nkushim: {r.reply or '(' + r.outcome + ')'}")
            loop = TalkLoop(mic, pipeline, kill, wake=lambda f: det.process(f) is not None,
                            ack=ack, flush=mic.flush, on_result=out)
            print(f"Wake Words: {', '.join(words)}. Notaus: 'Notaus' sagen oder die Verknüpfung. Strg+C beendet.")
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
