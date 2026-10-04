import pytest
import requests

from clipbot.errors import explain


@pytest.mark.parametrize("error,expected", [
    (SystemExit("Configuration manquante : TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET"),
     "Il manque la Client key TikTok, le Client secret TikTok → ajoute-les dans Comptes"),
    (requests.exceptions.ProxyError("Max retries exceeded with url"), "Pas de connexion"),
    (requests.exceptions.HTTPError("401 Client Error: Unauthorized for url: "
                                   "https://id.twitch.tv/oauth2/token"), "Twitch refuse tes clés"),
    (ValueError("Chaîne Twitch introuvable : kamettt0"), "« kamettt0 » n'existe pas"),
    (RuntimeError("Erreur TikTok : {'code': 'access_token_invalid'}"), "Reconnecter TikTok"),
    (RuntimeError("{'code': 'spam_risk_too_many_posts'}"), "réessaie plus tard"),
    (RuntimeError("ERROR: [twitch:clips] x: HTTP Error 404: Not Found"), "n'existe plus"),
    (OSError(28, "No space left on device"), "disque est plein"),
    (RuntimeError("Command '['ffmpeg']' returned non-zero exit status 1."), "montage vidéo"),
    (SystemExit("Pas de token TikTok : lance d'abord `clipbot tiktok-auth`."),
     "TikTok n'est pas connecté"),
])
def test_explain(error, expected):
    msg = explain(error)
    assert expected in msg and "→" in msg


def test_unknown_error_keeps_a_hint():
    msg = explain(KeyError("truc"))
    assert msg.startswith("Erreur inattendue") and "truc" in msg


def test_short_form_drops_the_action():
    assert explain(OSError(28, "No space left on device"), short=True) == "Le disque est plein"
