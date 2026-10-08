"""Page « Statistiques » de l'interface web (HTML généré côté serveur, sans dépendance).

Formes choisies selon la donnée : chiffres clés en tuiles, comparaisons en barres
horizontales d'une seule teinte (valeur au bout de la barre, info-bulle au survol,
tableau équivalent), classement des vidéos en tableau triable.
"""

from __future__ import annotations

import html
import time
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

e = lambda v: html.escape(str(v if v is not None else ""))  # noqa: E731

PERIODS = [(7, "7 jours"), (30, "30 jours"), (90, "90 jours"), (0, "Tout")]
SORTS = [("views", "Vues"), ("likes", "J'aime"), ("engagement", "Engagement"),
         ("recent", "Plus récentes")]

STYLE = """<style>
  .viz { --bar:linear-gradient(90deg,#9b5cff,#ff4fa3); --grid:var(--line); --t1:var(--fg); --t2:var(--muted); }
  .filters { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:16px }
  .chip { color:var(--t2); background:var(--card); border:1px solid var(--line); border-radius:999px; padding:7px 14px; text-decoration:none; font-size:14px }
  .chip.on { color:#fff; background:var(--grad); border-color:transparent }
  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:16px }
  .kpi { background:linear-gradient(180deg,rgba(155,92,255,.08),transparent),var(--card); border:1px solid var(--line); border-radius:16px; padding:16px 18px }
  .kpi .l { color:var(--t2); font-size:13px }
  .kpi .v { font-size:28px; font-weight:800; letter-spacing:-.02em; margin-top:4px; font-variant-numeric:tabular-nums }
  .kpi .s { color:var(--t2); font-size:12px }
  .tips { margin:8px 0 14px; padding-left:18px; line-height:1.7 }
  .tips .tipk { color:var(--t1); font-weight:600 }
  .charts { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; margin-bottom:16px }
  figure.chart { margin:0; background:var(--card); border:1px solid var(--line); border-radius:16px; padding:18px }
  figure.chart figcaption { font-weight:600; margin-bottom:2px }
  figure.chart .sub { color:var(--t2); font-size:12px; margin-bottom:10px }
  .bars { display:grid; grid-template-columns:minmax(80px,32%) 1fr; gap:6px 10px; align-items:center }
  .bars .name { color:var(--t2); font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
  .bars .track { position:relative; height:22px; display:flex; align-items:center; gap:6px; cursor:default;
                 border-left:1px solid var(--grid) }
  .bars .fill { height:14px; background:var(--bar); border-radius:0 7px 7px 0; min-width:3px }
  .bars .track:hover .fill, .bars .track:focus .fill { filter:brightness(1.25) }
  .bars .val { color:var(--t1); font-size:12px; font-variant-numeric:tabular-nums; white-space:nowrap }
  #tip { position:fixed; pointer-events:none; background:rgba(26,26,35,.97); border:1px solid var(--line2); border-radius:10px;
         padding:6px 10px; font-size:13px; display:none; z-index:10 }
  #tip b { display:block; font-size:15px }
  .vtable { width:100%; border-collapse:collapse; font-size:14px }
  .vtable th { text-align:left; color:var(--t2); font-weight:500; padding:6px; border-bottom:1px solid var(--grid) }
  .vtable td { padding:6px; border-bottom:1px solid var(--grid); vertical-align:middle }
  .vtable td.n, .vtable th.n { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap }
  .vtable img { width:36px; height:64px; object-fit:cover; border-radius:4px; background:#000 }
  .tablewrap { overflow-x:auto }
  details.tv summary { color:var(--t2); font-size:12px; cursor:pointer; margin-top:8px }
  .vtable td.title { min-width:120px }
  .panel .kpi { background:rgba(0,0,0,.25) }
  .lims { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:14px; margin:6px 0 10px }
  .lim { background:rgba(0,0,0,.25); border:1px solid var(--line); border-radius:14px; padding:14px 16px }
  .limtop { display:flex; justify-content:space-between; align-items:baseline; gap:8px }
  .limv { font-size:22px; font-weight:800 }
  .limbar { height:8px; border-radius:4px; background:rgba(255,255,255,.08); margin:10px 0 8px; overflow:hidden }
  .limbar i { display:block; height:100%; border-radius:4px }
  @media (max-width:600px) {
    .vtable .opt { display:none }
    .vtable img { width:27px; height:48px }
    .kpi .v { font-size:22px }
  }
</style>"""

