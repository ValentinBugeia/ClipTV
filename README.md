# cliptv (`clipbot`)

Une app web qui tourne **toute seule, de A à Z** :

1. trouve les clips **les plus viraux** des chaînes Twitch que tu suis, et clippe
   automatiquement les **moments forts des lives** (quand le chat s'emballe) ;
2. les monte au **format téléphone 9:16**, cadrés sur la facecam, avec des
   **sous-titres animés** (style TikTok, mot en cours surligné) ;
3. écrit l'**accroche et les hashtags** avec Claude ;
4. les publie sur **TikTok, YouTube Shorts et Instagram Reels** aux **heures de forte
   audience** que tu as choisies.

Tout se pilote **depuis le navigateur**, sur ordinateur comme sur téléphone : réglages,
suivi en direct, connexion des comptes, et si tu veux, validation ou annulation d'un clip.

```
Twitch (clips + chat des lives) ─► yt-dlp ─► cadrage visage ─► Whisper ─► ffmpeg 9:16 + sous-titres
        ─► légende Claude ─► programmation sur créneaux ─► TikTok · YouTube Shorts · Instagram Reels
```

## Démarrage rapide (serveur, 24 h/24)

Sur un petit serveur Linux (VPS à quelques €/mois, 2 Go de RAM minimum) avec Docker :

```bash
git clone https://github.com/ValentinBugeia/cliptv && cd cliptv
cp .env.example .env      # remplis au moins CLIPBOT_REVIEW_PASSWORD et les clés Twitch
docker compose up -d      # → http://<ip-du-serveur>:8000
```

Avec un nom de domaine (DNS pointé vers le serveur), ajoute `CLIPBOT_DOMAIN=clips.mondomaine.fr`
et `CLIPBOT_BIND=127.0.0.1` dans `.env`, puis :

```bash
docker compose --profile https up -d   # → https://clips.mondomaine.fr (certificat automatique)
```

Ensuite, **tout se passe dans le navigateur** :

- **Comptes** : connecte Twitch, TikTok, YouTube et Instagram en un clic (ou en entrant un
  code), puis « Tout vérifier » teste chaque connexion pour de vrai ;
- **Pilote auto** : choisis les chaînes, les lives à surveiller, les plateformes et les
  heures de publication. Il est **activé par défaut** ;
- **Clips** : suis ce qui est prêt, programmé ou publié, modifie une légende, annule un
  clip, ou lance une recherche ponctuelle.

> 🔒 L'interface est protégée par le mot de passe `CLIPBOT_REVIEW_PASSWORD` (utilisateur
> `admin`). Ne l'expose jamais sur Internet sans mot de passe, et utilise le HTTPS.

Mise à jour : `git pull && docker compose up -d --build`. L'image est aussi publiée sur
`ghcr.io/valentinbugeia/cliptv` à chaque push sur `main` (`docker compose pull` suffit
alors ; rends le paquet public dans GitHub, ou fais `docker login ghcr.io`).

## Clés API (à mettre dans `.env`)

| Service | Où | Variables |
|---|---|---|
| **Twitch** (obligatoire) | https://dev.twitch.tv/console/apps → app « Confidential » | `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` |
| **TikTok** | https://developers.tiktok.com → Login Kit + Content Posting API, scopes `video.upload` (+ `video.publish`) | `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI=https://<domaine>/tiktok/callback` |
| **YouTube** | console Google Cloud → API YouTube Data v3 → identifiants OAuth de type « TV et appareils à entrée limitée » | `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_PRIVACY` |
| **Instagram** | compte **professionnel** + app Meta (produit Instagram, `instagram_business_content_publish`) → token longue durée à coller dans la page Comptes | — |
| **Claude** (légendes) | https://console.anthropic.com | `ANTHROPIC_API_KEY` |

> ⚠️ **TikTok** : tant que l'app n'a pas passé l'**audit**, la publication directe est forcée
> en privé. Le mode par défaut (`draft`) envoie la vidéo dans ta boîte de réception TikTok :
> tu la publies d'un tap, ce qui marche sans audit. **YouTube** publie en `private` par défaut
> (`YOUTUBE_PRIVACY=public` une fois que tu es satisfait).

## Comment marche le pilote automatique

- Toutes les N minutes (réglable), il prend les clips des dernières 24 h classés par
  **vues/heure**, ignore ceux déjà traités et ceux sous le seuil de vues.
