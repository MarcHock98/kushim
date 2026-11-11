"""UI-Freigabeleiste an Claudes Channel-Freigaben (Roadmap C0): src/kushim/api/approvals_api.py."""
import json
import threading

from kushim.api.approvals_api import digest_of, register_approvals
from kushim.api.protocol import ApiCore, new_token
from kushim.channel.bridge import Bridge, Permission
from kushim.safety import killswitch

TOKEN = new_token()
PERM = Permission("abcde", "Bash", "Tests laufen lassen", '{ "command": "npm test" }')


class FakeBridge(Bridge):
    def __init__(self, root, status="ok"):
        super().__init__(root, request=lambda *a, **k: {})
        self.status, self.answers = status, []

    def answer(self, request_id, behavior):
        self.answers.append((request_id, behavior))
        if self.status == "ok":
            for p in [p for p in self.permissions if p.request_id == request_id]:
                self.permissions.remove(p)
        return self.status


def make(tmp_path, status="ok", **kw):
    b = FakeBridge(tmp_path, status)
    b.permissions.append(PERM)
    core = ApiCore(TOKEN)
    register_approvals(core, b, tmp_path, **kw)
    return core, b


def call(core, type_, **m):
    return json.loads(core.handle(json.dumps({"token": TOKEN, "type": type_, **m})))


def decide(core, approve=True, p=PERM, **over):
    msg = {"request_id": p.request_id, "approve": approve, "digest": digest_of(p), **({"confirm": True} if approve else {})}
    msg.update(over)
    return call(core, "approvals.decide", **msg)


def test_get_lists_exact_text_digest_and_summary(tmp_path):
    core, _ = make(tmp_path)
    r = call(core, "approvals.get")
    assert r["ok"] and len(r["pending"]) == 1
    item = r["pending"][0]
    assert item["request_id"] == "abcde" and item["tool_name"] == "Bash"
    assert item["description"] == "Tests laufen lassen" and item["input_preview"] == '{ "command": "npm test" }'
    assert item["digest"] == digest_of(PERM) and "npm test" in item["summary"]


def test_get_empty_and_during_kill(tmp_path):
    core, b = make(tmp_path)
    b.permissions.clear()
    assert call(core, "approvals.get")["pending"] == []
    b.permissions.append(PERM)
    killswitch.marker_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    killswitch.marker_path(tmp_path).write_text("x")
    assert call(core, "approvals.get")["pending"] == []


def test_allow_needs_digest_confirm_and_answers_once(tmp_path):
    core, b = make(tmp_path)
    assert call(core, "approvals.get")["ok"] and b.answers == []             # Ansehen entscheidet nie
    assert decide(core, confirm=False)["error"] == "confirm_required"
    assert decide(core, confirm="true")["error"] == "confirm_required"
    assert b.answers == []
    assert decide(core) == {"ok": True, "result": "allow"}
    assert b.answers == [("abcde", "allow")]
    assert decide(core)["error"] == "none"                                   # zweiter Klick: nichts mehr offen
    assert b.answers == [("abcde", "allow")]


def test_deny_needs_no_confirm(tmp_path):
    core, b = make(tmp_path)
    assert decide(core, approve=False) == {"ok": True, "result": "deny"}
    assert b.answers == [("abcde", "deny")]


def test_stale_digest_and_unknown_id_are_refused(tmp_path):
    core, b = make(tmp_path)
    assert decide(core, digest="0" * 64)["error"] == "stale"
    other = Permission("abcde", "Bash", "Tests laufen lassen", '{ "command": "rm -rf x" }')
    assert decide(core, p=other)["error"] == "stale"                         # Hash eines anderen Textes
    assert decide(core, request_id="zzz")["error"] == "none"
    assert b.answers == []


def test_bad_requests(tmp_path):
    core, b = make(tmp_path)
    for bad in ({"request_id": 5}, {"approve": "yes"}, {"digest": None}, {"request_id": None}):
        assert decide(core, **bad)["error"] == "bad_request"
    assert call(core, "approvals.decide")["error"] == "bad_request"
    assert b.answers == []


