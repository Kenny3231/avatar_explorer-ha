// Lit est chargé depuis un CDN, faute de moyen fiable de réutiliser celui du
// frontend.
//
// NE PAS remplacer par Object.getPrototypeOf(customElements.get("ha-panel-lovelace"))
// pour en tirer html et css : ce motif date de lit-element 2.x. Depuis Lit 2,
// et donc a fortiori sur Home Assistant 2026.x qui embarque Lit 3, html et css
// sont des exports autonomes et n'existent PAS sur LitElement.prototype. Ils
// valent alors undefined, et la carte échoue au premier appel de html`...`
// sans rien afficher.
//
// Contrepartie assumée : la carte ne s'affiche pas sans accès internet.
import {
  LitElement,
  html,
  css,
} from "https://unpkg.com/lit-element@2.4.0/lit-element.js?module";

// ==========================================
// 0. OUTILS PARTAGÉS (i18n, découverte, URL)
// ==========================================

// i18n légère : français si la langue de HA commence par « fr », anglais sinon.
const STRINGS = {
  fr: {
    loading_hass: "Chargement...",
    loading: "Chargement des poses…",
    user: "Profil",
    category: "Catégorie",
    all_categories: "Toutes catégories",
    search_label: "Rechercher une pose",
    search_ph: "Rechercher (titre ou mot-clé)...",
    fetch_failed: "Liste des poses indisponible ({error})",
    retry: "Réessayer",
    more: "Voir plus ({n} restant{s})",
    no_result: "Aucun résultat pour cette recherche.",
    no_poses: "Aucune pose dans ce dossier.",
    close: "Fermer",
    profile_of: "PROFIL {name}",
    send_to_short: "ENVOYER {name}",
    set_profile: "METTRE EN PROFIL",
    send_to: "ENVOYER À {name}",
    ok_avatar: "Avatar mis à jour",
    ok_emoji: "Emoji envoyé",
    err_action: "Échec de l'action : {error}",
    ed_show_duo: "Afficher le mode Duo",
    ed_duo_label: "Nom affiché pour Duo",
    ed_users: "Gestion des Utilisateurs",
    ed_folder: "Dossier : {id}",
    ed_name_ph: "Nom sur tablette (ex: Papa)",
    ed_no_phone: "-- Aucun téléphone --",
    ed_default: "Définir {name} comme utilisateur par défaut",
    ed_remove: "Supprimer {name}",
    ed_notify: "Service de notification de {name}",
    ed_name_of: "Nom affiché pour {id}",
    ed_add: "+ Ajouter un utilisateur existant...",
    ed_all_added: "Tous les profils de l'intégration sont ajoutés.",
    card_desc: "Choisis une pose Avatar Explorer, mets-la en profil ou envoie-la.",
  },
  en: {
    loading_hass: "Loading...",
    loading: "Loading poses…",
    user: "Profile",
    category: "Category",
    all_categories: "All categories",
    search_label: "Search poses",
    search_ph: "Search (title or keyword)...",
    fetch_failed: "Pose list unavailable ({error})",
    retry: "Retry",
    more: "Show more ({n} remaining)",
    no_result: "No results for this search.",
    no_poses: "No poses in this folder.",
    close: "Close",
    profile_of: "PROFILE {name}",
    send_to_short: "SEND {name}",
    set_profile: "SET AS PROFILE",
    send_to: "SEND TO {name}",
    ok_avatar: "Avatar updated",
    ok_emoji: "Emoji sent",
    err_action: "Action failed: {error}",
    ed_show_duo: "Show Duo mode",
    ed_duo_label: "Display name for Duo",
    ed_users: "User management",
    ed_folder: "Folder: {id}",
    ed_name_ph: "Name on tablet (e.g. Dad)",
    ed_no_phone: "-- No phone --",
    ed_default: "Set {name} as default user",
    ed_remove: "Remove {name}",
    ed_notify: "Notification service for {name}",
    ed_name_of: "Display name for {id}",
    ed_add: "+ Add an existing user...",
    ed_all_added: "All integration profiles have been added.",
    card_desc: "Pick an Avatar Explorer pose, set it as profile or send it.",
  },
};

function uiLang(hass) {
  const l = (hass && (hass.language || (hass.locale && hass.locale.language))) || "en";
  return String(l).toLowerCase().startsWith("fr") ? "fr" : "en";
}

function tr(hass, key, params) {
  const dict = STRINGS[uiLang(hass)];
  let out = dict[key] ?? STRINGS.en[key] ?? key;
  for (const [k, v] of Object.entries(params || {})) {
    out = out.replace(`{${k}}`, v);
  }
  return out;
}

// Nom de fichier d'une pose : un seul segment, .png. Refuse « ../x.png »,
// « a/b.png » et tout ce qui pourrait sortir du dossier de l'utilisateur.
const FICHIER_RE = /^[^/\\]+\.png$/;

