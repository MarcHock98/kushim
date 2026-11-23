"""Prüfung, ob der kushim-Channel in Claude Code an ist (src/kushim/channel/claude_log.py), mit gefälschten Protokolldateien."""
import os
import time
from pathlib import Path

from kushim.channel import claude_log as cl

SKIPPED = ('{"debug":"Connection established with capabilities: {}"}\n'
           '{"debug":"Channel notifications skipped: channels feature is not currently available"}\n')
REGISTERED = '{"debug":"Connection established"}\n{"debug":"Channel notifications registered"}\n'


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def run(directory, since=0.0, clock=None, wait=cl.WAIT):
    clock = clock or Clock()
    return cl.check(directory, since, wait=wait, clock=clock, sleep=clock.sleep)


def test_log_dir_is_built_from_local_appdata_and_the_working_folder_never_a_fixed_user():
    d = cl.log_dir(Path(r"C:\Users\someone\IdeaProjects\kushim"), local_appdata=r"D:\Local")
    assert d == Path(r"D:\Local") / "claude-cli-nodejs" / "Cache" / "C--Users-someone-IdeaProjects-kushim" / "mcp-logs-kushim"
    assert cl.project_key(Path(r"C:\Users\x\.claude\spares\spare-6fQcit")) == "C--Users-x--claude-spares-spare-6fQcit"
    assert cl.log_dir(Path("C:/a"), local_appdata="") is None
    src = (Path(__file__).resolve().parents[1] / "src" / "kushim" / "channel" / "claude_log.py").read_text(encoding="utf-8")
    assert "march" not in src.lower()


def test_skipped_without_registered_is_off_registered_is_on(tmp_path):
    (tmp_path / "a.jsonl").write_text(SKIPPED, encoding="utf-8")
    assert run(tmp_path) == "off"
    (tmp_path / "a.jsonl").write_text(SKIPPED + '{"debug":"Channel notifications registered"}\n', encoding="utf-8")
    assert run(tmp_path) == "on"                                                    # an gewinnt (z. B. nach Wiederverbinden)
    (tmp_path / "a.jsonl").write_text(REGISTERED, encoding="utf-8")
    assert run(tmp_path) == "on"


def test_off_is_only_reported_after_the_wait_and_registered_in_time_counts(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text(SKIPPED, encoding="utf-8")
    clock = Clock()

    def sleep(s):
        clock.t += s
        if clock.t >= 5:
            f.write_text(REGISTERED, encoding="utf-8")                              # Nutzer bestätigt den Hinweis, dann registriert
    assert cl.check(tmp_path, 0.0, wait=20, clock=clock, sleep=sleep) == "on" and clock.t < 20
    f.write_text(SKIPPED, encoding="utf-8")
    clock = Clock()
    assert run(tmp_path, clock=clock) == "off" and clock.t >= cl.WAIT


def test_missing_folder_empty_folder_and_old_files_are_unknown(tmp_path):
    assert run(None) == "unknown"
    assert run(tmp_path / "gibtsnicht") == "unknown"
    assert run(tmp_path) == "unknown"
    old = tmp_path / "alt.jsonl"
    old.write_text(SKIPPED, encoding="utf-8")
    past = time.time() - 3600
    os.utime(old, (past, past))
    assert run(tmp_path, since=time.time() - 60) == "unknown"                      # Protokoll einer früheren Sitzung zählt nicht


def test_only_the_newest_file_counts(tmp_path):
    a, b = tmp_path / "1.jsonl", tmp_path / "2.jsonl"
    a.write_text(REGISTERED, encoding="utf-8")
    b.write_text(SKIPPED, encoding="utf-8")
    now = time.time()
    os.utime(a, (now - 10, now - 10))
    os.utime(b, (now, now))
    assert run(tmp_path, since=now - 100) == "off"


def test_a_huge_file_is_read_only_partially(tmp_path, monkeypatch):
    f = tmp_path / "riesig.jsonl"
    with open(f, "wb") as fh:
        fh.write(SKIPPED.encode())
        fh.write(b"x" * (5 * 1024 * 1024))
        fh.write(b"Channel notifications registered")                               # hinter der Lesegrenze: wird nie gelesen
    reads = []
    real_open = open

    def spy(path, mode="r", *a, **k):
        fh = real_open(path, mode, *a, **k)
        real_read = fh.read

        class Wrapped:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                fh.close()

            def read(self, n=-1):
                reads.append(n)
                return real_read(n)
        return Wrapped()
    monkeypatch.setattr("builtins.open", spy)
    assert cl.markers(f) == (True, False)
    assert reads == [cl.READ_LIMIT] and cl.READ_LIMIT <= 64 * 1024


def test_texts_are_first_person_and_name_the_readme_section():
    assert "Sprachkanal in Claude Code" in cl.TERMINAL_HINT
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "### Sprachkanal in Claude Code" in readme
    assert "CLAUDE_CODE_GB_DISK_CACHE_WHEN_TELEMETRY_OFF" in readme and "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC" in readme
    assert "claude" not in cl.SPOKEN_HINT.lower()
