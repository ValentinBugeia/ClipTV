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
  form.act textarea {{ min-height:0; font-size:14px; padding:8px }}
  .bar {{ display:flex; gap:6px; margin-top:6px; align-items:stretch }}
  .bar > button {{ flex:1 1 0; min-height:38px; padding:6px 8px; font-size:14px }}
  details.more {{ position:relative; flex:0 0 auto }}
  .iconbtn {{ list-style:none; height:100%; min-height:38px; width:42px; display:grid; place-items:center;
             background:#3a3a3d; border-radius:8px; cursor:pointer; font-weight:700; font-size:18px }}
  .iconbtn::-webkit-details-marker {{ display:none }}
  details.more[open] .iconbtn {{ background:#4a4a4f }}
  .menu {{ position:absolute; right:0; top:calc(100% + 6px); z-index:5; width:250px; background:#1f1f23;
          border:1px solid #333; border-radius:10px; padding:6px; display:flex; flex-direction:column;
          gap:2px; box-shadow:0 10px 30px rgba(0,0,0,.5) }}
  .menu > a, .menu > button {{ background:transparent; color:var(--fg); text-align:left; text-decoration:none;
          padding:9px 10px; min-height:0; border-radius:6px; font-weight:500; font-size:14px; flex:none }}
  .menu > a:hover, .menu > button:hover {{ background:#2a2a2d }}
  .menu .danger {{ color:#ff9b9b }}
  .menu .redo {{ border-top:1px solid #2a2a2d; border-bottom:1px solid #2a2a2d; margin:4px 0; padding:8px 10px;
          display:flex; flex-wrap:wrap; gap:6px; align-items:center; font-size:14px }}
  .menu .redo span {{ flex:1 1 100% }}
  .menu .redo select {{ flex:1 1 100%; padding:6px; font-size:14px }}
  .menu .redo label {{ flex:1; font-size:14px }}
  .menu .redo button {{ flex:0 0 auto; min-height:32px; padding:4px 12px; font-size:14px }}
  .badges {{ display:flex; gap:6px; flex-wrap:wrap }}
  .badge {{ font-size:12px; padding:2px 8px; border-radius:999px; background:var(--line); color:var(--muted) }}
  .badge.ok {{ background:#123d1f; color:#7ee2a0 }} .badge.failed {{ background:#3d1212; color:#ff9b9b }}
  .pot {{ --r:#9d9d9d; flex-basis:100% }}
  .pot.r-uncommon {{ --r:#3ddc4a }} .pot.r-rare {{ --r:#4da3ff }} .pot.r-epic {{ --r:#b964ff }}
  .pot.r-legendary {{ --r:#ff9a1f }}
  .pot summary {{ cursor:pointer; list-style:none; display:inline-flex; align-items:baseline; gap:6px;
    padding:4px 10px; border-radius:8px; border:1px solid var(--r);
    background:color-mix(in srgb, var(--r) 14%, transparent) }}
  .pot summary::-webkit-details-marker {{ display:none }}
  .pot .note {{ color:var(--r); font-size:22px; font-weight:800; line-height:1 }}
  .pot .max {{ color:var(--muted); font-size:12px }}
  .pot .rar {{ color:var(--r); font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.04em }}
  .pot.r-legendary summary {{ box-shadow:0 0 12px color-mix(in srgb, var(--r) 45%, transparent) }}
  .pot ul {{ margin:6px 0 0; padding-left:18px; color:var(--muted); font-size:12px }}
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
<div id="fresh" class="flash" style="display:none;margin:8px 0 0">Nouveaux clips prêts ·
<a href="" onclick="location.reload();return false">actualiser</a></div>
<nav>{nav}</nav></header>
<div class="wrap{wrap_cls}">
{flash}
{body}
</div>
<script>
// ferme le menu « ⋯ » ouvert quand on clique ailleurs
document.addEventListener('click', ev => {{
  document.querySelectorAll('details.more[open]').forEach(d => {{ if (!d.contains(ev.target)) d.open = false; }});
}});
// copie la légende du clip (fonctionne aussi hors HTTPS, via une sélection)
function copyCaption(btn) {{
  const area = btn.closest('.card').querySelector('textarea');
  const text = area ? area.value : '';
  const label = btn.dataset.label || (btn.dataset.label = btn.textContent);
  const done = () => {{ btn.textContent = '✔ Copiée'; setTimeout(() => btn.textContent = label, 2000); }};
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text).then(done);
  }} else if (area) {{
    area.select(); document.execCommand('copy'); done();
  }}
}}
// met à jour l'état du pilote / de la recherche, et la page Clips quand un clip est prêt.
// Si une légende est en cours d'édition, on affiche un lien au lieu de recharger.
const VERSION = "{version}", AUTORELOAD = {autoreload};
let editing = false;
document.addEventListener('input', e => {{ if (e.target.tagName === 'TEXTAREA') editing = true; }});
setInterval(async () => {{
  try {{
    const s = await (await fetch('/status', {{credentials: 'same-origin'}})).json();
    const pill = document.getElementById('status');
    pill.textContent = s.message; pill.classList.toggle('on', s.active);
    if (AUTORELOAD && s.version !== VERSION) {{
      // ne pas interrompre une légende en cours d'édition ou une vidéo en lecture
      const busy = editing || document.activeElement.tagName === 'TEXTAREA'
                   || [...document.querySelectorAll('video')].some(v => !v.paused);
      if (busy) document.getElementById('fresh').style.display = 'block';
      else location.reload();
    }}
  }} catch (e) {{}}
}}, 5000);
</script>
{progress_ui}
</body></html>"""

PROGRESS_UI = """<style>
  #progress { position:fixed; top:50%; left:50%; transform:translate(-50%,-50%); z-index:20;
              width:min(480px, calc(100vw - 32px)); max-height:calc(100vh - 32px); overflow:auto;
              background:#18181b; border:1px solid #3a3a3d; border-radius:16px; padding:18px;
              box-shadow:0 20px 60px rgba(0,0,0,.6); display:none }
  #progress h3 { margin:0 0 2px; font-size:18px }
  #progress .pclip { color:#adadb8; font-size:13px; margin-bottom:12px; overflow-wrap:anywhere }
  #progress ol { list-style:none; margin:0; padding:0 }
  #progress li { display:flex; gap:10px; padding:7px 0; color:#6b6b73; align-items:flex-start }
  #progress li.st-done { color:#adadb8 }
  #progress li.st-now { color:#efeff1; font-weight:600; background:#26262b; border-radius:8px;
                        margin:2px -8px; padding:8px }
  #progress .ico { width:20px; flex:none; text-align:center }
  #progress .help { font-weight:400; color:#adadb8; font-size:13px; margin-top:2px }
  #progress .spin { display:inline-block; width:14px; height:14px; border:2px solid #9147ff;
                    border-right-color:transparent; border-radius:50%; animation:spin .8s linear infinite }
  @keyframes spin { to { transform:rotate(360deg) } }
  @media (prefers-reduced-motion: reduce) { #progress .spin { animation:none } }
  #progress .pfoot { display:flex; justify-content:space-between; align-items:center; margin-top:12px;
                     color:#adadb8; font-size:13px; gap:8px }
  #progress .pfoot button { flex:0 0 auto; min-height:34px; padding:4px 12px; background:#3a3a3d }
  #progress .pfoot span { flex:1 }
  #progress .pfoot button.stop { background:#8b1d1d }
  #progress .pdone { padding:10px 12px; border-radius:8px; background:#1f3a1f; margin-top:8px }
</style>
<div id="progress" role="status" aria-live="polite"></div>
<script>
// panneau de progression : étapes de la recherche en cours (textContent : données non fiables)
(function () {
  const box = document.getElementById('progress');
  const key = 'cliptv-progress-hidden';
  let hidden = null;
  try { hidden = sessionStorage.getItem(key); } catch (e) {}
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function fmt(s) { return s < 60 ? s + ' s' : Math.floor(s / 60) + ' min ' + String(s % 60).padStart(2, '0') + ' s'; }
  function render(p, steps) {
    const recent = !p.active && p.ended && (Date.now() / 1000 - p.ended) < 12;
    if (!(p.active || recent) || String(p.run) === hidden) { box.style.display = 'none'; return; }
    box.replaceChildren();
    box.append(el('h3', '', p.active ? '🔎 ' + (p.title || 'Recherche en cours') : '✅ Terminé'));
    if (p.active) box.append(el('div', 'pclip', p.clip || 'Préparation…'));
    const ol = el('ol');
    const current = steps.findIndex(s => s[0] === p.step);
    steps.forEach((s, i) => {
      const state = !p.active || i < current ? 'st-done' : i === current ? 'st-now' : '';
      const li = el('li', state);
      const ico = el('span', 'ico');
      if (state === 'st-now') ico.append(el('span', 'spin')); else ico.textContent = state ? '✓' : '○';
      const txt = el('div', '', s[1]);
      const spent = (p.durations || {})[s[0]];
      if (state === 'st-done' && spent) txt.append(el('span', 'help', '  · ' + fmt(spent)));
      if (state === 'st-now') txt.append(el('div', 'help', p.detail ? p.detail + ' — ' + s[2] : s[2]));
      li.append(ico, txt); ol.append(li);
    });
    box.append(ol);
    if (!p.active && p.message) box.append(el('div', 'pdone', p.message));
    const foot = el('div', 'pfoot');
    foot.append(el('span', '', (p.active ? 'En cours depuis ' : 'Durée : ') + fmt(p.elapsed || 0)));
    if (p.active) {
      const stop = el('button', 'stop', p.stopping ? 'Arrêt…' : '⏹ Arrêter');
      stop.type = 'button'; stop.disabled = !!p.stopping;
      stop.onclick = async () => {
        stop.disabled = true; stop.textContent = 'Arrêt…';
        try { await fetch('/stop', {method: 'POST', credentials: 'same-origin'}); } catch (e) {}
      };
      foot.append(stop);
    }
    const btn = el('button', '', p.active ? 'Masquer' : 'Fermer');
    btn.type = 'button';
    btn.onclick = () => { hidden = String(p.run); try { sessionStorage.setItem(key, hidden); } catch (e) {}
                          box.style.display = 'none'; };
    foot.append(btn); box.append(foot);
    box.style.display = 'block';
  }
  async function poll() {
    let delay = 5000;
    try {
      const s = await (await fetch('/status', {credentials: 'same-origin'})).json();
      if (s.progress) { render(s.progress, s.steps || []); if (s.progress.active) delay = 1500; }
    } catch (e) {}
    setTimeout(poll, delay);
  }
  poll();
})();
</script>"""


FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<rect width="100" height="100" rx="22" fill="#9147ff"/><path d="M38 28 L74 50 L38 72 Z" fill="#fff"/></svg>"""

SECTIONS = [("/", "Clips"), ("/auto", "Pilote auto"), ("/stats", "Statistiques"),
            ("/accounts", "Comptes"), ("/help", "Aide")]
STUDIO = "studio"  # onglet « TikTok Studio » : clips prêts, à publier soi-même
TABS = [("rendered", "À valider"), ("scheduled", "Programmés"), ("publishing", "Envoi en cours"),
        ("published", "Publiés"), ("rejected", "Rejetés"), ("failed", "Erreurs")]
CLIP_ACTIONS = ("publish", "schedule", "reject", "unschedule", "done", "redo", "restore")
HOURS = [(6, "6 dernières heures"), (24, "24 dernières heures"), (72, "3 derniers jours"),
         (168, "7 derniers jours")]
EVERY = [(15, "toutes les 15 min"), (30, "toutes les 30 min"), (60, "toutes les heures"),
         (120, "toutes les 2 h"), (240, "toutes les 4 h"), (720, "toutes les 12 h")]
LANGUAGES = [("fr", "Français"), ("en", "Anglais"), ("es", "Espagnol"), ("de", "Allemand"),
             ("it", "Italien"), ("pt", "Portugais"), ("", "Toutes les langues")]
SOURCES = [("discover", "Auto : streams les plus regardés"),
           ("channels", "Seulement mes chaînes")]
LAYOUTS_REDO = [("auto", "Cadrage auto"), ("crop", "Zoom plein écran"),
                ("split", "Facecam en haut / jeu en bas"), ("blur", "Fond flouté")]
LAYOUTS = [("auto", "Auto : facecam en haut si détectée, sinon zoom"),
           ("crop", "Zoom plein écran"), ("blur", "Vidéo entière sur fond flouté")]
RATIOS = [(2.0, "Très sensible (x2)"), (3.0, "Normale (x3)"), (5.0, "Peu sensible (x5)")]
PLATFORM_NAMES = {"tiktok": "TikTok", "youtube": "YouTube Shorts", "instagram": "Instagram Reels",
                  "manuel": "Publié à la main"}
CHANNEL_RE = re.compile(r"\w{2,25}")

CARD = """<div class="card">
  {player}
  <div><strong>{title}</strong></div>
  <div class="meta">{channel} · {views} vues · <a href="{url}" target="_blank" rel="noopener">clip Twitch</a>{error}</div>
  {badges}
  {actions}
</div>"""

# une seule rangée d'actions par clip ; le reste dans le menu « ⋯ » (un seul formulaire :
# chaque bouton envoie la légende éditée vers sa propre action via formaction)
ACTIONS = """<form method="post" action="/schedule/{id}" class="act">
  <textarea name="caption" rows="3" aria-label="Légende">{caption}</textarea>
  <div class="bar">
    <button type="submit" title="Sur le prochain créneau libre">⏰ Programmer</button>
    <button class="now" type="submit" formaction="/publish/{id}">🚀 {now_label}</button>
    {menu}
  </div>
</form>"""

# mode « je publie moi-même » (TikTok Studio) : télécharger, copier, marquer publié
MANUAL_ACTIONS = """<form method="post" action="/done/{id}" class="act">
  <input type="hidden" name="back" value="studio">
  <textarea name="caption" rows="4" aria-label="Description">{caption}</textarea>
  <div class="bar">
    <a class="btn" href="{download}" download title="Enregistre la vidéo sur ton PC">⬇ Vidéo</a>
    <button type="button" onclick="copyCaption(this)" title="Copie la description (modifiable ci-dessus)">📋 Description</button>
    <button class="now" type="submit" title="À cliquer une fois publié sur TikTok">✔ Publié</button>
    {menu}
  </div>
</form>"""

MANUAL_MENU = """<details class="more"><summary class="iconbtn" title="Plus d'actions" aria-label="Plus d'actions">⋯</summary>
  <div class="menu">
    <a href="https://www.tiktok.com/tiktokstudio/upload" target="_blank" rel="noopener">↗ Ouvrir TikTok Studio</a>
    <div class="redo">
      <span>🎬 Refaire le montage</span>
      <select name="layout" aria-label="Cadrage">{layouts}</select>
      <label class="check"><input type="checkbox" name="subtitles" value="1"{subs_checked}> Sous-titres</label>
      <button type="submit" formaction="/redo/{id}">Refaire</button>
    </div>
    {reject}
  </div>
</details>"""

SCHEDULED = """<div class="when">⏰ {when}</div>
<form method="post" action="/publish/{id}" class="act">
  <textarea name="caption" rows="3" aria-label="Légende">{caption}</textarea>
  <div class="bar">
    <button class="now" type="submit">🚀 Publier maintenant</button>
    <button class="rej" type="submit" formaction="/unschedule/{id}">↩ Annuler</button>
    {menu}
  </div>
</form>"""

MENU = """<details class="more"><summary class="iconbtn" title="Plus d'actions" aria-label="Plus d'actions">⋯</summary>
  <div class="menu">
    <a href="{download}" download>⬇ Télécharger la vidéo</a>
    <button type="button" onclick="copyCaption(this)">📋 Copier la légende</button>
    <button type="submit" formaction="/done/{id}" title="Tu l'as publié toi-même depuis TikTok">✔ Marquer comme publié</button>
    <div class="redo">
      <span>🎬 Refaire le montage</span>
      <select name="layout" aria-label="Cadrage">{layouts}</select>
      <label class="check"><input type="checkbox" name="subtitles" value="1"{subs_checked}> Sous-titres</label>
      <button type="submit" formaction="/redo/{id}">Refaire</button>
    </div>
    {reject}
  </div>
</details>"""

SEARCH = """<details class="panel">
<summary>🔎 Recherche ponctuelle</summary>
<form method="post" action="/search">
  <div class="grid">
    <label class="full">Chaînes Twitch (laisse vide pour trouver seul les temps forts du moment)
      <input name="channels" value="{channels}" placeholder="vide = découverte automatique"
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


def extract_oauth_code(raw: str) -> str:
    """Code d'autorisation depuis l'adresse de retour collée, ou depuis le code seul.

    Décodé une seule fois avec ``unquote`` (et non ``unquote_plus``) : les codes TikTok
    contiennent des caractères encodés (%2A…) et parfois des « + » à garder tels quels.
    """
    raw = raw.strip().strip('"\'')
    match = re.search(r"[?&#]code=([^&#\s]+)", raw)
    value = match.group(1) if match else raw.removeprefix("code=")
    return urllib.parse.unquote(value)


def _tiktok_error(exc: BaseException) -> str:
    """Échec de connexion TikTok : explication + action."""
    from .errors import explain

    return f"Connexion TikTok impossible : {explain(exc)}"


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
            from .errors import explain

            self.message = f"Recherche impossible : {explain(exc)}"
        finally:
            self.running = False


def run_search(job: SearchJob, cfg: Config, state: State, opts: Options, channels: list[str],
               hours: float, top: int) -> str:
    from . import progress
    from .twitch import TwitchClient

    cfg.require("twitch_client_id", "twitch_client_secret")
    cfg.ensure_dirs()
    twitch = TwitchClient(cfg.twitch_client_id, cfg.twitch_client_secret)
    progress.begin("Recherche ponctuelle")
    try:
        message = _run_search(job, cfg, state, opts, channels, hours, top, twitch)
    except progress.Cancelled:
        message = "Recherche arrêtée (les clips déjà prêts sont conservés)"
    except BaseException as exc:
        progress.end(f"Échec : {exc}")
        raise
    progress.end(message)
    return message


def _run_search(job, cfg, state, opts, channels, hours, top, twitch) -> str:
    from .pipeline import run_channels

    started = time.time()
    results: list[tuple[str, bool]] = []
    if not channels:  # découverte automatique des temps forts
        from .autopilot import load_settings
        from .discover import run_discovery

        lang = load_settings(state, cfg).get("language") or None
        results = run_discovery(cfg, state, opts, twitch, language=lang, hours=hours, top=top,
                                min_views=0)
    for i, channel in enumerate(channels, 1):
        job.message = f"Recherche en cours : {channel} ({i}/{len(channels)})…"
        results += run_channels([channel], cfg, state, opts, twitch, hours=hours, top=top,
                                min_views=0)
    ok = sum(r[1] for r in results)
    ko = len(results) - ok
    if not results:
        return f"Aucun nouveau clip trouvé ({', '.join(channels) or 'découverte auto'})"
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


def publish_in_background(app, clip_id: str) -> None:
    with app.publish_lock:  # une publication à la fois
        try:
            publish_clip(clip_id, app.cfg, app.state, app.opts)
        except Exception as exc:  # ne jamais laisser un clip bloqué « en cours »
            log.exception("Publication échouée pour %s", clip_id)
            clip = app.state.get(clip_id)
            from .errors import explain

            app.state.record(clip_id, clip["channel"], "failed", error=explain(exc))


def redo_clip(app, clip: dict, src: Path, opts: Options) -> None:
    from .pipeline import _render_lock, render_video

    try:
        with _render_lock:
            from .twitch import is_non_gaming

            info: dict = {}
            render_video(src, Path(clip["output_path"]), app.cfg, opts,
                         allow_split=not is_non_gaming(clip.get("category") or ""),
                         title=clip.get("title") or "", info=info)
            import json

            try:  # garde les indices Twitch, met à jour ceux du montage
                old = json.loads(clip.get("signals") or "{}")
            except ValueError:
                old = {}
            app.state.set_signals(clip["clip_id"], json.dumps({**old, **info}))
        error = None
    except Exception as exc:
        log.exception("Remontage échoué pour %s", clip["clip_id"])
        from .errors import explain

        error = f"Remontage impossible : {explain(exc)}"
    finally:
        app.redoing.discard(clip["clip_id"])
    # même statut (et même créneau) ; met à jour la date -> la page se rafraîchit
    app.state.record(clip["clip_id"], clip["channel"], clip["status"], error=error,
                     scheduled_at=clip.get("scheduled_at"))


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
    auth_ok: set = field(default_factory=set)  # en-têtes déjà vérifiés (hash lent)
    redoing: set = field(default_factory=set)  # clips en cours de remontage
    audio_cache: dict = field(default_factory=dict)  # (chemin, date) -> a du son ?


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

    def _is_local(self) -> bool:
        """Requête faite sur ce PC même ? Un tunnel ou un proxy (Cloudflare, Tailscale,
        ngrok, Caddy…) se connecte lui aussi depuis 127.0.0.1 : on le reconnaît à ses
        en-têtes de relais et on le traite comme un accès extérieur."""
        ip = self.client_address[0]
        if not (ip.startswith("127.") or ip == "::1"):
            return False
        relayed = ("X-Forwarded-For", "X-Real-IP", "Forwarded", "CF-Connecting-IP",
                   "True-Client-IP", "X-Forwarded-Host", "Tailscale-User-Login",
                   "Tailscale-Funnel-Request", "Ngrok-Trace-Id")
        return not any(h in self.headers for h in relayed)

    def _authorized(self) -> bool:
        """Sans mot de passe : seul ce PC a accès. Avec : tout appareil qui le connaît."""
        from .localkeys import PASSWORD_SETTING, check_password

        env_pw = self.cfg.review_password
        pw_hash = self.state.get_settings().get(PASSWORD_SETTING)
        if not env_pw and not pw_hash:
            if self._is_local():
                return True
            port = self.server.server_address[1]
            self._send(403, "Accès depuis un autre appareil refusé : ouvre cliptv sur le PC "
                            f"qui le fait tourner (http://localhost:{port}), page Comptes, et "
                            "choisis un mot de passe d'accès. (Avec Docker : définis "
                            "CLIPBOT_REVIEW_PASSWORD dans le fichier .env.)")
            return False
        header = self.headers.get("Authorization", "")
        if header in self.app.auth_ok:
            return True
        try:
            _, _, given = base64.b64decode(header.removeprefix("Basic ").strip()) \
                .decode().partition(":")
        except ValueError:
            given = None
        if given is not None and (
                (env_pw and hmac.compare_digest(given.encode(), env_pw.encode()))
                or (pw_hash and check_password(pw_hash, given))):
            self.app.auth_ok.add(header)
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
            progress_ui=PROGRESS_UI, version=e(self.state.version()), autoreload="true" if section == "/" else "false",
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
        if url.path.startswith("/tiktok/post/"):
            return self._tiktok_post_page(urllib.parse.unquote(url.path.removeprefix("/tiktok/post/")))
        routes = {
            "/": self._clips_page,
            "/auto": self._auto_page,
            "/accounts": self._accounts_page,
            "/stats": self._stats_page,
            "/help": self._help_page,
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
        from . import progress

        self._send(200, json.dumps({"running": self.app.job.running, "active": active,
                                    "message": message, "version": self.state.version(),
                                    "progress": progress.snapshot(), "steps": progress.STEPS},
                                   ensure_ascii=False),
                   "application/json; charset=utf-8")

    # ---------- page Clips ----------
    def _clips_page(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        tab = q.get("s", ["rendered"])[0]
        self._start_backfill()
        counts = {s: self.state.count(s) for s, _ in TABS}
        counts[STUDIO] = counts["rendered"]
        manual = tab == STUDIO  # onglet « TikTok Studio » : publier soi-même
        tabs = "".join(
            f'<a class="{"on" if s == tab else ""}" href="/?s={s}">{label} ({counts[s]})</a>'
            for s, label in TABS + [(STUDIO, "✋ TikTok Studio")])
        cards = "".join(self._card(c, manual=manual)
                        for c in self.state.list("rendered" if manual else tab)) or \
            '<p class="empty">Rien ici pour le moment.</p>'
        info = e(f"Publication : {', '.join(PLATFORM_NAMES.get(p, p) for p in self.platforms)}"
                 f" · créneaux {', '.join(self.cfg.post_slots)} ({self.cfg.timezone})")
        if manual:
            from . import stats as _stats

            checked = bool(self.state.get_settings().get(_stats.ENABLED))
            info = ('✋ Les clips prêts, à publier toi-même : <strong>⬇ Vidéo</strong> → <strong>📋 Description'
                    '</strong> → <a href="https://www.tiktok.com/tiktokstudio/upload" '
                    'target="_blank" rel="noopener">TikTok Studio ↗</a> (glisse la vidéo, colle '
                    'la description, publie) → <strong>✔ Publié</strong>')
            if checked:  # liste des vidéos du compte rafraîchie en fond (15 min max)
                threading.Thread(target=_stats.refresh_before_search,
                                 args=(self.cfg, self.state), daemon=True).start()
            else:
                info += ('<br>⚠️ Impossible de vérifier si un clip est déjà sur ton TikTok : '
                         'active les statistiques (onglet <a href="/stats">Statistiques</a>).')
        body = (f'<nav class="sub">{tabs}</nav>{self._search_panel()}'
                f'<p class="info">{info}</p><main>{cards}</main>')
        self._page(body, "/")

    def _search_panel(self) -> str:
        from .autopilot import load_settings

        s = load_settings(self.state, self.cfg)
        channels = ", ".join(s["channels"]) if s.get("source") == "channels" else ""
        return SEARCH.format(channels=e(channels), hours=_options(HOURS, 24),
                             disabled=" disabled" if self.app.job.running else "")

    def _tiktok_mode(self) -> str:
        from .pipeline import tiktok_mode

        return tiktok_mode(self.state, self.opts)

    def _set_tiktok_mode(self, form: dict[str, str]):
        from .pipeline import TIKTOK_MODE

        mode = form.get("mode")
        if mode not in ("draft", "direct"):
            return self._redirect("Choix inconnu.", err=True, to="/accounts")
        if mode == self._tiktok_mode():
            return self._redirect("Aucun changement.", to="/accounts")
        self.state.save_settings({TIKTOK_MODE: mode})
        if mode == "direct":
            msg = ("Les vidéos seront publiées directement sur ton profil, avec les réglages que tu "
                   "choisis pour chaque clip. Sur developers.tiktok.com, active « Direct Post » "
                   "(scope video.publish), puis reconnecte TikTok. Tant que ton app n'est pas "
                   "validée par TikTok, seuls « Moi uniquement » et un compte privé fonctionnent.")
        else:
            msg = "Les vidéos arriveront en brouillon dans l'app TikTok de ton téléphone."
        return self._redirect(msg, to="/accounts")

    def _settings(self) -> dict:
        from .autopilot import load_settings

        return load_settings(self.state, self.cfg)

    def _has_audio(self, path: str) -> bool:
        from .download import has_audio

        p = Path(path)
        if not p.exists():
            return True  # rien à signaler : la vidéo manque, pas le son
        key = (path, p.stat().st_mtime)
        if key not in self.app.audio_cache:
            self.app.audio_cache[key] = has_audio(p)
        return self.app.audio_cache[key]

    def _card(self, c: dict, manual: bool = False) -> str:
        """``manual`` : boutons de l'onglet TikTok Studio (télécharger, copier, publié)."""
        cid, status = e(c["clip_id"]), c["status"]
        base = f'/video/{urllib.parse.quote(c["clip_id"], safe="")}'
        video = e(f"{base}?v={c['updated_at']}")  # nouvelle URL après un remontage (cache)
        menu = ""
        if status in ("rendered", "scheduled") or (status == "failed" and c.get("output_path")):
            settings = self._settings()
            reject = ('<button type="submit" class="danger" formaction="/reject/{id}">'
                      '🗑 Rejeter</button>'.format(id=cid) if status != "scheduled" else "")
            menu = MENU.format(download=e(f"{base}?dl=1"), id=cid, reject=reject,
                               layouts=_options(LAYOUTS_REDO, settings.get("layout", "auto")),
                               subs_checked=" checked" if settings.get("subtitles", True) else "")
        if manual and (status in ("rendered", "scheduled")
                       or (status == "failed" and c.get("output_path"))):
            settings = self._settings()
            reject = ('<button type="submit" class="danger" formaction="/reject/{id}">'
                      '🗑 Rejeter</button>'.format(id=cid))
            menu = MANUAL_MENU.format(id=cid, reject=reject,
                                      layouts=_options(LAYOUTS_REDO, settings.get("layout", "auto")),
                                      subs_checked=" checked" if settings.get("subtitles", True) else "")
            actions = MANUAL_ACTIONS.format(id=cid, caption=e(c["caption"]), menu=menu,
                                            download=e(f"{base}?dl=1"))
        elif status == "rendered" or (status == "failed" and c.get("output_path")):
            label = "Réessayer" if status == "failed" else "Publier"
            actions = ACTIONS.format(id=cid, caption=e(c["caption"]), now_label=label, menu=menu)
        elif status == "publishing":
            actions = ('<div class="when">⏳ Envoi vers TikTok en cours…</div>'
                       f'<div class="meta">{e(c["caption"])}</div>')
        elif status == "scheduled":
            actions = SCHEDULED.format(id=cid, caption=e(c["caption"]), menu=menu,
                                       when=e(format_when(c["scheduled_at"], self.cfg.timezone)))
        else:
            actions = f'<div class="meta">{e(c["caption"])}</div>'
            if status == "rejected":
                actions += (f'<form method="post" action="/restore/{cid}" class="act">'
                            '<button type="submit" class="small">↩ Remettre dans « À valider »'
                            '</button></form>')
            tiktok = self.state.posts(c["clip_id"]).get("tiktok", {})
            if status == "published":  # légende prête à coller dans TikTok
                actions = (f'<textarea readonly rows="3" aria-label="Légende">{e(c["caption"] or "")}'
                           '</textarea><button type="button" class="small" '
                           'onclick="copyCaption(this)">📋 Copier la légende</button>')
            if status == "published" and tiktok.get("status") == "ok" \
                    and self._tiktok_mode() == "draft":
                actions += ('<div class="meta">📥 Envoyé dans ta <strong>boîte de réception '
                            'TikTok</strong>. TikTok ne reprend pas la légende des brouillons : '
                            'ouvre cette page sur ton téléphone, copie la légende, puis colle-la '
                            'dans TikTok avant de publier.</div>')
            elif status == "published" and tiktok.get("status") == "ok":
                actions += ('<div class="meta">✅ Publié sur ton profil TikTok avec la visibilité '
                            'choisie (TikTok peut mettre quelques minutes à l\'afficher).</div>')
        if c["clip_id"] in self.app.redoing:
            player = ('<div class="when" style="padding:40px 0;text-align:center">'
                      '⏳ Remontage en cours…</div>')
        else:
            player = f'<video src="{video}" controls preload="metadata" playsinline></video>'
            if c.get("output_path") and not self._has_audio(c["output_path"]):
                player += '<div class="badges"><span class="badge failed">🔇 vidéo sans son</span></div>'
        posts = self.state.posts(c["clip_id"])
        badges = "".join(
            f'<span class="badge {e(p["status"])}" title="{e(p.get("error") or p.get("post_id"))}">'
            f'{e(PLATFORM_NAMES.get(name, name))} {"✔" if p["status"] == "ok" else "✖"}</span>'
            for name, p in posts.items())
        if status in ("rendered", "scheduled", "failed") and self._on_tiktok(c):
            badges += ('<span class="badge failed" title="Une vidéo de ton compte TikTok a le '
                       'même titre ou les mêmes mots-clés et le même streamer">⚠️ Déjà sur ton '
                       'TikTok</span>')
        if c.get("signals") and status in ("rendered", "scheduled", "failed"):
            badges += self._potential_badge(c)
        badges = f'<div class="badges">{badges}</div>' if badges else ""
        error = f" · ⚠️ {e(c['error'])}" if c.get("error") else ""
        return CARD.format(player=player,
                           title=e(c["title"]), channel=e(c["channel"]),
                           views=e(c["view_count"]), url=e(c["url"]), error=error,
                           badges=badges, actions=actions)

    def _on_tiktok(self, c: dict) -> bool:
        """Ce clip est-il déjà sur le compte TikTok ? (liste des vidéos des statistiques)"""
        from types import SimpleNamespace

        from . import stats

        if not hasattr(self, "_tiktok_check"):  # une seule lecture par page
            self._tiktok_check = stats.on_tiktok(self.state)
        clip = SimpleNamespace(id=c["clip_id"], title=c.get("title") or "",
                               broadcaster_name=c.get("channel") or "")
        return self._tiktok_check(clip)

    def _start_backfill(self) -> None:
        """Indicateur de potentiel pour les clips préparés avant cette fonction (une fois)."""
        if getattr(self.app, "backfill_started", False):
            return
        self.app.backfill_started = True
        from . import potential

        def run():
            try:
                n = potential.backfill(self.cfg, self.state)
                if n:
                    log.info("Potentiel calculé pour %d clip(s) déjà prêts", n)
            except Exception:
                log.exception("Calcul du potentiel des anciens clips impossible")
        threading.Thread(target=run, daemon=True).start()

    def _potential_badge(self, c: dict) -> str:
        """Indicateur « potentiel de vues » (détail au clic : raisons du score)."""
        from . import potential

        if not hasattr(self, "_pot_hist"):  # une seule lecture des stats par page
            self._pot_hist = potential.history(self.state)
        p = potential.score(c, self._pot_hist)
        reasons = "".join(f"<li>{e(r)}</li>" for r in p["reasons"])
        return (f'<details class="pot r-{p["rarity"]}"><summary title="Potentiel de vues '
                f'(estimation, pas une garantie) : clique pour le détail">'
                f'<span class="note">{p["note"]:.1f}</span><span class="max">/10</span>'
                f'<span class="rar">{e(p["rarity_label"])}</span></summary>'
                f'<ul>{reasons}</ul></details>')

    # ---------- page Aide ----------
    def _help_page(self):
        from . import help_page

        cfg, settings = self.cfg, self._settings()
        status = {
            "twitch": bool(cfg.twitch_client_id and cfg.twitch_client_secret),
            "tiktok_keys": bool(cfg.tiktok_client_key and cfg.tiktok_client_secret
                                and cfg.tiktok_redirect_uri),
            "tiktok_connected": cfg.tiktok_token_path.exists(),
            "claude": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "autopilot": bool(settings.get("enabled")),
        }
        from .captions import last_error
        if status["claude"] and last_error:  # clé présente mais Claude refuse
            status["claude"], status["claude_error"] = False, last_error
        self._page(help_page.render(status), "/help", narrow=True)

    # ---------- page Statistiques ----------
    def _stats_page(self):
        from . import stats, stats_page

        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        try:
            days = int(q.get("p", ["30"])[0])
        except ValueError:
            days = 30
        sort = q.get("sort", ["views"])[0]
        since = time.time() - days * 86400 if days else 0
        summary = stats.summary(self.state, since=since, tz=self.cfg.timezone)
        summary["slots"] = list(self.cfg.post_slots)
        self._page(stats_page.render(summary, days=days, sort=sort, tz=self.cfg.timezone),
                   "/stats")

    def _stop(self):
        from . import progress

        if progress.cancel():
            return self._send(200, json.dumps({"ok": True}), "application/json")
        return self._send(409, json.dumps({"ok": False}), "application/json")

    def _stats_refresh(self):
        from . import stats

        if not self.cfg.tiktok_token_path.exists():
            return self._redirect("TikTok n'est pas connecté → page Comptes → Connecter TikTok.", err=True,
                                  to="/stats")
        msg = stats.refresh(self.cfg, self.state)
        err = bool(self.state.get_settings().get(stats.ERROR))
        return self._redirect(msg, err=err, to="/stats")

    def _stats_enable(self):
        from . import stats

        self.state.save_settings({stats.ENABLED: True, stats.ERROR: None})
        return self._redirect("Statistiques activées : reconnecte maintenant TikTok (bouton "
                              "« Reconnecter ») pour accorder les nouvelles autorisations.",
                              to="/accounts")

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
        from .audience import heatmap

        audience = heatmap(s["post_slots"], self.state.videos(0), self.cfg.timezone,
                           apply_button=True)
        then = _options([("schedule", "Programmer sur les créneaux"),
                         ("publish", "Publier dès que c'est prêt"),
                         ("manual", "Le garder : je publie moi-même")], s["then"])
        body = f"""
<div class="panel"><h2>{head}</h2>
<p class="info">Il repère tout seul les temps forts des streams les plus regardés (les
clips que les viewers partagent le plus en ce moment), les monte en vertical avec sous-titres,
écrit la légende, puis les publie aux heures choisies. Il surveille aussi les lives et
clippe chaque moment fort du chat. Tu n'as rien à faire : tu peux juste suivre
(ou annuler un clip) dans l'onglet Clips.</p>
{status}<div style="margin-top:12px">{toggle}</div></div>

{audience}
<form method="post" action="/auto" class="panel"><h2>Réglages</h2>
<div class="grid">
  <label class="full">Où chercher les clips <select name="source">{_options(SOURCES, s.get('source', 'discover'))}</select></label>
  <label>Langue des streams <select name="language">{_options(LANGUAGES, s.get('language', 'fr'))}</select></label>
  <label>Streams scannés (mode auto) <input name="streamers" type="number" min="5" max="100" value="{e(s.get('streamers', 30))}"></label>
  <label class="full">Chaînes favorites (toujours incluses ; obligatoires en mode « mes chaînes »)
    <input name="channels" value="{e(', '.join(s['channels']))}" placeholder="kamet0, zerator"
           autocapitalize="none" autocorrect="off"></label>
  <label class="full">Lives à surveiller (clip automatique à chaque pic de chat)
    <input name="live_channels" value="{e(', '.join(s['live_channels']))}" placeholder="kamet0"
           autocapitalize="none" autocorrect="off"></label>
  <label>Fréquence de recherche <select name="every">{_options(EVERY, int(s['every']))}</select></label>
  <label>Clips récents de moins de <select name="hours">{_options(HOURS, int(s['hours']))}</select></label>
  <label>Clips max par recherche <input name="top" type="number" min="1" max="20" value="{e(s['top'])}"></label>
  <label>Vues minimum <input name="min_views" type="number" min="0" value="{e(s['min_views'])}"></label>
  <label>Quand un clip est prêt <select name="then">{then}</select></label>
  <label class="full">Cadrage des vidéos <select name="layout">{_options(LAYOUTS, s.get('layout', 'auto'))}</select></label>
  <label>Sensibilité des lives <select name="ratio">{_options(RATIOS, float(s['ratio']))}</select></label>
  <label class="full">Heures de publication (heure de {e(self.cfg.timezone)})
    <input name="post_slots" value="{e(', '.join(s['post_slots']))}" placeholder="12:30, 18:00, 21:00"></label>
  <label>Clips programmés max (0 = auto) <input name="max_queue" type="number" min="0" value="{e(s['max_queue'])}"></label>
  <div class="full"><div class="info">Publier sur</div><div class="row">{checks}</div></div>
  <label class="check full"><input type="checkbox" name="subtitles" value="1"{" checked" if s.get("subtitles", True) else ""}>
    Ajouter des sous-titres animés (décoche si tes streamers ont déjà les leurs)</label>
  <label class="check full"><input type="checkbox" name="ai_caption" value="1"{" checked" if s["ai_caption"] else ""}>
    Légendes et hashtags écrits par Claude</label>
</div>
<div class="row" style="margin-top:14px"><button type="submit">Enregistrer</button></div>
</form>"""
        self._page(body, "/auto", narrow=True)

    # ---------- page Comptes ----------
    def _accounts_page(self):
        from .autopilot import load_settings

        cfg = self.cfg
        rows = []
        manual = load_settings(self.state, cfg).get("then") == "manual"

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
            "Renseigne le Client ID et le secret Twitch dans « Clés API » ci-dessous")
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
                    detail = "Renseigne la Client key et le secret TikTok dans « Clés API » ci-dessous"
                action = (f'<a class="btn small" href="/connect/tiktok" target="_blank" rel="noopener">'
                          f'{"Reconnecter" if ok else "Connecter"}</a>') if keys else ""
                paste = (
                    '<form method="post" action="/connect/tiktok-code" class="row" '
                    'style="margin-top:8px"><input name="code" required '
                    'placeholder="https://…/callback?code=…" autocomplete="off">'
                    '<button class="small">Valider</button></form>')
                if keys and not ok:
                    detail += ("<br>Si la page de retour ne s'ouvre pas (app lancée sur un PC), "
                               "copie son adresse complète et colle-la ici :" + paste)
                elif keys:  # reconnexion : même étape de copier-coller qu'à la 1re connexion
                    detail += ("<br>Pour reconnecter : clique sur « Reconnecter », accepte sur "
                               "TikTok, puis copie l'adresse complète de la page de retour "
                               "(ou clique « Terminer la connexion dans ClipTV ») et colle-la ici :" + paste)
                if keys:
                    mode = self._tiktok_mode()
                    choices = "".join(
                        f'<option value="{v}"{" selected" if v == mode else ""}>{lab}</option>'
                        for v, lab in (("draft", "📥 en brouillon dans l'app TikTok du téléphone"),
                                       ("direct", "🚀 publiées directement sur ton profil (tu choisis la visibilité)")))
                    detail += ("<br>⚠️ Tant que TikTok n'a pas validé ton app, les vidéos "
                               "n'arrivent que si ton compte TikTok est <strong>privé</strong>.")
                    detail += ('<form method="post" action="/tiktok/mode" class="row" '
                               'style="margin-top:8px">Les vidéos arrivent '
                               f'<select name="mode">{choices}</select>'
                               '<button class="small">OK</button></form>')
                stats_on = bool(self._settings().get("tiktok_stats"))
                if manual and not ok and not stats_on:  # pas de connexion nécessaire
                    detail = ("Pas nécessaire en mode « je publie moi-même » : télécharge "
                              "chaque clip depuis l'onglet Clips. (La publication "
                              "automatique demande le produit Content Posting API avec le "
                              "scope video.upload dans ton app TikTok.)")
                    action = ""
                row("TikTok", "✅" if ok else "—", detail, action, dest)
            elif platform == "youtube":
                keys = bool(cfg.youtube_client_id and cfg.youtube_client_secret)
                ok = cfg.youtube_token_path.exists()
                detail = pending_html("youtube", "YouTube") or (
                    f"Chaîne connectée (vidéos en « {e(cfg.youtube_privacy)} »)" if ok else
                    "Renseigne les clés YouTube dans « Clés API » ci-dessous" if not keys
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

        claude = bool(os.environ.get("ANTHROPIC_API_KEY"))  # .env ou Clés API
        row("Claude (légendes)", "✅" if claude else "—",
            "Clé configurée" if claude else
            "Renseigne la clé dans « Clés API » ci-dessous (sinon légende standard)")

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
{self._keys_panel()}
{self._access_panel()}
<div class="panel"><h2>Diagnostic</h2>
<p class="info">Teste ffmpeg, la police, et chaque connexion avec un vrai appel aux API.</p>
{checks}
<form method="post" action="/accounts/check" class="row" style="margin-top:12px">
<button>Tout vérifier</button></form></div>"""
        waiting = any(p.state == "pending" for p in self.app.pending.values())
        self._page(body, "/accounts", narrow=True, refresh=5 if waiting else 0)

    def _keys_panel(self) -> str:
        from .localkeys import KEYS, current_value

        fields = []
        for env, attr, label, secret in KEYS:
            if env.startswith("YOUTUBE") and "youtube" not in self.platforms:
                continue
            value = current_value(self.cfg, env, attr)
            if secret:
                hint = "••••••• enregistrée (laisse vide pour garder)" if value else ""
                fields.append(f'<label>{e(label)}<input type="password" name="{env}" '
                              f'placeholder="{hint}" autocomplete="off"></label>')
            else:
                fields.append(f'<label>{e(label)}<input name="{env}" value="{e(value)}" '
                              f'autocomplete="off" autocapitalize="none"></label>')
        return f"""<details class="panel"{" open" if not self.cfg.twitch_client_id else ""}>
<summary>🔑 Clés API</summary>
<p class="info">À créer une fois sur dev.twitch.tv, developers.tiktok.com et
console.anthropic.com (voir le README). Elles sont gardées sur ce PC uniquement.</p>
<form method="post" action="/keys"><div class="grid">{''.join(fields)}</div>
<div class="row" style="margin-top:12px"><button>Enregistrer les clés</button></div></form>
</details>"""

    def _access_panel(self) -> str:
        from .localkeys import PASSWORD_SETTING, lan_address

        has_pw = bool(self.cfg.review_password
                      or self.state.get_settings().get(PASSWORD_SETTING))
        host, port = self.server.server_address[:2]
        ip = lan_address() if host in ("0.0.0.0", "") else None
        if not has_pw:
            where = ("Pour l'ouvrir depuis un autre PC ou ton téléphone (même Wi-Fi), "
                     "choisis d'abord un mot de passe.")
        elif ip:
            url = f"http://{ip}:{port}"
            where = (f'Depuis un autre PC ou ton téléphone sur le même Wi-Fi, ouvre '
                     f'<a href="{e(url)}">{e(url)}</a> (n\'importe quel nom d\'utilisateur '
                     f'+ ce mot de passe).')
        else:
            where = "Mot de passe actif."
        return f"""<div class="panel"><h2>Accès depuis d'autres appareils</h2>
<p class="info">{where}</p>
<p class="info">⚠️ Si tu installes cliptv sur plusieurs PC avec le <strong>même compte
TikTok</strong>, n'active le pilote automatique que sur un seul, sinon les mêmes clips
seront publiés en double. Les autres PC peuvent simplement ouvrir son adresse.</p>
<form method="post" action="/password" class="row">
<input type="password" name="password" minlength="6" required autocomplete="new-password"
       placeholder="{'nouveau mot de passe' if has_pw else 'choisis un mot de passe (6 caractères min.)'}">
<button class="small">{'Changer' if has_pw else 'Définir'}</button></form></div>"""

    @staticmethod
    def _button(action: str, label: str, disabled: bool = False) -> str:
        return (f'<form method="post" action="{action}"><button class="small"'
                f'{" disabled" if disabled else ""}>{label}</button></form>')

    def _tiktok_redirect(self):
        from .tiktok import authorize_url

        cfg = self.cfg
        if not (cfg.tiktok_client_key and cfg.tiktok_redirect_uri):
            return self._redirect("Il manque la Client key ou la Redirect URI TikTok → ajoute-les dans « Clés API » ci-dessous.",
                                  err=True, to="/accounts")
        self.send_response(302)
        from .tiktok import PKCE_SETTING, new_pkce

        verifier, challenge = new_pkce()  # gardé pour l'échange du code
        self.state.save_settings({PKCE_SETTING: verifier})
        self.send_header("Location", authorize_url(cfg.tiktok_client_key,
                                                   cfg.tiktok_redirect_uri,
                                                   state=self.app.oauth_state,
                                                   direct=self._tiktok_mode() == "direct",
                                                   code_challenge=challenge,
                                                   stats=bool(self._settings().get(
                                                       "tiktok_stats"))))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _pkce_verifier(self) -> str | None:
        from .tiktok import PKCE_SETTING

        return self.state.get_settings().get(PKCE_SETTING)

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
            client.exchange_code(extract_oauth_code(self.path), cfg.tiktok_redirect_uri,
                                 self._pkce_verifier())
        except Exception as exc:
            return self._redirect(_tiktok_error(exc), err=True, to="/accounts")
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
        if "dl=1" in urllib.parse.urlparse(self.path).query:  # bouton « Télécharger »
            import re as _re
            import unicodedata as _ud

            slug = _ud.normalize("NFKD", f"{clip['channel']} {clip.get('title') or ''}")
            slug = _re.sub(r"[^A-Za-z0-9]+", "-", slug.encode("ascii", "ignore").decode())
            name = (slug.strip("-")[:60] or path.stem) + ".mp4"
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
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
            "/auto/slots": lambda: self._apply_slots(one),
            "/accounts/check": self._run_checks,
            "/stats/refresh": self._stats_refresh,
            "/stop": self._stop,
            "/stats/enable": self._stats_enable,
            "/tiktok/mode": lambda: self._set_tiktok_mode(one),
            "/connect/twitch": lambda: self._connect_device("twitch"),
            "/connect/youtube": lambda: self._connect_device("youtube"),
            "/connect/instagram": lambda: self._connect_instagram(one),
            "/connect/tiktok-code": lambda: self._tiktok_code(one),
            "/keys": lambda: self._save_keys(one),
            "/password": lambda: self._save_password(one),
        }
        if path in routes:
            return routes[path]()
        if path.startswith("/tiktok/post/"):
            return self._tiktok_post_submit(urllib.parse.unquote(path.removeprefix("/tiktok/post/")), one)
        parts = path.strip("/").split("/")
        if len(parts) == 2 and parts[0] in CLIP_ACTIONS:
            return self._clip_action(parts[0], urllib.parse.unquote(parts[1]), one)
        return self._send(404, "introuvable")

    def _clip_action(self, action: str, clip_id: str, form: dict[str, str],
                     chosen: bool = False):
        """``chosen`` : les réglages TikTok viennent d'être choisis sur l'écran dédié."""
        clip = self.state.get(clip_id)
        if not clip:
            return self._redirect("Ce clip n'existe plus → actualise la page.", err=True)
        caption = form.get("caption", clip["caption"] or "").strip()

        if action == "redo":
            return self._redo(clip, form)
        if action == "done":
            if clip["status"] not in ("rendered", "scheduled", "failed"):
                return self._redirect("Ce clip a déjà changé d'état (publié, programmé ou rejeté) → actualise la page.", err=True)
            self.state.record_post(clip_id, "manuel", "ok")
            self.state.record(clip_id, clip["channel"], "published", caption=caption or None)
            return self._redirect("Clip marqué comme publié ✔",
                                  tab=STUDIO if form.get("back") == STUDIO else None)
        if action == "unschedule":
            ok = self.state.unschedule(clip_id)
            return self._redirect("Programmation annulée." if ok else "Clip déjà parti.",
                                  err=not ok, tab="rendered")
        if action == "reject":
            if clip["status"] not in ("rendered", "failed"):
                return self._redirect("Ce clip a déjà changé d'état (publié, programmé ou rejeté) → actualise la page.", err=True)
            self.state.record(clip_id, clip["channel"], "rejected", caption=caption)
            return self._redirect("Clip rejeté.",
                                  tab=STUDIO if form.get("back") == STUDIO else None)
        if action == "restore":
            if clip["status"] != "rejected" or not clip.get("output_path") \
                    or not Path(clip["output_path"]).exists():
                return self._redirect("Impossible de récupérer ce clip : sa vidéo a été "
                                      "supprimée → relance une recherche.", err=True,
                                      tab="rejected")
            self.state.record(clip_id, clip["channel"], "rendered")
            return self._redirect("Clip récupéré : il est de nouveau dans « À valider ».",
                                  tab="rendered")
        # publication directe : TikTok exige que l'utilisateur choisisse les réglages ;
        # l'écran est aussi reproposé pour réessayer un clip en erreur
        if action in ("publish", "schedule") and not chosen \
                and clip["status"] in ("rendered", "failed", "scheduled") \
                and self._needs_tiktok_choices(clip_id, retry=clip["status"] == "failed"):
            # publication directe : TikTok exige que l'utilisateur choisisse les réglages
            self.state.record(clip_id, clip["channel"], clip["status"], caption=caption)
            return self._redirect_to(f"/tiktok/post/{urllib.parse.quote(clip_id, safe='')}"
                                     f"?then={action}")
        if action == "schedule":
            when = schedule_clip(self.state, self.cfg, clip_id, caption)
            if not when:
                return self._redirect("Ce clip a déjà changé d'état (publié, programmé ou rejeté) → actualise la page.", err=True)
            return self._redirect(
                f"Programmé pour {format_when(int(when.timestamp()), self.cfg.timezone)} ✔")

        if not self.state.claim(clip_id, caption):
            return self._redirect("Ce clip est déjà publié ou en cours d'envoi → regarde les onglets « Envoi en cours » et « Publiés ».", err=True)
        # l'envoi (upload + confirmation TikTok) peut prendre plusieurs minutes : en fond
        threading.Thread(target=publish_in_background, args=(self.app, clip_id),
                         daemon=True).start()
        return self._redirect("Envoi lancé : le clip passera dans « Publiés » (ou « Erreurs ») "
                              "dès que TikTok aura confirmé, la page se mettra à jour.",
                              tab="publishing")

    # ---------- écran « Publier sur TikTok » (publication directe) ----------
    def _needs_tiktok_choices(self, clip_id: str, retry: bool = False) -> bool:
        from .tiktok_post import SETTING

        platforms = self.opts.platforms or self.cfg.platforms
        return ("tiktok" in platforms and self._tiktok_mode() == "direct"
                and (retry or clip_id not in self.state.get_settings().get(SETTING, {})))

    def _creator_info(self) -> tuple[dict, str]:
        from .errors import explain
        from .tiktok import TikTokClient

        try:
            self.cfg.require("tiktok_client_key", "tiktok_client_secret")
            return TikTokClient(self.cfg.tiktok_client_key, self.cfg.tiktok_client_secret,
                                self.cfg.tiktok_token_path).creator_info(), ""
        except (Exception, SystemExit) as exc:
            return {}, explain(exc)

    def _tiktok_post_page(self, clip_id: str, error: str = ""):
        from . import tiktok_post
        from .render import probe_duration

        clip = self.state.get(clip_id)
        if not clip:
            return self._redirect("Ce clip n'existe plus → actualise la page.", err=True)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        then = q.get("then", ["publish"])[0]
        creator, problem = self._creator_info()
        duration = None
        try:
            duration = probe_duration(Path(clip["output_path"]))
        except Exception:
            pass
        body = tiktok_post.render(clip, creator, f"/video/{urllib.parse.quote(clip_id, safe='')}",
                                  "schedule" if then == "schedule" else "publish",
                                  duration=duration, error=problem)
        if error:
            body = f'<div class="flash err">⚠️ {e(error)}</div>' + body
        self._page(body, "/", narrow=True)

    def _tiktok_post_submit(self, clip_id: str, form: dict[str, str]):
        from . import tiktok_post

        clip = self.state.get(clip_id)
        if not clip:
            return self._redirect("Ce clip n'existe plus → actualise la page.", err=True)
        creator, problem = self._creator_info()
        if problem:
            return self._redirect(problem, err=True)
        options, error = tiktok_post.parse(form, creator)
        then = "schedule" if form.get("then") == "schedule" else "publish"
        if error:
            return self._redirect_to(f"/tiktok/post/{urllib.parse.quote(clip_id, safe='')}"
                                     f"?then={then}&" + urllib.parse.urlencode({"msg": error, "err": 1}))
        saved = dict(self.state.get_settings().get(tiktok_post.SETTING, {}))
        saved[clip_id] = options
        self.state.save_settings({tiktok_post.SETTING: saved})
        return self._clip_action(then, clip_id, {"caption": form.get("caption", "")},
                                 chosen=True)

    def _redirect_to(self, location: str):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _redo(self, clip: dict, form: dict[str, str]):
        """Remonte la vidéo (cadrage / sous-titres) à partir du clip déjà téléchargé."""
        src = self.cfg.downloads_dir / f"{clip['clip_id']}.mp4"
        if not src.exists() or not clip.get("output_path"):
            return self._redirect("La vidéo d'origine a été supprimée → relance une recherche pour retrouver ce clip.",
                                  err=True)
        if clip["clip_id"] in self.app.redoing:
            return self._redirect("Ce clip est déjà en cours de remontage → attends une minute, la page se mettra à jour.", err=True)
        layout = form.get("layout") if form.get("layout") in dict(LAYOUTS_REDO) else "auto"
        opts = Options(**{**self.opts.__dict__, "layout": layout,
                          "subtitles": form.get("subtitles") == "1"})
        self.app.redoing.add(clip["clip_id"])
        threading.Thread(target=redo_clip, args=(self.app, clip, src, opts),
                         daemon=True).start()
        return self._redirect("Remontage lancé : la vidéo se mettra à jour toute seule "
                              "dans une minute environ.")

    def _search(self, form: dict[str, str]):
        channels = _split_channels(form.get("channels", ""))
        if not all(CHANNEL_RE.fullmatch(c) for c in channels):
            return self._redirect("Nom de chaîne invalide → écris le nom tel qu'il apparaît dans l'adresse twitch.tv/nom (lettres, chiffres, _), ou laisse vide pour la découverte automatique.", err=True)
        try:
            hours = min(max(float(form.get("hours", 24)), 1), 24 * 30)
            top = min(max(int(form.get("top", 3)), 1), 20)
        except ValueError:
            return self._redirect("Période ou nombre de clips invalide → choisis une valeur dans les menus.", err=True)
        then = form.get("then", "review")
        from .autopilot import load_settings

        layout = load_settings(self.state, self.cfg).get("layout", "auto")
        opts = Options(**{**self.opts.__dict__, "ai_caption": form.get("ai") == "1",
                          "layout": layout,
                          "subtitles": load_settings(self.state, self.cfg).get("subtitles", True),
                          "publish": then == "publish", "schedule": then == "schedule"})
        job = self.app.job
        first = channels[0] if channels else "temps forts du moment"
        if not job.start(f"Recherche en cours : {first}…", run_search, job, self.cfg,
                         self.state, opts, channels, hours, top):
            return self._redirect("Une recherche est déjà en cours → attends la fin, ou clique sur « Arrêter » dans le panneau central.", err=True)
        return self._redirect("Recherche lancée : les clips apparaîtront ici au fur et à "
                              "mesure (téléchargement, sous-titres et rendu prennent "
                              "1 à 2 min par clip).")

    def _save_auto(self, form: dict[str, list[str]]):
        one = {k: v[0].strip() for k, v in form.items()}
        channels = _split_channels(one.get("channels", ""))
        live = _split_channels(one.get("live_channels", ""))
        bad = [c for c in channels + live if not CHANNEL_RE.fullmatch(c)]
        if bad:
            return self._redirect(f"Nom de chaîne invalide : « {bad[0]} » → écris le nom tel qu'il apparaît dans l'adresse twitch.tv/nom.", err=True, to="/auto")
        slots = [s for s in re.split(r"[\s,;]+", one.get("post_slots", "")) if s]
        try:
            parse_slots(slots)
            values = {
                "channels": channels,
                "live_channels": live,
                "source": "channels" if one.get("source") == "channels" else "discover",
                "language": one.get("language", "fr") if one.get("language", "fr") in
                dict(LANGUAGES) else "fr",
                "streamers": min(max(int(one.get("streamers", 30)), 5), 100),
                "every": int(one.get("every", 60)),
                "hours": int(one.get("hours", 24)),
                "top": min(max(int(one.get("top", 2)), 1), 20),
                "min_views": max(int(one.get("min_views", 0)), 0),
                "then": one.get("then") if one.get("then") in ("publish", "manual")
                else "schedule",
                "ratio": float(one.get("ratio", 3)),
                "layout": one.get("layout") if one.get("layout") in dict(LAYOUTS) else "auto",
                "post_slots": slots,
                "max_queue": max(int(one.get("max_queue", 0)), 0),
                "platforms": [p for p in form.get("platforms", []) if p in PLATFORMS],
                "ai_caption": one.get("ai_caption") == "1",
                "subtitles": one.get("subtitles") == "1",
            }
        except (ValueError, SystemExit) as exc:
            return self._redirect(f"Réglage invalide : {exc}", err=True, to="/auto")
        if not values["platforms"]:
            return self._redirect("Choisis au moins une plateforme.", err=True, to="/auto")
        self.state.save_settings(values)
        self._settings_changed()
        return self._redirect("Réglages enregistrés ✔", to="/auto")

    def _apply_slots(self, form: dict[str, str]):
        slots = [s for s in re.split(r"[\s,;]+", form.get("slots", "")) if s]
        try:
            parse_slots(slots)
        except SystemExit as exc:
            return self._redirect(f"Créneaux invalides : {exc}", err=True, to="/auto")
        self.state.save_settings({"post_slots": slots})
        self._settings_changed()
        return self._redirect(f"Créneaux mis à jour : {', '.join(slots)} ✔", to="/auto")

    def _toggle_auto(self, form: dict[str, str]):
        enabled = form.get("enabled") == "1"
        self.state.save_settings({"enabled": enabled})
        self._settings_changed()
        return self._redirect("Pilote automatique activé ✔" if enabled else
                              "Pilote automatique en pause.", to="/auto")

    def _run_auto(self):
        if self.app.autopilot is None:
            return self._redirect("Le pilote automatique ne tourne pas → relance l'app (fenêtre du terminal).", err=True, to="/auto")
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
            from .errors import explain

            return self._redirect(f"Connexion impossible : {explain(exc)}", err=True,
                                  to="/accounts")
        return self._redirect("Entre le code affiché sur la page indiquée.", to="/accounts")

    def _tiktok_code(self, form: dict[str, str]):
        from .tiktok import TikTokClient

        code = extract_oauth_code(form.get("code", ""))
        if not code:
            return self._redirect("Adresse TikTok vide : colle l'adresse complète de la page "
                                  "de retour.", err=True, to="/accounts")
        cfg = self.cfg
        try:
            cfg.require("tiktok_client_key", "tiktok_client_secret", "tiktok_redirect_uri")
            TikTokClient(cfg.tiktok_client_key, cfg.tiktok_client_secret,
                         cfg.tiktok_token_path).exchange_code(code, cfg.tiktok_redirect_uri,
                                                              self._pkce_verifier())
        except (Exception, SystemExit) as exc:
            return self._redirect(_tiktok_error(exc), err=True, to="/accounts")
        return self._redirect("TikTok connecté ✔", to="/accounts")

    def _save_keys(self, form: dict[str, str]):
        from .localkeys import save_keys

        changed = save_keys(self.state, self.cfg, form)
        msg = ("Clés enregistrées : " + ", ".join(changed)) if changed else "Aucun changement."
        return self._redirect(msg, to="/accounts")

    def _save_password(self, form: dict[str, str]):
        from .localkeys import PASSWORD_SETTING, hash_password

        password = form.get("password", "")
        if len(password) < 6:
            return self._redirect("Mot de passe trop court (6 caractères minimum).", err=True,
                                  to="/accounts")
        self.state.save_settings({PASSWORD_SETTING: hash_password(password)})
        self.app.auth_ok.clear()
        return self._redirect("Mot de passe enregistré ✔ (le navigateur va te le demander)",
                              to="/accounts")

    def _connect_instagram(self, form: dict[str, str]):
        from .instagram import InstagramClient

        cfg = self.cfg
        try:
            ig = InstagramClient(cfg.instagram_token_path, user_id=cfg.instagram_user_id,
                                 host=cfg.instagram_graph_host)
            ig.save(form.get("token", "").strip(), cfg.instagram_user_id)
            name = ig.account().get("username", "?")
        except (Exception, SystemExit) as exc:
            from .errors import explain

            return self._redirect(f"Instagram refuse ce token : {explain(exc)}", err=True,
                                  to="/accounts")
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
