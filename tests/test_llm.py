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


def test_claude_completes_every_clip(fake_claude, monkeypatch, tmp_path):
    """Claude ne trie pas : chaque clip est gardé, avec le début / la fin qu'il a choisis
    (ou la découpe automatique s'il n'en donne pas de valable)."""
    import subprocess

    from clipbot import selection
    from clipbot.moments import Window
    from clipbot.subtitles import Word

    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=320x180:duration=30", "-f", "lavfi", "-i", "sine=duration=30",
                    "-shortest", "-pix_fmt", "yuv420p", str(video)], check=True)
    monkeypatch.setattr("clipbot.jury.quick_transcript",
                        lambda v, language=None, **k: [Word("mdr", 12.0, 13.0)])
    monkeypatch.setenv("FAKE_RESULT", json.dumps({"clips": [
        {"id": "a", "reason": "ajouté la question avant", "hook": "Il craque 😂",
         "question": "", "hashtags": [], "overlay": "", "reaction": "laugh",
         "moderation": "", "hook_theme": "", "hook_color": "", "start": 2.0, "end": 26.0},
        {"id": "b", "reason": "", "hook": "", "question": "", "hashtags": [], "overlay": "",
         "reaction": "", "moderation": "", "hook_theme": "", "hook_color": "",
         "start": 5.0, "end": 6.0}]}))  # absurde : découpe automatique gardée

    def clip(cid):
        return SimpleNamespace(id=cid, title=cid, broadcaster_name="x", duration=20.0,
                               category="")
    a, b = clip("a"), clip("b")
    win = lambda: Window(video, 100.0, 30.0, (5.0, 25.0))
    selection.complete([(a, "x"), (b, "x")], {"a": win, "b": win}, SimpleNamespace(jury=True))
    assert a.cut == (2.0, 26.0) and a.jury["hook"] == "Il craque 😂"
    assert b.cut != (5.0, 6.0) and b.cut[1] - b.cut[0] >= 10
    # sans Claude : la découpe automatique, aucun appel
    c = clip("c")
    monkeypatch.setenv("FAKE_MODE", "login")
    selection.complete([(c, "x")], {"c": win}, SimpleNamespace(jury=False))
    assert c.cut and not hasattr(c, "jury")


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


def test_clip_reads_vod_position():
    from clipbot.twitch import Clip

    base = {"id": "x", "url": "u", "created_at": "2026-01-01T00:00:00Z"}
    assert Clip.from_api({**base, "video_id": "42", "vod_offset": 1234}).vod_offset == 1234.0
    assert Clip.from_api({**base, "video_id": "", "vod_offset": None}).vod_offset is None


def test_claude_unavailable_is_reported(monkeypatch, tmp_path):
    """Claude coché mais indisponible : la recherche le signale et chaque clip aussi."""
    from clipbot import progress, selection
    from clipbot.moments import Window

    monkeypatch.setattr(llm, "available", lambda: False)
    monkeypatch.setattr("clipbot.jury.quick_transcript", lambda v, language=None, **k: [])
    monkeypatch.setattr("clipbot.subtitles.load_audio", lambda p: None)
    clip = SimpleNamespace(id="a", title="a", broadcaster_name="x", duration=20.0)
    progress.begin("test")
    selection.complete([(clip, "x")], {"a": lambda: Window(tmp_path / "a.mp4", None, 20.0,
                                                               (0.0, 20.0))},
                       SimpleNamespace(jury=True))
    assert "Claude indisponible" in progress.warning() and clip.claude_missing
    progress.end("Recherche terminée")
    assert "⚠️ Claude indisponible" in progress.snapshot()["message"]
    progress.begin("suivante")
    assert progress.warning() == ""  # nouvelle recherche : alerte effacée
    progress.end("ok")


def test_windows_npm_launcher_gets_instructions_in_the_message(fake_claude, monkeypatch, tmp_path):
    """Claude Code installé avec npm sous Windows (claude.cmd) : cmd.exe abîme les arguments
    sur plusieurs lignes, les consignes passent donc dans le message."""
    cmd = tmp_path / "bin" / "claude.cmd"
    cmd.write_text(FAKE)
    cmd.chmod(cmd.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(llm, "cli_path", lambda: str(cmd))
    monkeypatch.setenv("FAKE_RESULT", '{"ok": true}')
    assert llm.ask_json(system="ligne 1\nligne 2 « é »", prompt="p", schema={}) == {"ok": True}
    call = fake_claude()
    assert "--append-system-prompt" not in call["args"] and "" not in call["args"]
    text = json.loads(call["stdin"])["message"]["content"][-1]["text"]
    assert text.startswith("CONSIGNES :\nligne 1\nligne 2 « é »")


def test_claude_keeps_the_strongest_candidates(tmp_path):
    """Avec Claude : ~2× plus de candidats, les mieux notés sont montés (à note égale, les
    plus vus) ; les extraits des autres sont supprimés. Sans Claude : les plus vus."""
    from clipbot import selection
    from clipbot.moments import Window

    def clip(cid, views, score):
        path = tmp_path / f"{cid}.mp4"
        path.write_bytes(b"x")
        return SimpleNamespace(id=cid, title=cid, broadcaster_name="x", view_count=views,
                               jury={"score": score}, window=Window(path, 0.0, 30.0, (0, 30)))
    found = [(clip("vu", 9000, 4), "x"), (clip("fou", 3000, 9), "x"),
             (clip("bon", 2000, 7), "x"), (clip("bon2", 2500, 7), "x")]
    kept = selection.choose(found, 2)
    assert [c.id for c, _ in kept] == ["fou", "bon2"]
    assert not (tmp_path / "vu.mp4").exists() and (tmp_path / "fou.mp4").exists()
    assert selection.candidates(3, SimpleNamespace(jury=False)) == 3


def test_unreadable_reply_is_asked_again_without_pausing(fake_claude, monkeypatch):
    """Texte ou 2e objet après le JSON : lu quand même. Réponse vraiment illisible :
    ReplyError, sans mettre Claude en pause pour la suite de la recherche."""
    monkeypatch.setenv("FAKE_RESULT", '{"clips": [{"id": "a"}]}\n\n{"remarque": "ok"}')
    assert llm.ask_json(system="s", prompt="p", schema={"required": ["clips"]}) == \
        {"clips": [{"id": "a"}]}
    monkeypatch.setenv("FAKE_RESULT", "désolé, pas de JSON")
    with pytest.raises(llm.ReplyError):
        llm.ask_json(system="s", prompt="p", schema={})
    monkeypatch.setenv("FAKE_RESULT", '{"ok": true}')
    assert llm.ask_json(system="s", prompt="p", schema={}) == {"ok": True}  # pas de pause