// Dossier du catalogue pour le mode Duo : l'intégration l'expose en attribut
// du capteur de synchro ; repli sur la clé `dir` de la carte, puis le défaut.
function catalogDir(hass, config) {
  const fromSensor = hass?.states?.["sensor.avatar_explorer_sync"]?.attributes?.catalog_dir;
  const raw = (typeof fromSensor === "string" && fromSensor) || config?.dir || "images/avatar";
  return raw.replace(/^\/+|\/+$/g, "").replace(/^local\//, "");
}

// Un seul balayage de hass.states partagé par la carte et son éditeur : sur une
// instance chargée (plusieurs milliers d'entités), le refaire à chaque rendu et
// dans chaque classe coûte cher pour un résultat qui bouge très rarement.
//
// Découverte : suffixe « _dynamique » (historique) OU entité enregistrée par
// l'intégration (hass.entities, plus robuste si l'entity_id a été renommé).
function collectUsers(hass) {
  if (!hass) return [];
  return Object.keys(hass.states)
    .filter((eid) => {
      if (!eid.startsWith("sensor.")) return false;
      if (eid.endsWith("_dynamique")) return true;
      return (
        hass.entities?.[eid]?.platform === "avatar_explorer" &&
        hass.states[eid].attributes?.folder_id !== undefined
      );
    })
    .map((eid) => {
      const s = hass.states[eid];
      return {
        entityId: eid,
        id: s.attributes.folder_id,
        label: (s.attributes.friendly_name || "").replace(" Dynamique", ""),
        directory: s.attributes.directory,
      };
    });
}

// « 🧔 Kenny » -> « Kenny ». L'ancien split(' ')[1] cassait sur les libellés
// sans emoji ou à prénom composé ; on retire simplement ce qui précède la
// première lettre ou le premier chiffre.
function shortLabel(label) {
  const cleaned = (label || "").replace(/^[^\p{L}\p{N}]+/u, "").trim();
  return cleaned || label || "";
}


// URL d'une pose : /local/<dossier du catalogue>/<utilisateur ou Duo>/<fichier>
function poseUrl(baseDir, folderName, fichier) {
  return `/local/${baseDir}/${folderName}/${fichier}`;
}

// Nettoie le catalogue : écarte les entrées dont le fichier est absent ou
// suspect (« ../x.png », sous-dossier...) et donne un titre de repli quand
// `titre` manque.
function cleanItems(raw) {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((i) => i && typeof i.fichier === "string" && FICHIER_RE.test(i.fichier))
    .map((i) => (i.titre ? i : { ...i, titre: i.fichier.replace(/\.png$/, "") }));
}

function userLabel(u) {
  return (u && (u.label || u.user_id_folder)) || "";
}

// ==========================================
// 1. LA CARTE PRINCIPALE
// ==========================================
class AvatarCard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
      _metadata: { type: Array },
      _search: { type: String },
      _category: { type: String },
      _currentUser: { type: String },
      _showLightbox: { type: Boolean },
      _selectedItem: { type: Object },
      _lastFetch: { type: Object },
      _limit: { type: Number },
      _loading: { type: Boolean },
      _busy: { type: Boolean }
    };
  }

  // Nombre d'items rendus d'emblée. Le catalogue en compte ~1260 par dossier :
  // tout afficher crée autant de noeuds DOM pour une quinzaine de visibles.
  static get PAGE_SIZE() { return 60; }

  static getConfigElement() {
    return document.createElement("avatar-card-editor");
  }

  /** Configuration proposée dans le sélecteur de cartes : on préremplit avec
   *  les profils déjà créés par l'intégration, le premier étant par défaut. */
  static getStubConfig(hass) {
    const users = collectUsers(hass)
      .filter((u) => u.id)
      .map((u, i) => ({
        user_id_folder: u.id,
        label: u.label || u.id,
        is_default: i === 0,
        notify_service: "",
      }));
    return { dir: "images/avatar", show_duo: true, users };
  }

  constructor() {
    super();
    this._metadata = [];
    this._search = "";
    this._category = "";
    this._showLightbox = false;
    this._lastFetch = null;
    this._limit = AvatarCard.PAGE_SIZE;
    // Dossier dont le chargement a déjà été tenté (réussi OU échoué). Sert à
    // ne pas relancer le fetch en boucle : déduire l'état d'un _metadata vide
    // ne distingue pas « pas encore chargé » de « chargé et vide / en erreur ».
    this._loadedFor = null;
    this._loading = false;
    this._busy = false;
    this._usersCache = null;
    this._usersCacheFor = null;
    this._trackedIds = null;
    this._returnFocus = null;
    this._onKeyDown = this._onKeyDown.bind(this);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    // La lightbox pose un écouteur sur document : le retirer si la carte est
    // détruite alors qu'elle est ouverte, sinon l'écouteur survit à la carte.
    document.removeEventListener("keydown", this._onKeyDown);
  }

  _t(key, params) {
    return tr(this.hass, key, params);
  }

  setConfig(config) {
    if (!config) throw new Error("Configuration invalide");
    this.config = {
      dir: "images/avatar",
      show_duo: true,
      duo_label: "👩‍❤️‍👨 Duo",
      users: [],
      ...config
    };

    if (this.config.users && this.config.users.length > 0 && !this._currentUser) {
      const def = this.config.users.find(u => u.is_default) || this.config.users[0];
      this._currentUser = def.user_id_folder;
    }
  }

  updated(changedProperties) {
    // hass change en permanence dans HA : la condition doit porter sur ce qui
    // a réellement été chargé, sinon un dossier vide ou en erreur relance une
    // requête à chaque tick.
    if (
      changedProperties.has("hass") &&
      this.hass &&
      this._currentUser &&
      !this._loading &&
      this._loadedFor !== this._currentUser
    ) {
      this._loadMetadata();
    }
  }

  /** Liste des utilisateurs, recalculée seulement quand hass change vraiment. */
  _getUsersFromHass() {
    if (!this.hass) return [];
    if (this._usersCache && this._usersCacheFor === this.hass.states) {
      return this._usersCache;
    }
    this._usersCache = collectUsers(this.hass);
    this._usersCacheFor = this.hass.states;
    // On suit aussi le capteur de synchro : il porte `catalog_dir` (mode Duo).
    this._trackedIds = [
      ...this._usersCache.map((u) => u.entityId),
      "sensor.avatar_explorer_sync",
    ];
    return this._usersCache;
  }

  /** hass est remplacé à chaque changement d'état de N'IMPORTE quelle entité.
   *  Sans ce filtre, la carte refiltre 1260 items et redessine la grille à
   *  chaque fois qu'une lampe change d'état ailleurs dans la maison.
   *
   *  Compromis assumé : si un nouveau capteur *_dynamique apparaît sans qu'aucun
   *  de ceux déjà suivis ne change, il ne sera visible qu'au prochain rendu
   *  (rechargement du tableau de bord, ou toute autre interaction avec la carte). */
  shouldUpdate(changedProps) {
    if (!changedProps.has("hass") || changedProps.size > 1) return true;
    const old = changedProps.get("hass");
    if (!old || !this._trackedIds || this._trackedIds.length === 0) return true;
    return this._trackedIds.some((eid) => old.states[eid] !== this.hass.states[eid]);
  }

  /** Utilisé par HA pour répartir les cartes en colonnes (vue Masonry). */
  getCardSize() {
    return 12;
  }

  /** Dimensions pour la vue Sections : pleine largeur par défaut, hauteur
   *  libre (la grille défile dans la carte). */
  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  /** Dossier de base des images : celui de l'utilisateur (attribut du capteur
   *  *_dynamique) ; pour Duo, celui du catalogue exposé par l'intégration. */
  _baseDir(isDuo, userObj) {
    if (!isDuo && userObj && userObj.directory) return userObj.directory;
    return catalogDir(this.hass, this.config);
  }

  async _loadMetadata() {
    if (!this._currentUser || this._loading) return;

    const target = this._currentUser;
    const isDuo = target === 'Duo';
    const folderName = isDuo ? 'Duo' : target;
    const usersHass = this._getUsersFromHass();
    const userObj = usersHass.find(u => u.id === target);
    const baseDir = this._baseDir(isDuo, userObj);

    // Volontairement non affiché dans la carte : l'état de la récupération est
    // conservé dans this._lastFetch et tracé en console (F12, filtrer sur
    // « avatar-card ») pour le diagnostic.
    const url = `/local/${baseDir}/${folderName}/metadata_${folderName}.json`;
    const started = performance.now();

    this._loading = true;
    try {
      const response = await fetch(url);
      if (response.ok) {
        this._metadata = cleanItems(await response.json());
        this._lastFetch = {
          date: new Date(),
          success: true,
          url,
          count: this._metadata.length,
          ms: Math.round(performance.now() - started),
        };
        console.info(
          `[avatar-card] ${folderName} : ${this._lastFetch.count} poses chargées ` +
            `en ${this._lastFetch.ms} ms (${url})`
        );
      } else {
        this._metadata = [];
        this._lastFetch = { date: new Date(), success: false, url, error: `HTTP ${response.status}` };
        console.error(`[avatar-card] échec ${url} : HTTP ${response.status}`);
      }
    } catch (e) {
      this._metadata = [];
      this._lastFetch = { date: new Date(), success: false, url, error: e.message };
      console.error(`[avatar-card] échec ${url} :`, e);
    } finally {
      this._loading = false;
      // Marqué même en cas d'échec : c'est ce qui coupe la boucle. Le bouton
      // « Réessayer » reste le moyen explicite de relancer.
      this._loadedFor = target;
    }
    this.requestUpdate();
  }

  _retry() {
    this._loadedFor = null;
    this._loadMetadata();
  }

  _openLightbox(item) {
    // Mémorise l'élément focalisé (la tuile) pour lui rendre le focus ensuite.
    this._returnFocus = this.shadowRoot.activeElement || null;
    this._selectedItem = item;
    this._showLightbox = true;
    document.addEventListener("keydown", this._onKeyDown);
    // Focus initial sur le bouton de fermeture, une fois la modale rendue.
    this.updateComplete.then(() => {
      const btn = this.shadowRoot.querySelector(".close-btn");
      if (btn) btn.focus();
    });
  }

  _closeLightbox() {
    this._showLightbox = false;
    document.removeEventListener("keydown", this._onKeyDown);
    const back = this._returnFocus;
    this._returnFocus = null;
    this.updateComplete.then(() => {
      if (back && back.isConnected && typeof back.focus === "function") back.focus();
    });
  }

  _onKeyDown(e) {
    if (!this._showLightbox) return;
    if (e.key === "Escape") {
      e.stopPropagation();
      this._closeLightbox();
    } else if (e.key === "Tab") {
      // Piège de focus simple : Tab boucle dans la modale.
      const focusables = [...this.shadowRoot.querySelectorAll(".modal button:not([disabled])")];
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = this.shadowRoot.activeElement;
      if (e.shiftKey && (active === first || !active)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (active === last || !active)) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  /** Normalise pour une recherche insensible à la casse ET aux accents :
   *  le catalogue contient « hâte », « à très vite »... que personne ne tape
   *  avec les accents dans un champ de recherche. */
  static _norm(str) {
    return (str || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "");
  }

  static get styles() {
    return css`
      :host {
        --avatar-primary: var(--primary-color);
        --avatar-card-bg: var(--ha-card-background, var(--card-background-color, white));
        --avatar-text: var(--primary-text-color);
        --avatar-secondary-text: var(--secondary-text-color);
        --avatar-border: var(--divider-color, rgba(0,0,0,0.1));
      }

      ha-card {
        padding: 16px;
        border-radius: var(--ha-card-border-radius, 12px);
        box-shadow: var(--ha-card-box-shadow, none);
        border: var(--ha-card-border-width, 1px) solid var(--avatar-border);
      }

      .header-controls { display: flex; flex-direction: column; gap: 10px; margin-bottom: 15px; }
      @media (min-width: 600px) { .header-controls { flex-direction: row; } }

      select, input {
        width: 100%;
        min-height: 44px;
        background: var(--secondary-background-color);
        border: 1px solid var(--avatar-border);
        border-radius: 8px;
        padding: 10px;
        color: var(--avatar-text);
        font-weight: bold;
        box-sizing: border-box;
      }
      /* Le contour natif est supprimé : on le remplace par un focus visible. */
      select:focus-visible, input:focus-visible, button:focus-visible {
        outline: 2px solid var(--avatar-primary);
        outline-offset: 2px;
      }

      /* Affiché uniquement en cas d'échec : rien ne s'affiche quand tout va
         bien. Le bouton est le seul moyen de relancer, un dossier n'étant
         tenté qu'une fois (cf. _loadedFor). */
      .fetch-error {
        display: flex;
        align-items: center;
        gap: 10px;
        flex-wrap: wrap;
        margin-bottom: 12px;
        padding: 8px 10px;
        border-radius: 8px;
        font-size: 12px;
        font-weight: bold;
        color: var(--error-color, #db4437);
        border: 1px solid currentColor;
      }
      .retry {
        min-height: 44px;
        min-width: 44px;
        padding: 4px 14px;
        font: inherit;
        cursor: pointer;
        border-radius: 6px;
        border: 1px solid currentColor;
        background: none;
        color: inherit;
      }
      @media (hover: hover) {
        .retry:hover { background: color-mix(in srgb, currentColor 12%, transparent); }
      }
      .retry:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }

      .loading {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
        padding: 24px 8px;
        font-size: 13px;
        color: var(--avatar-secondary-text);
      }
      .spinner {
        width: 18px;
        height: 18px;
        box-sizing: border-box;
        border: 2px solid var(--avatar-border);
        border-top-color: var(--avatar-primary);
        border-radius: 50%;
        animation: avatar-spin 0.8s linear infinite;
      }
      @keyframes avatar-spin { to { transform: rotate(360deg); } }

      .load-more {
        width: 100%;
        min-height: 44px;
        margin-top: 12px;
        padding: 10px;
        border: 1px solid var(--avatar-border);
        border-radius: 10px;
        background: var(--secondary-background-color);
        color: var(--avatar-text);
        font-weight: bold;
        font-size: 13px;
        cursor: pointer;
      }
      @media (hover: hover) {
        .load-more:hover { border-color: var(--avatar-primary); }
      }

      .empty {
        text-align: center;
        padding: 24px 8px;
        font-size: 13px;
        color: var(--avatar-secondary-text);
      }

      .grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
        gap: 12px;
        max-height: min(500px, 60vh);
        overflow-y: auto;
        scrollbar-width: thin;
        scrollbar-color: var(--avatar-border) transparent;
      }

      .item {
        /* <button> pour la navigation clavier : on annule ses styles natifs. */
        display: block;
        width: 100%;
        font: inherit;
        color: inherit;
        background: var(--secondary-background-color);
        border-radius: 12px;
        padding: 10px;
        text-align: center;
        cursor: pointer;
        transition: 0.2s;
        border: 1px solid var(--avatar-border);
      }
      @media (hover: hover) {
        .item:hover { transform: translateY(-3px); border-color: var(--avatar-primary); }
      }
      .item img { width: 100%; aspect-ratio: 1; object-fit: contain; }
      .item span { display: block; font-size: 12px; font-weight: bold; color: var(--avatar-secondary-text); margin-top: 5px; overflow-wrap: anywhere; }

      .lightbox {
        position: fixed; inset: 0;
        background: rgba(0,0,0,0.8);
        z-index: 9999;
        display: flex; align-items: center; justify-content: center;
        backdrop-filter: blur(5px);
      }
      .modal {
        position: relative;
        background: var(--avatar-card-bg);
        color: var(--avatar-text);
        padding: 30px;
        border-radius: 24px;
        width: 90%; max-width: 450px;
        max-height: 90vh;
        overflow-y: auto;
        box-sizing: border-box;
        text-align: center;
        border: 1px solid var(--avatar-border);
      }
      .modal img { max-height: 200px; margin-bottom: 20px; }

      .close-btn {
        position: absolute; top: 8px; right: 8px;
        min-width: 44px; min-height: 44px;
        background: none; border: none; border-radius: 50%;
        color: var(--avatar-secondary-text);
        font-size: 28px; cursor: pointer; line-height: 1;
      }
      @media (hover: hover) {
        .close-btn:hover { color: var(--avatar-text); }
      }

      .btn-list { display: flex; flex-direction: column; gap: 10px; width: 100%; }
      .btn-group { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; width: 100%; }
      .btn {
        min-height: 44px;
        padding: 12px;
        border-radius: 12px;
        border: none;
        font-weight: bold;
        cursor: pointer;
        font-size: 12px;
        text-transform: uppercase;
        transition: 0.2s;
      }
      .btn[disabled] { opacity: 0.5; cursor: default; }
      .btn-main { background: var(--avatar-primary); color: var(--text-primary-color, white); }
      .btn-ghost {
        background: var(--secondary-background-color);
        color: var(--avatar-text);
        border: 1px solid var(--avatar-border);
      }
      .btn:active:not([disabled]) { opacity: 0.7; transform: scale(0.98); }

      @media (prefers-reduced-motion: reduce) {
        .item, .btn { transition: none; }
        .item:hover, .btn:active { transform: none; }
        .spinner { animation: none; }
      }
    `;
  }

  render() {
    if (!this.hass) return html`<ha-card>${tr(null, "loading_hass")}</ha-card>`;
    const users = this.config.users || [];
    const isDuo = this._currentUser === 'Duo';
    const folderName = isDuo ? 'Duo' : this._currentUser;
    const userHass = this._getUsersFromHass();
    const currentUserObj = userHass.find(u => u.id === this._currentUser);
    const baseDir = this._baseDir(isDuo, currentUserObj);

    const categories = [...new Set((this._metadata || []).flatMap(i => i.categories || []))].sort();

    // Chaque mot saisi doit être présent : « bisou kenny » cherche les deux.
    const terms = AvatarCard._norm(this._search).split(/\s+/).filter(Boolean);

    const filtered = (this._metadata || []).filter(item => {
      // mots_cles contient les synonymes FR et EN du catalogue (« hugs »,
      // « tu me manques »...) : les ignorer rendait la recherche quasi inutile.
      const hay = AvatarCard._norm(`${item.titre || ""} ${item.mots_cles || ""}`);
      const ms = terms.every(t => hay.includes(t));
      const mc = !this._category || (item.categories && item.categories.includes(this._category));
      return ms && mc;
    });

    const shown = filtered.slice(0, this._limit);
    const remaining = filtered.length - shown.length;
    const failed = this._lastFetch && !this._lastFetch.success;
    const locale = this.hass.locale?.language || this.hass.language;
    const when = this._lastFetch?.date ? this._lastFetch.date.toLocaleString(locale) : "";

    return html`
      <ha-card>
        <div class="header-controls">
          <select aria-label="${this._t("user")}" @change="${this._changeUser}">
            ${users.map(u => html`<option value="${u.user_id_folder}" ?selected="${this._currentUser === u.user_id_folder}">${userLabel(u)}</option>`)}
            ${this.config.show_duo ? html`<option value="Duo" ?selected="${this._currentUser === 'Duo'}">${this.config.duo_label}</option>` : ""}
          </select>

          <select aria-label="${this._t("category")}" @change="${e => { this._category = e.target.value; this._resetPaging(); }}">
            <option value="">${this._t("all_categories")}</option>
            ${categories.map(c => html`<option value="${c}" ?selected="${this._category === c}">${c}</option>`)}
          </select>

          <input type="text" aria-label="${this._t("search_label")}" placeholder="${this._t("search_ph")}" .value="${this._search}" @input="${e => { this._search = e.target.value; this._resetPaging(); }}">
        </div>

        ${failed ? html`
          <div class="fetch-error" role="alert" title="${this._lastFetch.url || ''} (${when})">
            <span><span aria-hidden="true">⚠️</span> ${this._t("fetch_failed", { error: this._lastFetch.error })}</span>
            <button type="button" class="retry" @click="${() => this._retry()}">${this._t("retry")}</button>
          </div>
        ` : ""}

        ${this._loading ? html`
          <div class="loading" role="status">
            <span class="spinner" aria-hidden="true"></span>
            <span>${this._t("loading")}</span>
          </div>
        ` : ""}

        <div class="grid">
          ${shown.map(item => html`
            <button
              type="button"
              class="item"
              @click="${() => this._openLightbox(item)}">
              <img
                src="${poseUrl(baseDir, folderName, item.fichier)}"
                alt=""
                loading="lazy"
                decoding="async">
              <span>${item.titre}</span>
            </button>
          `)}
        </div>

        ${remaining > 0 ? html`
          <button type="button" class="load-more" @click="${() => { this._limit += AvatarCard.PAGE_SIZE; }}">
            ${this._t("more", { n: remaining, s: remaining > 1 ? "s" : "" })}
          </button>
        ` : ""}

        ${filtered.length === 0 && this._metadata.length > 0 ? html`
          <div class="empty" role="status">${this._t("no_result")}</div>
        ` : ""}

        ${this._metadata.length === 0 && !this._loading && !failed && this._loadedFor && this._loadedFor === this._currentUser ? html`
          <div class="empty" role="status">${this._t("no_poses")}</div>
        ` : ""}

        ${this._showLightbox && this._selectedItem ? this._renderLightbox(users, baseDir, folderName) : ""}
      </ha-card>
    `;
  }

  _renderLightbox(users, baseDir, folderName) {
    const item = this._selectedItem;
    const img = poseUrl(baseDir, folderName, item.fichier);
    const busy = this._busy;

    return html`
      <div class="lightbox" @click="${() => this._closeLightbox()}">
        <div
          class="modal"
          role="dialog"
          aria-modal="true"
          aria-label="${item.titre}"
          @click="${e => e.stopPropagation()}">
          <button type="button" class="close-btn" aria-label="${this._t("close")}" @click="${() => this._closeLightbox()}"><span aria-hidden="true">×</span></button>
          <img src="${img}" alt="${item.titre}">
          <h3>${item.titre}</h3>

          <div class="btn-list">
            ${this._currentUser === 'Duo' ? html`
              <div class="btn-group">
                ${users.map(u => html`<button type="button" class="btn btn-main" ?disabled="${busy}" @click="${() => this._trigger('profil', u.user_id_folder)}">${this._t("profile_of", { name: shortLabel(userLabel(u)) })}</button>`)}
              </div>
              <div class="btn-group">
                ${users.map(u => html`<button type="button" class="btn btn-ghost" ?disabled="${busy}" @click="${() => this._trigger('envoyer', u.user_id_folder)}">${this._t("send_to_short", { name: shortLabel(userLabel(u)) })}</button>`)}
              </div>
            ` : html`
              <button type="button" class="btn btn-main" ?disabled="${busy}" @click="${() => this._trigger('profil', this._currentUser)}">${this._t("set_profile")}</button>
              ${users.filter(u => u.user_id_folder !== this._currentUser).map(u => html`
                <button type="button" class="btn btn-ghost" ?disabled="${busy}" @click="${() => this._trigger('envoyer', u.user_id_folder)}">${this._t("send_to", { name: userLabel(u).toUpperCase() })}</button>
              `)}
            `}
          </div>
        </div>
      </div>
    `;
  }

  _changeUser(e) {
    this._currentUser = e.target.value;
    this._category = "";
    this._search = "";
    this._resetPaging();
    this._loadMetadata();
  }

  /** Toute modification de filtre doit repartir de la première page, sinon on
   *  garde le seuil élargi d'une recherche précédente. */
  _resetPaging() {
    this._limit = AvatarCard.PAGE_SIZE;
    this.requestUpdate();
  }

  /** Toast natif de HA (écouté par le frontend sur n'importe quel élément). */
  _toast(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", {
      detail: { message },
      bubbles: true,
      composed: true,
    }));
  }

  async _trigger(action, targetId) {
    if (this._busy) return;
    const isDuo = this._currentUser === 'Duo';
    const folderName = isDuo ? 'Duo' : this._currentUser;
    const usersHass = this._getUsersFromHass();
    const userObj = usersHass.find(u => u.id === this._currentUser);
    const baseDir = this._baseDir(isDuo, userObj);

    const img = poseUrl(baseDir, folderName, this._selectedItem.fichier);
    const destConfig = this.config.users.find(u => u.user_id_folder === targetId);
    const fromLabel = isDuo ? this.config.duo_label : (userLabel(this.config.users.find(u => u.user_id_folder === this._currentUser)) || this._currentUser);

    this._busy = true;
    try {
      if (action === 'profil') {
        await this.hass.callService('avatar_explorer', 'set_avatar', { user_id: targetId, image_path: img });
      } else {
        await this.hass.callService('avatar_explorer', 'send_emoji', {
          from_label: fromLabel,
          to_user: targetId,
          image_path: img,
          notify_service: destConfig ? destConfig.notify_service : null
        });
      }
      this._toast(this._t(action === 'profil' ? "ok_avatar" : "ok_emoji"));
      this._closeLightbox();
    } catch (e) {
      // La modale reste ouverte : l'utilisateur peut réessayer.
      console.error("[avatar-card] échec du service :", e);
      this._toast(this._t("err_action", { error: (e && e.message) || String(e) }));
    } finally {
      this._busy = false;
    }
  }
}

