"""Interface web de cliptv (stdlib uniquement), dans le navigateur d'un ordinateur ou d'un téléphone.

    clipbot app --port 8000   →   http://localhost:8000

Trois pages :
- **Clips** : regarder chaque vidéo, modifier la légende, programmer / publier / rejeter,
  lancer une recherche ponctuelle ;
- **Pilote auto** : réglages du mode 100 % automatique et état en direct ;
- **Comptes** : connecter Twitch, TikTok, YouTube et Instagram sans terminal, et
  vérifier toutes les connexions.

Si ``CLIPBOT_REVIEW_PASSWORD`` est défini, l'accès est protégé par mot de passe
(authentification HTTP Basic) : à faire impérativement sur un serveur, derrière HTTPS
(voir le service ``https`` de docker-compose.yml).
"""

from __future__ import annotations

import base64
import hmac
import html
import json
import logging
import mimetypes
import os
import re
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Config
from .pipeline import PLATFORMS, Options, publish_clip
from .schedule import format_when, parse_slots, schedule_clip
from .state import State

log = logging.getLogger("clipbot.review")
e = lambda v: html.escape(str(v if v is not None else ""))  # noqa: E731

PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0e0e10">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<title>cliptv</title>{refresh}
<style>
  :root {{ --bg:#0e0e10; --card:#18181b; --line:#2a2a2d; --fg:#efeff1; --muted:#adadb8; --accent:#9147ff; }}
  * {{ box-sizing:border-box }}
  body {{ margin:0; font:15px/1.45 system-ui,-apple-system,sans-serif; background:var(--bg); color:var(--fg) }}
  a {{ color:#bf94ff }}
  header {{ position:sticky; top:0; z-index:2; background:rgba(14,14,16,.94); backdrop-filter:blur(8px);
            padding:10px 16px 0; border-bottom:1px solid var(--line) }}
  .top {{ display:flex; align-items:center; gap:12px; justify-content:space-between; flex-wrap:wrap }}
  h1 {{ margin:0; font-size:20px }} h1 a {{ color:inherit; text-decoration:none }} h1 span {{ color:var(--accent) }}
  .pill {{ font-size:13px; color:var(--muted); background:var(--card); border-radius:999px; padding:4px 10px }}
  .pill.on {{ color:#7ee2a0; background:#123d1f }}
  nav {{ display:flex; gap:4px; overflow-x:auto; scrollbar-width:none; margin-top:8px }}
  nav a {{ color:var(--muted); padding:8px 10px; text-decoration:none; white-space:nowrap; border-bottom:2px solid transparent }}
  nav a.on {{ color:var(--fg); border-color:var(--accent) }}
  nav.sub {{ margin:0 0 12px; border-bottom:1px solid var(--line) }}
  .wrap {{ padding:16px; max-width:1400px; margin:0 auto }}
  .narrow {{ max-width:760px }}
  .panel {{ background:var(--card); border-radius:12px; padding:14px; margin-bottom:16px }}
  .panel h2 {{ margin:0 0 8px; font-size:17px }}
  details.panel summary {{ cursor:pointer; font-weight:600 }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin-top:12px }}
  .full {{ grid-column:1/-1 }}
  label {{ display:flex; flex-direction:column; gap:4px; font-size:13px; color:var(--muted) }}
  label.check {{ flex-direction:row; align-items:center; gap:8px; color:var(--fg); font-size:15px }}
  input, select, textarea {{ background:var(--bg); color:var(--fg); border:1px solid #333; border-radius:8px;
                             padding:10px; font:inherit; font-size:16px; width:100% }}
  input[type=checkbox] {{ width:20px; height:20px; flex:none }}
  .info, .meta {{ color:var(--muted); font-size:13px; overflow-wrap:anywhere }}
  .meta a {{ color:var(--muted) }}
  main {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:16px }}
  .card {{ background:var(--card); border-radius:12px; padding:12px; display:flex; flex-direction:column; gap:8px }}
  video {{ width:100%; aspect-ratio:9/16; max-height:72vh; object-fit:contain; background:#000; border-radius:8px }}
  textarea {{ min-height:96px; resize:vertical }}
  .row {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center }}
  button, .btn {{ flex:1 1 30%; min-height:44px; border:0; border-radius:8px; padding:10px 14px; font:inherit;
            font-weight:600; color:#fff; cursor:pointer; background:var(--accent); text-align:center; text-decoration:none }}
  button:disabled {{ opacity:.5; cursor:default }}
  .now {{ background:#5c16c5 }} .rej {{ background:#3a3a3d }} .small {{ flex:0 0 auto; min-height:36px; padding:6px 12px }}
  .when {{ font-weight:600 }}
  .badges {{ display:flex; gap:6px; flex-wrap:wrap }}
  .badge {{ font-size:12px; padding:2px 8px; border-radius:999px; background:var(--line); color:var(--muted) }}
  .badge.ok {{ background:#123d1f; color:#7ee2a0 }} .badge.failed {{ background:#3d1212; color:#ff9b9b }}
  .flash {{ padding:10px 12px; border-radius:8px; background:#1f3a1f; margin-bottom:16px }}
  .flash.err {{ background:#3a1f1f }}
  .acc {{ display:flex; justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap;
          padding:12px 0; border-top:1px solid var(--line) }}
  .acc:first-of-type {{ border-top:0 }}
  .acc > div:first-child {{ flex:1 1 300px }}
  .code {{ font:600 22px/1 ui-monospace,monospace; letter-spacing:2px; color:#fff }}
  table {{ width:100%; border-collapse:collapse }} td {{ padding:6px 4px; border-top:1px solid var(--line); vertical-align:top }}
  .empty {{ color:var(--muted) }}
  @media (max-width:600px) {{ .wrap {{ padding:12px }} main, .grid {{ grid-template-columns:1fr }} h1 {{ font-size:18px }} }}
</style></head><body>
<header><div class="top"><h1><a href="/">clip<span>tv</span></a></h1>
<span id="status" class="pill{status_cls}">{status}</span></div>
<nav>{nav}</nav></header>
<div class="wrap{wrap_cls}">
{flash}
{body}
</div>
<script>
// met à jour l'état du pilote / de la recherche sans recharger (une légende en cours d'édition n'est pas perdue)
setInterval(async () => {{
  try {{
    const s = await (await fetch('/status', {{credentials: 'same-origin'}})).json();
    const pill = document.getElementById('status');
    pill.textContent = s.message; pill.classList.toggle('on', s.active);
  }} catch (e) {{}}
}}, 10000);
</script>
</body></html>"""

FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<rect width="100" height="100" rx="22" fill="#9147ff"/><path d="M38 28 L74 50 L38 72 Z" fill="#fff"/></svg>"""

SECTIONS = [("/", "Clips"), ("/auto", "Pilote auto"), ("/accounts", "Comptes")]
TABS = [("rendered", "À valider"), ("scheduled", "Programmés"), ("published", "Publiés"),
        ("rejected", "Rejetés"), ("failed", "Erreurs")]
CLIP_ACTIONS = ("publish", "schedule", "reject", "unschedule")
HOURS = [(6, "6 dernières heures"), (24, "24 dernières heures"), (72, "3 derniers jours"),
         (168, "7 derniers jours")]
EVERY = [(15, "toutes les 15 min"), (30, "toutes les 30 min"), (60, "toutes les heures"),
         (120, "toutes les 2 h"), (240, "toutes les 4 h"), (720, "toutes les 12 h")]
RATIOS = [(2.0, "Très sensible (x2)"), (3.0, "Normale (x3)"), (5.0, "Peu sensible (x5)")]
PLATFORM_NAMES = {"tiktok": "TikTok", "youtube": "YouTube Shorts", "instagram": "Instagram Reels"}
CHANNEL_RE = re.compile(r"\w{2,25}")

CARD = """<div class="card">
  <video src="{video}" controls preload="metadata" playsinline></video>
  <div><strong>{title}</strong></div>
  <div class="meta">{channel} · {views} vues · <a href="{url}" target="_blank" rel="noopener">clip Twitch</a>{error}</div>
  {badges}
  {actions}
</div>"""

ACTIONS = """<form method="post" action="/schedule/{id}">
  <textarea name="caption" aria-label="Légende">{caption}</textarea>
  <div class="row">
    <button type="submit">Programmer</button>
    <button class="now" type="submit" formaction="/publish/{id}">{now_label}</button>
    <button class="rej" type="submit" formaction="/reject/{id}">Rejeter</button>
  </div>
</form>"""

SCHEDULED = """<div class="when">⏰ {when}</div>
<form method="post" action="/publish/{id}">
  <textarea name="caption" aria-label="Légende">{caption}</textarea>
  <div class="row">
    <button class="now" type="submit">Publier maintenant</button>
    <button class="rej" type="submit" formaction="/unschedule/{id}">Annuler</button>
  </div>
</form>"""

SEARCH = """<details class="panel">
<summary>🔎 Recherche ponctuelle</summary>
<form method="post" action="/search">
  <div class="grid">
    <label class="full">Chaînes Twitch (séparées par des virgules)
      <input name="channels" value="{channels}" placeholder="kamet0, zerator" required
             autocapitalize="none" autocorrect="off"></label>
    <label>Période <select name="hours">{hours}</select></label>
    <label>Clips par chaîne <input name="top" type="number" min="1" max="20" value="3"></label>
    <label>Ensuite
      <select name="then">
        <option value="review">À valider ici</option>
        <option value="schedule">Programmer automatiquement</option>
        <option value="publish">Publier tout de suite</option>
      </select></label>
    <label class="check"><input type="checkbox" name="ai" value="1" checked> Légende par Claude</label>
  </div>
  <div class="row" style="margin-top:12px"><button type="submit"{disabled}>Lancer la recherche</button></div>
</form>
</details>"""


def _options(items, selected) -> str:
    return "".join(f'<option value="{e(v)}"{" selected" if v == selected else ""}>{e(t)}</option>'
                   for v, t in items)


def _split_channels(raw: str) -> list[str]:
    return [c.lower() for c in re.split(r"[\s,]+", raw or "") if c]


# ---------------------------------------------------------------------------
# Tâches de fond lancées depuis le navigateur
# ---------------------------------------------------------------------------

@dataclass
class SearchJob:
    """Une seule recherche ponctuelle à la fois, dans un thread en arrière-plan."""
    running: bool = False
    message: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self, message: str, target, *args) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running, self.message = True, message
        threading.Thread(target=self._run, args=(target, *args), daemon=True).start()
        return True

    def _run(self, target, *args) -> None:
        try:
            self.message = target(*args)
        except (Exception, SystemExit) as exc:
            log.exception("Recherche échouée")
            self.message = f"Échec de la recherche : {exc}"
        finally:
            self.running = False


def run_search(job: SearchJob, cfg: Config, state: State, opts: Options, channels: list[str],
               hours: float, top: int) -> str:
    from .pipeline import run_channels
    from .twitch import TwitchClient

    cfg.require("twitch_client_id", "twitch_client_secret")
    cfg.ensure_dirs()
    twitch = TwitchClient(cfg.twitch_client_id, cfg.twitch_client_secret)
    started = time.time()
    results: list[tuple[str, bool]] = []
    for i, channel in enumerate(channels, 1):
        job.message = f"Recherche en cours : {channel} ({i}/{len(channels)})…"
        results += run_channels([channel], cfg, state, opts, twitch, hours=hours, top=top,
                                min_views=0)
    ok = sum(r[1] for r in results)
    ko = len(results) - ok
    if not results:
        return f"Aucun nouveau clip trouvé ({', '.join(channels)})"
    return (f"Recherche terminée : {ok} clip(s) prêt(s)" + (f", {ko} en erreur" if ko else "")
            + f" · {int(time.time() - started)} s")


@dataclass
class Pending:
    """Connexion par code (Twitch, YouTube) en attente de validation par l'utilisateur."""
    url: str = ""
    code: str = ""
    state: str = "pending"   # pending | ok | error
    message: str = ""


def start_device_flow(pendings: dict, name: str, client, url_key: str) -> None:
    device = client.start_device_flow()
    pending = Pending(url=device[url_key], code=device["user_code"])
    pendings[name] = pending

    def poll():
        try:
            client.poll_device_flow(device)
            pending.state, pending.message = "ok", "Compte connecté ✔"
        except Exception as exc:
            pending.state, pending.message = "error", str(exc)

    threading.Thread(target=poll, daemon=True).start()


@dataclass
class App:
    cfg: Config
    opts: Options
    state: State
    autopilot: object | None = None
    publish_lock: threading.Lock = field(default_factory=threading.Lock)
    job: SearchJob = field(default_factory=SearchJob)
    pending: dict = field(default_factory=dict)
    checks: list = field(default_factory=list)
    checks_at: float = 0
    oauth_state: str = field(default_factory=lambda: secrets.token_urlsafe(16))


# ---------------------------------------------------------------------------
# Serveur HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, app: App, **kwargs):
        self.app = app
        self.state, self.cfg, self.opts = app.state, app.cfg, app.opts
        super().__init__(*args, **kwargs)

    def log_message(self, fmt, *args):  # logs HTTP discrets
        log.debug(fmt, *args)

    @property
    def platforms(self) -> list[str]:
        return self.opts.platforms or self.cfg.platforms

    def _authorized(self) -> bool:
        if not self.cfg.review_password:
            return True
        expected = base64.b64encode(
            f"{self.cfg.review_user}:{self.cfg.review_password}".encode()).decode()
        given = self.headers.get("Authorization", "").removeprefix("Basic ").strip()
        if hmac.compare_digest(given.encode(), expected.encode()):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="cliptv", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    # ---------- état global (pastille en haut de page) ----------
    def _status(self) -> tuple[str, bool]:
        job, pilot = self.app.job, self.app.autopilot
        if job.running:
            return job.message, True
        if pilot is not None:
            from .autopilot import load_settings

            if load_settings(self.state, self.cfg)["enabled"]:
                return f"Pilote auto actif · {pilot.message}", True
            return job.message or "Pilote auto en pause", False
        return job.message or "Prêt", False

    def _page(self, body: str, section: str, *, narrow: bool = False, refresh: int = 0) -> None:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        flash = ""
        if "msg" in q:
            cls = "flash err" if q.get("err") else "flash"
            flash = f'<div class="{cls}">{e(q["msg"][0])}</div>'
        nav = "".join(f'<a class="{"on" if p == section else ""}" href="{p}">{label}</a>'
                      for p, label in SECTIONS)
        status, active = self._status()
        page = PAGE.format(
            nav=nav, flash=flash, body=body, status=e(status),
            status_cls=" on" if active else "", wrap_cls=" narrow" if narrow else "",
            refresh=f'\n<meta http-equiv="refresh" content="{refresh}">' if refresh else "")
        self._send(200, page, "text/html; charset=utf-8")

    # ---------- GET ----------
    def do_GET(self):
        if not self._authorized():
            return
        url = urllib.parse.urlparse(self.path)
        if url.path.startswith("/video/"):
            return self._send_video(url.path.removeprefix("/video/"))
        routes = {
            "/": self._clips_page,
            "/auto": self._auto_page,
            "/accounts": self._accounts_page,
            "/status": self._status_json,
            "/favicon.svg": lambda: self._send(200, FAVICON, "image/svg+xml"),
            "/connect/tiktok": self._tiktok_redirect,
            "/tiktok/callback": self._tiktok_callback,
        }
        handler = routes.get(url.path)
        if not handler:
            return self._send(404, "introuvable")
        return handler()

    def _status_json(self):
        message, active = self._status()
        self._send(200, json.dumps({"running": self.app.job.running, "active": active,
                                    "message": message}, ensure_ascii=False),
                   "application/json; charset=utf-8")

    # ---------- page Clips ----------
    def _clips_page(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        tab = q.get("s", ["rendered"])[0]
        counts = {s: self.state.count(s) for s, _ in TABS}
        tabs = "".join(
            f'<a class="{"on" if s == tab else ""}" href="/?s={s}">{label} ({counts[s]})</a>'
            for s, label in TABS)
        cards = "".join(self._card(c) for c in self.state.list(tab)) or \
            '<p class="empty">Rien ici pour le moment.</p>'
        info = e(f"Publication : {', '.join(PLATFORM_NAMES.get(p, p) for p in self.platforms)}"
                 f" · créneaux {', '.join(self.cfg.post_slots)} ({self.cfg.timezone})")
        body = (f'<nav class="sub">{tabs}</nav>{self._search_panel()}'
                f'<p class="info">{info}</p><main>{cards}</main>')
        self._page(body, "/")

    def _search_panel(self) -> str:
        from .autopilot import load_settings

        channels = ", ".join(load_settings(self.state, self.cfg)["channels"])
        return SEARCH.format(channels=e(channels), hours=_options(HOURS, 24),
                             disabled=" disabled" if self.app.job.running else "")

    def _card(self, c: dict) -> str:
        cid, status = e(c["clip_id"]), c["status"]
        if status == "rendered" or (status == "failed" and c.get("output_path")):
            label = "Réessayer" if status == "failed" else "Publier maintenant"
            actions = ACTIONS.format(id=cid, caption=e(c["caption"]), now_label=label)
        elif status == "scheduled":
            actions = SCHEDULED.format(id=cid, caption=e(c["caption"]),
                                       when=e(format_when(c["scheduled_at"], self.cfg.timezone)))
        else:
            actions = f'<div class="meta">{e(c["caption"])}</div>'
        posts = self.state.posts(c["clip_id"])
        badges = "".join(
            f'<span class="badge {e(p["status"])}" title="{e(p.get("error") or p.get("post_id"))}">'
            f'{e(PLATFORM_NAMES.get(name, name))} {"✔" if p["status"] == "ok" else "✖"}</span>'
            for name, p in posts.items())
        badges = f'<div class="badges">{badges}</div>' if badges else ""
        error = f" · ⚠️ {e(c['error'])}" if c.get("error") else ""
        return CARD.format(video=e(f'/video/{urllib.parse.quote(c["clip_id"], safe="")}'),
                           title=e(c["title"]), channel=e(c["channel"]),
                           views=e(c["view_count"]), url=e(c["url"]), error=error,
                           badges=badges, actions=actions)

    # ---------- page Pilote auto ----------
    def _auto_page(self):
        from .autopilot import load_settings, max_queue

        s = load_settings(self.state, self.cfg)
        pilot = self.app.autopilot
        if s["enabled"]:
            toggle = ('<form method="post" action="/auto/toggle"><div class="row">'
                      '<button class="rej" name="enabled" value="0">⏸ Mettre en pause</button>'
                      '<button class="now" formaction="/auto/run">▶ Chercher maintenant</button>'
                      '</div></form>')
            head = "🟢 Le pilote automatique est <strong>actif</strong>"
        else:
            toggle = ('<form method="post" action="/auto/toggle"><div class="row">'
                      '<button name="enabled" value="1">▶ Activer le pilote automatique</button>'
                      '</div></form>')
            head = "⏸ Le pilote automatique est <strong>en pause</strong>"
        lines = []
        if pilot is not None:
            lines.append(f"État : {e(pilot.message)}")
            if s["enabled"] and pilot.next_run:
                lines.append("Prochaine recherche : "
                             + e(format_when(int(pilot.next_run), self.cfg.timezone)))
            for channel, st in sorted(pilot.live_status.items()):
                lines.append(f"Live <strong>{e(channel)}</strong> : {e(st)}")
        queued = self.state.count("scheduled")
        lines.append(f"Clips programmés : {queued} / {max_queue(s)} max · publiés en 24 h : "
                     f"{self.state.count_since('published', time.time() - 86400)}")
        status = "".join(f'<div class="info">{line}</div>' for line in lines)

        checks = "".join(
            f'<label class="check"><input type="checkbox" name="platforms" value="{p}"'
            f'{" checked" if p in s["platforms"] else ""}> {PLATFORM_NAMES[p]}</label>'
            for p in PLATFORMS)
        then = _options([("schedule", "Programmer sur les créneaux"),
                         ("publish", "Publier dès que c'est prêt")], s["then"])
        body = f"""
<div class="panel"><h2>{head}</h2>
<p class="info">Il cherche les clips les plus viraux, les monte en vertical avec sous-titres,
écrit la légende, puis les publie aux heures choisies. Il surveille aussi les lives et
clippe chaque moment fort du chat. Tu n'as rien à faire : tu peux juste suivre
(ou annuler un clip) dans l'onglet Clips.</p>
{status}<div style="margin-top:12px">{toggle}</div></div>

<form method="post" action="/auto" class="panel"><h2>Réglages</h2>
<div class="grid">
  <label class="full">Chaînes dont on reprend les meilleurs clips
    <input name="channels" value="{e(', '.join(s['channels']))}" placeholder="kamet0, zerator"
           autocapitalize="none" autocorrect="off"></label>
  <label class="full">Lives à surveiller (clip automatique à chaque pic de chat)
    <input name="live_channels" value="{e(', '.join(s['live_channels']))}" placeholder="kamet0"
           autocapitalize="none" autocorrect="off"></label>
  <label>Fréquence de recherche <select name="every">{_options(EVERY, int(s['every']))}</select></label>
  <label>Clips récents de moins de <select name="hours">{_options(HOURS, int(s['hours']))}</select></label>
  <label>Clips max par chaîne <input name="top" type="number" min="1" max="20" value="{e(s['top'])}"></label>
  <label>Vues minimum <input name="min_views" type="number" min="0" value="{e(s['min_views'])}"></label>
  <label>Quand un clip est prêt <select name="then">{then}</select></label>
  <label>Sensibilité des lives <select name="ratio">{_options(RATIOS, float(s['ratio']))}</select></label>
  <label class="full">Heures de publication (heure de {e(self.cfg.timezone)})
    <input name="post_slots" value="{e(', '.join(s['post_slots']))}" placeholder="12:30, 18:00, 21:00"></label>
  <label>Clips programmés max (0 = auto) <input name="max_queue" type="number" min="0" value="{e(s['max_queue'])}"></label>
  <div class="full"><div class="info">Publier sur</div><div class="row">{checks}</div></div>
  <label class="check full"><input type="checkbox" name="ai_caption" value="1"{" checked" if s["ai_caption"] else ""}>
    Légendes et hashtags écrits par Claude</label>
</div>
<div class="row" style="margin-top:14px"><button type="submit">Enregistrer</button></div>
</form>"""
        self._page(body, "/auto", narrow=True)

    # ---------- page Comptes ----------
    def _accounts_page(self):
        cfg = self.cfg
        rows = []

        others: list[str] = []  # plateformes désactivées, repliées en bas

        def row(title: str, state: str, detail: str, action: str = "",
                dest: list[str] | None = None) -> None:
            (rows if dest is None else dest).append(f'<div class="acc"><div><strong>{title}</strong> {state}'
                        f'<div class="info">{detail}</div></div><div>{action}</div></div>')

        def pending_html(name: str, label: str) -> str | None:
            p = self.app.pending.get(name)
            if not p:
                return None
            if p.state == "pending":
                return (f'Ouvre <a href="{e(p.url)}" target="_blank" rel="noopener">{e(p.url)}</a>'
                        f' et entre le code : <span class="code">{e(p.code)}</span>')
            if p.state == "error":
                return f"⚠️ {label} : {e(p.message)}"
            return None

        has_twitch = bool(cfg.twitch_client_id and cfg.twitch_client_secret)
        row("Twitch (lecture des clips)", "✅" if has_twitch else "❌",
            "Clés configurées" if has_twitch else
            "Ajoute TWITCH_CLIENT_ID et TWITCH_CLIENT_SECRET dans le fichier .env")
        connected = cfg.twitch_token_path.exists()
        row("Twitch (clips des lives)", "✅" if connected else "—",
            pending_html("twitch", "Twitch") or
            ("Compte connecté" if connected else "Nécessaire seulement pour surveiller des lives"),
            self._button("/connect/twitch", "Reconnecter" if connected else "Connecter",
                         disabled=not has_twitch))

        for platform in PLATFORMS:
            dest = rows if platform in self.platforms else others
            if platform == "tiktok":
                keys = bool(cfg.tiktok_client_key and cfg.tiktok_client_secret)
                ok = cfg.tiktok_token_path.exists()
                callback = cfg.tiktok_redirect_uri or \
                    f"https://{self.headers.get('Host', 'ton-domaine')}/tiktok/callback"
                detail = ("Compte connecté (envoi en brouillon par défaut)" if ok else
                          f"Dans l'app TikTok Developers, l'URL de redirection doit être "
                          f"<code>{e(callback)}</code> (TIKTOK_REDIRECT_URI)")
                if not keys:
                    detail = "Ajoute TIKTOK_CLIENT_KEY et TIKTOK_CLIENT_SECRET dans .env"
                action = (f'<a class="btn small" href="/connect/tiktok">'
                          f'{"Reconnecter" if ok else "Connecter"}</a>') if keys else ""
                row("TikTok", "✅" if ok else "—", detail, action, dest)
            elif platform == "youtube":
                keys = bool(cfg.youtube_client_id and cfg.youtube_client_secret)
                ok = cfg.youtube_token_path.exists()
                detail = pending_html("youtube", "YouTube") or (
                    f"Chaîne connectée (vidéos en « {e(cfg.youtube_privacy)} »)" if ok else
                    "Ajoute YOUTUBE_CLIENT_ID et YOUTUBE_CLIENT_SECRET dans .env" if not keys
                    else "Connexion par code, comme pour une TV")
                row("YouTube Shorts", "✅" if ok else "—", detail,
                    self._button("/connect/youtube", "Reconnecter" if ok else "Connecter",
                                 disabled=not keys), dest)
            else:
                ok = cfg.instagram_token_path.exists() or bool(cfg.instagram_access_token)
                form = ('<form method="post" action="/connect/instagram" class="row" '
                        'style="margin-top:8px"><input name="token" required '
                        'placeholder="token longue durée Meta" autocomplete="off">'
                        '<button class="small">Enregistrer</button></form>')
                row("Instagram Reels", "✅" if ok else "—",
                    ("Token enregistré (prolongé automatiquement)" if ok else
                     "Compte pro + token longue durée du tableau de bord Meta") + form, dest=dest)

        claude = bool(os.environ.get("ANTHROPIC_API_KEY"))
        row("Claude (légendes)", "✅" if claude else "—",
            "Clé configurée" if claude else
            "Ajoute ANTHROPIC_API_KEY dans .env (sinon légende standard)")

        checks = ""
        if self.app.checks:
            from .doctor import ICONS

            when = format_when(int(self.app.checks_at), cfg.timezone)
            checks = (f'<p class="info">Dernière vérification : {e(when)}</p><table>' +
                      "".join(f"<tr><td>{ICONS[c.status]}</td><td>{e(c.label)}</td>"
                              f"<td class='info'>{e(c.detail)}</td></tr>"
                              for c in self.app.checks) + "</table>")
        more = ""
        if others:
            more = ('<details class="panel"><summary>Autres plateformes (désactivées — '
                    'à activer dans Pilote auto)</summary>' + "".join(others) + "</details>")
        body = f"""
<div class="panel"><h2>Comptes</h2>{''.join(rows)}</div>{more}
<div class="panel"><h2>Diagnostic</h2>
<p class="info">Teste ffmpeg, la police, et chaque connexion avec un vrai appel aux API.</p>
{checks}
<form method="post" action="/accounts/check" class="row" style="margin-top:12px">
<button>Tout vérifier</button></form></div>"""
        waiting = any(p.state == "pending" for p in self.app.pending.values())
        self._page(body, "/accounts", narrow=True, refresh=5 if waiting else 0)

    @staticmethod
    def _button(action: str, label: str, disabled: bool = False) -> str:
        return (f'<form method="post" action="{action}"><button class="small"'
                f'{" disabled" if disabled else ""}>{label}</button></form>')

    def _tiktok_redirect(self):
        from .tiktok import authorize_url

        cfg = self.cfg
        if not (cfg.tiktok_client_key and cfg.tiktok_redirect_uri):
            return self._redirect("TIKTOK_CLIENT_KEY / TIKTOK_REDIRECT_URI manquants dans .env",
                                  err=True, to="/accounts")
        self.send_response(302)
        self.send_header("Location", authorize_url(cfg.tiktok_client_key,
                                                   cfg.tiktok_redirect_uri,
                                                   state=self.app.oauth_state))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _tiktok_callback(self):
        from .tiktok import TikTokClient

        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if q.get("state", [""])[0] != self.app.oauth_state:
            return self._redirect("Connexion TikTok refusée (state invalide), réessaie.",
                                  err=True, to="/accounts")
        if "code" not in q:
            reason = q.get("error_description", q.get("error", ["annulée"]))[0]
            return self._redirect(f"Connexion TikTok : {reason}", err=True, to="/accounts")
        cfg = self.cfg
        try:
            client = TikTokClient(cfg.tiktok_client_key, cfg.tiktok_client_secret,
                                  cfg.tiktok_token_path)
            client.exchange_code(q["code"][0], cfg.tiktok_redirect_uri)
        except Exception as exc:
            return self._redirect(f"Connexion TikTok échouée : {exc}", err=True, to="/accounts")
        return self._redirect("TikTok connecté ✔", to="/accounts")

    def _send_video(self, clip_id: str):
        clip = self.state.get(urllib.parse.unquote(clip_id))
        path = Path(clip["output_path"]) if clip and clip.get("output_path") else None
        if not path or not path.exists():
            return self._send(404, "vidéo introuvable")
        size = path.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else max(size - int(b), 0)
            end = int(b) if a and b else size - 1
            end = min(end, size - 1)
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as fh:
            fh.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = fh.read(min(1 << 16, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)

    # ---------- POST ----------
    def _form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length") or 0)
        return urllib.parse.parse_qs(self.rfile.read(length).decode())

    def do_POST(self):
        if not self._authorized():
            return
        path = urllib.parse.urlparse(self.path).path
        form = self._form()
        one = {k: v[0] for k, v in form.items()}
        routes = {
            "/search": lambda: self._search(one),
            "/auto": lambda: self._save_auto(form),
            "/auto/toggle": lambda: self._toggle_auto(one),
            "/auto/run": self._run_auto,
            "/accounts/check": self._run_checks,
            "/connect/twitch": lambda: self._connect_device("twitch"),
            "/connect/youtube": lambda: self._connect_device("youtube"),
            "/connect/instagram": lambda: self._connect_instagram(one),
        }
        if path in routes:
            return routes[path]()
        parts = path.strip("/").split("/")
        if len(parts) == 2 and parts[0] in CLIP_ACTIONS:
            return self._clip_action(parts[0], urllib.parse.unquote(parts[1]), one)
        return self._send(404, "introuvable")

    def _clip_action(self, action: str, clip_id: str, form: dict[str, str]):
        clip = self.state.get(clip_id)
        if not clip:
            return self._redirect("Clip introuvable.", err=True)
        caption = form.get("caption", clip["caption"] or "").strip()

        if action == "unschedule":
            ok = self.state.unschedule(clip_id)
            return self._redirect("Programmation annulée." if ok else "Clip déjà parti.",
                                  err=not ok, tab="rendered")
        if action == "reject":
            if clip["status"] not in ("rendered", "failed"):
                return self._redirect("Clip déjà traité.", err=True)
            self.state.record(clip_id, clip["channel"], "rejected", caption=caption)
            return self._redirect("Clip rejeté.")
        if action == "schedule":
            when = schedule_clip(self.state, self.cfg, clip_id, caption)
            if not when:
                return self._redirect("Clip déjà traité.", err=True)
            return self._redirect(
                f"Programmé pour {format_when(int(when.timestamp()), self.cfg.timezone)} ✔")

        if not self.state.claim(clip_id, caption):
            return self._redirect("Clip déjà publié ou en cours de publication.", err=True)
        with self.app.publish_lock:  # une publication à la fois
            errors = publish_clip(clip_id, self.cfg, self.state, self.opts)
        if errors:
            return self._redirect("Échec : " + " | ".join(errors), err=True, tab="failed")
        names = ", ".join(PLATFORM_NAMES.get(p, p) for p in self.platforms)
        return self._redirect(f"Publié sur {names} ✔", tab="published")

    def _search(self, form: dict[str, str]):
        channels = _split_channels(form.get("channels", ""))
        if not channels or not all(CHANNEL_RE.fullmatch(c) for c in channels):
            return self._redirect("Indique des noms de chaînes Twitch valides.", err=True)
        try:
            hours = min(max(float(form.get("hours", 24)), 1), 24 * 30)
            top = min(max(int(form.get("top", 3)), 1), 20)
        except ValueError:
            return self._redirect("Paramètres de recherche invalides.", err=True)
        then = form.get("then", "review")
        opts = Options(**{**self.opts.__dict__, "ai_caption": form.get("ai") == "1",
                          "publish": then == "publish", "schedule": then == "schedule"})
        job = self.app.job
        if not job.start(f"Recherche en cours : {channels[0]}…", run_search, job, self.cfg,
                         self.state, opts, channels, hours, top):
            return self._redirect("Une recherche est déjà en cours.", err=True)
        return self._redirect("Recherche lancée : les clips apparaîtront ici au fur et à "
                              "mesure (téléchargement, sous-titres et rendu prennent "
                              "1 à 2 min par clip).")

    def _save_auto(self, form: dict[str, list[str]]):
        one = {k: v[0].strip() for k, v in form.items()}
        channels = _split_channels(one.get("channels", ""))
        live = _split_channels(one.get("live_channels", ""))
        bad = [c for c in channels + live if not CHANNEL_RE.fullmatch(c)]
        if bad:
            return self._redirect(f"Nom de chaîne invalide : {bad[0]}", err=True, to="/auto")
        slots = [s for s in re.split(r"[\s,;]+", one.get("post_slots", "")) if s]
        try:
            parse_slots(slots)
            values = {
                "channels": channels,
                "live_channels": live,
                "every": int(one.get("every", 60)),
                "hours": int(one.get("hours", 24)),
                "top": min(max(int(one.get("top", 2)), 1), 20),
                "min_views": max(int(one.get("min_views", 0)), 0),
                "then": "publish" if one.get("then") == "publish" else "schedule",
                "ratio": float(one.get("ratio", 3)),
                "post_slots": slots,
                "max_queue": max(int(one.get("max_queue", 0)), 0),
                "platforms": [p for p in form.get("platforms", []) if p in PLATFORMS],
                "ai_caption": one.get("ai_caption") == "1",
            }
        except (ValueError, SystemExit) as exc:
            return self._redirect(f"Réglage invalide : {exc}", err=True, to="/auto")
        if not values["platforms"]:
            return self._redirect("Choisis au moins une plateforme.", err=True, to="/auto")
        self.state.save_settings(values)
        self._settings_changed()
        return self._redirect("Réglages enregistrés ✔", to="/auto")

    def _toggle_auto(self, form: dict[str, str]):
        enabled = form.get("enabled") == "1"
        self.state.save_settings({"enabled": enabled})
        self._settings_changed()
        return self._redirect("Pilote automatique activé ✔" if enabled else
                              "Pilote automatique en pause.", to="/auto")

    def _run_auto(self):
        if self.app.autopilot is None:
            return self._redirect("Pilote automatique indisponible.", err=True, to="/auto")
        self.app.autopilot.run_now()
        return self._redirect("Recherche lancée ✔", to="/auto")

    def _settings_changed(self):
        from .autopilot import apply_settings, load_settings

        apply_settings(self.cfg, load_settings(self.state, self.cfg))
        if self.app.autopilot is not None:
            self.app.autopilot.refresh()

    def _run_checks(self):
        from .doctor import check_local, check_online

        fonts = self.opts.fonts_dir or Path("fonts")
        self.app.checks = check_local(self.cfg, fonts, render=False) + check_online(self.cfg)
        self.app.checks_at = time.time()
        return self._redirect("Vérification terminée.", to="/accounts")

    def _connect_device(self, name: str):
        cfg = self.cfg
        try:
            if name == "twitch":
                from .twitch import TwitchUserAuth

                cfg.require("twitch_client_id")
                client = TwitchUserAuth(cfg.twitch_client_id, cfg.twitch_client_secret,
                                        cfg.twitch_token_path)
                start_device_flow(self.app.pending, name, client, "verification_uri")
            else:
                from .youtube import YouTubeClient

                cfg.require("youtube_client_id", "youtube_client_secret")
                client = YouTubeClient(cfg.youtube_client_id, cfg.youtube_client_secret,
                                       cfg.youtube_token_path)
                start_device_flow(self.app.pending, name, client, "verification_url")
        except (Exception, SystemExit) as exc:
            return self._redirect(f"Connexion impossible : {exc}", err=True, to="/accounts")
        return self._redirect("Entre le code affiché sur la page indiquée.", to="/accounts")

    def _connect_instagram(self, form: dict[str, str]):
        from .instagram import InstagramClient

        cfg = self.cfg
        try:
            ig = InstagramClient(cfg.instagram_token_path, user_id=cfg.instagram_user_id,
                                 host=cfg.instagram_graph_host)
            ig.save(form.get("token", "").strip(), cfg.instagram_user_id)
            name = ig.account().get("username", "?")
        except (Exception, SystemExit) as exc:
            return self._redirect(f"Token Instagram refusé : {exc}", err=True, to="/accounts")
        return self._redirect(f"Instagram connecté (@{name}) ✔", to="/accounts")

    # ---------- utilitaires ----------
    def _redirect(self, msg: str, err: bool = False, tab: str | None = None, to: str = "/"):
        q = urllib.parse.urlencode({"msg": msg, **({"err": 1} if err else {}),
                                    **({"s": tab} if tab else {})})
        self.send_response(303)
        self.send_header("Location", f"{to}?{q}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, code: int, body: str, ctype: str = "text/plain; charset=utf-8"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def make_server(cfg: Config, opts: Options, host: str = "127.0.0.1", port: int = 8000,
                state: State | None = None, autopilot=None):
    cfg.ensure_dirs()
    app = App(cfg=cfg, opts=opts, state=state or State(cfg.db_path), autopilot=autopilot)
    return ThreadingHTTPServer((host, port), partial(Handler, app=app))