SCRIPT = """<div id="tip" role="tooltip"></div>
<script>
// info-bulle des barres : valeur en premier, libellé ensuite (textContent : données non fiables)
(function () {
  const tip = document.getElementById('tip');
  function show(el, x, y) {
    tip.replaceChildren();
    const b = document.createElement('b'); b.textContent = el.dataset.value;
    const s = document.createElement('span'); s.textContent = el.dataset.label;
    tip.append(b, s); tip.style.display = 'block';
    tip.style.left = Math.min(x + 12, innerWidth - tip.offsetWidth - 8) + 'px';
    tip.style.top = (y + 12) + 'px';
  }
  document.querySelectorAll('.bars .track').forEach(el => {
    el.addEventListener('pointermove', ev => show(el, ev.clientX, ev.clientY));
    el.addEventListener('pointerleave', () => tip.style.display = 'none');
    el.addEventListener('focus', () => { const r = el.getBoundingClientRect(); show(el, r.left, r.bottom); });
    el.addEventListener('blur', () => tip.style.display = 'none');
  });
})();
</script>"""


def compact(n: float) -> str:
    """1 284 · 12,9 k · 4,2 M (format français)."""
    n = float(n or 0)
    if abs(n) >= 1e6:
        return f"{n / 1e6:.1f} M".replace(".", ",")
    if abs(n) >= 1e4:
        return f"{n / 1e3:.1f} k".replace(".", ",")
    return f"{n:,.0f}".replace(",", " ")


def pct(x: float) -> str:
    return f"{x * 100:.1f} %".replace(".", ",")


def kpi(label: str, value: str, sub: str = "") -> str:
    sub = f'<div class="s">{e(sub)}</div>' if sub else ""
    return f'<div class="kpi"><div class="l">{e(label)}</div><div class="v">{e(value)}</div>{sub}</div>'


def bar_chart(title: str, sub: str, rows: list[tuple[str, float, int]], empty: str, *,
              unit: str = "vues en moyenne", head: str = "Vues moy.") -> str:
    """Barres horizontales, une seule teinte (comparaison de grandeurs)."""
    if not rows:
        return (f'<figure class="chart"><figcaption>{e(title)}</figcaption>'
                f'<div class="sub">{e(empty)}</div></figure>')
    top = max(r[1] for r in rows) or 1
    bars = "".join(
        f'<div class="name" title="{e(name)}">{e(name)}</div>'
        f'<div class="track" tabindex="0" data-label="{e(name)} · {n} vidéo(s)" '
        f'data-value="{e(compact(val))} {e(unit)}">'
        f'<div class="fill" style="width:{max(val / top * 82, 0.5):.1f}%"></div>'
        f'<span class="val">{e(compact(val))}</span></div>'
        for name, val, n in rows)
    table = "".join(f"<tr><td>{e(name)}</td><td class='n'>{e(compact(val))}</td>"
                    f"<td class='n'>{n}</td></tr>" for name, val, n in rows)
    return (f'<figure class="chart"><figcaption>{e(title)}</figcaption>'
            f'<div class="sub">{e(sub)}</div><div class="bars">{bars}</div>'
            f'<details class="tv"><summary>Voir le tableau</summary><table class="vtable">'
            f'<tr><th>{e(title.split(" par ")[-1].capitalize())}</th><th class="n">{e(head)}</th>'
            f'<th class="n">Vidéos</th></tr>{table}</table></details></figure>')