// ==========================================
// 2. L'ÉDITEUR VISUEL (UI)
// ==========================================
class AvatarCardEditor extends LitElement {
  static get properties() {
    return { hass: { type: Object }, _config: { type: Object } };
  }

  _t(key, params) {
    return tr(this.hass, key, params);
  }

  setConfig(config) {
    this._config = { users: [], dir: "images/avatar", show_duo: true, duo_label: "👩‍❤️‍👨 Duo", ...config };
  }

  _getUsersFromHass() {
    return collectUsers(this.hass);
  }

  render() {
    if (!this.hass || !this._config) return html``;
    const users = this._config.users || [];
    const haUsers = this._getUsersFromHass().filter(ha => !users.some(u => u.user_id_folder === ha.id));
    const notifyServices = Object.keys((this.hass.services && this.hass.services.notify) || {}).sort();

    return html`
      <div class="card-config">
        <div class="option-row">
          <label>${this._t("ed_show_duo")}</label>
          <ha-switch aria-label="${this._t("ed_show_duo")}" .checked=${this._config.show_duo} @change=${e => this._updateConfig('show_duo', e.target.checked)}></ha-switch>
        </div>
        ${this._config.show_duo ? html`
          <div class="option-row">
            <label>${this._t("ed_duo_label")}</label>
            <input aria-label="${this._t("ed_duo_label")}" .value="${this._config.duo_label}" @input="${e => this._updateConfig('duo_label', e.target.value)}">
          </div>
        ` : ''}

        <div class="users-section">
          <div class="section-title">${this._t("ed_users")}</div>
          ${users.map((u, i) => html`
            <div class="user-row">
              <button type="button" class="icon-btn star ${u.is_default ? 'active' : ''}"
                aria-label="${this._t("ed_default", { name: userLabel(u) })}"
                aria-pressed="${u.is_default ? 'true' : 'false'}"
                @click=${() => this._setDefault(i)}>
                <ha-icon icon="${u.is_default ? 'mdi:star' : 'mdi:star-outline'}"></ha-icon>
              </button>
              <div class="inputs">
                <div class="folder-id"><span aria-hidden="true">📁</span> ${this._t("ed_folder", { id: u.user_id_folder })}</div>
                <input aria-label="${this._t("ed_name_of", { id: u.user_id_folder })}" placeholder="${this._t("ed_name_ph")}" .value=${u.label || ""} @input=${e => this._updateUser(i, 'label', e.target.value)}>
                <select aria-label="${this._t("ed_notify", { name: userLabel(u) })}" @change=${e => this._updateUser(i, 'notify_service', e.target.value)}>
                  <option value="">${this._t("ed_no_phone")}</option>
                  ${notifyServices.map(s => html`<option value="${s}" ?selected=${u.notify_service === s}>📲 ${s}</option>`)}
                </select>
              </div>
              <button type="button" class="icon-btn del"
                aria-label="${this._t("ed_remove", { name: userLabel(u) })}"
                @click=${() => this._removeUser(i)}>
                <ha-icon icon="mdi:delete"></ha-icon>
              </button>
            </div>
          `)}

          ${haUsers.length > 0 ? html`
            <select class="add-select" aria-label="${this._t("ed_add")}" @change=${e => { if(e.target.value) this._addUser(e.target.value); e.target.value = ""; }}>
              <option value="">${this._t("ed_add")}</option>
              ${haUsers.map(h => html`<option value="${h.id}">${h.label} (${h.id})</option>`)}
            </select>
          ` : html`<p class="all-added">${this._t("ed_all_added")}</p>`}
        </div>
      </div>
    `;
  }

