import json
from types import SimpleNamespace

from kushim.api.dashboard_api import register_dashboard
from kushim.api.protocol import ApiCore, new_token
from kushim.tasks import TaskRegistry
from kushim.timers import TimerStore
from kushim.voice.tool_commands import ToolCommands
from kushim.web.sanitize import Untrusted

TOKEN = new_token()


def make(tmp_path):
    cmds = ToolCommands(SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), SimpleNamespace(on_finish=None),
                        lambda w: "Zusammenfassung", lambda: [])
    timers = TimerStore(tmp_path, clock=lambda: 1000.0)
    tasks = TaskRegistry()
    core = ApiCore(TOKEN)
    register_dashboard(core, cmds, timers, tasks, clock=lambda: 1000.0)
    return core, cmds, timers, tasks


def get(core):
    return json.loads(core.handle(json.dumps({"token": TOKEN, "type": "dashboard.get"})))


def claude_out(answer, note=""):
    return SimpleNamespace(kind="claude", answer=Untrusted(answer), wiki=None, note=note)


def wiki_out(*pairs):
    srcs = [SimpleNamespace(title=t, url=u, text="x") for t, u in pairs]
    return SimpleNamespace(kind="wikipedia", answer=Untrusted(""), wiki=SimpleNamespace(sources=srcs), note="")


def test_empty_dashboard(tmp_path):
    core, *_ = make(tmp_path)
    assert get(core) == {"ok": True, "timers": [], "tasks": [], "pending_approvals": 0, "results": []}


def test_timers_sorted_with_remaining_seconds(tmp_path):
    core, _, timers, _ = make(tmp_path)
    timers.add(600, "Nudeln")
    timers.add(60, "Tee")
    r = get(core)
    assert [(t["label"], t["due_in"]) for t in r["timers"]] == [("Tee", 60.0), ("Nudeln", 600.0)]


def test_running_tasks_are_listed(tmp_path):
    core, _, _, tasks = make(tmp_path)
    with tasks.running("Recherche"):
        assert get(core)["tasks"] == ["Recherche"]
    assert get(core)["tasks"] == []


def test_research_results_are_remembered_newest_first_as_plain_text(tmp_path):
    core, cmds, *_ = make(tmp_path)
    cmds._last_query = "Höhe des Eiffelturms"
    cmds._speak_research(claude_out("324 Meter <script>alert(1)</script>", note="Claude"))
    cmds._last_query = "Mia"
    cmds._speak_research(wiki_out(("Eiffelturm", "https://de.wikipedia.org/wiki/Eiffelturm")))
    res = get(core)["results"]
    assert [r["query"] for r in res] == ["Mia", "Höhe des Eiffelturms"]
    assert res[0]["sources"] == [{"title": "Eiffelturm", "url": "https://de.wikipedia.org/wiki/Eiffelturm"}]
    assert "324 Meter" in res[1]["answer"] and res[1]["note"] == "Claude"
    assert set(res[0]) == {"ts", "query", "kind", "answer", "note", "sources"}


def test_results_are_bounded_and_only_in_memory(tmp_path):
    core, cmds, *_ = make(tmp_path)
    for i in range(15):
        cmds._last_query = f"f{i}"
        cmds._speak_research(claude_out("a"))
    assert len(get(core)["results"]) == 10 and get(core)["results"][0]["query"] == "f14"
    assert not any(p.name.endswith(".json") and "result" in p.name for p in tmp_path.rglob("*"))


def test_broken_outcome_never_breaks_the_voice_answer(tmp_path):
    _, cmds, *_ = make(tmp_path)
    assert cmds._speak_research(SimpleNamespace(kind="none", note="nichts", answer=None, wiki=None)) == "nichts"


def test_needs_token(tmp_path):
    core, *_ = make(tmp_path)
    assert json.loads(core.handle(json.dumps({"type": "dashboard.get"})))["error"] == "unauthorized"
