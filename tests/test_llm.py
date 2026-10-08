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
print(json.dumps({"type": "result", "is_error": False, "result": os.environ["FAKE_RESULT"]}))
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
    assert text.splitlines()[:2] == ["Il découvre son score", "Tu t'attendais à ça ? 👇"]


def test_jury_drops_weak_clips(fake_claude, monkeypatch, tmp_path):
    import subprocess

    from clipbot import selection

    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=320x180:duration=2", "-f", "lavfi", "-i", "sine=duration=2",
                    "-shortest", "-pix_fmt", "yuv420p", str(video)], check=True)
    monkeypatch.setattr("clipbot.jury.quick_transcript", lambda v, language=None: "mdr")
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
    kept = selection.pick_best([(clip("nul"), "x"), (clip("bon"), "x")],
                               {cid: (lambda p=p: str(p)) for cid, p in copies.items()}, 2,
                               jury=selection.jury_for(opts))
    assert [c.id for c, _ in kept] == ["bon"] and kept[0][0].jury["score"] == 8
    assert not copies["nul"].exists()  # vidéo écartée supprimée