def insights_panel(videos: list[dict], tz: str) -> str:
    """« Ce qui marche sur ton compte » : conseils + vues médianes par durée, jour,
    ambiance, streamer et format de légende."""
    from . import insights

    data = insights.analyse(videos, tz)
    head = ('<div class="panel"><h2>🧠 Ce qui marche sur ton compte</h2>'
            '<p class="info">Vues <strong>médianes</strong> (une vidéo virale isolée ne fausse '
            f'pas le résultat) · ta médiane : <strong>{e(compact(data["overall"]))}</strong> '
            f'vues sur {data["count"]} vidéo(s).</p>')
    if data["count"] < insights.MIN_VIDEOS:
        return (head + f'<p class="info">Il faut au moins {insights.MIN_VIDEOS} vidéos sur la '
                'période pour tirer des conclusions : choisis une période plus longue ou '
                'reviens après quelques publications.</p></div>')
    if data["tips"]:
        items = "".join(
            f'<li><span class="tipk">{"▲" if t["good"] else "▼"} {e(t["dim"])} · '
            f'{e(t["name"])}</span> ×{t["ratio"]:.1f} ta médiane ({t["n"]} vidéos) → '
            f'{e(t["advice"])}</li>' for t in data["tips"])
        head += f'<ul class="tips">{items}</ul>'
    else:
        head += ('<p class="info">Pas encore d\'écart net : tes vidéos font à peu près '
                 'toutes pareil. Continue à varier, les tendances apparaîtront.</p>')
    g = data["groups"]
    opts = dict(unit="vues (médiane)", head="Vues méd.")
    empty = "Pas assez de vidéos."
    charts = "".join([
        bar_chart("Vues par durée", "Durée de la vidéo publiée", g["duration"], empty, **opts),
        bar_chart("Vues par jour", "Jour de publication", g["weekday"], empty, **opts),
        bar_chart("Vues par ambiance", "D'après l'emoji de l'accroche", g["mood"], empty, **opts),
        bar_chart("Vues par streamer", "D'après le lien twitch.tv de la légende",
                  g["streamer"][:8], empty, **opts),
        bar_chart("Vues par légende", "Question en fin de légende ou non", g["question"],
                  empty, **opts),
    ])
    return head + f'<div class="charts">{charts}</div></div>'


def videos_table(videos: list[dict], sort: str, tz: str, base_q: dict) -> str:
    key = {"likes": lambda v: v["likes"], "engagement": lambda v: v["engagement"],
           "recent": lambda v: v["create_time"]}.get(sort, lambda v: v["views"])
    videos = sorted(videos, key=key, reverse=True)[:50]
    zone = ZoneInfo(tz)
    sorts = " ".join(
        f'<a class="chip{" on" if s == sort else ""}" '
        f'href="/stats?{urllib.parse.urlencode({**base_q, "sort": s})}">{label}</a>'
        for s, label in SORTS)
    rows = []
    for i, v in enumerate(videos, 1):
        title = (v["description"] or v["title"] or "(sans titre)").split("\n")[0][:90]
        cover = f'<img src="{e(v["cover"])}" alt="" loading="lazy">' if v["cover"] else ""
        when = datetime.fromtimestamp(v["create_time"], zone).strftime("%d/%m %Hh") \
            if v["create_time"] else ""
        origin = e(v["channel"] or "—") + (f' · {e(v["category"])}' if v["category"] else "")
        link = (f'<a href="{e(v["share_url"])}" target="_blank" rel="noopener">{e(title)}</a>'
                if v["share_url"] else e(title))
        rows.append(
            f"<tr><td class='n'>{i}</td><td>{cover}</td><td class='title'>{link}"
            f"<div class='meta'>{origin}</div></td><td class='n opt'>{e(when)}</td>"
            f"<td class='n'>{e(compact(v['views']))}</td><td class='n'>{e(compact(v['likes']))}</td>"
            f"<td class='n opt'>{e(compact(v['comments']))}</td>"
            f"<td class='n opt'>{e(compact(v['shares']))}</td>"
            f"<td class='n'>{e(pct(v['engagement']))}</td></tr>")
    body = "".join(rows) or "<tr><td colspan='9' class='meta'>Aucune vidéo sur la période.</td></tr>"
    return (f'<div class="panel"><h2>Meilleures vidéos TikTok</h2>'
            f'<div class="filters">{sorts}</div><div class="tablewrap"><table class="vtable">'
            f"<tr><th class='n'>#</th><th></th><th>Vidéo</th><th class='n opt'>Publiée</th>"
            f"<th class='n'>Vues</th><th class='n'>J'aime</th><th class='n opt'>Comm.</th>"
            f"<th class='n opt'>Partages</th><th class='n'>Engag.</th></tr>{body}"
            f"</table></div></div>")


