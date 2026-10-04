# Faire valider ClipTV par TikTok

Une fois l'app validée, ClipTV publie **en public** sur ton compte, avec la légende et les
hashtags. Compte environ 1 h de préparation, puis quelques jours à quelques semaines d'attente.
TikTok peut refuser : dans ce cas, il dit pourquoi, et on corrige.

Les textes à copier sont **en anglais** (les vérificateurs de TikTok lisent l'anglais).

---

## Étape 1 — Mettre le site en ligne (2 min)

Le site est déjà prêt dans le dossier `docs/` du dépôt : accueil, conditions d'utilisation,
politique de confidentialité et page de retour de connexion.

1. Sur GitHub, ouvre ton dépôt **ClipTV** → **Settings** → **Pages**.
2. **Source** : *Deploy from a branch*. **Branch** : `main`, dossier `/docs` → **Save**.
3. Attends 1 à 2 minutes, puis ouvre <https://valentinbugeia.github.io/ClipTV/> : la page
   « Twitch highlights, ready for TikTok » doit s'afficher.

Adresses à utiliser ensuite :

| Quoi | Adresse |
|---|---|
| Site web | `https://valentinbugeia.github.io/ClipTV/` |
| Terms of Service | `https://valentinbugeia.github.io/ClipTV/terms.html` |
| Privacy Policy | `https://valentinbugeia.github.io/ClipTV/privacy.html` |
| Redirect URI | `https://valentinbugeia.github.io/ClipTV/callback.html` |
| Icône de l'app | le fichier `docs/logo.png` du dépôt (1024×1024) |

## Étape 2 — Nouvelle adresse de retour (Redirect URI)

TikTok refuse souvent les apps qui utilisent `example.com`. On passe sur ta propre page.

1. Sur **developers.tiktok.com** → ton app → **Login Kit** → **Redirect URI** : remplace
   l'ancienne par `https://valentinbugeia.github.io/ClipTV/callback.html` (dans le Sandbox
   **et** dans la configuration Production) → **Save**.
2. Dans ClipTV → **Comptes** → **Clés API** → **TikTok — Redirect URI** : colle la même
   adresse → **Enregistrer les clés**.
3. **Comptes** → **Reconnecter** TikTok. Après avoir accepté, tu arrives sur la page ClipTV du
   site : clique **Terminer la connexion dans ClipTV** (ou copie l'adresse et colle-la dans
   Comptes comme avant).

## Étape 3 — Remplir l'app pour la Production

developers.tiktok.com → ton app → onglet **Production** (pas Sandbox).

**App details**

- **App icon** : `docs/logo.png`
- **App name** : `ClipTV`
- **Category** : *Entertainment* (ou *Video* si proposé)
- **Description** (120 caractères max) :

  ```
  Turn Twitch stream highlights into vertical videos with subtitles and publish them to your own TikTok account.
  ```

- **Terms of Service URL** : `https://valentinbugeia.github.io/ClipTV/terms.html`
- **Privacy Policy URL** : `https://valentinbugeia.github.io/ClipTV/privacy.html`
- **Platforms** : coche **Web** → **Website URL** : `https://valentinbugeia.github.io/ClipTV/`

  Si TikTok demande de **vérifier le site** (URL properties / domain verification), il te
  donne un petit fichier (`tiktok....txt`) ou un code : envoie-le moi, je le mets sur le site.

**Products et scopes**

| Produit | Réglage | Scopes |
|---|---|---|
| Login Kit | Redirect URI ci-dessus | `user.info.basic` |
| Content Posting API | **Direct Post activé** | `video.upload`, `video.publish` |
| Display API *(facultatif)* | — | `user.info.stats`, `video.list` |

Conseil : pour maximiser les chances, envoie une première demande **sans Display API**
(moins de choses à justifier). Tu l'ajouteras dans une seconde demande pour l'onglet
Statistiques.

**« Explain how each product and scope works within your app »** (à coller tel quel) :

