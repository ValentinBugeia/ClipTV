"""Claude par l'abonnement (faux Claude Code) : pas de clé API transmise, réponse JSON lue,
erreurs expliquées ; le juré écarte les clips faibles."""

import json
import os
import stat
from types import SimpleNamespace

import pytest

from clipbot import llm

FAKE = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
stdin = sys.stdin.read()
with open(os.environ["FAKE_LOG"], "w") as f:
    json.dump({"args": args, "stdin": stdin, "api_key": os.environ.get("ANTHROPIC_API_KEY")}, f)
if os.environ.get("FAKE_OLD") and "--effort" in args:  # ancienne version de Claude Code
    print("error: unknown option '--effort'", file=sys.stderr)
    sys.exit(1)
print(json.dumps({"type": "system", "subtype": "init"}))
if os.environ.get("FAKE_MODE") == "login":
    print(json.dumps({"type": "result", "is_error": True,
                      "result": "Invalid API key · Please run /login"}))
    sys.exit(1)
print(json.dumps({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed",
    "unifiedWindows": {"five_hour": {"utilization": 0.36, "resetsAt": 9999999999},
                       "seven_day": {"utilization": 0.1, "resetsAt": 9999999999}}}}))
print(json.dumps({"type": "result", "is_error": False, "result": os.environ["FAKE_RESULT"],
                  "usage": {"input_tokens": 100, "cache_read_input_tokens": 1400,
                            "output_tokens": 40}, "total_cost_usd": 0.01, "duration_ms": 900}))
