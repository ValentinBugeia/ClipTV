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
  .viz { --bar:#9147ff; --grid:#2a2a2d; --t1:#efeff1; --t2:#adadb8; }
  .filters { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:16px }
  .chip { color:var(--t2); background:var(--card); border-radius:999px; padding:6px 12px; text-decoration:none; font-size:14px }
  .chip.on { color:#fff; background:#5c16c5 }
  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:16px }
  .kpi { background:var(--card); border-radius:12px; padding:12px 14px }
  .kpi .l { color:var(--t2); font-size:13px }
  .kpi .v { font-size:26px; font-weight:600; margin-top:2px }
  .kpi .s { color:var(--t2); font-size:12px }
  .tips { margin:8px 0 14px; padding-left:18px; line-height:1.7 }
  .tips .tipk { color:var(--t1); font-weight:600 }
  .charts { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; margin-bottom:16px }
  figure.chart { margin:0; background:var(--card); border-radius:12px; padding:14px }
  figure.chart figcaption { font-weight:600; margin-bottom:2px }
  figure.chart .sub { color:var(--t2); font-size:12px; margin-bottom:10px }
  .bars { display:grid; grid-template-columns:minmax(80px,32%) 1fr; gap:6px 10px; align-items:center }
  .bars .name { color:var(--t2); font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
  .bars .track { position:relative; height:22px; display:flex; align-items:center; gap:6px; cursor:default;
                 border-left:1px solid var(--grid) }
  .bars .fill { height:16px; background:var(--bar); border-radius:0 4px 4px 0; min-width:2px }
  .bars .track:hover .fill, .bars .track:focus .fill { filter:brightness(1.25) }
  .bars .val { color:var(--t1); font-size:12px; font-variant-numeric:tabular-nums; white-space:nowrap }
  #tip { position:fixed; pointer-events:none; background:#000; border:1px solid #333; border-radius:8px;
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
  .panel .kpi { background:#0e0e10 }
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

    a = summary["activity"]
    made = sum(a.get(k, 0) for k in ("rendered", "scheduled", "publishing", "published"))
    parts.append('<div class="panel"><h2>Activité de cliptv sur la période</h2><div class="kpis">'
                 + kpi("Clips montés", compact(made))
                 + kpi("Publiés", compact(a.get("published", 0)))
                 + kpi("Programmés", compact(a.get("scheduled", 0)))
                 + kpi("Rejetés", compact(a.get("rejected", 0)))
                 + kpi("En erreur", compact(a.get("failed", 0)))
                 + "</div></div>")
    parts.append("</div>" + SCRIPT)
    return "".join(parts)