```
ClipTV is a desktop tool that runs on the creator's own computer. It finds popular public Twitch clips, converts them to vertical 9:16 videos with subtitles and a caption that credits the streamer, and lets the creator publish them to their own TikTok account.

- Login Kit / user.info.basic: the creator connects their TikTok account; we show their nickname and avatar on the publishing screen so they always know which account they post to.
- Content Posting API / video.publish (Direct Post): after reviewing a video, the creator opens the "Publish on TikTok" screen, edits the caption, chooses the privacy level from the options returned by creator_info (no default), the comment/duet/stitch settings (off by default, disabled when the creator turned them off) and the commercial content disclosure, sees the Music Usage Confirmation (and Branded Content Policy) notice, then clicks Publish now or Schedule. Nothing is posted without this step.
- Content Posting API / video.upload: optional mode where the video is sent to the creator's TikTok inbox as a draft, to be finished in the TikTok app.
- Display API / user.info.stats, video.list (only if requested): show the creator the views, likes, comments and shares of their videos in ClipTV's Statistics page.

Tokens and videos are stored only on the creator's computer; there is no ClipTV server.
```

## Étape 4 — Filmer la vidéo de démonstration (5 à 10 min)

TikTok veut voir **tout le parcours dans l'app**, avec chaque produit et chaque scope utilisés.
Enregistre ton écran sur Linux Mint avec **SimpleScreenRecorder** (Gestionnaire de logiciels)
ou **OBS**, en 1080p, sans musique. Garde la barre d'adresse du navigateur visible.

Avant de filmer, comme l'app n'est pas encore validée :
- passe ton compte TikTok en **privé** (sinon TikTok refuse l'envoi) ;
- dans ClipTV → **Comptes** → ligne TikTok → « Les vidéos arrivent » →
  **🚀 publiées directement sur ton profil** → OK.

Déroulé à filmer (parle ou ajoute des sous-titres, en anglais si possible) :

1. **Présentation** : ouvre `https://valentinbugeia.github.io/ClipTV/`, fais défiler, montre
   les liens Terms et Privacy.
2. **Connexion (Login Kit)** : ClipTV → **Comptes** → **Reconnecter** TikTok → la page TikTok
   s'ouvre, montre les autorisations demandées → **Autoriser** → page de retour ClipTV →
   **Terminer la connexion dans ClipTV** → « TikTok connecté ✔ ».
3. **Préparation d'un clip** : onglet **Clips** → **Lancer la recherche** → le panneau montre
   les étapes → le clip arrive dans « À valider » → lis-le quelques secondes.
4. **Publication (Direct Post)** : clique **🚀 Publier** → l'écran **Publier sur TikTok**
   s'ouvre. Montre :
   - le nom du compte (« Publication sur le compte … ») ;
   - la légende modifiable (modifie un mot) ;
   - la liste « Qui peut voir cette vidéo ? » **sans choix par défaut**, puis choisis
     **Moi uniquement** (seul possible avant validation) ;
   - les cases Commenter / Duo / Collage décochées, coche Commenter ;
   - la case **contenu commercial** : coche-la, montre « Ta marque » / « Contenu de marque »
     et l'étiquette qui apparaît, puis décoche-la ;
   - la phrase « En publiant, tu acceptes la Music Usage Confirmation » ;
   - clique **Publier maintenant**.
5. **Résultat** : onglet **Envoi en cours** → **Publiés**, puis ouvre l'app TikTok (ou
   tiktok.com) et montre la vidéo publiée sur le profil, avec sa légende.
6. *(Seulement si tu demandes Display API)* : onglet **Statistiques** → **Actualiser** →
   montre les vues et j'aime.

Exporte en **MP4** (moins de 50 Mo si possible) et joins-la au formulaire.

## Étape 5 — Envoyer

developers.tiktok.com → ton app → **Submit for review**. Tu reçois la réponse par e-mail.

Après validation :
1. repasse ton compte TikTok en **public** ;
2. **Comptes** → **Reconnecter** TikTok (pour obtenir les autorisations de Production) ;
3. vérifie que le mode est **🚀 publiées directement sur ton profil**.

Ensuite, le pilote auto trouve et prépare les clips tout seul ; pour chacun, tu cliques
**Publier** ou **Programmer** et tu choisis la visibilité (TikTok exige ce choix pour chaque
vidéo). Les clips programmés partent ensuite seuls à l'heure prévue.

## Si TikTok refuse

Copie-moi le message de refus : on corrige le point demandé (texte, site, écran ou vidéo) et
tu renvoies la demande.