"""


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    exe = tmp_path / "bin" / "claude"
    exe.parent.mkdir()
    exe.write_text(FAKE)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "call.json"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-ne-doit-pas-servir")
    llm.reset_pause()  # une erreur d'un autre test ne met pas Claude en pause ici

    def last_call():
        return json.loads((tmp_path / "call.json").read_text())
    return last_call


def test_subscription_call_strips_api_key(fake_claude, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_RESULT", 'Voici :\n```json\n{"hook": "Il hurle", "hashtags": []}\n```')
    img = tmp_path / "a.jpg"
    img.write_bytes(b"x")
    data = llm.ask_json(system="s", prompt="p", schema={"type": "object"}, images=[img])
    assert data["hook"] == "Il hurle"
    call = fake_claude()
    assert call["api_key"] is None  # jamais facturé sur une clé API
    message = json.loads(call["stdin"])  # un seul message : l'image est jointe directement
    kinds = [c["type"] for c in message["message"]["content"]]
    assert kinds == ["image", "text"] and "--tools" in call["args"]


def test_old_claude_code_without_new_options(fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_OLD", "1")
    monkeypatch.setenv("FAKE_RESULT", '{"ok": true}')
    assert llm.ask_json(system="s", prompt="p", schema={}) == {"ok": True}
    assert "--effort" not in fake_claude()["args"]


def test_not_logged_in_is_explained(fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "login")
    with pytest.raises(llm.ClaudeError, match="/login"):
        llm.ask_json(system="s", prompt="p", schema={})


def test_caption_via_subscription(fake_claude, monkeypatch):
    from clipbot import captions

    monkeypatch.setenv("FAKE_RESULT", json.dumps({"hook": "Il découvre son score",
                                                  "question": "Tu t'attendais à ça ? 👇",
                                                  "hashtags": ["fyp"]}))
    text = captions.generate_caption(title="t", channel="Nico_La", transcript="")
    assert text.splitlines()[:2] == ["Il découvre son score 👀", "Tu t'attendais à ça ? 👇"]


def test_jury_drops_weak_clips(fake_claude, monkeypatch, tmp_path):
    import subprocess

    from clipbot import selection

    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=320x180:duration=2", "-f", "lavfi", "-i", "sine=duration=2",
                    "-shortest", "-pix_fmt", "yuv420p", str(video)], check=True)
    monkeypatch.setattr("clipbot.jury.quick_transcript",
                        lambda v, language=None: [__import__("clipbot.subtitles").subtitles.Word("mdr", 0.5, 1.0)])
    monkeypatch.setenv("FAKE_RESULT", json.dumps({"clips": [
        {"id": "bon", "score": 8, "standalone": True, "reason": "fou rire"},
        {"id": "nul", "score": 2, "standalone": False, "reason": "blague interne"}]}))

    def clip(cid):
        return SimpleNamespace(id=cid, title=cid, broadcaster_name="x", duration=20,
                               category="", audio=None)
    copies = {}
    for cid in ("bon", "nul"):
        copies[cid] = tmp_path / f"{cid}.mp4"
        copies[cid].write_bytes(video.read_bytes())
    opts = SimpleNamespace(jury=True)
    sources = {cid: (lambda p=p: str(p)) for cid, p in copies.items()}
    kept = selection.pick_best([(clip("nul"), "x"), (clip("bon"), "x")], sources, 1,
                               jury=selection.jury_for(opts))
    assert [c.id for c, _ in kept] == ["bon"] and kept[0][0].jury["score"] == 8
    assert not copies["nul"].exists()  # vidéo écartée supprimée
    # 2 clips demandés : le clip faible complète, après le bon
    for cid in ("bon", "nul"):
        copies[cid].write_bytes(video.read_bytes())
    kept = selection.pick_best([(clip("nul"), "x"), (clip("bon"), "x")], sources, 2,
                               jury=selection.jury_for(opts))
    assert [c.id for c, _ in kept] == ["bon", "nul"]


def test_jury_writes_publication(fake_claude, monkeypatch):
    """Le juré prépare aussi la description, l'accroche à l'écran, l'emoji et l'alerte."""
    from clipbot.enhance import reaction_emoji
    from clipbot.pipeline import Options, make_caption

    clip = SimpleNamespace(id="c", title="kekw", broadcaster_name="Nico_La", category="",
                           tiktok_handle=None,
                           jury={"hook": "Sa mère débarque en plein live", "question":
                                 "Vous auriez fait quoi ? 👇", "hashtags": ["nicola", "irl"],
                                 "overlay": "ELLE NE SAVAIT PAS…", "reaction": "cry",
                                 "moderation": ""})
    text = make_caption(clip, [], None, Options(ai_caption=True))
    assert text.splitlines()[:2] == ["Sa mère débarque en plein live 😭", "Vous auriez fait quoi ? 👇"]
    assert reaction_emoji([], 1.0, "mdr", preferred="cry").stem == "cry"
    assert reaction_emoji([], 1.0, "mdr", preferred="none") is None


def test_usage_recorded(fake_claude, monkeypatch, tmp_path):
    from clipbot import progress
    from clipbot.config import Config
    from clipbot.state import State

    cfg = Config()
    cfg.data_dir = tmp_path
    state = State(cfg.db_path)
    from clipbot import claude_usage

    monkeypatch.setattr(llm, "recorder", lambda *a: claude_usage.record(state, *a))
    monkeypatch.setenv("FAKE_RESULT", '{"ok": true}')
    progress.begin("test")
    llm.ask_json(system="s", prompt="p", schema={}, purpose="radar")
    rows = state.claude_usage(0)
    assert rows[0]["purpose"] == "radar" and rows[0]["calls"] == 1
    assert rows[0]["tokens_in"] == 1500 and rows[0]["tokens_out"] == 40
    assert progress.snapshot()["tokens"] == 1540
    progress.end("ok")
    limits = claude_usage.summary(state)["windows"]
    assert [round(w["used"], 2) for w in limits] == [0.36, 0.1]  # relevé de l'abonnement


def test_searches_left_estimate(tmp_path):
    from clipbot import claude_usage
    from clipbot.config import Config
    from clipbot.state import State

    cfg = Config()
    cfg.data_dir = tmp_path
    state = State(cfg.db_path)
    win = lambda u: {"unifiedWindows": {"five_hour": {"utilization": u, "resetsAt": 9999999999}}}
    claude_usage.record(state, "radar", 9000, 1000, 0, 0, win(0.30))
    claude_usage.record(state, "radar", 9000, 1000, 0, 0, win(0.32))  # 10 k tokens = 2 %
    for _ in range(3):
        claude_usage.search_done(state, 10000)
    w = claude_usage.summary(state)["windows"][0]
    assert w["searches_left"] == 34  # 68 % restant / 2 % par recherche
    assert claude_usage.short_line(state) == "68 % restant · ≈ 34 recherches"


def test_failure_pauses_claude_for_the_search(fake_claude, monkeypatch):
    """Claude Code bloqué ou déconnecté : on n'attend pas à chaque clip de la recherche."""
    monkeypatch.setenv("FAKE_MODE", "login")
    with pytest.raises(llm.ClaudeError):
        llm.ask_json(system="s", prompt="p", schema={})
    monkeypatch.setenv("FAKE_MODE", "ok")
    monkeypatch.setenv("FAKE_RESULT", '{"ok": true}')
    with pytest.raises(llm.ClaudeError, match="pause"):
        llm.ask_json(system="s", prompt="p", schema={})
    llm.reset_pause()  # nouvelle recherche
    assert llm.ask_json(system="s", prompt="p", schema={}) == {"ok": True}


