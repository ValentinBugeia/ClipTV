import threading
from pathlib import Path
import urllib.parse
import urllib.error
import urllib.request

import pytest

from clipbot.config import Config
from clipbot.pipeline import Options
from clipbot.review import make_server
from clipbot.state import State


@pytest.fixture()
def server(tmp_path):
    cfg = Config()
    cfg.data_dir = tmp_path
    video = tmp_path / "v.mp4"
    video.write_bytes(bytes(range(256)) * 4)
    state = State(cfg.db_path)
    state.record("abc", "kamet0", "rendered", title="<b>Énorme</b>", url="https://x",
                 view_count=42, output_path=str(video), caption="légende #fyp")
    srv = make_server(cfg, Options(), port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", state
    srv.shutdown()


def test_list_page_escapes_and_shows_clip(server):
    base, _ = server
    body = urllib.request.urlopen(base + "/").read().decode()
    assert "&lt;b&gt;Énorme&lt;/b&gt;" in body and "légende #fyp" in body
    assert "À valider (1)" in body


def test_video_range(server):
    base, _ = server
    req = urllib.request.Request(base + "/video/abc", headers={"Range": "bytes=10-19"})
    resp = urllib.request.urlopen(req)
    assert resp.status == 206 and resp.read() == bytes(range(10, 20))
    assert resp.headers["Content-Range"] == "bytes 10-19/1024"


def test_reject(server):
    base, state = server
    data = "caption=nouvelle+l%C3%A9gende".encode()
    urllib.request.urlopen(urllib.request.Request(base + "/reject/abc", data=data))
    row = state.get("abc")
    assert row["status"] == "rejected" and row["caption"] == "nouvelle légende"


def _post(url, data=b"caption=ok"):
    return urllib.request.urlopen(urllib.request.Request(url, data=data))


def test_schedule_then_cancel(server):
    base, state = server
    body = _post(base + "/schedule/abc").read().decode()
    assert "Programmé pour" in body
    assert state.get("abc")["status"] == "scheduled" and state.get("abc")["scheduled_at"]
    _post(base + "/unschedule/abc")
    assert state.get("abc")["status"] == "rendered"


def test_publish_now(server, monkeypatch):
    from clipbot import pipeline

    import time

    def slow_publish(p, *a):
        time.sleep(0.5)  # TikTok met du temps à confirmer
        return f"{p}-1"

    monkeypatch.setattr(pipeline, "publish_to", slow_publish)
    base, state = server
    body = _post(base + "/publish/abc").read().decode()
    assert "Envoi lancé" in body and "Envoi en cours" in body
    assert state.get("abc")["status"] == "publishing"   # visible dans l'onglet dédié
    assert "Envoi vers TikTok en cours" in urllib.request.urlopen(
        base + "/?s=publishing").read().decode()
    body = _post(base + "/publish/abc").read().decode()
    assert "déjà publié" in body                         # pas de double envoi
    for _ in range(30):
        if state.get("abc")["status"] == "published":
            break
        time.sleep(0.1)
    assert state.get("abc")["status"] == "published"
    assert "boîte de réception" in urllib.request.urlopen(
        base + "/?s=published").read().decode()


def test_stuck_publishing_recovered_on_start(tmp_path):
    from clipbot.state import State

    st = State(tmp_path / "s.sqlite3")
    st.record("x", "c", "rendered", output_path="v.mp4")
    st.claim("x")
    assert st.recover_stuck(older_than=0) == 1
    assert st.get("x")["status"] == "failed" and "interrompue" in st.get("x")["error"]


def test_password(tmp_path):
    cfg = Config()
    cfg.data_dir = tmp_path
    cfg.review_user, cfg.review_password = "admin", "s3cret"
    srv = make_server(cfg, Options(), port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(base)
        assert exc.value.code == 401
        import base64
        auth = base64.b64encode(b"admin:s3cret").decode()
        req = urllib.request.Request(base, headers={"Authorization": f"Basic {auth}"})
        assert urllib.request.urlopen(req).status == 200
    finally:
        srv.shutdown()


def test_search_from_browser(server, monkeypatch):
    import time

    from clipbot import review

    seen = {}

    def fake_search(job, cfg, state, opts, channels, hours, top):
        seen.update(channels=channels, hours=hours, top=top, schedule=opts.schedule,
                    ai=opts.ai_caption)
        return "Recherche terminée : 2 clip(s) prêt(s)"

    monkeypatch.setattr(review, "run_search", fake_search)
    base, _ = server
    body = _post(base + "/search",
                 b"channels=Kamet0%2C+zerator&hours=72&top=2&then=schedule&ai=1").read().decode()
    assert "Recherche lancée" in body
    for _ in range(50):
        status = urllib.request.urlopen(base + "/status").read().decode()
        if '"running": false' in status:
            break
        time.sleep(0.05)
    assert "Recherche terminée : 2 clip(s) prêt(s)" in status
    assert seen == {"channels": ["kamet0", "zerator"], "hours": 72.0, "top": 2,
                    "schedule": True, "ai": True}


def test_search_rejects_bad_channel(server):
    base, _ = server
    body = _post(base + "/search", b"channels=%3Cscript%3E").read().decode()
    assert "noms de chaînes Twitch valides" in body


def test_auto_settings_saved_and_validated(server):
    base, state = server
    data = urllib.parse.urlencode([
        ("channels", "Kamet0, zerator"), ("live_channels", "gotaga"), ("every", "30"),
        ("hours", "72"), ("top", "3"), ("min_views", "100"), ("then", "schedule"),
        ("ratio", "2.0"), ("post_slots", "12:00, 19:30"), ("max_queue", "0"),
        ("platforms", "tiktok"), ("platforms", "youtube"), ("ai_caption", "1")]).encode()
    body = _post(base + "/auto", data).read().decode()
    assert "Réglages enregistrés" in body and "kamet0, zerator" in body
    s = state.get_settings()
    assert s["channels"] == ["kamet0", "zerator"] and s["live_channels"] == ["gotaga"]
    assert s["platforms"] == ["tiktok", "youtube"] and s["post_slots"] == ["12:00", "19:30"]
    assert s["every"] == 30 and s["ai_caption"] is True

    bad = data.replace(b"19%3A30", b"19h30")
    assert "Réglage invalide" in _post(base + "/auto", bad).read().decode()
    assert state.get_settings()["post_slots"] == ["12:00", "19:30"]

    body = _post(base + "/auto/toggle", b"enabled=1").read().decode()
    assert "activé" in body and state.get_settings()["enabled"] is True


def test_pages_render(server):
    base, _ = server
    for path in ("/auto", "/accounts", "/?s=scheduled", "/favicon.svg"):
        assert urllib.request.urlopen(base + path).status == 200
    body = urllib.request.urlopen(base + "/accounts").read().decode()
    assert "Twitch (lecture des clips)" in body and "Tout vérifier" in body


def test_search_without_channels_uses_discovery(server, monkeypatch):
    from clipbot import review

    seen = {}
    monkeypatch.setattr(review, "run_search",
                        lambda job, cfg, state, opts, channels, hours, top:
                        seen.setdefault("channels", channels) and "" or "ok")
    base, _ = server
    body = _post(base + "/search", b"channels=&hours=24&top=3&then=review").read().decode()
    assert "Recherche lancée" in body
    import time
    time.sleep(0.2)
    assert seen["channels"] == []


def test_ui_password_and_keys(server):
    import base64

    base, state = server
    _post(base + "/keys", b"TWITCH_CLIENT_ID=abc&TWITCH_CLIENT_SECRET=xyz")
    assert state.get_settings()["keys"]["TWITCH_CLIENT_SECRET"] == "xyz"
    body = urllib.request.urlopen(base + "/accounts").read().decode()
    assert 'value="abc"' in body and "xyz" not in body  # le secret n'est jamais réaffiché

    with pytest.raises(urllib.error.HTTPError):  # la redirection exige déjà le mot de passe
        _post(base + "/password", b"password=motdepasse")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(base + "/")
    assert exc.value.code == 401
    auth = base64.b64encode(b"nimporte:motdepasse").decode()
    req = urllib.request.Request(base + "/", headers={"Authorization": f"Basic {auth}"})
    assert urllib.request.urlopen(req).status == 200


def test_tiktok_code_paste_extracts_code(server, monkeypatch):
    from clipbot import tiktok

    got = {}
    monkeypatch.setattr(tiktok.TikTokClient, "exchange_code",
                        lambda self, code, uri, verifier=None: got.setdefault("code", code))
    base, state = server
    _post(base + "/keys", b"TIKTOK_CLIENT_KEY=k&TIKTOK_CLIENT_SECRET=s"
                          b"&TIKTOK_REDIRECT_URI=https%3A%2F%2Fex.com%2Fcb")
    url = urllib.parse.quote("https://ex.com/cb?code=ABC%2A123&state=x", safe="")
    body = _post(base + "/connect/tiktok-code", f"code={url}".encode()).read().decode()
    assert "TikTok connecté" in body and got["code"] == "ABC*123"


@pytest.mark.parametrize("header", ["X-Forwarded-For", "CF-Connecting-IP",
                                    "Tailscale-Funnel-Request"])
def test_tunnel_is_not_treated_as_local(server, header):
    base, _ = server
    req = urllib.request.Request(base + "/", headers={header: "1"})
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 403


def test_tiktok_expired_code_message(server, monkeypatch):
    from clipbot import tiktok

    def refuse(self, code, uri, verifier=None):
        raise RuntimeError("Échange OAuth TikTok refusé : {'error': 'invalid_grant', "
                           "'error_description': 'Authorization code is expired.'}")

    monkeypatch.setattr(tiktok.TikTokClient, "exchange_code", refuse)
    base, _ = server
    _post(base + "/keys", b"TIKTOK_CLIENT_KEY=k&TIKTOK_CLIENT_SECRET=s"
                          b"&TIKTOK_REDIRECT_URI=https%3A%2F%2Fex.com%2Fcb")
    body = _post(base + "/connect/tiktok-code", b"code=abc").read().decode()
    assert "a expiré ou a déjà servi" in body and "Reclique sur" in body


@pytest.mark.parametrize("raw,code", [
    ("https://example.com/tiktok/callback?code=AbC%2A1%21&scopes=x&state=s", "AbC*1!"),
    ("https://example.com/cb?state=s&code=a+b%2Ac", "a+b*c"),
    ("AbC%2A1", "AbC*1"),
    ("code=AbC%2A1", "AbC*1"),
])
def test_extract_oauth_code(raw, code):
    from clipbot.review import extract_oauth_code

    assert extract_oauth_code(raw) == code


def test_manual_publishing(server):
    base, state = server
    body = urllib.request.urlopen(base + "/").read().decode()
    assert "Télécharger" in body and "Copier la légende" in body
    resp = urllib.request.urlopen(base + "/video/abc?dl=1")
    assert resp.headers["Content-Disposition"] == 'attachment; filename="v.mp4"'
    _post(base + "/done/abc", b"")
    assert state.get("abc")["status"] == "published"
    assert state.posts("abc")["manuel"]["status"] == "ok"


def test_manual_mode_setting(server):
    base, state = server
    data = urllib.parse.urlencode([("then", "manual"), ("platforms", "tiktok"),
                                   ("post_slots", "18:00")]).encode()
    _post(base + "/auto", data)
    assert state.get_settings()["then"] == "manual"


def test_accounts_page_in_manual_mode(server):
    base, state = server
    state.save_settings({"then": "manual"})
    body = urllib.request.urlopen(base + "/accounts").read().decode()
    assert "Pas nécessaire en mode" in body and 'href="/connect/tiktok"' not in body


def test_tiktok_pkce_round_trip(server, monkeypatch):
    import hashlib

    from clipbot import tiktok

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    base, state = server
    _post(base + "/keys", b"TIKTOK_CLIENT_KEY=k&TIKTOK_CLIENT_SECRET=s"
                          b"&TIKTOK_REDIRECT_URI=https%3A%2F%2Fex.com%2Fcb")
    opener = urllib.request.build_opener(NoRedirect)
    with pytest.raises(urllib.error.HTTPError) as exc:
        opener.open(base + "/connect/tiktok")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(exc.value.headers["Location"]).query)
    verifier = state.get_settings()["tiktok_pkce"]
    assert q["code_challenge"] == [hashlib.sha256(verifier.encode()).hexdigest()]
    assert q["code_challenge_method"] == ["S256"]
    assert q["scope"] == ["user.info.basic,video.upload"]

    got = {}
    monkeypatch.setattr(tiktok.TikTokClient, "exchange_code",
                        lambda self, code, uri, v=None: got.update(code=code, verifier=v))
    _post(base + "/connect/tiktok-code", b"code=https%3A%2F%2Fex.com%2Fcb%3Fcode%3DXYZ")
    assert got == {"code": "XYZ", "verifier": verifier}


def test_layout_setting_and_status_version(server):
    import json

    base, state = server
    v1 = json.loads(urllib.request.urlopen(base + "/status").read())["version"]
    data = urllib.parse.urlencode([("layout", "crop"), ("platforms", "tiktok"),
                                   ("post_slots", "18:00")]).encode()
    _post(base + "/auto", data)
    assert state.get_settings()["layout"] == "crop"
    state.record("new", "c", "rendered", title="t")
    v2 = json.loads(urllib.request.urlopen(base + "/status").read())["version"]
    assert v1 != v2


def test_redo_without_subtitles(server, monkeypatch, tmp_path):
    import time

    from clipbot import pipeline

    base, state = server
    cfg_downloads = Path(state.get("abc")["output_path"]).parent / "downloads"
    cfg_downloads.mkdir(exist_ok=True)
    (cfg_downloads / "abc.mp4").write_bytes(b"src")
    seen = {}

    def fake_render(src, dst, cfg, opts, **kw):
        seen.update(src=src.name, layout=opts.layout, subtitles=opts.subtitles)
        time.sleep(0.2)
        return dst, []

    monkeypatch.setattr(pipeline, "render_video", fake_render)
    before = state.get("abc")["updated_at"]
    time.sleep(1.1)
    body = _post(base + "/redo/abc", b"layout=crop").read().decode()
    assert "Remontage lancé" in body and "Remontage en cours" in body
    for _ in range(40):
        if state.get("abc")["updated_at"] != before:
            break
        time.sleep(0.1)
    assert seen == {"src": "abc.mp4", "layout": "crop", "subtitles": False}
    row = state.get("abc")
    assert row["status"] == "rendered" and row["updated_at"] != before


def test_subtitles_setting(server):
    base, state = server
    data = urllib.parse.urlencode([("platforms", "tiktok"), ("post_slots", "18:00")]).encode()
    _post(base + "/auto", data)
    assert state.get_settings()["subtitles"] is False  # case décochée


def test_stats_page(server):
    base, state = server
    body = urllib.request.urlopen(base + "/stats?p=7").read().decode()
    assert "Activer les statistiques TikTok" in body and "Activité de cliptv" in body
    _post(base + "/stats/enable", b"")
    assert state.get_settings()["tiktok_stats"] is True


def test_progress_in_status(server):
    import json

    from clipbot import progress

    base, _ = server
    progress.begin("Recherche ponctuelle")
    progress.clip(1, 2, "Clip test")
    progress.step("transcribe")
    s = json.loads(urllib.request.urlopen(base + "/status").read())
    assert s["progress"]["active"] and s["progress"]["step"] == "transcribe"
    assert s["progress"]["clip"] == "Clip 1/2 : Clip test"
    assert [k for k, _, _ in s["steps"]][:2] == ["search", "download"]
    progress.end("Terminé")
    s = json.loads(urllib.request.urlopen(base + "/status").read())
    assert not s["progress"]["active"] and s["progress"]["message"] == "Terminé"
    assert 'id="progress"' in urllib.request.urlopen(base + "/").read().decode()


def test_stop_search(server, monkeypatch):
    import time

    from clipbot import progress, review

    def slow_search(job, cfg, state, opts, channels, hours, top):
        progress.begin("Recherche ponctuelle")
        try:
            for _ in range(100):
                progress.step("search")
                time.sleep(0.05)
        except progress.Cancelled:
            progress.end("Recherche arrêtée")
            return "Recherche arrêtée"
        return "fini"

    monkeypatch.setattr(review, "run_search", slow_search)
    base, _ = server
    _post(base + "/search", b"channels=kamet0")
    time.sleep(0.3)
    assert urllib.request.urlopen(urllib.request.Request(base + "/stop", data=b"")).status == 200
    for _ in range(40):
        if not progress.snapshot()["active"]:
            break
        time.sleep(0.05)
    assert progress.snapshot()["message"] == "Recherche arrêtée"