- Pour les lives surveillés, il lit le chat et crée un clip dès que l'activité dépasse
  x3 la normale (emotes, « KEKW », « mdr », MAJUSCULES…), puis le traite aussitôt.
- Chaque clip est placé sur le **prochain créneau libre** (par défaut 12:30, 18:00 et
  21:00, heure de Paris). Il ne remplit pas la file au-delà de 2 jours de créneaux, pour
  ne publier que des clips frais.
- Si une plateforme échoue, le clip passe dans « Erreurs » : « Réessayer » ne republie
  **que** sur les plateformes manquantes.

## En local / ligne de commande

Prérequis : Python ≥ 3.10 et **ffmpeg** (avec libass, inclus dans les builds standard).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all,dev]"
cp .env.example .env
clipbot doctor            # vérifie ffmpeg, la police, les clés et chaque connexion
clipbot app               # interface + pilote auto → http://localhost:8000
```

Police des sous-titres : dépose `Montserrat-Black.ttf` dans `fonts/` (incluse dans l'image Docker).

Toutes les étapes existent aussi en commandes, pour les scripts et le cron :

```bash
clipbot run -c kamet0 -c zerator --top 3 --ai-caption --schedule   # clips viraux → programmés
clipbot run --every 60 --schedule                                  # en boucle (CLIPBOT_CHANNELS)
clipbot watch kamet0 gotaga --forever --schedule                   # plusieurs lives en parallèle
clipbot publisher                                                  # publie aux créneaux
clipbot render mon_clip.mp4 --layout auto                          # test du rendu sur un fichier
clipbot twitch-auth | tiktok-auth | youtube-auth | instagram-auth --token …
```

| Option | Effet |
|---|---|
| `--layout auto` | (défaut) facecam détectée → `split`, caméra plein écran → `crop` centré sur le visage, sinon `blur` |
| `--platform/-p` | `tiktok`, `youtube`, `instagram` (répétable ; défaut `CLIPBOT_PLATFORMS`) |
| `--publish` / `--schedule` | publie tout de suite / programme sur le prochain créneau |
| `--ai-caption` | légende (accroche + hashtags) générée par Claude |
| `--mode draft\|direct` | TikTok : boîte de réception ou publication directe |
| `--caption "…"` | légende modèle : `{title}` `{channel}` `{channel_tag}` `{clipper}` |
| `--no-subs`, `--highlight "#FFE600"`, `--language fr` | sous-titres |

Un historique SQLite (`data/state.sqlite3`) évite de retraiter ou republier un clip, et
garde les réglages faits dans l'interface.

## Structure

```
clipbot/
  review.py     interface web (Clips, Pilote auto, Comptes) — stdlib uniquement
  autopilot.py  pilote automatique (recherche périodique + surveillance des lives)
  schedule.py   créneaux de publication + planificateur
  pipeline.py   traitement d'un clip et publication multi-plateformes
  watcher.py    surveillance d'un live (attente, chat, création de clips)
  twitch.py     API Helix, viralité, token utilisateur (device flow), création de clips
  live.py       lecture du chat IRC + détecteur de pics
  facecam.py    détection du visage (OpenCV) et choix du cadrage
  subtitles.py  transcription faster-whisper + sous-titres ASS karaoké
  render.py     filtergraph ffmpeg 9:16 (blur / crop / split) + incrustation
  captions.py   légendes IA (Claude, sortie JSON structurée)
  tiktok.py     TikTok : OAuth, upload chunké, brouillon / publication
  youtube.py    YouTube Shorts : device flow Google, upload resumable
  instagram.py  Instagram Reels : upload resumable, publication
  doctor.py     diagnostic de l'installation et des connexions
  state.py      historique SQLite + réglages
  cli.py        commandes
Dockerfile, docker-compose.yml   déploiement serveur (+ HTTPS Caddy)
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

- Suivi du visage image par image (le cadrage actuel est fixe sur tout le clip).
- Combiner le chat avec le volume audio (cris) pour mieux détecter les moments forts.
- Statistiques de vues par plateforme dans l'interface pour ajuster les seuils.

## ⚖️ Droits

Les clips appartiennent aux streamers. Republier leur contenu sans accord peut entraîner
des retraits (copyright) ou la suspension du compte TikTok. Demande l'autorisation aux
streamers (beaucoup acceptent les "clippeurs", parfois via des programmes rémunérés) et
crédite toujours la chaîne dans la légende.
