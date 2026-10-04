"""Écran « Publier sur TikTok », conforme aux règles de TikTok pour la publication directe.

TikTok exige, avant chaque publication directe (Content Sharing Guidelines), que :
- le compte de destination (pseudo) soit affiché ;
- la visibilité soit choisie par l'utilisateur dans les options renvoyées par TikTok,
  sans valeur présélectionnée ;
- commentaires, duos et collages soient des cases non cochées par défaut, grisées si le
  créateur les a désactivés ;
- la mention de contenu commercial soit proposée (désactivée par défaut) ;
- la phrase d'accord avec la Music Usage Confirmation (et la Branded Content Policy pour
  un contenu de marque) soit affichée près du bouton ;
- la durée de la vidéo respecte ``max_video_post_duration_sec``.
Les choix sont enregistrés pour le clip et utilisés au moment de l'envoi (tout de suite
ou au créneau programmé).
"""

from __future__ import annotations

import html

SETTING = "tiktok_post_options"  # {clip_id: options choisies}

PRIVACY_LABELS = {
    "PUBLIC_TO_EVERYONE": "Tout le monde",
    "MUTUAL_FOLLOW_FRIENDS": "Amis (abonnements réciproques)",
    "FOLLOWER_OF_CREATOR": "Abonnés",
    "SELF_ONLY": "Moi uniquement",
}
MUSIC = "https://www.tiktok.com/legal/page/global/music-usage-confirmation/en"
BRANDED = "https://www.tiktok.com/legal/page/global/bc-policy/en"

STYLE = """<style>
  .ttpost { display:grid; grid-template-columns:minmax(0,300px) minmax(0,1fr); gap:20px; align-items:start }
  @media (max-width:720px) { .ttpost { grid-template-columns:1fr } }
  .ttpost video { width:100%; border-radius:12px; background:#000 }
  .ttpost fieldset { border:1px solid var(--line); border-radius:10px; padding:10px 12px; margin:12px 0 }
  .ttpost legend { color:var(--muted); font-size:13px; padding:0 4px }
  .ttpost .who { display:flex; align-items:center; gap:10px; font-size:15px }
  .ttpost .who img { width:40px; height:40px; border-radius:50% }
  .ttpost .sub { display:block; color:var(--muted); font-size:13px }
  .ttpost .declare { color:var(--muted); font-size:13px; margin:12px 0 }
  .ttpost .label { background:#2a2214; border-radius:8px; padding:8px 10px; font-size:13px; margin-top:8px }
  .ttpost select { width:100% }
</style>"""

SCRIPT = """<script>
(function () {
  const f = document.getElementById('ttform');
  const brand = f.querySelector('[name=commercial]'), opts = document.getElementById('cc-opts');
  const yours = f.querySelector('[name=your_brand]'), paid = f.querySelector('[name=branded]');
  const priv = f.querySelector('[name=privacy]'), self = priv.querySelector('option[value=SELF_ONLY]');
  const label = document.getElementById('cc-label'), extra = document.getElementById('bc-policy');
  const send = f.querySelectorAll('button[type=submit]');
  function update() {
    opts.hidden = !brand.checked;
    const on = brand.checked, b = on && paid.checked, y = on && yours.checked;
    // un contenu de marque ne peut pas être privé
    if (self) { self.disabled = b; if (b && priv.value === 'SELF_ONLY') priv.value = ''; }
    label.textContent = b ? 'Ta vidéo sera étiquetée « Partenariat rémunéré ».'
      : y ? 'Ta vidéo sera étiquetée « Contenu promotionnel ».' : '';
    label.hidden = !label.textContent;
    extra.hidden = !b;
    const ok = priv.value && (!on || paid.checked || yours.checked);
    send.forEach(s => s.disabled = !ok);
  }
  f.addEventListener('change', update); update();
})();
</script>"""


def creator_summary(creator: dict) -> str:
    name = html.escape(creator.get("creator_nickname") or creator.get("creator_username") or "?")
    avatar = creator.get("creator_avatar_url")
    img = f'<img src="{html.escape(avatar)}" alt="">' if avatar else ""
    return f'<div class="who">{img}<span>Publication sur le compte <strong>{name}</strong></span></div>'


