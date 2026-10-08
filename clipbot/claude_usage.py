"""Ce qu'il reste de ton abonnement Claude, et combien de recherches ça représente.

Claude Code renvoie à chaque appel le pourcentage utilisé de tes deux limites (fenêtre de
5 heures et semaine) avec leur heure de réinitialisation. ClipTV garde le dernier relevé
et apprend combien de pourcents consomme une recherche (tokens d'une recherche × part de
la limite consommée par token, mesurée entre deux relevés).
"""

from __future__ import annotations

import time

LIMITS = "claude_limits"       # dernier relevé {five_hour: {...}, seven_day: {...}, at}
RATES = "claude_rates"         # part de chaque limite consommée par token (moyenne glissante)
SEARCHES = "claude_search_tokens"  # tokens des dernières recherches
WINDOWS = (("five_hour", "Limite des 5 heures"), ("seven_day", "Limite de la semaine"))


def record(state, purpose: str, tokens_in: int, tokens_out: int, cost: float, ms: int,
           limits: dict | None = None) -> None:
    """Après chaque appel à Claude : tokens dans l'historique, relevé des limites."""
    state.add_claude_usage(purpose, tokens_in, tokens_out, cost, ms)
    if not limits:
        return
    windows = limits.get("unifiedWindows") or {}
    if not windows and limits.get("rateLimitType") and limits.get("utilization") is not None:
        windows = {limits["rateLimitType"]: {"utilization": limits["utilization"],
                                             "resetsAt": limits.get("resetsAt")}}
    if not windows:
        return
    settings = state.get_settings()
    previous = settings.get(LIMITS) or {}
    rates = settings.get(RATES) or {}
    tokens = tokens_in + tokens_out
    for key, _ in WINDOWS:
        now, before = windows.get(key), previous.get(key)
        if not now or not before or not tokens:
            continue
        delta = float(now.get("utilization") or 0) - float(before.get("utilization") or 0)
        same_window = now.get("resetsAt") == before.get("resetsAt")
        if same_window and 0 < delta < 0.5:  # (une baisse = réinitialisation : ignoré)
            rate = delta / tokens
            rates[key] = rate if key not in rates else 0.7 * rates[key] + 0.3 * rate
    state.save_settings({LIMITS: {**{k: windows[k] for k in windows}, "at": int(time.time())},
                         RATES: rates})


def search_done(state, tokens: int) -> None:
    """Fin d'une recherche : ses tokens servent à estimer le coût d'une recherche."""
    if tokens <= 0:
        return
    last = (state.get_settings().get(SEARCHES) or [])[-19:]
    state.save_settings({SEARCHES: last + [int(tokens)]})


def summary(state) -> dict:
    """Pour l'affichage : par limite, % utilisé, réinitialisation, recherches restantes."""
    settings = state.get_settings()
    limits = settings.get(LIMITS) or {}
    rates = settings.get(RATES) or {}
    searches = settings.get(SEARCHES) or []
    per_search = sum(searches) / len(searches) if searches else None
    now = time.time()
    out = {"at": limits.get("at"), "per_search_tokens": per_search, "windows": []}
    for key, label in WINDOWS:
        w = limits.get(key)
        if not w:
            continue
        used = float(w.get("utilization") or 0)
        resets = w.get("resetsAt")
        if resets and resets < now:  # réinitialisée depuis le dernier relevé
            used = 0.0
        left = None
        if per_search and rates.get(key):
            left = max(int((1 - used) / (rates[key] * per_search) + 1e-6), 0)
        out["windows"].append({"key": key, "label": label, "used": min(max(used, 0), 1),
                               "resets": resets, "searches_left": left})
    return out


def short_line(state) -> str:
    """« 64 % restant · ≈ 12 recherches » d'après la limite la plus proche d'être atteinte."""
    s = summary(state)
    if not s["windows"]:
        return ""
    w = max(s["windows"], key=lambda x: x["used"])
    known = [x["searches_left"] for x in s["windows"] if x["searches_left"] is not None]
    text = f"{round((1 - w['used']) * 100)} % restant"
    if known:
        text += f" · ≈ {min(known)} recherche{'s' if min(known) > 1 else ''}"
    return text
