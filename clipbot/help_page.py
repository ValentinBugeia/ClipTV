"""Page « Aide » : configuration pas à pas, fonctionnement et problèmes fréquents.

Écrite pour quelqu'un qui n'a jamais créé de clé d'API. La liste « Ta configuration »
en haut reflète l'état réel de l'app (ce qui est fait / ce qui reste à faire).
"""

from __future__ import annotations

import html

STYLE = """<style>
  .help h2 { margin:0 0 8px; font-size:19px }
  .help .panel { scroll-margin-top:110px }  /* titre visible sous la barre du haut */
  .help h3 { margin:16px 0 6px; font-size:16px }
  .help p, .help li { line-height:1.55 }
  .help ol, .help ul { padding-left:22px; margin:6px 0 }
  .help code { background:rgba(0,0,0,.3); border:1px solid var(--line2); border-radius:6px; padding:1px 6px;
               font-size:14px; overflow-wrap:anywhere }
  .help .toc { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px }
  .help .toc a { color:var(--muted); background:var(--card); border:1px solid var(--line); border-radius:999px; padding:7px 14px;
                 text-decoration:none; font-size:14px }
  .help .check { display:flex; gap:10px; align-items:flex-start; padding:10px 0;
                 border-top:1px solid var(--line) }
  .help .check:first-of-type { border-top:0 }
  .help .check .i { width:24px; flex:none; font-size:18px; text-align:center }
  .help .check .t { flex:1 }
  .help .check a.btn { flex:0 0 auto; min-height:34px; padding:6px 12px; font-size:14px }
  .help .steps { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px }
  .help .step { background:rgba(0,0,0,.25); border:1px solid var(--line); border-radius:12px; padding:14px }
  .help .step b { display:block; margin-bottom:4px }
  .help details.faq { border-top:1px solid var(--line); padding:10px 0 }
  .help details.faq summary { cursor:pointer; font-weight:600 }
  .help details.faq > div { margin-top:8px; color:#d6d6dc }
  .help .note { background:#2a2214; border-radius:8px; padding:10px 12px; margin:10px 0 }
</style>"""


def _check(done: bool, title: str, detail: str, href: str, action: str, optional=False) -> str:
    icon = "✅" if done else ("➖" if optional else "⬜")
    button = "" if done else f'<a class="btn small" href="{href}">{html.escape(action)}</a>'
    return (f'<div class="check"><div class="i">{icon}</div><div class="t"><strong>'
            f'{html.escape(title)}</strong><div class="info">{detail}</div></div>{button}</div>')


