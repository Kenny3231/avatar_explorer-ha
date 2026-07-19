import re

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import (
    BITMOJI_ID_PATTERN,
    CONF_LANG,
    CONF_SCALE,
    CONF_UPDATE_INTERVAL_HOURS,
    DEFAULT_DIR,
    DEFAULT_LANG,
    DEFAULT_SCALE,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    LANG_OPTIONS,
    SCALE_OPTIONS,
)

_BITMOJI_RE = re.compile(BITMOJI_ID_PATTERN)


def _scale_selector():
    """Liste déroulante Web / HD / Ultra pour le facteur de résolution."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=SCALE_OPTIONS,
            mode=selector.SelectSelectorMode.LIST,
        )
    )


def _current_scale(source) -> str:
    """Valeur courante en chaîne : le sélecteur compare aux valeurs des options,
    or les configurations existantes ont pu stocker un entier."""
    return str(source.get(CONF_SCALE, DEFAULT_SCALE))


def _lang_selector():
    """Langue du catalogue. Elle ne change pas que l'affichage : les noms de
    fichiers dérivent du titre traduit, donc en changer télécharge un jeu
    d'images entièrement différent."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=LANG_OPTIONS,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )

class AvatarExplorerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gestion du flux de configuration pour Avatar Explorer."""
    VERSION = 1

    def __init__(self):
        self._config_data = {}
        self._users = []

    async def async_step_user(self, user_input=None):
        """Étape 1 : Définition du dossier racine des images."""
        if user_input is not None:
            self._config_data.update(user_input)
            return await self.async_step_add_user()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("dir", default=DEFAULT_DIR): str,
            })
        )

    async def async_step_add_user(self, user_input=None):
        """Étape 2 : Ajout d'un utilisateur (Dossier + Bitmoji ID)."""
        if user_input is not None:
            # On utilise l'ID du dossier comme label par défaut pour HA
            user_input["label"] = user_input["user_id_folder"]
            self._users.append(user_input)
            return await self.async_step_choice()

        return self.async_show_form(
            step_id="add_user",
            data_schema=vol.Schema({
                vol.Required("user_id_folder"): str,  # Nom du dossier (ex: Kenny)
                vol.Required("bitmoji_id"): str,  # ID Bitmoji (ex: 103719295927_9-s5)
                vol.Optional("ha_person"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="person")
                ),
            })
        )

    async def async_step_choice(self, user_input=None):
        """Menu pour ajouter un autre utilisateur ou terminer."""
        return self.async_show_menu(
            step_id="choice",
            menu_options=["add_user", "finish"]
        )

    async def async_step_finish(self, user_input=None):
        """Étape intermédiaire : désignation de la paire Duo si besoin."""
        if len(self._users) >= 2:
            return await self.async_step_duo_pair()
        return await self.async_step_settings()

    async def async_step_duo_pair(self, user_input=None):
        """Désignation des deux utilisateurs formant le mode Duo."""
        folder_ids = [u["user_id_folder"] for u in self._users]
        errors = {}

        if user_input is not None:
            if user_input["duo_user1"] == user_input["duo_user2"]:
                errors["duo_user2"] = "duo_same_user"
            else:
                self._config_data["duo_pair"] = [user_input["duo_user1"], user_input["duo_user2"]]
                return await self.async_step_settings()

        return self.async_show_form(
            step_id="duo_pair",
            data_schema=vol.Schema({
                vol.Required("duo_user1"): vol.In(folder_ids),
                vol.Required("duo_user2"): vol.In(folder_ids),
            }),
            errors=errors,
        )

    async def async_step_settings(self, user_input=None):
        """Réglages de synchronisation (intervalle de vérification, qualité)."""
        if user_input is not None:
            self._config_data["users"] = self._users
            return self.async_create_entry(
                title=f"Avatar Explorer ({self._config_data['dir']})",
                data=self._config_data,
                options={
                    CONF_UPDATE_INTERVAL_HOURS: user_input[CONF_UPDATE_INTERVAL_HOURS],
                    CONF_SCALE: user_input[CONF_SCALE],
                    CONF_LANG: user_input[CONF_LANG],
                },
            )

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema({
                vol.Required(CONF_UPDATE_INTERVAL_HOURS, default=DEFAULT_UPDATE_INTERVAL_HOURS): vol.Coerce(int),
                vol.Required(CONF_SCALE, default=str(DEFAULT_SCALE)): _scale_selector(),
                vol.Required(CONF_LANG, default=DEFAULT_LANG): _lang_selector(),
            })
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return AvatarExplorerOptionsFlow()


class AvatarExplorerOptionsFlow(config_entries.OptionsFlow):
    """Modifie l'intervalle, la qualité et les IDs Bitmoji après coup."""

    def _field_for(self, user):
        """Nom du champ de formulaire portant l'ID Bitmoji d'un utilisateur."""
        return f"bitmoji_{user['user_id_folder']}"

    async def async_step_init(self, user_input=None):
        entry = self.config_entry
        users = entry.data.get("users", [])
        errors = {}

        if user_input is not None:
            changed = []
            new_users = []
            for user in users:
                field = self._field_for(user)
                new_id = (user_input.get(field) or "").strip()
                if new_id and not _BITMOJI_RE.match(new_id):
                    errors[field] = "invalid_bitmoji_id"
                if new_id != (user.get("bitmoji_id") or ""):
                    changed.append(user["user_id_folder"])
                new_users.append({**user, "bitmoji_id": new_id})

            if not errors:
                store = self.hass.data.setdefault(DOMAIN, {}).setdefault(
                    entry.entry_id, {}
                )

                if changed:
                    # Les IDs vivent dans data (pas options) : c'est la structure
                    # que lit catalog pour construire les appels export.
                    self.hass.config_entries.async_update_entry(
                        entry, data={**entry.data, "users": new_users}
                    )

                scale_changed = str(user_input[CONF_SCALE]) != _current_scale(entry.options)
                lang_changed = user_input[CONF_LANG] != entry.options.get(
                    CONF_LANG, DEFAULT_LANG
                )

                # ID Bitmoji ou qualité modifiés : les noms de fichiers générés
                # sont identiques, seul leur contenu change. Le différentiel les
                # sauterait tous, il faut donc forcer la réécriture.
                if changed or scale_changed:
                    store["pending_refresh_all"] = True
                # Changer de langue produit au contraire des noms différents
                # (les titres sont traduits) : le différentiel fait correctement
                # son travail, il suffit de déclencher un passage.
                elif lang_changed:
                    store["pending_resync"] = True

                return self.async_create_entry(data={
                    CONF_UPDATE_INTERVAL_HOURS: user_input[CONF_UPDATE_INTERVAL_HOURS],
                    CONF_SCALE: user_input[CONF_SCALE],
                    CONF_LANG: user_input[CONF_LANG],
                })

        schema = {
            vol.Required(
                CONF_UPDATE_INTERVAL_HOURS,
                default=entry.options.get(CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS),
            ): vol.Coerce(int),
            vol.Required(
                CONF_SCALE,
                default=_current_scale(entry.options),
            ): _scale_selector(),
            vol.Required(
                CONF_LANG,
                default=entry.options.get(CONF_LANG, DEFAULT_LANG),
            ): _lang_selector(),
        }
        # Un champ par utilisateur configuré, pré-rempli avec l'ID actuel.
        for user in users:
            schema[
                vol.Optional(
                    self._field_for(user),
                    description={"suggested_value": user.get("bitmoji_id", "")},
                    default="",
                )
            ] = str

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "users": ", ".join(u["user_id_folder"] for u in users) or "aucun"
            },
        )
