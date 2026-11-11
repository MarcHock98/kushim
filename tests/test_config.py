

def test_speaker_check_is_off_by_default_and_only_true_turns_it_on(tmp_path):
    from kushim.config import Config
    p = tmp_path / "config.toml"
    assert Config.load(p).voice_speaker_check is False                      # keine Datei
    p.write_text('[voice]\nclone = false\n', encoding="utf-8")
    assert Config.load(p).voice_speaker_check is False
    p.write_text('[voice]\nspeaker_check = "true"\n', encoding="utf-8")
    assert Config.load(p).voice_speaker_check is False                      # nur ein echtes true
    cfg = Config.load(p)
    cfg.set_speaker_check(True)
    assert Config.load(p).voice_speaker_check is True and p.read_text(encoding="utf-8").count("speaker_check") == 1
    cfg.set_speaker_check(False)
    assert Config.load(p).voice_speaker_check is False
    p.write_text('[memory]\nlocation = "local:~/v"\n', encoding="utf-8")
    Config.load(p).set_speaker_check(True)
    data = p.read_text(encoding="utf-8")
    assert "[voice]" in data and 'location = "local:~/v"' in data and Config.load(p).voice_speaker_check is True