def render(summary: dict, *, days: int, sort: str, tz: str) -> str:
    base_q = {"p": days}
    periods = " ".join(
        f'<a class="chip{" on" if d == days else ""}" '
        f'href="/stats?{urllib.parse.urlencode({"p": d, "sort": sort})}">{label}</a>'
        for d, label in PERIODS)
    updated = summary["updated_at"]
    ago = f"mis à jour il y a {max(int((time.time() - updated) / 60), 0)} min" if updated else ""
    filters = (f'<div class="filters">{periods}<form method="post" action="/stats/refresh" '
               f'style="display:contents"><button class="small rej">↻ Actualiser</button></form>'
               f'<span class="meta">{e(ago)}</span></div>')

    parts = [STYLE, '<div class="viz">', filters]
    if not summary["enabled"]:
        parts.append(
            '<div class="panel"><h2>Activer les statistiques TikTok</h2><p class="info">'
            "Pour voir les vues, j'aime, commentaires et partages de tes vidéos :</p><ol class='info'>"
            "<li>sur <b>developers.tiktok.com</b>, dans ton app (Sandbox), ajoute le produit "
            "<b>Display API</b> et les scopes <code>user.info.stats</code> et "
            "<code>video.list</code>, puis <b>Save</b> ;</li>"
            "<li>clique sur le bouton ci-dessous ;</li>"
            "<li>page <b>Comptes</b>, <b>reconnecte TikTok</b> pour accorder ces autorisations."
            "</li></ol><form method='post' action='/stats/enable' class='row'>"
            "<button>Activer les statistiques</button></form></div>")
    if summary["error"]:
        parts.append(f'<div class="flash err">⚠️ {e(summary["error"])} '
                     '<a href="/accounts">Aller dans Comptes</a></div>')

    t, acc = summary["totals"], summary["account"]
    tiles = [kpi("Vues", compact(t["views"]), f'{t["videos"]} vidéo(s) sur la période'),
             kpi("J'aime", compact(t["likes"])),
             kpi("Commentaires", compact(t["comments"])),
             kpi("Partages", compact(t["shares"])),
             kpi("Engagement", pct(t["engagement"]), "(j'aime + comm. + partages) / vues")]
    if acc.get("follower_count") is not None:
        tiles.append(kpi("Abonnés", compact(acc["follower_count"]),
                         f'{compact(acc.get("likes_count", 0))} j\'aime au total'))
    parts.append(f'<div class="kpis">{"".join(tiles)}</div>')

    empty = "Pas encore de vidéo reliée à un clip cliptv sur la période."
    parts.append('<div class="charts">' + "".join([
        bar_chart("Vues moyennes par streamer", "Quels streamers marchent le mieux",
                  summary["by_channel"], empty),
        bar_chart("Vues moyennes par catégorie", "Jeux et catégories Twitch",
                  summary["by_category"], empty),
        bar_chart("Vues moyennes par heure de publication",
                  "Pour choisir tes créneaux (heure locale)", summary["by_hour"],
                  "Pas encore de vidéo sur la période."),
    ]) + "</div>")
    parts.append(insights_panel(summary["videos"], tz))
    parts.append(videos_table(summary["videos"], sort, tz, base_q))
    from .audience import heatmap

    parts.append(heatmap(summary.get("slots", []), summary["videos"], tz, apply_button=False))

    parts.append(claude_panel(summary.get("claude") or [], days, summary.get("claude_limits"),
                              tz))
    parts.append("</div>" + SCRIPT)
    return "".join(parts)


PURPOSES = {"radar": "Radar (tri des clips)", "juré": "Radar (tri des clips)", "légende": "Légendes",
            "test": "Test de connexion", "autre": "Autre"}


