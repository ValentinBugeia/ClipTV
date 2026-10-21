"""Recherche des clips : aucune liste de chaînes à fournir.

1. **Où chercher** : chez les **streamers les plus vus** — classés par les vues de leurs
   rediffusions de la période (dans les catégories les plus regardées), plus ceux que
   l'app a vus les plus regardés en live ces 7 derniers jours (certains désactivent leurs
   rediffusions) — et chez tes chaînes favorites, même hors ligne au moment de la
   recherche ;
2. **quels clips** : seulement ceux créés pendant la période (24 h = le live a eu lieu
   dans les dernières 24 h), dans ta langue, pas déjà préparés ni déjà sur ton TikTok ;
3. **lesquels** : les plus vus sur Twitch, autant que de clips demandés (plusieurs clips
   du même moment n'en font qu'un).
Ensuite ``selection.make_clips`` les complète (Claude) et les monte.
"""

from __future__ import annotations

import logging
import time

from .twitch import Clip, TwitchClient

log = logging.getLogger("clipbot.discover")
MEMORY_DAYS = 7        # un streamer repéré en live reste scanné 7 jours (même hors ligne)
MEMORY_KEY = "discovered"
CATEGORY_KEY = "categories_seen"  # catégories vues dans les lives FR ces 7 derniers jours
MEMORY_MAX = 120                  # chaînes gardées (les plus regardées)


def remember_streams(state, streams: list[dict]) -> dict:
    """Mémorise les lives vus (relevé toutes les 30 min par l'app, et à chaque recherche) :
    une recherche du matin connaît ainsi les streamers et catégories de la veille au soir,
    hors ligne au moment de la recherche."""
    now = time.time()
    settings = state.get_settings()
    memory: dict = settings.get(MEMORY_KEY, {})
    cats: dict = settings.get(CATEGORY_KEY, {})
    viewers: dict[str, int] = {}
    for s in streams:
        login = s["user_login"].lower()
        v = int(s.get("viewer_count") or 0)
        old = memory.get(login, {})
        memory[login] = {"id": s["user_id"], "seen": now,
                         "viewers": max(v, int(old.get("viewers") or 0))}
        if s.get("game_id"):
            viewers[s["game_id"]] = viewers.get(s["game_id"], 0) + v
    for gid, v in viewers.items():
        cats[gid] = {"seen": now, "viewers": max(v, int((cats.get(gid) or {}).get("viewers") or 0))}
    week = MEMORY_DAYS * 86400
    memory = dict(sorted(((k, v) for k, v in memory.items() if now - v["seen"] < week),
                         key=lambda kv: kv[1].get("viewers", 0), reverse=True)[:MEMORY_MAX])
    cats = {k: v for k, v in cats.items() if now - v["seen"] < week}
    state.save_settings({MEMORY_KEY: memory, CATEGORY_KEY: cats})
    return memory


TOP_STREAMERS = 40   # streamers les plus vus de la période (vues des rediffusions)
TOP_LIVE = 20        # + les plus regardés en live ces 7 derniers jours (relevé de l'app)


def main_categories(twitch: TwitchClient, state) -> list[str]:
    """Catégories à fouiller : celles relevées ces 7 derniers jours (les plus regardées),
    complétées par le top des catégories Twitch (indispensable sur une app récente)."""
    seen = state.get_settings().get(CATEGORY_KEY) or {}
    games = sorted(seen, key=lambda g: seen[g].get("viewers", 0), reverse=True)[:TOP_CATEGORIES]
    if len(games) < TOP_CATEGORIES:
        try:
            games += [g["id"] for g in twitch._get("/games/top", {"first": 50})["data"]
                      if g["id"] not in games][: TOP_CATEGORIES - len(games)]
        except Exception:
            log.warning("Catégories Twitch indisponibles", exc_info=True)
    return games


