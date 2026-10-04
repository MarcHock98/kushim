import json
from pathlib import Path

import pytest

from kushim.api.folders_api import MAX_PENDING, TTL, register_folders
from kushim.api.protocol import ApiCore, new_token
from kushim.config import Config

TOKEN = new_token()


class Env:
    def __init__(self, tmp_path):
        self.cfg_path = tmp_path / "config.toml"
        self.projects = tmp_path / "p"
        self.projects.mkdir()
        self.now = 1000.0
        self.audit: list[tuple[str, str]] = []
        self.running: set[str] = set()
        self.core = ApiCore(TOKEN)
        register_folders(self.core, lambda: Config.load(self.cfg_path), self.validate, busy=lambda n: n in self.running,
                         audit=lambda e, d: self.audit.append((e, d)), clock=lambda: self.now)

    def validate(self, raw):
        p = Path(raw)
        if not p.is_dir():
            raise ValueError("Der Ordner existiert nicht.")
        if p.name == "verboten":
            raise ValueError("Dieser Ordner liegt in einem geschützten Bereich (System, AppData, .ssh, .claude).")
        return p.resolve()

    def call(self, type_, **m):
        return json.loads(self.core.handle(json.dumps({"token": TOKEN, "type": type_, **m})))

    def folder(self, name="proj"):
        d = self.projects / name
        d.mkdir(exist_ok=True)
        return str(d)

    def saved(self):
        return Config.load(self.cfg_path).claude_folders


@pytest.fixture()
def env(tmp_path):
    return Env(tmp_path)


def test_empty_list(env):
    assert env.call("claude.folder_list") == {"ok": True, "folders": []}


def test_propose_shows_the_exact_path_and_consequences_and_writes_nothing(env):
    r = env.call("claude.folder_propose", name="proj", path=env.folder())
    assert r["allowed"] and r["name"] == "proj" and r["expires_in"] == TTL
    assert "eigenen Worktree und Branch" in r["preview"] and "Anthropic" in r["preview"]
    assert str(Path(env.folder()).resolve()) in r["preview"]                      # der exakte Pfad, den der Nutzer freigibt
    assert env.saved() == ()                                                       # noch nichts freigegeben


def test_confirm_needs_confirm_true_and_is_single_use(env):
    r = env.call("claude.folder_propose", name="proj", path=env.folder())
    assert env.call("claude.folder_confirm", proposal=r["proposal"])["error"] == "confirm_required"
    assert env.saved() == ()
    ok = env.call("claude.folder_confirm", proposal=r["proposal"], confirm=True)
    assert ok["ok"] and [f["name"] for f in ok["folders"]] == ["proj"]
    assert len(env.saved()) == 1 and env.saved()[0].startswith("proj|")
    assert env.call("claude.folder_confirm", proposal=r["proposal"], confirm=True)["error"] == "unknown_proposal"
    assert env.audit == [("claude_folder_add", "name=proj")]


def test_refusals_come_from_the_path_rules_and_name_rules(env):
    forbidden = env.projects / "verboten"
    forbidden.mkdir()
    assert env.call("claude.folder_propose", name="x", path=str(forbidden))["reason"].startswith("Dieser Ordner liegt in einem geschützten")
    assert env.call("claude.folder_propose", name="x", path=str(env.projects / "nix"))["reason"] == "Der Ordner existiert nicht."
    assert "Kleinbuchstaben" in env.call("claude.folder_propose", name="Mein Ordner", path=env.folder())["reason"]
    assert env.saved() == ()


def test_duplicate_name_is_refused_at_propose_and_at_confirm(env):
    a = env.call("claude.folder_propose", name="proj", path=env.folder("a"))
    b = env.call("claude.folder_propose", name="proj", path=env.folder("b"))          # beide Vorschläge vor der Freigabe
    env.call("claude.folder_confirm", proposal=a["proposal"], confirm=True)
    assert env.call("claude.folder_confirm", proposal=b["proposal"], confirm=True)["error"] == "refused"
    assert env.call("claude.folder_propose", name="proj", path=env.folder("c"))["reason"] == "Diesen Namen gibt es schon."
    assert len(env.saved()) == 1


def test_proposal_expires_and_deny_voids_it(env):
    r = env.call("claude.folder_propose", name="proj", path=env.folder())
    env.now += TTL + 1
    assert env.call("claude.folder_confirm", proposal=r["proposal"], confirm=True)["error"] == "unknown_proposal"
    r2 = env.call("claude.folder_propose", name="proj", path=env.folder())
    assert env.call("claude.folder_deny", proposal=r2["proposal"]) == {"ok": True, "denied": True}
    assert env.call("claude.folder_confirm", proposal=r2["proposal"], confirm=True)["error"] == "unknown_proposal"
    assert env.saved() == ()


def test_path_is_checked_again_at_confirm(env):
    d = env.folder("weg")
    r = env.call("claude.folder_propose", name="weg", path=d)
    Path(d).rmdir()                                                                 # zwischen Vorschau und Klick verschwunden
    assert env.call("claude.folder_confirm", proposal=r["proposal"], confirm=True)["error"] == "refused"
    assert env.saved() == ()


def test_pending_proposals_are_bounded(env):
    ids = [env.call("claude.folder_propose", name=f"n{i}", path=env.folder(f"d{i}"))["proposal"] for i in range(MAX_PENDING + 2)]
    assert env.call("claude.folder_confirm", proposal=ids[0], confirm=True)["error"] == "unknown_proposal"     # älteste verworfen
    assert env.call("claude.folder_confirm", proposal=ids[-1], confirm=True)["ok"] is True


def test_remove_is_immediate_audited_and_refused_while_a_run_is_active(env):
    for n in ("a", "b"):
        r = env.call("claude.folder_propose", name=n, path=env.folder(n))
        env.call("claude.folder_confirm", proposal=r["proposal"], confirm=True)
    env.running.add("a")
    assert env.call("claude.folder_remove", name="a")["error"] == "in_use"
    assert len(env.saved()) == 2
    out = env.call("claude.folder_remove", name="b")
    assert [f["name"] for f in out["folders"]] == ["a"] and len(env.saved()) == 1
    assert env.call("claude.folder_remove", name="b")["error"] == "not_found"
    assert env.audit[-1] == ("claude_folder_remove", "name=b")


def test_bad_requests_and_token(env):
    assert env.call("claude.folder_propose", name=5, path="x")["error"] == "bad_request"
    assert env.call("claude.folder_propose", name="a", path="")["error"] == "bad_request"
    assert env.call("claude.folder_propose", name="a", path="x" * 401)["error"] == "bad_request"
    assert env.call("claude.folder_remove", name=None)["error"] == "bad_request"
    assert json.loads(env.core.handle(json.dumps({"type": "claude.folder_list"})))["error"] == "unauthorized"


def test_unwritable_config_gives_not_saved_and_changes_nothing(env, monkeypatch):
    r = env.call("claude.folder_propose", name="proj", path=env.folder())

    def boom(self, entries):
        raise OSError("schreibgeschützt")
    monkeypatch.setattr(Config, "set_claude_folders", boom)
    assert env.call("claude.folder_confirm", proposal=r["proposal"], confirm=True)["error"] == "not_saved"
    assert env.saved() == ()