def test_second_radar_round_before_weak_clips(monkeypatch, tmp_path):
    """Pas assez de clips publiables : d'autres clips sont regardés avant de compléter
    avec des clips faibles."""
    from clipbot import selection

    monkeypatch.setattr(selection, "audio_profile",
                        lambda p: {"reaction": 4, "peak_at": 1, "duration": 20})
    verdicts = {"a": 8, "b": 3, "c": 7, "d": 2}

    def jury(items):
        return {c.id: {"score": verdicts[c.id], "standalone": True, "reason": ""}
                for c, _ in items}
    jury.language = None
    monkeypatch.setattr("clipbot.jury.quick_transcript", lambda v, language=None: [])

    def clip(cid):
        return SimpleNamespace(id=cid, title=cid, duration=20, audio=None)
    paths = {}
    for cid in "abcd":
        paths[cid] = tmp_path / f"{cid}.mp4"
        paths[cid].write_bytes(b"x")
    src = {cid: (lambda p=p: str(p)) for cid, p in paths.items()}
    asked = []

    def more():
        asked.append(1)
        return [(clip("c"), "x"), (clip("d"), "x")], src
    kept = selection.pick_best([(clip("a"), "x"), (clip("b"), "x")], src, 2, jury=jury,
                               more=more)
    assert asked and sorted(c.id for c, _ in kept) == ["a", "c"]
    assert not paths["b"].exists() and not paths["d"].exists()


def test_clip_reads_vod_position():
    from clipbot.twitch import Clip

    base = {"id": "x", "url": "u", "created_at": "2026-01-01T00:00:00Z"}
    assert Clip.from_api({**base, "video_id": "42", "vod_offset": 1234}).vod_offset == 1234.0
    assert Clip.from_api({**base, "video_id": "", "vod_offset": None}).vod_offset is None


def test_radar_never_judges_a_clip_twice(monkeypatch, tmp_path):
    """Clip déjà jugé lors d'une recherche récente : ni téléchargé, ni réécouté, ni
    renvoyé à Claude."""
    from clipbot import jury as jury_mod
    from clipbot import llm, selection
    from clipbot.state import State

    state = State(tmp_path / "s.db")
    monkeypatch.setattr(llm, "available", lambda: True)
    calls = []

    def judge(items, language=None):
        calls.append([c.id for c, _ in items])
        return {c.id: {"score": 8, "standalone": True, "reason": ""} for c, _ in items}
    monkeypatch.setattr(jury_mod, "judge", judge)
    monkeypatch.setattr(jury_mod, "quick_transcript", lambda v, language=None: [])
    monkeypatch.setattr(selection, "audio_profile",
                        lambda p: {"reaction": 4, "peak_at": 1, "duration": 20})
    clip = SimpleNamespace(id="a", title="a", duration=20, audio=None)
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    radar = selection.jury_for(SimpleNamespace(jury=True), state=state)
    selection.pick_best([(clip, "x")], {"a": lambda: str(video)}, 1, jury=radar)
    assert calls == [["a"]]
    radar = selection.jury_for(SimpleNamespace(jury=True), state=state)  # recherche suivante
    assert selection.to_download([clip], radar) == []

    def no_download():
        raise AssertionError("téléchargé")
    again = SimpleNamespace(id="a", title="a", duration=20, audio=None)
    kept = selection.pick_best([(again, "x")], {"a": no_download}, 1, jury=radar)
    assert calls == [["a"]] and kept[0][0].jury["score"] == 8