def recent_broadcasters(twitch: TwitchClient, state, *, language: str | None,
                        hours: float) -> dict[str, str]:
    """{login: id} des streamers qui ont diffusé sur la période (dans la langue), d'après
    les rediffusions des catégories principales triées par vues : la veille au soir est
    couverte même si l'app était fermée et que la chaîne est hors ligne maintenant."""
    from concurrent.futures import ThreadPoolExecutor

    games = main_categories(twitch, state)
    if not games:
        return {}
    period = "day" if hours <= 24 else "week" if hours <= 24 * 7 else "month"

    def fetch(game_id):
        params = {"game_id": game_id, "period": period, "sort": "views", "type": "archive",
                  "first": 100, **({"language": language} if language else {})}
        try:
            return twitch._get("/videos", params)["data"]
        except Exception:
            log.warning("Rediffusions de la catégorie %s indisponibles", game_id)
            return []
    views: dict[str, int] = {}
    ids: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for batch in pool.map(fetch, games):
            for v in batch:
                login = (v.get("user_login") or "").lower()
                if login and v.get("user_id"):
                    views[login] = views.get(login, 0) + int(v.get("view_count") or 0)
                    ids[login] = v["user_id"]
    top = sorted(views, key=views.get, reverse=True)[:TOP_STREAMERS]
    log.info("Streamers les plus vus de la période (vues des rediffusions, %d catégories) : %s",
             len(games), ", ".join(f"{login} ({views[login]:,})".replace(",", " ")
                                   for login in top[:15]) + (" …" if len(top) > 15 else ""))
    return {login: ids[login] for login in top}


def top_live_streamers(state) -> dict[str, str]:
    """{login: id} des streamers les plus regardés en live ces 7 derniers jours (pic de
    spectateurs relevé par l'app), même s'ils n'ont pas de rediffusion."""
    memory = state.get_settings().get(MEMORY_KEY) or {}
    best = sorted(memory, key=lambda k: memory[k].get("viewers", 0), reverse=True)[:TOP_LIVE]
    return {login: memory[login]["id"] for login in best if memory[login].get("id")}


def candidate_channels(twitch: TwitchClient, state, *, language: str | None,
                       favorites: list[str] = (), hours: float = 24, **_) -> dict[str, str]:
    """{login: broadcaster_id} des chaînes à scanner : les streamers les plus vus de la
    période (rediffusions), les plus regardés en live ces 7 derniers jours, et tes favoris.
    Être en live ou non au moment de la recherche ne compte pas : seuls les clips de la
    période sont pris."""
    channels = recent_broadcasters(twitch, state, language=language, hours=hours)
    for login, bid in top_live_streamers(state).items():
        channels.setdefault(login, bid)
    for login in favorites:
        if login not in channels:
            try:
                channels[login] = twitch.get_broadcaster_id(login)
            except Exception:
                log.warning("Chaîne favorite introuvable : %s", login)
    return channels


def tiktok_check(state):
    """Vérifie les vidéos déjà sur le compte TikTok (liste rafraîchie si besoin)."""
    from . import stats

    return stats.on_tiktok(state)


def pick_clips(clips: list[Clip], owner: dict, *, top: int, max_duration: float = 60,
               language: str | None = None, is_done=lambda cid: False,
               on_tiktok=lambda clip: False) -> list[tuple[Clip, str]]:
    """Les ``top`` clips les plus vus : dans la langue, pas déjà préparés ni déjà sur ton
    TikTok, un seul clip par moment (plusieurs viewers clippent souvent le même)."""
    from .moments import same_moment

    _log_pool(clips, owner, language, max_duration, is_done)
    if language:
        clips = [c for c in clips if not c.language or c.language.startswith(language)]
    picked: list[Clip] = []
    seen: set[str] = set()
    for clip in sorted(clips, key=lambda c: c.view_count, reverse=True):
        if clip.id in seen or clip.duration > max_duration or is_done(clip.id):
            continue
        seen.add(clip.id)
        twin = next((p for p in picked if same_moment(p, clip)), None)
        if twin is not None:
            twin.clippers = getattr(twin, "clippers", 1) + 1
            continue
        if on_tiktok(clip):  # déjà sur le compte (autre PC, publication à la main…)
            log.info("Déjà sur TikTok, ignoré : %s · %s", clip.broadcaster_name, clip.title)
            continue
        clip.clippers = 1
        picked.append(clip)
        if len(picked) >= top:
            break
    return [(c, owner.get(c.id) or c.broadcaster_name.lower()) for c in picked]


