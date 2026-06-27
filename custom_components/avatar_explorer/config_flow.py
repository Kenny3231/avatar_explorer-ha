import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import (
    CONF_SCALE,
    CONF_UPDATE_INTERVAL_HOURS,
    DEFAULT_DIR,
    DEFAULT_SCALE,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
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
                },
            )

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema({
                vol.Required(CONF_UPDATE_INTERVAL_HOURS, default=DEFAULT_UPDATE_INTERVAL_HOURS): vol.Coerce(int),
                vol.Required(CONF_SCALE, default=DEFAULT_SCALE): vol.In([1, 2, 4]),
            })
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return AvatarExplorerOptionsFlow()


class AvatarExplorerOptionsFlow(config_entries.OptionsFlow):
    """Permet de modifier l'intervalle de vérification et la qualité après coup."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_UPDATE_INTERVAL_HOURS,
                    default=self.config_entry.options.get(CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS),
                ): vol.Coerce(int),
                vol.Required(
                    CONF_SCALE,
                    default=self.config_entry.options.get(CONF_SCALE, DEFAULT_SCALE),
                ): vol.In([1, 2, 4]),
            })
        )
