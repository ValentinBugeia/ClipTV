"""Affluence TikTok par jour et par heure, pour choisir les créneaux de publication.

TikTok ne fournit pas l'activité de l'audience heure par heure dans son API (seulement
dans l'app, onglet Analytics → Abonnés). On combine donc :

- une **estimation générale** pour un public francophone (habitudes courantes : pause
  de midi, sortie des cours / du travail, soirée, nuit, week-end, mercredi après-midi) ;
- les **vraies données du compte** dès qu'il y a assez de vidéos publiées : vues
  moyennes selon l'heure de publication (statistiques TikTok de l'app).
"""

from __future__ import annotations

import html
from datetime import datetime
from statistics import mean
from zoneinfo import ZoneInfo

DAYS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
LEVELS = {0: "faible", 1: "moyenne", 2: "forte"}
COLORS = {0: "#184f95", 1: "#3987e5", 2: "#9ec5f4"}  # rampe ordinale validée (fond sombre)
MIN_VIDEOS = 8  # vidéos nécessaires avant de se fier aux données du compte

# estimation générale, heure par heure (0 = faible, 1 = moyenne, 2 = forte)
_WEEKDAY = [1, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 1, 2, 2, 1, 1, 1, 1, 2, 2, 2, 2, 2, 1]
_WEDNESDAY = _WEEKDAY[:14] + [2, 2, 2, 1] + _WEEKDAY[18:]   # après-midi libre au collège
_FRIDAY = _WEEKDAY[:23] + [2]                               # on se couche plus tard
_SATURDAY = [2, 1, 1, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2]
_SUNDAY = [2, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 1, 1]
GENERAL = [_WEEKDAY, _WEEKDAY, _WEDNESDAY, _WEEKDAY, _FRIDAY, _SATURDAY, _SUNDAY]


def general_level(day: int, hour: int) -> int:
    return GENERAL[day][hour]


def personal_hours(videos: list[dict], tz: str) -> dict[int, tuple[float, int]]:
    """{heure: (vues moyennes, nb de vidéos)} d'après les vidéos TikTok du compte."""
    zone = ZoneInfo(tz)
    buckets: dict[int, list[int]] = {}
    for v in videos:
        if v.get("create_time"):
            h = datetime.fromtimestamp(v["create_time"], zone).hour
            buckets.setdefault(h, []).append(v.get("views") or 0)
    return {h: (mean(vs), len(vs)) for h, vs in buckets.items()}


def personal_levels(hours: dict[int, tuple[float, int]]) -> dict[int, int]:
    """Niveau par heure selon les vues moyennes (tiers bas / milieu / haut)."""
    if sum(n for _, n in hours.values()) < MIN_VIDEOS or len(hours) < 3:
        return {}
    ranked = sorted(hours, key=lambda h: hours[h][0])
    third = len(ranked) / 3
    return {h: (0 if i < third else 1 if i < 2 * third else 2) for i, h in enumerate(ranked)}


def recommended_slots(personal: dict[int, tuple[float, int]] | None = None, n: int = 3,
                      gap: int = 3) -> tuple[list[str], str]:
    """Créneaux conseillés (HH:MM) et leur source, espacés d'au moins ``gap`` heures."""
    if personal and personal_levels(personal):
        score = {h: v for h, (v, _) in personal.items()}
        source = "tes vidéos"
    else:
        score = {h: sum(GENERAL[d][h] for d in range(7)) for h in range(24)}
        source = "l'estimation générale"
    chosen: list[int] = []
    for h in sorted(score, key=lambda h: (-score[h], h)):
        if all(min(abs(h - c), 24 - abs(h - c)) >= gap for c in chosen):
            chosen.append(h)
        if len(chosen) == n:
            break
    return [f"{h:02d}:00" for h in sorted(chosen)], source


def _slot_hours(slots: list[str]) -> set[int]:
    hours = set()
    for s in slots:
        try:
            hours.add(int(s.split(":")[0]))
        except ValueError:
            pass
    return hours


STYLE = """<style>
  .aud { overflow-x:auto }
  .aud .grid { display:grid; grid-template-columns:34px repeat(24, minmax(11px, 1fr)); gap:2px;
               min-width:330px; align-items:center }
  .aud .lab { color:#adadb8; font-size:11px }
  .aud .hh { color:#adadb8; font-size:10px; text-align:left; white-space:nowrap }
  .aud .c { height:22px; border-radius:3px; cursor:default }
  .aud .c.slot { box-shadow:inset 0 0 0 2px #efeff1 }
  .aud .c.none { background:#2a2a2d }
  .aud .c:hover, .aud .c:focus { outline:2px solid #efeff1; outline-offset:1px }
  .aud .legend { display:flex; gap:14px; flex-wrap:wrap; margin:10px 0 4px; color:#adadb8; font-size:12px;
                 align-items:center }
  .aud .sw { display:inline-block; width:12px; height:12px; border-radius:3px; vertical-align:-2px;
             margin-right:5px }
  .aud .sep { grid-column:1 / -1; height:6px }
  #audtip { position:fixed; pointer-events:none; background:#000; border:1px solid #333;
            border-radius:8px; padding:6px 10px; font-size:13px; display:none; z-index:30 }
  #audtip b { display:block }
</style>"""

