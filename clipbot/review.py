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
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0a0a0f">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap">
<title>cliptv</title>{refresh}
<style>
  :root {{ --bg:#0a0a0f; --card:#13131a; --card2:#1a1a23; --line:rgba(255,255,255,.07);
           --line2:rgba(255,255,255,.12); --fg:#f4f4f7; --muted:#9b9bab; --accent:#9b5cff;
           --accent2:#ff4fa3; --grad:linear-gradient(135deg,#9b5cff 0%,#ff4fa3 100%);
           --ok:#3ddc84; --err:#ff6b7a; --radius:16px; color-scheme:dark; }}
  * {{ box-sizing:border-box }}
  html {{ -webkit-text-size-adjust:100% }}
  body {{ margin:0; font:15px/1.5 Inter,system-ui,-apple-system,"Segoe UI",sans-serif; color:var(--fg);
          background:radial-gradient(900px 500px at 15% -10%,rgba(155,92,255,.16),transparent 60%),
                     radial-gradient(800px 500px at 100% 0%,rgba(255,79,163,.08),transparent 60%),var(--bg);
          background-attachment:fixed; -webkit-font-smoothing:antialiased }}
  a {{ color:#c3a3ff }}
  ::selection {{ background:rgba(155,92,255,.45) }}
  header {{ position:sticky; top:0; z-index:10; background:rgba(10,10,15,.72);
            backdrop-filter:saturate(1.6) blur(16px); -webkit-backdrop-filter:saturate(1.6) blur(16px);
            border-bottom:1px solid var(--line) }}
  .top {{ display:flex; align-items:center; gap:16px; max-width:1400px; margin:0 auto; padding:10px 20px }}
  .brand {{ display:flex; align-items:center; gap:10px; color:inherit; text-decoration:none; flex:none }}
  .logo {{ width:32px; height:32px; border-radius:10px; background:var(--grad); display:grid; place-items:center;
           box-shadow:0 6px 20px rgba(155,92,255,.35) }}
  .logo svg {{ width:15px; height:15px; margin-left:2px }}
  .word {{ font-size:19px; font-weight:800; letter-spacing:-.02em }}
  .word b {{ background:var(--grad); -webkit-background-clip:text; background-clip:text; color:transparent }}
  nav.main {{ display:flex; gap:4px; margin:0 auto; padding:4px; background:rgba(255,255,255,.04);
              border:1px solid var(--line); border-radius:999px }}
  nav.main a {{ display:flex; align-items:center; gap:7px; color:var(--muted); padding:7px 14px; border-radius:999px;
                text-decoration:none; font-weight:500; font-size:14px; white-space:nowrap; transition:.15s }}
  nav.main a:hover {{ color:var(--fg); background:rgba(255,255,255,.05) }}
  nav.main a.on {{ color:#fff; background:rgba(155,92,255,.22); box-shadow:inset 0 0 0 1px rgba(155,92,255,.45) }}
  nav.main svg {{ width:17px; height:17px; flex:none }}
  .pill {{ display:inline-flex; align-items:center; gap:8px; font-size:13px; color:var(--muted);
           background:rgba(255,255,255,.04); border:1px solid var(--line); border-radius:999px; padding:6px 12px;
           max-width:340px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:0 1 auto }}
  .pill::before {{ content:""; width:7px; height:7px; border-radius:50%; background:#5b5b66; flex:none }}
  .pill.on {{ color:#bff5d4; border-color:rgba(61,220,132,.3); background:rgba(61,220,132,.08) }}
  .pill.on::before {{ background:var(--ok); box-shadow:0 0 0 0 rgba(61,220,132,.6); animation:pulse 1.8s infinite }}
  @keyframes pulse {{ 70% {{ box-shadow:0 0 0 7px rgba(61,220,132,0) }} 100% {{ box-shadow:0 0 0 0 rgba(61,220,132,0) }} }}
  nav.sub {{ display:flex; gap:6px; overflow-x:auto; scrollbar-width:none; margin:0 0 16px; padding-bottom:2px }}
  nav.sub a {{ display:flex; align-items:center; gap:8px; color:var(--muted); padding:8px 14px; border-radius:999px;
               text-decoration:none; font-weight:500; font-size:14px; white-space:nowrap;
               background:var(--card); border:1px solid var(--line); transition:.15s }}
  nav.sub a:hover {{ color:var(--fg); border-color:var(--line2) }}
  nav.sub a.on {{ color:#fff; background:var(--grad); border-color:transparent }}
  .count {{ min-width:22px; padding:1px 7px; border-radius:999px; font-size:12px; font-weight:700; text-align:center;
            background:rgba(255,255,255,.08) }}
  nav.sub a.on .count {{ background:rgba(0,0,0,.22) }}
  .wrap {{ padding:24px 20px 40px; max-width:1400px; margin:0 auto }}
  .narrow {{ max-width:780px }}
  .panel {{ background:linear-gradient(180deg,rgba(255,255,255,.025),transparent 120px),var(--card);
            border:1px solid var(--line); border-radius:var(--radius); padding:18px 20px; margin-bottom:16px }}
  .panel h2 {{ margin:0 0 10px; font-size:17px; font-weight:700; letter-spacing:-.01em }}
  details.panel summary {{ cursor:pointer; font-weight:600; list-style:none; display:flex; align-items:center; gap:8px }}
  details.panel summary::-webkit-details-marker {{ display:none }}
  details.panel summary::after {{ content:""; margin-left:auto; width:8px; height:8px; border-right:2px solid var(--muted);
            border-bottom:2px solid var(--muted); transform:rotate(45deg); transition:.2s }}
  details.panel[open] summary::after {{ transform:rotate(225deg) }}
  details.panel summary:has(.meta)::after {{ margin-left:14px }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:14px; margin-top:14px }}
  .full {{ grid-column:1/-1 }}
  label {{ display:flex; flex-direction:column; gap:6px; font-size:13px; font-weight:500; color:var(--muted) }}
  label.check {{ flex-direction:row; align-items:center; gap:10px; color:var(--fg); font-size:15px; font-weight:400 }}
  input, select, textarea {{ background:rgba(0,0,0,.28); color:var(--fg); border:1px solid var(--line2); border-radius:10px;
                             padding:10px 12px; font:inherit; font-size:16px; width:100%; transition:border-color .15s, box-shadow .15s }}
  input:focus, select:focus, textarea:focus {{ outline:none; border-color:var(--accent); box-shadow:0 0 0 3px rgba(155,92,255,.25) }}
  input[type=checkbox] {{ width:20px; height:20px; flex:none; accent-color:var(--accent) }}
  input[type=radio] {{ accent-color:var(--accent); width:auto }}
  :focus-visible {{ outline:2px solid var(--accent); outline-offset:2px }}
  .info, .meta {{ color:var(--muted); font-size:13px; overflow-wrap:anywhere }}
  .wrap > p.info {{ background:rgba(155,92,255,.07); border:1px solid rgba(155,92,255,.18); border-radius:12px; padding:10px 14px;
            line-height:1.6; margin:0 0 18px }}
  .meta a {{ color:var(--muted) }}
  main {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(290px,1fr)); gap:18px }}
  .card {{ position:relative; background:var(--card); border:1px solid var(--line); border-radius:20px; padding:12px;
           display:flex; flex-direction:column; gap:10px; transition:transform .2s, border-color .2s, box-shadow .2s }}
  .card:hover {{ border-color:var(--line2); box-shadow:0 18px 40px rgba(0,0,0,.35) }}
  .card > div > strong {{ font-size:15px; font-weight:700; line-height:1.35; letter-spacing:-.01em }}
  video {{ width:100%; aspect-ratio:9/16; max-height:72vh; object-fit:contain; background:#000; border-radius:14px; display:block }}
  textarea {{ min-height:96px; resize:vertical; line-height:1.5 }}
  .row {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center }}
  button, .btn {{ flex:1 1 30%; min-height:44px; border:0; border-radius:12px; padding:10px 16px; font:inherit;
            font-weight:600; color:#fff; cursor:pointer; background:var(--grad); text-align:center; text-decoration:none;
            box-shadow:0 6px 18px rgba(155,92,255,.25); transition:transform .12s, filter .15s, box-shadow .15s }}
  button:hover, .btn:hover {{ filter:brightness(1.08); box-shadow:0 8px 24px rgba(155,92,255,.35) }}
  button:active, .btn:active {{ transform:scale(.98) }}
  button:disabled {{ opacity:.5; cursor:default; transform:none }}
  .now {{ background:rgba(255,255,255,.07); box-shadow:inset 0 0 0 1px var(--line2) }}
  .now:hover {{ background:rgba(61,220,132,.14); box-shadow:inset 0 0 0 1px rgba(61,220,132,.45) }}
  .rej {{ background:rgba(255,255,255,.07); box-shadow:inset 0 0 0 1px var(--line2) }}
  .small {{ flex:0 0 auto; min-height:36px; padding:6px 14px; font-size:14px }}
  .when {{ font-weight:600 }}
  form.act {{ display:flex; flex-direction:column; gap:8px; margin-top:auto }}
  .card > .meta {{ margin-top:-4px }}
  form.act textarea {{ min-height:0; font-size:14px; padding:10px 12px; background:rgba(0,0,0,.25) }}
  .bar {{ display:flex; gap:8px; align-items:stretch }}
  .bar > button {{ flex:1 1 0; min-height:42px; padding:8px 10px; font-size:14px }}
  details.more {{ position:relative; flex:0 0 auto }}
  .iconbtn {{ list-style:none; height:100%; min-height:42px; width:44px; display:grid; place-items:center;
             background:rgba(255,255,255,.07); box-shadow:inset 0 0 0 1px var(--line2); border-radius:12px;
             cursor:pointer; font-weight:700; font-size:18px; transition:.15s }}
  .iconbtn:hover {{ background:rgba(255,255,255,.12) }}
  .iconbtn::-webkit-details-marker {{ display:none }}
  details.more[open] .iconbtn {{ background:rgba(155,92,255,.25) }}
  .menu {{ position:absolute; right:0; bottom:calc(100% + 8px); z-index:5; width:260px; background:rgba(26,26,35,.96);
          backdrop-filter:blur(14px); border:1px solid var(--line2); border-radius:14px; padding:6px; display:flex;
          flex-direction:column; gap:2px; box-shadow:0 20px 50px rgba(0,0,0,.6) }}
  .menu > a, .menu > button {{ background:transparent; box-shadow:none; color:var(--fg); text-align:left; text-decoration:none;
          padding:9px 10px; min-height:0; border-radius:8px; font-weight:500; font-size:14px; flex:none }}
  .menu > a:hover, .menu > button:hover {{ background:rgba(255,255,255,.07); filter:none; box-shadow:none }}
  .menu .danger {{ color:var(--err) }}
  .menu .redo {{ border-top:1px solid var(--line); border-bottom:1px solid var(--line); margin:4px 0; padding:10px;
          display:flex; flex-wrap:wrap; gap:8px; align-items:center; font-size:14px }}
  .menu .redo span {{ flex:1 1 100%; font-weight:600 }}
  .menu .redo select {{ flex:1 1 100%; padding:7px 10px; font-size:14px }}
  .menu .redo label {{ flex:1; font-size:14px }}
  .menu .redo button {{ flex:0 0 auto; min-height:34px; padding:4px 14px; font-size:14px }}
  .player {{ position:relative; width:min(100%, calc(72vh * 9 / 16)); aspect-ratio:9/16; margin:0 auto;
            container-type:inline-size; border-radius:14px; overflow:hidden; background:#000 }}
  .player video {{ width:100%; height:100%; max-height:none; border-radius:0 }}
  .ttbtn {{ position:absolute; top:10px; left:10px; z-index:3; flex:none; min-height:0; padding:5px 10px;
           font-size:12px; border-radius:999px; background:rgba(10,10,15,.7); backdrop-filter:blur(8px);
           box-shadow:inset 0 0 0 1px rgba(255,255,255,.18) }}
  .player.tt .ttbtn {{ background:#fff; color:#000 }}
  .player.tt {{ cursor:pointer }}
  .card.tton .pot {{ display:none }}
  .ttui {{ display:none; position:absolute; inset:0; z-index:2; pointer-events:none; color:#fff;
          font-family:"TikTok Sans",Inter,system-ui,sans-serif; text-shadow:0 1px 2px rgba(0,0,0,.5) }}
  .player.tt .ttui {{ display:block }}
  .ttui .tabs {{ position:absolute; top:4.5%; right:4%; font-size:4.6cqw; font-weight:600;
                color:rgba(255,255,255,.7) }}
  .ttui .tabs b {{ color:#fff; border-bottom:.6cqw solid #fff; padding-bottom:1cqw; margin-left:4cqw }}
  .ttui .side {{ position:absolute; right:2.5%; bottom:17%; width:13cqw; display:flex; flex-direction:column;
                align-items:center; gap:4.5cqw; font-size:3.2cqw; font-weight:600 }}
  .ttui .side span {{ display:flex; flex-direction:column; align-items:center; gap:.6cqw }}
  .ttui .side svg {{ width:9cqw; height:9cqw; filter:drop-shadow(0 1px 2px rgba(0,0,0,.4)) }}
  .ttui .av {{ width:11cqw; height:11cqw; border-radius:50%; border:.5cqw solid #fff; background:var(--grad) center/cover }}
  .ttui .disc {{ width:10cqw; height:10cqw; border-radius:50%; background:radial-gradient(#555 30%,#111 32%);
                border:2cqw solid #222 }}
  .ttui .cap {{ position:absolute; left:3.5%; right:20%; bottom:4%; font-size:3.7cqw; line-height:1.35 }}
  .ttui .cap b {{ display:block; font-size:4.2cqw; margin-bottom:1.2cqw }}
  .ttui .txt {{ display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;
               white-space:pre-line }}
  .ttui .snd {{ margin-top:1.6cqw; font-size:3.4cqw; white-space:nowrap; overflow:hidden; text-overflow:ellipsis }}
  .ttui .zone {{ position:absolute; left:0; right:0; bottom:0; height:22%;
                background:linear-gradient(transparent,rgba(0,0,0,.45)) }}
  .badges {{ display:flex; gap:6px; flex-wrap:wrap }}
  .badge {{ font-size:12px; font-weight:500; padding:3px 9px; border-radius:999px; background:rgba(255,255,255,.06);
            color:var(--muted); border:1px solid var(--line) }}
  .badge.ok {{ background:rgba(61,220,132,.1); color:#8ff0b8; border-color:rgba(61,220,132,.25) }}
  .badge.failed {{ background:rgba(255,107,122,.1); color:#ffa3ad; border-color:rgba(255,107,122,.25) }}
  .card.tk img, .card.tk .nocover {{ width:100%; aspect-ratio:9/16; max-height:420px; object-fit:cover;
    border-radius:14px; background:#000; display:grid; place-items:center; font-size:40px }}
  .tkstats {{ display:flex; gap:12px; flex-wrap:wrap; font-size:14px; font-weight:600 }}
  .mini {{ display:flex; flex-wrap:wrap; gap:4px 10px; font-size:12px; color:var(--muted) }}
  .mini a, .mini .link {{ color:var(--muted); background:none; border:0; padding:0; font:inherit; box-shadow:none;
    cursor:pointer; text-decoration:none; flex:none; min-height:0 }}
  .mini a:hover, .mini .link:hover {{ color:var(--fg); filter:none; box-shadow:none }}
  .pot {{ --r:#9d9d9d; position:absolute; top:22px; right:22px; z-index:2 }}
  .pot.r-uncommon {{ --r:#3ddc4a }} .pot.r-rare {{ --r:#4da3ff }} .pot.r-epic {{ --r:#b964ff }}
  .pot.r-legendary {{ --r:#ff9a1f }}
  .pot summary {{ cursor:pointer; list-style:none; min-width:48px; text-align:center;
    padding:4px 10px; border-radius:10px; border:1.5px solid var(--r); background:rgba(10,10,15,.75);
    backdrop-filter:blur(8px); color:var(--r); font-size:18px; font-weight:800; font-variant-numeric:tabular-nums }}
  .pot summary::-webkit-details-marker {{ display:none }}
  .pot.r-legendary summary, .pot.r-epic summary {{ box-shadow:0 0 16px color-mix(in srgb,var(--r) 55%,transparent) }}
  .pot .why {{ position:absolute; right:0; margin-top:6px; width:250px; background:rgba(26,26,35,.97);
    border:1px solid var(--r); border-radius:12px; padding:10px 12px; font-size:12px; box-shadow:0 20px 50px rgba(0,0,0,.6) }}
  .pot .why strong {{ color:var(--r) }}
  .pot ul {{ margin:6px 0 0; padding-left:18px; color:var(--muted); font-size:12px }}
  .flash {{ padding:12px 16px; border-radius:12px; background:rgba(61,220,132,.1); border:1px solid rgba(61,220,132,.28);
            color:#c9f7da; margin-bottom:18px; animation:drop .35s ease-out }}
  .flash.err {{ background:rgba(255,107,122,.1); border-color:rgba(255,107,122,.3); color:#ffd0d5 }}
  @keyframes drop {{ from {{ opacity:0; transform:translateY(-6px) }} }}
  #fresh {{ max-width:1400px; margin:0 auto 10px !important; width:calc(100% - 40px) }}
  .acc {{ display:flex; justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap;
          padding:14px 0; border-top:1px solid var(--line) }}
  .acc:first-of-type {{ border-top:0 }}
  .acc > div:first-child {{ flex:1 1 300px }}
  .code {{ font:600 22px/1 ui-monospace,monospace; letter-spacing:2px; color:#fff }}
  table {{ width:100%; border-collapse:collapse }} td {{ padding:8px 4px; border-top:1px solid var(--line); vertical-align:top }}
  .empty {{ color:var(--muted); grid-column:1/-1; text-align:center; padding:48px 16px; border:1px dashed var(--line2);
            border-radius:var(--radius) }}
  @media (prefers-reduced-motion: reduce) {{ *, *::before {{ animation:none !important; transition:none !important }} }}
  @media (max-width:820px) {{
    .top {{ padding:10px 14px }}
    nav.main {{ position:fixed; z-index:10; left:10px; right:10px; bottom:calc(10px + env(safe-area-inset-bottom));
                margin:0; justify-content:space-around; background:rgba(19,19,26,.88); backdrop-filter:blur(16px);
                -webkit-backdrop-filter:blur(16px); border-color:var(--line2); border-radius:20px; padding:6px;
                box-shadow:0 12px 40px rgba(0,0,0,.55) }}
    nav.main a {{ flex:1; flex-direction:column; gap:3px; padding:7px 2px; font-size:11px; border-radius:14px }}
    nav.main svg {{ width:21px; height:21px }}
    .pill {{ margin-left:auto; max-width:60vw }}
    .wrap {{ padding:16px 12px calc(100px + env(safe-area-inset-bottom)) }}
    main, .grid {{ grid-template-columns:1fr }}
    #fresh {{ width:calc(100% - 24px) }}
  }}
</style></head><body>
<header><div class="top"><a class="brand" href="/" aria-label="cliptv"><span class="logo"><svg viewBox="0 0 24 24" fill="#fff"><path d="M6 3.5v17l14-8.5z"/></svg></span><span class="word">clip<b>tv</b></span></a>
<nav class="main">{nav}</nav>
<span id="status" class="pill{status_cls}">{status}</span>
<div id="progress" role="status" aria-live="polite"></div></div>
<div id="fresh" class="flash" style="display:none">Nouveaux clips prêts ·
<a href="" onclick="location.reload();return false">actualiser</a></div>
</header>
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
// aperçu « comme sur TikTok » : interface de l'app par-dessus la vidéo, avec la description
function ttToggle(btn) {{
  const player = btn.closest('.player'), video = player.querySelector('video');
  const on = player.classList.toggle('tt');
  player.closest('.card').classList.toggle('tton', on);
  btn.textContent = on ? "✕ Fermer l’aperçu" : '👁 Aperçu TikTok';
  video.controls = !on;  // comme sur TikTok : un clic sur la vidéo = lecture / pause
  if (on) video.play().catch(() => {{}});
  ttFill(player.closest('.card'));
}}
document.addEventListener('click', ev => {{
  const player = ev.target.closest('.player.tt');
  if (!player || ev.target.closest('.ttbtn')) return;
  const video = player.querySelector('video');
  video.paused ? video.play() : video.pause();
}});
function ttFill(card) {{
  const area = card && card.querySelector('textarea'), box = card && card.querySelector('.ttui .txt');
  if (area && box) box.textContent = area.value;
}}
document.addEventListener('input', ev => {{ if (ev.target.tagName === 'TEXTAREA') ttFill(ev.target.closest('.card')); }});
// « Préparer » : télécharge la vidéo, copie la description, ouvre TikTok Studio
function prepareClip(btn) {{
  const form = btn.closest('form');
  const a = document.createElement('a');
  a.href = btn.dataset.video; a.download = btn.dataset.name; document.body.appendChild(a);
  a.click(); a.remove();
  copyCaption(form.querySelector('.mini .link'));
  window.open('https://www.tiktok.com/tiktokstudio/upload', '_blank', 'noopener');
  btn.textContent = '✔ Prêt : glisse la vidéo, colle (Ctrl+V)';
}}
// téléphone (si le navigateur le permet) : partage direct de la vidéo vers l'app TikTok
async function shareClip(btn) {{
  const form = btn.closest('form');
  copyCaption(form.querySelector('.mini .link'));
  const blob = await (await fetch(btn.dataset.video)).blob();
  const file = new File([blob], btn.dataset.name, {{ type: 'video/mp4' }});
  try {{ await navigator.share({{ files: [file], text: form.querySelector('textarea').value }}); }} catch (e) {{}}
}}
if (navigator.canShare && navigator.canShare({{ files: [new File([''], 'x.mp4', {{ type: 'video/mp4' }})] }})) {{
  document.addEventListener('DOMContentLoaded', () => document.querySelectorAll('.share').forEach(b => b.hidden = false));
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
    // bouton de recherche : réactivé dès que la recherche est finie ou arrêtée
    document.querySelectorAll('.searchbtn').forEach(b => b.disabled = s.running);
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
  #progress { display:none; align-items:center; gap:12px; flex:0 1 460px; min-width:0; margin-left:auto;
              padding:7px 8px 7px 14px; border-radius:14px; background:rgba(61,220,132,.07);
              border:1px solid rgba(61,220,132,.28) }
  #progress.done { background:rgba(155,92,255,.1); border-color:rgba(155,92,255,.35) }
  #progress .ptext { flex:1; min-width:0 }
  #progress .pl1 { display:flex; align-items:center; gap:8px; font-size:13px; color:#f4f4f7; white-space:nowrap }
  #progress .pl1 b { color:#bff5d4; font-weight:700 }
  #progress.done .pl1 b { color:#d8c2ff }
  #progress .pname { overflow:hidden; text-overflow:ellipsis; font-weight:600 }
  #progress .ptime { margin-left:auto; color:#9b9bab; font-variant-numeric:tabular-nums; padding-left:6px }
  #progress .pl2 { font-size:12px; color:#9b9bab; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
                   margin-top:1px }
  #progress .pbar { display:flex; gap:3px; margin-top:6px }
  #progress .pbar i { flex:1; height:3px; border-radius:2px; background:rgba(255,255,255,.12) }
  #progress .pbar i.ok { background:#3ddc84 }
  #progress .pbar i.now { background:linear-gradient(90deg,#3ddc84,rgba(61,220,132,.25));
                          animation:blink 1.2s ease-in-out infinite }
  #progress.done .pbar i { background:linear-gradient(90deg,#9b5cff,#ff4fa3) }
  @keyframes blink { 50% { opacity:.45 } }
  #progress .spin { display:inline-block; width:12px; height:12px; flex:none; border:2px solid #3ddc84;
                    border-right-color:transparent; border-radius:50%; animation:spin .8s linear infinite }
  @keyframes spin { to { transform:rotate(360deg) } }
  @media (prefers-reduced-motion: reduce) { #progress .spin, #progress .pbar i.now { animation:none } }
  #progress button { flex:none; min-height:32px; width:32px; padding:0; border-radius:10px; font-size:13px;
                     background:rgba(255,107,122,.16); box-shadow:inset 0 0 0 1px rgba(255,107,122,.4); color:#ffd0d5 }
  #progress button:disabled { opacity:.5 }
  header .top.busy #status { display:none }
  #progress { position:relative; cursor:pointer }
  #progress .chev { flex:none; width:8px; height:8px; margin:0 4px 3px; border-right:2px solid #9b9bab;
                    border-bottom:2px solid #9b9bab; transform:rotate(45deg); transition:transform .2s }
  #progress.open .chev { transform:rotate(225deg); margin-bottom:-3px }
  #progress .pdrop { position:absolute; top:calc(100% + 8px); right:0; width:min(440px, calc(100vw - 24px));
                     z-index:20; cursor:default; background:rgba(19,19,26,.97); backdrop-filter:blur(16px);
                     border:1px solid rgba(255,255,255,.12); border-radius:16px; padding:14px 16px;
                     box-shadow:0 20px 50px rgba(0,0,0,.6) }
  #progress .pclip { color:#9b9bab; font-size:13px; margin-bottom:8px; overflow-wrap:anywhere }
  #progress ol { list-style:none; margin:0; padding:0 }
  #progress li { display:flex; gap:10px; padding:6px 0; color:#6b6b78; font-size:14px; align-items:flex-start }
  #progress li.st-done { color:#b8b8c4 }
  #progress li.st-now { color:#f4f4f7; font-weight:600; background:rgba(61,220,132,.08); border-radius:10px;
                        margin:2px -8px; padding:8px }
  #progress li .ico { width:18px; flex:none; text-align:center }
  #progress li .help { display:block; font-weight:400; color:#9b9bab; font-size:12px; margin-top:2px }
  #progress li .dur { font-weight:400; color:#9b9bab; font-size:12px }
  #progress .pmsg { margin-top:8px; padding:8px 10px; border-radius:10px; background:rgba(155,92,255,.1);
                    font-size:13px }
</style>
<script>
// étape de la recherche en cours, en haut à droite (textContent : données non fiables)
(function () {
  const box = document.getElementById('progress'), top = box.closest('.top');
  let open = false, last = null;
  try { open = sessionStorage.getItem('cliptv-progress-open') === '1'; } catch (e) {}
  box.addEventListener('click', ev => {
    ev.stopPropagation();  // le clic ne doit pas aussi compter comme « clic ailleurs »
    if (ev.target.closest('button') || ev.target.closest('.pdrop')) return;
    open = !open;
    try { sessionStorage.setItem('cliptv-progress-open', open ? '1' : '0'); } catch (e) {}
    if (last) render(last[0], last[1]);
  });
  document.addEventListener('click', ev => {  // clic ailleurs : on replie
    if (open && !box.contains(ev.target)) { open = false; if (last) render(last[0], last[1]); }
  });
  function details(p, steps, current) {
    const drop = el('div', 'pdrop');
    if (p.active && p.clip) drop.append(el('div', 'pclip', p.clip));
    const ol = el('ol');
    steps.forEach((s, i) => {
      const state = !p.active || i < current ? 'st-done' : i === current ? 'st-now' : '';
      const li = el('li', state), ico = el('span', 'ico');
      if (state === 'st-now') ico.append(el('span', 'spin')); else ico.textContent = state ? '✓' : '○';
      const txt = el('div', '', s[1]);
      const spent = (p.durations || {})[s[0]];
      if (state === 'st-done' && spent) txt.append(el('span', 'dur', '  · ' + fmt(spent)));
      if (state === 'st-now') txt.append(el('span', 'help', p.detail ? p.detail + ' — ' + s[2] : s[2]));
      li.append(ico, txt); ol.append(li);
    });
    drop.append(ol);
    if (p.tokens) drop.append(el('div', 'pclip', '🤖 Claude : ' + tok(p.tokens) + ' tokens pour cette recherche'));
    if (!p.active && p.message) drop.append(el('div', 'pmsg', p.message));
    return drop;
  }
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function fmt(s) { return s < 60 ? s + ' s' : Math.floor(s / 60) + ' min ' + String(s % 60).padStart(2, '0') + ' s'; }
  function tok(n) { return n >= 1000 ? (n / 1000).toFixed(1).replace('.', ',') + ' k' : String(n); }
  function render(p, steps) {
    last = [p, steps];
    const recent = !p.active && p.ended && (Date.now() / 1000 - p.ended) < 15;
    const show = p.active || recent;
    box.style.display = show ? 'flex' : 'none';
    top.classList.toggle('busy', !!show);
    if (!show) return;
    box.classList.toggle('done', !p.active);
    box.classList.toggle('open', open);
    box.title = open ? '' : 'Clique pour voir le détail des étapes';
    box.replaceChildren();
    const text = el('div', 'ptext'), l1 = el('div', 'pl1');
    const current = steps.findIndex(s => s[0] === p.step);
    if (p.active) {
      const st = steps[current];
      l1.append(el('span', 'spin'), el('b', '', current >= 0 ? 'Étape ' + (current + 1) + '/' + steps.length : '🔎'),
                el('span', 'pname', p.stopping ? 'Arrêt en cours…' : st ? st[1] : (p.title || 'Recherche en cours')));
      const detail = [p.clip, p.detail || (st ? st[2] : '')].filter(Boolean).join(' · ');
      text.append(l1, el('div', 'pl2', detail || 'Préparation…'));
      text.title = (p.clip ? p.clip + '\\n' : '') + (st ? st[1] + ' : ' + (p.detail ? p.detail + ' — ' : '') + st[2] : '');
    } else {
      l1.append(el('b', '', '✅ Terminé'), el('span', 'pname', ''));
      text.append(l1, el('div', 'pl2', (p.message || '') + (p.tokens ? ' · Claude : ' + tok(p.tokens) + ' tokens' : '')));
      const spent = steps.filter(s => (p.durations || {})[s[0]]).map(s => s[1] + ' : ' + fmt(p.durations[s[0]]));
      text.title = (p.message || '') + (spent.length ? '\\n' + spent.join('\\n') : '');
    }
    l1.append(el('span', 'ptime', fmt(p.elapsed || 0)));
    const bar = el('div', 'pbar');
    steps.forEach((s, i) => bar.append(el('i', !p.active || i < current ? 'ok' : i === current ? 'now' : '')));
    text.append(bar);
    box.append(text);
    if (p.active) {
      const stop = el('button', '', '⏹');
      stop.type = 'button'; stop.title = 'Arrêter la recherche (les clips déjà prêts sont gardés)';
      stop.setAttribute('aria-label', 'Arrêter la recherche');
      stop.disabled = !!p.stopping;
      stop.onclick = async () => {
        stop.disabled = true;
        try { await fetch('/stop', {method: 'POST', credentials: 'same-origin'}); } catch (e) {}
      };
      box.append(stop);
    }
    box.append(el('span', 'chev'));
    if (open) box.append(details(p, steps, current));
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
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#9b5cff"/>
<stop offset="1" stop-color="#ff4fa3"/></linearGradient></defs>
<rect width="100" height="100" rx="26" fill="url(#g)"/><path d="M38 27 L76 50 L38 73 Z" fill="#fff"/></svg>"""

SECTIONS = [("/", "Clips"), ("/auto", "Pilote auto"), ("/stats", "Statistiques"),
            ("/accounts", "Comptes"), ("/help", "Aide")]
_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{}</svg>')
ICONS = {
    "/": _SVG.format('<rect x="3" y="3" width="18" height="18" rx="5"/><path d="M10 8.5v7l5.5-3.5z"/>'),
    "/auto": _SVG.format('<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>'),
    "/stats": _SVG.format('<path d="M3 21h18M7 17v-5M12 17V7M17 17v-8"/>'),
    "/accounts": _SVG.format('<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6 8-6s8 2 8 6"/>'),
    "/help": _SVG.format('<circle cx="12" cy="12" r="9"/><path d="M9.6 9.2a2.5 2.5 0 1 1 3.3 2.4c-.6.2-.9.8-.9 1.4v.5M12 17h.01"/>'),
}
STUDIO = "studio"  # ancien onglet « TikTok Studio » (redirige vers « À publier »)
AUTO_PUBLISH = "auto_publish"  # publication / programmation par ClipTV (app validée par TikTok)
MANUAL_TABS = [("rendered", "À publier"), ("published", "Publiés"), ("rejected", "Historique")]
TABS = [("rendered", "À valider"), ("scheduled", "Programmés"), ("publishing", "Envoi en cours"),
        ("published", "Publiés"), ("rejected", "Historique"), ("failed", "Erreurs")]
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

CARD = """<div class="card">{corner}
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
  <input type="hidden" name="back" value="rendered">
  <textarea name="caption" rows="4" aria-label="Description">{caption}</textarea>
  <div class="bar">
    <button type="button" class="prep" data-video="{download}" data-name="{filename}"
            onclick="prepareClip(this)" title="Télécharge la vidéo, copie la description et ouvre TikTok Studio">🚀 Préparer</button>
    <button class="now" type="submit" title="À cliquer une fois publié sur TikTok">✔ Publié</button>
    {menu}
  </div>
  <div class="mini">
    <a href="{download}" download="{filename}">⬇ Vidéo seule</a> ·
    <button type="button" class="link" onclick="copyCaption(this)">📋 Description seule</button>
    <button type="button" class="link share" hidden onclick="shareClip(this)" data-video="{download}" data-name="{filename}">· 📲 Partager vers TikTok</button>
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
<summary>🔎 Recherche ponctuelle{claude}</summary>
<form method="post" action="/search">
  <div class="grid">
    <label class="full">Chaînes Twitch (laisse vide pour trouver seul les temps forts du moment)
      <input name="channels" value="{channels}" placeholder="vide = découverte automatique"
             autocapitalize="none" autocorrect="off"></label>
    <label>Période <select name="hours">{hours}</select></label>
    <label>Clips par chaîne <input name="top" type="number" min="1" max="20" value="3"></label>
    {then_field}
    <label class="check"><input type="checkbox" name="ai" value="1" checked> Légende par Claude</label>
  </div>
  <div class="row" style="margin-top:12px"><button type="submit" class="searchbtn"{disabled}>Lancer la recherche</button></div>
</form>
</details>"""


def _download_name(clip: dict) -> str:
    """Nom lisible du fichier téléchargé : streamer + titre (sans accents ni espaces)."""
    import unicodedata

    slug = unicodedata.normalize("NFKD", f"{clip.get('channel', '')} {clip.get('title') or ''}")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", slug.encode("ascii", "ignore").decode()).strip("-")
    return f"{slug[:60]}.mp4" if slug else ""


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
    if not state.get_settings().get(AUTO_PUBLISH):  # « À publier » = dernière recherche
        state.archive_pending()
        state.trim_rejected(cfg.downloads_dir)
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
        nav = "".join(f'<a class="{"on" if p == section else ""}" href="{p}">{ICONS[p]}'
                      f'<span>{label}</span></a>' for p, label in SECTIONS)
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
        manual = not self._auto_publish()  # tu publies toi-même (TikTok Studio)
        if manual:
            self._release_scheduled()
            if tab not in {s for s, _ in MANUAL_TABS}:  # ancien onglet (Studio, Erreurs…)
                tab = "rendered"
        counts = {s: self.state.count(s) for s, _ in TABS}
        tiktok_videos = self.state.recent_videos()
        counts["published"] = len(tiktok_videos)  # « Publiés » = ce qui est sur TikTok
        tab_list = MANUAL_TABS if manual else TABS
        tabs = "".join(
            f'<a class="{"on" if s == tab else ""}" href="/?s={s}">{label} '
            f'<span class="count">{counts[s]}</span></a>'
            for s, label in tab_list)
        if tab == "published":
            return self._published_page(tabs, tiktok_videos)
        cards = "".join(self._card(c, manual=manual) for c in self.state.list(tab)) or \
            '<p class="empty">Rien ici pour le moment.</p>'
        info = e(f"Publication : {', '.join(PLATFORM_NAMES.get(p, p) for p in self.platforms)}"
                 f" · créneaux {', '.join(self.cfg.post_slots)} ({self.cfg.timezone})")
        if manual:
            from . import stats as _stats

            checked = bool(self.state.get_settings().get(_stats.ENABLED))
            info = ('Pour publier un clip : <strong>🚀 Préparer</strong> (télécharge la vidéo, '
                    'copie la description et ouvre TikTok Studio) → dans TikTok Studio, glisse la '
                    'vidéo depuis tes Téléchargements, colle la description (Ctrl+V), publie → '
                    'reviens ici et clique <strong>✔ Publié</strong>.')
            if checked:  # liste des vidéos du compte rafraîchie en fond (15 min max)
                threading.Thread(target=_stats.refresh_before_search,
                                 args=(self.cfg, self.state), daemon=True).start()
            else:
                info += ('<br>⚠️ Impossible de vérifier si un clip est déjà sur ton TikTok : '
                         'active les statistiques (onglet <a href="/stats">Statistiques</a>).')
        body = (f'<nav class="sub">{tabs}</nav>{self._search_panel()}'
                f'<p class="info">{info}</p><main>{cards}</main>')
        self._page(body, "/")

    def _published_page(self, tabs: str, videos: list[dict]):
        """Onglet « Publiés » : tes vraies vidéos TikTok (liste du compte), pas l'historique
        de ClipTV. Rafraîchie en fond si elle a plus de 15 min."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from . import stats
        from .stats_page import compact

        settings = self.state.get_settings()
        if settings.get(stats.ENABLED):
            threading.Thread(target=stats.refresh_before_search, args=(self.cfg, self.state),
                             daemon=True).start()
            updated = settings.get(stats.UPDATED)
            ago = (f"mise à jour il y a {max(int((time.time() - updated) / 60), 0)} min"
                   if updated else "pas encore récupérée")
            info = (f"Tes vidéos sur TikTok ({e(ago)}). Les clips de « À publier » que ClipTV "
                    "retrouve ici passent tout seuls en publiés.")
            if settings.get(stats.ERROR):
                info += f'<br>⚠️ {e(settings[stats.ERROR])}'
        else:
            info = ('⚠️ Active les statistiques TikTok (onglet <a href="/stats">Statistiques'
                    '</a>) pour voir ici tes vidéos publiées, avec leurs vues.')
        zone = ZoneInfo(self.cfg.timezone)
        cards = []
        for v in videos:
            text = (v.get("description") or v.get("title") or "").strip()
            first, _, rest = text.partition("\n")
            when = (datetime.fromtimestamp(v["create_time"], zone).strftime("%d/%m %H:%M")
                    if v.get("create_time") else "")
            cover = (f'<img src="{e(v["cover"])}" alt="" loading="lazy" referrerpolicy="no-referrer">'
                     if v.get("cover") else '<div class="nocover">🎬</div>')
            link = (f'<a href="{e(v["share_url"])}" target="_blank" rel="noopener">'
                    'Voir sur TikTok ↗</a>' if v.get("share_url") else "")
            cards.append(
                f'<div class="card tk">{cover}<div><strong>{e(first or "(sans description)")}'
                f'</strong></div><div class="meta">{e(rest[:140])}</div>'
                f'<div class="tkstats">👁 {compact(v.get("views") or 0)} · ♥ '
                f'{compact(v.get("likes") or 0)} · 💬 {compact(v.get("comments") or 0)} · ↗ '
                f'{compact(v.get("shares") or 0)}</div><div class="meta">{e(when)} · {link}'
                '</div></div>')
        grid = "".join(cards) or '<p class="empty">Aucune vidéo TikTok récupérée pour le moment.</p>'
        body = (f'<nav class="sub">{tabs}</nav>{self._search_panel()}'
                f'<p class="info">{info}</p><main>{grid}</main>')
        self._page(body, "/")

    def _search_panel(self) -> str:
        from .autopilot import load_settings

        s = load_settings(self.state, self.cfg)
        channels = ", ".join(s["channels"]) if s.get("source") == "channels" else ""
        then_field = "" if not self._auto_publish() else (
            '<label>Ensuite <select name="then"><option value="review">À valider ici</option>'
            '<option value="schedule">Programmer automatiquement</option>'
            '<option value="publish">Publier tout de suite</option></select></label>')
        from .claude_usage import short_line

        line = short_line(self.state)
        claude = (f'<span class="meta" style="margin-left:auto;font-weight:400" title="Ce qu’il '
                  f'reste de ton abonnement Claude (détail dans Statistiques)">🤖 Claude : '
                  f'{e(line)}</span>') if line else ""
        return SEARCH.format(channels=e(channels), hours=_options(HOURS, 24), then_field=then_field,
                             claude=claude,
                             disabled=" disabled" if self.app.job.running else "")

    def _auto_publish(self) -> bool:
        """Publication / programmation par ClipTV : seulement une fois l'app validée par
        TikTok. Sinon (par défaut) tu publies toi-même depuis TikTok Studio."""
        return bool(self.state.get_settings().get(AUTO_PUBLISH))

    def _release_scheduled(self) -> None:
        """Mode manuel : les clips programmés reviennent dans « À publier »."""
        for clip in self.state.list("scheduled"):
            self.state.unschedule(clip["clip_id"])

    def _set_auto_publish(self, form: dict[str, str]):
        on = form.get("on") == "1"
        self.state.save_settings({AUTO_PUBLISH: on})
        msg = ("Publication automatique activée : programmation, envoi vers TikTok et pilote "
               "« publier » sont de retour." if on else
               "Publication manuelle : tu publies toi-même depuis TikTok Studio.")
        return self._redirect(msg, to="/accounts")

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
                                            download=e(f"{base}?dl=1"),
                                            filename=e(_download_name(c)))
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
                            '<button type="submit" class="small">↩ Remettre dans « '
                            f'{"À publier" if not self._auto_publish() else "À valider"} »'
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
            player = (f'<div class="player"><video src="{video}" controls preload="metadata" '
                      f'playsinline></video>{self._tiktok_overlay()}</div>')
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
        try:
            moderation = json.loads(c.get("signals") or "{}").get("moderation")
        except ValueError:
            moderation = None
        if moderation and status in ("rendered", "scheduled", "failed"):
            badges += (f'<span class="badge failed" title="{e(moderation)}">⚠️ Risque de '
                       f'modération : {e(moderation[:60])}</span>')
        corner = (self._potential_badge(c) if status in ("rendered", "scheduled", "failed")
                  else "")
        badges = f'<div class="badges">{badges}</div>' if badges else ""
        error = f" · ⚠️ {e(c['error'])}" if c.get("error") else ""
        return CARD.format(player=player, corner=corner,
                           title=e(c["title"]), channel=e(c["channel"]),
                           views=e(c["view_count"]), url=e(c["url"]), error=error,
                           badges=badges, actions=actions)

    def _tiktok_overlay(self) -> str:
        """Interface TikTok simulée (bouton « Aperçu TikTok ») : voir avant de publier si la
        description ou les boutons cachent les sous-titres."""
        from . import stats

        account = self.state.get_settings().get(stats.ACCOUNT) or {}
        name = e(account.get("display_name") or "ton_compte")
        avatar = (f' style="background-image:url(\'{e(account["avatar_url"])}\')"'
                  if account.get("avatar_url") else "")
        icon = ('<svg viewBox="0 0 24 24" fill="#fff">{}</svg>').format
        heart = icon('<path d="M12 21s-7.5-4.6-9.5-9.2C1 8.2 3.3 4.5 7 4.5c2 0 3.6 1.1 5 2.8 '
                     '1.4-1.7 3-2.8 5-2.8 3.7 0 6 3.7 4.5 7.3C19.5 16.4 12 21 12 21z"/>')
        comment = icon('<path d="M12 3C6.5 3 2 6.6 2 11c0 2.4 1.3 4.6 3.4 6L5 21l4.3-2.4c.9.2 '
                       '1.8.3 2.7.3 5.5 0 10-3.6 10-8s-4.5-8-10-8z"/>')
        save = icon('<path d="M6 2h12a1 1 0 0 1 1 1v19l-7-4.5L5 22V3a1 1 0 0 1 1-1z"/>')
        share = icon('<path d="M14 4l8 7.5-8 7.5v-4.5c-6 0-9.5 1.8-12 6 .8-6.5 4-11.5 12-12.5z"/>')
        return (
            '<button type="button" class="ttbtn" onclick="ttToggle(this)">👁 Aperçu TikTok</button>'
            '<div class="ttui" aria-hidden="true"><div class="zone"></div>'
            '<div class="tabs"><b>Pour toi</b></div>'
            f'<div class="side"><div class="av"{avatar}></div><span>{heart}12,4 k</span>'
            f'<span>{comment}318</span><span>{save}1 024</span><span>{share}562</span>'
            '<div class="disc"></div></div>'
            f'<div class="cap"><b>{name}</b><div class="txt"></div>'
            f'<div class="snd">♫ son original - {name}</div></div></div>')

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
        tip = e(f"{p['rarity_label']} · " + " · ".join(p["reasons"]))
        return (f'<details class="pot r-{p["rarity"]}"><summary title="{tip}">'
                f'{p["note"]:.1f}</summary><div class="why"><strong>{e(p["rarity_label"])} · '
                f'{p["note"]:.1f}/10</strong><ul>{reasons}</ul></div></details>')

    # ---------- page Aide ----------
    def _help_page(self):
        from . import help_page

        cfg, settings = self.cfg, self._settings()
        status = {
            "twitch": bool(cfg.twitch_client_id and cfg.twitch_client_secret),
            "tiktok_keys": bool(cfg.tiktok_client_key and cfg.tiktok_client_secret
                                and cfg.tiktok_redirect_uri),
            "tiktok_connected": cfg.tiktok_token_path.exists(),
            "claude": self._claude_ok(),
            "autopilot": bool(settings.get("enabled")),
        }
        from .captions import last_error
        if status["claude"] and last_error:  # clé présente mais Claude refuse
            status["claude"], status["claude_error"] = False, last_error
        self._page(help_page.render(status), "/help", narrow=True)

    @staticmethod
    def _claude_ok() -> bool:
        from . import llm

        return llm.available()

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
        summary["claude"] = self.state.claude_usage(since)
        from .claude_usage import summary as claude_limits

        summary["claude_limits"] = claude_limits(self.state)
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
        auto = self._auto_publish()
        if auto:
            queued = self.state.count("scheduled")
            lines.append(f"Clips programmés : {queued} / {max_queue(s)} max · publiés en 24 h : "
                         f"{self.state.count_since('published', time.time() - 86400)}")
        else:
            lines.append(f"Clips prêts à publier : {self.state.count('rendered')} / "
                         f"{max_queue(s)} max (au-delà, les recherches attendent) · publiés en "
                         f"24 h : {self.state.count_since('published', time.time() - 86400)}")
        status = "".join(f'<div class="info">{line}</div>' for line in lines)

        checks = "".join(
            f'<label class="check"><input type="checkbox" name="platforms" value="{p}"'
            f'{" checked" if p in s["platforms"] else ""}> {PLATFORM_NAMES[p]}</label>'
            for p in PLATFORMS)
        from .audience import heatmap

        audience = heatmap(s["post_slots"] if auto else [], self.state.videos(0),
                           self.cfg.timezone, apply_button=auto)
        then = _options([("schedule", "Programmer sur les créneaux"),
                         ("publish", "Publier dès que c'est prêt"),
                         ("manual", "Le garder : je publie moi-même")], s["then"])
        if auto:
            intro = ("Il repère tout seul les temps forts des streams les plus regardés, les "
                     "monte en vertical avec sous-titres, écrit la légende, puis les publie aux "
                     "heures choisies. Il surveille aussi les lives et clippe chaque moment fort "
                     "du chat.")
            then_field = (f'<label>Quand un clip est prêt <select name="then">{then}</select>'
                          '</label>')
            publish_fields = f"""<label class="full">Heures de publication (heure de {e(self.cfg.timezone)})
    <input name="post_slots" value="{e(', '.join(s['post_slots']))}" placeholder="12:30, 18:00, 21:00"></label>
  <label>Clips programmés max (0 = auto) <input name="max_queue" type="number" min="0" value="{e(s['max_queue'])}"></label>
  <div class="full"><div class="info">Publier sur</div><div class="row">{checks}</div></div>"""
        else:
            intro = ("Il repère tout seul les temps forts des streams les plus regardés, les "
                     "monte en vertical avec sous-titres et écrit la légende. Les clips "
                     "t'attendent dans <a href=\"/\">Clips → À publier</a> : 🚀 Préparer, "
                     "puis tu publies sur TikTok Studio. Il surveille aussi les lives et "
                     "clippe chaque moment fort du chat.")
            then_field = ""
            publish_fields = (f'<label>Clips prêts max (0 = auto) <input name="max_queue" '
                              f'type="number" min="0" value="{e(s["max_queue"])}"></label>')
        body = f"""
<div class="panel"><h2>{head}</h2>
<p class="info">{intro}</p>
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
  {then_field}
  <label class="full">Cadrage des vidéos <select name="layout">{_options(LAYOUTS, s.get('layout', 'auto'))}</select></label>
  <label>Sensibilité des lives <select name="ratio">{_options(RATIOS, float(s['ratio']))}</select></label>
  {publish_fields}
  <label class="check full"><input type="checkbox" name="subtitles" value="1"{" checked" if s.get("subtitles", True) else ""}>
    Ajouter des sous-titres animés (décoche si tes streamers ont déjà les leurs)</label>
  <label class="check full"><input type="checkbox" name="ai_caption" value="1"{" checked" if s["ai_caption"] else ""}>
    Légendes et hashtags écrits par Claude</label>
  <label class="check full"><input type="checkbox" name="jury" value="1"{" checked" if s.get("jury", True) else ""}>
    Radar : Claude regarde les clips présélectionnés (images + paroles) et écarte ceux qui ne
    marchent pas sans contexte, les temps morts et les clips sans vraie réaction</label>
  <label class="check full"><input type="checkbox" name="smart_timing" value="1"{" checked" if s.get("smart_timing", True) else ""}>
    Horaires intelligents : cherche 2× plus souvent le soir (18 h - 2 h, quand les gros lives
    tournent) et 3× moins la nuit et le matin</label>
</div>
<div class="row" style="margin-top:14px"><button type="submit">Enregistrer</button></div>
</form>
{self._handles_panel()}"""
        self._page(body, "/auto", narrow=True)

    def _handles_panel(self) -> str:
        from .socials import as_lines

        lines = as_lines(self.state)
        return f"""<details class="panel"><summary>🏷️ Comptes TikTok des streamers</summary>
<p class="info">ClipTV ajoute le @ TikTok du streamer dans la description (il trouve le compte
tout seul sur la chaîne Twitch quand le streamer l'affiche). Corrige ou ajoute un compte : une
ligne par streamer, « nom_twitch @compte_tiktok » ; « nom_twitch - » pour ne jamais le
mentionner.</p>
<form method="post" action="/handles">
  <textarea name="handles" rows="6" placeholder="nico_la @nicolatiktok&#10;kamet0 @kameto"
            autocapitalize="none" autocorrect="off" spellcheck="false">{e(lines)}</textarea>
  <div class="row" style="margin-top:10px"><button type="submit" class="small">Enregistrer</button></div>
</form></details>"""

    def _save_handles(self, form: dict[str, str]):
        from .socials import save_manual

        n = save_manual(self.state, form.get("handles", ""))
        return self._redirect(f"Comptes TikTok enregistrés ({n} streamer(s)).", to="/auto")

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
                if keys and not self._auto_publish():
                    detail = (("Compte connecté : sert aux statistiques et à repérer les clips "
                               "déjà publiés." if ok else
                               "Connecte-le pour les statistiques et pour repérer les clips "
                               "déjà publiés (la publication se fait depuis TikTok Studio).")
                              + detail[detail.find("<br>"):] if "<br>" in detail else
                              ("Compte connecté : sert aux statistiques et à repérer les clips "
                               "déjà publiés." if ok else
                               "Connecte-le pour les statistiques et pour repérer les clips "
                               "déjà publiés."))
                elif keys:
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
                if manual and not ok and not stats_on and self._auto_publish():
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

        from . import llm

        ok, how = llm.describe()
        row("Claude (Radar et légendes)", "✅" if ok else "—", e(how))

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
{self._publish_mode_panel()}
<div class="panel"><h2>Diagnostic</h2>
<p class="info">Teste ffmpeg, la police, et chaque connexion avec un vrai appel aux API.</p>
{checks}
<form method="post" action="/accounts/check" class="row" style="margin-top:12px">
<button>Tout vérifier</button></form></div>"""
        waiting = any(p.state == "pending" for p in self.app.pending.values())
        self._page(body, "/accounts", narrow=True, refresh=5 if waiting else 0)

    def _publish_mode_panel(self) -> str:
        """Interrupteur unique : publication par ClipTV (app validée) ou à la main."""
        if self._auto_publish():
            return ('<details class="panel"><summary>📤 Publication automatique : activée'
                    '</summary><p class="info">ClipTV programme et envoie les vidéos sur TikTok. '
                    'Si TikTok n\'a pas (encore) validé ton app, repasse en manuel.</p>'
                    '<form method="post" action="/publish-mode"><button name="on" value="0" '
                    'class="rej">Revenir à la publication manuelle (TikTok Studio)</button>'
                    '</form></details>')
        return ('<details class="panel"><summary>📤 Publication automatique : désactivée '
                '(tu publies depuis TikTok Studio)</summary><p class="info">À activer '
                '<strong>seulement quand TikTok aura validé ton app</strong> : ClipTV pourra '
                'alors programmer et publier les vidéos lui-même (créneaux, envoi, choix de la '
                'visibilité).</p><form method="post" action="/publish-mode"><button name="on" '
                'value="1">Activer la publication automatique</button></form></details>')

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
<p class="info">À créer une fois sur dev.twitch.tv et developers.tiktok.com (voir le
README). Elles sont gardées sur ce PC uniquement.</p>
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
            name = _download_name(clip) or path.name
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
            "/publish-mode": lambda: self._set_auto_publish(one),
            "/connect/twitch": lambda: self._connect_device("twitch"),
            "/connect/youtube": lambda: self._connect_device("youtube"),
            "/connect/instagram": lambda: self._connect_instagram(one),
            "/connect/tiktok-code": lambda: self._tiktok_code(one),
            "/keys": lambda: self._save_keys(one),
            "/password": lambda: self._save_password(one),
            "/handles": lambda: self._save_handles(one),
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
            return self._redirect("Clip marqué comme publié ✔")
        if action == "unschedule":
            ok = self.state.unschedule(clip_id)
            return self._redirect("Programmation annulée." if ok else "Clip déjà parti.",
                                  err=not ok, tab="rendered")
        if action == "reject":
            if clip["status"] not in ("rendered", "failed"):
                return self._redirect("Ce clip a déjà changé d'état (publié, programmé ou rejeté) → actualise la page.", err=True)
            self.state.record(clip_id, clip["channel"], "rejected", caption=caption)
            self.state.trim_rejected(self.cfg.downloads_dir)
            return self._redirect("Clip rejeté.")
        if action == "restore":
            if clip["status"] != "rejected" or not clip.get("output_path") \
                    or not Path(clip["output_path"]).exists():
                return self._redirect("Impossible de récupérer ce clip : sa vidéo a été "
                                      "supprimée → relance une recherche.", err=True,
                                      tab="rejected")
            self.state.record(clip_id, clip["channel"], "rendered")
            where = "À valider" if self._auto_publish() else "À publier"
            return self._redirect(f"Clip récupéré : il est de nouveau dans « {where} ».",
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
        then = form.get("then", "review") if self._auto_publish() else "review"
        from .autopilot import load_settings

        layout = load_settings(self.state, self.cfg).get("layout", "auto")
        settings = load_settings(self.state, self.cfg)
        opts = Options(**{**self.opts.__dict__, "ai_caption": form.get("ai") == "1",
                          "jury": bool(settings.get("jury", True)),
                          "layout": layout,
                          "subtitles": load_settings(self.state, self.cfg).get("subtitles", True),
                          "publish": then == "publish", "schedule": then == "schedule"})
        job = self.app.job
        first = channels[0] if channels else "temps forts du moment"
        if not job.start(f"Recherche en cours : {first}…", run_search, job, self.cfg,
                         self.state, opts, channels, hours, top):
            return self._redirect("Une recherche est déjà en cours → attends la fin, ou clique sur ⏹ en haut à droite.", err=True)
        return self._redirect_to("/")  # la progression s'affiche en haut à droite

    def _save_auto(self, form: dict[str, list[str]]):
        one = {k: v[0].strip() for k, v in form.items()}
        channels = _split_channels(one.get("channels", ""))
        live = _split_channels(one.get("live_channels", ""))
        bad = [c for c in channels + live if not CHANNEL_RE.fullmatch(c)]
        if bad:
            return self._redirect(f"Nom de chaîne invalide : « {bad[0]} » → écris le nom tel qu'il apparaît dans l'adresse twitch.tv/nom.", err=True, to="/auto")
        from .autopilot import load_settings as _load

        current = _load(self.state, self.cfg)
        auto = self._auto_publish()
        if not auto:  # champs cachés : on garde les valeurs actuelles
            one.setdefault("post_slots", ", ".join(current["post_slots"]))
            one.setdefault("then", current.get("then", "schedule"))
            if not form.get("platforms"):
                form["platforms"] = list(current["platforms"])
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
                "jury": one.get("jury") == "1",
                "subtitles": one.get("subtitles") == "1",
                "smart_timing": one.get("smart_timing") == "1",
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
        return self._redirect_to("/auto")

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
    from . import llm

    from . import claude_usage, progress

    # suivi des tokens et de ce qu'il reste de l'abonnement (page Statistiques)
    llm.recorder = lambda *a: claude_usage.record(app.state, *a)
    progress.on_tokens = lambda n: claude_usage.search_done(app.state, n)
    return ThreadingHTTPServer((host, port), partial(Handler, app=app))
