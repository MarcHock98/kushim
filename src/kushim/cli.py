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
  kushim voice reset           Stimmprofil löschen

Sprachmodell und Grafikkarten
  kushim gpu                   Grafikkarten zeigen und wie Whisper und das Sprachmodell verteilt werden
  kushim llm                   Aktuelles Modell zeigen
  kushim llm set <name>        Modell wechseln (z. B. qwen3.5:9b); laden mit install.ps1 -Llm <name>

Gedächtnis und Schlüssel
  kushim memory init           Vault anlegen (erzeugt auch den Schlüssel)
  kushim memory info           Vault-Ort und Zustand
  kushim memory backup         Verschlüsselte Sicherung erstellen
  kushim memory migrate --to local:D:/kushim-vault
  kushim key export            Schlüssel zum Sichern anzeigen (nur im eigenen Terminal)
  kushim key import <vault_id> <hexkey>

Prüfen und Hilfe
  kushim doctor                Prüft, ob alles installiert und eingerichtet ist
  kushim help                  Diese Übersicht
  kushim <befehl> --help       Optionen eines Befehls

Einstellungen: config.toml (Vault, LLM, Grafikkarten), wakewords.toml (Wake Words, Zeiten). Anleitung: README.md
"""


def _gpu_plan(cfg: Config):
    """Karten lesen und gemäß [gpu] in config.toml verteilen. Gibt (Karten, Plan) zurück; falsche Einstellung: ValueError."""
    from . import gpu
    gpus = gpu.list_gpus()
    return gpus, gpu.make_plan(gpus, cfg.gpu_whisper, cfg.gpu_llm)


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
    sub.add_parser("doctor", help="Prüft, ob alles installiert und eingerichtet ist")
    sub.add_parser("help", help="Übersicht aller Befehle mit Beispielen")
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
        from .llm.ollama import manifest_rel
        if getattr(args, "sub", None) == "set":
            try:
                cfg.set_llm_model(args.model)
            except ValueError as e:
                print(e)
                return 2
            print(f"LLM gesetzt: {cfg.llm_model} (gilt ab dem nächsten Start)")
        else:
            print(f"LLM: {cfg.llm_model}")
        if not (root / manifest_rel(cfg.llm_model)).exists():
            print(f"Noch nicht installiert. Laden (einmalig, Netzwerk nur zu registry.ollama.ai): "
                  f"install.ps1 -Llm {cfg.llm_model}")
        return 0
    if args.cmd == "doctor":
        from .doctor import run_checks
        from .voice import voiceprint

        def vault_state() -> str:
            try:
                with open_store(cfg) as store:
                    return "ok" if voiceprint.load(store) else "kein-profil"
            except FileNotFoundError:
                return "kein-vault"
        results = run_checks(root, vault_state, cfg.llm_model)
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
            pipeline, kill, mic, ack = build_live(root, audio.find_device(args.out, "output"),
                                                  audio.find_device(args.mic, "input"),
                                                  verifier=verifier, commands=WakeWordCommands(root),
                                                  wake_names=[w.name for w in wcfg.enabled()],
                                                  llm_model=cfg.llm_model, whisper_device=plan.whisper_device,
                                                  whisper_index=plan.whisper_index)
            det = build_detector(wcfg, root)
            wait_ms = int(wcfg.settings.listen_seconds * 1000)
            first_ms = int(wcfg.settings.command_wait_seconds * 1000)
            end_ms = int(wcfg.settings.end_silence_seconds * 1000)
            max_ms = int(wcfg.settings.max_seconds * 1000)
            out = lambda r: print(f"Du: {r.heard}\nkushim: {r.reply or '(' + r.outcome + ')'}"
                                  + (f"  [{r.detail}]" if r.detail else ""))
            loop = TalkLoop(mic, pipeline, kill, wake=lambda f: det.process(f) is not None, ack=ack,
                            flush=mic.flush, new_collector=lambda: UtteranceCollector(wait_ms=wait_ms, silence_ms=end_ms, max_ms=max_ms),
                            on_result=out,
                            first_collector=lambda: UtteranceCollector(wait_ms=first_ms, silence_ms=end_ms, max_ms=max_ms))
            print("Wake Words: " + ", ".join(w.name for w in wcfg.enabled())
                  + ". Notaus: 'Notaus' sagen oder die Verknüpfung. Strg+C beendet.")
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


if __name__ == "__main__":
    raise SystemExit(main())
