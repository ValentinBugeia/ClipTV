# twitch-clips-to-tiktok (`clipbot`)

Récupère automatiquement les clips **les plus viraux** d'une ou plusieurs chaînes Twitch,
les convertit au **format téléphone 9:16** avec des **sous-titres animés** (style TikTok,
mot en cours surligné) et les **publie sur TikTok** via l'API officielle.

```
Twitch Helix API ──► classement viralité ──► yt-dlp ──► faster-whisper ──► ffmpeg 9:16 + ASS ──► TikTok Content Posting API
   (clips 24h)        (vues / heure)        (mp4)      (mots horodatés)    (blur / crop / split)    (brouillon ou direct)
```

## Installation

Prérequis : Python ≥ 3.10 et **ffmpeg** (avec libass, inclus dans les builds standard).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # puis remplis les clés
```

Police des sous-titres : dépose `Montserrat-Black.ttf` dans `fonts/` (sinon police de repli).

## Clés API

**Twitch** — https://dev.twitch.tv/console/apps → nouvelle app → `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET`.
Le token "app" (client credentials) suffit pour lire les clips publics.

**TikTok** — https://developers.tiktok.com → crée une app, ajoute **Login Kit** et
**Content Posting API**, scopes `video.upload` (+ `video.publish` pour la publication directe),
et déclare ton `TIKTOK_REDIRECT_URI`. Puis :

```bash
clipbot tiktok-auth              # affiche l'URL d'autorisation
clipbot tiktok-auth --code XXXX  # échange le code -> data/tiktok_token.json (refresh auto)
```

> ⚠️ Tant que l'app TikTok n'a pas passé l'**audit**, la publication directe est forcée en
> privé (`SELF_ONLY`). Le mode `--mode draft` (par défaut) envoie la vidéo dans ta boîte de
> réception TikTok : tu la publies d'un tap depuis l'app, ce qui marche sans audit.

## Utilisation

```bash
# Tester le rendu sur un fichier local
clipbot render mon_clip.mp4 --layout blur --language fr

# Les 3 clips les plus viraux des dernières 24h, rendus dans data/output/ (sans publier)
clipbot run -c kamet0 -c zerator --hours 24 --top 3 --language fr

# Idem + envoi en brouillon sur TikTok
clipbot run -c kamet0 --top 2 --publish --mode draft
```

Options utiles :

| Option | Effet |
|---|---|
| `--layout blur` | vidéo 16:9 centrée sur fond flouté (défaut) |
| `--layout crop` | recadrage plein écran sur le centre |
| `--layout split` | facecam (coin haut-droit de la source) en haut, jeu en bas |
| `--min-views N` | ignore les clips avec moins de N vues |
| `--caption "…"` | légende TikTok, variables `{title}` `{channel}` `{channel_tag}` `{clipper}` |
| `--highlight "#FFE600"` | couleur du mot surligné |
| `--no-subs` | pas de sous-titres |

Un historique SQLite (`data/state.sqlite3`) évite de retraiter/republier deux fois le même clip.

### Automatisation

- **Cron local** : `0 */6 * * * cd /chemin && .venv/bin/clipbot run -c kamet0 --publish`
- **GitHub Actions** : `.github/workflows/clipbot.yml` (déclenchement manuel, schedule à
  décommenter). Secrets : `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `TIKTOK_CLIENT_KEY`,
  `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN` (le `refresh_token` de `data/tiktok_token.json`).

## Structure

```
clipbot/
  twitch.py     API Helix, pagination, score de viralité (vues/heure)
  download.py   téléchargement des clips (yt-dlp)
  subtitles.py  transcription faster-whisper + génération ASS karaoké
  render.py     filtergraph ffmpeg 9:16 (blur / crop / split) + incrustation
  tiktok.py     OAuth + upload chunké + publication / brouillon + suivi du statut
  state.py      historique SQLite
  cli.py        commandes `run`, `render`, `tiktok-auth`
tests/          pytest (dont rendu ffmpeg réel)
```

## Projets open source existants (repérés sur GitHub)

Utiles comme référence ou pour piocher des idées :

| Repo | Intérêt |
|---|---|
| [ColinGPT9/clips-studio](https://github.com/ColinGPT9/clips-studio) | Alternative locale à Opus Clip : streams Twitch/Kick → shorts sous-titrés, auto-post 24/7 (Whisper + LLM). Le plus proche du besoin. |
| [LuisSotelo/vod-to-viral](https://github.com/LuisSotelo/vod-to-viral) | Détection de moments forts dans les **VODs** (audio, chat, mouvement, parole) → vertical + sous-titres. Bonne base pour une v2 "sans clips existants". |
| [fralapo/clippyme](https://github.com/fralapo/clippyme) | Recadrage sur le locuteur actif (YOLO), éditeur web, planification TikTok. |
| [NaufalRizqullah/opensource-clipping](https://github.com/NaufalRizqullah/opensource-clipping) | Face-tracking MediaPipe, sous-titres karaoké, B-roll. |
| [bihanikeshav/TwitchSnipBot](https://github.com/bihanikeshav/TwitchSnipBot) | Détection de highlights via les **pics de chat** Twitch. |
| [wkaisertexas/tiktok-uploader](https://github.com/wkaisertexas/tiktok-uploader) / [makiisthenes/TiktokAutoUploader](https://github.com/makiisthenes/TiktokAutoUploader) | Upload TikTok non officiel (Selenium / requêtes) — plan B si l'API officielle bloque, mais risque de ban du compte. |
| [chand1012/twitch-tiktok-generator](https://github.com/chand1012/twitch-tiktok-generator), [genaroibc/clippitt](https://github.com/genaroibc/clippitt) | Petits projets Twitch clip → TikTok, simples à lire. |

## Pistes pour la suite

- Détection de moments viraux en **live** (pics de messages/emotes dans le chat IRC) puis
  création du clip via `POST /helix/clips` (nécessite un token utilisateur `clips:edit`).
- Recadrage intelligent sur la facecam (détection de visage) au lieu du coin fixe en `split`.
- Titre/hashtags générés par LLM à partir de la transcription.
- Interface web (file d'attente, validation manuelle avant publication).

## ⚖️ Droits

Les clips appartiennent aux streamers. Republier leur contenu sans accord peut entraîner
des retraits (copyright) ou la suspension du compte TikTok. Demande l'autorisation aux
streamers (beaucoup acceptent les "clippeurs", parfois via des programmes rémunérés) et
crédite toujours la chaîne dans la légende.