def _log_pool(clips: list[Clip], owner: dict, language, max_duration, is_done, n: int = 15):
    """Journal : les clips les plus vus du vivier et pourquoi certains sont écartés (pour
    vérifier que les gros moments de la période arrivent bien jusqu'ici)."""
    best = sorted({c.id: c for c in clips}.values(), key=lambda c: c.view_count,
                  reverse=True)[:n]
    lines = []
    for c in best:
        why = ("autre langue" if language and c.language and not c.language.startswith(language)
               else "trop long" if c.duration > max_duration
               else "déjà préparé" if is_done(c.id) else "")
        lines.append(f"  {c.view_count:>7} vues · {owner.get(c.id) or c.broadcaster_name} · "
                     f"{c.title[:50]} ({c.language or '?'}, {c.created_at:%d/%m %Hh%M})"
                     + (f" → écarté : {why}" if why else ""))
    if lines:
        log.info("Les plus vus du vivier :\n%s", "\n".join(lines))


TOP_CATEGORIES = 25  # catégories où chercher les rediffusions des streamers les plus vus


def category_clips(twitch: TwitchClient, pool, state, *, language: str | None, hours: float,
                   favorites=(), known=(), games: list[str] | None = None) -> list[tuple[Clip, str]]:
    """Clips les plus vus des catégories les plus regardées en ce moment (dans la langue),
    y compris chez des streamers hors ligne : les vrais moments viraux de la journée.
    ``games`` : catégories imposées (recherche « Valorant »…) au lieu de celles du moment."""
    if games is None:
        games = main_categories(twitch, state)
    if not games:
        return []

    def fetch(game_id):
        try:
            # 300 clips : les plus vus mêlent toutes les langues, on garde ensuite le français
            return twitch.get_game_clips(game_id, since_hours=hours, limit=300)
        except Exception:
            log.warning("Clips de la catégorie %s indisponibles", game_id)
            return []
    found = [c for batch in pool.map(fetch, games) for c in batch
             if c.id not in known and (not language or not c.language
                                       or c.language.startswith(language))]
    if not found:
        return []
    try:
        logins = twitch.logins(c.broadcaster_id for c in found)
    except Exception:
        log.warning("Noms des chaînes indisponibles", exc_info=True)
        return []
    out, seen = [], set()
    for c in found:
        login = logins.get(c.broadcaster_id)
        if not login or c.id in seen:
            continue
        seen.add(c.id)
        out.append((c, login))
    return out