def limits_html(limits: dict | None, tz: str) -> str:
    """Ce qu'il reste de chaque limite de l'abonnement, avec une barre."""
    from .schedule import format_when

    windows = (limits or {}).get("windows") or []
    if not windows:
        return ('<p class="info">Le pourcentage restant de ton abonnement s\'affichera après le '
                "prochain appel à Claude (une recherche suffit).</p>")
    rows = []
    for w in windows:
        left = 1 - w["used"]
        color = "#3ddc84" if left > 0.4 else "#ffb547" if left > 0.15 else "#ff6b7a"
        est = (f"≈ <b>{w['searches_left']}</b> recherche{'s' if w['searches_left'] > 1 else ''} "
               "possibles" if w["searches_left"] is not None else
               "estimation des recherches possibles après quelques recherches")
        resets = format_when(w["resets"], tz) if w.get("resets") else ""
        rows.append(
            f'<div class="lim"><div class="limtop"><b>{e(w["label"])}</b>'
            f'<span class="limv" style="color:{color}">{round(left * 100)} % restant</span></div>'
            f'<div class="limbar"><i style="width:{w["used"] * 100:.0f}%;background:{color}"></i></div>'
            f'<div class="meta">{est}{" · réinitialisation " + e(resets) if resets else ""}</div></div>')
    ago = ""
    if limits.get("at"):
        ago = f" · relevé il y a {max(int((time.time() - limits['at']) / 60), 0)} min"
    per = limits.get("per_search_tokens")
    per_txt = f" Une recherche utilise ≈ {compact(per)} tokens." if per else ""
    return (f'<div class="lims">{"".join(rows)}</div><p class="info">Relevé fait par Claude Code '
            f"à chaque appel{ago}.{per_txt} Ton utilisation de Claude ailleurs (claude.ai, "
            "Claude Code) compte aussi dans ces limites.</p>")


def claude_panel(rows: list[dict], days: int, limits: dict | None = None,
                 tz: str = "Europe/Paris") -> str:
    """Ce qu'il reste de l'abonnement, puis les tokens utilisés sur la période."""
    period = f"sur les {days} derniers jours" if days else "depuis le début"
    head = f'<div class="panel"><h2>🤖 Ton abonnement Claude</h2>{limits_html(limits, tz)}'
    if not rows:
        return head + f'<p class="info">Aucun appel à Claude {e(period)}.</p></div>'

    total_in = sum(r["tokens_in"] for r in rows)
    total_out = sum(r["tokens_out"] for r in rows)
    calls = sum(r["calls"] for r in rows)
    cost = sum(r["cost"] for r in rows)
    tiles = (kpi("Tokens au total", compact(total_in + total_out), period)
             + kpi("Lus", compact(total_in), "images, paroles, consignes")
             + kpi("Écrits", compact(total_out), "notes, légendes")
             + kpi("Appels", compact(calls), f"≈ {compact((total_in + total_out) / calls)} tokens / appel")
             + kpi("Équivalent API", f"{cost:.2f} $".replace(".", ","),
                   "indicatif : inclus dans ton abonnement"))
    lines = "".join(
        f'<tr><td>{e(PURPOSES.get(r["purpose"], r["purpose"]))}</td>'
        f'<td class="n">{r["calls"]}</td><td class="n">{compact(r["tokens_in"])}</td>'
        f'<td class="n">{compact(r["tokens_out"])}</td>'
        f'<td class="n">{compact((r["tokens_in"] + r["tokens_out"]) / max(r["calls"], 1))}</td></tr>'
        for r in rows)
    return (head + f'<details class="tv"><summary>Détail des tokens {e(period)}</summary>'
            f'<div class="kpis" style="margin-top:10px">{tiles}</div><div class="tablewrap"><table class="vtable">'
            '<tr><th>Usage</th><th class="n">Appels</th><th class="n">Lus</th>'
            '<th class="n">Écrits</th><th class="n">Moy. / appel</th></tr>'
            f"{lines}</table></div></details></div>")