def render(clip: dict, creator: dict, video_url: str, then: str, *,
           duration: float | None = None, error: str = "") -> str:
    """Formulaire de publication. ``then`` : publish (maintenant) ou schedule (créneau)."""
    e = html.escape
    if error:
        return (f'{STYLE}<div class="panel"><h2>Publier sur TikTok</h2>'
                f'<div class="flash err">⚠️ {e(error)}</div>'
                '<p><a href="/">← Retour aux clips</a></p></div>')
    max_d = creator.get("max_video_post_duration_sec")
    if duration and max_d and duration > max_d:
        return render(clip, creator, video_url, then, error=(
            f"Cette vidéo dure {duration:.0f} s, ton compte TikTok accepte {max_d} s maximum → "
            "refais le montage plus court ou rejette ce clip."))
    if creator.get("can_post") is False:
        return render(clip, creator, video_url, then, error=(
            "TikTok n'accepte pas de nouvelle publication sur ce compte pour le moment "
            "(limite atteinte) → réessaie plus tard."))
    options = "".join(f'<option value="{e(p)}">{e(PRIVACY_LABELS.get(p, p))}</option>'
                      for p in creator.get("privacy_level_options") or [])

    def box(name: str, label: str, disabled_key: str) -> str:
        off = bool(creator.get(disabled_key))
        note = " (désactivé dans les réglages de ton compte TikTok)" if off else ""
        return (f'<label class="check"><input type="checkbox" name="{name}" value="1"'
                f'{" disabled" if off else ""}> {label}{note}</label>')

    action_label = "🚀 Publier maintenant" if then == "publish" else "⏰ Programmer"
    return f"""{STYLE}<div class="panel"><h2>Publier sur TikTok</h2>
<div class="ttpost">
  <video src="{e(video_url)}" controls playsinline preload="metadata"></video>
  <form method="post" action="/tiktok/post/{e(clip['clip_id'])}" id="ttform">
    {creator_summary(creator)}
    <input type="hidden" name="then" value="{e(then)}">
    <label style="margin-top:12px">Légende
      <textarea name="caption" rows="4" maxlength="2200">{e(clip.get('caption') or '')}</textarea></label>
    <fieldset><legend>Qui peut voir cette vidéo ?</legend>
      <select name="privacy" required aria-label="Visibilité">
        <option value="" selected disabled>Choisis…</option>{options}</select></fieldset>
    <fieldset><legend>Autoriser les utilisateurs à</legend>
      {box("allow_comment", "Commenter", "comment_disabled")}
      {box("allow_duet", "Faire un duo", "duet_disabled")}
      {box("allow_stitch", "Faire un collage", "stitch_disabled")}
    </fieldset>
    <fieldset><legend>Mention de contenu commercial</legend>
      <label class="check"><input type="checkbox" name="commercial" value="1">
        Cette vidéo fait la promotion d'une marque, d'un produit ou d'un service</label>
      <div id="cc-opts" hidden>
        <label class="check"><input type="checkbox" name="your_brand" value="1"><span>Ta marque
          <span class="sub">Tu fais la promotion de toi-même ou de ton activité</span></span></label>
        <label class="check"><input type="checkbox" name="branded" value="1"><span>Contenu de marque
          <span class="sub">Partenariat avec une marque tierce</span></span></label>
        <div class="label" id="cc-label" hidden></div>
      </div>
    </fieldset>
    <p class="declare">En publiant, tu acceptes la
      <a href="{MUSIC}" target="_blank" rel="noopener">Music Usage Confirmation</a> de TikTok<span
      id="bc-policy" hidden> et sa <a href="{BRANDED}" target="_blank" rel="noopener">Branded
      Content Policy</a></span>.</p>
    <div class="bar"><button class="now" type="submit">{action_label}</button>
      <a class="btn small rej" href="/">Annuler</a></div>
    <p class="declare">Après l'envoi, TikTok peut mettre quelques minutes à traiter la vidéo
      avant qu'elle apparaisse sur ton profil.</p>
  </form>
</div></div>{SCRIPT}"""


def parse(form: dict[str, str], creator: dict) -> tuple[dict | None, str]:
    """Options choisies → (options, "") ou (None, message d'erreur)."""
    privacy = form.get("privacy", "")
    if privacy not in (creator.get("privacy_level_options") or []):
        return None, "Choisis qui peut voir la vidéo."
    commercial = form.get("commercial") == "1"
    your_brand = commercial and form.get("your_brand") == "1"
    branded = commercial and form.get("branded") == "1"
    if commercial and not (your_brand or branded):
        return None, "Contenu commercial : coche « Ta marque » et/ou « Contenu de marque »."
    if branded and privacy == "SELF_ONLY":
        return None, "Un contenu de marque ne peut pas être privé : choisis une autre visibilité."
    return {
        "privacy_level": privacy,
        "disable_comment": bool(creator.get("comment_disabled")) or form.get("allow_comment") != "1",
        "disable_duet": bool(creator.get("duet_disabled")) or form.get("allow_duet") != "1",
        "disable_stitch": bool(creator.get("stitch_disabled")) or form.get("allow_stitch") != "1",
        "brand_organic_toggle": your_brand,
        "brand_content_toggle": branded,
    }, ""
