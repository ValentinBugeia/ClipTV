"""Messages d'erreur compréhensibles : ce qui s'est passé → ce qu'il faut faire.

Toutes les erreurs montrées dans l'interface (clips en erreur, connexions, vérifications,
pilote automatique) passent par ``explain``. Les cas inconnus gardent un court extrait du
message technique pour pouvoir diagnostiquer.
"""

from __future__ import annotations

import re

# variables de configuration -> libellé de l'interface (Comptes → Clés API)
LABELS = {
    "TWITCH_CLIENT_ID": "le Client ID Twitch",
    "TWITCH_CLIENT_SECRET": "le Client secret Twitch",
    "TIKTOK_CLIENT_KEY": "la Client key TikTok",
    "TIKTOK_CLIENT_SECRET": "le Client secret TikTok",
    "TIKTOK_REDIRECT_URI": "la Redirect URI TikTok",
    "YOUTUBE_CLIENT_ID": "le Client ID YouTube",
    "YOUTUBE_CLIENT_SECRET": "le Client secret YouTube",
}

KEYS = "Comptes → Clés API"
RECONNECT_TIKTOK = "page Comptes → Reconnecter TikTok"

# (motif dans le message technique, explication → action), du plus précis au plus général
RULES: list[tuple[str, str]] = [
    # --- configuration / comptes ---
    (r"Pas de token TikTok|tiktok_token",
     f"TikTok n'est pas connecté → {RECONNECT_TIKTOK.replace('Reconnecter', 'Connecter')}."),
    (r"Pas de token Twitch utilisateur",
     "Ton compte Twitch n'est pas connecté (nécessaire pour clipper les lives) → page Comptes "
     "→ Connecter Twitch."),
    (r"Pas de token YouTube", "YouTube n'est pas connecté → page Comptes → Connecter YouTube."),
    (r"Pas de token Instagram|INSTAGRAM_USER_ID",
     "Instagram n'est pas connecté → page Comptes → colle ton token Instagram."),
    # --- TikTok ---
    (r"invalid_grant|Authorization code is expired",
     "Le code de connexion TikTok a expiré ou a déjà servi → reclique sur « Connecter », "
     "accepte, puis colle tout de suite la nouvelle adresse et valide une seule fois."),
    (r"redirect_uri", "La Redirect URI ne correspond pas → elle doit être identique, au "
     f"caractère près, sur developers.tiktok.com et dans {KEYS}."),
    (r"Refresh du token TikTok refusé|access_token_invalid|token_expired",
     f"La connexion à TikTok a expiré → {RECONNECT_TIKTOK}."),
    (r"(creator_info|/post/publish/video/init).*(scope_not_authorized|scope_permission_missed)",
     "TikTok refuse la publication directe : l'autorisation video.publish manque → sur "
     "developers.tiktok.com, dans le Sandbox de ton app : Content Posting API → active "
     "« Direct Post », ajoute le scope video.publish, Save ; puis page Comptes → Reconnecter "
     "TikTok et accepte les nouvelles autorisations."),
    (r"scope_not_authorized|scope_permission_missed|insufficient.?scope",
     "TikTok refuse : une autorisation (scope) manque → vérifie les scopes de ton app sur "
     f"developers.tiktok.com (user.info.basic, video.upload), puis {RECONNECT_TIKTOK}."),
    (r"invalid_client",
     f"TikTok refuse tes clés → vérifie la Client key et le Client secret du Sandbox dans {KEYS}."),
    (r"unaudited_client|private_account",
     "Ton app TikTok n'est pas encore validée : la publication sur le profil ne marche que si "
     "ton compte TikTok est privé → app TikTok → Profil → ☰ → Paramètres et confidentialité → "
     "Confidentialité → Compte privé, ou repasse en mode « brouillon » (page Comptes)."),
    (r"scope_not_authorized.*video\.publish|video\.publish",
     "TikTok refuse la publication sur le profil → active « Direct Post » (scope video.publish) "
     f"dans Content Posting API sur developers.tiktok.com, puis {RECONNECT_TIKTOK}."),
    (r"too_many_pending_share",
     "Trop de brouillons TikTok en attente (5 maximum par 24 h) → ouvre l'app TikTok, publie "
     "ou supprime ceux de ta boîte de réception, puis réessaie."),
    (r"spam_risk|rate_limit|too_many",
     "TikTok limite le nombre d'envois pour le moment → réessaie plus tard (dans 1 h)."),
    (r"file_format_check_failed|duration_check_failed|picture_size|video_pull_failed",
     "TikTok a refusé la vidéo (format ou durée) → refais le montage (menu ⋯) ou rejette ce clip."),
    # --- Twitch ---
    (r"Chaîne Twitch introuvable : (\S+)",
     "La chaîne « {0} » n'existe pas sur Twitch → corrige son nom dans Pilote auto."),
    (r"(?:400|401|403)\b.*(?:id|api)\.twitch\.tv|invalid client secret|Autorisation Twitch refusée",
     f"Twitch refuse tes clés → vérifie le Client ID et le Client secret dans {KEYS} (si tu as "
     "recréé le secret sur dev.twitch.tv, colle le nouveau)."),
    (r"429|Too Many Requests",
     "Twitch limite les requêtes pour le moment → réessaie dans quelques minutes."),
    # --- téléchargement ---
    (r"sans son", "Twitch a fourni ce clip sans son → rejette-le (menu ⋯ → Rejeter)."),
    (r"HTTP Error 404|not available|does not exist|no longer available|Clip not found",
     "Ce clip n'existe plus sur Twitch (supprimé par le streamer) → rejette-le."),
    (r"Échec du téléchargement|DownloadError|Unable to download|yt.dlp",
     "Le téléchargement du clip a échoué → vérifie ta connexion puis clique sur Réessayer ; "
     "si ça continue, mets l'app à jour (git pull puis relance cliptv.sh)."),
    # --- transcription / montage ---
    (r"huggingface|hf\.co|LocalEntryNotFound|snapshot_download",
     "Impossible de télécharger le modèle de transcription (environ 500 Mo la 1re fois) → "
     "vérifie ta connexion et réessaie, ou décoche les sous-titres dans Pilote auto."),
    (r"Extraction audio impossible",
     "Le son du clip est illisible → refais le montage sans sous-titres (menu ⋯) ou rejette-le."),
    (r"No space left|Errno 28",
     "Le disque est plein → libère de la place (le dossier cliptv/data/downloads peut être vidé)."),
    (r"MemoryError|Cannot allocate memory|std::bad_alloc",
     "Plus assez de mémoire → ferme d'autres programmes, ou utilise un modèle de transcription "
     "plus léger (WHISPER_MODEL=base dans le fichier .env)."),
    (r"ffmpeg|CalledProcessError|returned non-zero exit status",
     "Le montage vidéo a échoué → lance « Tout vérifier » (page Comptes) pour contrôler "
     "ffmpeg, puis Réessayer ; si ça recommence, refais le montage avec un autre cadrage."),
    # --- réseau (en dernier : beaucoup d'erreurs ci-dessus mentionnent aussi l'URL) ---
    (r"ProxyError|ConnectionError|Max retries exceeded|NameResolution|Failed to resolve|"
     r"Connection refused|timed out|Timeout|Network is unreachable|getaddrinfo",
     "Pas de connexion à Internet, ou le service ne répond pas → vérifie ta connexion puis "
     "réessaie."),
]


def _missing_config(text: str) -> str | None:
    m = re.search(r"Configuration manquante : ([A-Z_, ]+)", text)
    if not m:
        return None
    names = [n.strip() for n in m.group(1).split(",") if n.strip()]
    labels = [LABELS.get(n, n) for n in names]
    return f"Il manque {', '.join(labels)} → ajoute-les dans {KEYS}, puis Enregistrer les clés."


def explain(error: BaseException | str, *, short: bool = False) -> str:
    """Message pour l'utilisateur. ``short`` : sans la partie « → action » (listes)."""
    text = error if isinstance(error, str) else f"{type(error).__name__}: {error}"
    message = _missing_config(text)
    if message is None:
        for pattern, explanation in RULES:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                message = explanation.format(*m.groups()) if m.groups() else explanation
                break
    if message is None:
        detail = re.sub(r"\s+", " ", str(error) if not isinstance(error, str) else error)
        detail = detail.strip()[:160] or type(error).__name__
        message = (f"Erreur inattendue ({detail}) → réessaie ; si ça recommence, envoie ce "
                   "message et la fin du terminal pour obtenir de l'aide.")
    return message.split(" → ")[0] if short else message