def render(status: dict) -> str:
    """``status`` : twitch, tiktok_keys, tiktok_connected, claude, autopilot, stats, password."""
    s = status
    checklist = "".join([
        _check(s["twitch"], "1. Clés Twitch",
               "Pour trouver les clips. Obligatoire.", "#twitch", "Comment faire"),
        _check(s["tiktok_keys"], "2. Clés TikTok",
               "Pour envoyer les vidéos sur ton compte.", "#tiktok", "Comment faire"),
        _check(s["tiktok_connected"], "3. Compte TikTok connecté",
               "Page Comptes → Connecter.", "/accounts", "Aller dans Comptes"),
        _check(s["claude"], "4. Claude (facultatif)",
               html.escape(s["claude_error"]) if s.get("claude_error") else
               "Pour compléter le début ou la fin des clips et écrire les légendes, avec ton "
               "abonnement Claude (Claude Code installé sur ce PC).",
               "#claude", "Comment faire", optional=True),
        _check(s["autopilot"], "5. Pilote automatique activé",
               "Pour que l'app trouve et prépare les clips toute seule.", "/auto",
               "Aller dans Pilote auto"),
    ])
    return f"""{STYLE}<div class="help">
<nav class="toc" aria-label="Sommaire">
  <a href="#config">Ta configuration</a><a href="#fonctionnement">Comment ça marche</a>
  <a href="#twitch">Clés Twitch</a><a href="#tiktok">Clés TikTok</a><a href="#claude">Claude</a>
  <a href="#utiliser">Utiliser l'app</a><a href="#problemes">Problèmes fréquents</a>
</nav>

<div class="panel" id="config"><h2>Ta configuration</h2>
<p class="info">Ce qui est déjà fait est coché. Suis les étapes dans l'ordre, puis clique sur
<strong>Tout vérifier</strong> en bas de la page <a href="/accounts">Comptes</a>.</p>
{checklist}</div>

<div class="panel" id="fonctionnement"><h2>Comment ça marche</h2>
<div class="steps">
  <div class="step"><b>1. Trouver</b>Les clips Twitch <strong>les plus vus</strong> des lives
  diffusés pendant la période choisie (24 h = lives des dernières 24 h, même si la chaîne est
  hors ligne maintenant), autant que de clips demandés.</div>
  <div class="step"><b>2. Compléter</b><strong>Claude</strong> lit ce qui se dit autour du clip
  dans la rediffusion et <strong>ajoute le début ou la fin</strong> qui manque pour qu'on
  comprenne (situation → chute → réaction du streamer, jamais au milieu d'une phrase). Sans
  Claude, l'app le fait elle-même avec les pauses entre les phrases.</div>
  <div class="step"><b>3. Monter</b>Format vertical, cadrage sur le streamer, sous-titres
  animés, accroche au style du jeu, emoji sur la réaction, description et hashtags.</div>
  <div class="step"><b>4. Publier</b>Dans <em>Clips → À publier</em>, <strong>🚀 Préparer</strong>
  télécharge la vidéo, copie la description et ouvre TikTok Studio : glisse la vidéo, colle la
  description, publie, puis clique <strong>✔ Publié</strong>.</div>
</div>
<p>Tout se fait sur <strong>ton ordinateur</strong> : laisse la fenêtre noire (le terminal)
ouverte et le PC allumé pendant que l'app travaille.</p></div>

<div class="panel" id="twitch"><h2>Créer les clés Twitch (5 min, gratuit)</h2>
<ol>
  <li>Ouvre <a href="https://dev.twitch.tv/console/apps" target="_blank" rel="noopener">dev.twitch.tv/console/apps</a>
  et connecte-toi avec ton compte Twitch.
  <div class="note">Twitch demande d'activer la <strong>double authentification</strong> sur ton
  compte avant de créer une app : sur twitch.tv, Paramètres → Sécurité et confidentialité.</div></li>
  <li>Clique sur <strong>Register Your Application</strong> (enregistrer une application) et remplis :
    <ul><li><strong>Name</strong> : un nom unique, par exemple <code>cliptv-tonpseudo</code></li>
    <li><strong>OAuth Redirect URLs</strong> : <code>http://localhost</code></li>
    <li><strong>Category</strong> : <em>Application Integration</em></li>
    <li><strong>Client Type</strong> : <em>Confidential</em></li></ul></li>
  <li>Clique sur <strong>Create</strong>, puis sur <strong>Manage</strong> à côté de ton app.</li>
  <li>Copie le <strong>Client ID</strong>. Clique sur <strong>New Secret</strong> et copie le
  <strong>Client Secret</strong> (il n'est affiché qu'une fois).</li>
  <li>Dans cliptv : <a href="/accounts">Comptes</a> → <strong>Clés API</strong> → colle les deux
  → <strong>Enregistrer les clés</strong>.</li>
</ol></div>

<div class="panel" id="tiktok"><h2>Créer les clés TikTok (15 min, gratuit)</h2>
<ol>
  <li>Ouvre <a href="https://developers.tiktok.com/apps" target="_blank" rel="noopener">developers.tiktok.com</a>
  et connecte-toi avec le compte TikTok sur lequel tu veux publier.</li>
  <li><strong>Manage apps → Connect an app</strong>. Donne un nom à l'app et une icône (tu peux
  utiliser le logo de cliptv : fichier <code>docs/logo.png</code> dans le dossier de l'app).</li>
  <li>En haut de la page de l'app, passe de <strong>Production</strong> à <strong>Sandbox</strong>
  (mode test), puis <strong>Create Sandbox</strong>. <em>Fais toute la suite dans le Sandbox.</em></li>
  <li>Dans <strong>Products → Add products</strong>, ajoute :
    <ul><li><strong>Login Kit</strong> : coche la plateforme <strong>Web</strong> et mets en
    <strong>Redirect URI</strong> : <code>https://valentinbugeia.github.io/ClipTV/callback.html</code></li>
    <li><strong>Content Posting API</strong> (pour envoyer les vidéos)</li>
    <li><strong>Display API</strong> (facultatif, pour l'onglet Statistiques)</li></ul></li>
  <li>Dans <strong>Scopes</strong>, vérifie : <code>user.info.basic</code>, <code>video.upload</code>
  (et pour les statistiques : <code>user.info.stats</code>, <code>video.list</code>).</li>
  <li>Dans <strong>Sandbox settings → Target users</strong>, ajoute <strong>ton compte TikTok</strong>.</li>
  <li>Clique sur <strong>Save</strong>, puis copie la <strong>Client key</strong> et le
  <strong>Client secret</strong> du Sandbox.</li>
  <li>Dans cliptv : <a href="/accounts">Comptes</a> → <strong>Clés API</strong> → colle la Client
  key, le Client secret et la Redirect URI <code>https://valentinbugeia.github.io/ClipTV/callback.html</code>
  → <strong>Enregistrer les clés</strong>.</li>
  <li>Toujours dans Comptes : <strong>Connecter</strong> à côté de TikTok → accepte → tu arrives sur
  une page « Example Domain » : <strong>c'est normal</strong>. Copie toute l'adresse de cette page
  (Ctrl+L puis Ctrl+C), colle-la dans cliptv et clique sur <strong>Valider</strong>, tout de suite
  (le code n'est valable que quelques instants).</li>
</ol>
<div class="note">La connexion TikTok sert aux <strong>statistiques</strong> (note des clips, ce
qui marche) et à repérer les clips déjà publiés. Tant que TikTok n'a pas validé ton app, tu
publies toi-même depuis TikTok Studio (bouton <strong>🚀 Préparer</strong>).</div></div>

<div class="panel" id="claude"><h2>Claude (facultatif)</h2>
<ol>
  <li>Installe Claude Code sur ce PC : sous Windows, dans PowerShell
  <code>irm https://claude.ai/install.ps1 | iex</code> ; sous Linux / Mac
  <code>curl -fsSL https://claude.ai/install.sh | bash</code></li>
  <li>Dans un terminal, tape <code>claude</code> puis <code>/login</code> et connecte ton compte.</li>
  <li>C'est tout : cliptv l'utilise tout seul (quota de ton abonnement, pas de crédit API).
  La page <a href="/accounts">Comptes</a> indique s'il est trouvé.</li>
</ol></div>

<div class="panel" id="utiliser"><h2>Utiliser l'app</h2>
<h3>Les onglets</h3>
<ul>
  <li><strong>Clips</strong> : <em>À publier</em> (clips prêts), <em>Publiés</em>,
  <em>Historique</em> (les 10 derniers clips des recherches précédentes ou écartés,
  récupérables).</li>
  <li><strong>Pilote auto</strong> : le mode automatique (marche/pause), ses réglages et la grille
  d'affluence TikTok pour choisir tes heures de publication.</li>
  <li><strong>Statistiques</strong> : vues, j'aime, meilleures vidéos, ce qui marche le mieux.</li>
  <li><strong>Comptes</strong> : tes clés, la connexion TikTok, le mot de passe d'accès et le
  bouton <strong>Tout vérifier</strong>.</li>
</ul>
<h3>Sous chaque clip</h3>
<ul>
  <li>En haut à droite : les <strong>vues du clip sur Twitch</strong>. Les clips sont
  triés par vues.</li>
  <li><strong>👁 Aperçu TikTok</strong> sur la vidéo : l'interface de TikTok par-dessus, pour
  vérifier que rien ne cache les sous-titres.</li>
  <li><strong>🚀 Préparer</strong> : télécharge la vidéo, copie la description et ouvre TikTok
  Studio. Il ne reste qu'à glisser la vidéo (dossier Téléchargements) et coller (Ctrl+V).</li>
  <li><strong>✔ Publié</strong> : une fois en ligne, pour ranger le clip dans « Publiés ».</li>
  <li>En petit : <strong>Vidéo seule</strong>, <strong>Description seule</strong>, et sur
  téléphone <strong>📲 Partager vers TikTok</strong> quand le navigateur le permet.</li>
  <li><strong>⋯</strong> : ouvrir TikTok Studio, <strong>refaire le montage</strong> (autre
  cadrage, avec ou sans sous-titres) ou rejeter.</li>
  <li>Tu peux <strong>modifier la description</strong> dans la zone de texte avant de préparer.</li>
</ul>
<h3>Recherche ponctuelle</h3>
<p>Laisse la case vide pour les temps forts du moment, ou tape une <strong>chaîne</strong>, un
<strong>jeu</strong> ou un <strong>mot-clé</strong>, séparés par des virgules (ex.
<code>gotaga, Valorant, fou rire</code>). Chaque nouvelle recherche remplace « À publier » ;
les anciens clips vont dans « Historique ».</p>
<h3>Pendant une recherche</h3>
<p>L'étape en cours s'affiche en haut à droite ; clique dessus pour le détail.
<strong>⏹</strong> arrête tout de suite (les clips déjà prêts sont gardés).</p>
<h3>Lancer l'app</h3>
<p>Dans un terminal : <code>cd ~/cliptv &amp;&amp; git pull &amp;&amp; ./cliptv.sh</code> (le
<code>git pull</code> installe les dernières améliorations). Puis ouvre
<a href="/">http://localhost:8000</a>.</p></div>

<div class="panel" id="problemes"><h2>Problèmes fréquents</h2>
<details class="faq"><summary>Une ligne est rouge dans « Tout vérifier »</summary><div>
Lis le message à droite : il dit quelle clé ou quel compte pose problème et quoi faire. Le plus
souvent, une clé a été mal copiée (espace en trop, caractère manquant) : recopie-la dans
<a href="/accounts">Comptes → Clés API</a>.</div></details>
<details class="faq"><summary>« Le code TikTok a expiré ou a déjà servi »</summary><div>
Le code reçu sur la page de retour ne dure que quelques instants et ne sert qu'une fois. Reclique
sur <strong>Connecter</strong>, accepte, puis colle tout de suite la nouvelle adresse et clique
une seule fois sur <strong>Valider</strong>.</div></details>
<details class="faq"><summary>La vidéo n'a pas de son (badge 🔇)</summary><div>
Twitch a fourni le clip sans piste audio. Rejette-le (menu ⋯ → Rejeter) ; les prochains clips sont
vérifiés automatiquement.</div></details>
<details class="faq"><summary>Les sous-titres apparaissent en double</summary><div>
ClipTV repère les streams qui ont déjà leurs sous-titres (il n'en ajoute pas, et les garde
au-dessus de la description TikTok), mais il peut en rater. Menu ⋯ → <strong>Refaire le
montage</strong>, décoche <strong>Sous-titres</strong>.</div></details>
<details class="faq"><summary>Le cadrage n'est pas bon (mauvais visage, découpage inutile)</summary><div>
Menu ⋯ → <strong>Refaire le montage</strong> → choisis <strong>Zoom plein écran</strong> (ou une
autre option) → Refaire.</div></details>
<details class="faq"><summary>La recherche est longue</summary><div>
Compte 1 à 3 minutes par clip sur un PC récent, plus sur un PC ancien (l'étape en cours
s'affiche en haut à droite ; clique dessus pour le détail). Branche le portable sur le
secteur. La toute première fois, l'app télécharge les modèles de transcription : quelques
minutes de plus.</div></details>
<details class="faq"><summary>Un clip n'a pas pu être monté</summary><div>
Il n'apparaît pas dans « À publier » : la cause est notée dans le journal de la fenêtre du
lanceur. ClipTV pourra le reproposer lors d'une prochaine recherche.</div></details>
<details class="faq"><summary>Ouvrir l'app depuis mon téléphone ou un autre PC</summary><div>
Les deux appareils doivent être sur le même Wi-Fi. Dans <a href="/accounts">Comptes</a> →
« Accès depuis d'autres appareils », choisis un mot de passe : l'adresse à ouvrir s'affiche
(du style <code>http://192.168.1.20:8000</code>).</div></details>
<details class="faq"><summary>J'utilise cliptv sur deux PC</summary><div>
Chaque PC a ses propres réglages et clés. Avec le <strong>même compte TikTok</strong>, n'active
le pilote automatique que sur <strong>un seul</strong> PC, sinon les mêmes clips partent en double.</div></details>
<details class="faq"><summary>L'app s'arrête toute seule</summary><div>
Elle tourne tant que le terminal reste ouvert et que le PC ne se met pas en veille. Désactive la
mise en veille dans les réglages d'alimentation de ton PC.</div></details>
<details class="faq"><summary>Droits d'auteur</summary><div>
Les clips appartiennent aux streamers. La chaîne est créditée dans chaque légende, mais
republier sans accord peut entraîner des retraits ou une suspension du compte TikTok. Beaucoup de
streamers acceptent les « clippeurs » : demande-leur.</div></details>
</div>
</div>"""
