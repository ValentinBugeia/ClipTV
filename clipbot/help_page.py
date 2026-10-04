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
  .help code { background:#0e0e10; border:1px solid #2a2a2d; border-radius:6px; padding:1px 6px;
               font-size:14px; overflow-wrap:anywhere }
  .help .toc { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px }
  .help .toc a { color:#adadb8; background:var(--card); border-radius:999px; padding:6px 12px;
                 text-decoration:none; font-size:14px }
  .help .check { display:flex; gap:10px; align-items:flex-start; padding:10px 0;
                 border-top:1px solid #2a2a2d }
  .help .check:first-of-type { border-top:0 }
  .help .check .i { width:24px; flex:none; font-size:18px; text-align:center }
  .help .check .t { flex:1 }
  .help .check a.btn { flex:0 0 auto; min-height:34px; padding:6px 12px; font-size:14px }
  .help .steps { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px }
  .help .step { background:#0e0e10; border-radius:10px; padding:12px }
  .help .step b { display:block; margin-bottom:4px }
  .help details.faq { border-top:1px solid #2a2a2d; padding:10px 0 }
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
        _check(s["claude"], "4. Clé Claude (facultatif)",
               html.escape(s["claude_error"]) if s.get("claude_error") else
               "Pour des légendes et hashtags écrits par l'IA. Sans elle : légende standard.",
               "#claude", "Comment faire", optional=True),
        _check(s["autopilot"], "5. Pilote automatique activé",
               "Pour que l'app trouve et prépare les clips toute seule.", "/auto",
               "Aller dans Pilote auto"),
    ])
    return f"""{STYLE}<div class="help">
<nav class="toc" aria-label="Sommaire">
  <a href="#config">Ta configuration</a><a href="#fonctionnement">Comment ça marche</a>
  <a href="#twitch">Clés Twitch</a><a href="#tiktok">Clés TikTok</a><a href="#claude">Clé Claude</a>
  <a href="#utiliser">Utiliser l'app</a><a href="#problemes">Problèmes fréquents</a>
</nav>

<div class="panel" id="config"><h2>Ta configuration</h2>
<p class="info">Ce qui est déjà fait est coché. Suis les étapes dans l'ordre, puis clique sur
<strong>Tout vérifier</strong> en bas de la page <a href="/accounts">Comptes</a>.</p>
{checklist}</div>

<div class="panel" id="fonctionnement"><h2>Comment ça marche</h2>
<div class="steps">
  <div class="step"><b>1. Trouver</b>L'app regarde les lives Twitch les plus suivis et repère
  les clips que les spectateurs partagent le plus en ce moment.</div>
  <div class="step"><b>2. Monter</b>Elle télécharge le clip, le met au format téléphone
  (vertical), cadre le streamer et ajoute des sous-titres animés.</div>
  <div class="step"><b>3. Écrire</b>Elle prépare la légende avec des hashtags (par l'IA Claude
  si tu as mis sa clé).</div>
  <div class="step"><b>4. Publier</b>Aux heures choisies, elle envoie la vidéo sur ton compte
  TikTok. Tu la publies d'un tap depuis l'app TikTok.</div>
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
    <strong>Redirect URI</strong> : <code>https://example.com/tiktok/callback</code></li>
    <li><strong>Content Posting API</strong> (pour envoyer les vidéos)</li>
    <li><strong>Display API</strong> (facultatif, pour l'onglet Statistiques)</li></ul></li>
  <li>Dans <strong>Scopes</strong>, vérifie : <code>user.info.basic</code>, <code>video.upload</code>
  (et pour les statistiques : <code>user.info.stats</code>, <code>video.list</code>).</li>
  <li>Dans <strong>Sandbox settings → Target users</strong>, ajoute <strong>ton compte TikTok</strong>.</li>
  <li>Clique sur <strong>Save</strong>, puis copie la <strong>Client key</strong> et le
  <strong>Client secret</strong> du Sandbox.</li>
  <li>Dans cliptv : <a href="/accounts">Comptes</a> → <strong>Clés API</strong> → colle la Client
  key, le Client secret et la Redirect URI <code>https://example.com/tiktok/callback</code>
  → <strong>Enregistrer les clés</strong>.</li>
  <li>Toujours dans Comptes : <strong>Connecter</strong> à côté de TikTok → accepte → tu arrives sur
  une page « Example Domain » : <strong>c'est normal</strong>. Copie toute l'adresse de cette page
  (Ctrl+L puis Ctrl+C), colle-la dans cliptv et clique sur <strong>Valider</strong>, tout de suite
  (le code n'est valable que quelques instants).</li>
</ol>
<div class="note">Tant que TikTok n'a pas validé ton app, les vidéos arrivent <strong>en
brouillon</strong> : une notification dans l'app TikTok de ton téléphone, où tu publies d'un tap.</div></div>

<div class="panel" id="claude"><h2>Créer la clé Claude (facultatif, payant à l'usage)</h2>
<ol>
  <li>Ouvre <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener">console.anthropic.com</a>
  et crée un compte.</li>
  <li>Dans <strong>Billing</strong>, ajoute quelques euros de crédit : une légende coûte une
  fraction de centime à quelques centimes.</li>
  <li><strong>API Keys → Create Key</strong>, copie la clé (elle commence par <code>sk-ant-</code>,
  affichée une seule fois).</li>
  <li>Dans cliptv : <a href="/accounts">Comptes</a> → <strong>Clés API</strong> → colle-la →
  <strong>Enregistrer les clés</strong>.</li>
</ol></div>

<div class="panel" id="utiliser"><h2>Utiliser l'app</h2>
<h3>Les onglets</h3>
<ul>
  <li><strong>Clips</strong> : les vidéos préparées. <em>À valider</em> (prêtes), <em>Programmés</em>
  (partiront à l'heure prévue), <em>Envoi en cours</em>, <em>Publiés</em>, <em>Rejetés</em>,
  <em>Erreurs</em>.</li>
  <li><strong>Pilote auto</strong> : le mode automatique (marche/pause), ses réglages et la grille
  d'affluence TikTok pour choisir tes heures de publication.</li>
  <li><strong>Statistiques</strong> : vues, j'aime, meilleures vidéos, ce qui marche le mieux.</li>
  <li><strong>Comptes</strong> : tes clés, la connexion TikTok, le mot de passe d'accès et le
  bouton <strong>Tout vérifier</strong>.</li>
</ul>
<h3>Sous chaque clip</h3>
<ul>
  <li><strong>⏰ Programmer</strong> : le clip partira au prochain créneau libre.</li>
  <li><strong>🚀 Publier</strong> : envoi tout de suite vers TikTok.</li>
  <li><strong>⋯</strong> : télécharger la vidéo, copier la légende, marquer comme publié (si tu
  l'as postée toi-même), <strong>refaire le montage</strong> (autre cadrage, avec ou sans
  sous-titres) ou rejeter.</li>
  <li>Tu peux <strong>modifier la légende</strong> dans la zone de texte avant de programmer ou publier.</li>
</ul>
<h3>Pendant une recherche</h3>
<p>Un panneau au centre montre chaque étape. <strong>Masquer</strong> le cache,
<strong>⏹ Arrêter</strong> stoppe tout de suite (les clips déjà prêts sont gardés).</p>
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
Le code dans l'adresse example.com ne dure que quelques instants et ne sert qu'une fois. Reclique
sur <strong>Connecter</strong>, accepte, puis colle tout de suite la nouvelle adresse et clique
une seule fois sur <strong>Valider</strong>.</div></details>
<details class="faq"><summary>ClipTV dit « publié » mais rien n'arrive dans TikTok</summary><div>
Tant que TikTok n'a pas <strong>validé ton app</strong> (elle est en Sandbox), TikTok accepte les
vidéos mais ne les livre que si ton compte est <strong>privé</strong>. Avec un compte public, rien
n'arrive, sans message d'erreur. Pour publier automatiquement sur un compte public, il faut faire
valider l'app par TikTok (developers.tiktok.com → ton app → Production → envoi en validation).
</div></details>
<details class="faq"><summary>Je veux voir mes vidéos sur PC, pas seulement sur le téléphone</summary><div>
Les brouillons TikTok ne s'ouvrent que dans l'app du téléphone. Pour tout gérer depuis le PC :
<a href="/accounts">Comptes</a> → ligne TikTok → « Les vidéos arrivent <strong>en privé sur ton
profil</strong> » → OK. Ensuite : sur developers.tiktok.com, dans Content Posting API, active
<strong>Direct Post</strong> (scope <code>video.publish</code>) ; passe ton compte TikTok en
<strong>privé</strong> (obligatoire tant que TikTok n'a pas validé ton app) ; puis
<strong>Reconnecter</strong> TikTok. Les vidéos apparaissent alors en privé sur ton profil, sur
tiktok.com : ouvre-en une → ⋯ → Paramètres de confidentialité pour la rendre publique.</div></details>
<details class="faq"><summary>J'ai publié mais je ne vois pas la vidéo sur mon profil TikTok</summary><div>
C'est normal en mode brouillon : la vidéo est dans les <strong>notifications de l'app TikTok</strong>
sur ton téléphone. Ouvre-la et publie-la d'un tap.</div></details>
<details class="faq"><summary>La vidéo n'a pas de son (badge 🔇)</summary><div>
Twitch a fourni le clip sans piste audio. Rejette-le (menu ⋯ → Rejeter) ; les prochains clips sont
vérifiés automatiquement.</div></details>
<details class="faq"><summary>Les sous-titres apparaissent en double</summary><div>
Le streamer affichait déjà ses propres sous-titres. Menu ⋯ → <strong>Refaire le montage</strong>,
décoche <strong>Sous-titres</strong>. Pour tous les clips : Pilote auto → décoche « Ajouter des
sous-titres animés ».</div></details>
<details class="faq"><summary>Le cadrage n'est pas bon (mauvais visage, découpage inutile)</summary><div>
Menu ⋯ → <strong>Refaire le montage</strong> → choisis <strong>Zoom plein écran</strong> (ou une
autre option) → Refaire.</div></details>
<details class="faq"><summary>La recherche est longue</summary><div>
Compte 1 à 3 minutes par clip (le panneau central montre l'étape en cours). La toute première
fois, l'app télécharge le modèle de transcription (environ 500 Mo) : quelques minutes de plus.</div></details>
<details class="faq"><summary>Un clip est dans « Erreurs »</summary><div>
Le message sous le clip explique ce qui s'est passé. Si c'est un problème de connexion
passager, clique sur <strong>Réessayer</strong>.</div></details>
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
