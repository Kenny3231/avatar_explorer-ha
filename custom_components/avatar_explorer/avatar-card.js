import {
  LitElement,
  html,
  css,
} from "https://unpkg.com/lit-element@2.4.0/lit-element.js?module";

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
      _lastFetch: { type: Object }
    };
  }

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
    if (changedProperties.has("hass") && this.hass && this._currentUser && this._metadata.length === 0) {
      this._loadMetadata();
    }
  }

  _getUsersFromHass() {
    if (!this.hass) return [];
    return Object.keys(this.hass.states)
      .filter(eid => eid.startsWith('sensor.') && eid.endsWith('_dynamique'))
      .map(eid => {
        const s = this.hass.states[eid];
        return {
          id: s.attributes.folder_id,
          label: s.attributes.friendly_name.replace(' Dynamique', ''),
          directory: s.attributes.directory
        };
      });
  }

  async _loadMetadata() {
    if (!this._currentUser) return;
    
    const isDuo = this._currentUser === 'Duo';
    const folderName = isDuo ? 'Duo' : this._currentUser;
    const usersHass = this._getUsersFromHass();
    const userObj = usersHass.find(u => u.id === this._currentUser);
    const baseDir = isDuo ? this.config.dir : (userObj ? userObj.directory : this.config.dir);

    try {
      const response = await fetch(`/local/${baseDir}/${folderName}/metadata_${folderName}.json`);
      if (response.ok) {
        this._metadata = await response.json();
        this._lastFetch = { date: new Date(), success: true };
      } else {
        this._metadata = [];
        this._lastFetch = { date: new Date(), success: false, error: `HTTP ${response.status}` };
      }
    } catch (e) {
      this._metadata = [];
      this._lastFetch = { date: new Date(), success: false, error: e.message };
    }
    this.requestUpdate();
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
      
      .fetch-status { font-size: 11px; margin-bottom: 10px; color: var(--avatar-secondary-text); }
      .fetch-status.error { color: var(--error-color, #db4437); font-weight: bold; }

      .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 12px; max-height: 500px; overflow-y: auto; }
      .grid::-webkit-scrollbar { width: 4px; }
      .grid::-webkit-scrollbar-thumb { background: var(--avatar-border); border-radius: 4px; }

      .item { 
        background: var(--secondary-background-color); 
        border-radius: 12px; 
        padding: 10px; 
        text-align: center; 
        cursor: pointer; 
        transition: 0.2s; 
        border: 1px solid var(--avatar-border); 
      }
      .item:hover { transform: translateY(-3px); border-color: var(--avatar-primary); }
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
    
    const filtered = (this._metadata || []).filter(item => {
      const ms = !this._search || item.titre.toLowerCase().includes(this._search.toLowerCase());
      const mc = !this._category || (item.categories && item.categories.includes(this._category));
      return ms && mc;
    });

    return html`
      <ha-card>
        <div class="header-controls">
          <select @change="${this._changeUser}">
            ${users.map(u => html`<option value="${u.user_id_folder}" ?selected="${this._currentUser === u.user_id_folder}">${u.label}</option>`)}
            ${this.config.show_duo ? html`<option value="Duo" ?selected="${this._currentUser === 'Duo'}">${this.config.duo_label}</option>` : ""}
          </select>
          
          <select @change="${e => { this._category = e.target.value; this.requestUpdate(); }}">
            <option value="">Toutes catégories</option>
            ${categories.map(c => html`<option value="${c}" ?selected="${this._category === c}">${c}</option>`)}
          </select>
          
          <input type="text" placeholder="Rechercher..." .value="${this._search}" @input="${e => { this._search = e.target.value; this.requestUpdate(); }}">
        </div>

        ${this._lastFetch ? html`
          <div class="fetch-status ${this._lastFetch.success ? 'ok' : 'error'}" title="${this._lastFetch.error || ''}">
            ${this._lastFetch.success ? '✅' : '❌'} Dernière récupération : ${this._lastFetch.date.toLocaleString('fr-FR')}
          </div>
        ` : ""}

        <div class="grid">
          ${filtered.map(item => html`
            <div class="item" @click="${() => { this._selectedItem = item; this._showLightbox = true; }}">
              <img src="/local/${baseDir}/${folderName}/${item.fichier}">
              <span>${item.titre}</span>
            </div>
          `)}
        </div>
        ${this._showLightbox ? this._renderLightbox(users, baseDir, folderName) : ""}
      </ha-card>
    `;
  }

  _renderLightbox(users, baseDir, folderName) {
    const item = this._selectedItem;
    const img = `/local/${baseDir}/${folderName}/${item.fichier}`;
    
    return html`
      <div class="lightbox" @click="${() => this._showLightbox = false}">
        <div class="modal" @click="${e => e.stopPropagation()}">
          <button class="close-btn" @click="${() => this._showLightbox = false}">×</button>
          <img src="${img}">
          <h3>${item.titre}</h3>
          
          <div class="btn-list">
            ${this._currentUser === 'Duo' ? html`
              <div class="btn-group">
                ${users.map(u => html`<button class="btn btn-main" @click="${() => this._trigger('profil', u.user_id_folder)}">PROFIL ${u.label.split(' ')[1] || u.label}</button>`)}
              </div>
              <div class="btn-group">
                ${users.map(u => html`<button class="btn btn-ghost" @click="${() => this._trigger('envoyer', u.user_id_folder)}">ENVOYER ${u.label.split(' ')[1] || u.label}</button>`)}
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
    this._loadMetadata(); 
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
    this._showLightbox = false;
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
    if (!this.hass) return [];
    return Object.keys(this.hass.states)
      .filter(eid => eid.startsWith('sensor.') && eid.endsWith('_dynamique'))
      .map(eid => {
        const s = this.hass.states[eid];
        return {
          id: s.attributes.folder_id,
          label: s.attributes.friendly_name.replace(' Dynamique', '')
        };
      });
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