  _updateConfig(key, value) {
    this._config = { ...this._config, [key]: value };
    this._fireChanged();
  }

  _addUser(id) {
    const haUser = this._getUsersFromHass().find(u => u.id === id);
    if (!haUser) return;
    const users = [...(this._config.users || []), { user_id_folder: id, label: haUser.label, is_default: false, notify_service: "" }];
    this._config = { ...this._config, users };
    this._fireChanged();
  }

  _updateUser(index, field, value) {
    const users = [...this._config.users];
    users[index] = { ...users[index], [field]: value };
    this._config = { ...this._config, users };
    this._fireChanged();
  }

  _setDefault(index) {
    const users = this._config.users.map((u, i) => ({ ...u, is_default: i === index }));
    this._config = { ...this._config, users };
    this._fireChanged();
  }

  _removeUser(index) {
    const users = this._config.users.filter((_, i) => i !== index);
    this._config = { ...this._config, users };
    this._fireChanged();
  }

  _fireChanged() {
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
  }

  static get styles() {
    return css`
      .card-config { display: flex; flex-direction: column; gap: 15px; color: var(--primary-text-color); }
      .option-row { display: flex; align-items: center; justify-content: space-between; background: var(--secondary-background-color); padding: 10px; border-radius: 8px; border: 1px solid var(--divider-color); }
      .option-row input { padding: 8px; border-radius: 5px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); width: 50%; }
      .users-section { background: var(--secondary-background-color); padding: 10px; border-radius: 8px; border: 1px solid var(--divider-color); }
      .section-title { font-weight: bold; display: block; margin-bottom: 10px; }
      .user-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; background: var(--card-background-color); padding: 10px; border-radius: 8px; border: 1px solid var(--divider-color); }
      .folder-id { font-size: 12px; color: var(--secondary-text-color); font-weight: bold; margin-bottom: 4px; }
      .inputs { display: flex; flex-direction: column; gap: 6px; flex-grow: 1; }
      input, select { padding: 8px; min-height: 44px; border-radius: 4px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); width: 100%; box-sizing: border-box; }
      input:focus-visible, select:focus-visible, button:focus-visible {
        outline: 2px solid var(--primary-color);
        outline-offset: 2px;
      }
      /* Boutons-icônes : <button> natif pour le clavier et le lecteur d'écran. */
      .icon-btn { display: inline-flex; align-items: center; justify-content: center; min-width: 44px; min-height: 44px; padding: 0; border: none; border-radius: 50%; background: none; cursor: pointer; }
      .star { color: var(--disabled-text-color); }
      .star.active { color: var(--state-icon-active-color, var(--warning-color, var(--primary-color))); }
      .del { color: var(--error-color); }
      .add-select { width: 100%; padding: 12px; background: var(--primary-color); color: var(--text-primary-color, white); border: none; border-radius: 8px; cursor: pointer; margin-top: 10px; font-weight: bold; }
      .all-added { font-size: 12px; color: var(--secondary-text-color); text-align: center; margin-top: 10px; }
    `;
  }
}

// Gardes : le fichier peut être chargé deux fois (ressource Lovelace ajoutée en
// plus du chargement automatique) ; define() lèverait alors une exception.
if (!customElements.get("avatar-card")) {
  customElements.define("avatar-card", AvatarCard);
}
if (!customElements.get("avatar-card-editor")) {
  customElements.define("avatar-card-editor", AvatarCardEditor);
}

// Déclaration dans le sélecteur de cartes de HA (pas de preview : la carte
// charge un catalogue distant).
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "avatar-card")) {
  const fr = String(navigator.language || "").toLowerCase().startsWith("fr");
  window.customCards.push({
    type: "avatar-card",
    name: "Avatar Explorer",
    description: STRINGS[fr ? "fr" : "en"].card_desc,
    preview: false,
  });
}