def _plain(text: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", text or "").lower()
    return "".join(c for c in text if not unicodedata.combining(c))


def resolve_query(twitch: TwitchClient, terms: list[str]) -> dict:
    """Devine ce que chaque terme désigne : un jeu / une catégorie (nom exact), une chaîne
    Twitch, un jeu au nom approchant, sinon un mot-clé à chercher dans les titres des clips."""
    import re

    out: dict = {"channels": {}, "games": {}, "keywords": []}
    for term in (t.strip() for t in terms):
        if not term:
            continue
        try:
            cats = twitch._get("/search/categories", {"query": term, "first": 5})["data"]
        except Exception:
            cats = []
        exact = next((c for c in cats if _plain(c["name"]) == _plain(term)), None)
        if exact:
            out["games"][exact["id"]] = exact["name"]
            continue
        if re.fullmatch(r"\w{2,25}", term):
            try:
                out["channels"][term.lower()] = twitch.get_broadcaster_id(term)
                continue
            except Exception:
                pass
        close = next((c for c in cats if len(term) >= 3 and _plain(term) in _plain(c["name"])),
                     None)
        if close:
            out["games"][close["id"]] = close["name"]
        else:
            out["keywords"].append(term)
    log.info("Recherche : chaînes %s · jeux %s · mots-clés %s", list(out["channels"]) or "—",
             list(out["games"].values()) or "—", out["keywords"] or "—")
    return out


def query_pool(twitch: TwitchClient, pool, state, q: dict, *, language: str | None,
               hours: float, favorites=()) -> tuple[list, dict]:
    """Clips correspondant à la recherche : ceux des chaînes demandées, les plus vus des
    jeux demandés, et pour les mots-clés, les clips du moment dont le titre les contient."""
    clips, owner = [], {}

    def fetch(item):
        login, bid = item
        try:
            return login, twitch.get_clips(bid, since_hours=hours, limit=100)
        except Exception:
            log.warning("Clips indisponibles pour %s", login)
            return login, []
    for login, found in pool.map(fetch, q["channels"].items()):
        for c in found:
            owner[c.id] = login
            clips.append(c)
    if q["games"]:
        for c, login in category_clips(twitch, pool, state, language=language, hours=hours,
                                       favorites=favorites, known=owner,
                                       games=list(q["games"])):
            owner[c.id] = login
            clips.append(c)
    if q["keywords"]:  # mots-clés : dans les clips du moment (chaînes et catégories suivies)
        words = [_plain(k) for k in q["keywords"]]
        chans = candidate_channels(twitch, state, language=language, favorites=favorites,
                                   hours=hours)
        found = list(pool.map(fetch, chans.items()))
        extra = category_clips(twitch, pool, state, language=language, hours=hours,
                               favorites=favorites, known=owner)
        pool_clips = [(c, login) for login, batch in found for c in batch] + extra
        for c, login in pool_clips:
            if c.id not in owner and any(w in _plain(c.title) for w in words):
                owner[c.id] = login
                clips.append(c)
    return clips, owner


def discover(twitch: TwitchClient, state, *, language: str | None = "fr", hours: float = 24,
             top: int = 3, max_duration: float = 60, favorites: list[str] = (),
             query: list[str] | None = None, **_) -> list[tuple[Clip, str]]:
    """[(clip, login)] des ``top`` clips les plus vus de la période, ou de la recherche
    ``query`` (chaînes, jeux ou mots-clés tapés dans « Recherche ponctuelle »)."""
    from concurrent.futures import ThreadPoolExecutor

    check = dict(is_done=state.is_done, on_tiktok=tiktok_check(state))
    if query:
        q = resolve_query(twitch, query)
        with ThreadPoolExecutor(max_workers=8) as pool:
            clips, owner = query_pool(twitch, pool, state, q, language=language, hours=hours,
                                      favorites=favorites)
        if q["channels"] and not q["games"] and not q["keywords"]:
            language = None  # chaîne demandée : ses clips, quelle que soit la langue
        picked = pick_clips(clips, owner, top=top, max_duration=max_duration,
                            language=language, **check)
        log.info("Recherche « %s » : %d clips trouvés, %d retenus", ", ".join(query),
                 len(clips), len(picked))
        return picked
    channels = candidate_channels(twitch, state, language=language, favorites=favorites,
                                  hours=hours)
    log.info("Recherche : clips de %d streamers parmi les plus vus (%s)", len(channels),
             language or "toutes langues")

    def fetch(item):
        login, broadcaster_id = item
        try:
            return login, twitch.get_clips(broadcaster_id, since_hours=hours, limit=50)
        except Exception:
            log.warning("Clips indisponibles pour %s", login)
            return login, []

    clips, owner = [], {}
    # 8 requêtes Twitch à la fois (bien sous la limite de 800/min)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for login, found in pool.map(fetch, channels.items()):
            for c in found:
                owner[c.id] = login
            clips += found
    picked = pick_clips(clips, owner, top=top, max_duration=max_duration, language=language,
                        **check)
    log.info("%d clips de la période trouvés, les %d plus vus retenus", len(clips), len(picked))
    return picked


def run_discovery(cfg, state, opts, twitch: TwitchClient, **kwargs) -> list[tuple[str, bool]]:
    """Recherche complète : les clips les plus vus, complétés par Claude, puis montés."""
    from . import progress, stats
    from .selection import candidates, make_clips

    progress.step("search", f"Clips les plus vus ({kwargs.get('language') or 'toutes langues'})")
    stats.refresh_before_search(cfg, state)  # pour écarter les clips déjà sur TikTok
    top = int(kwargs.pop("top", 3))
    found = discover(twitch, state, max_duration=opts.max_duration,
                     top=candidates(top, opts), **kwargs)
    if not found:
        progress.step("search", "Aucun nouveau clip sur la période")
        return []
    twitch.annotate_categories([clip for clip, _ in found])
    return make_clips(found, cfg, state, opts, language=kwargs.get("language"), top=top)
