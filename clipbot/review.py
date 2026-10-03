"""Mini interface web pour valider les clips avant publication (stdlib uniquement).

    clipbot review --port 8000   →   http://localhost:8000
"""

from __future__ import annotations

import html
import logging
import mimetypes
import threading
import urllib.parse
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Config
from .pipeline import Options, publish
from .state import State

log = logging.getLogger("clipbot.review")

PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>cliptv · revue</title>
<style>
  :root {{ --bg:#0e0e10; --card:#18181b; --fg:#efeff1; --muted:#adadb8; --accent:#9147ff; --ok:#00c853; --ko:#ff4d4d; }}
  * {{ box-sizing:border-box }}
  body {{ margin:0; font:15px/1.4 system-ui,sans-serif; background:var(--bg); color:var(--fg) }}
  header {{ padding:16px; display:flex; gap:16px; align-items:baseline; flex-wrap:wrap }}
  h1 {{ margin:0; font-size:20px }}
  nav a {{ color:var(--muted); margin-right:12px; text-decoration:none }}
  nav a.on {{ color:var(--fg); border-bottom:2px solid var(--accent) }}
  main {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:16px; padding:0 16px 32px }}
  .card {{ background:var(--card); border-radius:12px; padding:12px; display:flex; flex-direction:column; gap:8px }}
  video {{ width:100%; aspect-ratio:9/16; background:#000; border-radius:8px }}
  .meta {{ color:var(--muted); font-size:13px }}
  .meta a {{ color:var(--muted) }}
  textarea {{ width:100%; min-height:90px; background:#0e0e10; color:var(--fg); border:1px solid #333; border-radius:8px; padding:8px; font:inherit }}
  .row {{ display:flex; gap:8px }}
  button {{ flex:1; border:0; border-radius:8px; padding:10px; font-weight:600; color:#fff; cursor:pointer }}
  .pub {{ background:var(--accent) }} .rej {{ background:#3a3a3d }}
  .flash {{ margin:0 16px 16px; padding:10px; border-radius:8px; background:#1f3a1f }}
  .flash.err {{ background:#3a1f1f }}
  .empty {{ color:var(--muted); padding:16px }}
</style></head><body>
<header><h1>cliptv</h1><nav>{nav}</nav></header>
{flash}
<main>{cards}</main>
</body></html>"""

CARD = """<div class="card">
  <video src="/video/{id}" controls preload="metadata" playsinline></video>
  <div><strong>{title}</strong></div>
  <div class="meta">{channel} · {views} vues · <a href="{url}" target="_blank" rel="noopener">clip Twitch</a>{error}</div>
  {actions}
</div>"""

ACTIONS = """<form method="post" action="/publish/{id}">
  <textarea name="caption">{caption}</textarea>
  <div class="row">
    <button class="pub" type="submit">Publier sur TikTok</button>
    <button class="rej" type="submit" formaction="/reject/{id}">Rejeter</button>
  </div>
</form>"""

TABS = [("rendered", "À valider"), ("published", "Publiés"), ("rejected", "Rejetés"),
        ("failed", "Erreurs")]


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, state: State, cfg: Config, opts: Options, lock: threading.Lock,
                 **kwargs):
        self.state, self.cfg, self.opts, self.lock = state, cfg, opts, lock
        super().__init__(*args, **kwargs)

    def log_message(self, fmt, *args):  # logs HTTP discrets
        log.debug(fmt, *args)

    # ---------- pages ----------
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path.startswith("/video/"):
            return self._send_video(url.path.removeprefix("/video/"))
        if url.path != "/":
            return self._send(404, "introuvable")
        q = urllib.parse.parse_qs(url.query)
        tab = q.get("s", ["rendered"])[0]
        nav = "".join(
            f'<a class="{"on" if s == tab else ""}" href="/?s={s}">{label} '
            f'({len(self.state.list(s))})</a>'
            for s, label in TABS
        )
        cards = "".join(self._card(c) for c in self.state.list(tab)) or \
            '<p class="empty">Rien ici pour le moment.</p>'
        flash = ""
        if "msg" in q:
            cls = "flash err" if q.get("err") else "flash"
            flash = f'<div class="{cls}">{html.escape(q["msg"][0])}</div>'
        self._send(200, PAGE.format(nav=nav, cards=cards, flash=flash), "text/html; charset=utf-8")

    def _card(self, c: dict) -> str:
        e = lambda v: html.escape(str(v or ""))  # noqa: E731
        actions = ACTIONS.format(id=e(c["clip_id"]), caption=e(c["caption"])) \
            if c["status"] == "rendered" else f'<div class="meta">{e(c["caption"])}</div>'
        error = f" · ⚠️ {e(c['error'])}" if c.get("error") else ""
        return CARD.format(id=e(c["clip_id"]), title=e(c["title"]), channel=e(c["channel"]),
                           views=e(c["view_count"]), url=e(c["url"]), error=error,
                           actions=actions)

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

    # ---------- actions ----------
    def do_POST(self):
        parts = self.path.strip("/").split("/")
        if len(parts) != 2 or parts[0] not in ("publish", "reject"):
            return self._send(404, "introuvable")
        action, clip_id = parts[0], urllib.parse.unquote(parts[1])
        clip = self.state.get(clip_id)
        if not clip or clip["status"] != "rendered":
            return self._redirect("Clip introuvable ou déjà traité.", err=True)
        length = int(self.headers.get("Content-Length") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(length).decode())
        caption = form.get("caption", [clip["caption"] or ""])[0].strip()

        if action == "reject":
            self.state.record(clip_id, clip["channel"], "rejected", caption=caption)
            return self._redirect("Clip rejeté.")
        with self.lock:  # une publication à la fois
            try:
                publish_id = publish(Path(clip["output_path"]), caption, self.cfg, self.opts)
            except (Exception, SystemExit) as exc:
                log.exception("Publication échouée")
                return self._redirect(f"Échec de la publication : {exc}", err=True)
        self.state.record(clip_id, clip["channel"], "published", caption=caption,
                          publish_id=publish_id)
        mode = "envoyé dans ta boîte de réception TikTok" if self.opts.mode == "draft" \
            else "publié"
        return self._redirect(f"Clip {mode} ✔")

    # ---------- utilitaires ----------
    def _redirect(self, msg: str, err: bool = False):
        q = urllib.parse.urlencode({"msg": msg, **({"err": 1} if err else {})})
        self.send_response(303)
        self.send_header("Location", f"/?{q}")
        self.end_headers()

    def _send(self, code: int, body: str, ctype: str = "text/plain; charset=utf-8"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def make_server(cfg: Config, opts: Options, host: str = "127.0.0.1", port: int = 8000):
    cfg.ensure_dirs()
    handler = partial(Handler, state=State(cfg.db_path), cfg=cfg, opts=opts,
                      lock=threading.Lock())
    return ThreadingHTTPServer((host, port), handler)
