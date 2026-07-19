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

// Un seul balayage de hass.states partagé par la carte et son éditeur : sur une
// instance chargée (plusieurs milliers d'entités), le refaire à chaque rendu et
// dans chaque classe coûte cher pour un résultat qui bouge très rarement.
function collectUsers(hass) {
  if (!hass) return [];
  return Object.keys(hass.states)
    .filter((eid) => eid.startsWith("sensor.") && eid.endsWith("_dynamique"))
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
      _limit: { type: Number }
    };
  }

  // Nombre d'items rendus d'emblée. Le catalogue en compte ~1260 par dossier :
  // tout afficher crée autant de noeuds DOM pour une quinzaine de visibles.
  static get PAGE_SIZE() { return 60; }

  static getConfigElement() {
    return document.createElement("avatar-card-editor");
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
    this._usersCache = null;
    this._usersCacheFor = null;
    this._trackedIds = null;
    this._onKeyDown = this._onKeyDown.bind(this);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    // La lightbox pose un écouteur sur document : le retirer si la carte est
    // détruite alors qu'elle est ouverte, sinon l'écouteur survit à la carte.
    document.removeEventListener("keydown", this._onKeyDown);
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
    this._trackedIds = this._usersCache.map((u) => u.entityId);
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

  /** Utilisé par HA pour répartir les cartes en colonnes. */
  getCardSize() {
    return 12;
  }

  async _loadMetadata() {
    if (!this._currentUser || this._loading) return;

    const target = this._currentUser;
    const isDuo = target === 'Duo';
    const folderName = isDuo ? 'Duo' : target;
    const usersHass = this._getUsersFromHass();
    const userObj = usersHass.find(u => u.id === target);
    const baseDir = isDuo ? this.config.dir : (userObj ? userObj.directory : this.config.dir);

    // Volontairement non affiché dans la carte : l'état de la récupération est
    // conservé dans this._lastFetch et tracé en console (F12, filtrer sur
    // « avatar-card ») pour le diagnostic.
    const url = `/local/${baseDir}/${folderName}/metadata_${folderName}.json`;
    const started = performance.now();

    this._loading = true;
    try {
      const response = await fetch(url);
      if (response.ok) {
        this._metadata = await response.json();
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
    this._selectedItem = item;
    this._showLightbox = true;
    document.addEventListener("keydown", this._onKeyDown);
  }

  _closeLightbox() {
    this._showLightbox = false;
    document.removeEventListener("keydown", this._onKeyDown);
  }

  _onKeyDown(e) {
    if (e.key === "Escape" && this._showLightbox) {
      e.stopPropagation();
      this._closeLightbox();
    }
  }

  /** Normalise pour une recherche insensible à la casse ET aux accents :
   *  le catalogue contient « hâte », « à très vite »... que personne ne tape
   *  avec les accents dans un champ de recherche. */
  static _norm(str) {
    return (str || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");
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
        background: var(--secondary-background-color); 
        border: 1px solid var(--avatar-border); 
        border-radius: 8px; 
        padding: 10px; 
        color: var(--avatar-text); 
        font-weight: bold; 
        outline: none; 
        box-sizing: border-box; 
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
        padding: 4px 10px;
        font: inherit;
        cursor: pointer;
        border-radius: 6px;
        border: 1px solid currentColor;
        background: none;
        color: inherit;
      }
      .retry:hover { background: rgba(219, 68, 55, 0.12); }
      .retry:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }

      .load-more {
        width: 100%;
        margin-top: 12px;
        padding: 10px;
        border: 1px solid var(--avatar-border);
        border-radius: 10px;
        background: var(--secondary-background-color);
        color: var(--avatar-text);
        font-weight: bold;
        cursor: pointer;
      }
      .load-more:hover { border-color: var(--avatar-primary); }

      .empty {
        text-align: center;
        padding: 24px 8px;
        font-size: 13px;
        color: var(--avatar-secondary-text);
      }

      .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 12px; max-height: 500px; overflow-y: auto; }
      .grid::-webkit-scrollbar { width: 4px; }
      .grid::-webkit-scrollbar-thumb { background: var(--avatar-border); border-radius: 4px; }

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
      .item:hover { transform: translateY(-3px); border-color: var(--avatar-primary); }
      .item:focus-visible {
        outline: 2px solid var(--avatar-primary);
        outline-offset: 2px;
      }
      .item img { width: 100%; aspect-ratio: 1; object-fit: contain; }
      .item span { display: block; font-size: 10px; font-weight: bold; color: var(--avatar-secondary-text); margin-top: 5px; }
      
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
        text-align: center; 
        border: 1px solid var(--avatar-border); 
      }
      .modal img { max-height: 200px; margin-bottom: 20px; }
      
      .close-btn { position: absolute; top: 15px; right: 15px; background: none; border: none; color: var(--avatar-secondary-text); font-size: 28px; cursor: pointer; line-height: 1; }
      .close-btn:hover { color: var(--avatar-text); }

      .btn-list { display: flex; flex-direction: column; gap: 10px; width: 100%; }
      .btn-group { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; width: 100%; }
      .btn { 
        padding: 12px; 
        border-radius: 12px; 
        border: none; 
        font-weight: bold; 
        cursor: pointer; 
        font-size: 11px; 
        text-transform: uppercase; 
        transition: 0.2s;
      }
      .btn-main { background: var(--avatar-primary); color: var(--text-primary-color, white); }
      .btn-ghost { 
        background: var(--secondary-background-color); 
        color: var(--avatar-text); 
        border: 1px solid var(--avatar-border); 
      }
      .btn:active { opacity: 0.7; transform: scale(0.98); }
    `;
  }

  render() {
    if (!this.hass) return html`<ha-card>Chargement...</ha-card>`;
    const users = this.config.users || [];
    const isDuo = this._currentUser === 'Duo';
    const folderName = isDuo ? 'Duo' : this._currentUser;
    const userHass = this._getUsersFromHass();
    const currentUserObj = userHass.find(u => u.id === this._currentUser);
    const baseDir = isDuo ? this.config.dir : (currentUserObj ? currentUserObj.directory : this.config.dir);
    
    const categories = [...new Set((this._metadata || []).flatMap(i => i.categories || []))].sort();
    
    // Chaque mot saisi doit être présent : « bisou kenny » cherche les deux.
    const terms = AvatarCard._norm(this._search).split(/\s+/).filter(Boolean);

    const filtered = (this._metadata || []).filter(item => {
      // mots_cles contient les synonymes FR et EN du catalogue (« hugs »,
      // « tu me manques »...) : les ignorer rendait la recherche quasi inutile.
      const hay = AvatarCard._norm(`${item.titre} ${item.mots_cles || ""}`);
      const ms = terms.every(t => hay.includes(t));
      const mc = !this._category || (item.categories && item.categories.includes(this._category));
      return ms && mc;
    });

    const shown = filtered.slice(0, this._limit);
    const remaining = filtered.length - shown.length;

    return html`
      <ha-card>
        <div class="header-controls">
          <select @change="${this._changeUser}">
            ${users.map(u => html`<option value="${u.user_id_folder}" ?selected="${this._currentUser === u.user_id_folder}">${u.label}</option>`)}
            ${this.config.show_duo ? html`<option value="Duo" ?selected="${this._currentUser === 'Duo'}">${this.config.duo_label}</option>` : ""}
          </select>
          
          <select @change="${e => { this._category = e.target.value; this._resetPaging(); }}">
            <option value="">Toutes catégories</option>
            ${categories.map(c => html`<option value="${c}" ?selected="${this._category === c}">${c}</option>`)}
          </select>

          <input type="text" placeholder="Rechercher (titre ou mot-clé)..." .value="${this._search}" @input="${e => { this._search = e.target.value; this._resetPaging(); }}">
        </div>

        ${this._lastFetch && !this._lastFetch.success ? html`
          <div class="fetch-error" title="${this._lastFetch.url || ''}">
            <span>⚠️ Liste des poses indisponible (${this._lastFetch.error})</span>
            <button type="button" class="retry" @click="${() => this._retry()}">Réessayer</button>
          </div>
        ` : ""}

        <div class="grid">
          ${shown.map(item => html`
            <button
              type="button"
              class="item"
              title="${item.titre}"
              @click="${() => this._openLightbox(item)}">
              <img
                src="/local/${baseDir}/${folderName}/${item.fichier}"
                alt="${item.titre}"
                loading="lazy"
                decoding="async">
              <span>${item.titre}</span>
            </button>
          `)}
        </div>

        ${remaining > 0 ? html`
          <button class="load-more" @click="${() => { this._limit += AvatarCard.PAGE_SIZE; }}">
            Voir plus (${remaining} restant${remaining > 1 ? "s" : ""})
          </button>
        ` : ""}

        ${filtered.length === 0 && this._metadata.length > 0 ? html`
          <div class="empty">Aucun résultat pour cette recherche.</div>
        ` : ""}

        ${this._showLightbox ? this._renderLightbox(users, baseDir, folderName) : ""}
      </ha-card>
    `;
  }

  _renderLightbox(users, baseDir, folderName) {
    const item = this._selectedItem;
    const img = `/local/${baseDir}/${folderName}/${item.fichier}`;
    
    return html`
      <div class="lightbox" @click="${() => this._closeLightbox()}">
        <div
          class="modal"
          role="dialog"
          aria-modal="true"
          aria-label="${item.titre}"
          @click="${e => e.stopPropagation()}">
          <button class="close-btn" aria-label="Fermer" @click="${() => this._closeLightbox()}">×</button>
          <img src="${img}" alt="${item.titre}">
          <h3>${item.titre}</h3>
          
          <div class="btn-list">
            ${this._currentUser === 'Duo' ? html`
              <div class="btn-group">
                ${users.map(u => html`<button class="btn btn-main" @click="${() => this._trigger('profil', u.user_id_folder)}">PROFIL ${shortLabel(u.label)}</button>`)}
              </div>
              <div class="btn-group">
                ${users.map(u => html`<button class="btn btn-ghost" @click="${() => this._trigger('envoyer', u.user_id_folder)}">ENVOYER ${shortLabel(u.label)}</button>`)}
              </div>
            ` : html`
              <button class="btn btn-main" @click="${() => this._trigger('profil', this._currentUser)}">METTRE EN PROFIL</button>
              ${users.filter(u => u.user_id_folder !== this._currentUser).map(u => html`
                <button class="btn btn-ghost" @click="${() => this._trigger('envoyer', u.user_id_folder)}">ENVOYER À ${u.label.toUpperCase()}</button>
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
  
  async _trigger(action, targetId) {
    const isDuo = this._currentUser === 'Duo';
    const folderName = isDuo ? 'Duo' : this._currentUser;
    const usersHass = this._getUsersFromHass();
    const userObj = usersHass.find(u => u.id === this._currentUser);
    const baseDir = isDuo ? this.config.dir : (userObj ? userObj.directory : this.config.dir);
    
    const img = `/local/${baseDir}/${folderName}/${this._selectedItem.fichier}`;
    const destConfig = this.config.users.find(u => u.user_id_folder === targetId);
    const fromLabel = isDuo ? this.config.duo_label : (this.config.users.find(u => u.user_id_folder === this._currentUser)?.label || this._currentUser);

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
    this._closeLightbox();
  }
}

// ==========================================
// 2. L'ÉDITEUR VISUEL (UI)
// ==========================================
class AvatarCardEditor extends LitElement {
  static get properties() {
    return { hass: { type: Object }, _config: { type: Object } };
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
    const notifyServices = Object.keys(this.hass.services.notify || {}).sort();

    return html`
      <div class="card-config">
        <div class="option-row">
          <label>Afficher le mode Duo</label>
          <ha-switch .checked=${this._config.show_duo} @change=${e => this._updateConfig('show_duo', e.target.checked)}></ha-switch>
        </div>
        ${this._config.show_duo ? html`
          <div class="option-row">
            <label>Nom affiché pour Duo</label>
            <input .value="${this._config.duo_label}" @input="${e => this._updateConfig('duo_label', e.target.value)}">
          </div>
        ` : ''}

        <div class="users-section">
          <label style="font-weight:bold; display:block; margin-bottom:10px;">Gestion des Utilisateurs</label>
          ${users.map((u, i) => html`
            <div class="user-row">
              <ha-icon icon="${u.is_default ? 'mdi:star' : 'mdi:star-outline'}" class="star ${u.is_default ? 'active' : ''}" @click=${() => this._setDefault(i)}></ha-icon>
              <div class="inputs">
                <div class="folder-id">📁 Dossier: ${u.user_id_folder}</div>
                <input placeholder="Nom sur tablette (ex: Papa)" .value=${u.label || ""} @input=${e => this._updateUser(i, 'label', e.target.value)}>
                <select @change=${e => this._updateUser(i, 'notify_service', e.target.value)}>
                  <option value="">-- Aucun téléphone --</option>
                  ${notifyServices.map(s => html`<option value="${s}" ?selected=${u.notify_service === s}>📲 ${s}</option>`)}
                </select>
              </div>
              <ha-icon icon="mdi:delete" class="del" @click=${() => this._removeUser(i)}></ha-icon>
            </div>
          `)}
          
          ${haUsers.length > 0 ? html`
            <select class="add-select" @change=${e => { if(e.target.value) this._addUser(e.target.value); e.target.value = ""; }}>
              <option value="">+ Ajouter un utilisateur existant...</option>
              ${haUsers.map(h => html`<option value="${h.id}">${h.label} (${h.id})</option>`)}
            </select>
          ` : html`<p style="font-size:11px; color:#888; text-align:center; margin-top:10px;">Tous les profils de l'intégration sont ajoutés.</p>`}
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
      .user-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; background: var(--card-background-color); padding: 10px; border-radius: 8px; border: 1px solid var(--divider-color); }
      .folder-id { font-size: 11px; color: var(--secondary-text-color); font-weight: bold; margin-bottom: 4px; }
      .inputs { display: flex; flex-direction: column; gap: 6px; flex-grow: 1; }
      input, select { padding: 8px; border-radius: 4px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); width: 100%; box-sizing: border-box; }
      .star { cursor: pointer; color: var(--disabled-text-color); }
      .star.active { color: #eab308; }
      .del { cursor: pointer; color: var(--error-color); }
      .add-select { width: 100%; padding: 12px; background: var(--primary-color); color: var(--text-primary-color, white); border: none; border-radius: 8px; cursor: pointer; margin-top: 10px; font-weight: bold; }
    `;
  }
}

customElements.define("avatar-card", AvatarCard);
customElements.define("avatar-card-editor", AvatarCardEditor);