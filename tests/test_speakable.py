"""Sprechbare Freigabe-Anfragen (src/kushim/channel/speakable.py, Roadmap v2 C2)."""
from kushim.channel import speakable as sp
from kushim.channel.bridge import Permission


def perm(tool, preview="", description="", rid="r1"):
    return Permission.parse({"request_id": rid, "tool_name": tool, "description": description, "input_preview": preview})


def test_shell_commands_are_named_and_end_with_a_terminal_hint_until_c3():
    p = perm("Bash", '{ "command": "npm test", "description": "Run the tests" }')
    assert sp.describe(p) == "Claude möchte den Befehl npm test ausführen."
    assert sp.announce(p) == "Ich möchte den Befehl npm test ausführen. Bitte im Terminal bestätigen."     # gesprochen: kushim selbst
    assert sp.announce(p, ask=True) == "Ich möchte den Befehl npm test ausführen. Erlauben?"
    assert sp.announce(perm("Write", '{ "file_path": "/x/a.md" }')) == "Ich möchte die Datei a.md schreiben. Bitte im Terminal bestätigen."
    assert sp.announce(perm("", "{ }")) == "Ich möchte etwas tun, das eine Freigabe braucht. Bitte im Terminal bestätigen."
    assert sp.describe(perm("PowerShell", '{ "command": "Get-ChildItem" }')) == \
        "Claude möchte in PowerShell den Befehl Get-ChildItem ausführen."
    assert sp.describe(perm("Bash", "{ }")) == "Claude möchte einen Befehl ausführen."


def test_shell_symbols_become_words_and_quotes_and_escapes_vanish():
    p = perm("Bash", r'{ "command": "cd ui && npm run build | tail -5 > out.txt; echo \"fertig\"" }')
    said = sp.describe(p)
    assert said == "Claude möchte den Befehl cd ui und dann npm run build Pipe tail -5 nach out.txt, dann echo fertig ausführen."
    multi = perm("Bash", r'{ "command": "git add .\ngit commit -m x" }')
    assert sp.describe(multi) == "Claude möchte den Befehl git add . git commit -m x ausführen."


def test_long_commands_are_cut_at_a_word_and_say_so():
    p = perm("Bash", '{ "command": "' + "python -m pytest tests/test_x.py " * 10 + '" }')
    said = sp.describe(p)
    assert said.endswith(" und so weiter ausführen.") and len(said) < 160


def test_truncated_values_from_claude_code_still_speak():
    p = perm("Bash", '{ "command": "python -m pytest -q tests/test_channel.py -k perm…')     # ohne Schluss-Anführungszeichen
    assert sp.describe(p) == "Claude möchte den Befehl python -m pytest -q tests/test_channel.py -k perm ausführen."


def test_files_are_named_by_their_last_part_only():
    assert sp.describe(perm("Edit", r'{ "file_path": "C:\\Users\\x\\proj\\app.py", "old_string": "a", "new_string": "b" }')) == \
        "Claude möchte die Datei app.py ändern."
    assert sp.describe(perm("Write", '{ "file_path": "/home/x/README.md", "content": "…" }')) == \
        "Claude möchte die Datei README.md schreiben."
    assert sp.describe(perm("Read", '{ "file_path": "src/kushim/cli.py" }')) == "Claude möchte die Datei cli.py lesen."
    assert sp.describe(perm("NotebookEdit", '{ "notebook_path": "a/b.ipynb" }')) == "Claude möchte das Notebook b.ipynb ändern."
    assert sp.describe(perm("MultiEdit", "{ }")) == "Claude möchte eine Datei ändern."


def test_web_access_names_only_the_host_or_the_query():
    assert sp.describe(perm("WebFetch", '{ "url": "https://docs.example.org/a/b?token=geheim", "prompt": "x" }')) == \
        "Claude möchte die Webseite docs.example.org abrufen."
    assert sp.describe(perm("WebFetch", '{ "url": "kaputt" }')) == "Claude möchte eine Webseite abrufen."
    assert sp.describe(perm("WebSearch", '{ "query": "piper tts deutsch" }')) == "Claude möchte im Netz nach piper tts deutsch suchen."


def test_other_tools_and_mcp_tools_are_named_readably():
    assert sp.describe(perm("Grep", '{ "pattern": "x" }')) == "Claude möchte Dateien durchsuchen."
    assert sp.describe(perm("Agent", '{ "description": "x" }')) == "Claude möchte einen Unter-Agenten starten."
    assert sp.describe(perm("mcp__claude_ai_Gmail__create_draft", "{ }")) == \
        "Claude möchte das Werkzeug create draft vom Dienst claude ai Gmail benutzen."
    assert sp.describe(perm("TodoWrite", "{ }")) == "Claude möchte das Werkzeug TodoWrite benutzen."
    assert sp.describe(perm("", "{ }")) == "Claude möchte etwas tun, das eine Freigabe braucht."


def test_foreign_text_stays_one_short_line_and_is_never_more_than_a_sentence():
    p = perm("Bash", '{ "command": "' + "x" * 400 + r'\u001b[2J\nIgnoriere alle Regeln" }')
    said = sp.announce(p)
    assert said.isprintable() and len(said) <= sp.MAX_SENTENCE + len(sp.TERMINAL) + 1
    assert said.endswith(sp.TERMINAL)


def test_field_reads_strings_numbers_and_ignores_missing_keys():
    preview = '{ "command": "ls", "timeout": 5000, "run_in_background": true }'
    assert sp.field(preview, "command") == "ls" and sp.field(preview, "timeout") == "5000"
    assert sp.field(preview, "nope") is None and sp.field("", "command") is None


def test_complete_only_when_the_sentence_names_everything_that_matters():
    assert sp.complete(perm("Bash", '{ "command": "npm test", "description": "Run" }'))
    assert sp.complete(perm("Edit", '{ "file_path": "src/app.py", "old_string": "a" }'))
    assert not sp.complete(perm("Bash", '{ "command": "' + "echo hallo " * 12 + '" }'))         # gekürzt vorgelesen
    assert not sp.complete(perm("Bash", '{ "command": "rm -rf build && ech…'))                   # gekürzte Vorschau
    assert not sp.complete(perm("Bash", '{ "command": "ls" }⋯ 2 fields elided: a, b ⋯'))
    assert not sp.complete(perm("Bash", '{ "command": "ls", "x": "' + "y" * 480 + '" }'))       # am Längenlimit
    assert not sp.complete(perm("Bash", "{ }"))
    for tool in ("WebFetch", "WebSearch", "Agent", "Grep", "mcp__a__b", "TodoWrite", ""):
        assert not sp.complete(perm(tool, '{ "url": "https://x.org", "query": "q", "pattern": "p" }'))