SCRIPT = """<div id="audtip" role="tooltip"></div>
<script>
(function () {
  const tip = document.getElementById('audtip');
  function show(el, x, y) {
    tip.replaceChildren();
    const b = document.createElement('b'); b.textContent = el.dataset.level;
    const s = document.createElement('span'); s.textContent = el.dataset.when;
    tip.append(b, s); tip.style.display = 'block';
    tip.style.left = Math.min(x + 12, innerWidth - tip.offsetWidth - 8) + 'px';
    tip.style.top = (y + 12) + 'px';
  }
  document.querySelectorAll('.aud .c[data-level]').forEach(el => {
    el.addEventListener('pointermove', ev => show(el, ev.clientX, ev.clientY));
    el.addEventListener('pointerleave', () => tip.style.display = 'none');
    el.addEventListener('focus', () => { const r = el.getBoundingClientRect(); show(el, r.left, r.bottom); });
    el.addEventListener('blur', () => tip.style.display = 'none');
  });
})();
</script>"""


def _cell(level: int | None, when: str, slot: bool, label: str) -> str:
    cls = "c slot" if slot else "c"
    if level is None:
        return (f'<div class="{cls} none" tabindex="0" data-level="pas encore de données" '
                f'data-when="{html.escape(when)}"></div>')
    return (f'<div class="{cls}" tabindex="0" style="background:{COLORS[level]}" '
            f'data-level="{html.escape(label)}" data-when="{html.escape(when)}"></div>')


def heatmap(slots: list[str], videos: list[dict], tz: str, *, apply_button: bool) -> str:
    """Panneau « Affluence TikTok » : grille jours x heures + tes données + conseil."""
    slot_hours = _slot_hours(slots)
    personal = personal_hours(videos, tz)
    plevels = personal_levels(personal)
    best, source = recommended_slots(personal)

    head = ['<div></div>'] + [f'<div class="hh">{h}h</div>' if h % 3 == 0 else "<div></div>"
                              for h in range(24)]
    rows = []
    for d, name in enumerate(DAYS):
        rows.append(f'<div class="lab">{name}</div>')
        rows += [_cell(GENERAL[d][h], f"{name} {h}h-{h + 1}h", h in slot_hours,
                       f"Affluence {LEVELS[GENERAL[d][h]]}") for h in range(24)]
    mine = ""
    if personal:
        cells = []
        for h in range(24):
            if h in plevels:
                avg, n = personal[h]
                cells.append(_cell(plevels[h], f"publiées vers {h}h · {n} vidéo(s)",
                                   h in slot_hours, f"{int(avg):,} vues en moyenne"
                                   .replace(",", " ")))
            else:
                cells.append(_cell(None, f"{h}h", h in slot_hours, ""))
        mine = ('<div class="sep"></div><div class="lab" title="Vues moyennes de tes vidéos">'
                'toi</div>' + "".join(cells))

    # équivalent texte (accessibilité) : plages fortes par jour
    def ranges(day: int) -> str:
        out, h = [], 0
        while h < 24:
            if GENERAL[day][h] == 2:
                start = h
                while h < 24 and GENERAL[day][h] == 2:
                    h += 1
                out.append(f"{start}h-{h}h")
            else:
                h += 1
        return ", ".join(out)

    table = "".join(f"<tr><td>{name}</td><td>{ranges(d)}</td></tr>" for d, name in enumerate(DAYS))
    mine_note = (f"La ligne « toi » vient de tes vidéos ({sum(n for _, n in personal.values())} "
                 "publiées) : plus clair = plus de vues." if plevels else
                 f"Avec au moins {MIN_VIDEOS} vidéos dans tes statistiques TikTok, une ligne "
                 "« toi » montrera tes vraies meilleures heures.")
    button = ""
    if apply_button and set(best) != set(slots):
        button = (f'<form method="post" action="/auto/slots" class="row" style="margin-top:10px">'
                  f'<input type="hidden" name="slots" value="{html.escape(", ".join(best))}">'
                  f'<button>Utiliser les créneaux conseillés ({html.escape(", ".join(best))})'
                  f'</button></form>')
    legend = "".join(f'<span><span class="sw" style="background:{COLORS[k]}"></span>'
                     f'Affluence {v}</span>' for k, v in LEVELS.items())
    return f"""{STYLE}
<div class="panel aud"><h2>Affluence TikTok par heure</h2>
<p class="info">Estimation générale pour un public francophone (TikTok ne publie pas ces
chiffres). {mine_note} Les cases entourées sont tes créneaux actuels
({html.escape(", ".join(slots) or "aucun")}).</p>
<div class="grid">{"".join(head)}{"".join(rows)}{mine}</div>
<div class="legend">{legend}<span><span class="sw" style="box-shadow:inset 0 0 0 2px #efeff1"></span>Tes créneaux</span></div>
<p class="info">Conseillé d'après {source} : <strong>{html.escape(", ".join(best))}</strong></p>
<details class="tv"><summary class="meta" style="cursor:pointer">Voir en texte</summary>
<table class="vtable"><tr><th>Jour</th><th>Affluence forte (estimation)</th></tr>{table}</table></details>
{button}</div>{SCRIPT}"""