def test_kill_switch_refuses_decisions(tmp_path):
    core, b = make(tmp_path)
    killswitch.marker_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    killswitch.marker_path(tmp_path).write_text("x")
    assert decide(core)["error"] == "kill" and decide(core, approve=False)["error"] == "kill"
    assert b.answers == []


def test_bridge_failures_map_to_short_codes(tmp_path):
    for status, code in (("unknown", "none"), ("kill", "kill"), ("not_running", "unavailable"), ("error", "unavailable")):
        core, _ = make(tmp_path, status)
        assert decide(core)["error"] == code


def test_on_decision_and_audit_hooks(tmp_path):
    seen, aud = [], []
    core, _ = make(tmp_path, on_decision=seen.append, audit=lambda e, d: aud.append((e, d)))
    decide(core)
    assert seen == [{"request_id": "abcde", "tool": "Bash", "result": "allowed", "source": "ui",
                     "what": "Claude möchte den Befehl npm test ausführen."}]
    assert aud == [("approval", "ui allow")]                                  # nie der fremde Text


def test_failing_hooks_do_not_break_the_decision(tmp_path):
    def boom(*a):
        raise RuntimeError("x")
    core, b = make(tmp_path, on_decision=boom, audit=boom)
    assert decide(core) == {"ok": True, "result": "allow"}


def test_truncated_preview_can_only_be_denied_in_the_ui(tmp_path):
    for preview in ('{ "command": "rm -rf build && ech…', '{ "command": "ls" }⋯ 2 fields elided: a, b ⋯',
                    '{ "command": "' + "x" * 490 + '" }'):
        long = Permission.parse({"request_id": "r9", "tool_name": "Bash", "description": "", "input_preview": preview})
        core, b = make(tmp_path)
        b.permissions.append(long)
        item = [i for i in call(core, "approvals.get")["pending"] if i["request_id"] == "r9"][0]
        assert item["truncated"] is True
        assert decide(core, p=long)["error"] == "terminal_only" and b.answers == []
        assert decide(core, approve=False, p=long) == {"ok": True, "result": "deny"}
    core, _ = make(tmp_path)
    assert call(core, "approvals.get")["pending"][0]["truncated"] is False


def test_ui_decisions_land_in_the_approval_log(tmp_path):
    from kushim.channel import approval_log as al
    from kushim.memory.local import LocalStore
    key = "ab" * 32
    LocalStore(tmp_path / "v", create=True, key=key).close()
    core, _ = make(tmp_path, on_decision=al.ApprovalLog(lambda: LocalStore(tmp_path / "v", key=key)))
    decide(core)
    with LocalStore(tmp_path / "v", key=key) as store:
        row = al.recent(store)[0]
    assert row["source"] == "ui" and row["result"] == "allowed" and "npm test" in row["what"]
    assert "Oberfläche" in al.format_row(row)


def test_failed_answer_is_reported_to_hook(tmp_path):
    seen = []
    core, _ = make(tmp_path, "not_running", on_decision=seen.append)
    decide(core)
    assert seen[0]["result"] == "not_running"


def test_parallel_clicks_and_appends_from_other_threads(tmp_path):
    core, b = make(tmp_path)
    out, gate, stop = [], threading.Barrier(2), threading.Event()

    def feeder():                                                            # Sprach-Schleife hängt ständig an
        i = 0
        while not stop.is_set():
            extra = Permission(f"x{i}", "Read", "", "")
            b.permissions.append(extra)                                      # kommt und geht, PERM bleibt im Puffer
            b.permissions.remove(extra)
            i += 1

    def click():
        gate.wait()
        out.append(decide(core))
    f = threading.Thread(target=feeder)
    f.start()
    ts = [threading.Thread(target=click) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    for _ in range(50):
        assert call(core, "approvals.get")["ok"]                             # Kopie, kein Fehler beim Iterieren
    stop.set()
    f.join()
    assert sorted(o.get("error", "ok") for o in out) == ["none", "ok"]
    assert b.answers == [("abcde", "allow")]
